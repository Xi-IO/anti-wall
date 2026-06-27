from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
import math
from pathlib import Path

import pandas as pd

from wall.dataset.rounds import RoundData
from wall.domain.player import PlayerFrame
from wall.domain.sound import SoundEffect, resolve_sound_effect_position
from wall.io.table_io import DEFAULT_TABLE_FORMAT, normalize_table_format
from wall.profile import profile_log
from wall.visibility.dataset import MatchDataset


SOUND_EXPOSURE_COLUMNS = [
    "round_id",
    "effect_id",
    "observer_id",
    "source_type",
    "source_id",
    "start_tick",
    "end_tick",
    "sound_class",
    "sound_action",
    "item_name",
    "shot_count",
    "distance_min",
    "distance_at_start",
    "radius",
    "exposure_type",
    "raw_source",
]


@dataclass(frozen=True)
class SoundExposureRow:
    round_id: int
    effect_id: str
    observer_id: str
    source_type: str
    source_id: str
    start_tick: int
    end_tick: int
    sound_class: str
    sound_action: str
    item_name: str
    shot_count: int | None
    distance_min: float
    distance_at_start: float
    radius: float
    exposure_type: str
    raw_source: str


class SoundExposureExportResult:
    def __init__(self, output_path: Path, table: pd.DataFrame) -> None:
        self.output_path = output_path
        self.table = table


@dataclass(frozen=True)
class SoundExposureBatchRoundResult:
    round_id: int
    output_path: Path
    table: pd.DataFrame


@dataclass(frozen=True)
class SoundExposureBatchExportResult:
    round_results: tuple[SoundExposureBatchRoundResult, ...]
    output_path: Path | None = None


@dataclass(frozen=True)
class _SoundExposureWorkerTask:
    worker_index: int
    data_dir: str
    round_ids: tuple[int, ...]
    output_path: str | None
    tick_step: int | None
    tickrate: float
    table_format: str | None
    combine_rounds: bool


@dataclass(frozen=True)
class _SoundExposureWorkerResult:
    worker_index: int
    assigned_round_ids: tuple[int, ...]
    round_results: tuple[SoundExposureBatchRoundResult, ...]


DEFAULT_SOUND_EXPOSURE_TICK_STEPS: dict[tuple[str, str], int] = {
    ("movement", "locomotion"): 16,
    ("movement", "hard_step"): 8,
    ("weapon", "gunfire"): 4,
    ("weapon", "reload"): 4,
    ("weapon", "zoom"): 4,
    ("utility", "detonate"): 4,
    ("utility", "bounce"): 4,
    ("bomb", "dropped"): 1,
    ("bomb", "begin_plant"): 1,
    ("bomb", "begin_defuse"): 1,
    ("bomb", "abort_defuse"): 1,
    ("bomb", "defused"): 1,
    ("bomb", "exploded"): 1,
    ("damage", "hurt"): 4,
}

MOVEMENT_COARSE_STEP = 64
MOVEMENT_FINE_STEP = 16
MOVEMENT_REFINE_MARGIN = 384.0


@dataclass
class _MovementSamplingStats:
    movement_pairs_total: int = 0
    movement_pairs_skipped_by_time: int = 0
    movement_pairs_skipped_by_bbox: int = 0
    movement_pairs_after_prefilter: int = 0
    movement_coarse_samples: int = 0
    movement_candidate_windows: int = 0
    movement_fine_samples: int = 0
    movement_exposures: int = 0


@dataclass(frozen=True)
class _MovementPairSample:
    tick: int
    source_x: float
    source_y: float
    source_z: float
    observer_x: float
    observer_y: float
    observer_z: float


@dataclass(frozen=True)
class _MovementPairData:
    samples: list[_MovementPairSample]
    source_min_x: float
    source_max_x: float
    source_min_y: float
    source_max_y: float
    observer_min_x: float
    observer_max_x: float
    observer_min_y: float
    observer_max_y: float


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "<na>"}:
        return ""
    return text


def _parse_source_id(source_id: str) -> tuple[str | None, str | None]:
    if not source_id:
        return None, None
    if source_id.startswith("name:"):
        return None, source_id.split(":", 1)[1]
    return source_id, None


def _player_key(frame: PlayerFrame) -> str:
    steamid = _clean_text(frame.steamid)
    return steamid or f"name:{frame.name}"


def _distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def _shot_count_or_none(value: object) -> int | None:
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return None
    return int(numeric)


def _resolved_tick_step(effect: SoundEffect, tick_step_override: int | None) -> int:
    if tick_step_override is not None:
        return max(1, int(tick_step_override))
    if effect.emitter_type != "continuous":
        return 1
    by_pair = DEFAULT_SOUND_EXPOSURE_TICK_STEPS.get((effect.sound_class, effect.sound_action))
    if by_pair is not None:
        return max(1, int(by_pair))
    by_class = {
        "movement": 16,
        "weapon": 4,
        "utility": 4,
        "bomb": 1,
        "damage": 4,
    }.get(effect.sound_class)
    if by_class is not None:
        return int(by_class)
    return 8


def _merge_tick_windows(windows: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not windows:
        return []
    ordered = sorted((int(start), int(end)) for start, end in windows if int(end) >= int(start))
    if not ordered:
        return []
    merged: list[tuple[int, int]] = [ordered[0]]
    for start, end in ordered[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end + 1:
            merged[-1] = (prev_start, max(prev_end, end))
            continue
        merged.append((start, end))
    return merged


def _sample_ticks_for_interval(frame_ticks: list[int], *, start_tick: int, end_tick: int, step: int) -> list[int]:
    effective_step = max(1, int(step))
    return [
        int(tick)
        for tick in frame_ticks[::effective_step]
        if int(start_tick) <= int(tick) <= int(end_tick)
    ]


def _bbox_min_distance_2d(
    *,
    source_min_x: float,
    source_max_x: float,
    source_min_y: float,
    source_max_y: float,
    observer_min_x: float,
    observer_max_x: float,
    observer_min_y: float,
    observer_max_y: float,
) -> float:
    dx = max(source_min_x - observer_max_x, observer_min_x - source_max_x, 0.0)
    dy = max(source_min_y - observer_max_y, observer_min_y - source_max_y, 0.0)
    return math.sqrt((dx * dx) + (dy * dy))


def _source_context_for_player_effect(effect: SoundEffect, round_data: RoundData) -> tuple[int | None, str | None]:
    steamid, name = _parse_source_id(effect.source_id)
    frame = round_data.round_players.frame_at(steamid=steamid, name=name, tick=effect.start_tick)
    if frame is None or frame.team_num is None:
        return None, None
    return frame.team_num, _player_key(frame)


def _source_context_for_grenade_effect(effect: SoundEffect, round_data: RoundData) -> tuple[int | None, str | None]:
    if effect.raw_source == "grenade_bounce":
        segments = round_data.utility_timeline.round_grenade_trajectory_segments
        if segments.empty or "grenade_id" not in segments.columns:
            return None, None
        match = segments[segments["grenade_id"].astype("string") == effect.source_id]
        if match.empty:
            return None, None
        row = match.sort_values(["segment_index", "start_tick"]).iloc[0]
        steamid = _clean_text(row.get("thrower_key"))
        name = _clean_text(row.get("thrower"))
        frame = round_data.round_players.frame_at(steamid=steamid or None, name=name or None, tick=effect.start_tick)
        if frame is None or frame.team_num is None:
            return None, None
        return frame.team_num, _player_key(frame)

    table_by_source = {
        "smokegrenade_detonate": round_data.utility_timeline.round_smoke_detonates,
        "flashbang_detonate": round_data.utility_timeline.round_flash_detonates,
        "hegrenade_detonate": round_data.utility_timeline.round_he_detonates,
        "inferno_startburn": round_data.utility_timeline.round_inferno_starts,
    }
    table = table_by_source.get(effect.raw_source)
    if table is None or table.empty:
        return None, None
    matches = table[pd.to_numeric(table.get("tick"), errors="coerce") == int(effect.start_tick)]
    if "entityid" in table.columns and effect.source_id:
        entity_matches = matches[
            pd.to_numeric(matches.get("entityid"), errors="coerce").astype("Int64").astype("string") == effect.source_id
        ]
        if not entity_matches.empty:
            matches = entity_matches
    if matches.empty:
        return None, None
    row = matches.iloc[0]
    steamid = _clean_text(row.get("user_steamid"))
    name = _clean_text(row.get("user_name"))
    frame = round_data.round_players.frame_at(steamid=steamid or None, name=name or None, tick=effect.start_tick)
    if frame is None or frame.team_num is None:
        return None, None
    return frame.team_num, _player_key(frame)


def _source_context_for_bomb_effect(effect: SoundEffect, round_data: RoundData) -> tuple[int | None, str | None]:
    if effect.source_type == "player":
        return _source_context_for_player_effect(effect, round_data)
    if effect.raw_source != "bomb_dropped":
        return None, None
    drops = round_data.bomb_timeline.round_bomb_drops
    if drops.empty:
        return None, None
    matches = drops[pd.to_numeric(drops.get("tick"), errors="coerce") == int(effect.start_tick)]
    if matches.empty:
        return None, None
    row = matches.iloc[0]
    steamid = _clean_text(row.get("user_steamid"))
    name = _clean_text(row.get("user_name"))
    frame = round_data.round_players.frame_at(steamid=steamid or None, name=name or None, tick=effect.start_tick)
    if frame is None or frame.team_num is None:
        return None, None
    return frame.team_num, _player_key(frame)


def _resolve_source_context(effect: SoundEffect, round_data: RoundData) -> tuple[int | None, str | None]:
    if effect.source_type == "player":
        return _source_context_for_player_effect(effect, round_data)
    if effect.source_type == "grenade":
        return _source_context_for_grenade_effect(effect, round_data)
    if effect.sound_class == "bomb":
        return _source_context_for_bomb_effect(effect, round_data)
    return None, None


def _build_row(
    *,
    round_id: int,
    effect: SoundEffect,
    observer_id: str,
    start_tick: int,
    end_tick: int,
    distance_min: float,
    distance_at_start: float,
    exposure_type: str,
) -> SoundExposureRow:
    return SoundExposureRow(
        round_id=int(round_id),
        effect_id=effect.effect_id,
        observer_id=observer_id,
        source_type=effect.source_type,
        source_id=effect.source_id,
        start_tick=int(start_tick),
        end_tick=int(end_tick),
        sound_class=effect.sound_class,
        sound_action=effect.sound_action,
        item_name=effect.item_name,
        shot_count=_shot_count_or_none(getattr(effect, "shot_count", None)),
        distance_min=float(distance_min),
        distance_at_start=float(distance_at_start),
        radius=float(effect.radius),
        exposure_type=exposure_type,
        raw_source=effect.raw_source,
    )


def _continuous_rows_for_observer(
    effect: SoundEffect,
    *,
    round_id: int,
    pair_samples: list[_MovementPairSample],
    tick_step: int,
    observer_id: str,
) -> list[SoundExposureRow]:
    rows: list[SoundExposureRow] = []
    current_start_tick: int | None = None
    current_start_distance: float | None = None
    current_min_distance: float | None = None
    previous_tick: int | None = None

    def _flush(end_tick: int) -> None:
        nonlocal current_start_tick, current_start_distance, current_min_distance
        if current_start_tick is None or current_start_distance is None or current_min_distance is None:
            return
        rows.append(
            _build_row(
                round_id=round_id,
                effect=effect,
                observer_id=observer_id,
                start_tick=current_start_tick,
                end_tick=end_tick,
                distance_min=current_min_distance,
                distance_at_start=current_start_distance,
                exposure_type="heard_interval",
            )
        )
        current_start_tick = None
        current_start_distance = None
        current_min_distance = None

    for sample in pair_samples:
        heard_distance = _distance(
            (sample.source_x, sample.source_y, sample.source_z),
            (sample.observer_x, sample.observer_y, sample.observer_z),
        )
        if heard_distance > effect.radius:
            if previous_tick is not None:
                _flush(previous_tick)
            previous_tick = sample.tick
            continue
        if current_start_tick is None or previous_tick is None or sample.tick != previous_tick + max(1, int(tick_step)):
            if previous_tick is not None and current_start_tick is not None:
                _flush(previous_tick)
            current_start_tick = sample.tick
            current_start_distance = heard_distance
            current_min_distance = heard_distance
        else:
            current_min_distance = min(float(current_min_distance), heard_distance)
        previous_tick = sample.tick

    if previous_tick is not None:
        _flush(previous_tick)
    return rows


def _merge_adjacent_movement_rows(rows: list[SoundExposureRow], *, max_gap_ticks: int) -> list[SoundExposureRow]:
    if len(rows) <= 1:
        return rows
    gap_limit = max(0, int(max_gap_ticks))
    merged: list[SoundExposureRow] = []
    current = rows[0]
    for row in rows[1:]:
        same_series = (
            row.round_id == current.round_id
            and row.effect_id == current.effect_id
            and row.observer_id == current.observer_id
            and row.sound_class == current.sound_class
            and row.sound_action == current.sound_action
            and row.exposure_type == current.exposure_type
        )
        if (not same_series) or int(row.start_tick) - int(current.end_tick) > gap_limit:
            merged.append(current)
            current = row
            continue
        current = SoundExposureRow(
            round_id=current.round_id,
            effect_id=current.effect_id,
            observer_id=current.observer_id,
            source_type=current.source_type,
            source_id=current.source_id,
            start_tick=current.start_tick,
            end_tick=max(int(current.end_tick), int(row.end_tick)),
            sound_class=current.sound_class,
            sound_action=current.sound_action,
            item_name=current.item_name,
            shot_count=current.shot_count,
            distance_min=min(float(current.distance_min), float(row.distance_min)),
            distance_at_start=current.distance_at_start,
            radius=current.radius,
            exposure_type=current.exposure_type,
            raw_source=current.raw_source,
        )
    merged.append(current)
    return merged


def _movement_effect_round_id(effect: SoundEffect, round_data: RoundData) -> int:
    _ = effect
    return int(round_data.round_id)

def _movement_pair_samples(
    effect: SoundEffect,
    *,
    observer_timeline,
    source_timeline,
    round_data: RoundData,
) -> _MovementPairData | None:
    if observer_timeline.frames.empty or source_timeline.frames.empty:
        return None
    if observer_timeline.ticks.size == 0 or source_timeline.ticks.size == 0:
        return None
    observer_frames = observer_timeline.frames
    source_frames = source_timeline.frames
    observer_xs = pd.to_numeric(observer_frames["X"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    observer_ys = pd.to_numeric(observer_frames["Y"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    observer_zs = pd.to_numeric(observer_frames["Z"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    observer_health = pd.to_numeric(observer_frames["health"], errors="coerce").to_numpy(dtype=float)
    observer_alive = (~pd.isna(observer_health)) & (observer_health > 0)
    source_xs = pd.to_numeric(source_frames["X"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    source_ys = pd.to_numeric(source_frames["Y"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    source_zs = pd.to_numeric(source_frames["Z"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    samples: list[_MovementPairSample] = []
    source_min_x: float | None = None
    source_max_x: float | None = None
    source_min_y: float | None = None
    source_max_y: float | None = None
    observer_min_x: float | None = None
    observer_max_x: float | None = None
    observer_min_y: float | None = None
    observer_max_y: float | None = None
    observer_idx = -1
    source_idx = -1
    effect_start = int(effect.start_tick)
    effect_end = int(effect.end_tick)
    for tick in round_data.frame_ticks:
        tick_value = int(tick)
        if tick_value < effect_start:
            continue
        if tick_value > effect_end:
            break
        while observer_idx + 1 < observer_timeline.ticks.size and int(observer_timeline.ticks[observer_idx + 1]) <= tick_value:
            observer_idx += 1
        if observer_idx < 0:
            continue
        if observer_timeline.death_tick is not None and tick_value >= int(observer_timeline.death_tick):
            continue
        if not bool(observer_alive[observer_idx]):
            continue
        while source_idx + 1 < source_timeline.ticks.size and int(source_timeline.ticks[source_idx + 1]) <= tick_value:
            source_idx += 1
        if source_idx < 0:
            continue
        sample = _MovementPairSample(
            tick=tick_value,
            source_x=float(source_xs[source_idx]),
            source_y=float(source_ys[source_idx]),
            source_z=float(source_zs[source_idx]),
            observer_x=float(observer_xs[observer_idx]),
            observer_y=float(observer_ys[observer_idx]),
            observer_z=float(observer_zs[observer_idx]),
        )
        samples.append(sample)
        if source_min_x is None:
            source_min_x = source_max_x = sample.source_x
            source_min_y = source_max_y = sample.source_y
            observer_min_x = observer_max_x = sample.observer_x
            observer_min_y = observer_max_y = sample.observer_y
            continue
        source_min_x = min(float(source_min_x), sample.source_x)
        source_max_x = max(float(source_max_x), sample.source_x)
        source_min_y = min(float(source_min_y), sample.source_y)
        source_max_y = max(float(source_max_y), sample.source_y)
        observer_min_x = min(float(observer_min_x), sample.observer_x)
        observer_max_x = max(float(observer_max_x), sample.observer_x)
        observer_min_y = min(float(observer_min_y), sample.observer_y)
        observer_max_y = max(float(observer_max_y), sample.observer_y)
    if not samples:
        return None
    return _MovementPairData(
        samples=samples,
        source_min_x=float(source_min_x),
        source_max_x=float(source_max_x),
        source_min_y=float(source_min_y),
        source_max_y=float(source_max_y),
        observer_min_x=float(observer_min_x),
        observer_max_x=float(observer_max_x),
        observer_min_y=float(observer_min_y),
        observer_max_y=float(observer_max_y),
    )


def _movement_pair_survives_bbox_prefilter(
    effect: SoundEffect,
    *,
    pair_data: _MovementPairData,
) -> bool:
    bbox_min_distance = _bbox_min_distance_2d(
        source_min_x=pair_data.source_min_x,
        source_max_x=pair_data.source_max_x,
        source_min_y=pair_data.source_min_y,
        source_max_y=pair_data.source_max_y,
        observer_min_x=pair_data.observer_min_x,
        observer_max_x=pair_data.observer_max_x,
        observer_min_y=pair_data.observer_min_y,
        observer_max_y=pair_data.observer_max_y,
    )
    return bbox_min_distance <= float(effect.radius) + float(MOVEMENT_REFINE_MARGIN)


def _movement_candidate_windows(
    effect: SoundEffect,
    *,
    pair_samples: list[_MovementPairSample],
    stats: _MovementSamplingStats | None,
) -> list[tuple[int, int]]:
    if not pair_samples:
        return []
    coarse_ticks = _sample_ticks_for_interval(
        [sample.tick for sample in pair_samples],
        start_tick=pair_samples[0].tick,
        end_tick=pair_samples[-1].tick,
        step=MOVEMENT_COARSE_STEP,
    )
    if pair_samples[-1].tick not in coarse_ticks:
        coarse_ticks.append(pair_samples[-1].tick)
    sample_by_tick = {sample.tick: sample for sample in pair_samples}
    candidate_windows: list[tuple[int, int]] = []
    interval_start = int(pair_samples[0].tick)
    interval_end = int(pair_samples[-1].tick)
    for tick in coarse_ticks:
        if stats is not None:
            stats.movement_coarse_samples += 1
        sample = sample_by_tick.get(int(tick))
        if sample is None:
            continue
        heard_distance = _distance(
            (sample.source_x, sample.source_y, sample.source_z),
            (sample.observer_x, sample.observer_y, sample.observer_z),
        )
        if heard_distance > effect.radius + MOVEMENT_REFINE_MARGIN:
            continue
        candidate_windows.append(
            (
                max(interval_start, int(tick) - MOVEMENT_COARSE_STEP),
                min(interval_end, int(tick) + MOVEMENT_COARSE_STEP),
            )
        )
    merged = _merge_tick_windows(candidate_windows)
    if stats is not None:
        stats.movement_candidate_windows += len(merged)
    return merged


def _movement_rows_for_observer(
    effect: SoundEffect,
    *,
    observer_id: str,
    observer_timeline,
    source_timeline,
    round_data: RoundData,
    stats: _MovementSamplingStats | None,
    tick_step_override: int | None,
) -> list[SoundExposureRow]:
    if stats is not None:
        stats.movement_pairs_total += 1
    pair_data = _movement_pair_samples(
        effect,
        observer_timeline=observer_timeline,
        source_timeline=source_timeline,
        round_data=round_data,
    )
    if pair_data is None:
        if stats is not None:
            stats.movement_pairs_skipped_by_time += 1
        return []
    if not _movement_pair_survives_bbox_prefilter(effect, pair_data=pair_data):
        if stats is not None:
            stats.movement_pairs_skipped_by_bbox += 1
        return []
    if stats is not None:
        stats.movement_pairs_after_prefilter += 1
    pair_samples = pair_data.samples
    if tick_step_override is not None:
        uniform_ticks = _sample_ticks_for_interval(
            [sample.tick for sample in pair_samples],
            start_tick=pair_samples[0].tick,
            end_tick=pair_samples[-1].tick,
            step=max(1, int(tick_step_override)),
        )
        if pair_samples[-1].tick not in uniform_ticks:
            uniform_ticks.append(pair_samples[-1].tick)
        selected_ticks = set(int(tick) for tick in uniform_ticks)
        sampled_pairs = [sample for sample in pair_samples if sample.tick in selected_ticks]
        if stats is not None:
            stats.movement_fine_samples += len(sampled_pairs)
        rows = _continuous_rows_for_observer(
            effect,
            round_id=_movement_effect_round_id(effect, round_data),
            pair_samples=sampled_pairs,
            tick_step=max(1, int(tick_step_override)),
            observer_id=observer_id,
        )
        rows = _merge_adjacent_movement_rows(rows, max_gap_ticks=max(1, int(tick_step_override)))
    else:
        candidate_windows = _movement_candidate_windows(
            effect,
            pair_samples=pair_samples,
            stats=stats,
        )
        if not candidate_windows:
            return []
        fine_ticks: list[int] = []
        effective_ticks = [sample.tick for sample in pair_samples]
        for start_tick, end_tick in candidate_windows:
            sampled = _sample_ticks_for_interval(
                effective_ticks,
                start_tick=start_tick,
                end_tick=end_tick,
                step=MOVEMENT_FINE_STEP,
            )
            if end_tick not in sampled and end_tick in effective_ticks:
                sampled.append(end_tick)
            fine_ticks.extend(sampled)
        fine_tick_set = set(int(tick) for tick in fine_ticks)
        sampled_pairs = [sample for sample in pair_samples if sample.tick in fine_tick_set]
        if stats is not None:
            stats.movement_fine_samples += len(sampled_pairs)
        rows = _continuous_rows_for_observer(
            effect,
            round_id=_movement_effect_round_id(effect, round_data),
            pair_samples=sampled_pairs,
            tick_step=MOVEMENT_FINE_STEP,
            observer_id=observer_id,
        )
        rows = _merge_adjacent_movement_rows(rows, max_gap_ticks=MOVEMENT_FINE_STEP)
    if stats is not None:
        stats.movement_exposures += len(rows)
    return rows


def _effect_rows(
    effect: SoundEffect,
    round_data: RoundData,
    *,
    tick_step: int | None,
    movement_stats: _MovementSamplingStats | None = None,
) -> list[SoundExposureRow]:
    source_team_num, source_player_key = _resolve_source_context(effect, round_data)
    if source_team_num is None:
        return []
    rows: list[SoundExposureRow] = []
    for observer_timeline in round_data.round_players.players_by_steamid.values():
        observer_name = observer_timeline.display_name
        observer_steamid = observer_timeline.steamid
        observer_frame = round_data.round_players.frame_at(
            steamid=observer_steamid or None,
            name=observer_name or None,
            tick=effect.start_tick,
        )
        if observer_frame is None or observer_frame.team_num is None or observer_frame.team_num == source_team_num:
            continue
        observer_id = _player_key(observer_frame)
        if source_player_key is not None and observer_id == source_player_key:
            continue
        if effect.emitter_type == "impulse":
            if not observer_frame.is_alive:
                continue
            effect_position = resolve_sound_effect_position(effect, tick=effect.start_tick, round_players=round_data.round_players)
            if effect_position is None:
                continue
            observer_position = (observer_frame.x, observer_frame.y, observer_frame.z)
            heard_distance = _distance(effect_position, observer_position)
            if heard_distance > effect.radius:
                continue
            rows.append(
                _build_row(
                    round_id=round_data.round_id,
                    effect=effect,
                    observer_id=observer_id,
                    start_tick=effect.start_tick,
                    end_tick=effect.start_tick,
                    distance_min=heard_distance,
                    distance_at_start=heard_distance,
                    exposure_type="heard_impulse",
                )
            )
            continue
        if effect.sound_class == "movement" and effect.sound_action == "locomotion":
            source_steamid, source_name = _parse_source_id(effect.source_id)
            source_timeline = (
                round_data.round_players.get_by_steamid(source_steamid)
                if source_steamid
                else round_data.round_players.get_by_name(source_name)
            )
            if source_timeline is None:
                continue
            rows.extend(
                _movement_rows_for_observer(
                    effect,
                    observer_id=observer_id,
                    observer_timeline=observer_timeline,
                    source_timeline=source_timeline,
                    round_data=round_data,
                    stats=movement_stats,
                    tick_step_override=tick_step,
                )
            )
            continue

        effective_step = _resolved_tick_step(effect, tick_step)
        frame_ticks = _sample_ticks_for_interval(
            round_data.frame_ticks,
            start_tick=effect.start_tick,
            end_tick=effect.end_tick,
            step=effective_step,
        )
        if not frame_ticks:
            continue
        rows.extend(
            _continuous_rows_for_observer(
                effect,
                round_id=int(round_data.round_id),
                pair_samples=[
                    _MovementPairSample(
                        tick=int(tick),
                        source_x=float(position[0]),
                        source_y=float(position[1]),
                        source_z=float(position[2]),
                        observer_x=float(observer_frame_tick.x),
                        observer_y=float(observer_frame_tick.y),
                        observer_z=float(observer_frame_tick.z),
                    )
                    for tick in frame_ticks
                    for observer_frame_tick in [observer_timeline.frame_at(int(tick))]
                    for position in [resolve_sound_effect_position(effect, tick=int(tick), round_players=round_data.round_players)]
                    if observer_frame_tick is not None and observer_frame_tick.is_alive and position is not None
                ],
                tick_step=effective_step,
                observer_id=observer_id,
            )
        )
    return rows


def _table_from_rows(rows: list[SoundExposureRow], *, round_id: int) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=SOUND_EXPOSURE_COLUMNS)
    table = pd.DataFrame([asdict(row) for row in rows])
    table = table.sort_values(
        ["round_id", "observer_id", "start_tick", "end_tick", "effect_id", "source_type", "source_id"]
    ).reset_index(drop=True)
    return table.loc[:, SOUND_EXPOSURE_COLUMNS]


def build_sound_exposure_table(round_data: RoundData, *, tick_step: int | None = None) -> pd.DataFrame:
    movement_stats = _MovementSamplingStats()
    rows: list[SoundExposureRow] = []
    for effect in round_data.sound_timeline.effects:
        rows.extend(
            _effect_rows(
                effect,
                round_data,
                tick_step=tick_step,
                movement_stats=movement_stats,
            )
        )
    profile_log(
        "sound_exposure.movement_sampling",
        round_id=round_data.round_id,
        note=(
            f"movement_pairs_total={movement_stats.movement_pairs_total} "
            f"movement_pairs_skipped_by_time={movement_stats.movement_pairs_skipped_by_time} "
            f"movement_pairs_skipped_by_bbox={movement_stats.movement_pairs_skipped_by_bbox} "
            f"movement_pairs_after_prefilter={movement_stats.movement_pairs_after_prefilter} "
            f"movement_coarse_samples={movement_stats.movement_coarse_samples} "
            f"movement_candidate_windows={movement_stats.movement_candidate_windows} "
            f"movement_fine_samples={movement_stats.movement_fine_samples} "
            f"movement_exposures={movement_stats.movement_exposures}"
        ),
    )
    return _table_from_rows(rows, round_id=int(round_data.round_id))


def _default_output_path(
    data_dir: Path,
    *,
    round_id: int | None,
    output_format: str,
) -> Path:
    suffix = ".parquet" if output_format == "parquet" else ".csv"
    if round_id is None:
        return data_dir / f"sound_exposure{suffix}"
    return data_dir / f"sound_exposure_round_{int(round_id):02d}{suffix}"


def _write_table(table: pd.DataFrame, output_path: Path, *, output_format: str) -> None:
    if output_format == "parquet":
        table.to_parquet(output_path, index=False)
    else:
        table.to_csv(output_path, index=False)


def _concat_tables(tables: list[pd.DataFrame]) -> pd.DataFrame:
    if not tables:
        return pd.DataFrame()
    if len(tables) == 1:
        return tables[0].reset_index(drop=True)
    return pd.concat(tables, ignore_index=True)


def _chunk_round_ids(round_ids: list[int], jobs: int) -> list[tuple[int, ...]]:
    if not round_ids:
        return []
    worker_count = max(1, min(int(jobs), len(round_ids)))
    chunks: list[list[int]] = [[] for _ in range(worker_count)]
    for index, round_id in enumerate(round_ids):
        chunks[index % worker_count].append(int(round_id))
    return [tuple(chunk) for chunk in chunks if chunk]


def run_sound_exposure_export(
    data_dir: Path,
    *,
    round_id: int,
    output_path: Path | None = None,
    tick_step: int | None = None,
    tickrate: float = 64.0,
    table_format: str | None = None,
    dataset: MatchDataset | None = None,
    write_output: bool = True,
) -> SoundExposureExportResult:
    loaded_dataset = MatchDataset.from_data_dir(data_dir) if dataset is None else dataset
    round_data = loaded_dataset.build_round_data(
        int(round_id),
        tickrate=tickrate,
        include_visibility_context=False,
    )
    table = build_sound_exposure_table(round_data, tick_step=tick_step)
    output_format = normalize_table_format(table_format or DEFAULT_TABLE_FORMAT)
    target_path = Path(output_path) if output_path is not None else _default_output_path(
        data_dir,
        round_id=int(round_id),
        output_format=output_format,
    )
    if write_output:
        _write_table(table, target_path, output_format=output_format)
    return SoundExposureExportResult(target_path, table)


def _run_sound_exposure_worker_task(task: _SoundExposureWorkerTask) -> _SoundExposureWorkerResult:
    data_dir = Path(task.data_dir)
    dataset = MatchDataset.from_data_dir(data_dir)
    round_results: list[SoundExposureBatchRoundResult] = []
    for round_id in task.round_ids:
        result = run_sound_exposure_export(
            data_dir,
            round_id=int(round_id),
            output_path=None if task.output_path is None else Path(task.output_path),
            tick_step=task.tick_step,
            tickrate=task.tickrate,
            table_format=task.table_format,
            dataset=dataset,
            write_output=not task.combine_rounds,
        )
        round_results.append(
            SoundExposureBatchRoundResult(
                round_id=int(round_id),
                output_path=result.output_path,
                table=result.table,
            )
        )
    return _SoundExposureWorkerResult(
        worker_index=task.worker_index,
        assigned_round_ids=task.round_ids,
        round_results=tuple(round_results),
    )


def run_sound_exposure_exports(
    data_dir: Path,
    *,
    round_ids: list[int],
    output_path: Path | None = None,
    tick_step: int | None = None,
    tickrate: float = 64.0,
    table_format: str | None = None,
    dataset: MatchDataset | None = None,
    combine_rounds: bool = True,
    jobs: int = 4,
) -> SoundExposureBatchExportResult:
    resolved_jobs = max(1, int(jobs))
    output_format = normalize_table_format(table_format or DEFAULT_TABLE_FORMAT)
    if resolved_jobs == 1:
        loaded_dataset = MatchDataset.from_data_dir(data_dir) if dataset is None else dataset
        round_results: list[SoundExposureBatchRoundResult] = []
        for round_id in round_ids:
            result = run_sound_exposure_export(
                data_dir,
                round_id=int(round_id),
                output_path=output_path if (not combine_rounds and len(round_ids) == 1) else None,
                tick_step=tick_step,
                tickrate=tickrate,
                table_format=output_format,
                dataset=loaded_dataset,
                write_output=not combine_rounds,
            )
            round_results.append(
                SoundExposureBatchRoundResult(
                    round_id=int(round_id),
                    output_path=result.output_path,
                    table=result.table,
                )
            )
    else:
        chunks = _chunk_round_ids(round_ids, resolved_jobs)
        with ProcessPoolExecutor(max_workers=len(chunks)) as executor:
            future_to_task = {
                executor.submit(
                    _run_sound_exposure_worker_task,
                    _SoundExposureWorkerTask(
                        worker_index=worker_index,
                        data_dir=str(data_dir),
                        round_ids=chunk,
                        output_path=None if output_path is None else str(output_path),
                        tick_step=tick_step,
                        tickrate=tickrate,
                        table_format=output_format,
                        combine_rounds=combine_rounds,
                    ),
                ): chunk
                for worker_index, chunk in enumerate(chunks)
            }
            round_results = []
            for future in as_completed(future_to_task):
                worker_result = future.result()
                round_results.extend(worker_result.round_results)
        round_results = sorted(round_results, key=lambda result: result.round_id)
    if not combine_rounds:
        return SoundExposureBatchExportResult(round_results=tuple(round_results), output_path=None)
    combined = _concat_tables([result.table for result in round_results])
    combined_path = Path(output_path) if output_path is not None else _default_output_path(
        data_dir,
        round_id=None,
        output_format=output_format,
    )
    _write_table(combined, combined_path, output_format=output_format)
    return SoundExposureBatchExportResult(round_results=tuple(round_results), output_path=combined_path)
