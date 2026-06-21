from __future__ import annotations

import pandas as pd


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
