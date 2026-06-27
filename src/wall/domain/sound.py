from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from wall.domain.player import RoundPlayers


@dataclass(frozen=True)
class SoundStyle:
    color: tuple[int, int, int] = (210, 210, 210)
    draw_priority: int = 0
    alpha_mult: float = 1.0
    ring_width: int = 2
    display_radius_mult: float = 1.0
    fill_alpha_mult: float = 1.0
    capped_label: str | None = None
    suppress_lower_priority_same_emitter: bool = True
    suppression_group: str = "default"
    center_marker_radius: int = 0
    center_marker_alpha_cap: int = 0
    impulse_display_ticks: int = 1


@dataclass(frozen=True)
class SoundPresentationConfig:
    max_display_radius_ratio: float
    base_alpha: int
    global_alpha_boost: int
    start_expand_ticks: int
    end_shrink_ticks: int
    suppression_distance_px: float


@dataclass(frozen=True)
class SoundEffect:
    effect_id: str
    emitter_type: str
    source_type: str
    source_id: str
    start_tick: int
    end_tick: int
    sound_class: str
    sound_action: str
    item_name: str
    radius: float
    position_mode: str
    x: float
    y: float
    z: float
    raw_source: str
    shot_count: int | None
    style: SoundStyle


@dataclass(frozen=True)
class SoundRenderEvent:
    sound_kind: str
    center_px: tuple[float, float]
    color: tuple[int, int, int]
    radius_px: int
    alpha: int
    ring_width: int
    fill_alpha_mult: float
    is_capped: bool
    label: str | None
    emitter_key: str
    draw_priority: int
    suppression_group: str
    suppress_lower_priority_same_emitter: bool
    center_marker_radius: int
    center_marker_alpha_cap: int


DEFAULT_SOUND_STYLE = SoundStyle()
STYLE_BY_ACTION: dict[str, SoundStyle] = {
    "locomotion": SoundStyle(color=(104, 214, 144), draw_priority=40, alpha_mult=1.10, ring_width=2, display_radius_mult=0.62, fill_alpha_mult=0.0),
    "hard_step": SoundStyle(color=(176, 108, 48), draw_priority=32, alpha_mult=1.05, ring_width=2, display_radius_mult=0.82, fill_alpha_mult=0.10, impulse_display_ticks=6),
    "gunfire": SoundStyle(color=(232, 74, 74), draw_priority=10, alpha_mult=0.42, ring_width=2, display_radius_mult=1.0, fill_alpha_mult=0.0, capped_label="MAP", impulse_display_ticks=4),
    "hurt": SoundStyle(color=(255, 166, 77), draw_priority=25, alpha_mult=0.82, ring_width=2, display_radius_mult=0.72, fill_alpha_mult=0.08, impulse_display_ticks=8),
    "dropped": SoundStyle(color=(164, 196, 214), draw_priority=26, alpha_mult=0.70, ring_width=2, display_radius_mult=0.84, fill_alpha_mult=0.10, impulse_display_ticks=10),
    "bounce": SoundStyle(color=(188, 224, 236), draw_priority=45, alpha_mult=0.62, ring_width=1, display_radius_mult=0.72, fill_alpha_mult=0.0, suppress_lower_priority_same_emitter=False, suppression_group="grenade_bounce", center_marker_radius=1, center_marker_alpha_cap=120, impulse_display_ticks=12),
    "smoke_detonate": SoundStyle(color=(245, 245, 245), draw_priority=20, alpha_mult=0.48, ring_width=2, display_radius_mult=1.0, fill_alpha_mult=0.0, impulse_display_ticks=10),
    "flash_detonate": SoundStyle(color=(245, 245, 245), draw_priority=20, alpha_mult=0.48, ring_width=2, display_radius_mult=1.0, fill_alpha_mult=0.0, impulse_display_ticks=10),
    "he_detonate": SoundStyle(color=(245, 245, 245), draw_priority=20, alpha_mult=0.48, ring_width=2, display_radius_mult=1.0, fill_alpha_mult=0.0, impulse_display_ticks=12),
    "inferno_startburn": SoundStyle(color=(245, 245, 245), draw_priority=20, alpha_mult=0.48, ring_width=2, display_radius_mult=1.0, fill_alpha_mult=0.0, impulse_display_ticks=16),
    "begin_plant": SoundStyle(color=(244, 210, 91), draw_priority=20, alpha_mult=0.58, ring_width=2, display_radius_mult=1.0, fill_alpha_mult=1.0, impulse_display_ticks=12),
    "begin_defuse": SoundStyle(color=(244, 210, 91), draw_priority=20, alpha_mult=0.58, ring_width=2, display_radius_mult=1.0, fill_alpha_mult=1.0, impulse_display_ticks=16),
    "abort_defuse": SoundStyle(color=(244, 210, 91), draw_priority=20, alpha_mult=0.58, ring_width=2, display_radius_mult=1.0, fill_alpha_mult=1.0, impulse_display_ticks=10),
    "defused": SoundStyle(color=(244, 210, 91), draw_priority=20, alpha_mult=0.58, ring_width=2, display_radius_mult=1.0, fill_alpha_mult=1.0, impulse_display_ticks=16),
    "exploded": SoundStyle(color=(244, 210, 91), draw_priority=20, alpha_mult=0.58, ring_width=2, display_radius_mult=1.0, fill_alpha_mult=1.0, impulse_display_ticks=32),
    "reload": SoundStyle(color=(245, 245, 245), draw_priority=18, alpha_mult=0.46, ring_width=2, display_radius_mult=0.92, fill_alpha_mult=0.0, impulse_display_ticks=8),
    "zoom": SoundStyle(color=(245, 245, 245), draw_priority=18, alpha_mult=0.46, ring_width=2, display_radius_mult=0.92, fill_alpha_mult=0.0, impulse_display_ticks=6),
}


def _coerce_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "<na>"}:
        return ""
    return text


def _coerce_float(value: object) -> float:
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return float("nan")
    return float(numeric)


def _render_key_for_effect(effect: SoundEffect) -> str:
    if effect.sound_action == "dropped":
        utility_items = {"smokegrenade", "flashbang", "hegrenade", "molotov", "incgrenade", "decoy"}
        return "utility_drop" if effect.item_name in utility_items else "dropped"
    return effect.sound_action or effect.sound_class or "unknown"


def _style_for_effect(effect: SoundEffect) -> SoundStyle:
    render_key = _render_key_for_effect(effect)
    if render_key == "utility_drop":
        return SoundStyle(color=(198, 182, 244), draw_priority=27, alpha_mult=0.76, ring_width=2, display_radius_mult=0.88, fill_alpha_mult=0.12, impulse_display_ticks=10)
    return STYLE_BY_ACTION.get(render_key, DEFAULT_SOUND_STYLE)


def _parse_source_id(source_id: str) -> tuple[str | None, str | None]:
    if not source_id:
        return None, None
    if source_id.startswith("name:"):
        return None, source_id.split(":", 1)[1]
    return source_id, None


def resolve_sound_effect_position(
    effect: SoundEffect,
    *,
    tick: int,
    round_players: RoundPlayers | None,
) -> tuple[float, float, float] | None:
    if effect.position_mode == "event_snapshot":
        if np.isnan(effect.x) or np.isnan(effect.y):
            return None
        return (effect.x, effect.y, effect.z)
    if effect.position_mode == "entity_at_tick":
        if effect.source_type != "player" or round_players is None:
            return None
        steamid, name = _parse_source_id(effect.source_id)
        frame = round_players.frame_at(steamid=steamid, name=name, tick=tick)
        if frame is None:
            return None
        return (frame.x, frame.y, frame.z)
    return None


class SoundTimeline:
    def __init__(self, round_sound_effects: pd.DataFrame) -> None:
        sorted_effects = (
            round_sound_effects.sort_values(["start_tick", "end_tick", "sound_class", "sound_action"]).copy()
            if not round_sound_effects.empty
            else round_sound_effects.copy()
        )
        self.effects = self._build_effects(sorted_effects)

    def has_events(self) -> bool:
        return bool(self.effects)

    def present_events_at(
        self,
        frame_tick: int,
        *,
        round_players: RoundPlayers | None,
        world_to_px: Callable[[float, float], tuple[float, float]],
        world_dist_to_px: Callable[[float], float],
        viewport_width: int,
        viewport_height: int,
        presentation: SoundPresentationConfig,
    ) -> list[SoundRenderEvent]:
        if not self.effects:
            return []
        max_radius_px = max(24.0, min(viewport_width, viewport_height) * presentation.max_display_radius_ratio)
        candidates: list[SoundRenderEvent] = []
        for effect in self.effects:
            active_start, active_end = self._active_window_for(effect)
            if frame_tick < active_start or frame_tick > active_end:
                continue
            position = self.resolve_sound_effect_position(effect, tick=frame_tick, round_players=round_players)
            if position is None:
                continue
            visual_state = self._visual_state_at(
                effect,
                frame_tick=frame_tick,
                active_start_tick=active_start,
                active_end_tick=active_end,
                world_dist_to_px=world_dist_to_px,
                max_radius_px=max_radius_px,
                base_alpha=presentation.base_alpha,
                global_alpha_boost=presentation.global_alpha_boost,
                start_expand_ticks=presentation.start_expand_ticks,
                end_shrink_ticks=presentation.end_shrink_ticks,
            )
            if visual_state is None:
                continue
            radius_px, alpha, ring_width, is_capped, label = visual_state
            center_px = world_to_px(position[0], position[1])
            candidates.append(
                SoundRenderEvent(
                    sound_kind=_render_key_for_effect(effect),
                    center_px=center_px,
                    color=effect.style.color,
                    radius_px=radius_px,
                    alpha=alpha,
                    ring_width=ring_width,
                    fill_alpha_mult=effect.style.fill_alpha_mult,
                    is_capped=is_capped,
                    label=label,
                    emitter_key=self._emitter_key(effect),
                    draw_priority=effect.style.draw_priority,
                    suppression_group=effect.style.suppression_group,
                    suppress_lower_priority_same_emitter=effect.style.suppress_lower_priority_same_emitter,
                    center_marker_radius=effect.style.center_marker_radius,
                    center_marker_alpha_cap=effect.style.center_marker_alpha_cap,
                )
            )
        if not candidates:
            return []
        candidates.sort(key=lambda item: (item.draw_priority, item.radius_px, item.sound_kind))
        return self._suppress_same_emitter_rings(candidates, suppression_distance_px=presentation.suppression_distance_px)

    def resolve_sound_effect_position(
        self,
        effect: SoundEffect,
        *,
        tick: int,
        round_players: RoundPlayers | None,
    ) -> tuple[float, float, float] | None:
        return resolve_sound_effect_position(effect, tick=tick, round_players=round_players)

    def _build_effects(self, round_sound_effects: pd.DataFrame) -> list[SoundEffect]:
        if round_sound_effects.empty:
            return []
        effects: list[SoundEffect] = []
        for row in round_sound_effects.itertuples(index=False):
            start_tick = pd.to_numeric(getattr(row, "start_tick", np.nan), errors="coerce")
            end_tick = pd.to_numeric(getattr(row, "end_tick", np.nan), errors="coerce")
            radius = pd.to_numeric(getattr(row, "radius", np.nan), errors="coerce")
            if pd.isna(start_tick) or pd.isna(end_tick) or pd.isna(radius):
                continue
            effect = SoundEffect(
                effect_id=_coerce_text(getattr(row, "effect_id", "")),
                emitter_type=_coerce_text(getattr(row, "emitter_type", "")),
                source_type=_coerce_text(getattr(row, "source_type", "")),
                source_id=_coerce_text(getattr(row, "source_id", "")),
                start_tick=int(start_tick),
                end_tick=int(end_tick),
                sound_class=_coerce_text(getattr(row, "sound_class", "")),
                sound_action=_coerce_text(getattr(row, "sound_action", "")),
                item_name=_coerce_text(getattr(row, "item_name", "")),
                radius=float(radius),
                position_mode=_coerce_text(getattr(row, "position_mode", "")),
                x=_coerce_float(getattr(row, "x", np.nan)),
                y=_coerce_float(getattr(row, "y", np.nan)),
                z=_coerce_float(getattr(row, "z", np.nan)),
                raw_source=_coerce_text(getattr(row, "raw_source", "")),
                shot_count=None
                if pd.isna(pd.to_numeric(getattr(row, "shot_count", np.nan), errors="coerce"))
                else int(pd.to_numeric(getattr(row, "shot_count", np.nan), errors="coerce")),
                style=DEFAULT_SOUND_STYLE,
            )
            effects.append(effect.__class__(**{**effect.__dict__, "style": _style_for_effect(effect)}))
        return effects

    def _emitter_key(self, effect: SoundEffect) -> str:
        if effect.source_type and effect.source_id:
            return f"{effect.source_type}:{effect.source_id}"
        if effect.effect_id:
            return effect.effect_id
        return ""

    def _active_window_for(self, effect: SoundEffect) -> tuple[int, int]:
        if effect.emitter_type == "continuous":
            return effect.start_tick, effect.end_tick
        impulse_ticks = max(1, int(effect.style.impulse_display_ticks))
        return effect.start_tick, effect.start_tick + impulse_ticks - 1

    def _visual_state_at(
        self,
        effect: SoundEffect,
        *,
        frame_tick: int,
        active_start_tick: int,
        active_end_tick: int,
        world_dist_to_px: Callable[[float], float],
        max_radius_px: float,
        base_alpha: int,
        global_alpha_boost: int,
        start_expand_ticks: int,
        end_shrink_ticks: int,
    ) -> tuple[int, int, int, bool, str | None] | None:
        elapsed = frame_tick - active_start_tick
        duration_ticks = max(1, active_end_tick - active_start_tick + 1)
        fade_in_ticks = max(1, min(start_expand_ticks, duration_ticks))
        fade_out_ticks = max(1, min(end_shrink_ticks, duration_ticks))
        alpha_scale = 1.0
        if elapsed < fade_in_ticks:
            alpha_scale = min(alpha_scale, (elapsed + 1) / fade_in_ticks)
        remaining = duration_ticks - elapsed
        if remaining <= fade_out_ticks:
            alpha_scale = min(alpha_scale, max(0.0, remaining / fade_out_ticks))
        scale = 1.0
        if elapsed < fade_in_ticks:
            scale = 0.92 + 0.08 * ((elapsed + 1) / fade_in_ticks)
        elif remaining <= fade_out_ticks:
            scale = 0.96 + 0.04 * max(0.0, remaining / fade_out_ticks)
        raw_radius_px = world_dist_to_px(effect.radius) * scale
        is_capped = raw_radius_px > max_radius_px
        radius_px = int(round(min(raw_radius_px, max_radius_px) * effect.style.display_radius_mult))
        if radius_px < 4:
            return None
        resolved_base_alpha = base_alpha + (global_alpha_boost if is_capped else 0)
        alpha = max(0, min(255, int(round(resolved_base_alpha * alpha_scale * effect.style.alpha_mult))))
        if alpha <= 0:
            return None
        ring_width = int(effect.style.ring_width) + (1 if is_capped else 0)
        label = effect.style.capped_label if is_capped else None
        return radius_px, alpha, ring_width, is_capped, label

    def _suppress_same_emitter_rings(
        self,
        events: list[SoundRenderEvent],
        *,
        suppression_distance_px: float,
    ) -> list[SoundRenderEvent]:
        kept: list[SoundRenderEvent] = []
        for event in events:
            if self._is_suppressed(event, kept, suppression_distance_px=suppression_distance_px):
                continue
            kept.append(event)
        return kept

    def _is_suppressed(
        self,
        candidate: SoundRenderEvent,
        kept: list[SoundRenderEvent],
        *,
        suppression_distance_px: float,
    ) -> bool:
        if not candidate.emitter_key or not candidate.suppress_lower_priority_same_emitter:
            return False
        for existing in kept:
            if not existing.suppress_lower_priority_same_emitter:
                continue
            if existing.emitter_key != candidate.emitter_key:
                continue
            if existing.suppression_group != candidate.suppression_group:
                continue
            dx = existing.center_px[0] - candidate.center_px[0]
            dy = existing.center_px[1] - candidate.center_px[1]
            if dx * dx + dy * dy > suppression_distance_px ** 2:
                continue
            if existing.radius_px > candidate.radius_px:
                return True
        return False
