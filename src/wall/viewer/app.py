from __future__ import annotations

import argparse
import bisect
from collections import OrderedDict
from dataclasses import dataclass
import math
from pathlib import Path
import random

import pandas as pd

try:
    import pygame
except ModuleNotFoundError as exc:
    raise SystemExit(
        "pygame is not installed in the current environment. "
        "Install it in the 'wall' environment first, then rerun this viewer."
    ) from exc

from wall.paths import awpy_maps_dir, resolve_asset_path
from wall.render.round_pygame_components import BlindEffectTracker, BombStateTracker
from wall.render.round_pygame_effects import draw_blind_glow, draw_flash_eye, draw_flash_eye_texture, load_flash_eye_texture, mix_with_white
from wall.render.round_render import MAP_DATA, game_to_pixel_axis, get_round_data, load_round_data, team_color


SIDEBAR_WIDTH = 300
BOTTOM_BAR_HEIGHT = 64
BACKGROUND_COLOR = (20, 20, 20)
SIDEBAR_COLOR = (28, 28, 28)
TEXT_COLOR = (240, 240, 240)
MUTED_TEXT_COLOR = (180, 180, 180)
BUTTON_COLOR = (52, 52, 52)
BUTTON_ACTIVE_COLOR = (72, 72, 72)
ACCENT_COLOR = (110, 168, 254)
TRACER_T_COLOR = (255, 238, 170, 210)
TRACER_CT_COLOR = (120, 205, 255, 210)
TRACER_NEUTRAL_COLOR = (235, 235, 235, 200)
SPEED_OPTIONS = [0.25, 0.5, 1.0, 2.0, 4.0, 10.0]
SMOKE_RADIUS_WORLD = 176.0
SMOKE_DEPLOY_TICKS = 18
FLASH_EFFECT_TICKS = 128
HE_EFFECT_TICKS = 28
HE_RADIUS_WORLD = 384.0
HE_SMOKE_HOLE_RECOVERY_DELAY_SECONDS = 1.5
HE_SMOKE_HOLE_FULL_RECOVERY_SECONDS = 3.5
HE_SMOKE_HOLE_FEATHER_RATIO = 0.35
INFERNO_DURATION_SECONDS = 7.03125
INFERNO_GROWTH_SECONDS = 2.0
INFERNO_CT_RADIUS_WORLD = 128.0
INFERNO_T_RADIUS_WORLD = 144.0
INFERNO_INITIAL_RADIUS_SCALE = 0.45
SMOKE_PULSE_FREQUENCY = 0.075
SMOKE_PULSE_AMPLITUDE = 0.02
GRENADE_TYPE_STYLES = {
    "CSmokeGrenadeProjectile": {"color": (210, 210, 210), "radius": 5},
    "CFlashbangProjectile": {"color": (245, 245, 200), "radius": 4},
    "CHEGrenadeProjectile": {"color": (110, 190, 110), "radius": 4},
    "CMolotovProjectile": {"color": (255, 140, 60), "radius": 4},
    "CIncendiaryGrenadeProjectile": {"color": (255, 110, 50), "radius": 4},
    "CDecoyProjectile": {"color": (150, 150, 150), "radius": 4},
}
GRENADE_ICON_PATHS = {
    "CSmokeGrenadeProjectile": "smokegrenade.png",
    "CFlashbangProjectile": "flashbang.png",
    "CHEGrenadeProjectile": "frag_grenade.png",
    "CMolotovProjectile": "firebomb.png",
    "CDecoyProjectile": "decoy.png",
}
C4_CARRIED_COLOR = (217, 205, 33)
C4_DROPPED_COLOR = (255, 255, 255)
C4_PLANTED_COLOR = (220, 72, 72)
C4_DEFUSED_COLOR = (135, 255, 89)
C4_DEFUSED_GLOW_COLOR = (200, 255, 178, 150)
DEFUSE_BAR_COLOR = C4_DEFUSED_COLOR
DEFUSE_BAR_SHADOW = (34, 54, 34, 220)
DEFUSE_BAR_GLOW = (170, 255, 150, 120)
DEFUSE_SHAKE_TICKS = 20


def format_hud_number(number: int) -> str:
    return "0" if number == 10 else str(number)


@dataclass
class RoundCache:
    round_id: int
    renderer: "PygameRoundRenderer"
    frame_ticks: list[int]
    cache: OrderedDict[int, pygame.Surface]


class PygameRoundRenderer:
    def __init__(
        self,
        round_ticks: pd.DataFrame,
        round_deaths: pd.DataFrame,
        round_fires: pd.DataFrame,
        round_hurts: pd.DataFrame,
        round_smoke_detonates: pd.DataFrame,
        round_flash_detonates: pd.DataFrame,
        round_he_detonates: pd.DataFrame,
        round_blinds: pd.DataFrame,
        round_bomb_pickups: pd.DataFrame,
        round_bomb_drops: pd.DataFrame,
        round_bomb_plants: pd.DataFrame,
        round_bomb_defuses: pd.DataFrame,
        round_bomb_begin_defuses: pd.DataFrame,
        round_bomb_abort_defuses: pd.DataFrame,
        round_bomb_explodes: pd.DataFrame,
        round_smoke_expires: pd.DataFrame,
        round_inferno_starts: pd.DataFrame,
        round_grenades: pd.DataFrame,
        player_numbers: dict[str, int] | None,
        width: int,
        height: int,
        trail: int,
        facing_radius: float,
        facing_fov: float,
        map_name: str | None,
        tickrate: float,
    ) -> None:
        self.round_ticks = round_ticks.sort_values(["tick", "name"]).copy()
        self.round_deaths = self._sort_if_has_columns(round_deaths, ["tick"])
        self.round_fires = self._sort_if_has_columns(round_fires, ["tick"])
        self.round_hurts = self._sort_if_has_columns(round_hurts, ["tick"])
        self.round_smoke_detonates = self._sort_if_has_columns(round_smoke_detonates, ["tick"])
        self.round_flash_detonates = self._sort_if_has_columns(round_flash_detonates, ["tick"])
        self.round_he_detonates = self._sort_if_has_columns(round_he_detonates, ["tick"])
        self.round_blinds = self._sort_if_has_columns(round_blinds, ["tick"])
        self.round_bomb_pickups = self._sort_if_has_columns(round_bomb_pickups, ["tick"])
        self.round_bomb_drops = self._sort_if_has_columns(round_bomb_drops, ["tick"])
        self.round_bomb_plants = self._sort_if_has_columns(round_bomb_plants, ["tick"])
        self.round_bomb_defuses = self._sort_if_has_columns(round_bomb_defuses, ["tick"])
        self.round_bomb_begin_defuses = self._sort_if_has_columns(round_bomb_begin_defuses, ["tick"])
        self.round_bomb_abort_defuses = self._sort_if_has_columns(round_bomb_abort_defuses, ["tick"])
        self.round_bomb_explodes = self._sort_if_has_columns(round_bomb_explodes, ["tick"])
        self.round_smoke_expires = self._sort_if_has_columns(round_smoke_expires, ["tick"])
        self.round_inferno_starts = self._sort_if_has_columns(round_inferno_starts, ["tick"])
        self.round_grenades = self._sort_if_has_columns(round_grenades, ["grenade_entity_id", "tick"])
        self.width = width
        self.height = height
        self.trail = trail
        self.facing_radius = facing_radius
        self.facing_fov = facing_fov
        self.map_name = map_name
        self.tickrate = tickrate
        self.round_id = int(self.round_ticks["inferred_round_id"].iloc[0])
        self.round_start_tick = int(self.round_ticks["tick"].min())
        self.frame_ticks = [int(tick) for tick in self.round_ticks["tick"].sort_values().unique().tolist()]
        self.players = sorted(self.round_ticks["name"].dropna().unique())
        if player_numbers is None:
            self.player_numbers = {player: index + 1 for index, player in enumerate(self.players)}
        else:
            next_fallback = max(player_numbers.values(), default=0) + 1
            resolved_numbers: dict[str, int] = {}
            for player in self.players:
                if player in player_numbers:
                    resolved_numbers[player] = player_numbers[player]
                else:
                    resolved_numbers[player] = next_fallback
                    next_fallback += 1
            self.player_numbers = resolved_numbers
            self.players = sorted(self.players, key=lambda player: (self.player_numbers[player], player))
        self.death_lookup = self._build_death_lookup()
        self.death_tick_lookup = self._build_death_tick_lookup()
        self.damage_flash_lookup = self._build_damage_flash_lookup()
        self.fire_lookup = self._build_fire_lookup()
        self.hurt_lookup = self._build_hurt_lookup()
        self.grenade_trails = self._build_grenade_trails()
        self.smoke_windows = self._build_smoke_windows()
        self.smoke_start_tick_by_entity = self._build_smoke_start_tick_by_entity()
        self.flash_effects = self._build_flash_effects()
        self.he_effects = self._build_he_effects()
        self.inferno_effects = self._build_inferno_effects()
        self.smoke_holes_by_window = self._build_smoke_holes_by_window()
        self.flash_start_tick_by_entity = self._build_flash_start_tick_by_entity()
        self.damage_flash_duration_ticks = 96
        self.fire_flash_duration_ticks = 32
        self.hit_match_window_ticks = 12
        self.blind_tracker = BlindEffectTracker(self.round_blinds, self.tickrate)
        self.bomb_tracker = BombStateTracker(
            round_ticks=self.round_ticks,
            round_bomb_pickups=self.round_bomb_pickups,
            round_bomb_drops=self.round_bomb_drops,
            round_bomb_plants=self.round_bomb_plants,
            round_bomb_defuses=self.round_bomb_defuses,
            round_bomb_explodes=self.round_bomb_explodes,
            death_tick_lookup=self.death_tick_lookup,
            frame_ticks=self.frame_ticks,
        )
        self.defuse_attempts = self._build_defuse_attempts()

        self.background_original = self._load_background_image()
        self.uses_map_background = self.background_original is not None and self.map_name in MAP_DATA and game_to_pixel_axis is not None
        self.background_surface = self._build_background_surface()
        self.bounds = self._compute_bounds()
        self.font = pygame.font.SysFont("segoe ui", 18)
        self.player_number_font = pygame.font.SysFont("segoe ui", 11)
        self.small_font = pygame.font.SysFont("segoe ui", 14)
        self.title_font = pygame.font.SysFont("segoe ui", 22, bold=True)
        self.muzzle_flash_sprite = self._load_muzzle_flash_sprite()
        self.muzzle_flash_anchor = self._find_muzzle_flash_anchor(self.muzzle_flash_sprite)
        self.grenade_icons = self._load_grenade_icons()
        self.he_animation_frames = self._load_he_animation_frames()
        self.fire_animation_layers = self._load_fire_animation_layers()
        self.soft_circle_masks: dict[tuple[int, int], pygame.Surface] = {}
        self.c4_icons = self._load_c4_icons()
        self.flash_eye_texture = load_flash_eye_texture()
        self.smoke_texture = self._build_smoke_texture()

    def _sort_if_has_columns(self, df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
        if df.empty or not all(column in df.columns for column in columns):
            return df.copy()
        return df.sort_values(columns).copy()

    def _build_death_lookup(self) -> dict[str, list[pd.Series]]:
        lookup: dict[str, list[pd.Series]] = {}
        for _, row in self.round_deaths.iterrows():
            lookup.setdefault(str(row["user_name"]), []).append(row)
        return lookup

    def _build_death_tick_lookup(self) -> dict[str, int]:
        lookup: dict[str, int] = {}
        for player, rows in self.death_lookup.items():
            if rows:
                lookup[player] = int(rows[0]["tick"])
        return lookup

    def _build_damage_flash_lookup(self) -> dict[str, list[tuple[int, float]]]:
        if "health" not in self.round_ticks.columns:
            return {}
        work = self.round_ticks[["name", "tick", "health"]].copy()
        work["health"] = pd.to_numeric(work["health"], errors="coerce")
        lookup: dict[str, list[tuple[int, float]]] = {}
        for player, group in work.groupby("name", sort=False):
            group = group.sort_values("tick").copy()
            group["prev_health"] = group["health"].shift(1)
            drops = group[
                group["health"].notna()
                & group["prev_health"].notna()
                & (group["health"] < group["prev_health"])
            ]
            if not drops.empty:
                lookup[str(player)] = [
                    (int(row["tick"]), float(row["prev_health"] - row["health"]))
                    for _, row in drops.iterrows()
                ]
        return lookup

    def _build_fire_lookup(self) -> dict[str, list[pd.Series]]:
        if self.round_fires.empty or "user_name" not in self.round_fires.columns:
            return {}
        lookup: dict[str, list[pd.Series]] = {}
        for _, row in self.round_fires.iterrows():
            lookup.setdefault(str(row["user_name"]), []).append(row)
        return lookup

    def _build_hurt_lookup(self) -> dict[str, list[pd.Series]]:
        if self.round_hurts.empty or "attacker_name" not in self.round_hurts.columns:
            return {}
        lookup: dict[str, list[pd.Series]] = {}
        for _, row in self.round_hurts.iterrows():
            attacker_name = row.get("attacker_name")
            if pd.isna(attacker_name):
                continue
            lookup.setdefault(str(attacker_name), []).append(row)
        return lookup

    def _load_background_image(self) -> pygame.Surface | None:
        if not self.map_name:
            return None
        map_path = awpy_maps_dir() / f"{self.map_name}.png"
        if not map_path.exists():
            return None
        return pygame.image.load(str(map_path)).convert()

    def _lookup_player_team_num(self, player_name: str, steamid: str | None, tick: int) -> int | None:
        if self.round_ticks.empty or "team_num" not in self.round_ticks.columns:
            return None
        work = self.round_ticks[self.round_ticks["name"].astype(str) == player_name].copy()
        if steamid is not None and "player_steamid" in work.columns:
            work = work[work["player_steamid"].astype(str) == steamid].copy()
        if work.empty:
            return None
        work["tick"] = pd.to_numeric(work["tick"], errors="coerce")
        work["team_num"] = pd.to_numeric(work["team_num"], errors="coerce")
        exact = work[work["tick"] == tick]
        if exact.empty:
            exact = work[(work["tick"] >= tick - 2) & (work["tick"] <= tick + 2)].sort_values("tick")
        if exact.empty:
            return None
        team_num = exact["team_num"].iloc[0]
        if pd.isna(team_num):
            return None
        return int(team_num)

    def _match_inferno_start(self, player_name: str, steamid: str | None, projectile_end_tick: int) -> pd.Series | None:
        if self.round_inferno_starts.empty or "user_name" not in self.round_inferno_starts.columns:
            return None
        work = self.round_inferno_starts[self.round_inferno_starts["user_name"].astype(str) == player_name].copy()
        if steamid is not None and "user_steamid" in work.columns:
            work = work[work["user_steamid"].astype(str) == steamid].copy()
        if work.empty:
            return None
        work["tick"] = pd.to_numeric(work["tick"], errors="coerce")
        work["delta"] = work["tick"] - projectile_end_tick
        close = work[(work["delta"] >= -2) & (work["delta"] <= 6)].sort_values(["delta", "tick"])
        if close.empty:
            return None
        return close.iloc[0]

    def _build_grenade_trails(self) -> list[pd.DataFrame]:
        if self.round_grenades.empty:
            return []
        required = {"grenade_type", "grenade_entity_id", "x", "y", "z", "tick"}
        if not required.issubset(self.round_grenades.columns):
            return []
        work = self.round_grenades.copy()
        work = work[work["grenade_type"].astype(str).str.contains("Projectile", na=False)].copy()
        work = work[work[["x", "y", "z"]].notna().all(axis=1)].copy()
        if work.empty:
            return []
        work["grenade_entity_id"] = pd.to_numeric(work["grenade_entity_id"], errors="coerce")
        work = work[work["grenade_entity_id"].notna()].copy()
        trails: list[pd.DataFrame] = []
        for _, group in work.groupby(["grenade_entity_id", "steamid", "name"], sort=False):
            group = group.sort_values("tick").copy()
            tick_diff = group["tick"].diff().fillna(1)
            segment_id = (tick_diff > 2).cumsum()
            longest_segment = group.groupby(segment_id, sort=False).size().idxmax()
            segment = group[segment_id == longest_segment].copy()
            current_row = segment.iloc[-1]
            segment["burn_icon_path"] = None
            segment["did_burn"] = False
            if str(current_row["grenade_type"]) == "CMolotovProjectile":
                player_name = str(current_row.get("name", ""))
                steamid_value = current_row.get("steamid")
                steamid = None if pd.isna(steamid_value) else str(steamid_value)
                inferno_start = self._match_inferno_start(player_name, steamid, int(current_row["tick"]))
                team_tick = int(inferno_start["tick"]) if inferno_start is not None else int(current_row["tick"])
                team_num = self._lookup_player_team_num(player_name, steamid, team_tick)
                segment["burn_icon_path"] = "incgrenade.png" if team_num == 3 else "firebomb.png"
                segment["did_burn"] = inferno_start is not None
            trails.append(segment)
        return trails

    def _build_smoke_windows(self) -> list[dict[str, float | int]]:
        if self.round_smoke_detonates.empty:
            return []
        windows: list[dict[str, float | int]] = []
        expires = self.round_smoke_expires.copy() if not self.round_smoke_expires.empty else pd.DataFrame()
        used_expire_indices: set[int] = set()
        for _, detonate in self.round_smoke_detonates.iterrows():
            start_tick = int(detonate["tick"])
            end_tick = start_tick + 1152
            matched_index: int | None = None
            if not expires.empty and "entityid" in detonate.index and "entityid" in expires.columns:
                entity_matches = expires[
                    (expires["entityid"] == detonate["entityid"])
                    & (expires["tick"] >= start_tick)
                ]
                for expire_index, expire_row in entity_matches.iterrows():
                    if expire_index in used_expire_indices:
                        continue
                    matched_index = expire_index
                    end_tick = int(expire_row["tick"])
                    break
            if matched_index is None and not expires.empty:
                generic_matches = expires[expires["tick"] >= start_tick]
                for expire_index, expire_row in generic_matches.iterrows():
                    if expire_index in used_expire_indices:
                        continue
                    matched_index = expire_index
                    end_tick = int(expire_row["tick"])
                    break
            if matched_index is not None:
                used_expire_indices.add(matched_index)
            windows.append(
                {
                    "start_tick": start_tick,
                    "end_tick": end_tick,
                    "x": float(detonate["x"]),
                    "y": float(detonate["y"]),
                }
            )
        return windows

    def _build_smoke_start_tick_by_entity(self) -> dict[int, int]:
        if self.round_smoke_detonates.empty or "entityid" not in self.round_smoke_detonates.columns:
            return {}
        work = self.round_smoke_detonates[["entityid", "tick"]].copy()
        work["entityid"] = pd.to_numeric(work["entityid"], errors="coerce")
        work["tick"] = pd.to_numeric(work["tick"], errors="coerce")
        work = work.dropna(subset=["entityid", "tick"])
        if work.empty:
            return {}
        work = work.sort_values(["entityid", "tick"]).drop_duplicates("entityid", keep="first")
        return {
            int(row["entityid"]): int(row["tick"])
            for _, row in work.iterrows()
        }

    def _build_flash_effects(self) -> list[dict[str, float | int]]:
        if self.round_flash_detonates.empty:
            return []
        required = {"tick", "x", "y"}
        if not required.issubset(self.round_flash_detonates.columns):
            return []
        effects: list[dict[str, float | int]] = []
        for _, detonate in self.round_flash_detonates.iterrows():
            if pd.isna(detonate.get("x")) or pd.isna(detonate.get("y")):
                continue
            entity_id = pd.to_numeric(detonate.get("entityid"), errors="coerce")
            effects.append(
                {
                    "entityid": -1 if pd.isna(entity_id) else int(entity_id),
                    "start_tick": int(detonate["tick"]),
                    "end_tick": int(detonate["tick"]) + FLASH_EFFECT_TICKS,
                    "x": float(detonate["x"]),
                    "y": float(detonate["y"]),
                }
            )
        return effects

    def _build_flash_start_tick_by_entity(self) -> dict[int, int]:
        if self.round_flash_detonates.empty or "entityid" not in self.round_flash_detonates.columns:
            return {}
        work = self.round_flash_detonates[["entityid", "tick"]].copy()
        work["entityid"] = pd.to_numeric(work["entityid"], errors="coerce")
        work["tick"] = pd.to_numeric(work["tick"], errors="coerce")
        work = work.dropna(subset=["entityid", "tick"])
        if work.empty:
            return {}
        work = work.sort_values(["entityid", "tick"]).drop_duplicates("entityid", keep="first")
        return {
            int(row["entityid"]): int(row["tick"])
            for _, row in work.iterrows()
        }

    def _build_he_effects(self) -> list[dict[str, float | int]]:
        if self.round_he_detonates.empty:
            return []
        required = {"tick", "x", "y"}
        if not required.issubset(self.round_he_detonates.columns):
            return []
        effects: list[dict[str, float | int]] = []
        for _, detonate in self.round_he_detonates.iterrows():
            if pd.isna(detonate.get("x")) or pd.isna(detonate.get("y")):
                continue
            entity_id = pd.to_numeric(detonate.get("entityid"), errors="coerce")
            effects.append(
                {
                    "entityid": -1 if pd.isna(entity_id) else int(entity_id),
                    "start_tick": int(detonate["tick"]),
                    "end_tick": int(detonate["tick"]) + HE_EFFECT_TICKS,
                    "x": float(detonate["x"]),
                    "y": float(detonate["y"]),
                }
            )
        return effects

    def _smoke_extinguish_tick_for_point(self, x: float, y: float, inferno_start_tick: int, inferno_end_tick: int) -> int | None:
        if not self.smoke_windows:
            return None
        for smoke in self.smoke_windows:
            smoke_start_tick = int(smoke["start_tick"]) + SMOKE_DEPLOY_TICKS
            smoke_end_tick = int(smoke["end_tick"])
            if smoke_end_tick < inferno_start_tick or smoke_start_tick > inferno_end_tick:
                continue
            smoke_x = float(smoke["x"])
            smoke_y = float(smoke["y"])
            if (smoke_x - x) ** 2 + (smoke_y - y) ** 2 <= SMOKE_RADIUS_WORLD ** 2:
                return max(inferno_start_tick, smoke_start_tick)
        return None

    def _build_inferno_effects(self) -> list[dict[str, object]]:
        if self.round_inferno_starts.empty:
            return []
        effects: list[dict[str, object]] = []
        duration_ticks = int(round(self.tickrate * INFERNO_DURATION_SECONDS))
        for _, row in self.round_inferno_starts.iterrows():
            if pd.isna(row.get("x")) or pd.isna(row.get("y")):
                continue
            player_name = str(row.get("user_name", ""))
            steamid_value = row.get("user_steamid")
            steamid = None if pd.isna(steamid_value) else str(steamid_value)
            start_tick = int(row["tick"])
            team_num = self._lookup_player_team_num(player_name, steamid, start_tick)
            full_radius_world = INFERNO_CT_RADIUS_WORLD if team_num == 3 else INFERNO_T_RADIUS_WORLD
            entity_id = pd.to_numeric(row.get("entityid"), errors="coerce")
            seed = int(entity_id) if not pd.isna(entity_id) else start_tick
            natural_end_tick = start_tick + duration_ticks
            extinguish_tick = self._smoke_extinguish_tick_for_point(
                float(row["x"]),
                float(row["y"]),
                start_tick,
                natural_end_tick,
            )
            if extinguish_tick is not None:
                end_tick = min(natural_end_tick, extinguish_tick)
                tiles: list[dict[str, float | int | str]] = []
            else:
                end_tick = natural_end_tick
                tiles = self._build_inferno_tiles(seed, full_radius_world)
                for tile in tiles:
                    tile_x = float(row["x"]) + float(tile["offset_x"])
                    tile_y = float(row["y"]) + float(tile["offset_y"])
                    tile_extinguish_tick = self._smoke_extinguish_tick_for_point(tile_x, tile_y, start_tick, end_tick)
                    tile["extinguish_tick"] = tile_extinguish_tick
            effects.append(
                {
                    "entityid": -1 if pd.isna(entity_id) else int(entity_id),
                    "start_tick": start_tick,
                    "end_tick": end_tick,
                    "x": float(row["x"]),
                    "y": float(row["y"]),
                    "team_num": team_num,
                    "full_radius_world": full_radius_world,
                    "extinguish_tick": extinguish_tick,
                    "tiles": tiles,
                }
            )
        return effects

    def _build_inferno_tiles(self, seed: int, full_radius_world: float) -> list[dict[str, float | int | str]]:
        rng = random.Random(seed)
        tiles: list[dict[str, float | int | str]] = []
        layer_specs = [
            ("01", 28, 0.36, 1.02, 0.08, 0.98),
            ("02", 16, 0.24, 0.94, 0.00, 0.86),
        ]
        for layer_name, count, min_scale, max_scale, min_ring, max_ring in layer_specs:
            for _ in range(count):
                theta = rng.random() * math.tau
                radius = full_radius_world * (min_ring + (max_ring - min_ring) * math.sqrt(rng.random()))
                jitter = full_radius_world * 0.10
                offset_x = math.cos(theta) * radius + rng.uniform(-jitter, jitter)
                offset_y = math.sin(theta) * radius + rng.uniform(-jitter, jitter)
                tiles.append(
                    {
                        "layer": layer_name,
                        "offset_x": offset_x,
                        "offset_y": offset_y,
                        "scale": rng.uniform(min_scale, max_scale),
                        "phase": rng.randrange(5),
                    }
                )
        return tiles

    def _build_smoke_holes_by_window(self) -> dict[int, list[dict[str, float | int]]]:
        if not self.smoke_windows or not self.he_effects:
            return {}
        smoke_radius = SMOKE_RADIUS_WORLD
        he_radius = HE_RADIUS_WORLD
        holes_by_window: dict[int, list[dict[str, float | int]]] = {}
        for index, smoke in enumerate(self.smoke_windows):
            smoke_start_tick = int(smoke["start_tick"])
            smoke_end_tick = int(smoke["end_tick"])
            smoke_x = float(smoke["x"])
            smoke_y = float(smoke["y"])
            for effect in self.he_effects:
                effect_tick = int(effect["start_tick"])
                if effect_tick < smoke_start_tick or effect_tick > smoke_end_tick:
                    continue
                dx = float(effect["x"]) - smoke_x
                dy = float(effect["y"]) - smoke_y
                if dx * dx + dy * dy > (smoke_radius + he_radius) ** 2:
                    continue
                holes_by_window.setdefault(index, []).append(
                    {
                        "start_tick": effect_tick,
                        "x": float(effect["x"]),
                        "y": float(effect["y"]),
                    }
                )
        return holes_by_window

    def _get_soft_circle_mask(self, radius_px: int, inner_alpha: int) -> pygame.Surface:
        key = (radius_px, inner_alpha)
        cached = self.soft_circle_masks.get(key)
        if cached is not None:
            return cached
        diameter = max(2, radius_px * 2)
        mask = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
        center = radius_px
        feather_start = radius_px * max(0.0, min(0.95, 1.0 - HE_SMOKE_HOLE_FEATHER_RATIO))
        for y in range(diameter):
            dy = y - center
            for x in range(diameter):
                dx = x - center
                distance = math.sqrt(dx * dx + dy * dy)
                if distance >= radius_px:
                    alpha = 255
                elif distance <= feather_start:
                    alpha = inner_alpha
                else:
                    t = (distance - feather_start) / max(1e-6, radius_px - feather_start)
                    alpha = int(round(inner_alpha + (255 - inner_alpha) * t))
                value = max(0, min(255, alpha))
                mask.set_at((x, y), (value, value, value, value))
        self.soft_circle_masks[key] = mask
        return mask

    def _build_background_surface(self) -> pygame.Surface:
        if self.background_original is None:
            surface = pygame.Surface((self.width, self.height))
            surface.fill((245, 245, 245))
            return surface
        return pygame.transform.smoothscale(self.background_original, (self.width, self.height)).convert()

    def _load_muzzle_flash_sprite(self) -> pygame.Surface | None:
        sprite_path = resolve_asset_path("sprite.png")
        if not sprite_path.exists():
            return None
        return pygame.image.load(str(sprite_path)).convert_alpha()

    def _load_grenade_icons(self) -> dict[str, pygame.Surface]:
        icons: dict[str, pygame.Surface] = {}
        target_height = 14
        for grenade_type, filename in GRENADE_ICON_PATHS.items():
            icon_path = resolve_asset_path(filename)
            if not icon_path.exists():
                continue
            try:
                icon = pygame.image.load(str(icon_path)).convert_alpha()
            except pygame.error:
                continue
            width, height = icon.get_size()
            if width <= 0 or height <= 0:
                continue
            scale = target_height / height
            scaled_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
            icons[grenade_type] = pygame.transform.smoothscale(icon, scaled_size)
        for filename in ("firebomb.png", "incgrenade.png"):
            icon_path = resolve_asset_path(filename)
            if not icon_path.exists():
                continue
            try:
                icon = pygame.image.load(str(icon_path)).convert_alpha()
            except pygame.error:
                continue
            width, height = icon.get_size()
            if width <= 0 or height <= 0:
                continue
            scale = target_height / height
            scaled_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
            icons[filename] = pygame.transform.smoothscale(icon, scaled_size)
        return icons

    def _load_he_animation_frames(self) -> list[pygame.Surface]:
        frames: list[pygame.Surface] = []
        target_height = 60
        base_dir = resolve_asset_path("grenade")
        for frame_index in range(1, 8):
            frame_path = base_dir / f"he{frame_index}.png"
            if not frame_path.exists():
                continue
            try:
                frame = pygame.image.load(str(frame_path)).convert_alpha()
            except pygame.error:
                continue
            width, height = frame.get_size()
            if width <= 0 or height <= 0:
                continue
            scale = target_height / height
            scaled_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
            frames.append(pygame.transform.smoothscale(frame, scaled_size))
        return frames

    def _load_fire_animation_layers(self) -> dict[str, list[pygame.Surface]]:
        layers: dict[str, list[pygame.Surface]] = {"01": [], "02": []}
        base_dir = resolve_asset_path("fire")
        target_height = 34
        for layer_name in ("01", "02"):
            for frame_index in range(1, 6):
                frame_path = base_dir / f"Fire0_{layer_name}_{frame_index}.png"
                if not frame_path.exists():
                    continue
                try:
                    frame = pygame.image.load(str(frame_path)).convert_alpha()
                except pygame.error:
                    continue
                width, height = frame.get_size()
                if width <= 0 or height <= 0:
                    continue
                scale = target_height / height
                scaled_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
                layers[layer_name].append(pygame.transform.smoothscale(frame, scaled_size))
        return layers

    def _load_c4_icons(self) -> dict[str, pygame.Surface]:
        icon_path = resolve_asset_path("c4.png")
        if not icon_path.exists():
            return {}
        try:
            icon = pygame.image.load(str(icon_path)).convert_alpha()
        except pygame.error:
            return {}
        width, height = icon.get_size()
        if width <= 0 or height <= 0:
            return {}
        target_height = 15
        scale = target_height / height
        scaled_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
        base = pygame.transform.scale(icon, scaled_size)
        return {
            "carried": self._tint_icon(base, C4_CARRIED_COLOR),
            "dropped": self._tint_icon(base, C4_DROPPED_COLOR),
            "planted": self._tint_icon(base, C4_PLANTED_COLOR),
            "defused": self._tint_icon(base, C4_DEFUSED_COLOR),
        }

    def _build_defuse_attempts(self) -> list[dict[str, object]]:
        if self.round_bomb_begin_defuses.empty:
            return []
        attempts: list[dict[str, object]] = []
        aborts = self.round_bomb_abort_defuses.copy() if not self.round_bomb_abort_defuses.empty else pd.DataFrame()
        defuses = self.round_bomb_defuses.copy() if not self.round_bomb_defuses.empty else pd.DataFrame()
        used_abort_indices: set[int] = set()
        used_defuse_indices: set[int] = set()
        for _, begin in self.round_bomb_begin_defuses.iterrows():
            start_tick = int(begin["tick"])
            haskit = bool(begin.get("haskit", False))
            duration_ticks = int(round((5.0 if haskit else 10.0) * self.tickrate))
            success_row = None
            abort_row = None
            if not defuses.empty:
                future_defuses = defuses[defuses["tick"] >= start_tick]
                for idx, row in future_defuses.iterrows():
                    if idx in used_defuse_indices:
                        continue
                    success_row = row
                    used_defuse_indices.add(idx)
                    break
            if not aborts.empty:
                future_aborts = aborts[aborts["tick"] >= start_tick]
                for idx, row in future_aborts.iterrows():
                    if idx in used_abort_indices:
                        continue
                    abort_row = row
                    used_abort_indices.add(idx)
                    break
            success_tick = int(success_row["tick"]) if success_row is not None else None
            abort_tick = int(abort_row["tick"]) if abort_row is not None else None
            natural_end_tick = start_tick + duration_ticks
            end_tick = natural_end_tick
            status = "active"
            if success_tick is not None and success_tick <= natural_end_tick and (abort_tick is None or success_tick <= abort_tick):
                end_tick = success_tick
                status = "success"
            elif abort_tick is not None and abort_tick <= natural_end_tick:
                end_tick = abort_tick
                status = "aborted"
            attempts.append(
                {
                    "player": str(begin.get("user_name", "")),
                    "start_tick": start_tick,
                    "end_tick": end_tick,
                    "natural_end_tick": natural_end_tick,
                    "duration_ticks": duration_ticks,
                    "haskit": haskit,
                    "status": status,
                }
            )
        return attempts

    def _tint_icon(self, base: pygame.Surface, color: tuple[int, int, int]) -> pygame.Surface:
        tinted = base.copy()
        tinted.fill((*color, 255), special_flags=pygame.BLEND_RGBA_MULT)
        return tinted

    def _blit_icon_with_shadow(self, surface: pygame.Surface, icon: pygame.Surface, center: tuple[int, int]) -> None:
        shadow = icon.copy()
        shadow.fill((18, 18, 18, 170), special_flags=pygame.BLEND_RGBA_MULT)
        shadow_rect = shadow.get_rect(center=(center[0] + 1, center[1] + 1))
        icon_rect = icon.get_rect(center=center)
        surface.blit(shadow, shadow_rect)
        surface.blit(icon, icon_rect)

    def _blit_icon_with_glow(
        self,
        surface: pygame.Surface,
        icon: pygame.Surface,
        center: tuple[int, int],
        glow_color: tuple[int, int, int, int],
    ) -> None:
        glow = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        glow_radius = max(icon.get_width(), icon.get_height()) // 2 + 4
        pygame.draw.circle(glow, glow_color, (center[0] + 1, center[1] + 1), glow_radius)
        surface.blit(glow, (0, 0))
        self._blit_icon_with_shadow(surface, icon, center)

    def _build_smoke_texture(self) -> pygame.Surface:
        asset_path = resolve_asset_path("smoke_texture.png")
        if asset_path.exists():
            try:
                return pygame.image.load(str(asset_path)).convert_alpha()
            except pygame.error:
                pass
        size = 384
        center = size // 2
        max_radius = size // 2 - 8
        surface = pygame.Surface((size, size), pygame.SRCALPHA)

        core_layers = [
            (0.82, 230, (92, 98, 104)),
            (0.92, 214, (100, 106, 112)),
            (1.02, 195, (110, 116, 122)),
        ]
        for scale, alpha, color in core_layers:
            pygame.draw.circle(
                surface,
                color + (alpha,),
                (center, center),
                int(round(max_radius * scale / 1.02)),
            )

        edge_layers = [
            (-0.14, -0.04, 1.05, 54),
            (0.13, -0.09, 1.03, 48),
            (-0.03, 0.16, 1.04, 44),
            (0.12, 0.11, 1.02, 52),
        ]
        for offset_x, offset_y, scale, alpha in edge_layers:
            pygame.draw.circle(
                surface,
                (118, 124, 130, alpha),
                (
                    int(round(center + max_radius * offset_x / 1.02)),
                    int(round(center + max_radius * offset_y / 1.02)),
                ),
                int(round(max_radius * scale / 1.02)),
            )
        return surface

    def _find_muzzle_flash_anchor(self, sprite: pygame.Surface | None) -> tuple[float, float] | None:
        if sprite is None:
            return None
        alpha = pygame.surfarray.array_alpha(sprite)
        non_zero = alpha > 0
        if not non_zero.any():
            return (0.0, sprite.get_height() / 2)
        xs, ys = non_zero.nonzero()
        left = int(xs.min())
        right = int(xs.max()) + 1
        top = int(ys.min())
        bottom = int(ys.max()) + 1
        band_width = max(6, int(round((right - left) * 0.12)))
        band_right = min(sprite.get_width(), left + band_width)
        weighted_y = 0.0
        total_alpha = 0.0
        for x in range(left, band_right):
            for y in range(top, bottom):
                value = int(alpha[x, y])
                if value <= 0:
                    continue
                weighted_y += y * value
                total_alpha += value
        anchor_y = (weighted_y / total_alpha) if total_alpha > 0 else ((top + bottom) / 2)
        return (float(left), float(anchor_y))

    def _compute_bounds(self) -> tuple[float, float, float, float]:
        if self.uses_map_background:
            return (0.0, float(self.width), 0.0, float(self.height))
        xmin = float(self.round_ticks["X"].min())
        xmax = float(self.round_ticks["X"].max())
        ymin = float(self.round_ticks["Y"].min())
        ymax = float(self.round_ticks["Y"].max())
        xpad = max(50.0, (xmax - xmin) * 0.05)
        ypad = max(50.0, (ymax - ymin) * 0.05)
        return xmin - xpad, xmax + xpad, ymin - ypad, ymax + ypad

    def world_to_px(self, x: float, y: float) -> tuple[float, float]:
        if self.uses_map_background:
            original_width = self.background_original.get_width() if self.background_original else self.width
            original_height = self.background_original.get_height() if self.background_original else self.height
            px = float(game_to_pixel_axis(self.map_name, x, "x"))
            py = float(game_to_pixel_axis(self.map_name, y, "y"))
            return (px / original_width * self.width, py / original_height * self.height)
        xmin, xmax, ymin, ymax = self.bounds
        px = (x - xmin) / (xmax - xmin) * (self.width - 1)
        py = (1 - (y - ymin) / (ymax - ymin)) * (self.height - 1)
        return px, py

    def world_dist_to_px(self, distance: float) -> float:
        if self.uses_map_background:
            scale = MAP_DATA[self.map_name]["scale"]
            original_width = self.background_original.get_width() if self.background_original else self.width
            return (distance / scale) * (self.width / original_width)
        xmin, xmax, _, _ = self.bounds
        return distance / (xmax - xmin) * (self.width - 1)

    def render_map_frame(self, frame_tick: int) -> pygame.Surface:
        surface = self.background_surface.copy()
        if self.background_original is None:
            self._draw_grid(surface)
        self._draw_title(surface, frame_tick)
        self._draw_infernos(surface, frame_tick)
        self._draw_smokes(surface, frame_tick)
        self._draw_grenades(surface, frame_tick)
        self._draw_flash_effects(surface, frame_tick)
        self._draw_he_effects(surface, frame_tick)
        self._draw_ground_bomb(surface, frame_tick)

        frame_slice = self.round_ticks[self.round_ticks["tick"] <= frame_tick]
        for player in self.players:
            player_hist = frame_slice[frame_slice["name"] == player].sort_values("tick")
            if player_hist.empty:
                continue
            current = player_hist.iloc[-1]
            base_color = team_color(current.get("team_num"))
            if self._is_dead(player, frame_tick):
                self._draw_death_marker(surface, player, frame_tick, base_color)
                death_position = self._death_position(player, frame_tick)
                if death_position is not None:
                    death_px, death_py = death_position
                    self._draw_player_id_label(surface, death_px, death_py, 0.0, player, base_color)
                continue

            color = self._resolve_player_color(player, frame_tick, base_color)
            blind_strength = self._blind_effect_strength(player, frame_tick)
            tail = player_hist.tail(self.trail)
            tail_points = [self.world_to_px(float(row.X), float(row.Y)) for row in tail.itertuples()]
            if len(tail_points) >= 2:
                pygame.draw.lines(surface, color, False, tail_points, 3)
            self._draw_facing_wedge(surface, float(current["X"]), float(current["Y"]), float(current["yaw"]), color)
            self._draw_player(
                surface,
                float(current["X"]),
                float(current["Y"]),
                float(current["yaw"]),
                player,
                color,
                base_color,
                current.get("team_num"),
                frame_tick,
                blind_strength,
            )
            self._draw_tracer_and_flash(surface, player, current, frame_tick)
            self._draw_death_marker(surface, player, frame_tick, base_color)
        return surface

    def _draw_grid(self, surface: pygame.Surface) -> None:
        step = 100
        for x in range(0, self.width, step):
            pygame.draw.line(surface, (220, 220, 220), (x, 0), (x, self.height), 1)
        for y in range(0, self.height, step):
            pygame.draw.line(surface, (220, 220, 220), (0, y), (self.width, y), 1)

    def _draw_title(self, surface: pygame.Surface, frame_tick: int) -> None:
        relative_tick = frame_tick - self.round_start_tick
        relative_seconds = relative_tick / self.tickrate if self.tickrate > 0 else 0.0
        title = f"Inferred round {self.round_id} | rtick={relative_tick} | t={relative_seconds:.2f}s"
        text_surface = self.title_font.render(title, True, TEXT_COLOR)
        shadow_surface = self.title_font.render(title, True, (10, 10, 10))
        surface.blit(shadow_surface, (18, 18))
        surface.blit(text_surface, (16, 16))

    def _draw_player(
        self,
        surface: pygame.Surface,
        x: float,
        y: float,
        yaw: float,
        player: str,
        color: tuple[int, int, int],
        id_color: tuple[int, int, int],
        team_num: int | float | None,
        frame_tick: int,
        blind_strength: float,
    ) -> None:
        px, py = self.world_to_px(x, y)
        center = (int(round(px)), int(round(py)))
        if blind_strength > 0.0:
            draw_blind_glow(surface, self.width, self.height, center, blind_strength)
        pygame.draw.circle(surface, color, center, 8)
        pygame.draw.circle(surface, (0, 0, 0), center, 8, 1)
        number_color = (24, 22, 2) if team_num == 2 else (255, 255, 255)
        number_color = mix_with_white(number_color, blind_strength * 0.45)
        number_surface = self.player_number_font.render(format_hud_number(self.player_numbers[player]), True, number_color)
        rect = number_surface.get_rect(center=(center[0], center[1] - 1))
        surface.blit(number_surface, rect)
        self._draw_carried_bomb_icon(surface, player, center, frame_tick)
        self._draw_player_id_label(surface, px, py, yaw, player, id_color, blind_strength)

    def _draw_player_id_label(
        self,
        surface: pygame.Surface,
        px: float,
        py: float,
        yaw: float,
        player_label: str,
        color: tuple[int, int, int],
        blind_strength: float = 0.0,
    ) -> None:
        text_color = mix_with_white(color, blind_strength * 0.60)
        shadow_color = mix_with_white((12, 12, 12), blind_strength * 0.18)
        text_surface = self.small_font.render(player_label, True, text_color)
        shadow_surface = self.small_font.render(player_label, True, shadow_color)
        label_x = int(round(px + 10.0))
        label_y = int(round(py + 10.0))
        text_rect = text_surface.get_rect(midleft=(label_x, label_y))
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            shadow_rect = text_rect.move(dx, dy)
            surface.blit(shadow_surface, shadow_rect)
        surface.blit(text_surface, text_rect)

    def _draw_facing_wedge(self, surface: pygame.Surface, x: float, y: float, yaw: float, color: tuple[int, int, int]) -> None:
        px, py = self.world_to_px(x, y)
        radius = self.world_dist_to_px(self.facing_radius)
        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        points = [(px, py)]
        step_count = max(6, int(self.facing_fov / 12))
        for index in range(step_count + 1):
            angle = -yaw - (self.facing_fov / 2) + (self.facing_fov * index / step_count)
            radians = math.radians(angle)
            points.append((px + math.cos(radians) * radius, py + math.sin(radians) * radius))
        pygame.draw.polygon(overlay, color + (110,), points)
        surface.blit(overlay, (0, 0))

    def _draw_death_marker(self, surface: pygame.Surface, player: str, frame_tick: int, color: tuple[int, int, int]) -> None:
        shown = [row for row in self.death_lookup.get(player, []) if int(row["tick"]) <= frame_tick]
        if not shown:
            return
        death_row = shown[0]
        px, py = self.world_to_px(float(death_row["user_X"]), float(death_row["user_Y"]))
        size = 5
        stroke_width = 2
        shadow_color = (18, 18, 18)
        shadow_offset = 1
        points_a = [
            (int(round(px - size)), int(round(py - size))),
            (int(round(px)), int(round(py))),
            (int(round(px + size)), int(round(py + size))),
        ]
        points_b = [
            (int(round(px - size)), int(round(py + size))),
            (int(round(px)), int(round(py))),
            (int(round(px + size)), int(round(py - size))),
        ]
        shadow_points_a = [(x + shadow_offset, y + shadow_offset) for x, y in points_a]
        shadow_points_b = [(x + shadow_offset, y + shadow_offset) for x, y in points_b]
        pygame.draw.lines(surface, shadow_color, False, shadow_points_a, stroke_width + 1)
        pygame.draw.lines(surface, shadow_color, False, shadow_points_b, stroke_width + 1)
        pygame.draw.lines(surface, color, False, points_a, stroke_width)
        pygame.draw.lines(surface, color, False, points_b, stroke_width)

    def _death_position(self, player: str, frame_tick: int) -> tuple[float, float] | None:
        shown = [row for row in self.death_lookup.get(player, []) if int(row["tick"]) <= frame_tick]
        if not shown:
            return None
        death_row = shown[0]
        return self.world_to_px(float(death_row["user_X"]), float(death_row["user_Y"]))

    def _draw_grenades(self, surface: pygame.Surface, frame_tick: int) -> None:
        if not self.grenade_trails:
            return
        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        for trail in self.grenade_trails:
            current = trail[trail["tick"] == frame_tick]
            if current.empty:
                continue
            current_row = current.iloc[-1]
            recent = trail[(trail["tick"] <= frame_tick) & (trail["tick"] >= frame_tick - 8)].copy()
            if recent.empty:
                continue
            style = GRENADE_TYPE_STYLES.get(str(current_row["grenade_type"]), {"color": (220, 220, 220), "radius": 4})
            points = [
                self.world_to_px(float(row["x"]), float(row["y"]))
                for _, row in recent.iterrows()
            ]
            if len(points) >= 2:
                pygame.draw.lines(overlay, style["color"] + (110,), False, points, 2)
            px, py = self.world_to_px(float(current_row["x"]), float(current_row["y"]))
            grenade_type = str(current_row["grenade_type"])
            if grenade_type == "CSmokeGrenadeProjectile":
                entity_id = pd.to_numeric(current_row.get("grenade_entity_id"), errors="coerce")
                if not pd.isna(entity_id):
                    smoke_start_tick = self.smoke_start_tick_by_entity.get(int(entity_id))
                    if smoke_start_tick is not None and frame_tick >= smoke_start_tick + SMOKE_DEPLOY_TICKS:
                        continue
            if grenade_type == "CFlashbangProjectile":
                entity_id = pd.to_numeric(current_row.get("grenade_entity_id"), errors="coerce")
                if not pd.isna(entity_id):
                    flash_start_tick = self.flash_start_tick_by_entity.get(int(entity_id))
                    if flash_start_tick is not None and frame_tick >= flash_start_tick:
                        continue
            if grenade_type == "CHEGrenadeProjectile":
                entity_id = pd.to_numeric(current_row.get("grenade_entity_id"), errors="coerce")
                if not pd.isna(entity_id):
                    he_effect = next(
                        (
                            effect
                            for effect in self.he_effects
                            if pd.to_numeric(effect.get("entityid"), errors="coerce") == int(entity_id)
                        ),
                        None,
                    )
                    if he_effect is not None and frame_tick >= int(he_effect["start_tick"]):
                        continue
            icon_key = current_row.get("burn_icon_path")
            if pd.isna(icon_key) or not icon_key:
                icon_key = grenade_type
            icon = self.grenade_icons.get(str(icon_key))
            if icon is not None:
                icon_rect = icon.get_rect(center=(int(round(px)), int(round(py))))
                overlay.blit(icon, icon_rect)
            else:
                pygame.draw.circle(overlay, style["color"] + (220,), (int(round(px)), int(round(py))), int(style["radius"]))
                pygame.draw.circle(surface, (20, 20, 20), (int(round(px)), int(round(py))), int(style["radius"]), 1)
        surface.blit(overlay, (0, 0))

    def _draw_smokes(self, surface: pygame.Surface, frame_tick: int) -> None:
        if not self.smoke_windows:
            return
        radius_px = max(8, int(round(self.world_dist_to_px(SMOKE_RADIUS_WORLD))))
        he_hole_radius_px = max(10, int(round(self.world_dist_to_px(HE_RADIUS_WORLD))))
        recovery_delay_ticks = int(round(self.tickrate * HE_SMOKE_HOLE_RECOVERY_DELAY_SECONDS))
        full_recovery_ticks = int(round(self.tickrate * HE_SMOKE_HOLE_FULL_RECOVERY_SECONDS))
        for smoke_index, smoke in enumerate(self.smoke_windows):
            start_tick = int(smoke["start_tick"])
            end_tick = int(smoke["end_tick"])
            if frame_tick < start_tick or frame_tick > end_tick:
                continue
            fade_ticks = 16
            if frame_tick - start_tick < fade_ticks:
                alpha_scale = (frame_tick - start_tick + 1) / fade_ticks
            elif end_tick - frame_tick < fade_ticks:
                alpha_scale = (end_tick - frame_tick + 1) / fade_ticks
            else:
                alpha_scale = 1.0
            growth_ticks = SMOKE_DEPLOY_TICKS
            growth_scale = min(1.0, max(0.35, (frame_tick - start_tick + 1) / growth_ticks))
            px, py = self.world_to_px(float(smoke["x"]), float(smoke["y"]))
            pulse = math.sin((frame_tick - start_tick) * SMOKE_PULSE_FREQUENCY) * SMOKE_PULSE_AMPLITUDE
            smoke_scale = max(0.2, (1.0 + pulse) * growth_scale)
            smoke_radius_px = max(1, int(round(radius_px * 1.02 * smoke_scale)))
            texture_size = smoke_radius_px * 2
            texture = pygame.transform.smoothscale(self.smoke_texture, (texture_size, texture_size)).copy()
            smoke_holes = self.smoke_holes_by_window.get(smoke_index, [])
            if smoke_holes:
                texture_scale = smoke_radius_px / max(1, radius_px)
                scaled_hole_radius_px = max(1, int(round(he_hole_radius_px * texture_scale)))
                hole_mask = pygame.Surface((texture_size, texture_size), pygame.SRCALPHA)
                hole_mask.fill((255, 255, 255, 255))
                smoke_center_x = float(smoke["x"])
                smoke_center_y = float(smoke["y"])
                for hole in smoke_holes:
                    hole_start_tick = int(hole["start_tick"])
                    if frame_tick < hole_start_tick:
                        continue
                    if frame_tick <= hole_start_tick + recovery_delay_ticks:
                        hole_alpha_scale = 0.0
                    elif frame_tick >= hole_start_tick + full_recovery_ticks:
                        hole_alpha_scale = 1.0
                    else:
                        hole_alpha_scale = (
                            frame_tick - (hole_start_tick + recovery_delay_ticks)
                        ) / max(1, full_recovery_ticks - recovery_delay_ticks)
                    if hole_alpha_scale >= 1.0:
                        continue
                    local_x = texture_size / 2 + (float(hole["x"]) - smoke_center_x) * texture_scale
                    local_y = texture_size / 2 - (float(hole["y"]) - smoke_center_y) * texture_scale
                    inner_alpha = max(0, min(255, int(round(255 * hole_alpha_scale))))
                    soft_mask = self._get_soft_circle_mask(scaled_hole_radius_px, inner_alpha)
                    soft_rect = soft_mask.get_rect(center=(int(round(local_x)), int(round(local_y))))
                    hole_mask.blit(soft_mask, soft_rect, special_flags=pygame.BLEND_RGBA_MULT)
                texture.blit(hole_mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            texture.set_alpha(max(0, min(255, int(255 * alpha_scale))))
            rect = texture.get_rect(center=(int(round(px)), int(round(py))))
            surface.blit(texture, rect)

    def _draw_infernos(self, surface: pygame.Surface, frame_tick: int) -> None:
        if not self.inferno_effects or not self.fire_animation_layers:
            return
        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        growth_ticks = max(1, int(round(self.tickrate * INFERNO_GROWTH_SECONDS)))
        for effect in self.inferno_effects:
            start_tick = int(effect["start_tick"])
            end_tick = int(effect["end_tick"])
            extinguish_tick = effect.get("extinguish_tick")
            if frame_tick < start_tick or frame_tick > end_tick:
                continue
            if extinguish_tick is not None and frame_tick >= int(extinguish_tick):
                continue
            full_radius_world = float(effect["full_radius_world"])
            elapsed = frame_tick - start_tick
            growth_progress = min(1.0, max(0.0, elapsed / growth_ticks))
            current_radius_world = full_radius_world * (
                INFERNO_INITIAL_RADIUS_SCALE + (1.0 - INFERNO_INITIAL_RADIUS_SCALE) * growth_progress
            )
            center_x = float(effect["x"])
            center_y = float(effect["y"])
            phase_tick = max(0, elapsed // 6)
            for tile in effect["tiles"]:
                tile_extinguish_tick = tile.get("extinguish_tick")
                if tile_extinguish_tick is not None and frame_tick >= int(tile_extinguish_tick):
                    continue
                tile_distance = math.sqrt(float(tile["offset_x"]) ** 2 + float(tile["offset_y"]) ** 2)
                if tile_distance > current_radius_world:
                    continue
                layer_name = str(tile["layer"])
                frames = self.fire_animation_layers.get(layer_name, [])
                if not frames:
                    continue
                phase = int(tile["phase"])
                frame = frames[(phase_tick + phase) % len(frames)]
                base_scale = float(tile["scale"])
                world_scale = 0.72 + 0.28 * growth_progress
                scaled_size = (
                    max(1, int(round(frame.get_width() * base_scale * world_scale))),
                    max(1, int(round(frame.get_height() * base_scale * world_scale))),
                )
                sprite = pygame.transform.smoothscale(frame, scaled_size)
                norm = tile_distance / max(1.0, full_radius_world)
                if layer_name == "02":
                    alpha = int(round(228 * max(0.24, 1.0 - norm * 0.50)))
                else:
                    alpha = int(round(192 * max(0.30, 1.0 - norm * 0.60)))
                sprite.set_alpha(max(0, min(255, alpha)))
                px, py = self.world_to_px(center_x + float(tile["offset_x"]), center_y + float(tile["offset_y"]))
                rect = sprite.get_rect(center=(int(round(px)), int(round(py))))
                overlay.blit(sprite, rect)
        surface.blit(overlay, (0, 0))

    def _draw_flash_effects(self, surface: pygame.Surface, frame_tick: int) -> None:
        if not self.flash_effects:
            return
        for flash in self.flash_effects:
            start_tick = int(flash["start_tick"])
            end_tick = int(flash["end_tick"])
            if frame_tick < start_tick or frame_tick > end_tick:
                continue
            progress = (frame_tick - start_tick) / max(1, end_tick - start_tick)
            fade = max(0.0, 1.0 - progress)
            px, py = self.world_to_px(float(flash["x"]), float(flash["y"]))
            if self.flash_eye_texture is not None:
                draw_flash_eye_texture(surface, self.flash_eye_texture, self.world_dist_to_px, px, py, fade)
            else:
                draw_flash_eye(surface, self.width, self.height, self.world_dist_to_px, px, py, fade)

    def _draw_he_effects(self, surface: pygame.Surface, frame_tick: int) -> None:
        if not self.he_effects or not self.he_animation_frames:
            return
        for effect in self.he_effects:
            start_tick = int(effect["start_tick"])
            end_tick = int(effect["end_tick"])
            if frame_tick < start_tick or frame_tick > end_tick:
                continue
            progress = (frame_tick - start_tick) / max(1, end_tick - start_tick)
            px, py = self.world_to_px(float(effect["x"]), float(effect["y"]))
            frame_count = len(self.he_animation_frames)
            frame_index = min(frame_count - 1, max(0, int(progress * frame_count)))
            frame = self.he_animation_frames[frame_index].copy()
            frame.set_alpha(205)
            frame_rect = frame.get_rect(center=(int(round(px)), int(round(py))))
            surface.blit(frame, frame_rect)

    def _bomb_state_at(self, frame_tick: int) -> dict[str, object] | None:
        return self.bomb_tracker.state_at(frame_tick)

    def _bomb_visual_state_at(self, frame_tick: int) -> dict[str, object] | None:
        return self.bomb_tracker.visual_state_at(frame_tick)

    def _draw_ground_bomb(self, surface: pygame.Surface, frame_tick: int) -> None:
        state = self._bomb_visual_state_at(frame_tick)
        if state is None:
            return
        kind = str(state.get("state"))
        if kind not in {"dropped", "planted", "defused"}:
            return
        icon = self.c4_icons.get(kind)
        if icon is None:
            return
        px, py = self.world_to_px(float(state["x"]), float(state["y"]))
        center = (int(round(px)), int(round(py)))
        if kind == "planted":
            self._draw_planted_bomb_timer(surface, center, frame_tick, state)
            self._blit_icon_with_shadow(surface, icon, center)
            self._draw_defuse_progress(surface, center, frame_tick)
            return
        if kind == "defused":
            self._blit_icon_with_glow(surface, icon, center, C4_DEFUSED_GLOW_COLOR)
            return
        self._blit_icon_with_shadow(surface, icon, center)

    def _draw_defuse_progress(self, surface: pygame.Surface, center: tuple[int, int], frame_tick: int) -> None:
        if not self.defuse_attempts:
            return
        attempt = None
        for item in self.defuse_attempts:
            start_tick = int(item["start_tick"])
            end_tick = int(item["end_tick"])
            if start_tick <= frame_tick <= end_tick:
                attempt = item
                break
            if str(item["status"]) == "aborted" and end_tick < frame_tick <= end_tick + DEFUSE_SHAKE_TICKS:
                attempt = item
                break
        if attempt is None:
            return
        start_tick = int(attempt["start_tick"])
        end_tick = int(attempt["end_tick"])
        duration_ticks = max(1, int(attempt["duration_ticks"]))
        status = str(attempt["status"])
        if status == "aborted" and frame_tick > end_tick:
            progress = max(0.0, min(1.0, (end_tick - start_tick) / duration_ticks))
            vanish_progress = (frame_tick - end_tick) / max(1, DEFUSE_SHAKE_TICKS)
            alpha_scale = max(0.0, 1.0 - vanish_progress)
            shake = math.sin(vanish_progress * math.pi * 4.0) * 4.0
        else:
            progress = max(0.0, min(1.0, (frame_tick - start_tick) / duration_ticks))
            alpha_scale = 1.0
            shake = 0.0
        if progress <= 0.0 and status != "aborted":
            return
        bar_width = 38
        bar_height = 7
        left = int(round(center[0] - bar_width / 2 + shake))
        top = int(round(center[1] - 18))
        shadow_rect = pygame.Rect(left + 1, top + 1, bar_width, bar_height)
        bg_rect = pygame.Rect(left, top, bar_width, bar_height)
        fill_width = max(0, min(bar_width, int(round(bar_width * progress))))
        fill_rect = pygame.Rect(left, top, fill_width, bar_height)
        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        shadow_alpha = int(round(180 * alpha_scale))
        fill_alpha = int(round(230 * alpha_scale))
        glow_alpha = int(round(110 * alpha_scale))
        glow_rect = pygame.Rect(left - 2, top - 2, bar_width + 4, bar_height + 4)
        pygame.draw.rect(overlay, DEFUSE_BAR_GLOW[:3] + (glow_alpha,), glow_rect, border_radius=5)
        pygame.draw.rect(overlay, DEFUSE_BAR_SHADOW[:3] + (shadow_alpha,), shadow_rect, border_radius=3)
        pygame.draw.rect(overlay, (16, 16, 16, int(round(195 * alpha_scale))), bg_rect, border_radius=3)
        if fill_width > 0:
            pygame.draw.rect(overlay, DEFUSE_BAR_COLOR + (fill_alpha,), fill_rect, border_radius=3)
            highlight_width = max(1, fill_width - 2)
            if highlight_width > 0:
                highlight_rect = pygame.Rect(left + 1, top + 1, highlight_width, max(1, bar_height // 2))
                pygame.draw.rect(overlay, (220, 255, 210, int(round(120 * alpha_scale))), highlight_rect, border_radius=2)
        pygame.draw.rect(overlay, (12, 12, 12, int(round(230 * alpha_scale))), bg_rect, width=1, border_radius=3)
        surface.blit(overlay, (0, 0))

    def _draw_carried_bomb_icon(self, surface: pygame.Surface, player: str, center: tuple[int, int], frame_tick: int) -> None:
        state = self._bomb_visual_state_at(frame_tick)
        if state is None or str(state.get("state")) != "carried":
            return
        if str(state.get("player")) != player:
            return
        icon = self.c4_icons.get("carried")
        if icon is None:
            return
        self._blit_icon_with_shadow(surface, icon, (center[0] - 8, center[1] + 8))

    def _draw_planted_bomb_timer(
        self,
        surface: pygame.Surface,
        center: tuple[int, int],
        frame_tick: int,
        state: dict[str, object],
    ) -> None:
        start_tick = int(state.get("start_tick", frame_tick))
        end_tick = int(state.get("end_tick", frame_tick))
        total_ticks = max(1, end_tick - start_tick + 1)
        elapsed_ticks = max(0, min(total_ticks, frame_tick - start_tick))
        progress = elapsed_ticks / total_ticks
        remaining_fraction = max(0.0, 1.0 - progress)
        if remaining_fraction <= 0.0:
            return

        icon = self.c4_icons.get("planted")
        icon_radius = max(6, (icon.get_width() // 2) if icon is not None else 6)
        ring_radius = icon_radius + 7
        ring_width = 3
        shadow_points = self._build_arc_points(center[0] + 1, center[1] + 1, ring_radius, remaining_fraction)
        ring_points = self._build_arc_points(center[0], center[1], ring_radius, remaining_fraction)
        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        if len(shadow_points) >= 2:
            pygame.draw.lines(overlay, (18, 18, 18, 170), False, shadow_points, ring_width + 1)
        if len(ring_points) >= 2:
            pygame.draw.lines(overlay, (220, 72, 72, 230), False, ring_points, ring_width)
        surface.blit(overlay, (0, 0))

    def _build_arc_points(
        self,
        center_x: int,
        center_y: int,
        radius: int,
        remaining_fraction: float,
    ) -> list[tuple[int, int]]:
        start_angle = -math.pi / 2
        visible_start = start_angle + (2 * math.pi * (1.0 - remaining_fraction))
        visible_end = start_angle + (2 * math.pi)
        step_count = max(24, int(round(72 * remaining_fraction)))
        points: list[tuple[int, int]] = []
        for index in range(step_count + 1):
            t = index / step_count
            angle = visible_start + (visible_end - visible_start) * t
            points.append(
                (
                    int(round(center_x + math.cos(angle) * radius)),
                    int(round(center_y + math.sin(angle) * radius)),
                )
            )
        return points

    def _smoke_is_active_at(self, px: float, py: float, frame_tick: int) -> bool:
        for smoke in self.smoke_windows:
            if frame_tick < int(smoke["start_tick"]) or frame_tick > int(smoke["end_tick"]):
                continue
            smoke_px, smoke_py = self.world_to_px(float(smoke["x"]), float(smoke["y"]))
            if (smoke_px - px) ** 2 + (smoke_py - py) ** 2 <= self.world_dist_to_px(SMOKE_RADIUS_WORLD) ** 2:
                return True
        return False

    def _draw_tracer_and_flash(self, surface: pygame.Surface, player: str, current: pd.Series, frame_tick: int) -> None:
        fire_event = self._latest_fire_event(player, frame_tick)
        if fire_event is None:
            return
        fire_tick = int(fire_event["tick"])
        elapsed = frame_tick - fire_tick
        if elapsed < 0 or elapsed > self.fire_flash_duration_ticks:
            return
        px, py = self.world_to_px(float(current["X"]), float(current["Y"]))
        yaw = float(current["yaw"])
        muzzle_px, muzzle_py = self._offset_point(px, py, yaw, 8.0)
        self._draw_tracer_line(surface, fire_event, muzzle_px, muzzle_py, yaw)
        self._draw_muzzle_flash(surface, muzzle_px, muzzle_py, yaw, 1.0 - (elapsed / self.fire_flash_duration_ticks))

    def _draw_tracer_line(self, surface: pygame.Surface, fire_event: pd.Series, start_x: float, start_y: float, yaw: float) -> None:
        hit_point = self._resolve_hit_point(fire_event)
        if hit_point is None:
            tracer_length = max(48.0, self.world_dist_to_px(320.0))
            end_x, end_y = self._offset_point(start_x, start_y, yaw, tracer_length)
        else:
            end_x, end_y = self.world_to_px(*hit_point)
        team_num = pd.to_numeric(fire_event.get("team_num"), errors="coerce")
        if team_num == 2:
            tracer_color = TRACER_T_COLOR
        elif team_num == 3:
            tracer_color = TRACER_CT_COLOR
        else:
            tracer_color = TRACER_NEUTRAL_COLOR
        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        pygame.draw.line(overlay, tracer_color, (start_x, start_y), (end_x, end_y), 2)
        surface.blit(overlay, (0, 0))

    def _draw_muzzle_flash(self, surface: pygame.Surface, muzzle_px: float, muzzle_py: float, yaw: float, fade: float) -> None:
        if self.muzzle_flash_sprite is None or self.muzzle_flash_anchor is None:
            return
        sprite = self.muzzle_flash_sprite.copy()
        sprite_width, sprite_height = sprite.get_size()
        scale = max(0.12, self.world_dist_to_px(48.0) / sprite_width)
        sprite = pygame.transform.smoothscale(sprite, (max(1, int(sprite_width * scale)), max(1, int(sprite_height * scale))))
        alpha = max(0, min(255, int(255 * fade)))
        sprite.set_alpha(alpha)

        scaled_anchor_x = self.muzzle_flash_anchor[0] * (sprite.get_width() / sprite_width)
        scaled_anchor_y = self.muzzle_flash_anchor[1] * (sprite.get_height() / sprite_height)
        padded_size = max(sprite.get_width(), sprite.get_height()) * 4
        centered = pygame.Surface((padded_size, padded_size), pygame.SRCALPHA)
        center_x = padded_size / 2
        center_y = padded_size / 2
        centered.blit(sprite, (center_x - scaled_anchor_x, center_y - scaled_anchor_y))
        rotated = pygame.transform.rotozoom(centered, yaw, 1.0)
        rect = rotated.get_rect(center=(int(round(muzzle_px)), int(round(muzzle_py))))
        surface.blit(rotated, rect)

    def _latest_fire_event(self, player: str, frame_tick: int) -> pd.Series | None:
        events = self.fire_lookup.get(player, [])
        latest: pd.Series | None = None
        for event in events:
            if int(event["tick"]) > frame_tick:
                break
            latest = event
        return latest

    def _resolve_hit_point(self, fire_event: pd.Series) -> tuple[float, float] | None:
        attacker_name = str(fire_event.get("user_name", ""))
        if not attacker_name:
            return None
        fire_tick = int(fire_event["tick"])
        hurts = self.hurt_lookup.get(attacker_name, [])
        for hurt in hurts:
            hurt_tick = int(hurt["tick"])
            if hurt_tick < fire_tick:
                continue
            if hurt_tick - fire_tick > self.hit_match_window_ticks:
                break
            hit_xy = self._extract_hurt_world_xy(hurt)
            if hit_xy is not None:
                return hit_xy
        return None

    def _extract_hurt_world_xy(self, hurt_event: pd.Series) -> tuple[float, float] | None:
        victim_name = hurt_event.get("user_name")
        if pd.isna(victim_name):
            return None
        hurt_tick = int(hurt_event["tick"])
        victim_rows = self.round_ticks[
            (self.round_ticks["name"] == str(victim_name))
            & (self.round_ticks["tick"] <= hurt_tick)
        ].sort_values("tick")
        if victim_rows.empty:
            return None
        victim_row = victim_rows.iloc[-1]
        return (float(victim_row["X"]), float(victim_row["Y"]))

    def _is_dead(self, player: str, frame_tick: int) -> bool:
        death_tick = self.death_tick_lookup.get(player)
        return death_tick is not None and frame_tick >= death_tick

    def _resolve_player_color(self, player: str, frame_tick: int, base_color: tuple[int, int, int]) -> tuple[int, int, int]:
        color = base_color
        flash = self._latest_damage_flash(player, frame_tick)
        if flash is not None:
            damage_tick, _damage = flash
            elapsed = frame_tick - damage_tick
            if 0 <= elapsed <= self.damage_flash_duration_ticks:
                fade = 1.0 - (elapsed / self.damage_flash_duration_ticks)
                color = tuple(
                    int(round((1.0 - fade) * base_channel + fade * overlay_channel))
                    for base_channel, overlay_channel in zip(color, (220, 48, 48))
                )
        blind_strength = self._blind_effect_strength(player, frame_tick)
        if blind_strength > 0.0:
            color = mix_with_white(color, blind_strength * 0.88)
        return color

    def _latest_damage_flash(self, player: str, frame_tick: int) -> tuple[int, float] | None:
        flashes = self.damage_flash_lookup.get(player, [])
        latest: tuple[int, float] | None = None
        for damage_tick, damage in flashes:
            if damage_tick > frame_tick:
                break
            latest = (damage_tick, damage)
        return latest

    def _blind_effect_strength(self, player: str, frame_tick: int) -> float:
        return self.blind_tracker.strength_at(player, frame_tick)

    def _offset_point(self, px: float, py: float, yaw: float, distance: float) -> tuple[float, float]:
        radians = math.radians(-yaw)
        return (px + math.cos(radians) * distance, py + math.sin(radians) * distance)

class PygameRoundViewer:
    def __init__(
        self,
        data_dir: Path,
        initial_round_id: int | None,
        map_width: int,
        map_height: int,
        fps: int,
        frame_step: int,
        tickrate: float,
    ) -> None:
        pygame.init()
        pygame.font.init()
        self.data_dir = data_dir
        self.fps = fps
        self.tickrate = tickrate
        self.frame_step = max(1, frame_step)
        (
            self.ticks,
            self.deaths,
            self.fires,
            self.hurts,
            self.hits,
            self.smoke_detonates,
            self.flash_detonates,
            self.he_detonates,
            self.blinds,
            self.bomb_pickups,
            self.bomb_drops,
            self.bomb_plants,
            self.bomb_defuses,
            self.bomb_begin_defuses,
            self.bomb_abort_defuses,
            self.bomb_explodes,
            self.smoke_expires,
            self.inferno_starts,
            self.grenades,
            self.inferred_rounds,
            self.metadata,
        ) = load_round_data(data_dir)
        self.map_width, self.map_height = self._resolve_map_viewport_size(map_width, map_height)
        self.screen = pygame.display.set_mode((self.map_width + SIDEBAR_WIDTH, self.map_height + BOTTOM_BAR_HEIGHT))
        pygame.display.set_caption("wall pygame viewer")
        self.clock = pygame.time.Clock()
        self.round_ids = sorted(self.inferred_rounds["inferred_round_id"].astype(int).tolist())
        if not self.round_ids:
            raise ValueError("No inferred rounds found in inferred_rounds table")
        self.player_numbers = self._build_demo_hud_numbers()
        self.selected_round_id = initial_round_id if initial_round_id in self.round_ids else self.round_ids[0]
        self.round_cache: RoundCache | None = None
        self.current_frame_index = 0
        self.current_playback_tick = 0.0
        self.playing = False
        self.dragging_timeline = False
        self.dragging_round_scroll = False
        self.max_cached_frames = 240
        self.speed_index = SPEED_OPTIONS.index(1.0)
        self.font = pygame.font.SysFont("segoe ui", 18)
        self.small_font = pygame.font.SysFont("segoe ui", 14)
        self.button_rects: dict[str, pygame.Rect] = {}
        self.round_item_rects: dict[int, pygame.Rect] = {}
        self.speed_rects: dict[float, pygame.Rect] = {}
        self.round_scroll_area_rect = pygame.Rect(0, 0, 0, 0)
        self.round_scroll_track_rect = pygame.Rect(0, 0, 0, 0)
        self.round_scroll_thumb_rect = pygame.Rect(0, 0, 0, 0)
        self.round_dropdown_open = False
        self.round_dropdown_start = 0
        self.select_round(self.selected_round_id)

    def _resolve_map_viewport_size(self, target_width: int, target_height: int) -> tuple[int, int]:
        map_name = self.metadata.get("derived", {}).get("map_name")
        if not map_name:
            return target_width, target_height
        map_path = awpy_maps_dir() / f"{map_name}.png"
        if not map_path.exists():
            return target_width, target_height
        try:
            map_surface = pygame.image.load(str(map_path))
            original_width, original_height = map_surface.get_size()
        except pygame.error:
            return target_width, target_height
        if original_width <= 0 or original_height <= 0:
            return target_width, target_height
        scale = min(target_width / original_width, target_height / original_height)
        width = max(1, int(round(original_width * scale)))
        height = max(1, int(round(original_height * scale)))
        return width, height

    def select_round(self, round_id: int) -> None:
        self.selected_round_id = round_id
        self.round_dropdown_open = False
        selected_index = self.round_ids.index(round_id)
        self.round_dropdown_start = max(0, min(selected_index, max(0, len(self.round_ids) - 5)))
        round_data = get_round_data(
            self.ticks,
            self.deaths,
            self.fires,
            self.hurts,
            self.hits,
            self.smoke_detonates,
            self.flash_detonates,
            self.he_detonates,
            self.blinds,
            self.bomb_pickups,
            self.bomb_drops,
            self.bomb_plants,
            self.bomb_defuses,
            self.bomb_begin_defuses,
            self.bomb_abort_defuses,
            self.bomb_explodes,
            self.smoke_expires,
            self.inferno_starts,
            self.grenades,
            round_id,
        )
        renderer = PygameRoundRenderer(
            round_ticks=round_data.round_ticks,
            round_deaths=round_data.round_deaths,
            round_fires=round_data.round_fires,
            round_hurts=round_data.round_hurts,
            round_smoke_detonates=round_data.round_smoke_detonates,
            round_flash_detonates=round_data.round_flash_detonates,
            round_he_detonates=round_data.round_he_detonates,
            round_blinds=round_data.round_blinds,
            round_bomb_pickups=round_data.round_bomb_pickups,
            round_bomb_drops=round_data.round_bomb_drops,
            round_bomb_plants=round_data.round_bomb_plants,
            round_bomb_defuses=round_data.round_bomb_defuses,
            round_bomb_begin_defuses=round_data.round_bomb_begin_defuses,
            round_bomb_abort_defuses=round_data.round_bomb_abort_defuses,
            round_bomb_explodes=round_data.round_bomb_explodes,
            round_smoke_expires=round_data.round_smoke_expires,
            round_inferno_starts=round_data.round_inferno_starts,
            round_grenades=round_data.round_grenades,
            player_numbers=self.player_numbers,
            width=self.map_width,
            height=self.map_height,
            trail=24,
            facing_radius=70.0,
            facing_fov=90.0,
            map_name=self.metadata.get("derived", {}).get("map_name"),
            tickrate=self.tickrate,
        )
        frame_ticks = renderer.frame_ticks[:: self.frame_step]
        last_tick = renderer.frame_ticks[-1]
        if frame_ticks[-1] != last_tick:
            frame_ticks = list(frame_ticks) + [last_tick]
        self.round_cache = RoundCache(
            round_id=round_id,
            renderer=renderer,
            frame_ticks=[int(tick) for tick in frame_ticks],
            cache=OrderedDict(),
        )
        self.current_frame_index = 0
        self.current_playback_tick = float(self.round_cache.frame_ticks[0])
        self.playing = False
        self._ensure_cached(0)

    def _build_demo_hud_numbers(self) -> dict[str, int]:
        if self.ticks.empty or "name" not in self.ticks.columns:
            return {}
        work = self.ticks[["tick", "name", "team_num"]].copy()
        work = work[work["name"].notna()].copy()
        work["team_num"] = pd.to_numeric(work["team_num"], errors="coerce")
        work = work[work["team_num"].isin([2, 3])].sort_values(["tick", "name"]).copy()
        first_seen = work.groupby("name", sort=False).first().reset_index()

        player_numbers: dict[str, int] = {}
        team_slots = {2: [1, 2, 3, 4, 5], 3: [6, 7, 8, 9, 10]}
        for team_num in (2, 3):
            team_rows = first_seen[first_seen["team_num"] == team_num].sort_values(["tick", "name"])
            slots = team_slots[team_num]
            for slot, player in zip(slots, team_rows["name"].tolist()):
                player_numbers[str(player)] = slot

        remaining_players = sorted(set(self.ticks["name"].dropna().astype(str)) - set(player_numbers))
        next_number = 11
        for player in remaining_players:
            player_numbers[player] = next_number
            next_number += 1
        return player_numbers

    def _ensure_cached(self, frame_index: int) -> None:
        if self.round_cache is None:
            return
        frame_index = max(0, min(frame_index, len(self.round_cache.frame_ticks) - 1))
        if frame_index in self.round_cache.cache:
            self.round_cache.cache.move_to_end(frame_index)
            return
        surface = self.round_cache.renderer.render_map_frame(self.round_cache.frame_ticks[frame_index]).convert()
        self.round_cache.cache[frame_index] = surface
        while len(self.round_cache.cache) > self.max_cached_frames:
            self.round_cache.cache.popitem(last=False)

    def run(self) -> None:
        running = True
        while running:
            dt_seconds = self.clock.tick(self.fps) / 1000.0
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    running = self._handle_keydown(event)
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    button = getattr(event, "button", None)
                    if button == 4:
                        self._handle_mousewheel(1, event.pos)
                    elif button == 5:
                        self._handle_mousewheel(-1, event.pos)
                    elif button == 1:
                        self._handle_mouse_down(event.pos)
                elif event.type == pygame.MOUSEWHEEL:
                    self._handle_mousewheel(event.y, pygame.mouse.get_pos())
                elif event.type == pygame.MOUSEBUTTONUP:
                    self.dragging_timeline = False
                    self.dragging_round_scroll = False
                elif event.type == pygame.MOUSEMOTION:
                    if self.dragging_timeline:
                        self._update_timeline_from_mouse(event.pos)
                    elif self.dragging_round_scroll:
                        self._update_round_scroll_from_mouse(event.pos)

            if self.playing and self.round_cache is not None:
                self._advance_playback(dt_seconds)
            self._draw()
            pygame.display.flip()
        pygame.quit()

    def _handle_keydown(self, event: pygame.event.Event) -> bool:
        if event.key == pygame.K_ESCAPE:
            return False
        if self.round_cache is None:
            return True
        if event.key == pygame.K_SPACE:
            self.playing = not self.playing
        elif event.key == pygame.K_RIGHT:
            self.current_frame_index = min(self.current_frame_index + 1, len(self.round_cache.frame_ticks) - 1)
            self.current_playback_tick = float(self.round_cache.frame_ticks[self.current_frame_index])
            self._ensure_cached(self.current_frame_index)
        elif event.key == pygame.K_LEFT:
            self.current_frame_index = max(self.current_frame_index - 1, 0)
            self.current_playback_tick = float(self.round_cache.frame_ticks[self.current_frame_index])
            self._ensure_cached(self.current_frame_index)
        elif event.key == pygame.K_DOWN:
            self._change_round(1)
        elif event.key == pygame.K_UP:
            self._change_round(-1)
        elif event.key in (pygame.K_MINUS, pygame.K_LEFTBRACKET):
            self._change_speed(-1)
        elif event.key in (pygame.K_EQUALS, pygame.K_RIGHTBRACKET):
            self._change_speed(1)
        elif event.key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5, pygame.K_6):
            self.speed_index = event.key - pygame.K_1
        return True

    def _handle_mouse_down(self, position: tuple[int, int]) -> None:
        dropdown_rect = self.button_rects.get("round_dropdown")
        if dropdown_rect and dropdown_rect.collidepoint(position):
            self.round_dropdown_open = not self.round_dropdown_open
            if self.round_dropdown_open:
                selected_index = self.round_ids.index(self.selected_round_id)
                self.round_dropdown_start = max(0, min(selected_index, max(0, len(self.round_ids) - 5)))
            return
        if self.button_rects.get("round_scroll_up") and self.button_rects["round_scroll_up"].collidepoint(position):
            self._scroll_round_dropdown(1)
            return
        if self.button_rects.get("round_scroll_down") and self.button_rects["round_scroll_down"].collidepoint(position):
            self._scroll_round_dropdown(-1)
            return
        if self.round_scroll_thumb_rect.collidepoint(position):
            self.dragging_round_scroll = True
            self._update_round_scroll_from_mouse(position)
            return
        if self.round_scroll_track_rect.collidepoint(position):
            self._jump_round_scroll_to_mouse(position)
            return
        for round_id, rect in self.round_item_rects.items():
            if rect.collidepoint(position):
                self.select_round(round_id)
                return
        if self.button_rects.get("prev_round") and self.button_rects["prev_round"].collidepoint(position):
            self._change_round(-1)
            return
        if self.button_rects.get("play") and self.button_rects["play"].collidepoint(position):
            self.playing = not self.playing
            return
        if self.button_rects.get("next_round") and self.button_rects["next_round"].collidepoint(position):
            self._change_round(1)
            return
        for speed_value, rect in self.speed_rects.items():
            if rect.collidepoint(position):
                self.speed_index = SPEED_OPTIONS.index(speed_value)
                return
        if self.button_rects.get("timeline") and self.button_rects["timeline"].collidepoint(position):
            self.dragging_timeline = True
            self._update_timeline_from_mouse(position)
            return
        self.round_dropdown_open = False

    def _handle_mousewheel(self, delta: int, position: tuple[int, int] | None = None) -> None:
        if not self.round_dropdown_open or len(self.round_ids) <= 5:
            return
        if position is not None:
            hit_dropdown = (
                self.round_scroll_area_rect.collidepoint(position)
                or self.round_scroll_track_rect.collidepoint(position)
                or self.round_scroll_thumb_rect.collidepoint(position)
                or (self.button_rects.get("round_dropdown") and self.button_rects["round_dropdown"].collidepoint(position))
            )
            if not hit_dropdown:
                return
        self._scroll_round_dropdown(delta)

    def _scroll_round_dropdown(self, delta: int) -> None:
        max_start = max(0, len(self.round_ids) - 5)
        self.round_dropdown_start = max(0, min(self.round_dropdown_start - delta, max_start))

    def _jump_round_scroll_to_mouse(self, position: tuple[int, int]) -> None:
        if len(self.round_ids) <= 5 or self.round_scroll_track_rect.height <= 0:
            return
        max_start = max(0, len(self.round_ids) - 5)
        relative_y = position[1] - self.round_scroll_track_rect.y
        ratio = max(0.0, min(1.0, relative_y / max(1, self.round_scroll_track_rect.height)))
        self.round_dropdown_start = int(round(ratio * max_start))

    def _update_round_scroll_from_mouse(self, position: tuple[int, int]) -> None:
        if len(self.round_ids) <= 5 or self.round_scroll_track_rect.height <= 0 or self.round_scroll_thumb_rect.height <= 0:
            return
        max_start = max(0, len(self.round_ids) - 5)
        thumb_half = self.round_scroll_thumb_rect.height / 2
        relative_y = position[1] - self.round_scroll_track_rect.y - thumb_half
        thumb_travel = max(1.0, self.round_scroll_track_rect.height - self.round_scroll_thumb_rect.height)
        ratio = max(0.0, min(1.0, relative_y / thumb_travel))
        self.round_dropdown_start = int(round(ratio * max_start))

    def _update_timeline_from_mouse(self, position: tuple[int, int]) -> None:
        if self.round_cache is None:
            return
        timeline_rect = self.button_rects.get("timeline")
        if timeline_rect is None:
            return
        ratio = (position[0] - timeline_rect.x) / max(1, timeline_rect.width)
        ratio = max(0.0, min(1.0, ratio))
        frame_index = int(round(ratio * max(0, len(self.round_cache.frame_ticks) - 1)))
        self.current_frame_index = frame_index
        self.current_playback_tick = float(self.round_cache.frame_ticks[frame_index])
        self._ensure_cached(frame_index)

    def _advance_playback(self, dt_seconds: float) -> None:
        if self.round_cache is None:
            return
        speed = SPEED_OPTIONS[self.speed_index]
        self.current_playback_tick += dt_seconds * self.tickrate * speed
        last_tick = float(self.round_cache.frame_ticks[-1])
        if self.current_playback_tick >= last_tick:
            self.current_playback_tick = last_tick
            self.current_frame_index = len(self.round_cache.frame_ticks) - 1
            self.playing = False
            self._ensure_cached(self.current_frame_index)
            return
        frame_index = bisect.bisect_right(self.round_cache.frame_ticks, self.current_playback_tick) - 1
        self.current_frame_index = max(0, min(frame_index, len(self.round_cache.frame_ticks) - 1))
        self._ensure_cached(self.current_frame_index)

    def _change_speed(self, delta: int) -> None:
        self.speed_index = max(0, min(self.speed_index + delta, len(SPEED_OPTIONS) - 1))

    def _change_round(self, delta: int) -> None:
        index = self.round_ids.index(self.selected_round_id)
        next_index = max(0, min(index + delta, len(self.round_ids) - 1))
        if next_index != index:
            self.select_round(self.round_ids[next_index])

    def _draw_media_icon(self, rect: pygame.Rect, kind: str, color: tuple[int, int, int]) -> None:
        cx, cy = rect.center
        icon_height = 12
        half_height = icon_height // 2
        if kind == "prev":
            group_left = cx - 6
            bar = pygame.Rect(group_left, cy - half_height, 2, icon_height)
            pygame.draw.rect(self.screen, color, bar, border_radius=1)
            points = [(group_left + 4, cy), (group_left + 11, cy - half_height), (group_left + 11, cy + half_height)]
            pygame.draw.polygon(self.screen, color, points)
        elif kind == "next":
            group_left = cx - 6
            bar = pygame.Rect(group_left + 9, cy - half_height, 2, icon_height)
            pygame.draw.rect(self.screen, color, bar, border_radius=1)
            points = [(group_left, cy - half_height), (group_left, cy + half_height), (group_left + 7, cy)]
            pygame.draw.polygon(self.screen, color, points)
        elif kind == "pause":
            left_bar = pygame.Rect(cx - 6, cy - half_height, 4, icon_height)
            right_bar = pygame.Rect(cx + 2, cy - half_height, 4, icon_height)
            pygame.draw.rect(self.screen, color, left_bar, border_radius=1)
            pygame.draw.rect(self.screen, color, right_bar, border_radius=1)
        else:
            points = [(cx + 5, cy), (cx - 4, cy - half_height), (cx - 4, cy + half_height)]
            pygame.draw.polygon(self.screen, color, points)

    def _speed_button_rects(self, start_y: int) -> dict[float, pygame.Rect]:
        if self.round_cache is None:
            return {}
        x = self.map_width + 16
        y = start_y
        rects: dict[float, pygame.Rect] = {}
        for index, speed in enumerate(SPEED_OPTIONS):
            col = index % 3
            row = index // 3
            rects[speed] = pygame.Rect(x + col * 84, y + row * 36, 74, 28)
        return rects

    def _draw(self) -> None:
        self.screen.fill(BACKGROUND_COLOR)
        if self.round_cache is not None:
            self._ensure_cached(self.current_frame_index)
            map_surface = self.round_cache.cache[self.current_frame_index]
            self.screen.blit(map_surface, (0, 0))
        self._draw_sidebar()
        self._draw_bottom_bar()

    def _draw_sidebar(self) -> None:
        sidebar_rect = pygame.Rect(self.map_width, 0, SIDEBAR_WIDTH, self.map_height + BOTTOM_BAR_HEIGHT)
        pygame.draw.rect(self.screen, SIDEBAR_COLOR, sidebar_rect)
        self.button_rects = {key: value for key, value in self.button_rects.items() if key == "timeline"}
        self.round_item_rects = {}
        self.speed_rects = {}
        self.round_scroll_area_rect = pygame.Rect(0, 0, 0, 0)
        self.round_scroll_track_rect = pygame.Rect(0, 0, 0, 0)
        self.round_scroll_thumb_rect = pygame.Rect(0, 0, 0, 0)
        x = self.map_width + 16
        y = 16

        title = self.font.render("Controls", True, TEXT_COLOR)
        self.screen.blit(title, (x, y))
        y += 32

        round_title = self.small_font.render("Round", True, MUTED_TEXT_COLOR)
        self.screen.blit(round_title, (x, y))
        y += 22
        dropdown_rect = pygame.Rect(x, y, SIDEBAR_WIDTH - 32, 32)
        self.button_rects["round_dropdown"] = dropdown_rect
        pygame.draw.rect(self.screen, BUTTON_ACTIVE_COLOR if self.round_dropdown_open else BUTTON_COLOR, dropdown_rect, border_radius=4)
        dropdown_label = self.small_font.render(f"Round {self.selected_round_id}", True, TEXT_COLOR)
        self.screen.blit(dropdown_label, (dropdown_rect.x + 10, dropdown_rect.y + 7))
        arrow = "^" if self.round_dropdown_open else "v"
        arrow_label = self.small_font.render(arrow, True, TEXT_COLOR)
        self.screen.blit(arrow_label, (dropdown_rect.right - 22, dropdown_rect.y + 7))
        y += 40
        dropdown_overlay: tuple[
            pygame.Rect,
            list[tuple[int, pygame.Rect, tuple[int, int, int]]],
            tuple[pygame.Rect, pygame.Rect, pygame.Rect, pygame.Rect] | None,
        ] | None = None
        if self.round_dropdown_open:
            max_start = max(0, len(self.round_ids) - 5)
            self.round_dropdown_start = max(0, min(self.round_dropdown_start, max_start))
            visible_rounds = self.round_ids[self.round_dropdown_start : self.round_dropdown_start + 5]
            list_top = y
            list_width = SIDEBAR_WIDTH - 32
            scroll_enabled = len(self.round_ids) > 5
            arrow_width = 22 if scroll_enabled else 0
            item_width = list_width - (arrow_width + 6 if scroll_enabled else 0)
            overlay_bottom = list_top
            item_specs: list[tuple[int, pygame.Rect, tuple[int, int, int]]] = []
            for round_id in visible_rounds:
                rect = pygame.Rect(x, overlay_bottom, item_width, 26)
                self.round_item_rects[round_id] = rect
                color = ACCENT_COLOR if round_id == self.selected_round_id else BUTTON_COLOR
                item_specs.append((round_id, rect, color))
                overlay_bottom += 30
            list_height = overlay_bottom - list_top
            list_rect = pygame.Rect(x - 4, list_top - 4, list_width + 8, list_height + 8)
            self.round_scroll_area_rect = pygame.Rect(x, list_top, list_width, list_height)
            scroll_specs: tuple[pygame.Rect, pygame.Rect, pygame.Rect, pygame.Rect] | None = None
            if scroll_enabled:
                track_x = x + item_width + 6
                up_rect = pygame.Rect(track_x, list_top, arrow_width, 24)
                down_rect = pygame.Rect(track_x, list_top + list_height - 24, arrow_width, 24)
                track_rect = pygame.Rect(track_x, up_rect.bottom + 4, arrow_width, max(8, list_height - 56))
                self.button_rects["round_scroll_up"] = up_rect
                self.button_rects["round_scroll_down"] = down_rect
                self.round_scroll_track_rect = track_rect
                visible_count = 5
                thumb_height = max(20, int(round(track_rect.height * visible_count / len(self.round_ids))))
                max_start = max(1, len(self.round_ids) - visible_count)
                thumb_travel = max(0, track_rect.height - thumb_height)
                thumb_offset = int(round(thumb_travel * (self.round_dropdown_start / max_start)))
                thumb_rect = pygame.Rect(track_rect.x + 3, track_rect.y + thumb_offset, track_rect.width - 6, thumb_height)
                self.round_scroll_thumb_rect = thumb_rect
                scroll_specs = (up_rect, down_rect, track_rect, thumb_rect)
            dropdown_overlay = (list_rect, item_specs, scroll_specs)

        if self.round_cache is None:
            return

        button_gap = 8
        button_width = (SIDEBAR_WIDTH - 32 - button_gap * 2) // 3
        prev_rect = pygame.Rect(x, y, button_width, 32)
        play_rect = pygame.Rect(prev_rect.right + button_gap, y, button_width, 32)
        next_rect = pygame.Rect(play_rect.right + button_gap, y, button_width, 32)
        self.button_rects["prev_round"] = prev_rect
        self.button_rects["play"] = play_rect
        self.button_rects["next_round"] = next_rect
        prev_active = self.selected_round_id != self.round_ids[0]
        next_active = self.selected_round_id != self.round_ids[-1]
        icon_color = (214, 214, 214)
        inactive_icon = (112, 112, 112)
        pygame.draw.rect(self.screen, BUTTON_COLOR if prev_active else (42, 42, 42), prev_rect, border_radius=4)
        pygame.draw.rect(self.screen, BUTTON_ACTIVE_COLOR if self.playing else BUTTON_COLOR, play_rect, border_radius=4)
        pygame.draw.rect(self.screen, BUTTON_COLOR if next_active else (42, 42, 42), next_rect, border_radius=4)
        self._draw_media_icon(prev_rect, "prev", icon_color if prev_active else inactive_icon)
        self._draw_media_icon(play_rect, "pause" if self.playing else "play", icon_color)
        self._draw_media_icon(next_rect, "next", icon_color if next_active else inactive_icon)
        y += 48

        progress_text = self.small_font.render(f"Cached {len(self.round_cache.cache)} frames", True, MUTED_TEXT_COLOR)
        self.screen.blit(progress_text, (x, y))
        y += 28

        current_tick = self.round_cache.frame_ticks[self.current_frame_index]
        relative_tick = current_tick - self.round_cache.renderer.round_start_tick
        relative_seconds = relative_tick / self.tickrate if self.tickrate > 0 else 0.0
        tick_text = self.small_font.render(
            f"Round tick {relative_tick} | {relative_seconds:.2f}s | frame {self.current_frame_index + 1}/{len(self.round_cache.frame_ticks)}",
            True,
            MUTED_TEXT_COLOR,
        )
        self.screen.blit(tick_text, (x, y))
        y += 36

        speed_title = self.font.render("Speed", True, TEXT_COLOR)
        self.screen.blit(speed_title, (x, y))
        y += 34
        self.speed_rects = self._speed_button_rects(y)
        for speed_value, rect in self.speed_rects.items():
            active = speed_value == SPEED_OPTIONS[self.speed_index]
            pygame.draw.rect(self.screen, BUTTON_ACTIVE_COLOR if active else BUTTON_COLOR, rect, border_radius=4)
            label = self.small_font.render(self._format_speed_label(speed_value), True, TEXT_COLOR)
            label_rect = label.get_rect(center=rect.center)
            self.screen.blit(label, label_rect)
        if self.speed_rects:
            y = max(rect.bottom for rect in self.speed_rects.values()) + 24

        legend_title = self.font.render("Players", True, TEXT_COLOR)
        self.screen.blit(legend_title, (x, y))
        y += 30
        for player in self.round_cache.renderer.players:
            number = self.round_cache.renderer.player_numbers[player]
            color = team_color(self._latest_team_num(player))
            pygame.draw.rect(self.screen, color, (x, y + 4, 12, 12))
            label = self.small_font.render(f"{format_hud_number(number)}. {player}", True, TEXT_COLOR)
            self.screen.blit(label, (x + 20, y))
            y += 22

        if dropdown_overlay is not None:
            list_rect, item_specs, scroll_specs = dropdown_overlay
            pygame.draw.rect(self.screen, SIDEBAR_COLOR, list_rect, border_radius=6)
            pygame.draw.rect(self.screen, (66, 66, 66), list_rect, 1, border_radius=6)
            for round_id, rect, color in item_specs:
                pygame.draw.rect(self.screen, color, rect, border_radius=4)
                label = self.small_font.render(f"Round {round_id}", True, TEXT_COLOR)
                self.screen.blit(label, (rect.x + 10, rect.y + 5))
            if scroll_specs is not None:
                up_rect, down_rect, track_rect, thumb_rect = scroll_specs
                pygame.draw.rect(self.screen, BUTTON_COLOR, up_rect, border_radius=4)
                pygame.draw.rect(self.screen, BUTTON_COLOR, down_rect, border_radius=4)
                pygame.draw.rect(self.screen, (58, 58, 58), track_rect, border_radius=4)
                up_label = self.small_font.render("^", True, TEXT_COLOR)
                down_label = self.small_font.render("v", True, TEXT_COLOR)
                self.screen.blit(up_label, up_label.get_rect(center=up_rect.center))
                self.screen.blit(down_label, down_label.get_rect(center=down_rect.center))
                pygame.draw.rect(self.screen, ACCENT_COLOR, thumb_rect, border_radius=4)

    def _latest_team_num(self, player: str) -> int | float | None:
        if self.round_cache is None:
            return None
        rows = self.round_cache.renderer.round_ticks[self.round_cache.renderer.round_ticks["name"] == player]
        if rows.empty:
            return None
        return rows.iloc[-1].get("team_num")

    def _draw_bottom_bar(self) -> None:
        if self.round_cache is None:
            return
        bar_rect = pygame.Rect(0, self.map_height, self.map_width, BOTTOM_BAR_HEIGHT)
        pygame.draw.rect(self.screen, (24, 24, 24), bar_rect)
        timeline_rect = pygame.Rect(16, self.map_height + 20, self.map_width - 32, 16)
        self.button_rects["timeline"] = timeline_rect
        pygame.draw.rect(self.screen, (70, 70, 70), timeline_rect, border_radius=8)
        if len(self.round_cache.frame_ticks) > 1:
            ratio = self.current_frame_index / (len(self.round_cache.frame_ticks) - 1)
        else:
            ratio = 0.0
        fill_width = int(round(timeline_rect.width * ratio))
        pygame.draw.rect(
            self.screen,
            ACCENT_COLOR,
            pygame.Rect(timeline_rect.x, timeline_rect.y, max(8, fill_width), timeline_rect.height),
            border_radius=8,
        )
        speed_text = self.small_font.render(
            f"{self._format_speed_label(SPEED_OPTIONS[self.speed_index])} | tickrate {self.tickrate:g}",
            True,
            MUTED_TEXT_COLOR,
        )
        self.screen.blit(speed_text, (16, self.map_height + 42))

    def _format_speed_label(self, speed: float) -> str:
        if speed < 1.0:
            return f"1/{int(round(1.0 / speed))}x"
        if float(speed).is_integer():
            return f"{int(speed)}x"
        return f"{speed:g}x"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pygame viewer for inferred CS rounds.")
    parser.add_argument("data_dir", type=Path, help="Directory containing parsed output tables")
    parser.add_argument("--round", dest="round_id", type=int, help="Initial round to select")
    parser.add_argument("--map-width", type=int, default=1200, help="Map viewport width")
    parser.add_argument("--map-height", type=int, default=900, help="Map viewport height")
    parser.add_argument("--fps", type=int, default=60, help="Target viewer refresh rate")
    parser.add_argument("--frame-step", type=int, default=1, help="Animate every Nth tick")
    parser.add_argument("--tickrate", type=float, default=64.0, help="Playback tickrate for real-time speed sync")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    viewer = PygameRoundViewer(
        data_dir=args.data_dir,
        initial_round_id=args.round_id,
        map_width=args.map_width,
        map_height=args.map_height,
        fps=args.fps,
        frame_step=args.frame_step,
        tickrate=args.tickrate,
    )
    viewer.run()


if __name__ == "__main__":
    main()
