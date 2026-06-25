from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import time

import pandas as pd

from wall.profile import profile_log, profile_note


GRENADE_SEGMENT_MAX_ERROR_2D = 32.0
GRENADE_SEGMENT_MAX_ERROR_Z = 32.0
GRENADE_SEGMENT_MAX_TICKS = 24

GRENADE_SEGMENT_SCHEMA_COLUMNS = [
    "round_id",
    "grenade_id",
    "grenade_type",
    "thrower_key",
    "thrower",
    "segment_index",
    "start_tick",
    "end_tick",
    "start_seconds",
    "end_seconds",
    "duration_seconds",
    "start_x",
    "start_y",
    "start_z",
    "end_x",
    "end_y",
    "end_z",
    "point_count",
    "max_error_2d",
    "max_error_z",
    "reason_end",
]


@dataclass(frozen=True)
class GrenadeSegmentCompressionConfig:
    max_error_2d: float = GRENADE_SEGMENT_MAX_ERROR_2D
    max_error_z: float = GRENADE_SEGMENT_MAX_ERROR_Z
    max_segment_ticks: int = GRENADE_SEGMENT_MAX_TICKS


@dataclass(frozen=True)
class GrenadeTrajectoryPoint:
    round_id: int
    grenade_id: str
    grenade_type: str
    thrower_key: str
    thrower: str
    tick: int
    seconds: float
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class GrenadeTrajectorySegment:
    round_id: int
    grenade_id: str
    grenade_type: str
    thrower_key: str
    thrower: str
    segment_index: int
    start_tick: int
    end_tick: int
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    start_x: float
    start_y: float
    start_z: float
    end_x: float
    end_y: float
    end_z: float
    point_count: int
    max_error_2d: float
    max_error_z: float
    reason_end: str


def _coerce_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "<na>"}:
        return ""
    return text


def _coerce_float(value: object) -> float | None:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return None
    parsed = float(numeric)
    return parsed if math.isfinite(parsed) else None


def _coerce_int(value: object) -> int | None:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return None
    return int(numeric)


def _projectile_identity_fallback(group: pd.DataFrame) -> str:
    # Prefer the parser's grenade_entity_id. If it is missing, fall back to a
    # round-local composite derived from thrower, projectile type, and the
    # first observed tick so the compression path still has a stable key.
    first = group.iloc[0]
    round_id = _coerce_int(first.get("inferred_round_id")) or 0
    grenade_type = _coerce_text(first.get("grenade_type")) or "unknown_grenade"
    thrower_key = _coerce_text(first.get("steamid")) or _coerce_text(first.get("name")) or "unknown_thrower"
    first_tick = _coerce_int(first.get("tick")) or 0
    return f"fallback:{round_id}:{grenade_type}:{thrower_key}:{first_tick}"


def _build_identity_and_sort(grenades: pd.DataFrame) -> pd.DataFrame:
    required = {"grenade_type", "tick", "x", "y", "z", "inferred_round_id"}
    if grenades.empty or not required.issubset(grenades.columns):
        return pd.DataFrame(columns=list(grenades.columns) + ["_grenade_identity"])
    work = grenades.copy()
    work = work[work["grenade_type"].astype(str).str.contains("Projectile", na=False)].copy()
    work["tick"] = pd.to_numeric(work["tick"], errors="coerce")
    work["inferred_round_id"] = pd.to_numeric(work["inferred_round_id"], errors="coerce")
    work["inferred_round_seconds"] = pd.to_numeric(
        work.get("inferred_round_seconds", pd.Series(index=work.index, dtype="float64")),
        errors="coerce",
    )
    work["x"] = pd.to_numeric(work["x"], errors="coerce")
    work["y"] = pd.to_numeric(work["y"], errors="coerce")
    work["z"] = pd.to_numeric(work["z"], errors="coerce")
    work["grenade_entity_id"] = pd.to_numeric(
        work.get("grenade_entity_id", pd.Series(index=work.index, dtype="float64")),
        errors="coerce",
    )
    work = work.dropna(subset=["tick", "inferred_round_id"]).copy()
    work = work.sort_values(["inferred_round_id", "grenade_entity_id", "tick"]).copy()
    if "grenade_entity_id" in work.columns:
        ids = work["grenade_entity_id"].astype("Int64").astype("string").fillna("")
    else:
        ids = pd.Series([""] * len(work), index=work.index, dtype="string")
    work["_grenade_identity"] = ids
    for key, group in work.groupby(["inferred_round_id", "_grenade_identity"], sort=False, dropna=False):
        if key[1]:
            continue
        fallback_identity = _projectile_identity_fallback(group)
        work.loc[group.index, "_grenade_identity"] = fallback_identity
    return work


def _expected_tick_gap(points: list[GrenadeTrajectoryPoint]) -> int:
    diffs = [
        points[index + 1].tick - points[index].tick
        for index in range(len(points) - 1)
        if points[index + 1].tick - points[index].tick > 0
    ]
    if not diffs:
        return 1
    return max(1, int(round(float(pd.Series(diffs).median()))))


def _segment_error(points: list[GrenadeTrajectoryPoint], start_index: int, end_index: int) -> tuple[float, float]:
    if end_index <= start_index:
        return 0.0, 0.0
    start = points[start_index]
    end = points[end_index]
    tick_span = end.tick - start.tick
    if tick_span <= 0:
        return 0.0, 0.0
    max_error_2d = 0.0
    max_error_z = 0.0
    for index in range(start_index + 1, end_index):
        point = points[index]
        alpha = (point.tick - start.tick) / tick_span
        pred_x = start.x + alpha * (end.x - start.x)
        pred_y = start.y + alpha * (end.y - start.y)
        pred_z = start.z + alpha * (end.z - start.z)
        error_2d = math.dist((point.x, point.y), (pred_x, pred_y))
        error_z = abs(point.z - pred_z)
        max_error_2d = max(max_error_2d, float(error_2d))
        max_error_z = max(max_error_z, float(error_z))
    return max_error_2d, max_error_z


def _is_valid_position(point: GrenadeTrajectoryPoint) -> bool:
    return all(math.isfinite(value) for value in (point.x, point.y, point.z))


def compress_grenade_trajectory_segments(
    raw_points: list[GrenadeTrajectoryPoint],
    config: GrenadeSegmentCompressionConfig,
) -> list[GrenadeTrajectorySegment]:
    if not raw_points:
        return []
    points = sorted(raw_points, key=lambda point: int(point.tick))
    expected_gap = _expected_tick_gap(points)
    segments: list[GrenadeTrajectorySegment] = []
    segment_index = 0
    start_index = 0

    while start_index < len(points):
        while start_index < len(points) and not _is_valid_position(points[start_index]):
            start_index += 1
        if start_index >= len(points):
            break
        accepted_end_index = start_index
        candidate_index = start_index + 1
        reason_end = "end"
        next_start_index = len(points)

        while candidate_index < len(points):
            candidate = points[candidate_index]
            previous = points[candidate_index - 1]
            if not _is_valid_position(candidate):
                reason_end = "invalid_position"
                next_start_index = candidate_index + 1
                break
            tick_gap = candidate.tick - previous.tick
            if tick_gap > expected_gap:
                reason_end = "tick_gap"
                next_start_index = candidate_index
                break
            if candidate.tick - points[start_index].tick >= int(config.max_segment_ticks):
                reason_end = "max_segment_ticks"
                next_start_index = accepted_end_index
                break
            max_error_2d, max_error_z = _segment_error(points, start_index, candidate_index)
            if max_error_2d > float(config.max_error_2d):
                reason_end = "max_error_2d"
                next_start_index = accepted_end_index
                break
            if max_error_z > float(config.max_error_z):
                reason_end = "max_error_z"
                next_start_index = accepted_end_index
                break
            accepted_end_index = candidate_index
            candidate_index += 1

        if candidate_index >= len(points):
            reason_end = "end"
            next_start_index = len(points)

        start = points[start_index]
        end = points[accepted_end_index]
        max_error_2d, max_error_z = _segment_error(points, start_index, accepted_end_index)
        segments.append(
            GrenadeTrajectorySegment(
                round_id=int(start.round_id),
                grenade_id=str(start.grenade_id),
                grenade_type=str(start.grenade_type),
                thrower_key=str(start.thrower_key),
                thrower=str(start.thrower),
                segment_index=segment_index,
                start_tick=int(start.tick),
                end_tick=int(end.tick),
                start_seconds=float(start.seconds),
                end_seconds=float(end.seconds),
                duration_seconds=float(end.seconds - start.seconds),
                start_x=float(start.x),
                start_y=float(start.y),
                start_z=float(start.z),
                end_x=float(end.x),
                end_y=float(end.y),
                end_z=float(end.z),
                point_count=int(accepted_end_index - start_index + 1),
                max_error_2d=float(max_error_2d),
                max_error_z=float(max_error_z),
                reason_end=reason_end,
            )
        )
        segment_index += 1
        if next_start_index == len(points):
            break
        if next_start_index <= start_index:
            next_start_index = start_index + 1
        start_index = next_start_index

    return segments


def build_grenade_trajectory_segments_table(
    grenades: pd.DataFrame,
    *,
    tickrate: float = 64.0,
    config: GrenadeSegmentCompressionConfig | None = None,
) -> pd.DataFrame:
    resolved_config = config or GrenadeSegmentCompressionConfig()
    load_started_at = time.perf_counter()
    work = _build_identity_and_sort(grenades)
    profile_log(
        "grenade_segments.load_raw",
        started_at=load_started_at,
        df=work,
        note=profile_note(f"tickrate={tickrate}", f"input_rows={len(grenades)}"),
    )
    if work.empty:
        return pd.DataFrame(columns=GRENADE_SEGMENT_SCHEMA_COLUMNS)

    compress_started_at = time.perf_counter()
    segments: list[GrenadeTrajectorySegment] = []
    effective_tickrate = tickrate if tickrate > 0 else 64.0
    for _, group in work.groupby(["inferred_round_id", "_grenade_identity"], sort=False):
        group = group.sort_values("tick").copy()
        points: list[GrenadeTrajectoryPoint] = []
        for _, row in group.iterrows():
            tick = _coerce_int(row.get("tick"))
            round_id = _coerce_int(row.get("inferred_round_id"))
            seconds_value = _coerce_float(row.get("inferred_round_seconds"))
            if tick is None or round_id is None:
                continue
            points.append(
                GrenadeTrajectoryPoint(
                    round_id=int(round_id),
                    grenade_id=_coerce_text(row.get("_grenade_identity")),
                    grenade_type=_coerce_text(row.get("grenade_type")),
                    thrower_key=_coerce_text(row.get("steamid")) or _coerce_text(row.get("name")),
                    thrower=_coerce_text(row.get("name")),
                    tick=int(tick),
                    seconds=(float(seconds_value) if seconds_value is not None else float(tick) / effective_tickrate),
                    x=float(row["x"]) if pd.notna(row["x"]) else float("nan"),
                    y=float(row["y"]) if pd.notna(row["y"]) else float("nan"),
                    z=float(row["z"]) if pd.notna(row["z"]) else float("nan"),
                )
            )
        segments.extend(compress_grenade_trajectory_segments(points, resolved_config))
    profile_log(
        "grenade_segments.compress",
        started_at=compress_started_at,
        note=profile_note(f"input_rows={len(work)}", f"segments={len(segments)}"),
    )
    if not segments:
        return pd.DataFrame(columns=GRENADE_SEGMENT_SCHEMA_COLUMNS)
    table = pd.DataFrame([asdict(segment) for segment in segments])
    return table[GRENADE_SEGMENT_SCHEMA_COLUMNS]
