from __future__ import annotations

import math

import pandas as pd


def _offset_world_point(x: float, y: float, yaw: float, distance: float) -> tuple[float, float]:
    radians = math.radians(-yaw)
    return (x + math.cos(radians) * distance, y + math.sin(radians) * distance)


class BlindEffectTracker:
    def __init__(
        self,
        round_blinds: pd.DataFrame,
        tickrate: float,
        max_reference_seconds: float = 2.5,
    ) -> None:
        self.round_blinds = round_blinds.sort_values(["tick"]).copy() if not round_blinds.empty else round_blinds.copy()
        self.tickrate = tickrate if tickrate > 0 else 64.0
        self.max_reference_seconds = max_reference_seconds
        self.lookup = self._build_lookup()

    def _build_lookup(self) -> dict[str, list[dict[str, float | int]]]:
        if self.round_blinds.empty or "user_name" not in self.round_blinds.columns or "blind_duration" not in self.round_blinds.columns:
            return {}
        lookup: dict[str, list[dict[str, float | int]]] = {}
        for _, row in self.round_blinds.iterrows():
            user_name = row.get("user_name")
            duration_seconds = pd.to_numeric(row.get("blind_duration"), errors="coerce")
            if pd.isna(user_name) or pd.isna(duration_seconds) or float(duration_seconds) <= 0:
                continue
            start_tick = int(row["tick"])
            duration_ticks = max(1, int(round(float(duration_seconds) * self.tickrate)))
            severity = max(0.25, min(1.0, float(duration_seconds) / self.max_reference_seconds))
            lookup.setdefault(str(user_name), []).append(
                {
                    "start_tick": start_tick,
                    "end_tick": start_tick + duration_ticks,
                    "duration_seconds": float(duration_seconds),
                    "severity": severity,
                }
            )
        return lookup

    def strength_at(self, player: str, frame_tick: int) -> float:
        events = self.lookup.get(player, [])
        if not events:
            return 0.0
        strength = 0.0
        for event in events:
            start_tick = int(event["start_tick"])
            end_tick = int(event["end_tick"])
            if frame_tick < start_tick or frame_tick > end_tick:
                continue
            duration_ticks = max(1, end_tick - start_tick)
            progress = (frame_tick - start_tick) / duration_ticks
            severity = float(event["severity"])
            event_strength = severity * ((1.0 - progress) ** 1.6)
            if event_strength > strength:
                strength = event_strength
        return max(0.0, min(1.0, strength))


class BombStateTracker:
    def __init__(
        self,
        round_ticks: pd.DataFrame,
        round_bomb_pickups: pd.DataFrame,
        round_bomb_drops: pd.DataFrame,
        round_bomb_plants: pd.DataFrame,
        round_bomb_defuses: pd.DataFrame,
        round_bomb_explodes: pd.DataFrame,
        death_tick_lookup: dict[str, int],
        frame_ticks: list[int],
        throw_offset_world: float = 28.0,
        prepickup_ticks: int = 96,
        prepickup_distance_world: float = 28.0,
    ) -> None:
        self.round_ticks = round_ticks
        self.round_bomb_pickups = round_bomb_pickups.sort_values(["tick"]).copy() if not round_bomb_pickups.empty else round_bomb_pickups.copy()
        self.round_bomb_drops = round_bomb_drops.sort_values(["tick"]).copy() if not round_bomb_drops.empty else round_bomb_drops.copy()
        self.round_bomb_plants = round_bomb_plants.sort_values(["tick"]).copy() if not round_bomb_plants.empty else round_bomb_plants.copy()
        self.round_bomb_defuses = round_bomb_defuses.sort_values(["tick"]).copy() if not round_bomb_defuses.empty else round_bomb_defuses.copy()
        self.round_bomb_explodes = round_bomb_explodes.sort_values(["tick"]).copy() if not round_bomb_explodes.empty else round_bomb_explodes.copy()
        self.death_tick_lookup = death_tick_lookup
        self.frame_ticks = frame_ticks
        self.throw_offset_world = throw_offset_world
        self.prepickup_ticks = prepickup_ticks
        self.prepickup_distance_world = prepickup_distance_world
        self.segments = self._build_segments()

    def _build_segments(self) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        for _, row in self.round_bomb_pickups.iterrows():
            events.append({"kind": "pickup", "tick": int(row["tick"]), "row": row})
        for _, row in self.round_bomb_drops.iterrows():
            events.append({"kind": "drop", "tick": int(row["tick"]), "row": row})
        for _, row in self.round_bomb_plants.iterrows():
            events.append({"kind": "plant", "tick": int(row["tick"]), "row": row})
        for _, row in self.round_bomb_defuses.iterrows():
            events.append({"kind": "defuse", "tick": int(row["tick"]), "row": row})
        for _, row in self.round_bomb_explodes.iterrows():
            events.append({"kind": "clear", "tick": int(row["tick"]), "row": row})
        if not events:
            return []

        priority = {"pickup": 0, "drop": 1, "plant": 2, "defuse": 3, "clear": 4}
        events.sort(key=lambda event: (int(event["tick"]), priority[str(event["kind"])]))
        round_end_tick = int(self.frame_ticks[-1]) if self.frame_ticks else 0
        segments: list[dict[str, object]] = []
        current_state: dict[str, object] | None = None
        current_start_tick: int | None = None

        def append_segment(end_tick: int) -> None:
            nonlocal current_state, current_start_tick
            if current_state is None or current_start_tick is None or end_tick < current_start_tick:
                return
            segments.append(
                {
                    "start_tick": current_start_tick,
                    "end_tick": end_tick,
                    **current_state,
                }
            )

        for event in events:
            tick = int(event["tick"])
            append_segment(tick - 1)
            current_start_tick = tick
            row = event["row"]
            kind = str(event["kind"])
            if kind == "pickup":
                current_state = {
                    "state": "carried",
                    "player": str(row.get("user_name", "")),
                }
            elif kind == "drop":
                x = float(row["user_X"])
                y = float(row["user_Y"])
                if not self._is_death_drop(row):
                    yaw = pd.to_numeric(row.get("user_yaw"), errors="coerce")
                    if not pd.isna(yaw):
                        x, y = _offset_world_point(x, y, float(yaw), self.throw_offset_world)
                current_state = {
                    "state": "dropped",
                    "x": x,
                    "y": y,
                }
            elif kind == "plant":
                current_state = {
                    "state": "planted",
                    "x": float(row["user_X"]),
                    "y": float(row["user_Y"]),
                }
            elif kind == "defuse":
                current_state = {
                    "state": "defused",
                    "x": float(row["user_X"]),
                    "y": float(row["user_Y"]),
                }
            else:
                current_state = None
        append_segment(round_end_tick)
        self._annotate_prepickup_segments(segments)
        return segments

    def _annotate_prepickup_segments(self, segments: list[dict[str, object]]) -> None:
        if not segments or self.round_bomb_pickups.empty:
            return
        pickup_rows = self.round_bomb_pickups.sort_values("tick")
        for segment in segments:
            if str(segment.get("state")) != "dropped":
                continue
            start_tick = int(segment["start_tick"])
            end_tick = int(segment["end_tick"])
            future_pickups = pickup_rows[
                (pickup_rows["tick"] >= start_tick)
                & (pickup_rows["tick"] <= end_tick + 1)
            ]
            if future_pickups.empty:
                continue
            pickup = future_pickups.iloc[0]
            pickup_tick = int(pickup["tick"])
            player = str(pickup.get("user_name", ""))
            if not player:
                continue
            window_start = max(start_tick, pickup_tick - self.prepickup_ticks)
            prepickup_start_tick: int | None = None
            player_rows = self.round_ticks[
                (self.round_ticks["name"] == player)
                & (self.round_ticks["tick"] >= window_start)
                & (self.round_ticks["tick"] <= pickup_tick)
            ].sort_values("tick")
            if player_rows.empty:
                continue
            drop_x = float(segment["x"])
            drop_y = float(segment["y"])
            max_dist_sq = self.prepickup_distance_world ** 2
            for _, row in player_rows.iterrows():
                dx = float(row["X"]) - drop_x
                dy = float(row["Y"]) - drop_y
                if dx * dx + dy * dy <= max_dist_sq:
                    prepickup_start_tick = int(row["tick"])
                    break
            if prepickup_start_tick is None:
                continue
            segment["prepickup_player"] = player
            segment["prepickup_start_tick"] = prepickup_start_tick
            segment["prepickup_end_tick"] = pickup_tick

    def _is_death_drop(self, drop_row: pd.Series) -> bool:
        player = str(drop_row.get("user_name", ""))
        if not player:
            return False
        drop_tick = int(drop_row["tick"])
        death_tick = self.death_tick_lookup.get(player)
        return death_tick is not None and abs(death_tick - drop_tick) <= 2

    def state_at(self, frame_tick: int) -> dict[str, object] | None:
        for segment in self.segments:
            if int(segment["start_tick"]) <= frame_tick <= int(segment["end_tick"]):
                return segment
        return None

    def visual_state_at(self, frame_tick: int) -> dict[str, object] | None:
        state = self.state_at(frame_tick)
        if state is None or str(state.get("state")) != "dropped":
            return state
        prepickup_start_tick = state.get("prepickup_start_tick")
        prepickup_end_tick = state.get("prepickup_end_tick")
        prepickup_player = state.get("prepickup_player")
        if prepickup_start_tick is None or prepickup_end_tick is None or not prepickup_player:
            return state
        if int(prepickup_start_tick) <= frame_tick <= int(prepickup_end_tick):
            return {
                "state": "carried",
                "player": str(prepickup_player),
                "visual_only": True,
                "start_tick": state.get("start_tick", frame_tick),
                "end_tick": state.get("end_tick", frame_tick),
            }
        return state
