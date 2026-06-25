from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import time

import pandas as pd

from wall.domain.bomb import BombTimeline
from wall.domain.player import RoundPlayers
from wall.domain.sound import SoundTimeline
from wall.domain.utility import UtilityTimeline
from wall.domain.visibility import VisibilityTimeline
from wall.domain.visibility_profile import VisibilityProfile
from wall.io.table_io import read_table_with_fallback
from wall.profile import frame_tick_range, profile_log


FLASH_EFFECT_TICKS = 128
HE_EFFECT_TICKS = 28
SMOKE_RADIUS_WORLD = 176.0
SMOKE_DEPLOY_TICKS = 18
INFERNO_DURATION_SECONDS = 7.03125
INFERNO_CT_RADIUS_WORLD = 128.0
INFERNO_T_RADIUS_WORLD = 144.0


def require_column(df: pd.DataFrame, column: str, file_label: str) -> None:
    if column not in df.columns:
        raise ValueError(f"{file_label} is missing required column: {column}")


def require_round_time_columns(df: pd.DataFrame, file_label: str) -> None:
    for column in ("inferred_round_id", "inferred_round_tick", "inferred_round_seconds"):
        require_column(df, column, file_label)


def load_round_data(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    ticks, ticks_label = read_table_with_fallback(data_dir, "ticks", required=True)
    deaths, deaths_label = read_table_with_fallback(data_dir, "player_death", required=True)
    fires, fires_label = read_table_with_fallback(data_dir, "fire_bullets")
    hurts, hurts_label = read_table_with_fallback(data_dir, "player_hurt")
    hits, hits_label = read_table_with_fallback(data_dir, "player_bullet_hit")
    footsteps, footsteps_label = read_table_with_fallback(data_dir, "player_footstep")
    smoke_detonates, smoke_detonates_label = read_table_with_fallback(data_dir, "smokegrenade_detonate")
    flash_detonates, flash_detonates_label = read_table_with_fallback(data_dir, "flashbang_detonate")
    he_detonates, he_detonates_label = read_table_with_fallback(data_dir, "hegrenade_detonate")
    blinds, blinds_label = read_table_with_fallback(data_dir, "player_blind")
    bomb_pickups, bomb_pickups_label = read_table_with_fallback(data_dir, "bomb_pickup")
    bomb_drops, bomb_drops_label = read_table_with_fallback(data_dir, "bomb_dropped")
    bomb_begin_plants, bomb_begin_plants_label = read_table_with_fallback(data_dir, "bomb_beginplant")
    bomb_plants, bomb_plants_label = read_table_with_fallback(data_dir, "bomb_planted")
    bomb_defuses, bomb_defuses_label = read_table_with_fallback(data_dir, "bomb_defused")
    bomb_begin_defuses, bomb_begin_defuses_label = read_table_with_fallback(data_dir, "bomb_begindefuse")
    bomb_abort_defuses, bomb_abort_defuses_label = read_table_with_fallback(data_dir, "bomb_abortdefuse")
    bomb_explodes, bomb_explodes_label = read_table_with_fallback(data_dir, "bomb_exploded")
    smoke_expires, smoke_expires_label = read_table_with_fallback(data_dir, "smokegrenade_expired")
    inferno_starts, inferno_starts_label = read_table_with_fallback(data_dir, "inferno_startburn")
    grenade_trajectory_segments, grenade_trajectory_segments_label = read_table_with_fallback(
        data_dir,
        "grenade_trajectory_segments",
    )
    sound_events, sound_events_label = read_table_with_fallback(data_dir, "sound_events")
    inferred_rounds, inferred_rounds_label = read_table_with_fallback(data_dir, "inferred_rounds", required=True)
    metadata_path = data_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    require_round_time_columns(ticks, ticks_label)
    require_round_time_columns(deaths, deaths_label)
    if not fires.empty:
        require_round_time_columns(fires, fires_label)
    if not hurts.empty:
        require_round_time_columns(hurts, hurts_label)
    if not hits.empty:
        require_round_time_columns(hits, hits_label)
    if not footsteps.empty:
        require_round_time_columns(footsteps, footsteps_label)
    if not smoke_detonates.empty:
        require_round_time_columns(smoke_detonates, smoke_detonates_label)
    if not flash_detonates.empty:
        require_round_time_columns(flash_detonates, flash_detonates_label)
    if not he_detonates.empty:
        require_round_time_columns(he_detonates, he_detonates_label)
    if not blinds.empty:
        require_round_time_columns(blinds, blinds_label)
    if not bomb_pickups.empty:
        require_round_time_columns(bomb_pickups, bomb_pickups_label)
    if not bomb_drops.empty:
        require_round_time_columns(bomb_drops, bomb_drops_label)
    if not bomb_begin_plants.empty:
        require_round_time_columns(bomb_begin_plants, bomb_begin_plants_label)
    if not bomb_plants.empty:
        require_round_time_columns(bomb_plants, bomb_plants_label)
    if not bomb_defuses.empty:
        require_round_time_columns(bomb_defuses, bomb_defuses_label)
    if not bomb_begin_defuses.empty:
        require_round_time_columns(bomb_begin_defuses, bomb_begin_defuses_label)
    if not bomb_abort_defuses.empty:
        require_round_time_columns(bomb_abort_defuses, bomb_abort_defuses_label)
    if not bomb_explodes.empty:
        require_round_time_columns(bomb_explodes, bomb_explodes_label)
    if not smoke_expires.empty:
        require_round_time_columns(smoke_expires, smoke_expires_label)
    if not inferno_starts.empty:
        require_round_time_columns(inferno_starts, inferno_starts_label)
    if not grenade_trajectory_segments.empty:
        require_column(grenade_trajectory_segments, "round_id", grenade_trajectory_segments_label)
        require_column(grenade_trajectory_segments, "start_tick", grenade_trajectory_segments_label)
        require_column(grenade_trajectory_segments, "end_tick", grenade_trajectory_segments_label)
    if not sound_events.empty:
        require_round_time_columns(sound_events, sound_events_label)
    require_column(inferred_rounds, "inferred_round_id", inferred_rounds_label)
    return ticks, deaths, fires, hurts, hits, footsteps, smoke_detonates, flash_detonates, he_detonates, blinds, bomb_pickups, bomb_drops, bomb_begin_plants, bomb_plants, bomb_defuses, bomb_begin_defuses, bomb_abort_defuses, bomb_explodes, smoke_expires, inferno_starts, grenade_trajectory_segments, sound_events, inferred_rounds, metadata


@dataclass
class RoundData:
    round_ticks: pd.DataFrame
    round_players: RoundPlayers
    utility_timeline: UtilityTimeline
    bomb_timeline: BombTimeline
    sound_timeline: SoundTimeline
    visibility_timeline: VisibilityTimeline
    frame_ticks: list[int]
    round_start_tick: int
    freeze_start_tick: int
    freeze_end_tick: int
    live_start_tick: int
    round_id: int


def _slice_round_table(df: pd.DataFrame, round_id: int) -> pd.DataFrame:
    if df.empty or "inferred_round_id" not in df.columns:
        return df
    round_ids = df["inferred_round_id"].dropna().astype(int).unique().tolist()
    if len(round_ids) == 1 and int(round_ids[0]) == int(round_id):
        return df
    return df[df["inferred_round_id"] == int(round_id)].copy()


def _sort_if_needed(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if df.empty:
        return df
    available_columns = [column for column in columns if column in df.columns]
    if not available_columns:
        return df
    sort_view = df.loc[:, available_columns]
    if pd.MultiIndex.from_frame(sort_view).is_monotonic_increasing:
        return df
    return df.sort_values(available_columns).copy()


def get_round_data(
    ticks: pd.DataFrame,
    deaths: pd.DataFrame,
    fires: pd.DataFrame,
    hurts: pd.DataFrame,
    hits: pd.DataFrame,
    footsteps: pd.DataFrame,
    smoke_detonates: pd.DataFrame,
    flash_detonates: pd.DataFrame,
    he_detonates: pd.DataFrame,
    blinds: pd.DataFrame,
    bomb_pickups: pd.DataFrame,
    bomb_drops: pd.DataFrame,
    bomb_begin_plants: pd.DataFrame,
    bomb_plants: pd.DataFrame,
    bomb_defuses: pd.DataFrame,
    bomb_begin_defuses: pd.DataFrame,
    bomb_abort_defuses: pd.DataFrame,
    bomb_explodes: pd.DataFrame,
    smoke_expires: pd.DataFrame,
    inferno_starts: pd.DataFrame,
    sound_events: pd.DataFrame,
    inferred_rounds: pd.DataFrame,
    round_id: int,
    tickrate: float = 64.0,
    map_name: str | None = None,
    visibility_profile: VisibilityProfile | None = None,
    visibility_checker=None,
    grenade_trajectory_segments: pd.DataFrame | None = None,
) -> RoundData:
    round_lookup_started_at = time.perf_counter()
    round_ticks = _slice_round_table(ticks, round_id)
    round_deaths = _slice_round_table(deaths, round_id)
    round_fires = _slice_round_table(fires, round_id) if not fires.empty else pd.DataFrame()
    round_hurts = _slice_round_table(hurts, round_id) if not hurts.empty else pd.DataFrame()
    round_smoke_detonates = _slice_round_table(smoke_detonates, round_id) if not smoke_detonates.empty else pd.DataFrame()
    round_flash_detonates = _slice_round_table(flash_detonates, round_id) if not flash_detonates.empty else pd.DataFrame()
    round_he_detonates = _slice_round_table(he_detonates, round_id) if not he_detonates.empty else pd.DataFrame()
    round_blinds = _slice_round_table(blinds, round_id) if not blinds.empty else pd.DataFrame()
    round_bomb_pickups = _slice_round_table(bomb_pickups, round_id) if not bomb_pickups.empty else pd.DataFrame()
    round_bomb_drops = _slice_round_table(bomb_drops, round_id) if not bomb_drops.empty else pd.DataFrame()
    round_bomb_begin_plants = _slice_round_table(bomb_begin_plants, round_id) if not bomb_begin_plants.empty else pd.DataFrame()
    round_bomb_plants = _slice_round_table(bomb_plants, round_id) if not bomb_plants.empty else pd.DataFrame()
    round_bomb_defuses = _slice_round_table(bomb_defuses, round_id) if not bomb_defuses.empty else pd.DataFrame()
    round_bomb_begin_defuses = _slice_round_table(bomb_begin_defuses, round_id) if not bomb_begin_defuses.empty else pd.DataFrame()
    round_bomb_abort_defuses = _slice_round_table(bomb_abort_defuses, round_id) if not bomb_abort_defuses.empty else pd.DataFrame()
    round_bomb_explodes = _slice_round_table(bomb_explodes, round_id) if not bomb_explodes.empty else pd.DataFrame()
    round_smoke_expires = _slice_round_table(smoke_expires, round_id) if not smoke_expires.empty else pd.DataFrame()
    round_inferno_starts = _slice_round_table(inferno_starts, round_id) if not inferno_starts.empty else pd.DataFrame()
    grenade_segments_source = pd.DataFrame() if grenade_trajectory_segments is None else grenade_trajectory_segments
    round_grenade_trajectory_segments = (
        grenade_segments_source[grenade_segments_source["round_id"] == int(round_id)].copy()
        if not grenade_segments_source.empty and "round_id" in grenade_segments_source.columns
        else pd.DataFrame()
    )
    round_sound_events = _slice_round_table(sound_events, round_id) if not sound_events.empty else pd.DataFrame()
    round_info = inferred_rounds[inferred_rounds["inferred_round_id"] == round_id].copy() if not inferred_rounds.empty else pd.DataFrame()
    if visibility_profile is not None:
        visibility_profile.round_lookup_seconds += time.perf_counter() - round_lookup_started_at
    if round_ticks.empty:
        raise ValueError(f"No ticks found for inferred round {round_id}")
    round_ticks = _sort_if_needed(round_ticks, ["tick", "name"])
    round_deaths = _sort_if_needed(round_deaths, ["tick"])
    round_fires = _sort_if_needed(round_fires, ["tick"])
    round_hurts = _sort_if_needed(round_hurts, ["tick"])
    round_blinds = _sort_if_needed(round_blinds, ["tick"])
    round_smoke_detonates = _sort_if_needed(round_smoke_detonates, ["tick"])
    round_smoke_expires = _sort_if_needed(round_smoke_expires, ["tick"])
    round_flash_detonates = _sort_if_needed(round_flash_detonates, ["tick"])
    round_he_detonates = _sort_if_needed(round_he_detonates, ["tick"])
    round_inferno_starts = _sort_if_needed(round_inferno_starts, ["tick"])
    round_grenade_trajectory_segments = _sort_if_needed(
        round_grenade_trajectory_segments,
        ["grenade_id", "segment_index", "start_tick"],
    )
    round_sound_events = _sort_if_needed(round_sound_events, ["tick", "sound_kind"])
    profile_log(
        "round_data.slice",
        started_at=round_lookup_started_at,
        df=round_ticks,
        round_id=round_id,
        tick_range=frame_tick_range(round_ticks),
    )
    frame_ticks = [int(tick) for tick in round_ticks["tick"].sort_values().unique().tolist()]
    player_frame_started_at = time.perf_counter()
    round_players = RoundPlayers.from_round_ticks(
        round_ticks,
        round_deaths,
        round_fires=round_fires,
        round_hurts=round_hurts,
        round_blinds=round_blinds,
        tickrate=tickrate,
        visibility_profile=visibility_profile,
    )
    if visibility_profile is not None:
        visibility_profile.player_frame_extraction_seconds += time.perf_counter() - player_frame_started_at
    profile_log(
        "round_players.build",
        started_at=player_frame_started_at,
        df=round_ticks,
        round_id=round_id,
        tick_range=frame_tick_range(round_ticks),
    )

    def lookup_player_team_num(player_name: str, steamid: str | None, tick: int) -> int | None:
        frame = round_players.frame_at(steamid=steamid, name=player_name, tick=tick)
        if frame is None:
            return None
        return frame.team_num

    utility_timeline = UtilityTimeline(
        round_smoke_detonates=round_smoke_detonates,
        round_smoke_expires=round_smoke_expires,
        round_flash_detonates=round_flash_detonates,
        round_he_detonates=round_he_detonates,
        round_inferno_starts=round_inferno_starts,
        round_grenade_trajectory_segments=round_grenade_trajectory_segments,
        flash_effect_ticks=FLASH_EFFECT_TICKS,
        he_effect_ticks=HE_EFFECT_TICKS,
        inferno_duration_ticks=int(round(tickrate * INFERNO_DURATION_SECONDS)),
        inferno_ct_radius_world=INFERNO_CT_RADIUS_WORLD,
        inferno_t_radius_world=INFERNO_T_RADIUS_WORLD,
        smoke_radius_world=SMOKE_RADIUS_WORLD,
        smoke_deploy_ticks=SMOKE_DEPLOY_TICKS,
        player_team_lookup=lookup_player_team_num,
    )
    bomb_timeline = BombTimeline(
        round_bomb_pickups=round_bomb_pickups,
        round_bomb_drops=round_bomb_drops,
        round_bomb_begin_plants=round_bomb_begin_plants,
        round_bomb_plants=round_bomb_plants,
        round_bomb_defuses=round_bomb_defuses,
        round_bomb_begin_defuses=round_bomb_begin_defuses,
        round_bomb_abort_defuses=round_bomb_abort_defuses,
        round_bomb_explodes=round_bomb_explodes,
        frame_ticks=frame_ticks,
        tickrate=tickrate,
        round_players=round_players,
    )
    sound_timeline = SoundTimeline(round_sound_events)
    visibility_timeline = VisibilityTimeline(
        round_players=round_players,
        fov_deg=90.0,
        visibility_checker=visibility_checker,
        visibility_profile=visibility_profile,
    )
    round_start_tick = int(round_ticks["tick"].min())
    freeze_start_tick = round_start_tick
    freeze_end_tick = round_start_tick
    live_start_tick = round_start_tick
    if not round_info.empty:
        row = round_info.iloc[0]
        freeze_start_tick = int(pd.to_numeric(row.get("freeze_start_tick"), errors="coerce")) if pd.notna(pd.to_numeric(row.get("freeze_start_tick"), errors="coerce")) else round_start_tick
        freeze_end_tick = int(pd.to_numeric(row.get("freeze_end_tick"), errors="coerce")) if pd.notna(pd.to_numeric(row.get("freeze_end_tick"), errors="coerce")) else freeze_start_tick
        live_start_tick = int(pd.to_numeric(row.get("live_start_tick"), errors="coerce")) if pd.notna(pd.to_numeric(row.get("live_start_tick"), errors="coerce")) else round_start_tick
    return RoundData(
        round_ticks=round_ticks,
        round_players=round_players,
        utility_timeline=utility_timeline,
        bomb_timeline=bomb_timeline,
        sound_timeline=sound_timeline,
        visibility_timeline=visibility_timeline,
        frame_ticks=frame_ticks,
        round_start_tick=round_start_tick,
        freeze_start_tick=freeze_start_tick,
        freeze_end_tick=freeze_end_tick,
        live_start_tick=live_start_tick,
        round_id=round_id,
    )
