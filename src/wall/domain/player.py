from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Callable

import numpy as np
import pandas as pd

from wall.domain.visibility_profile import VisibilityProfile
from wall.profile import profile_log


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "<na>"}:
        return ""
    return text


def _normalize_player_key(steamid: str | None, name: str) -> str:
    normalized_steamid = _clean_text(steamid)
    if normalized_steamid:
        return normalized_steamid
    return f"name:{name}"


def _coerce_optional_int(value: object) -> int | None:
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return None
    return int(numeric)


def _coerce_float(value: object, default: float = 0.0) -> float:
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return default
    return float(numeric)


def _coerce_bool(value: object) -> bool:
    numeric = pd.to_numeric(value, errors="coerce")
    if not pd.isna(numeric):
        return bool(int(numeric))
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "t", "yes", "y"}:
            return True
        if lowered in {"false", "f", "no", "n", ""}:
            return False
    return bool(value)


@dataclass(frozen=True, slots=True)
class PlayerFrame:
    name: str
    steamid: str
    active_weapon_name: str
    has_defuser: bool
    tick: int
    x: float
    y: float
    z: float
    yaw: float
    pitch: float
    team_num: int | None
    health: int | None
    is_alive: bool
    is_ducking: bool
    is_airborne: bool
    velocity_x: float
    velocity_y: float
    velocity_z: float


@dataclass(frozen=True, slots=True)
class PlayerOverlayState:
    damage_flash_fade: float
    blind_strength: float


class PlayerTimeline:
    def __init__(
        self,
        steamid: str,
        frames: pd.DataFrame,
        death_tick: int | None = None,
        death_events: list[pd.Series] | None = None,
        fire_events: list[pd.Series] | None = None,
        hurt_events: list[pd.Series] | None = None,
        blind_events: list[dict[str, float | int]] | None = None,
    ) -> None:
        self.steamid = steamid
        self.frames = frames.sort_values("tick").reset_index(drop=True).copy()
        self.ticks = self.frames["tick"].to_numpy(dtype=np.int64) if not self.frames.empty else np.array([], dtype=np.int64)
        self.death_tick = death_tick
        self.display_name = str(self.frames["name"].iloc[-1]) if not self.frames.empty else ""
        self.death_events = sorted(death_events or [], key=lambda row: int(row["tick"]))
        self.fire_events = sorted(fire_events or [], key=lambda row: int(row["tick"]))
        self.hurt_events = sorted(hurt_events or [], key=lambda row: int(row["tick"]))
        self.blind_events = sorted(blind_events or [], key=lambda event: int(event["start_tick"]))
        self.damage_flashes = self._build_damage_flashes()

    @property
    def names(self) -> list[str]:
        if self.frames.empty or "name" not in self.frames.columns:
            return []
        return [str(name) for name in self.frames["name"].dropna().astype(str).drop_duplicates().tolist()]

    def frame_at(self, tick: int) -> PlayerFrame | None:
        if self.frames.empty or self.ticks.size == 0:
            return None
        idx = int(self.ticks.searchsorted(tick, side="right") - 1)
        if idx < 0:
            return None
        row = self.frames.iloc[idx]
        return self._frame_from_row(row, tick)

    def frames_between(self, start_tick: int, end_tick: int) -> pd.DataFrame:
        if self.frames.empty or self.ticks.size == 0 or end_tick < start_tick:
            return self.frames.iloc[0:0].copy()
        start_idx = int(self.ticks.searchsorted(start_tick, side="left"))
        end_idx = int(self.ticks.searchsorted(end_tick, side="right"))
        if end_idx <= start_idx:
            return self.frames.iloc[0:0].copy()
        return self.frames.iloc[start_idx:end_idx].copy()

    def position_at(self, tick: int) -> tuple[float, float, float] | None:
        frame = self.frame_at(tick)
        if frame is None:
            return None
        return (frame.x, frame.y, frame.z)

    def velocity_at(self, tick: int) -> tuple[float, float, float] | None:
        frame = self.frame_at(tick)
        if frame is None:
            return None
        return (frame.velocity_x, frame.velocity_y, frame.velocity_z)

    def speed_xy_at(self, tick: int) -> float | None:
        velocity = self.velocity_at(tick)
        if velocity is None:
            return None
        vx, vy, _vz = velocity
        return math.hypot(vx, vy)

    def facing_at(self, tick: int) -> tuple[float, float] | None:
        frame = self.frame_at(tick)
        if frame is None:
            return None
        return (frame.yaw, frame.pitch)

    def team_at(self, tick: int) -> int | None:
        frame = self.frame_at(tick)
        if frame is None:
            return None
        return frame.team_num

    def health_at(self, tick: int) -> int | None:
        frame = self.frame_at(tick)
        if frame is None:
            return None
        return frame.health

    def is_alive_at(self, tick: int) -> bool:
        if self.death_tick is not None and tick >= self.death_tick:
            return False
        frame = self.frame_at(tick)
        return frame is not None and frame.health is not None and frame.health > 0

    def latest_damage_flash(self, tick: int) -> tuple[int, float] | None:
        latest: tuple[int, float] | None = None
        for damage_tick, damage in self.damage_flashes:
            if damage_tick > tick:
                break
            latest = (damage_tick, damage)
        return latest

    def overlay_state_at(self, tick: int, *, damage_flash_duration_ticks: int) -> PlayerOverlayState:
        damage_flash_fade = 0.0
        flash = self.latest_damage_flash(tick)
        if flash is not None:
            damage_tick, _damage = flash
            elapsed = tick - damage_tick
            if 0 <= elapsed <= damage_flash_duration_ticks:
                damage_flash_fade = max(0.0, min(1.0, 1.0 - (elapsed / max(1, damage_flash_duration_ticks))))
        return PlayerOverlayState(
            damage_flash_fade=damage_flash_fade,
            blind_strength=self.blind_strength_at(tick),
        )

    def blind_strength_at(self, tick: int) -> float:
        strength = 0.0
        for event in self.blind_events:
            start_tick = int(event["start_tick"])
            end_tick = int(event["end_tick"])
            if tick < start_tick or tick > end_tick:
                continue
            duration_ticks = max(1, end_tick - start_tick)
            progress = (tick - start_tick) / duration_ticks
            severity = float(event["severity"])
            event_strength = severity * ((1.0 - progress) ** 1.6)
            if event_strength > strength:
                strength = event_strength
        return max(0.0, min(1.0, strength))

    def latest_fire_event(self, tick: int) -> pd.Series | None:
        latest: pd.Series | None = None
        for event in self.fire_events:
            if int(event["tick"]) > tick:
                break
            latest = event
        return latest

    def hurt_events_after(self, start_tick: int, max_tick: int | None = None) -> list[pd.Series]:
        matches: list[pd.Series] = []
        for event in self.hurt_events:
            event_tick = int(event["tick"])
            if event_tick < start_tick:
                continue
            if max_tick is not None and event_tick > max_tick:
                break
            matches.append(event)
        return matches

    def resolve_hit_position_for_fire_event(
        self,
        fire_event: pd.Series,
        *,
        max_tick: int,
        victim_position_lookup: Callable[[pd.Series], tuple[float, float] | None],
    ) -> tuple[float, float] | None:
        fire_tick = int(fire_event["tick"])
        hurts = self.hurt_events_after(fire_tick, max_tick)
        for hurt in hurts:
            hit_xy = victim_position_lookup(hurt)
            if hit_xy is not None:
                return hit_xy
        return None

    def death_event_at(self, tick: int) -> pd.Series | None:
        shown: pd.Series | None = None
        for event in self.death_events:
            if int(event["tick"]) > tick:
                break
            shown = event
        return shown

    def death_position_at(self, tick: int) -> tuple[float, float] | None:
        event = self.death_event_at(tick)
        if event is None:
            return None
        return (_coerce_float(event.get("user_X")), _coerce_float(event.get("user_Y")))

    def _build_damage_flashes(self) -> list[tuple[int, float]]:
        if self.frames.empty or "health" not in self.frames.columns:
            return []
        group = self.frames[["tick", "health"]].copy()
        group["health"] = pd.to_numeric(group["health"], errors="coerce")
        group["prev_health"] = group["health"].shift(1)
        drops = group[
            group["health"].notna()
            & group["prev_health"].notna()
            & (group["health"] < group["prev_health"])
        ]
        if drops.empty:
            return []
        return [
            (int(row["tick"]), float(row["prev_health"] - row["health"]))
            for _, row in drops.iterrows()
        ]

    def _frame_from_row(self, row: pd.Series, tick: int) -> PlayerFrame:
        started_at = time.perf_counter()
        health = _coerce_optional_int(row.get("health"))
        frame = PlayerFrame(
            name=str(row.get("name", "") or ""),
            steamid=_clean_text(row.get("steamid", "")) or self.steamid,
            active_weapon_name=_clean_text(row.get("active_weapon_name", "")),
            has_defuser=_coerce_bool(row.get("has_defuser")),
            tick=int(tick),
            x=_coerce_float(row.get("X")),
            y=_coerce_float(row.get("Y")),
            z=_coerce_float(row.get("Z")),
            yaw=_coerce_float(row.get("yaw")),
            pitch=_coerce_float(row.get("pitch")),
            team_num=_coerce_optional_int(row.get("team_num")),
            health=health,
            is_alive=(self.death_tick is None or tick < self.death_tick) and health is not None and health > 0,
            is_ducking=_coerce_bool(row.get("ducking")),
            is_airborne=_coerce_bool(row.get("is_airborne")),
            velocity_x=_coerce_float(row.get("velocity_X")),
            velocity_y=_coerce_float(row.get("velocity_Y")),
            velocity_z=_coerce_float(row.get("velocity_Z")),
        )
        _ = started_at
        return frame


class RoundPlayers:
    def __init__(
        self,
        players_by_steamid: dict[str, PlayerTimeline],
        players_by_name: dict[str, PlayerTimeline],
        ordered_steamids: list[str],
        frames_by_tick: dict[int, dict[str, PlayerFrame]] | None = None,
        alive_players_by_tick: dict[int, tuple[PlayerFrame, ...]] | None = None,
    ) -> None:
        self.players_by_steamid = players_by_steamid
        self.players_by_name = players_by_name
        self.ordered_steamids = ordered_steamids
        self.ordered_names = [
            players_by_steamid[steamid].display_name
            for steamid in ordered_steamids
            if steamid in players_by_steamid
        ]
        self.frames_by_tick = frames_by_tick or {}
        self.alive_players_by_tick = alive_players_by_tick or {}

    @classmethod
    def from_round_ticks(
        cls,
        round_ticks: pd.DataFrame,
        round_deaths: pd.DataFrame | None = None,
        round_fires: pd.DataFrame | None = None,
        round_hurts: pd.DataFrame | None = None,
        round_blinds: pd.DataFrame | None = None,
        tickrate: float = 64.0,
        blind_reference_seconds: float = 2.5,
        visibility_profile: VisibilityProfile | None = None,
    ) -> RoundPlayers:
        if round_ticks.empty:
            return cls({}, {}, [])
        total_started_at = time.perf_counter()
        profile_log("round_players.input", started_at=total_started_at, df=round_ticks, note="from_round_ticks")
        tick_name_view = round_ticks.loc[:, [column for column in ("tick", "name") if column in round_ticks.columns]]
        if pd.MultiIndex.from_frame(tick_name_view).is_monotonic_increasing:
            work = round_ticks
        else:
            work = round_ticks.sort_values(["tick", "name"]).copy()
        profile_log("round_players.grouping.start", df=work)
        death_tick_by_key: dict[str, int] = {}
        death_events_by_key: dict[str, list[pd.Series]] = {}
        fire_events_by_key: dict[str, list[pd.Series]] = {}
        hurt_events_by_key: dict[str, list[pd.Series]] = {}
        blind_events_by_key: dict[str, list[dict[str, float | int]]] = {}
        if round_deaths is not None and not round_deaths.empty and "tick" in round_deaths.columns:
            for _, row in round_deaths.sort_values("tick").iterrows():
                name = _clean_text(row.get("user_name", ""))
                steamid = _clean_text(row.get("user_steamid", ""))
                key = _normalize_player_key(steamid, name)
                death_tick_by_key.setdefault(key, int(row["tick"]))
                death_events_by_key.setdefault(key, []).append(row)
        if round_fires is not None and not round_fires.empty and "tick" in round_fires.columns:
            for _, row in round_fires.sort_values("tick").iterrows():
                key = _normalize_player_key(
                    _clean_text(row.get("user_steamid", "")),
                    _clean_text(row.get("user_name", "")),
                )
                fire_events_by_key.setdefault(key, []).append(row)
        if round_hurts is not None and not round_hurts.empty and "tick" in round_hurts.columns:
            for _, row in round_hurts.sort_values("tick").iterrows():
                attacker_name = _clean_text(row.get("attacker_name", ""))
                if not attacker_name:
                    continue
                key = _normalize_player_key(
                    _clean_text(row.get("attacker_steamid", "")),
                    attacker_name,
                )
                hurt_events_by_key.setdefault(key, []).append(row)
        if round_blinds is not None and not round_blinds.empty and "tick" in round_blinds.columns and "blind_duration" in round_blinds.columns:
            effective_tickrate = tickrate if tickrate > 0 else 64.0
            for _, row in round_blinds.sort_values("tick").iterrows():
                user_name = _clean_text(row.get("user_name", ""))
                duration_seconds = pd.to_numeric(row.get("blind_duration"), errors="coerce")
                if not user_name or pd.isna(duration_seconds) or float(duration_seconds) <= 0:
                    continue
                key = _normalize_player_key(
                    _clean_text(row.get("user_steamid", "")),
                    user_name,
                )
                start_tick = int(row["tick"])
                duration_ticks = max(1, int(round(float(duration_seconds) * effective_tickrate)))
                severity = max(0.25, min(1.0, float(duration_seconds) / blind_reference_seconds))
                blind_events_by_key.setdefault(key, []).append(
                    {
                        "start_tick": start_tick,
                        "end_tick": start_tick + duration_ticks,
                        "duration_seconds": float(duration_seconds),
                        "severity": severity,
                    }
                )
        profile_log("round_players.grouping.end", df=work, note=f"death_keys={len(death_events_by_key)} fire_keys={len(fire_events_by_key)} hurt_keys={len(hurt_events_by_key)} blind_keys={len(blind_events_by_key)}")
        players_by_steamid: dict[str, PlayerTimeline] = {}
        players_by_name: dict[str, PlayerTimeline] = {}
        ordered_steamids: list[str] = []
        timeline_started_at = time.perf_counter()
        profile_log("round_players.timeline_build.start", df=work)
        for _, group in work.groupby(["steamid", "name"], sort=False, dropna=False):
            name = _clean_text(group["name"].iloc[-1] if "name" in group.columns else "")
            steamid_value = _clean_text(group["steamid"].iloc[-1] if "steamid" in group.columns else "")
            key = _normalize_player_key(steamid_value, name)
            if key in players_by_steamid:
                # Merge name-changed segments for the same identity.
                merged = pd.concat([players_by_steamid[key].frames, group], ignore_index=True)
                death_tick = death_tick_by_key.get(key)
                timeline = PlayerTimeline(
                    key,
                    merged,
                    death_tick=death_tick,
                    death_events=death_events_by_key.get(key),
                    fire_events=fire_events_by_key.get(key),
                    hurt_events=hurt_events_by_key.get(key),
                    blind_events=blind_events_by_key.get(key),
                )
                players_by_steamid[key] = timeline
            else:
                death_tick = death_tick_by_key.get(key)
                timeline = PlayerTimeline(
                    key,
                    group,
                    death_tick=death_tick,
                    death_events=death_events_by_key.get(key),
                    fire_events=fire_events_by_key.get(key),
                    hurt_events=hurt_events_by_key.get(key),
                    blind_events=blind_events_by_key.get(key),
                )
                players_by_steamid[key] = timeline
                ordered_steamids.append(key)
            for candidate_name in timeline.names:
                players_by_name[candidate_name] = timeline
        profile_log("round_players.timeline_build.end", started_at=timeline_started_at, df=work, note=f"players={len(players_by_steamid)}")
        frames_by_tick: dict[int, dict[str, PlayerFrame]] = {}
        alive_players_by_tick: dict[int, tuple[PlayerFrame, ...]] = {}
        lookup_started_at = time.perf_counter()
        row_records = work.to_dict("records")
        if visibility_profile is not None:
            visibility_profile.player_timeline_lookup_seconds += time.perf_counter() - lookup_started_at
        profile_log("round_players.frames_by_tick.start", note=f"row_records={len(row_records)}")
        alive_cache_started_at = time.perf_counter()
        profile_log("round_players.alive_cache_build.start", note=f"row_records={len(row_records)}")
        active_tick: int | None = None
        tick_frames: dict[str, PlayerFrame] = {}
        tick_alive: list[PlayerFrame] = []
        weapon_state_started_at = time.perf_counter()
        for row in row_records:
            tick_value = int(row["tick"])
            if active_tick is None:
                active_tick = tick_value
            elif tick_value != active_tick:
                frames_by_tick[active_tick] = tick_frames
                alive_players_by_tick[active_tick] = tuple(tick_alive)
                tick_frames = {}
                tick_alive = []
                active_tick = tick_value

            extraction_started_at = time.perf_counter()
            name = _clean_text(row.get("name", ""))
            steamid_value = _clean_text(row.get("steamid", ""))
            key = _normalize_player_key(steamid_value, name)
            if visibility_profile is not None:
                visibility_profile.player_timeline_lookup_seconds += time.perf_counter() - extraction_started_at
            timeline = players_by_steamid.get(key)
            if timeline is None:
                continue

            coord_started_at = time.perf_counter()
            x = _coerce_float(row.get("X"))
            y = _coerce_float(row.get("Y"))
            z = _coerce_float(row.get("Z"))
            if visibility_profile is not None:
                visibility_profile.coordinate_extraction_seconds += time.perf_counter() - coord_started_at

            yaw_started_at = time.perf_counter()
            yaw = _coerce_float(row.get("yaw"))
            pitch = _coerce_float(row.get("pitch"))
            if visibility_profile is not None:
                visibility_profile.yaw_pitch_extraction_seconds += time.perf_counter() - yaw_started_at

            filter_started_at = time.perf_counter()
            health = _coerce_optional_int(row.get("health"))
            team_num = _coerce_optional_int(row.get("team_num"))
            is_alive = (timeline.death_tick is None or tick_value < timeline.death_tick) and health is not None and health > 0
            if visibility_profile is not None:
                visibility_profile.alive_team_filtering_seconds += time.perf_counter() - filter_started_at

            construct_started_at = time.perf_counter()
            frame = PlayerFrame(
                name=name,
                steamid=steamid_value or timeline.steamid,
                active_weapon_name=_clean_text(row.get("active_weapon_name", "")),
                has_defuser=_coerce_bool(row.get("has_defuser")),
                tick=tick_value,
                x=x,
                y=y,
                z=z,
                yaw=yaw,
                pitch=pitch,
                team_num=team_num,
                health=health,
                is_alive=is_alive,
                is_ducking=_coerce_bool(row.get("ducking")),
                is_airborne=_coerce_bool(row.get("is_airborne")),
                velocity_x=_coerce_float(row.get("velocity_X")),
                velocity_y=_coerce_float(row.get("velocity_Y")),
                velocity_z=_coerce_float(row.get("velocity_Z")),
            )
            if visibility_profile is not None:
                visibility_profile.frame_object_construction_seconds += time.perf_counter() - construct_started_at
            if not frame.name:
                continue
            tick_frames[frame.name] = frame
            if frame.is_alive:
                tick_alive.append(frame)
        profile_log("round_players.weapon_state_cache_build.end", started_at=weapon_state_started_at, note=f"ticks_seen={len(frames_by_tick) + (1 if active_tick is not None else 0)}")
        if active_tick is not None:
            frames_by_tick[active_tick] = tick_frames
            alive_players_by_tick[active_tick] = tuple(tick_alive)
        profile_log("round_players.frames_by_tick.end", started_at=lookup_started_at, note=f"frames_by_tick={len(frames_by_tick)}")
        profile_log("round_players.alive_cache_build.end", started_at=alive_cache_started_at, note=f"alive_ticks={len(alive_players_by_tick)}")
        profile_log("round_players.total.end", started_at=total_started_at, df=work, note=f"players={len(players_by_steamid)} frame_ticks={len(frames_by_tick)}")
        return cls(
            players_by_steamid,
            players_by_name,
            ordered_steamids,
            frames_by_tick=frames_by_tick,
            alive_players_by_tick=alive_players_by_tick,
        )

    def get_by_steamid(self, steamid: str | None) -> PlayerTimeline | None:
        if steamid is None:
            return None
        return self.players_by_steamid.get(steamid)

    def get_by_name(self, name: str | None) -> PlayerTimeline | None:
        if name is None:
            return None
        return self.players_by_name.get(name)

    def frame_at(self, *, steamid: str | None = None, name: str | None = None, tick: int) -> PlayerFrame | None:
        tick_value = int(tick)
        tick_frames = self.frames_by_tick.get(tick_value)
        if tick_frames is not None and name:
            cached = tick_frames.get(name)
            if cached is not None:
                return cached
        timeline = self.get_by_steamid(steamid) if steamid else None
        if timeline is None and name:
            timeline = self.get_by_name(name)
        if timeline is None:
            return None
        return timeline.frame_at(tick_value)

    def alive_players_at(self, tick: int) -> list[PlayerFrame]:
        tick_value = int(tick)
        cached = self.alive_players_by_tick.get(tick_value)
        if cached is not None:
            return list(cached)
        alive: list[PlayerFrame] = []
        for steamid in self.ordered_steamids:
            timeline = self.players_by_steamid.get(steamid)
            if timeline is None or not timeline.is_alive_at(tick_value):
                continue
            frame = timeline.frame_at(tick_value)
            if frame is not None:
                alive.append(frame)
        return alive
