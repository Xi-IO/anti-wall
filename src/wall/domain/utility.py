from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Callable

import pandas as pd


@dataclass(frozen=True)
class SmokeWindow:
    start_tick: int
    end_tick: int
    x: float
    y: float
    entity_id: int | None = None


@dataclass(frozen=True)
class FlashEffect:
    entity_id: int
    start_tick: int
    end_tick: int
    x: float
    y: float


@dataclass(frozen=True)
class HeEffect:
    entity_id: int
    start_tick: int
    end_tick: int
    x: float
    y: float


@dataclass(frozen=True)
class InfernoTile:
    layer: str
    offset_x: float
    offset_y: float
    scale: float
    phase: int
    extinguish_tick: int | None = None


@dataclass(frozen=True)
class InfernoEffect:
    entity_id: int
    start_tick: int
    end_tick: int
    x: float
    y: float
    team_num: int | None
    full_radius_world: float
    extinguish_tick: int | None
    tiles: list[InfernoTile]


@dataclass(frozen=True)
class GrenadeTrail:
    points: tuple["GrenadeTrailPoint", ...]
    grenade_type: str
    burn_icon_path: str | None
    did_burn: bool
    smoke_start_tick: int | None = None
    flash_start_tick: int | None = None
    he_burst_start_tick: int | None = None

    def point_at_tick(self, frame_tick: int) -> "GrenadeTrailPoint | None":
        for point in reversed(self.points):
            if point.tick == frame_tick:
                return point
            if point.tick < frame_tick:
                break
        return None

    def recent_points_at(self, frame_tick: int, recent_window_ticks: int) -> list["GrenadeTrailPoint"]:
        return [
            point
            for point in self.points
            if frame_tick - recent_window_ticks <= point.tick <= frame_tick
        ]

    def should_hide_at(self, frame_tick: int, smoke_deploy_ticks: int) -> bool:
        if self.grenade_type == "CSmokeGrenadeProjectile":
            return self.smoke_start_tick is not None and frame_tick >= self.smoke_start_tick + smoke_deploy_ticks
        if self.grenade_type == "CFlashbangProjectile":
            return self.flash_start_tick is not None and frame_tick >= self.flash_start_tick
        if self.grenade_type == "CHEGrenadeProjectile":
            return self.he_burst_start_tick is not None and frame_tick >= self.he_burst_start_tick
        return False


@dataclass(frozen=True)
class GrenadeTrailPoint:
    tick: int
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class ActiveGrenadeTrail:
    grenade_type: str
    burn_icon_path: str | None
    current_x: float
    current_y: float
    recent_points: tuple[GrenadeTrailPoint, ...]


@dataclass(frozen=True)
class SmokeHole:
    start_tick: int
    x: float
    y: float


class UtilityTimeline:
    def __init__(
        self,
        round_smoke_detonates: pd.DataFrame,
        round_smoke_expires: pd.DataFrame,
        round_flash_detonates: pd.DataFrame,
        round_he_detonates: pd.DataFrame,
        round_inferno_starts: pd.DataFrame,
        round_grenades: pd.DataFrame,
        flash_effect_ticks: int,
        he_effect_ticks: int,
        inferno_duration_ticks: int,
        inferno_ct_radius_world: float,
        inferno_t_radius_world: float,
        smoke_radius_world: float,
        smoke_deploy_ticks: int,
        player_team_lookup: Callable[[str, str | None, int], int | None],
    ) -> None:
        self.round_smoke_detonates = round_smoke_detonates.sort_values(["tick"]).copy() if not round_smoke_detonates.empty else round_smoke_detonates.copy()
        self.round_smoke_expires = round_smoke_expires.sort_values(["tick"]).copy() if not round_smoke_expires.empty else round_smoke_expires.copy()
        self.round_flash_detonates = round_flash_detonates.sort_values(["tick"]).copy() if not round_flash_detonates.empty else round_flash_detonates.copy()
        self.round_he_detonates = round_he_detonates.sort_values(["tick"]).copy() if not round_he_detonates.empty else round_he_detonates.copy()
        self.round_inferno_starts = round_inferno_starts.sort_values(["tick"]).copy() if not round_inferno_starts.empty else round_inferno_starts.copy()
        self.round_grenades = round_grenades.sort_values(["grenade_entity_id", "tick"]).copy() if not round_grenades.empty else round_grenades.copy()
        self.flash_effect_ticks = int(flash_effect_ticks)
        self.he_effect_ticks = int(he_effect_ticks)
        self.inferno_duration_ticks = int(inferno_duration_ticks)
        self.inferno_ct_radius_world = float(inferno_ct_radius_world)
        self.inferno_t_radius_world = float(inferno_t_radius_world)
        self.smoke_radius_world = float(smoke_radius_world)
        self.smoke_deploy_ticks = int(smoke_deploy_ticks)
        self.player_team_lookup = player_team_lookup
        self.smoke_windows = self._build_smoke_windows()
        self.smoke_start_tick_by_entity = self._build_smoke_start_tick_by_entity()
        self.flash_effects = self._build_flash_effects()
        self.flash_start_tick_by_entity = self._build_flash_start_tick_by_entity()
        self.he_effects = self._build_he_effects()
        self.inferno_effects = self._build_inferno_effects()
        self.grenade_trails = self._build_grenade_trails()
        self.smoke_holes_by_window = self._build_smoke_holes_by_window()

    def has_grenade_trails(self) -> bool:
        return bool(self.grenade_trails)

    # IMPORTANT: viewer should ask the utility timeline for active projectile
    # trail states instead of reopening grenade trajectory DataFrames itself.
    def active_grenade_trails_at(self, frame_tick: int, *, recent_window_ticks: int, smoke_deploy_ticks: int) -> list[ActiveGrenadeTrail]:
        active: list[ActiveGrenadeTrail] = []
        for trail in self.grenade_trails:
            if trail.should_hide_at(frame_tick, smoke_deploy_ticks):
                continue
            current_point = trail.point_at_tick(frame_tick)
            if current_point is None:
                continue
            recent_points = trail.recent_points_at(frame_tick, recent_window_ticks)
            if not recent_points:
                continue
            active.append(
                ActiveGrenadeTrail(
                    grenade_type=trail.grenade_type,
                    burn_icon_path=trail.burn_icon_path,
                    current_x=current_point.x,
                    current_y=current_point.y,
                    recent_points=tuple(recent_points),
                )
            )
        return active

    def has_smokes(self) -> bool:
        return bool(self.smoke_windows)

    def _build_smoke_windows(self) -> list[SmokeWindow]:
        if self.round_smoke_detonates.empty:
            return []
        windows: list[SmokeWindow] = []
        expires = self.round_smoke_expires.copy() if not self.round_smoke_expires.empty else pd.DataFrame()
        used_expire_indices: set[int] = set()
        for _, detonate in self.round_smoke_detonates.iterrows():
            start_tick = int(detonate["tick"])
            end_tick = start_tick + 1152
            entity_id_value = pd.to_numeric(detonate.get("entityid"), errors="coerce")
            entity_id = None if pd.isna(entity_id_value) else int(entity_id_value)
            matched_index: int | None = None
            if not expires.empty and entity_id is not None and "entityid" in expires.columns:
                entity_matches = expires[
                    (pd.to_numeric(expires["entityid"], errors="coerce") == entity_id)
                    & (pd.to_numeric(expires["tick"], errors="coerce") >= start_tick)
                ]
                for expire_index, expire_row in entity_matches.iterrows():
                    if expire_index in used_expire_indices:
                        continue
                    matched_index = expire_index
                    end_tick = int(expire_row["tick"])
                    break
            if matched_index is None and not expires.empty:
                generic_matches = expires[pd.to_numeric(expires["tick"], errors="coerce") >= start_tick]
                for expire_index, expire_row in generic_matches.iterrows():
                    if expire_index in used_expire_indices:
                        continue
                    matched_index = expire_index
                    end_tick = int(expire_row["tick"])
                    break
            if matched_index is not None:
                used_expire_indices.add(matched_index)
            windows.append(
                SmokeWindow(
                    start_tick=start_tick,
                    end_tick=end_tick,
                    x=float(detonate["x"]),
                    y=float(detonate["y"]),
                    entity_id=entity_id,
                )
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

    def active_smokes_at(self, frame_tick: int) -> list[SmokeWindow]:
        return [
            smoke
            for smoke in self.smoke_windows
            if smoke.start_tick <= frame_tick <= smoke.end_tick
        ]

    def active_smoke_windows_at(self, frame_tick: int) -> list[tuple[int, SmokeWindow]]:
        return [
            (index, smoke)
            for index, smoke in enumerate(self.smoke_windows)
            if smoke.start_tick <= frame_tick <= smoke.end_tick
        ]

    def _smoke_start_tick_for_entity(self, entity_id: int) -> int | None:
        return self.smoke_start_tick_by_entity.get(entity_id)

    def smoke_holes_for_window(self, window_index: int) -> list[SmokeHole]:
        return self.smoke_holes_by_window.get(window_index, [])

    def _build_flash_effects(self) -> list[FlashEffect]:
        if self.round_flash_detonates.empty:
            return []
        required = {"tick", "x", "y"}
        if not required.issubset(self.round_flash_detonates.columns):
            return []
        effects: list[FlashEffect] = []
        for _, detonate in self.round_flash_detonates.iterrows():
            if pd.isna(detonate.get("x")) or pd.isna(detonate.get("y")):
                continue
            entity_id = pd.to_numeric(detonate.get("entityid"), errors="coerce")
            effects.append(
                FlashEffect(
                    entity_id=-1 if pd.isna(entity_id) else int(entity_id),
                    start_tick=int(detonate["tick"]),
                    end_tick=int(detonate["tick"]) + self.flash_effect_ticks,
                    x=float(detonate["x"]),
                    y=float(detonate["y"]),
                )
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

    def active_flashes_at(self, frame_tick: int) -> list[FlashEffect]:
        return [
            effect
            for effect in self.flash_effects
            if effect.start_tick <= frame_tick <= effect.end_tick
        ]

    def has_flashes(self) -> bool:
        return bool(self.flash_effects)

    def _flash_start_tick_for_entity(self, entity_id: int) -> int | None:
        return self.flash_start_tick_by_entity.get(entity_id)

    def _build_he_effects(self) -> list[HeEffect]:
        if self.round_he_detonates.empty:
            return []
        required = {"tick", "x", "y"}
        if not required.issubset(self.round_he_detonates.columns):
            return []
        effects: list[HeEffect] = []
        for _, detonate in self.round_he_detonates.iterrows():
            if pd.isna(detonate.get("x")) or pd.isna(detonate.get("y")):
                continue
            entity_id = pd.to_numeric(detonate.get("entityid"), errors="coerce")
            effects.append(
                HeEffect(
                    entity_id=-1 if pd.isna(entity_id) else int(entity_id),
                    start_tick=int(detonate["tick"]),
                    end_tick=int(detonate["tick"]) + self.he_effect_ticks,
                    x=float(detonate["x"]),
                    y=float(detonate["y"]),
                )
            )
        return effects

    def active_he_bursts_at(self, frame_tick: int) -> list[HeEffect]:
        return [
            effect
            for effect in self.he_effects
            if effect.start_tick <= frame_tick <= effect.end_tick
        ]

    def has_he_effects(self) -> bool:
        return bool(self.he_effects)

    def _he_effect_for_entity(self, entity_id: int) -> HeEffect | None:
        for effect in self.he_effects:
            if effect.entity_id == entity_id:
                return effect
        return None

    def _smoke_extinguish_tick_for_point(self, x: float, y: float, inferno_start_tick: int, inferno_end_tick: int) -> int | None:
        if not self.smoke_windows:
            return None
        for smoke in self.smoke_windows:
            smoke_start_tick = int(smoke.start_tick) + self.smoke_deploy_ticks
            smoke_end_tick = int(smoke.end_tick)
            if smoke_end_tick < inferno_start_tick or smoke_start_tick > inferno_end_tick:
                continue
            smoke_x = float(smoke.x)
            smoke_y = float(smoke.y)
            if (smoke_x - x) ** 2 + (smoke_y - y) ** 2 <= self.smoke_radius_world ** 2:
                return max(inferno_start_tick, smoke_start_tick)
        return None

    def _build_inferno_effects(self) -> list[InfernoEffect]:
        if self.round_inferno_starts.empty:
            return []
        effects: list[InfernoEffect] = []
        for _, row in self.round_inferno_starts.iterrows():
            if pd.isna(row.get("x")) or pd.isna(row.get("y")):
                continue
            player_name = str(row.get("user_name", ""))
            steamid_value = row.get("user_steamid")
            steamid = None if pd.isna(steamid_value) else str(steamid_value)
            start_tick = int(row["tick"])
            team_num = self.player_team_lookup(player_name, steamid, start_tick)
            full_radius_world = self.inferno_ct_radius_world if team_num == 3 else self.inferno_t_radius_world
            entity_id = pd.to_numeric(row.get("entityid"), errors="coerce")
            normalized_entity_id = -1 if pd.isna(entity_id) else int(entity_id)
            seed = normalized_entity_id if normalized_entity_id >= 0 else start_tick
            natural_end_tick = start_tick + self.inferno_duration_ticks
            extinguish_tick = self._smoke_extinguish_tick_for_point(
                float(row["x"]),
                float(row["y"]),
                start_tick,
                natural_end_tick,
            )
            if extinguish_tick is not None:
                end_tick = min(natural_end_tick, extinguish_tick)
                tiles: list[InfernoTile] = []
            else:
                end_tick = natural_end_tick
                tiles = self._build_inferno_tiles(seed, full_radius_world)
                updated_tiles: list[InfernoTile] = []
                for tile in tiles:
                    tile_x = float(row["x"]) + float(tile.offset_x)
                    tile_y = float(row["y"]) + float(tile.offset_y)
                    tile_extinguish_tick = self._smoke_extinguish_tick_for_point(tile_x, tile_y, start_tick, end_tick)
                    updated_tiles.append(
                        InfernoTile(
                            layer=tile.layer,
                            offset_x=tile.offset_x,
                            offset_y=tile.offset_y,
                            scale=tile.scale,
                            phase=tile.phase,
                            extinguish_tick=tile_extinguish_tick,
                        )
                    )
                tiles = updated_tiles
            effects.append(
                InfernoEffect(
                    entity_id=normalized_entity_id,
                    start_tick=start_tick,
                    end_tick=end_tick,
                    x=float(row["x"]),
                    y=float(row["y"]),
                    team_num=team_num,
                    full_radius_world=full_radius_world,
                    extinguish_tick=extinguish_tick,
                    tiles=tiles,
                )
            )
        return effects

    def _build_inferno_tiles(self, seed: int, full_radius_world: float) -> list[InfernoTile]:
        rng = random.Random(seed)
        tiles: list[InfernoTile] = []
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
                    InfernoTile(
                        layer=layer_name,
                        offset_x=offset_x,
                        offset_y=offset_y,
                        scale=rng.uniform(min_scale, max_scale),
                        phase=rng.randrange(5),
                    )
                )
        return tiles

    def active_infernos_at(self, frame_tick: int) -> list[InfernoEffect]:
        return [
            effect
            for effect in self.inferno_effects
            if effect.start_tick <= frame_tick <= effect.end_tick
            and (effect.extinguish_tick is None or frame_tick < effect.extinguish_tick)
        ]

    def has_infernos(self) -> bool:
        return bool(self.inferno_effects)

    def _build_smoke_holes_by_window(self) -> dict[int, list[SmokeHole]]:
        if not self.smoke_windows or not self.he_effects:
            return {}
        smoke_radius = self.smoke_radius_world
        he_radius = 384.0
        holes_by_window: dict[int, list[SmokeHole]] = {}
        for index, smoke in enumerate(self.smoke_windows):
            smoke_start_tick = int(smoke.start_tick)
            smoke_end_tick = int(smoke.end_tick)
            smoke_x = float(smoke.x)
            smoke_y = float(smoke.y)
            for effect in self.he_effects:
                effect_tick = int(effect.start_tick)
                if effect_tick < smoke_start_tick or effect_tick > smoke_end_tick:
                    continue
                dx = float(effect.x) - smoke_x
                dy = float(effect.y) - smoke_y
                if dx * dx + dy * dy > (smoke_radius + he_radius) ** 2:
                    continue
                holes_by_window.setdefault(index, []).append(
                    SmokeHole(start_tick=effect_tick, x=float(effect.x), y=float(effect.y))
                )
        return holes_by_window

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

    def _build_grenade_trails(self) -> list[GrenadeTrail]:
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
        trails: list[GrenadeTrail] = []
        for _, group in work.groupby(["grenade_entity_id", "steamid", "name"], sort=False):
            group = group.sort_values("tick").copy()
            tick_diff = group["tick"].diff().fillna(1)
            segment_id = (tick_diff > 2).cumsum()
            longest_segment = group.groupby(segment_id, sort=False).size().idxmax()
            segment = group[segment_id == longest_segment].copy()
            current_row = segment.iloc[-1]
            burn_icon_path: str | None = None
            did_burn = False
            grenade_type = str(current_row["grenade_type"])
            entity_id = int(current_row["grenade_entity_id"])
            smoke_start_tick: int | None = None
            flash_start_tick: int | None = None
            he_burst_start_tick: int | None = None
            if grenade_type == "CMolotovProjectile":
                player_name = str(current_row.get("name", ""))
                steamid_value = current_row.get("steamid")
                steamid = None if pd.isna(steamid_value) else str(steamid_value)
                inferno_start = self._match_inferno_start(player_name, steamid, int(current_row["tick"]))
                team_tick = int(inferno_start["tick"]) if inferno_start is not None else int(current_row["tick"])
                team_num = self.player_team_lookup(player_name, steamid, team_tick)
                burn_icon_path = "icons/equipment/incgrenade.png" if team_num == 3 else "icons/equipment/firebomb.png"
                did_burn = inferno_start is not None
            elif grenade_type == "CSmokeGrenadeProjectile":
                smoke_start_tick = self._smoke_start_tick_for_entity(entity_id)
            elif grenade_type == "CFlashbangProjectile":
                flash_start_tick = self._flash_start_tick_for_entity(entity_id)
            elif grenade_type == "CHEGrenadeProjectile":
                he_effect = self._he_effect_for_entity(entity_id)
                he_burst_start_tick = None if he_effect is None else int(he_effect.start_tick)
            trails.append(
                GrenadeTrail(
                    points=tuple(
                        GrenadeTrailPoint(
                            tick=int(row["tick"]),
                            x=float(row["x"]),
                            y=float(row["y"]),
                            z=float(row["z"]),
                        )
                        for _, row in segment.iterrows()
                    ),
                    grenade_type=grenade_type,
                    burn_icon_path=burn_icon_path,
                    did_burn=did_burn,
                    smoke_start_tick=smoke_start_tick,
                    flash_start_tick=flash_start_tick,
                    he_burst_start_tick=he_burst_start_tick,
                )
            )
        return trails
