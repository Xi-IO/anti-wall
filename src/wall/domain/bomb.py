from __future__ import annotations

from dataclasses import dataclass
import math
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from wall.domain.player import RoundPlayers


def _offset_world_point(x: float, y: float, yaw: float, distance: float) -> tuple[float, float]:
    radians = math.radians(-yaw)
    return (x + math.cos(radians) * distance, y + math.sin(radians) * distance)


@dataclass(frozen=True)
class BombState:
    state: str
    start_tick: int
    end_tick: int
    x: float | None = None
    y: float | None = None
    player: str | None = None
    visual_only: bool = False
    prepickup_player: str | None = None
    prepickup_start_tick: int | None = None
    prepickup_end_tick: int | None = None


@dataclass(frozen=True)
class PlantAttempt:
    player: str
    start_tick: int
    end_tick: int
    status: str
    x: float
    y: float
    anchor_x: float
    anchor_y: float
    abort_fade_end_tick: int


@dataclass(frozen=True)
class DefuseAttempt:
    player: str
    start_tick: int
    end_tick: int
    natural_end_tick: int
    duration_ticks: int
    haskit: bool
    status: str


@dataclass(frozen=True)
class PlantAttemptVisual:
    center_x: float
    center_y: float
    progress: float
    fade: float
    start_angle: float
    end_angle: float
    status: str


@dataclass(frozen=True)
class DefuseAttemptVisual:
    progress: float
    alpha_scale: float
    shake: float
    status: str


@dataclass(frozen=True)
class BombRenderState:
    icon_state: str | None
    world_position: tuple[float, float] | None
    carrier: str | None
    planted_timer_progress: float | None
    defuse_visual: DefuseAttemptVisual | None
    plant_visual: PlantAttemptVisual | None


class BombTimeline:
    def __init__(
        self,
        round_bomb_pickups: pd.DataFrame,
        round_bomb_drops: pd.DataFrame,
        round_bomb_begin_plants: pd.DataFrame,
        round_bomb_plants: pd.DataFrame,
        round_bomb_defuses: pd.DataFrame,
        round_bomb_begin_defuses: pd.DataFrame,
        round_bomb_abort_defuses: pd.DataFrame,
        round_bomb_explodes: pd.DataFrame,
        frame_ticks: list[int],
        tickrate: float,
        round_players: RoundPlayers,
        throw_offset_world: float = 28.0,
        prepickup_ticks: int = 96,
        prepickup_distance_world: float = 28.0,
        inferred_claim_distance_world: float = 96.0,
        plant_duration_ticks: int = 200,
        inferred_plant_duration_ticks: int = 200,
        plant_success_window_ticks: int = 240,
        plant_abort_fade_ticks: int = 18,
    ) -> None:
        self.round_players = round_players
        self.round_bomb_pickups = round_bomb_pickups.sort_values(["tick"]).copy() if not round_bomb_pickups.empty else round_bomb_pickups.copy()
        self.round_bomb_drops = round_bomb_drops.sort_values(["tick"]).copy() if not round_bomb_drops.empty else round_bomb_drops.copy()
        self.round_bomb_begin_plants = round_bomb_begin_plants.sort_values(["tick"]).copy() if not round_bomb_begin_plants.empty else round_bomb_begin_plants.copy()
        self.round_bomb_plants = round_bomb_plants.sort_values(["tick"]).copy() if not round_bomb_plants.empty else round_bomb_plants.copy()
        self.round_bomb_defuses = round_bomb_defuses.sort_values(["tick"]).copy() if not round_bomb_defuses.empty else round_bomb_defuses.copy()
        self.round_bomb_begin_defuses = round_bomb_begin_defuses.sort_values(["tick"]).copy() if not round_bomb_begin_defuses.empty else round_bomb_begin_defuses.copy()
        self.round_bomb_abort_defuses = round_bomb_abort_defuses.sort_values(["tick"]).copy() if not round_bomb_abort_defuses.empty else round_bomb_abort_defuses.copy()
        self.round_bomb_explodes = round_bomb_explodes.sort_values(["tick"]).copy() if not round_bomb_explodes.empty else round_bomb_explodes.copy()
        self.frame_ticks = frame_ticks
        self.tickrate = tickrate if tickrate > 0 else 64.0
        self.throw_offset_world = throw_offset_world
        self.prepickup_ticks = prepickup_ticks
        self.prepickup_distance_world = prepickup_distance_world
        self.inferred_claim_distance_world = inferred_claim_distance_world
        self.plant_duration_ticks = plant_duration_ticks
        self.inferred_plant_duration_ticks = inferred_plant_duration_ticks
        self.plant_success_window_ticks = plant_success_window_ticks
        self.plant_abort_fade_ticks = plant_abort_fade_ticks
        self.segments = self._build_segments()
        self.plant_attempts = self._build_plant_attempts()
        self.defuse_attempts = self._build_defuse_attempts()

    def _segment_at(self, frame_tick: int) -> BombState | None:
        for segment in self.segments:
            if segment.start_tick <= frame_tick <= segment.end_tick:
                return segment
        return None

    def _pickup_source_for_segment(self, segment: BombState | None) -> str | None:
        if segment is None or segment.state != "carried":
            return None
        if segment.player:
            matches = self.round_bomb_pickups[
                (pd.to_numeric(self.round_bomb_pickups.get("tick"), errors="coerce") == segment.start_tick)
                & (self.round_bomb_pickups.get("user_name", pd.Series(dtype="object")).astype("string") == segment.player)
            ]
            if not matches.empty:
                row = matches.iloc[0]
                source = row.get("pickup_event_source")
                if isinstance(source, str) and source.strip():
                    return source.strip()
        return "inferred"

    def _build_segments(self) -> list[BombState]:
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
        round_start_tick = int(self.frame_ticks[0]) if self.frame_ticks else 0
        round_end_tick = int(self.frame_ticks[-1]) if self.frame_ticks else 0
        segments: list[BombState] = []
        current_state: dict[str, object] | None = None
        current_start_tick: int | None = None

        def append_segment(end_tick: int) -> None:
            nonlocal current_state, current_start_tick
            if current_state is None or current_start_tick is None or end_tick < current_start_tick:
                return
            segments.append(
                BombState(
                    state=str(current_state["state"]),
                    start_tick=current_start_tick,
                    end_tick=end_tick,
                    x=current_state.get("x"),
                    y=current_state.get("y"),
                    player=current_state.get("player"),
                )
            )

        first_event = events[0]
        first_kind = str(first_event["kind"])
        first_tick = int(first_event["tick"])
        first_row = first_event["row"]
        first_player = str(first_row.get("user_name", ""))
        if (
            round_start_tick < first_tick
            and first_kind in {"drop", "plant"}
            and first_player
        ):
            current_state = {
                "state": "carried",
                "player": first_player,
            }
            current_start_tick = round_start_tick

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
        return self._annotate_prepickup_segments(segments)

    def _death_tick_for_player(self, player_name: str) -> int | None:
        timeline = self.round_players.get_by_name(player_name)
        if timeline is None or timeline.death_tick is None:
            return None
        return int(timeline.death_tick)

    def _player_frames_between(self, player_name: str, start_tick: int, end_tick: int) -> pd.DataFrame:
        timeline = self.round_players.get_by_name(player_name)
        if timeline is None:
            return pd.DataFrame()
        return timeline.frames_between(start_tick, end_tick)

    def _dropped_segment_claim(self, segment: BombState) -> tuple[str, int, bool] | None:
        if segment.x is None or segment.y is None:
            return None

        pickup_rows = self.round_bomb_pickups[
            (self.round_bomb_pickups["tick"] >= segment.start_tick)
            & (self.round_bomb_pickups["tick"] <= segment.end_tick + 1)
        ].sort_values("tick")
        if not pickup_rows.empty:
            pickup = pickup_rows.iloc[0]
            player = str(pickup.get("user_name", ""))
            if player:
                return (player, int(pickup["tick"]), False)

        next_tick = segment.end_tick + 1
        future_claim_events: list[tuple[int, str]] = []
        for table in (self.round_bomb_plants, self.round_bomb_drops):
            if table.empty or "tick" not in table.columns:
                continue
            matches = table[table["tick"] == next_tick]
            if matches.empty:
                continue
            row = matches.iloc[0]
            player = str(row.get("user_name", ""))
            if not player:
                continue
            future_claim_events.append((int(row["tick"]), player))
        if not future_claim_events:
            return None
        future_claim_events.sort(key=lambda item: item[0])
        claim_tick, claim_player = future_claim_events[0]
        return (claim_player, claim_tick, True)

    def _annotate_prepickup_segments(self, segments: list[BombState]) -> list[BombState]:
        if not segments or self.round_bomb_pickups.empty:
            return segments
        pickup_rows = self.round_bomb_pickups.sort_values("tick")
        annotated: list[BombState] = []
        for segment in segments:
            if segment.state != "dropped" or segment.x is None or segment.y is None:
                annotated.append(segment)
                continue
            claim = self._dropped_segment_claim(segment)
            if claim is None:
                annotated.append(segment)
                continue
            player, claim_tick, inferred_claim = claim
            window_start = segment.start_tick
            prepickup_start_tick: int | None = None
            player_rows = self._player_frames_between(player, window_start, claim_tick)
            if not player_rows.empty:
                contact_distance_world = self.inferred_claim_distance_world if inferred_claim else self.prepickup_distance_world
                max_dist_sq = contact_distance_world ** 2
                for _, row in player_rows.iterrows():
                    dx = float(row["X"]) - segment.x
                    dy = float(row["Y"]) - segment.y
                    if dx * dx + dy * dy <= max_dist_sq:
                        prepickup_start_tick = int(row["tick"])
                        break
            if prepickup_start_tick is None:
                annotated.append(segment)
                continue
            annotated.append(
                BombState(
                    state=segment.state,
                    start_tick=segment.start_tick,
                    end_tick=segment.end_tick,
                    x=segment.x,
                    y=segment.y,
                    player=segment.player,
                    visual_only=segment.visual_only,
                    prepickup_player=player,
                    prepickup_start_tick=prepickup_start_tick,
                    prepickup_end_tick=claim_tick,
                )
            )
        return annotated

    def _player_world_position_at(self, player_name: str, frame_tick: int) -> tuple[float, float] | None:
        timeline = self.round_players.get_by_name(player_name)
        if timeline is None:
            return None
        position = timeline.position_at(frame_tick)
        if position is None:
            return None
        return (position[0], position[1])

    def _build_plant_attempts(self) -> list[PlantAttempt]:
        success_lookup = list(self.round_bomb_plants.itertuples(index=False)) if not self.round_bomb_plants.empty else []
        attempts: list[PlantAttempt] = []
        if self.round_bomb_begin_plants.empty:
            for planted in success_lookup:
                plant_tick = int(getattr(planted, "tick"))
                start_tick = max(
                    int(self.frame_ticks[0]) if self.frame_ticks else plant_tick,
                    plant_tick - self.inferred_plant_duration_ticks,
                )
                x = float(getattr(planted, "user_X"))
                y = float(getattr(planted, "user_Y"))
                attempts.append(
                    PlantAttempt(
                        player=str(getattr(planted, "user_name", "")),
                        start_tick=start_tick,
                        end_tick=plant_tick,
                        status="success",
                        x=x,
                        y=y,
                        anchor_x=x,
                        anchor_y=y,
                        abort_fade_end_tick=plant_tick + self.plant_abort_fade_ticks,
                    )
                )
            return attempts

        for begin in self.round_bomb_begin_plants.itertuples(index=False):
            start_tick = int(begin.tick)
            player = str(getattr(begin, "user_name", ""))
            site = getattr(begin, "site", None)
            success_row = None
            for planted in success_lookup:
                if str(getattr(planted, "user_name", "")) != player:
                    continue
                if getattr(planted, "site", None) != site:
                    continue
                plant_tick = int(getattr(planted, "tick"))
                if start_tick <= plant_tick <= start_tick + self.plant_success_window_ticks:
                    success_row = planted
                    break

            position = self._player_world_position_at(player, start_tick)
            if position is None and success_row is not None:
                position = (
                    float(getattr(success_row, "user_X")),
                    float(getattr(success_row, "user_Y")),
                )
            if position is None:
                continue

            if success_row is not None:
                end_tick = int(getattr(success_row, "tick"))
                status = "success"
                anchor_x = float(getattr(success_row, "user_X"))
                anchor_y = float(getattr(success_row, "user_Y"))
            else:
                end_tick = start_tick + self.plant_duration_ticks
                status = "aborted"
                anchor_x = float(position[0])
                anchor_y = float(position[1])

            attempts.append(
                PlantAttempt(
                    player=player,
                    start_tick=start_tick,
                    end_tick=end_tick,
                    status=status,
                    x=float(position[0]),
                    y=float(position[1]),
                    anchor_x=anchor_x,
                    anchor_y=anchor_y,
                    abort_fade_end_tick=end_tick + self.plant_abort_fade_ticks,
                )
            )
        return attempts

    def _build_defuse_attempts(self) -> list[DefuseAttempt]:
        if self.round_bomb_begin_defuses.empty:
            return []
        attempts: list[DefuseAttempt] = []
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
                DefuseAttempt(
                    player=str(begin.get("user_name", "")),
                    start_tick=start_tick,
                    end_tick=end_tick,
                    natural_end_tick=natural_end_tick,
                    duration_ticks=duration_ticks,
                    haskit=haskit,
                    status=status,
                )
            )
        return attempts

    def _is_death_drop(self, drop_row: pd.Series) -> bool:
        reason = str(drop_row.get("drop_reason", "") or "").strip().lower()
        if reason:
            return reason == "death"
        death_flag = drop_row.get("drop_is_death")
        if pd.notna(death_flag):
            return bool(death_flag)
        player = str(drop_row.get("user_name", ""))
        if not player:
            return False
        drop_tick = int(drop_row["tick"])
        death_tick = self._death_tick_for_player(player)
        return death_tick is not None and abs(death_tick - drop_tick) <= 2

    def active_plant_attempt_at(self, frame_tick: int) -> PlantAttempt | None:
        for attempt in self.plant_attempts:
            if frame_tick < attempt.start_tick:
                continue
            if attempt.status == "success" and frame_tick <= attempt.end_tick:
                return attempt
            if attempt.status == "aborted" and frame_tick <= attempt.abort_fade_end_tick:
                return attempt
        return None

    def active_defuse_attempt_at(self, frame_tick: int, abort_shake_ticks: int = 20) -> DefuseAttempt | None:
        for attempt in self.defuse_attempts:
            if attempt.start_tick <= frame_tick <= attempt.end_tick:
                return attempt
            if attempt.status == "aborted" and attempt.end_tick < frame_tick <= attempt.end_tick + abort_shake_ticks:
                return attempt
        return None

    def plant_attempt_visual_at(self, frame_tick: int) -> PlantAttemptVisual | None:
        attempt = self.active_plant_attempt_at(frame_tick)
        if attempt is None:
            return None
        start_tick = int(attempt.start_tick)
        end_tick = int(attempt.end_tick)
        abort_fade_end_tick = int(attempt.abort_fade_end_tick)
        status = str(attempt.status)
        progress = max(0.0, min(1.0, (frame_tick - start_tick) / max(1, end_tick - start_tick)))
        fade = 1.0
        center_x = float(attempt.anchor_x)
        center_y = float(attempt.anchor_y)
        if status == "aborted" and frame_tick > end_tick:
            vanish_progress = (frame_tick - end_tick) / max(1, abort_fade_end_tick - end_tick)
            fade = max(0.0, 1.0 - vanish_progress)
            center_x += math.sin(vanish_progress * math.pi * 4.0) * 4.0
        progress = max(0.02, progress)
        start_angle = -math.pi / 2
        end_angle = start_angle - (2 * math.pi * progress)
        return PlantAttemptVisual(
            center_x=center_x,
            center_y=center_y,
            progress=progress,
            fade=fade,
            start_angle=start_angle,
            end_angle=end_angle,
            status=status,
        )

    def defuse_attempt_visual_at(self, frame_tick: int, abort_shake_ticks: int = 20) -> DefuseAttemptVisual | None:
        attempt = self.active_defuse_attempt_at(frame_tick, abort_shake_ticks=abort_shake_ticks)
        if attempt is None:
            return None
        start_tick = int(attempt.start_tick)
        end_tick = int(attempt.end_tick)
        duration_ticks = max(1, int(attempt.duration_ticks))
        status = str(attempt.status)
        if status == "aborted" and frame_tick > end_tick:
            progress = max(0.0, min(1.0, (end_tick - start_tick) / duration_ticks))
            vanish_progress = (frame_tick - end_tick) / max(1, abort_shake_ticks)
            alpha_scale = max(0.0, 1.0 - vanish_progress)
            shake = math.sin(vanish_progress * math.pi * 4.0) * 4.0
        else:
            progress = max(0.0, min(1.0, (frame_tick - start_tick) / duration_ticks))
            alpha_scale = 1.0
            shake = 0.0
        return DefuseAttemptVisual(
            progress=progress,
            alpha_scale=alpha_scale,
            shake=shake,
            status=status,
        )

    def carrier_at(self, frame_tick: int) -> str | None:
        state = self.visual_state_at(frame_tick)
        if state is None or state.state != "carried":
            return None
        return state.player or None

    def icon_state_at(self, frame_tick: int) -> str | None:
        state = self.visual_state_at(frame_tick)
        if state is None:
            return None
        kind = str(state.state)
        if kind in {"carried", "dropped", "planted", "defused"}:
            return kind
        return None

    def dropped_position_at(self, frame_tick: int) -> tuple[float, float] | None:
        state = self.state_at(frame_tick)
        if state is None or state.state != "dropped" or state.x is None or state.y is None:
            return None
        return (float(state.x), float(state.y))

    def drop_reason_at(self, frame_tick: int) -> str | None:
        state = self.state_at(frame_tick)
        if state is None or state.state != "dropped":
            return None
        matches = self.round_bomb_drops[pd.to_numeric(self.round_bomb_drops.get("tick"), errors="coerce") == state.start_tick]
        if state.player:
            name_matches = matches[matches.get("user_name", pd.Series(dtype="object")).astype("string") == state.player]
            if not name_matches.empty:
                matches = name_matches
        if matches.empty:
            return None
        value = str(matches.iloc[0].get("drop_reason", "") or "").strip().lower()
        return value or None

    def planted_state_at(self, frame_tick: int) -> BombState | None:
        state = self.state_at(frame_tick)
        if state is None or state.state != "planted":
            return None
        return state

    def planted_position_at(self, frame_tick: int) -> tuple[float, float] | None:
        state = self.planted_state_at(frame_tick)
        if state is None or state.x is None or state.y is None:
            return None
        return (float(state.x), float(state.y))

    def defused_position_at(self, frame_tick: int) -> tuple[float, float] | None:
        state = self.state_at(frame_tick)
        if state is None or state.state != "defused" or state.x is None or state.y is None:
            return None
        return (float(state.x), float(state.y))

    def planted_timer_progress_at(self, frame_tick: int, total_ticks: int) -> float | None:
        state = self.planted_state_at(frame_tick)
        if state is None:
            return None
        max_ticks = max(1, int(total_ticks))
        elapsed_ticks = max(0, min(max_ticks, frame_tick - int(state.start_tick)))
        return elapsed_ticks / max_ticks

    def render_state_at(
        self,
        frame_tick: int,
        *,
        planted_total_ticks: int,
        abort_shake_ticks: int = 20,
    ) -> BombRenderState:
        visual_state = self.visual_state_at(frame_tick)
        icon_state: str | None = None
        world_position: tuple[float, float] | None = None
        carrier: str | None = None
        if visual_state is not None:
            kind = str(visual_state.state)
            if kind in {"carried", "dropped", "planted", "defused"}:
                icon_state = kind
            if kind == "carried":
                carrier = visual_state.player or None
            elif visual_state.x is not None and visual_state.y is not None:
                world_position = (float(visual_state.x), float(visual_state.y))
        # IMPORTANT: viewer should consume this aggregate render state instead of
        # stitching together bomb icon/position/timer queries from segment internals.
        return BombRenderState(
            icon_state=icon_state,
            world_position=world_position,
            carrier=carrier,
            planted_timer_progress=self.planted_timer_progress_at(frame_tick, planted_total_ticks),
            defuse_visual=self.defuse_attempt_visual_at(frame_tick, abort_shake_ticks=abort_shake_ticks),
            plant_visual=self.plant_attempt_visual_at(frame_tick),
        )

    def pickup_source_at(self, frame_tick: int) -> str | None:
        state = self.state_at(frame_tick)
        return self._pickup_source_for_segment(state)

    def state_at(self, frame_tick: int) -> BombState | None:
        return self._segment_at(frame_tick)

    def visual_state_at(self, frame_tick: int) -> BombState | None:
        state = self.state_at(frame_tick)
        if state is None or state.state != "dropped":
            return state
        if (
            state.prepickup_start_tick is not None
            and state.prepickup_end_tick is not None
            and state.prepickup_player
            and state.prepickup_start_tick <= frame_tick <= state.prepickup_end_tick
        ):
            return BombState(
                state="carried",
                start_tick=state.start_tick,
                end_tick=state.end_tick,
                player=state.prepickup_player,
                visual_only=True,
            )
        return state
