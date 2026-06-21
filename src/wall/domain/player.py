from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd


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


@dataclass(frozen=True)
class PlayerFrame:
    name: str
    steamid: str
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
        health = _coerce_optional_int(row.get("health"))
        return PlayerFrame(
            name=str(row.get("name", "") or ""),
            steamid=_clean_text(row.get("steamid", "")) or self.steamid,
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


class RoundPlayers:
    def __init__(
        self,
        players_by_steamid: dict[str, PlayerTimeline],
        players_by_name: dict[str, PlayerTimeline],
        ordered_steamids: list[str],
    ) -> None:
        self.players_by_steamid = players_by_steamid
        self.players_by_name = players_by_name
        self.ordered_steamids = ordered_steamids
        self.ordered_names = [
            players_by_steamid[steamid].display_name
            for steamid in ordered_steamids
            if steamid in players_by_steamid
        ]

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
    ) -> RoundPlayers:
        if round_ticks.empty:
            return cls({}, {}, [])
        work = round_ticks.sort_values(["tick", "name"]).copy()
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
        players_by_steamid: dict[str, PlayerTimeline] = {}
        players_by_name: dict[str, PlayerTimeline] = {}
        ordered_steamids: list[str] = []
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
        return cls(players_by_steamid, players_by_name, ordered_steamids)

    def get_by_steamid(self, steamid: str | None) -> PlayerTimeline | None:
        if steamid is None:
            return None
        return self.players_by_steamid.get(steamid)

    def get_by_name(self, name: str | None) -> PlayerTimeline | None:
        if name is None:
            return None
        return self.players_by_name.get(name)

    def frame_at(self, *, steamid: str | None = None, name: str | None = None, tick: int) -> PlayerFrame | None:
        timeline = self.get_by_steamid(steamid) if steamid else None
        if timeline is None and name:
            timeline = self.get_by_name(name)
        if timeline is None:
            return None
        return timeline.frame_at(tick)

    def alive_players_at(self, tick: int) -> list[PlayerFrame]:
        alive: list[PlayerFrame] = []
        for steamid in self.ordered_steamids:
            timeline = self.players_by_steamid.get(steamid)
            if timeline is None or not timeline.is_alive_at(tick):
                continue
            frame = timeline.frame_at(tick)
            if frame is not None:
                alive.append(frame)
        return alive
