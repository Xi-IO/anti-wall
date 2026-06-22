from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import pandas as pd
from PIL import ImageColor

try:
    from awpy.data.map_data import MAP_DATA
    from awpy.plot.utils import game_to_pixel_axis
except ModuleNotFoundError:
    MAP_DATA = {}
    game_to_pixel_axis = None

from wall.domain.bomb import BombTimeline
from wall.domain.player import RoundPlayers
from wall.domain.sound import SoundTimeline
from wall.domain.utility import UtilityTimeline
from wall.io.table_io import read_table_with_fallback


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


def team_color(team_num: int | float | None) -> tuple[int, int, int]:
    if team_num == 3:
        return ImageColor.getrgb("#1991BD")
    if team_num == 2:
        return ImageColor.getrgb("#D9CD21")
    return ImageColor.getrgb("#808080")


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
    grenades, grenades_label = read_table_with_fallback(data_dir, "grenades")
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
    if not grenades.empty:
        require_round_time_columns(grenades, grenades_label)
    if not sound_events.empty:
        require_round_time_columns(sound_events, sound_events_label)
    require_column(inferred_rounds, "inferred_round_id", inferred_rounds_label)
    return ticks, deaths, fires, hurts, hits, footsteps, smoke_detonates, flash_detonates, he_detonates, blinds, bomb_pickups, bomb_drops, bomb_begin_plants, bomb_plants, bomb_defuses, bomb_begin_defuses, bomb_abort_defuses, bomb_explodes, smoke_expires, inferno_starts, grenades, sound_events, inferred_rounds, metadata


@dataclass
class RoundData:
    round_ticks: pd.DataFrame
    round_players: RoundPlayers
    utility_timeline: UtilityTimeline
    bomb_timeline: BombTimeline
    sound_timeline: SoundTimeline
    frame_ticks: list[int]
    round_start_tick: int
    round_id: int


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
    grenades: pd.DataFrame,
    sound_events: pd.DataFrame,
    round_id: int,
    tickrate: float = 64.0,
) -> RoundData:
    round_ticks = ticks[ticks["inferred_round_id"] == round_id].copy()
    round_deaths = deaths[deaths["inferred_round_id"] == round_id].copy()
    round_fires = fires[fires["inferred_round_id"] == round_id].copy() if not fires.empty else pd.DataFrame()
    round_hurts = hurts[hurts["inferred_round_id"] == round_id].copy() if not hurts.empty else pd.DataFrame()
    round_smoke_detonates = smoke_detonates[smoke_detonates["inferred_round_id"] == round_id].copy() if not smoke_detonates.empty else pd.DataFrame()
    round_flash_detonates = flash_detonates[flash_detonates["inferred_round_id"] == round_id].copy() if not flash_detonates.empty else pd.DataFrame()
    round_he_detonates = he_detonates[he_detonates["inferred_round_id"] == round_id].copy() if not he_detonates.empty else pd.DataFrame()
    round_blinds = blinds[blinds["inferred_round_id"] == round_id].copy() if not blinds.empty else pd.DataFrame()
    round_bomb_pickups = bomb_pickups[bomb_pickups["inferred_round_id"] == round_id].copy() if not bomb_pickups.empty else pd.DataFrame()
    round_bomb_drops = bomb_drops[bomb_drops["inferred_round_id"] == round_id].copy() if not bomb_drops.empty else pd.DataFrame()
    round_bomb_begin_plants = bomb_begin_plants[bomb_begin_plants["inferred_round_id"] == round_id].copy() if not bomb_begin_plants.empty else pd.DataFrame()
    round_bomb_plants = bomb_plants[bomb_plants["inferred_round_id"] == round_id].copy() if not bomb_plants.empty else pd.DataFrame()
    round_bomb_defuses = bomb_defuses[bomb_defuses["inferred_round_id"] == round_id].copy() if not bomb_defuses.empty else pd.DataFrame()
    round_bomb_begin_defuses = bomb_begin_defuses[bomb_begin_defuses["inferred_round_id"] == round_id].copy() if not bomb_begin_defuses.empty else pd.DataFrame()
    round_bomb_abort_defuses = bomb_abort_defuses[bomb_abort_defuses["inferred_round_id"] == round_id].copy() if not bomb_abort_defuses.empty else pd.DataFrame()
    round_bomb_explodes = bomb_explodes[bomb_explodes["inferred_round_id"] == round_id].copy() if not bomb_explodes.empty else pd.DataFrame()
    round_smoke_expires = smoke_expires[smoke_expires["inferred_round_id"] == round_id].copy() if not smoke_expires.empty else pd.DataFrame()
    round_inferno_starts = inferno_starts[inferno_starts["inferred_round_id"] == round_id].copy() if not inferno_starts.empty else pd.DataFrame()
    round_grenades = grenades[grenades["inferred_round_id"] == round_id].copy() if not grenades.empty else pd.DataFrame()
    round_sound_events = sound_events[sound_events["inferred_round_id"] == round_id].copy() if not sound_events.empty else pd.DataFrame()
    if round_ticks.empty:
        raise ValueError(f"No ticks found for inferred round {round_id}")
    round_ticks = round_ticks.sort_values(["tick", "name"]).copy()
    round_deaths = round_deaths.sort_values(["tick"]).copy() if not round_deaths.empty else round_deaths
    round_fires = round_fires.sort_values(["tick"]).copy() if not round_fires.empty else round_fires
    round_hurts = round_hurts.sort_values(["tick"]).copy() if not round_hurts.empty else round_hurts
    round_blinds = round_blinds.sort_values(["tick"]).copy() if not round_blinds.empty else round_blinds
    round_smoke_detonates = round_smoke_detonates.sort_values(["tick"]).copy() if not round_smoke_detonates.empty else round_smoke_detonates
    round_smoke_expires = round_smoke_expires.sort_values(["tick"]).copy() if not round_smoke_expires.empty else round_smoke_expires
    round_flash_detonates = round_flash_detonates.sort_values(["tick"]).copy() if not round_flash_detonates.empty else round_flash_detonates
    round_he_detonates = round_he_detonates.sort_values(["tick"]).copy() if not round_he_detonates.empty else round_he_detonates
    round_inferno_starts = round_inferno_starts.sort_values(["tick"]).copy() if not round_inferno_starts.empty else round_inferno_starts
    round_grenades = round_grenades.sort_values(["grenade_entity_id", "tick"]).copy() if not round_grenades.empty else round_grenades
    round_sound_events = round_sound_events.sort_values(["tick", "sound_kind"]).copy() if not round_sound_events.empty else round_sound_events
    frame_ticks = [int(tick) for tick in round_ticks["tick"].sort_values().unique().tolist()]
    round_players = RoundPlayers.from_round_ticks(
        round_ticks,
        round_deaths,
        round_fires=round_fires,
        round_hurts=round_hurts,
        round_blinds=round_blinds,
        tickrate=tickrate,
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
        round_grenades=round_grenades,
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
    return RoundData(
        round_ticks=round_ticks,
        round_players=round_players,
        utility_timeline=utility_timeline,
        bomb_timeline=bomb_timeline,
        sound_timeline=sound_timeline,
        frame_ticks=frame_ticks,
        round_start_tick=int(round_ticks["tick"].min()),
        round_id=round_id,
    )
