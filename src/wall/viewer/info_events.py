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
class VisibilityArtifactSchema:
    round_id_column: str
    tick_column: str
    observer_key_column: str
    target_key_column: str
    observer_column: str
    target_column: str
    is_visible_column: str
    seconds_column: str | None
    observer_team_column: str | None
    target_team_column: str | None

    @property
    def required_columns(self) -> list[str]:
        columns = [
            self.round_id_column,
            self.tick_column,
            self.observer_key_column,
            self.target_key_column,
            self.observer_column,
            self.target_column,
            self.is_visible_column,
        ]
        if self.seconds_column is not None:
            columns.append(self.seconds_column)
        if self.observer_team_column is not None:
            columns.append(self.observer_team_column)
        if self.target_team_column is not None:
            columns.append(self.target_team_column)
        return list(dict.fromkeys(columns))


def _pick_first(columns: set[str], candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def resolve_visibility_artifact_schema(columns: list[str]) -> VisibilityArtifactSchema | None:
    column_set = set(columns)
    round_id_column = _pick_first(column_set, ("round_id", "inferred_round_id"))
    tick_column = _pick_first(column_set, ("tick",))
    observer_key_column = _pick_first(column_set, ("observer_steamid", "observer", "observer_name"))
    target_key_column = _pick_first(column_set, ("target_steamid", "target", "target_name"))
    observer_column = _pick_first(column_set, ("observer", "observer_name", "observer_steamid"))
    target_column = _pick_first(column_set, ("target", "target_name", "target_steamid"))
    is_visible_column = _pick_first(column_set, ("is_visible", "visible", "visibility"))
    if None in {
        round_id_column,
        tick_column,
        observer_key_column,
        target_key_column,
        observer_column,
        target_column,
        is_visible_column,
    }:
        return None
    return VisibilityArtifactSchema(
        round_id_column=round_id_column,
        tick_column=tick_column,
        observer_key_column=observer_key_column,
        target_key_column=target_key_column,
        observer_column=observer_column,
        target_column=target_column,
        is_visible_column=is_visible_column,
        seconds_column=_pick_first(column_set, ("seconds", "round_seconds", "inferred_round_seconds")),
        observer_team_column=_pick_first(column_set, ("observer_team", "observer_team_num")),
        target_team_column=_pick_first(column_set, ("target_team", "target_team_num")),
    )


def _round_start_ticks(inferred_rounds: pd.DataFrame) -> dict[int, int]:
    if inferred_rounds.empty or "inferred_round_id" not in inferred_rounds.columns or "start_tick" not in inferred_rounds.columns:
        return {}
    work = inferred_rounds.loc[:, ["inferred_round_id", "start_tick"]].copy()
    work["inferred_round_id"] = pd.to_numeric(work["inferred_round_id"], errors="coerce")
    work["start_tick"] = pd.to_numeric(work["start_tick"], errors="coerce")
    work = work.dropna(subset=["inferred_round_id", "start_tick"])
    return {int(row["inferred_round_id"]): int(row["start_tick"]) for _, row in work.iterrows()}


def _coerce_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "<na>"}:
        return ""
    return text


def _normalize_player_key(value: object, display_value: object) -> str:
    key = _coerce_text(value)
    if key:
        return key
    return _coerce_text(display_value)


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


def _seconds_series(
    visibility_table: pd.DataFrame,
    *,
    schema: VisibilityArtifactSchema,
    inferred_rounds: pd.DataFrame,
    tickrate: float,
) -> pd.Series:
    if schema.seconds_column is not None and schema.seconds_column in visibility_table.columns:
        numeric = pd.to_numeric(visibility_table[schema.seconds_column], errors="coerce")
        if numeric.notna().any():
            return numeric.astype(float)
    start_ticks = _round_start_ticks(inferred_rounds)
    round_ids = pd.to_numeric(visibility_table[schema.round_id_column], errors="coerce")
    ticks = pd.to_numeric(visibility_table[schema.tick_column], errors="coerce")
    effective_tickrate = tickrate if tickrate > 0 else 64.0
    derived = [
        ((float(tick) - float(start_ticks.get(int(round_id), int(tick)))) / effective_tickrate)
        if pd.notna(round_id) and pd.notna(tick)
        else 0.0
        for round_id, tick in zip(round_ids.tolist(), ticks.tolist())
    ]
    return pd.Series(derived, index=visibility_table.index, dtype="float64")


def _load_visibility_rows_for_dataset(
    loaded_data: Any,
    *,
    round_id: int | None,
) -> tuple[pd.DataFrame, VisibilityArtifactSchema | None]:
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
        read_started_at = time.perf_counter()
        _profile_info_events_stage(
            "info_events.read_visibility.start",
            round_id=round_id,
            selected_columns="schema_fallback_pending",
            extra_note="read_mode=full_table_schema_fallback",
        )
        visibility_table = pd.read_parquet(artifact_path)
        schema = resolve_visibility_artifact_schema(list(visibility_table.columns))
        if schema is None:
            return pd.DataFrame(), None
        projected_columns = schema.required_columns
        visibility_table = visibility_table.loc[:, projected_columns].copy()
        _profile_info_events_stage(
            "info_events.read_visibility.end",
            started_at=read_started_at,
            round_id=round_id,
            rows_before=0,
            rows_after=len(visibility_table),
            selected_columns=projected_columns,
            extra_note="read_mode=full_table_schema_fallback",
        )
    else:
        schema = resolve_visibility_artifact_schema(artifact_columns)
        if schema is None:
            return pd.DataFrame(), None
        projected_columns = schema.required_columns
        read_started_at = time.perf_counter()
        _profile_info_events_stage(
            "info_events.read_visibility.start",
            round_id=round_id,
            selected_columns=projected_columns,
            extra_note="read_mode=projected_all_rounds",
        )
        visibility_table = pd.read_parquet(artifact_path, columns=projected_columns)
        _profile_info_events_stage(
            "info_events.read_visibility.end",
            started_at=read_started_at,
            round_id=round_id,
            rows_before=0,
            rows_after=len(visibility_table),
            selected_columns=projected_columns,
            extra_note="read_mode=projected_all_rounds",
        )
    pre_filter_rows = len(visibility_table)
    filter_started_at = time.perf_counter()
    _profile_info_events_stage(
        "info_events.filter_round.start",
        round_id=round_id,
        rows_before=len(visibility_table),
        selected_columns=schema.required_columns,
        extra_note="round_scope=all" if round_id is None else f"round_scope=single target_round_id={int(round_id)}",
    )
    if round_id is not None:
        round_ids = pd.to_numeric(visibility_table[schema.round_id_column], errors="coerce")
        visibility_table = visibility_table.loc[round_ids == int(round_id)].copy()
    _profile_info_events_stage(
        "info_events.filter_round.end",
        started_at=filter_started_at,
        round_id=round_id,
        rows_before=pre_filter_rows,
        rows_after=len(visibility_table),
        selected_columns=schema.required_columns,
        extra_note="round_scope=all" if round_id is None else f"round_scope=single target_round_id={int(round_id)}",
    )
    return visibility_table, schema


def _decode_visibility_rows(
    visibility_table: pd.DataFrame,
    *,
    schema: VisibilityArtifactSchema,
    inferred_rounds: pd.DataFrame,
    tickrate: float,
) -> pd.DataFrame:
    if visibility_table.empty:
        return pd.DataFrame(
            columns=[
                "round_id",
                "tick",
                "observer",
                "target",
                "observer_key",
                "target_key",
                "is_visible",
                "seconds",
                "observer_team",
                "target_team",
            ]
        )
    work = visibility_table.loc[:, schema.required_columns].copy()
    work["round_id"] = pd.to_numeric(work[schema.round_id_column], errors="coerce")
    work["tick"] = pd.to_numeric(work[schema.tick_column], errors="coerce")
    work["observer"] = work[schema.observer_column].map(_coerce_text)
    work["target"] = work[schema.target_column].map(_coerce_text)
    work["observer_key"] = [
        _normalize_player_key(key_value, display_value)
        for key_value, display_value in zip(work[schema.observer_key_column].tolist(), work[schema.observer_column].tolist())
    ]
    work["target_key"] = [
        _normalize_player_key(key_value, display_value)
        for key_value, display_value in zip(work[schema.target_key_column].tolist(), work[schema.target_column].tolist())
    ]
    work["is_visible"] = work[schema.is_visible_column].map(_coerce_bool)
    work["seconds"] = _seconds_series(work, schema=schema, inferred_rounds=inferred_rounds, tickrate=tickrate)
    if schema.observer_team_column is not None:
        work["observer_team"] = pd.to_numeric(work[schema.observer_team_column], errors="coerce")
    else:
        work["observer_team"] = pd.Series([pd.NA] * len(work), index=work.index)
    if schema.target_team_column is not None:
        work["target_team"] = pd.to_numeric(work[schema.target_team_column], errors="coerce")
    else:
        work["target_team"] = pd.Series([pd.NA] * len(work), index=work.index)
    work = work.dropna(subset=["round_id", "tick"])
    work = work[(work["observer"] != "") & (work["target"] != "")]
    work = work[(work["observer_key"] != "") & (work["target_key"] != "")]
    return work.loc[
        :,
        ["round_id", "tick", "observer", "target", "observer_key", "target_key", "is_visible", "seconds", "observer_team", "target_team"],
    ]


def _filter_enemy_pairs(decoded_rows: pd.DataFrame) -> pd.DataFrame:
    if decoded_rows.empty:
        return decoded_rows
    return decoded_rows[
        decoded_rows["observer_team"].isna()
        | decoded_rows["target_team"].isna()
        | (decoded_rows["observer_team"] != decoded_rows["target_team"])
    ].copy()


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
    work = _filter_enemy_pairs(decoded_rows)
    if work.empty:
        return []
    if "observer_key" not in work.columns:
        work = work.copy()
        work["observer_key"] = work["observer"].map(_coerce_text)
    if "target_key" not in work.columns:
        work = work.copy()
        work["target_key"] = work["target"].map(_coerce_text)
    work = work.sort_values(["round_id", "observer_key", "target_key", "tick"]).reset_index(drop=True)

    events: list[InfoEvent] = []
    pair_state: dict[tuple[int, str, str], dict[str, object]] = {}
    for row in work.to_dict("records"):
        round_id = int(row["round_id"])
        tick = int(row["tick"])
        observer = str(row["observer"])
        target = str(row["target"])
        observer_key = str(row["observer_key"])
        target_key = str(row["target_key"])
        is_visible = bool(row["is_visible"])
        seconds = float(row["seconds"])
        key = (round_id, observer_key, target_key)
        state = pair_state.setdefault(
            key,
            {
                "has_visible_before": False,
                "currently_visible": False,
                "last_visible_seconds": None,
            },
        )
        if not is_visible:
            state["currently_visible"] = False
            continue
        should_emit = False
        if not bool(state["has_visible_before"]):
            should_emit = True
        elif bool(state["currently_visible"]):
            should_emit = False
        else:
            last_visible_seconds = state["last_visible_seconds"]
            gap_seconds = float("inf") if last_visible_seconds is None else (seconds - float(last_visible_seconds))
            should_emit = gap_seconds >= VISIBILITY_REDISCOVERY_GAP_SECONDS
        if should_emit:
            events.append(
                _make_info_event(
                    round_id=round_id,
                    tick=tick,
                    seconds=seconds,
                    observer=observer,
                    target=target,
                    observer_key=observer_key,
                    target_key=target_key,
                )
            )
        state["has_visible_before"] = True
        state["currently_visible"] = True
        state["last_visible_seconds"] = seconds
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
            extra_note="artifact_or_schema_unavailable",
        )
        return []
    build_started_at = time.perf_counter()
    _profile_info_events_stage(
        "info_events.build_spotted.start",
        round_id=round_id,
        rows_before=len(visibility_table),
        selected_columns=schema.required_columns,
        extra_note="event_scope=all_rounds" if round_id is None else f"event_scope=round_{int(round_id)}",
    )
    decoded_rows = _decode_visibility_rows(
        visibility_table,
        schema=schema,
        inferred_rounds=inferred_rounds,
        tickrate=64.0 if tickrate is None else float(tickrate),
    )
    unformatted_events = build_visibility_spotted_events(decoded_rows)
    _profile_info_events_stage(
        "info_events.build_spotted.end",
        started_at=build_started_at,
        round_id=round_id,
        rows_before=len(visibility_table),
        rows_after=len(decoded_rows),
        events_count=len(unformatted_events),
        selected_columns=schema.required_columns,
        extra_note="event_scope=all_rounds" if round_id is None else f"event_scope=round_{int(round_id)}",
    )

    format_started_at = time.perf_counter()
    _profile_info_events_stage(
        "info_events.format_lines.start",
        round_id=round_id,
        rows_before=len(unformatted_events),
        events_count=len(unformatted_events),
        selected_columns=("seconds", "observer", "target", "message"),
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
        "info_events.format_lines.end",
        started_at=format_started_at,
        round_id=round_id,
        rows_before=len(unformatted_events),
        rows_after=len(formatted_events),
        events_count=len(formatted_events),
        selected_columns=("seconds", "observer", "target", "message"),
    )
    _profile_info_events_stage(
        "info_events.load.end",
        started_at=load_started_at,
        round_id=round_id,
        rows_before=len(visibility_table),
        rows_after=len(decoded_rows),
        events_count=len(formatted_events),
        selected_columns=schema.required_columns,
        extra_note="round_scope=all" if round_id is None else f"round_scope=single target_round_id={int(round_id)}",
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
