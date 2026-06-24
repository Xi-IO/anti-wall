from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import time

import pandas as pd

from wall.dataset.rounds import RoundData, get_round_data, require_column, require_round_time_columns
from wall.profile import (
    current_rss_mb,
    frame_tick_range,
    profile_log,
    profile_note,
    profile_table_log,
)
from wall.domain.visibility_profile import VisibilityProfile
from wall.io.table_io import detect_existing_tables, read_table_with_fallback
from wall.visibility.context import MapVisibilityContext

try:
    import pyarrow.parquet as pq
except ModuleNotFoundError:
    pq = None


VIEWER_TICK_COLUMNS = (
    "tick",
    "inferred_round_id",
    "inferred_round_tick",
    "inferred_round_seconds",
    "name",
    "steamid",
    "active_weapon_name",
    "has_defuser",
    "X",
    "Y",
    "Z",
    "yaw",
    "pitch",
    "team_num",
    "health",
    "ducking",
    "is_airborne",
    "velocity_X",
    "velocity_Y",
    "velocity_Z",
)
HUD_TICK_COLUMNS = ("tick", "inferred_round_id", "name", "team_num")


def _parquet_schema_columns(path: Path) -> set[str] | None:
    if pq is None:
        return None
    return set(pq.ParquetFile(path).schema.names)


def _parquet_tick_filters(inferred_rounds: pd.DataFrame, round_id: int) -> tuple[list[tuple[str, str, int]] | list[list[tuple[str, str, int]]] | None, str]:
    round_info = inferred_rounds[inferred_rounds["inferred_round_id"] == int(round_id)]
    if round_info.empty:
        return None, "missing round metadata; no tick-range filter"
    row = round_info.iloc[0]
    start_tick = pd.to_numeric(row.get("start_tick"), errors="coerce")
    end_tick = pd.to_numeric(row.get("end_tick"), errors="coerce")
    if pd.isna(start_tick) or pd.isna(end_tick):
        return None, "round tick range unavailable; no tick-range filter"
    return [[("tick", ">=", int(start_tick)), ("tick", "<=", int(end_tick))]], "fallback tick-range filter"


def _filter_columns(columns: tuple[str, ...], available_columns: set[str] | None) -> list[str]:
    if available_columns is None:
        return list(columns)
    return [column for column in columns if column in available_columns]


def _read_round_scoped_table(
    data_dir: Path,
    stem: str,
    *,
    round_id: int,
    required: bool = False,
    require_round_columns: bool = True,
) -> pd.DataFrame:
    started_at = time.perf_counter()
    rss_before_mb = current_rss_mb()
    table, label = read_table_with_fallback(data_dir, stem, required=required)
    if table.empty:
        profile_table_log(
            stem,
            round_id=round_id,
            read_path="missing" if label.endswith(".missing") else f"{Path(label).suffix.lstrip('.')} empty",
            filter_column="inferred_round_id" if require_round_columns else None,
            started_at=started_at,
            rss_before_mb=rss_before_mb,
            before_df=table,
            after_df=table,
            note=f"source={label}",
        )
        return table
    if require_round_columns:
        require_round_time_columns(table, label)
        filtered = table[table["inferred_round_id"] == int(round_id)].copy()
        read_path = f"{Path(label).suffix.lstrip('.')} fallback"
        if label.endswith(".parquet"):
            read_path = "parquet full-table fallback"
        elif label.endswith(".csv"):
            read_path = "csv fallback"
        profile_table_log(
            stem,
            round_id=round_id,
            read_path=read_path,
            filter_column="inferred_round_id",
            started_at=started_at,
            rss_before_mb=rss_before_mb,
            before_df=table,
            after_df=filtered,
            note=f"source={label}",
        )
        return filtered
    result = table.copy()
    read_path = f"{Path(label).suffix.lstrip('.')} unfiltered"
    if label.endswith(".parquet"):
        read_path = "parquet full-table fallback"
    elif label.endswith(".csv"):
        read_path = "csv fallback"
    profile_table_log(
        stem,
        round_id=round_id,
        read_path=read_path,
        filter_column=None,
        started_at=started_at,
        rss_before_mb=rss_before_mb,
        before_df=table,
        after_df=result,
        note=f"source={label}",
    )
    return result


@dataclass(frozen=True)
class DatasetIndex:
    data_dir: Path
    inferred_rounds: pd.DataFrame
    metadata: dict
    table_paths: dict[str, Path]
    artifacts: dict[str, bool]
    hud_numbers_cache: dict[int, dict[str, int]] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_data_dir(cls, data_dir: Path) -> "DatasetIndex":
        started_at = time.perf_counter()
        inferred_rounds, inferred_rounds_label = read_table_with_fallback(data_dir, "inferred_rounds", required=True)
        require_column(inferred_rounds, "inferred_round_id", inferred_rounds_label)
        metadata_path = data_dir / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
        table_paths = {stem: path for stem, path, _ in detect_existing_tables(data_dir)}
        artifacts = {
            "visibility_parquet": (data_dir / "visibility.parquet").exists(),
            "visibility_csv": (data_dir / "visibility.csv").exists(),
        }
        index = cls(
            data_dir=Path(data_dir),
            inferred_rounds=inferred_rounds,
            metadata=metadata,
            table_paths=table_paths,
            artifacts=artifacts,
        )
        profile_log(
            "dataset_index.load",
            started_at=started_at,
            df=inferred_rounds,
            note=profile_note(
                f"tables={len(table_paths)}",
                f"artifacts={sorted(name for name, present in artifacts.items() if present)}",
            ),
        )
        return index

    @property
    def round_ids(self) -> list[int]:
        return sorted(self.inferred_rounds["inferred_round_id"].astype(int).tolist())

    @property
    def map_name(self) -> str | None:
        return self.metadata.get("derived", {}).get("map_name")

    def _read_ticks_for_round(self, round_id: int, *, columns: tuple[str, ...]) -> pd.DataFrame:
        started_at = time.perf_counter()
        rss_before_mb = current_rss_mb()
        ticks_path = self.table_paths.get("ticks")
        if ticks_path is None:
            raise FileNotFoundError(
                f"Missing required table 'ticks' in {self.data_dir}. Expected one of: ticks.parquet, ticks.csv"
            )
        if ticks_path.suffix.lower() == ".parquet":
            available_columns = _parquet_schema_columns(ticks_path)
            projected_columns = _filter_columns(columns, available_columns)
            read_note = "parquet projected"
            filters = None
            if available_columns is None or "inferred_round_id" in available_columns:
                filters = [("inferred_round_id", "==", int(round_id))]
                read_note = "parquet inferred_round_id filter"
            elif "tick" in (available_columns or set()):
                filters, read_note = _parquet_tick_filters(self.inferred_rounds, round_id)
            ticks = pd.read_parquet(
                ticks_path,
                columns=projected_columns or None,
                filters=filters,
            )
            before_df = ticks
            if not ticks.empty and "inferred_round_id" in ticks.columns:
                ticks = ticks[ticks["inferred_round_id"] == int(round_id)]
            read_path = "parquet filtered" if filters is not None else "parquet full-table fallback"
            filter_column = None
            if filters == [("inferred_round_id", "==", int(round_id))]:
                filter_column = "inferred_round_id"
            elif filters is not None:
                filter_column = "tick"
            profile_table_log(
                "ticks",
                round_id=round_id,
                read_path=read_path,
                filter_column=filter_column,
                started_at=started_at,
                rss_before_mb=rss_before_mb,
                before_df=before_df,
                after_df=ticks,
                note=profile_note(read_note, f"source={ticks_path.name}", f"columns={projected_columns}"),
            )
            return ticks
        ticks, label = read_table_with_fallback(self.data_dir, "ticks", required=True)
        before_df = ticks
        if "inferred_round_id" in ticks.columns:
            ticks = ticks[ticks["inferred_round_id"] == int(round_id)].copy()
        profile_table_log(
            "ticks",
            round_id=round_id,
            read_path="csv fallback" if label.endswith(".csv") else "parquet full-table fallback",
            filter_column="inferred_round_id" if "inferred_round_id" in before_df.columns else None,
            started_at=started_at,
            rss_before_mb=rss_before_mb,
            before_df=before_df,
            after_df=ticks,
            note=f"source={label}",
        )
        return ticks

    def _round_player_numbers_from_ticks(self, ticks: pd.DataFrame) -> dict[str, int]:
        if ticks.empty or "name" not in ticks.columns:
            return {}
        work = ticks.loc[:, [column for column in ("tick", "name", "team_num") if column in ticks.columns]].copy()
        work = work[work["name"].notna()].copy()
        work["team_num"] = pd.to_numeric(work.get("team_num"), errors="coerce")
        work = work[work["team_num"].isin([2, 3])]
        if not work.empty:
            work = work.sort_values(["tick", "name"])
        first_seen = work.groupby("name", sort=False).first().reset_index() if not work.empty else pd.DataFrame(columns=["name", "tick", "team_num"])

        player_numbers: dict[str, int] = {}
        team_slots = {2: [1, 2, 3, 4, 5], 3: [6, 7, 8, 9, 10]}
        for team_num in (2, 3):
            team_rows = first_seen[first_seen["team_num"] == team_num].sort_values(["tick", "name"])
            for slot, player in zip(team_slots[team_num], team_rows["name"].tolist()):
                player_numbers[str(player)] = slot

        remaining_players = sorted(set(ticks["name"].dropna().astype(str)) - set(player_numbers))
        next_number = 11
        for player in remaining_players:
            player_numbers[player] = next_number
            next_number += 1
        return player_numbers

    def build_round_data(
        self,
        round_id: int,
        *,
        tickrate: float,
        visibility_profile: VisibilityProfile | None = None,
        map_visibility_context: MapVisibilityContext | None = None,
    ) -> RoundData:
        function_started_at = time.perf_counter()
        profile_log("build_round_data.enter", round_id=round_id, map_name=self.map_name)
        context_started_at = time.perf_counter()
        profile_log("build_round_data.visibility_context.start", round_id=round_id, map_name=self.map_name)
        if map_visibility_context is not None:
            context = map_visibility_context
        elif self.artifacts.get("visibility_parquet", False):
            context = MapVisibilityContext.precomputed(
                self.map_name,
                visibility_artifact_path=self.data_dir / "visibility.parquet",
            )
        else:
            context = MapVisibilityContext.unavailable(self.map_name)
        profile_log(
            "build_round_data.visibility_context.end",
            started_at=context_started_at,
            round_id=round_id,
            map_name=self.map_name,
            note=f"mode={context.mode}",
        )
        started_at = time.perf_counter()
        rss_before_mb = current_rss_mb()
        profile_log("build_round_data.start", started_at=function_started_at, round_id=round_id, map_name=self.map_name, note=f"rss_mb={rss_before_mb:.1f}" if rss_before_mb is not None else None)
        ticks = self._read_ticks_for_round(round_id, columns=VIEWER_TICK_COLUMNS)
        deaths = _read_round_scoped_table(self.data_dir, "player_death", round_id=round_id, required=True)
        fires = _read_round_scoped_table(self.data_dir, "fire_bullets", round_id=round_id)
        hurts = _read_round_scoped_table(self.data_dir, "player_hurt", round_id=round_id)
        hits = _read_round_scoped_table(self.data_dir, "player_bullet_hit", round_id=round_id)
        footsteps = _read_round_scoped_table(self.data_dir, "player_footstep", round_id=round_id)
        smoke_detonates = _read_round_scoped_table(self.data_dir, "smokegrenade_detonate", round_id=round_id)
        flash_detonates = _read_round_scoped_table(self.data_dir, "flashbang_detonate", round_id=round_id)
        he_detonates = _read_round_scoped_table(self.data_dir, "hegrenade_detonate", round_id=round_id)
        blinds = _read_round_scoped_table(self.data_dir, "player_blind", round_id=round_id)
        bomb_pickups = _read_round_scoped_table(self.data_dir, "bomb_pickup", round_id=round_id)
        bomb_drops = _read_round_scoped_table(self.data_dir, "bomb_dropped", round_id=round_id)
        bomb_begin_plants = _read_round_scoped_table(self.data_dir, "bomb_beginplant", round_id=round_id)
        bomb_plants = _read_round_scoped_table(self.data_dir, "bomb_planted", round_id=round_id)
        bomb_defuses = _read_round_scoped_table(self.data_dir, "bomb_defused", round_id=round_id)
        bomb_begin_defuses = _read_round_scoped_table(self.data_dir, "bomb_begindefuse", round_id=round_id)
        bomb_abort_defuses = _read_round_scoped_table(self.data_dir, "bomb_abortdefuse", round_id=round_id)
        bomb_explodes = _read_round_scoped_table(self.data_dir, "bomb_exploded", round_id=round_id)
        smoke_expires = _read_round_scoped_table(self.data_dir, "smokegrenade_expired", round_id=round_id)
        inferno_starts = _read_round_scoped_table(self.data_dir, "inferno_startburn", round_id=round_id)
        grenades = _read_round_scoped_table(self.data_dir, "grenades", round_id=round_id)
        sound_events = _read_round_scoped_table(self.data_dir, "sound_events", round_id=round_id)
        round_data = get_round_data(
            ticks=ticks,
            deaths=deaths,
            fires=fires,
            hurts=hurts,
            hits=hits,
            footsteps=footsteps,
            smoke_detonates=smoke_detonates,
            flash_detonates=flash_detonates,
            he_detonates=he_detonates,
            blinds=blinds,
            bomb_pickups=bomb_pickups,
            bomb_drops=bomb_drops,
            bomb_begin_plants=bomb_begin_plants,
            bomb_plants=bomb_plants,
            bomb_defuses=bomb_defuses,
            bomb_begin_defuses=bomb_begin_defuses,
            bomb_abort_defuses=bomb_abort_defuses,
            bomb_explodes=bomb_explodes,
            smoke_expires=smoke_expires,
            inferno_starts=inferno_starts,
            grenades=grenades,
            sound_events=sound_events,
            inferred_rounds=self.inferred_rounds,
            round_id=round_id,
            tickrate=tickrate,
            map_name=self.map_name,
            visibility_profile=visibility_profile,
            visibility_checker=None if context is None else context.visibility_checker,
        )
        if hasattr(round_data, "round_ticks"):
            profile_log(
                "round_data.build",
                started_at=started_at,
                df=round_data.round_ticks,
                round_id=round_id,
                tick_range=frame_tick_range(round_data.round_ticks),
                note=profile_note(
                    "ticks round-scoped; non-ticks may still use full-table fallback",
                    f"rss_before_mb={rss_before_mb:.1f}" if rss_before_mb is not None else None,
                    f"rss_after_mb={current_rss_mb():.1f}" if current_rss_mb() is not None else None,
                ),
            )
        return round_data

    def build_demo_hud_numbers(self, round_id: int) -> dict[str, int]:
        cached = self.hud_numbers_cache.get(int(round_id))
        if cached is not None:
            return cached
        started_at = time.perf_counter()
        ticks = self._read_ticks_for_round(int(round_id), columns=HUD_TICK_COLUMNS)
        player_numbers = self._round_player_numbers_from_ticks(ticks)
        self.hud_numbers_cache[int(round_id)] = player_numbers
        profile_log(
            "hud_numbers.build",
            started_at=started_at,
            df=ticks,
            round_id=round_id,
            tick_range=frame_tick_range(ticks),
            note=f"players={len(player_numbers)}",
        )
        return player_numbers
