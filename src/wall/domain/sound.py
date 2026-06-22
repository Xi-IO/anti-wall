from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd


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


@dataclass(frozen=True)
class SoundPresentationConfig:
    max_display_radius_ratio: float
    base_alpha: int
    global_alpha_boost: int
    start_expand_ticks: int
    end_shrink_ticks: int
    suppression_distance_px: float


@dataclass(frozen=True)
class SoundEvent:
    tick: int
    end_tick: int
    duration_ticks: int
    sound_kind: str
    x: float
    y: float
    radius_world: float
    emitter_key: str
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
SOUND_STYLE_BY_KIND: dict[str, SoundStyle] = {
    "footstep": SoundStyle(color=(104, 214, 144), draw_priority=40, alpha_mult=1.15, ring_width=2, display_radius_mult=0.62, fill_alpha_mult=0.0),
    "landing": SoundStyle(color=(176, 108, 48), draw_priority=30, alpha_mult=1.05, ring_width=2, display_radius_mult=1.0, fill_alpha_mult=0.10),
    "gunfire": SoundStyle(color=(245, 245, 245), draw_priority=10, alpha_mult=0.42, ring_width=2, display_radius_mult=1.0, fill_alpha_mult=0.0, capped_label="MAP"),
    "damage": SoundStyle(color=(224, 78, 78), draw_priority=25, alpha_mult=0.82, ring_width=2, display_radius_mult=0.72, fill_alpha_mult=0.08),
    "grenade_bounce": SoundStyle(
        color=(188, 224, 236),
        draw_priority=45,
        alpha_mult=0.62,
        ring_width=1,
        display_radius_mult=0.72,
        fill_alpha_mult=0.0,
        suppress_lower_priority_same_emitter=False,
        suppression_group="grenade_bounce",
        center_marker_radius=1,
        center_marker_alpha_cap=120,
    ),
    "utility": SoundStyle(color=(245, 245, 245), draw_priority=20, alpha_mult=0.48, ring_width=2, display_radius_mult=1.0, fill_alpha_mult=0.0),
    "bomb": SoundStyle(color=(244, 210, 91), draw_priority=20, alpha_mult=0.58, ring_width=2, display_radius_mult=1.0, fill_alpha_mult=1.0),
}


class SoundTimeline:
    def __init__(self, round_sound_events: pd.DataFrame) -> None:
        sorted_events = round_sound_events.sort_values(["tick", "sound_kind"]).copy() if not round_sound_events.empty else round_sound_events.copy()
        self.events = self._build_events(sorted_events)

    def has_events(self) -> bool:
        return bool(self.events)

    def present_events_at(
        self,
        frame_tick: int,
        *,
        world_to_px: Callable[[float, float], tuple[float, float]],
        world_dist_to_px: Callable[[float], float],
        viewport_width: int,
        viewport_height: int,
        presentation: SoundPresentationConfig,
    ) -> list[SoundRenderEvent]:
        if not self.events:
            return []
        # IMPORTANT: viewer passes one presentation config object so sound semantics
        # stay centralized in domain and new call sites do not rebuild rule bundles ad hoc.
        max_radius_px = max(24.0, min(viewport_width, viewport_height) * presentation.max_display_radius_ratio)
        candidates: list[SoundRenderEvent] = []
        for event in self.events:
            if frame_tick < event.tick or frame_tick >= event.end_tick:
                continue
            visual_state = self._visual_state_at(
                event,
                frame_tick=frame_tick,
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
            center_px = world_to_px(event.x, event.y)
            candidates.append(
                SoundRenderEvent(
                    sound_kind=event.sound_kind,
                    center_px=center_px,
                    color=event.style.color,
                    radius_px=radius_px,
                    alpha=alpha,
                    ring_width=ring_width,
                    fill_alpha_mult=event.style.fill_alpha_mult,
                    is_capped=is_capped,
                    label=label,
                    emitter_key=event.emitter_key,
                    draw_priority=event.style.draw_priority,
                    suppression_group=event.style.suppression_group,
                    suppress_lower_priority_same_emitter=event.style.suppress_lower_priority_same_emitter,
                    center_marker_radius=event.style.center_marker_radius,
                    center_marker_alpha_cap=event.style.center_marker_alpha_cap,
                )
            )
        if not candidates:
            return []
        candidates.sort(key=lambda item: (item.draw_priority, item.radius_px, item.sound_kind))
        return self._suppress_same_emitter_rings(candidates, suppression_distance_px=presentation.suppression_distance_px)

    def _build_events(self, round_sound_events: pd.DataFrame) -> list[SoundEvent]:
        if round_sound_events.empty:
            return []
        events: list[SoundEvent] = []
        for sound in round_sound_events.itertuples(index=False):
            x = pd.to_numeric(getattr(sound, "x", np.nan), errors="coerce")
            y = pd.to_numeric(getattr(sound, "y", np.nan), errors="coerce")
            radius_world = pd.to_numeric(getattr(sound, "radius_world", np.nan), errors="coerce")
            tick = pd.to_numeric(getattr(sound, "tick", np.nan), errors="coerce")
            duration_ticks = pd.to_numeric(getattr(sound, "duration_ticks", 1), errors="coerce")
            if pd.isna(x) or pd.isna(y) or pd.isna(radius_world) or pd.isna(tick):
                continue
            normalized_duration = max(1, int(duration_ticks)) if pd.notna(duration_ticks) else 1
            sound_kind = str(getattr(sound, "sound_kind", "") or "")
            events.append(
                SoundEvent(
                    tick=int(tick),
                    end_tick=int(tick) + normalized_duration,
                    duration_ticks=normalized_duration,
                    sound_kind=sound_kind,
                    x=float(x),
                    y=float(y),
                    radius_world=float(radius_world),
                    emitter_key=self._emitter_key(sound),
                    style=SOUND_STYLE_BY_KIND.get(sound_kind, DEFAULT_SOUND_STYLE),
                )
            )
        return events

    def _emitter_key(self, sound) -> str:
        grenade_entity_id = pd.to_numeric(getattr(sound, "grenade_entity_id", np.nan), errors="coerce")
        if pd.notna(grenade_entity_id):
            return f"grenade:{int(grenade_entity_id)}"
        steamid = str(getattr(sound, "emitter_steamid", "") or "").strip()
        if steamid and steamid.lower() != "nan":
            return f"steamid:{steamid}"
        name = str(getattr(sound, "emitter_name", "") or "").strip()
        if name and name.lower() != "nan":
            return f"name:{name}"
        return ""

    def _visual_state_at(
        self,
        event: SoundEvent,
        *,
        frame_tick: int,
        world_dist_to_px: Callable[[float], float],
        max_radius_px: float,
        base_alpha: int,
        global_alpha_boost: int,
        start_expand_ticks: int,
        end_shrink_ticks: int,
    ) -> tuple[int, int, int, bool, str | None] | None:
        elapsed = frame_tick - event.tick
        duration_ticks = event.duration_ticks
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
            t = (elapsed + 1) / fade_in_ticks
            scale = 0.92 + 0.08 * t
        elif remaining <= fade_out_ticks:
            t = max(0.0, remaining / fade_out_ticks)
            scale = 0.96 + 0.04 * t

        raw_radius_px = world_dist_to_px(event.radius_world) * scale
        is_capped = raw_radius_px > max_radius_px
        radius_px = int(round(min(raw_radius_px, max_radius_px) * event.style.display_radius_mult))
        if radius_px < 4:
            return None
        resolved_base_alpha = base_alpha + (global_alpha_boost if is_capped else 0)
        alpha = max(0, min(255, int(round(resolved_base_alpha * alpha_scale * event.style.alpha_mult))))
        if alpha <= 0:
            return None
        ring_width = int(event.style.ring_width) + (1 if is_capped else 0)
        label = event.style.capped_label if is_capped else None
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
        if not candidate.emitter_key:
            return False
        if not candidate.suppress_lower_priority_same_emitter:
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
