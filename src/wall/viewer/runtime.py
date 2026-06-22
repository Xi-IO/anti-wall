from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Protocol

import pygame

from wall.viewer.session import LoadedViewerData


class CachedRoundRenderer(Protocol):
    frame_ticks: list[int]
    round_start_tick: int
    show_sound_effects: bool
    player_numbers: dict[str, int]
    players: list[str]

    def render_map_frame(self, frame_tick: int) -> pygame.Surface: ...


@dataclass
class RoundCache:
    round_id: int
    renderer: CachedRoundRenderer
    frame_ticks: list[int]
    cache: OrderedDict[int, pygame.Surface]


class ViewerRoundRuntime:
    def __init__(
        self,
        *,
        loaded_data: LoadedViewerData,
        initial_round_id: int | None,
        frame_step: int,
        tickrate: float,
        max_cached_frames: int,
        renderer_factory: Callable[[int], CachedRoundRenderer],
    ) -> None:
        self.loaded_data = loaded_data
        self.frame_step = max(1, frame_step)
        self.tickrate = tickrate
        self.max_cached_frames = max_cached_frames
        self.renderer_factory = renderer_factory
        self.round_ids = loaded_data.round_ids
        if not self.round_ids:
            raise ValueError("No inferred rounds found in inferred_rounds table")
        self.selected_round_id = initial_round_id if initial_round_id in self.round_ids else self.round_ids[0]
        self.round_cache: RoundCache | None = None

    # IMPORTANT: keep round switching and frame-cache lifecycle centralized here
    # so app.py stays focused on event orchestration and view composition.
    def select_round(self, round_id: int, *, show_sound_effects: bool) -> RoundCache:
        renderer = self.renderer_factory(round_id)
        renderer.show_sound_effects = show_sound_effects
        frame_ticks = renderer.frame_ticks[:: self.frame_step]
        last_tick = renderer.frame_ticks[-1]
        if frame_ticks[-1] != last_tick:
            frame_ticks = list(frame_ticks) + [last_tick]
        self.selected_round_id = round_id
        self.round_cache = RoundCache(
            round_id=round_id,
            renderer=renderer,
            frame_ticks=[int(tick) for tick in frame_ticks],
            cache=OrderedDict(),
        )
        return self.round_cache

    def change_round(self, delta: int, *, show_sound_effects: bool) -> bool:
        current_index = self.round_ids.index(self.selected_round_id)
        next_index = max(0, min(current_index + delta, len(self.round_ids) - 1))
        if next_index == current_index:
            return False
        self.select_round(self.round_ids[next_index], show_sound_effects=show_sound_effects)
        return True

    def ensure_cached(self, frame_index: int) -> None:
        if self.round_cache is None:
            return
        frame_index = max(0, min(frame_index, len(self.round_cache.frame_ticks) - 1))
        if frame_index in self.round_cache.cache:
            self.round_cache.cache.move_to_end(frame_index)
            return
        rendered = self.round_cache.renderer.render_map_frame(self.round_cache.frame_ticks[frame_index])
        surface = rendered.convert() if hasattr(rendered, "convert") else rendered
        self.round_cache.cache[frame_index] = surface
        while len(self.round_cache.cache) > self.max_cached_frames:
            self.round_cache.cache.popitem(last=False)
