from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any

import pandas as pd

from wall.io.table_io import DEFAULT_TABLE_FORMAT, normalize_table_format, read_table_with_fallback
from wall.profile import profile_log, profile_note
from wall.sound.feed import (
    HARD_STEP_DEDUPE_WINDOW_TICKS,
    MIN_MOVEMENT_FEED_DURATION_TICKS,
    MOVEMENT_FEED_MERGE_GAP_TICKS,
    format_sound_exposure_message,
    is_sound_exposure_feed_candidate,
    sound_feed_priority,
)

try:
    import pyarrow.parquet as pq
except ModuleNotFoundError:
    pq = None
try:
    import pyarrow.lib as pa_lib
except ModuleNotFoundError:
    pa_lib = None


VISIBILITY_EVENT_KIND = "visibility_spotted"
SOUND_EVENT_KIND = "sound_heard"
VISIBILITY_REDISCOVERY_GAP_SECONDS = 2.0
UNSUPPORTED_VISIBILITY_SCHEMA_MESSAGE = (
    "visibility.parquet uses an unsupported visibility schema. "
    "Re-run `wall visibility <dataset_dir>` to generate the interval visibility artifact."
)
UNSUPPORTED_SOUND_EXPOSURE_SCHEMA_MESSAGE = (
    "sound_exposure.parquet uses an unsupported schema. "
    "Re-run `wall sound-exposure <dataset_dir>` to generate the observer-specific sound artifact."
)

SOUND_EXPOSURE_SOFT_FAILURES: tuple[type[BaseException], ...] = tuple(
    failure_type
    for failure_type in (
        ValueError,
        TypeError,
        OSError,
        FileNotFoundError,
        None if pa_lib is None else getattr(pa_lib, "ArrowException", None),
    )
    if failure_type is not None
)


@dataclass(frozen=True)
class InfoEvent:
    round_id: int
    tick: int
    seconds: float
    kind: str
    observer: str
    target: str
    message: str
    observer_key: str = ""
    target_key: str = ""


@dataclass(frozen=True)
class SoundFeedBuildStats:
    sound_exposure_rows_loaded: int = 0
    sound_info_events_generated: int = 0
    sound_movement_exposures_merged: int = 0
    sound_movement_exposures_dropped_short: int = 0
    sound_hard_step_events_deduped: int = 0
    sound_info_events_by_class: tuple[tuple[str, int], ...] = ()
    sound_exposure_rows_by_class_action: tuple[tuple[str, int], ...] = ()
    sound_info_events_by_class_action: tuple[tuple[str, int], ...] = ()
    sound_info_events_dropped_by_class_action: tuple[tuple[str, int], ...] = ()


INFO_FEED_AUDIT_COLUMNS = [
    "round_id",
    "tick",
    "priority",
    "event_class",
    "event_type",
    "observer_id",
    "observer_name",
    "source_id",
    "source_name",
    "sound_class",
    "sound_action",
    "message",
]


@dataclass(frozen=True)
class VisibilityIntervalSchema:
    round_id_column: str
    observer_column: str
    target_column: str
    observer_key_column: str | None
    target_key_column: str | None
    start_tick_column: str
    end_tick_column: str
    start_seconds_column: str | None
    end_seconds_column: str | None
    is_visible_column: str | None
    state_column: str | None

    @property
    def projected_columns(self) -> list[str]:
        columns = [
            self.round_id_column,
            self.observer_column,
            self.target_column,
            self.start_tick_column,
            self.end_tick_column,
        ]
        if self.observer_key_column is not None:
            columns.append(self.observer_key_column)
        if self.target_key_column is not None:
            columns.append(self.target_key_column)
        if self.start_seconds_column is not None:
            columns.append(self.start_seconds_column)
        if self.end_seconds_column is not None:
            columns.append(self.end_seconds_column)
        if self.is_visible_column is not None:
            columns.append(self.is_visible_column)
        if self.state_column is not None:
            columns.append(self.state_column)
        return list(dict.fromkeys(columns))


@dataclass(frozen=True)
class SoundExposureSchema:
    round_id_column: str
    effect_id_column: str
    observer_id_column: str
    source_type_column: str
    source_id_column: str
    start_tick_column: str
    end_tick_column: str
    sound_class_column: str
    sound_action_column: str
    item_name_column: str | None
    shot_count_column: str | None
    raw_source_column: str | None

    @property
    def projected_columns(self) -> list[str]:
        columns = [
            self.round_id_column,
            self.effect_id_column,
            self.observer_id_column,
            self.source_type_column,
            self.source_id_column,
            self.start_tick_column,
            self.end_tick_column,
            self.sound_class_column,
            self.sound_action_column,
        ]
        if self.item_name_column is not None:
            columns.append(self.item_name_column)
        if self.shot_count_column is not None:
            columns.append(self.shot_count_column)
        if self.raw_source_column is not None:
            columns.append(self.raw_source_column)
        return list(dict.fromkeys(columns))


def _pick_first(columns: set[str], candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def _coerce_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "<na>"}:
        return ""
    return text


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = _coerce_text(value).lower()
    if text in {"true", "t", "1", "yes", "y"}:
        return True
    if text in {"false", "f", "0", "no", "n"}:
        return False
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.notna(numeric):
        return bool(int(numeric))
    return bool(value)


def _normalize_player_key(value: object, display_value: object) -> str:
    key = _coerce_text(value)
    return key or _coerce_text(display_value)


def _visibility_artifact_path(loaded_data: Any) -> Path:
    return Path(getattr(loaded_data, "data_dir")) / "visibility.parquet"


def _sound_exposure_artifact_path(loaded_data: Any) -> Path:
    return Path(getattr(loaded_data, "data_dir")) / "sound_exposure.parquet"


def _visibility_artifact_columns(artifact_path: Path) -> list[str] | None:
    if pq is None:
        return None
    return list(pq.ParquetFile(artifact_path).schema.names)


def _profile_info_events_stage(
    stage: str,
    *,
    started_at: float | None = None,
    round_id: int | None = None,
    rows_before: int | None = None,
    rows_after: int | None = None,
    events_count: int | None = None,
    selected_columns: list[str] | tuple[str, ...] | str | None = None,
    extra_note: str | None = None,
) -> None:
    if isinstance(selected_columns, (list, tuple)):
        selected_columns_text = ",".join(str(column) for column in selected_columns)
    else:
        selected_columns_text = selected_columns
    profile_log(
        stage,
        started_at=started_at,
        round_id=round_id,
        note=profile_note(
            f"rows_before={rows_before}" if rows_before is not None else None,
            f"rows_after={rows_after}" if rows_after is not None else None,
            f"events_count={events_count}" if events_count is not None else None,
            f"selected_columns={selected_columns_text}" if selected_columns_text is not None else None,
            extra_note,
        ),
    )


def validate_visibility_interval_schema(columns: list[str]) -> None:
    column_set = set(columns)
    has_old_pair_shape = "tick" in column_set and "is_visible" in column_set and (
        "start_tick" not in column_set or "end_tick" not in column_set
    )
    required_base = {"round_id", "observer", "target", "start_tick", "end_tick"}
    has_state_signal = "is_visible" in column_set or "state" in column_set
    if has_old_pair_shape or not required_base.issubset(column_set) or not has_state_signal:
        raise ValueError(UNSUPPORTED_VISIBILITY_SCHEMA_MESSAGE)


def resolve_visibility_interval_schema(columns: list[str]) -> VisibilityIntervalSchema:
    validate_started_at = time.perf_counter()
    _profile_info_events_stage(
        "viewer.info_events.visibility_schema_validate.start",
        selected_columns=columns,
    )
    validate_visibility_interval_schema(columns)
    column_set = set(columns)
    schema = VisibilityIntervalSchema(
        round_id_column="round_id",
        observer_column="observer",
        target_column="target",
        observer_key_column=_pick_first(column_set, ("observer_key", "observer_steamid")),
        target_key_column=_pick_first(column_set, ("target_key", "target_steamid")),
        start_tick_column="start_tick",
        end_tick_column="end_tick",
        start_seconds_column=_pick_first(column_set, ("start_seconds",)),
        end_seconds_column=_pick_first(column_set, ("end_seconds",)),
        is_visible_column=_pick_first(column_set, ("is_visible",)),
        state_column=_pick_first(column_set, ("state",)),
    )
    _profile_info_events_stage(
        "viewer.info_events.visibility_schema_validate.end",
        started_at=validate_started_at,
        selected_columns=schema.projected_columns,
    )
    return schema


def validate_sound_exposure_schema(columns: list[str]) -> None:
    required = {
        "round_id",
        "effect_id",
        "observer_id",
        "source_type",
        "source_id",
        "start_tick",
        "end_tick",
        "sound_class",
        "sound_action",
    }
    if not required.issubset(set(columns)):
        raise ValueError(UNSUPPORTED_SOUND_EXPOSURE_SCHEMA_MESSAGE)


def resolve_sound_exposure_schema(columns: list[str]) -> SoundExposureSchema:
    validate_sound_exposure_schema(columns)
    column_set = set(columns)
    return SoundExposureSchema(
        round_id_column="round_id",
        effect_id_column="effect_id",
        observer_id_column="observer_id",
        source_type_column="source_type",
        source_id_column="source_id",
        start_tick_column="start_tick",
        end_tick_column="end_tick",
        sound_class_column="sound_class",
        sound_action_column="sound_action",
        item_name_column=_pick_first(column_set, ("item_name",)),
        shot_count_column=_pick_first(column_set, ("shot_count",)),
        raw_source_column=_pick_first(column_set, ("raw_source",)),
    )


def _round_start_ticks(inferred_rounds: pd.DataFrame) -> dict[int, int]:
    if inferred_rounds.empty or "inferred_round_id" not in inferred_rounds.columns or "start_tick" not in inferred_rounds.columns:
        return {}
    work = inferred_rounds.loc[:, ["inferred_round_id", "start_tick"]].copy()
    work["inferred_round_id"] = pd.to_numeric(work["inferred_round_id"], errors="coerce")
    work["start_tick"] = pd.to_numeric(work["start_tick"], errors="coerce")
    work = work.dropna(subset=["inferred_round_id", "start_tick"])
    return {int(row["inferred_round_id"]): int(row["start_tick"]) for _, row in work.iterrows()}


def _derived_seconds(round_id: int, tick: int, *, start_ticks: dict[int, int], tickrate: float) -> float:
    effective_tickrate = tickrate if tickrate > 0 else 64.0
    round_start_tick = start_ticks.get(int(round_id), int(tick))
    return (float(tick) - float(round_start_tick)) / effective_tickrate


def _load_visibility_rows_for_dataset(
    loaded_data: Any,
    *,
    round_id: int | None,
) -> tuple[pd.DataFrame, VisibilityIntervalSchema | None]:
    resolve_started_at = time.perf_counter()
    _profile_info_events_stage("info_events.visibility_artifact.resolve.start", round_id=round_id)
    artifact_path = _visibility_artifact_path(loaded_data)
    _profile_info_events_stage(
        "info_events.visibility_artifact.resolve.end",
        started_at=resolve_started_at,
        round_id=round_id,
        extra_note=f"artifact_path={artifact_path} exists={artifact_path.exists()}",
    )
    if not artifact_path.exists():
        return pd.DataFrame(), None
    artifact_columns = _visibility_artifact_columns(artifact_path)
    if artifact_columns is None:
        full_table = pd.read_parquet(artifact_path)
        schema = resolve_visibility_interval_schema(list(full_table.columns))
        visibility_table = full_table.loc[:, schema.projected_columns].copy()
    else:
        schema = resolve_visibility_interval_schema(artifact_columns)
        read_started_at = time.perf_counter()
        _profile_info_events_stage(
            "viewer.info_events.load_interval_visibility.start",
            round_id=round_id,
            selected_columns=schema.projected_columns,
        )
        visibility_table = pd.read_parquet(artifact_path, columns=schema.projected_columns)
        _profile_info_events_stage(
            "viewer.info_events.load_interval_visibility.end",
            started_at=read_started_at,
            round_id=round_id,
            rows_after=len(visibility_table),
            selected_columns=schema.projected_columns,
        )
    pre_filter_rows = len(visibility_table)
    if round_id is not None:
        round_ids = pd.to_numeric(visibility_table[schema.round_id_column], errors="coerce")
        visibility_table = visibility_table.loc[round_ids == int(round_id)].copy()
    _profile_info_events_stage(
        "info_events.filter_round.end",
        round_id=round_id,
        rows_before=pre_filter_rows,
        rows_after=len(visibility_table),
        selected_columns=schema.projected_columns,
    )
    return visibility_table, schema


def _load_sound_exposure_rows_for_dataset(
    loaded_data: Any,
    *,
    round_id: int | None,
) -> tuple[pd.DataFrame, SoundExposureSchema | None]:
    artifact_path = _sound_exposure_artifact_path(loaded_data)
    if not artifact_path.exists():
        return pd.DataFrame(), None
    try:
        artifact_columns = _visibility_artifact_columns(artifact_path)
        if artifact_columns is None:
            full_table = pd.read_parquet(artifact_path)
            schema = resolve_sound_exposure_schema(list(full_table.columns))
            sound_table = full_table.loc[:, schema.projected_columns].copy()
        else:
            schema = resolve_sound_exposure_schema(artifact_columns)
            sound_table = pd.read_parquet(artifact_path, columns=schema.projected_columns)
        if round_id is not None:
            round_ids = pd.to_numeric(sound_table[schema.round_id_column], errors="coerce")
            sound_table = sound_table.loc[round_ids == int(round_id)].copy()
        return sound_table, schema
    except SOUND_EXPOSURE_SOFT_FAILURES as exc:
        _profile_info_events_stage(
            "info_events.sound_exposure_ignored",
            round_id=round_id,
            extra_note=profile_note(
                f"artifact_path={artifact_path}",
                f"reason={type(exc).__name__}: {exc}",
            ),
        )
        return pd.DataFrame(), None


def _decode_visibility_intervals(
    visibility_table: pd.DataFrame,
    *,
    schema: VisibilityIntervalSchema,
    inferred_rounds: pd.DataFrame,
    tickrate: float,
) -> pd.DataFrame:
    if visibility_table.empty:
        return pd.DataFrame(
            columns=[
                "round_id",
                "observer",
                "target",
                "observer_key",
                "target_key",
                "start_tick",
                "end_tick",
                "start_seconds",
                "end_seconds",
                "is_visible",
                "state",
            ]
        )
    start_ticks = _round_start_ticks(inferred_rounds)
    work = visibility_table.loc[:, schema.projected_columns].copy()
    work["round_id"] = pd.to_numeric(work[schema.round_id_column], errors="coerce")
    work["start_tick"] = pd.to_numeric(work[schema.start_tick_column], errors="coerce")
    work["end_tick"] = pd.to_numeric(work[schema.end_tick_column], errors="coerce")
    work["observer"] = work[schema.observer_column].map(_coerce_text)
    work["target"] = work[schema.target_column].map(_coerce_text)
    work["observer_key"] = (
        work[schema.observer_key_column].map(_coerce_text)
        if schema.observer_key_column is not None
        else work["observer"].map(_coerce_text)
    )
    work["target_key"] = (
        work[schema.target_key_column].map(_coerce_text)
        if schema.target_key_column is not None
        else work["target"].map(_coerce_text)
    )
    if schema.start_seconds_column is not None:
        work["start_seconds"] = pd.to_numeric(work[schema.start_seconds_column], errors="coerce")
    else:
        work["start_seconds"] = pd.Series([float("nan")] * len(work), index=work.index, dtype="float64")
    if schema.end_seconds_column is not None:
        work["end_seconds"] = pd.to_numeric(work[schema.end_seconds_column], errors="coerce")
    else:
        work["end_seconds"] = pd.Series([float("nan")] * len(work), index=work.index, dtype="float64")
    if schema.is_visible_column is not None:
        work["is_visible"] = work[schema.is_visible_column].map(_coerce_bool)
    else:
        work["is_visible"] = False
    work["state"] = "" if schema.state_column is None else work[schema.state_column].map(_coerce_text)
    work = work.dropna(subset=["round_id", "start_tick", "end_tick"])
    work = work[(work["observer"] != "") & (work["target"] != "")]
    work["observer_key"] = [
        _normalize_player_key(key_value, display_value)
        for key_value, display_value in zip(work["observer_key"].tolist(), work["observer"].tolist())
    ]
    work["target_key"] = [
        _normalize_player_key(key_value, display_value)
        for key_value, display_value in zip(work["target_key"].tolist(), work["target"].tolist())
    ]
    missing_start = work["start_seconds"].isna()
    work.loc[missing_start, "start_seconds"] = [
        _derived_seconds(int(round_id), int(start_tick), start_ticks=start_ticks, tickrate=tickrate)
        for round_id, start_tick in zip(work.loc[missing_start, "round_id"], work.loc[missing_start, "start_tick"])
    ]
    missing_end = work["end_seconds"].isna()
    work.loc[missing_end, "end_seconds"] = [
        _derived_seconds(int(round_id), int(end_tick), start_ticks=start_ticks, tickrate=tickrate)
        for round_id, end_tick in zip(work.loc[missing_end, "round_id"], work.loc[missing_end, "end_tick"])
    ]
    return work.loc[
        :,
        [
            "round_id",
            "observer",
            "target",
            "observer_key",
            "target_key",
            "start_tick",
            "end_tick",
            "start_seconds",
            "end_seconds",
            "is_visible",
            "state",
        ],
    ]


def format_info_event_line(event: InfoEvent) -> str:
    if event.message:
        return event.message
    return f"{event.seconds:.2f}s  {event.observer} spotted {event.target}"


def _make_info_event(
    *,
    round_id: int,
    tick: int,
    seconds: float,
    observer: str,
    target: str,
    observer_key: str,
    target_key: str,
) -> InfoEvent:
    return InfoEvent(
        round_id=round_id,
        tick=tick,
        seconds=seconds,
        kind=VISIBILITY_EVENT_KIND,
        observer=observer,
        target=target,
        message="",
        observer_key=observer_key,
        target_key=target_key,
    )


def build_visibility_spotted_events(decoded_rows: pd.DataFrame) -> list[InfoEvent]:
    if decoded_rows.empty:
        return []
    work = decoded_rows.copy()
    work["visible_now"] = (
        work["state"].map(_coerce_text).str.upper().eq("VISIBLE")
        | work["is_visible"].map(_coerce_bool)
    )
    work = work[work["visible_now"]].copy()
    if work.empty:
        return []
    work = work.sort_values(["round_id", "observer_key", "target_key", "start_tick"]).reset_index(drop=True)
    events: list[InfoEvent] = []
    last_visible_window: dict[tuple[int, str, str], float] = {}
    for row in work.to_dict("records"):
        round_id = int(row["round_id"])
        observer = str(row["observer"])
        target = str(row["target"])
        observer_key = _normalize_player_key(row.get("observer_key"), observer)
        target_key = _normalize_player_key(row.get("target_key"), target)
        start_tick = int(row["start_tick"])
        start_seconds = float(row["start_seconds"])
        end_seconds = float(row["end_seconds"])
        key = (round_id, observer_key, target_key)
        previous_end_seconds = last_visible_window.get(key)
        should_emit = previous_end_seconds is None or (start_seconds - previous_end_seconds) >= VISIBILITY_REDISCOVERY_GAP_SECONDS
        if should_emit:
            events.append(
                _make_info_event(
                    round_id=round_id,
                    tick=start_tick,
                    seconds=start_seconds,
                    observer=observer,
                    target=target,
                    observer_key=observer_key,
                    target_key=target_key,
                )
            )
        last_visible_window[key] = end_seconds
    return sorted(events, key=lambda event: (int(event.round_id), int(event.tick), str(event.observer), str(event.target)))


def _load_player_name_lookup(loaded_data: Any, *, player_keys: set[str]) -> dict[str, str]:
    normalized_keys = {_coerce_text(key) for key in player_keys if _coerce_text(key) and not _coerce_text(key).startswith("name:")}
    if not normalized_keys:
        return {}
    data_dir = Path(getattr(loaded_data, "data_dir"))
    ticks_path = data_dir / "ticks.parquet"
    if ticks_path.exists() and pq is not None:
        available_columns = _visibility_artifact_columns(ticks_path) or []
        selected_columns = [column for column in ("steamid", "name") if column in set(available_columns)]
        if selected_columns:
            parquet_filter_values: list[object] = [int(key) if key.isdigit() else key for key in sorted(normalized_keys)]
            try:
                ticks = pd.read_parquet(
                    ticks_path,
                    columns=selected_columns,
                    filters=[[("steamid", "==", value)] for value in parquet_filter_values],
                )
            except Exception:
                ticks = pd.read_parquet(ticks_path, columns=selected_columns)
        else:
            ticks = pd.DataFrame()
    else:
        ticks, _label = read_table_with_fallback(data_dir, "ticks", required=False)
    if ticks.empty or "name" not in ticks.columns:
        return {}
    names = ticks.loc[:, [column for column in ("steamid", "name") if column in ticks.columns]].copy()
    names["name"] = names["name"].map(_coerce_text)
    names = names[names["name"] != ""]
    if "steamid" not in names.columns:
        return {}
    names["steamid"] = names["steamid"].map(_coerce_text)
    names = names[names["steamid"].isin(normalized_keys)]
    if names.empty:
        return {}
    deduped = names.drop_duplicates(subset=["steamid"], keep="last")
    return {str(row["steamid"]): str(row["name"]) for _, row in deduped.iterrows()}


def _display_name_for_player_key(player_key: object, *, name_lookup: dict[str, str]) -> str:
    key = _coerce_text(player_key)
    if key.startswith("name:"):
        return key.split(":", 1)[1]
    return name_lookup.get(key, key)


def _normalize_sound_feed_rows(sound_rows: pd.DataFrame) -> pd.DataFrame:
    if sound_rows.empty:
        return pd.DataFrame(
            columns=[
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
                "raw_source",
                "distance_min",
            ]
        )
    work = sound_rows.copy()
    for column in ("round_id", "start_tick", "end_tick"):
        work[column] = pd.to_numeric(work.get(column), errors="coerce")
    if "shot_count" in work.columns:
        work["shot_count"] = pd.to_numeric(work["shot_count"], errors="coerce")
    else:
        work["shot_count"] = pd.Series([float("nan")] * len(work), index=work.index, dtype="float64")
    if "distance_min" in work.columns:
        work["distance_min"] = pd.to_numeric(work["distance_min"], errors="coerce")
    else:
        work["distance_min"] = pd.Series([float("nan")] * len(work), index=work.index, dtype="float64")
    for column in ("effect_id", "observer_id", "source_type", "source_id", "sound_class", "sound_action", "item_name", "raw_source"):
        if column not in work.columns:
            work[column] = ""
        work[column] = work[column].map(_coerce_text)
    work = work.dropna(subset=["round_id", "start_tick", "end_tick"]).copy()
    return work


def _sound_class_action_counts(sound_rows: pd.DataFrame) -> tuple[tuple[str, int], ...]:
    if sound_rows.empty:
        return ()
    labels = [
        f"{_coerce_text(sound_class)}/{_coerce_text(sound_action)}"
        for sound_class, sound_action in zip(sound_rows["sound_class"], sound_rows["sound_action"])
    ]
    counts = pd.Series(labels, dtype="string").value_counts(sort=False).to_dict()
    return tuple((str(label), int(count)) for label, count in counts.items())


def _count_diff(
    base_counts: tuple[tuple[str, int], ...],
    kept_counts: tuple[tuple[str, int], ...],
) -> tuple[tuple[str, int], ...]:
    base = {str(label): int(count) for label, count in base_counts}
    kept = {str(label): int(count) for label, count in kept_counts}
    diff: list[tuple[str, int]] = []
    for label, count in base.items():
        remaining = count - kept.get(label, 0)
        if remaining > 0:
            diff.append((label, int(remaining)))
    return tuple(diff)


def _format_count_tuples(counts: tuple[tuple[str, int], ...]) -> str:
    if not counts:
        return ""
    return ",".join(f"{label}:{count}" for label, count in counts)


def build_sound_heard_events(
    sound_rows: pd.DataFrame,
    *,
    inferred_rounds: pd.DataFrame,
    tickrate: float,
    player_name_lookup: dict[str, str],
) -> list[InfoEvent]:
    if sound_rows.empty:
        return []
    start_ticks = _round_start_ticks(inferred_rounds)
    events: list[InfoEvent] = []
    ordered_rows = sound_rows.copy()
    if "priority" not in ordered_rows.columns:
        ordered_rows["priority"] = [
            sound_feed_priority(sound_class=row.get("sound_class", ""), sound_action=row.get("sound_action", ""))
            for row in ordered_rows.to_dict("records")
        ]
    ordered_rows = ordered_rows.sort_values(
        ["round_id", "start_tick", "priority", "observer_id", "source_id", "sound_class", "sound_action", "effect_id"],
        kind="stable",
    ).reset_index(drop=True)
    for row in ordered_rows.to_dict("records"):
        sound_class = _coerce_text(row.get("sound_class"))
        sound_action = _coerce_text(row.get("sound_action"))
        raw_source = _coerce_text(row.get("raw_source"))
        if not is_sound_exposure_feed_candidate(
            sound_class=sound_class,
            sound_action=sound_action,
            raw_source=raw_source,
        ):
            continue
        round_id = int(row["round_id"])
        tick = int(row["start_tick"])
        observer_key = _coerce_text(row.get("observer_id"))
        source_key = _coerce_text(row.get("source_id"))
        observer_label = _display_name_for_player_key(observer_key, name_lookup=player_name_lookup)
        source_label = ""
        if _coerce_text(row.get("source_type")) == "player":
            source_label = _display_name_for_player_key(source_key, name_lookup=player_name_lookup)
        shot_count_value = pd.to_numeric(row.get("shot_count"), errors="coerce")
        shot_count = None if pd.isna(shot_count_value) else int(shot_count_value)
        seconds = _derived_seconds(round_id, tick, start_ticks=start_ticks, tickrate=tickrate)
        message = f"{seconds:.2f}s  " + format_sound_exposure_message(
            observer_label=observer_label,
            source_label=source_label,
            sound_class=sound_class,
            sound_action=sound_action,
            item_name=_coerce_text(row.get("item_name")),
            shot_count=shot_count,
            raw_source=raw_source,
        )
        events.append(
            InfoEvent(
                round_id=round_id,
                tick=tick,
                seconds=seconds,
                kind=SOUND_EVENT_KIND,
                observer=observer_label,
                target=source_label or sound_action,
                message=message,
                observer_key=observer_key or observer_label,
                target_key=source_key if _coerce_text(row.get("source_type")) == "player" else "",
            )
        )
    return events


def _merge_locomotion_feed_rows(sound_rows: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
    if sound_rows.empty:
        return sound_rows, 0, 0
    merged_rows: list[dict[str, object]] = []
    merged_count = 0
    dropped_short = 0
    group_columns = ["round_id", "observer_id", "source_id", "sound_class", "sound_action"]
    for _group_key, group in sound_rows.groupby(group_columns, sort=False):
        ordered = group.sort_values(["start_tick", "end_tick", "effect_id"]).reset_index(drop=True)
        current: dict[str, object] | None = None
        for row in ordered.to_dict("records"):
            if current is None:
                current = dict(row)
                continue
            if int(row["start_tick"]) - int(current["end_tick"]) <= MOVEMENT_FEED_MERGE_GAP_TICKS:
                current["end_tick"] = max(int(current["end_tick"]), int(row["end_tick"]))
                current["distance_min"] = min(
                    float(current["distance_min"]) if pd.notna(current["distance_min"]) else float("inf"),
                    float(row["distance_min"]) if pd.notna(row["distance_min"]) else float("inf"),
                )
                merged_count += 1
                continue
            if int(current["end_tick"]) - int(current["start_tick"]) < MIN_MOVEMENT_FEED_DURATION_TICKS:
                dropped_short += 1
            else:
                merged_rows.append(current)
            current = dict(row)
        if current is not None:
            if int(current["end_tick"]) - int(current["start_tick"]) < MIN_MOVEMENT_FEED_DURATION_TICKS:
                dropped_short += 1
            else:
                merged_rows.append(current)
    if not merged_rows:
        return sound_rows.iloc[0:0].copy(), merged_count, dropped_short
    return pd.DataFrame(merged_rows), merged_count, dropped_short


def _dedupe_hard_step_feed_rows(sound_rows: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if sound_rows.empty:
        return sound_rows, 0
    deduped_rows: list[dict[str, object]] = []
    deduped_count = 0
    group_columns = ["round_id", "observer_id", "source_id", "sound_class", "sound_action"]
    for _group_key, group in sound_rows.groupby(group_columns, sort=False):
        ordered = group.sort_values(["start_tick", "end_tick", "effect_id"]).reset_index(drop=True)
        current: dict[str, object] | None = None
        for row in ordered.to_dict("records"):
            if current is None:
                current = dict(row)
                continue
            if int(row["start_tick"]) - int(current["start_tick"]) <= HARD_STEP_DEDUPE_WINDOW_TICKS:
                current["distance_min"] = min(
                    float(current["distance_min"]) if pd.notna(current["distance_min"]) else float("inf"),
                    float(row["distance_min"]) if pd.notna(row["distance_min"]) else float("inf"),
                )
                deduped_count += 1
                continue
            deduped_rows.append(current)
            current = dict(row)
        if current is not None:
            deduped_rows.append(current)
    if not deduped_rows:
        return sound_rows.iloc[0:0].copy(), deduped_count
    return pd.DataFrame(deduped_rows), deduped_count


def _build_sound_feed_rows(sound_rows: pd.DataFrame) -> tuple[pd.DataFrame, SoundFeedBuildStats]:
    normalized = _normalize_sound_feed_rows(sound_rows)
    if normalized.empty:
        return normalized, SoundFeedBuildStats(sound_exposure_rows_loaded=0, sound_info_events_by_class=())
    artifact_counts = _sound_class_action_counts(normalized)
    candidate_rows = _filter_sound_feed_candidate_rows(normalized)
    locomotion_rows = candidate_rows[
        (candidate_rows["sound_class"] == "movement") & (candidate_rows["sound_action"] == "locomotion")
    ].copy()
    hard_step_rows = candidate_rows[
        (candidate_rows["sound_class"] == "movement") & (candidate_rows["sound_action"] == "hard_step")
    ].copy()
    other_rows = candidate_rows[
        ~(
            ((candidate_rows["sound_class"] == "movement") & (candidate_rows["sound_action"] == "locomotion"))
            | ((candidate_rows["sound_class"] == "movement") & (candidate_rows["sound_action"] == "hard_step"))
        )
    ].copy()
    merged_locomotion, merged_count, dropped_short = _merge_locomotion_feed_rows(locomotion_rows)
    deduped_hard_step, deduped_count = _dedupe_hard_step_feed_rows(hard_step_rows)
    feed_rows = pd.concat([other_rows, merged_locomotion, deduped_hard_step], ignore_index=True) if (
        not other_rows.empty or not merged_locomotion.empty or not deduped_hard_step.empty
    ) else candidate_rows.iloc[0:0].copy()
    by_class = (
        tuple(
            (str(sound_class), int(count))
            for sound_class, count in feed_rows["sound_class"].value_counts(sort=False).to_dict().items()
        )
        if not feed_rows.empty
        else ()
    )
    generated_counts = _sound_class_action_counts(feed_rows)
    dropped_counts = _count_diff(artifact_counts, generated_counts)
    stats = SoundFeedBuildStats(
        sound_exposure_rows_loaded=len(normalized),
        sound_info_events_generated=len(feed_rows),
        sound_movement_exposures_merged=merged_count,
        sound_movement_exposures_dropped_short=dropped_short,
        sound_hard_step_events_deduped=deduped_count,
        sound_info_events_by_class=by_class,
        sound_exposure_rows_by_class_action=artifact_counts,
        sound_info_events_by_class_action=generated_counts,
        sound_info_events_dropped_by_class_action=dropped_counts,
    )
    if not feed_rows.empty:
        feed_rows["priority"] = [
            sound_feed_priority(sound_class=row["sound_class"], sound_action=row["sound_action"])
            for row in feed_rows.to_dict("records")
        ]
    return feed_rows, stats


def _filter_sound_feed_candidate_rows(sound_rows: pd.DataFrame) -> pd.DataFrame:
    if sound_rows.empty:
        return sound_rows
    candidate_mask = [
        is_sound_exposure_feed_candidate(
            sound_class=_coerce_text(sound_class),
            sound_action=_coerce_text(sound_action),
            raw_source=_coerce_text(raw_source),
        )
        for sound_class, sound_action, raw_source in zip(
            sound_rows.get("sound_class", pd.Series(dtype="string")),
            sound_rows.get("sound_action", pd.Series(dtype="string")),
            sound_rows.get("raw_source", pd.Series(dtype="string")),
        )
    ]
    return sound_rows.loc[candidate_mask].copy()


def filter_events_by_players(events: list[InfoEvent], selected_players: set[str] | frozenset[str]) -> list[InfoEvent]:
    if not selected_players:
        return events
    return [
        event
        for event in events
        if (event.observer_key or event.observer) in selected_players or (event.target_key or event.target) in selected_players
    ]


def load_info_events_for_dataset(
    loaded_data: Any,
    round_id: int | None = None,
    tickrate: float | None = None,
) -> list[InfoEvent]:
    load_started_at = time.perf_counter()
    _profile_info_events_stage("info_events.load.start", round_id=round_id)
    inferred_rounds = getattr(loaded_data, "inferred_rounds", pd.DataFrame())
    visibility_table, schema = _load_visibility_rows_for_dataset(loaded_data, round_id=round_id)
    sound_table, sound_schema = _load_sound_exposure_rows_for_dataset(loaded_data, round_id=round_id)
    if schema is None and sound_schema is None:
        _profile_info_events_stage(
            "info_events.load.end",
            started_at=load_started_at,
            round_id=round_id,
            rows_before=0,
            rows_after=0,
            events_count=0,
            selected_columns=None,
            extra_note="artifact_missing",
        )
        return []
    effective_tickrate = 64.0 if tickrate is None else float(tickrate)
    formatted_events: list[InfoEvent] = []
    decoded_rows = pd.DataFrame()
    if schema is not None:
        build_started_at = time.perf_counter()
        _profile_info_events_stage(
            "viewer.info_events.build_from_intervals.start",
            round_id=round_id,
            rows_before=len(visibility_table),
            selected_columns=schema.projected_columns,
        )
        decoded_rows = _decode_visibility_intervals(
            visibility_table,
            schema=schema,
            inferred_rounds=inferred_rounds,
            tickrate=effective_tickrate,
        )
        unformatted_events = build_visibility_spotted_events(decoded_rows)
        _profile_info_events_stage(
            "viewer.info_events.build_from_intervals.end",
            started_at=build_started_at,
            round_id=round_id,
            rows_before=len(visibility_table),
            rows_after=len(decoded_rows),
            events_count=len(unformatted_events),
            selected_columns=schema.projected_columns,
        )
        formatted_events.extend(
            InfoEvent(
                round_id=event.round_id,
                tick=event.tick,
                seconds=event.seconds,
                kind=event.kind,
                observer=event.observer,
                target=event.target,
                message=format_info_event_line(event),
                observer_key=event.observer_key,
                target_key=event.target_key,
            )
            for event in unformatted_events
        )
    if sound_schema is not None:
        normalized_sound_rows = sound_table.rename(
            columns={
                sound_schema.round_id_column: "round_id",
                sound_schema.effect_id_column: "effect_id",
                sound_schema.observer_id_column: "observer_id",
                sound_schema.source_type_column: "source_type",
                sound_schema.source_id_column: "source_id",
                sound_schema.start_tick_column: "start_tick",
                sound_schema.end_tick_column: "end_tick",
                sound_schema.sound_class_column: "sound_class",
                sound_schema.sound_action_column: "sound_action",
                **({sound_schema.item_name_column: "item_name"} if sound_schema.item_name_column is not None else {}),
                **({sound_schema.shot_count_column: "shot_count"} if sound_schema.shot_count_column is not None else {}),
                **({sound_schema.raw_source_column: "raw_source"} if sound_schema.raw_source_column is not None else {}),
                **({"distance_min": "distance_min"} if "distance_min" in sound_table.columns else {}),
            }
        )
        sound_feed_rows, sound_feed_stats = _build_sound_feed_rows(normalized_sound_rows)
        player_keys: set[str] = set(sound_feed_rows.get("observer_id", pd.Series(dtype="string")).map(_coerce_text).tolist())
        player_keys.update(
            _coerce_text(source_id)
            for source_type, source_id in zip(
                sound_feed_rows.get("source_type", pd.Series(dtype="string")),
                sound_feed_rows.get("source_id", pd.Series(dtype="string")),
            )
            if _coerce_text(source_type) == "player" and _coerce_text(source_id)
        )
        player_name_lookup = _load_player_name_lookup(loaded_data, player_keys=player_keys)
        sound_events = build_sound_heard_events(
            sound_feed_rows,
            inferred_rounds=inferred_rounds,
            tickrate=effective_tickrate,
            player_name_lookup=player_name_lookup,
        )
        _profile_info_events_stage(
            "info_events.sound_feed_build",
            round_id=round_id,
            rows_before=sound_feed_stats.sound_exposure_rows_loaded,
            rows_after=len(sound_feed_rows),
            events_count=len(sound_events),
            extra_note=profile_note(
                "sound_info_events_by_class="
                + ",".join(f"{sound_class}:{count}" for sound_class, count in sound_feed_stats.sound_info_events_by_class),
                "sound_exposure_rows_by_class_action="
                + _format_count_tuples(sound_feed_stats.sound_exposure_rows_by_class_action),
                "sound_info_events_generated_by_class_action="
                + _format_count_tuples(sound_feed_stats.sound_info_events_by_class_action),
                "sound_info_events_dropped_by_class_action="
                + _format_count_tuples(sound_feed_stats.sound_info_events_dropped_by_class_action),
                f"sound_movement_exposures_merged={sound_feed_stats.sound_movement_exposures_merged}",
                f"sound_movement_exposures_dropped_short={sound_feed_stats.sound_movement_exposures_dropped_short}",
                f"sound_hard_step_events_deduped={sound_feed_stats.sound_hard_step_events_deduped}",
            ),
        )
        formatted_events.extend(sound_events)
    formatted_events = sorted(
        formatted_events,
        key=lambda event: (int(event.round_id), int(event.tick), str(event.kind), str(event.observer), str(event.target)),
    )
    _profile_info_events_stage(
        "info_events.load.end",
        started_at=load_started_at,
        round_id=round_id,
        rows_before=len(visibility_table) + len(sound_table),
        rows_after=len(decoded_rows) + len(sound_table),
        events_count=len(formatted_events),
        selected_columns=(
            []
            if schema is None and sound_schema is None
            else list(
                dict.fromkeys(
                    ([] if schema is None else schema.projected_columns)
                    + ([] if sound_schema is None else sound_schema.projected_columns)
                )
            )
        ),
    )
    return formatted_events


def visible_event_lines_for_tick(
    events: list[InfoEvent],
    *,
    round_id: int,
    current_tick: int,
) -> list[str]:
    visible_lines = [
        format_info_event_line(event)
        for event in events
        if int(event.round_id) == int(round_id) and int(event.tick) <= int(current_tick)
    ]
    return visible_lines if visible_lines else ["No info events"]


def build_info_feed_audit_table(
    loaded_data: Any,
    *,
    round_id: int | None = None,
    tickrate: float | None = None,
) -> pd.DataFrame:
    inferred_rounds = getattr(loaded_data, "inferred_rounds", pd.DataFrame())
    effective_tickrate = 64.0 if tickrate is None else float(tickrate)
    audit_rows: list[dict[str, object]] = []
    visibility_table, schema = _load_visibility_rows_for_dataset(loaded_data, round_id=round_id)
    if schema is not None:
        decoded_rows = _decode_visibility_intervals(
            visibility_table,
            schema=schema,
            inferred_rounds=inferred_rounds,
            tickrate=effective_tickrate,
        )
        for event in build_visibility_spotted_events(decoded_rows):
            message = format_info_event_line(event)
            audit_rows.append(
                {
                    "round_id": int(event.round_id),
                    "tick": int(event.tick),
                    "priority": -1,
                    "event_class": "visibility",
                    "event_type": event.kind,
                    "observer_id": event.observer_key or event.observer,
                    "observer_name": event.observer,
                    "source_id": event.target_key or event.target,
                    "source_name": event.target,
                    "sound_class": "",
                    "sound_action": "",
                    "message": message,
                }
            )
    sound_table, sound_schema = _load_sound_exposure_rows_for_dataset(loaded_data, round_id=round_id)
    if sound_schema is not None:
        normalized_sound_rows = sound_table.rename(
            columns={
                sound_schema.round_id_column: "round_id",
                sound_schema.effect_id_column: "effect_id",
                sound_schema.observer_id_column: "observer_id",
                sound_schema.source_type_column: "source_type",
                sound_schema.source_id_column: "source_id",
                sound_schema.start_tick_column: "start_tick",
                sound_schema.end_tick_column: "end_tick",
                sound_schema.sound_class_column: "sound_class",
                sound_schema.sound_action_column: "sound_action",
                **({sound_schema.item_name_column: "item_name"} if sound_schema.item_name_column is not None else {}),
                **({sound_schema.shot_count_column: "shot_count"} if sound_schema.shot_count_column is not None else {}),
                **({sound_schema.raw_source_column: "raw_source"} if sound_schema.raw_source_column is not None else {}),
                **({"distance_min": "distance_min"} if "distance_min" in sound_table.columns else {}),
            }
        )
        sound_feed_rows, _stats = _build_sound_feed_rows(normalized_sound_rows)
        player_keys: set[str] = set(sound_feed_rows.get("observer_id", pd.Series(dtype="string")).map(_coerce_text).tolist())
        player_keys.update(
            _coerce_text(source_id)
            for source_type, source_id in zip(
                sound_feed_rows.get("source_type", pd.Series(dtype="string")),
                sound_feed_rows.get("source_id", pd.Series(dtype="string")),
            )
            if _coerce_text(source_type) == "player" and _coerce_text(source_id)
        )
        player_name_lookup = _load_player_name_lookup(loaded_data, player_keys=player_keys)
        sound_events = build_sound_heard_events(
            sound_feed_rows,
            inferred_rounds=inferred_rounds,
            tickrate=effective_tickrate,
            player_name_lookup=player_name_lookup,
        )
        ordered_rows = sound_feed_rows.sort_values(
            ["round_id", "start_tick", "priority", "observer_id", "source_id", "sound_class", "sound_action", "effect_id"],
            kind="stable",
        ).reset_index(drop=True)
        for row in ordered_rows.to_dict("records"):
            observer_id = _coerce_text(row.get("observer_id"))
            source_id = _coerce_text(row.get("source_id"))
            observer_name = _display_name_for_player_key(observer_id, name_lookup=player_name_lookup)
            source_name = ""
            if _coerce_text(row.get("source_type")) == "player":
                source_name = _display_name_for_player_key(source_id, name_lookup=player_name_lookup)
            shot_count_value = pd.to_numeric(row.get("shot_count"), errors="coerce")
            shot_count = None if pd.isna(shot_count_value) else int(shot_count_value)
            seconds = _derived_seconds(int(row["round_id"]), int(row["start_tick"]), start_ticks=_round_start_ticks(inferred_rounds), tickrate=effective_tickrate)
            message = f"{seconds:.2f}s  " + format_sound_exposure_message(
                observer_label=observer_name,
                source_label=source_name,
                sound_class=_coerce_text(row.get("sound_class")),
                sound_action=_coerce_text(row.get("sound_action")),
                item_name=_coerce_text(row.get("item_name")),
                shot_count=shot_count,
                raw_source=_coerce_text(row.get("raw_source")),
            )
            audit_rows.append(
                {
                    "round_id": int(row["round_id"]),
                    "tick": int(row["start_tick"]),
                    "priority": int(row.get("priority", sound_feed_priority(sound_class=_coerce_text(row.get("sound_class")), sound_action=_coerce_text(row.get("sound_action"))))),
                    "event_class": "sound",
                    "event_type": SOUND_EVENT_KIND,
                    "observer_id": observer_id,
                    "observer_name": observer_name,
                    "source_id": source_id,
                    "source_name": source_name,
                    "sound_class": _coerce_text(row.get("sound_class")),
                    "sound_action": _coerce_text(row.get("sound_action")),
                    "message": message,
                }
            )
    if not audit_rows:
        return pd.DataFrame(columns=INFO_FEED_AUDIT_COLUMNS)
    table = pd.DataFrame(audit_rows)
    table = table.sort_values(
        ["round_id", "tick", "priority", "event_class", "observer_name", "source_name", "message"],
        kind="stable",
    ).reset_index(drop=True)
    return table.loc[:, INFO_FEED_AUDIT_COLUMNS]


def export_info_feed_audit(
    loaded_data: Any,
    *,
    round_ids: list[int] | None,
    tickrate: float,
    output_path: Path | None,
    table_format: str | None,
) -> Path:
    resolved_round_ids = (
        [int(round_id) for round_id in getattr(loaded_data, "round_ids", [])]
        if round_ids is None
        else [int(round_id) for round_id in round_ids]
    )
    tables = [
        build_info_feed_audit_table(
            loaded_data,
            round_id=int(round_id),
            tickrate=tickrate,
        )
        for round_id in resolved_round_ids
    ]
    combined = pd.concat(tables, ignore_index=True) if tables else pd.DataFrame(columns=INFO_FEED_AUDIT_COLUMNS)
    output_format = normalize_table_format(table_format or DEFAULT_TABLE_FORMAT)
    target_path = Path(output_path) if output_path is not None else (
        Path(getattr(loaded_data, "data_dir")) / f"info_feed_audit{'.parquet' if output_format == 'parquet' else '.csv'}"
    )
    if output_format == "parquet":
        combined.to_parquet(target_path, index=False)
    else:
        combined.to_csv(target_path, index=False)
    return target_path
