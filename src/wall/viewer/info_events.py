from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any

import pandas as pd

from wall.profile import profile_log, profile_note

try:
    import pyarrow.parquet as pq
except ModuleNotFoundError:
    pq = None


VISIBILITY_EVENT_KIND = "visibility_spotted"
VISIBILITY_REDISCOVERY_GAP_SECONDS = 2.0
UNSUPPORTED_VISIBILITY_SCHEMA_MESSAGE = (
    "visibility.parquet uses an unsupported visibility schema. "
    "Re-run `wall visibility <dataset_dir>` to generate the interval visibility artifact."
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
    if schema is None:
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
        tickrate=64.0 if tickrate is None else float(tickrate),
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
    formatted_events = [
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
    ]
    _profile_info_events_stage(
        "info_events.load.end",
        started_at=load_started_at,
        round_id=round_id,
        rows_before=len(visibility_table),
        rows_after=len(decoded_rows),
        events_count=len(formatted_events),
        selected_columns=schema.projected_columns,
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
    return visible_lines if visible_lines else ["No visibility events"]
