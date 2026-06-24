from __future__ import annotations

from dataclasses import dataclass, field
import bisect

import pygame


@dataclass
class PlaybackState:
    current_frame_index: int = 0
    current_playback_tick: float = 0.0
    playing: bool = True
    dragging_timeline: bool = False

    # IMPORTANT: keep playback index/tick synchronization here so viewer UI
    # code does not reimplement timeline state transitions in multiple places.
    def reset(self, frame_ticks: list[int], *, playing: bool = True) -> None:
        self.current_frame_index = 0
        self.current_playback_tick = float(frame_ticks[0]) if frame_ticks else 0.0
        self.playing = playing
        self.dragging_timeline = False

    def set_frame_index(self, frame_index: int, frame_ticks: list[int]) -> int:
        if not frame_ticks:
            self.current_frame_index = 0
            self.current_playback_tick = 0.0
            return 0
        clamped_index = max(0, min(frame_index, len(frame_ticks) - 1))
        self.current_frame_index = clamped_index
        self.current_playback_tick = float(frame_ticks[clamped_index])
        return clamped_index

    def step_frame(self, delta: int, frame_ticks: list[int]) -> int:
        return self.set_frame_index(self.current_frame_index + delta, frame_ticks)

    def seek_to_timeline_position(self, mouse_x: int, timeline_rect: pygame.Rect, frame_ticks: list[int]) -> int:
        ratio = (mouse_x - timeline_rect.x) / max(1, timeline_rect.width)
        ratio = max(0.0, min(1.0, ratio))
        frame_index = int(round(ratio * max(0, len(frame_ticks) - 1)))
        return self.set_frame_index(frame_index, frame_ticks)

    def advance(self, dt_seconds: float, *, tickrate: float, speed: float, frame_ticks: list[int]) -> int:
        if not frame_ticks:
            self.current_frame_index = 0
            self.current_playback_tick = 0.0
            self.playing = False
            return 0
        self.current_playback_tick += dt_seconds * tickrate * speed
        last_tick = float(frame_ticks[-1])
        if self.current_playback_tick >= last_tick:
            self.current_playback_tick = last_tick
            self.current_frame_index = len(frame_ticks) - 1
            self.playing = False
            return self.current_frame_index
        frame_index = bisect.bisect_right(frame_ticks, self.current_playback_tick) - 1
        self.current_frame_index = max(0, min(frame_index, len(frame_ticks) - 1))
        return self.current_frame_index


@dataclass
class RoundDropdownState:
    visible_count: int = 5
    is_open: bool = False
    start_index: int = 0
    dragging_scroll: bool = False
    area_rect: pygame.Rect = field(default_factory=lambda: pygame.Rect(0, 0, 0, 0))
    track_rect: pygame.Rect = field(default_factory=lambda: pygame.Rect(0, 0, 0, 0))
    thumb_rect: pygame.Rect = field(default_factory=lambda: pygame.Rect(0, 0, 0, 0))

    def reset_layout(self) -> None:
        self.area_rect = pygame.Rect(0, 0, 0, 0)
        self.track_rect = pygame.Rect(0, 0, 0, 0)
        self.thumb_rect = pygame.Rect(0, 0, 0, 0)

    def close(self) -> None:
        self.is_open = False
        self.dragging_scroll = False

    def align_to_selected(self, selected_index: int, total_count: int) -> None:
        max_start = max(0, total_count - self.visible_count)
        self.start_index = max(0, min(selected_index, max_start))

    def toggle(self, selected_index: int, total_count: int) -> None:
        self.is_open = not self.is_open
        if self.is_open:
            self.align_to_selected(selected_index, total_count)

    def scroll(self, delta: int, total_count: int) -> None:
        max_start = max(0, total_count - self.visible_count)
        self.start_index = max(0, min(self.start_index - delta, max_start))

    def jump_to_mouse(self, mouse_y: int, total_count: int) -> None:
        if total_count <= self.visible_count or self.track_rect.height <= 0:
            return
        max_start = max(0, total_count - self.visible_count)
        relative_y = mouse_y - self.track_rect.y
        ratio = max(0.0, min(1.0, relative_y / max(1, self.track_rect.height)))
        self.start_index = int(round(ratio * max_start))

    def update_from_mouse(self, mouse_y: int, total_count: int) -> None:
        if total_count <= self.visible_count or self.track_rect.height <= 0 or self.thumb_rect.height <= 0:
            return
        max_start = max(0, total_count - self.visible_count)
        thumb_half = self.thumb_rect.height / 2
        relative_y = mouse_y - self.track_rect.y - thumb_half
        thumb_travel = max(1.0, self.track_rect.height - self.thumb_rect.height)
        ratio = max(0.0, min(1.0, relative_y / thumb_travel))
        self.start_index = int(round(ratio * max_start))

    def clamp_start(self, total_count: int) -> None:
        max_start = max(0, total_count - self.visible_count)
        self.start_index = max(0, min(self.start_index, max_start))

    def visible_round_ids(self, round_ids: list[int]) -> list[int]:
        return round_ids[self.start_index : self.start_index + self.visible_count]


@dataclass
class SidebarInfoPanelState:
    start_index: int = 0
    stick_to_latest: bool = True
    dragging_scroll: bool = False
    viewport_rect: pygame.Rect = field(default_factory=lambda: pygame.Rect(0, 0, 0, 0))
    track_rect: pygame.Rect = field(default_factory=lambda: pygame.Rect(0, 0, 0, 0))
    thumb_rect: pygame.Rect = field(default_factory=lambda: pygame.Rect(0, 0, 0, 0))

    def reset_layout(self) -> None:
        self.viewport_rect = pygame.Rect(0, 0, 0, 0)
        self.track_rect = pygame.Rect(0, 0, 0, 0)
        self.thumb_rect = pygame.Rect(0, 0, 0, 0)

    def max_start(self, total_count: int, visible_count: int) -> int:
        return max(0, total_count - max(1, visible_count))

    def is_at_latest(self, total_count: int, visible_count: int) -> bool:
        return self.start_index >= self.max_start(total_count, visible_count)

    def snap_to_latest(self, total_count: int, visible_count: int) -> None:
        self.start_index = self.max_start(total_count, visible_count)
        self.stick_to_latest = True

    def clamp_start(self, total_count: int, visible_count: int) -> None:
        max_start = self.max_start(total_count, visible_count)
        self.start_index = max(0, min(self.start_index, max_start))
        if self.stick_to_latest:
            self.start_index = max_start

    def scroll(self, delta: int, total_count: int, visible_count: int) -> None:
        max_start = self.max_start(total_count, visible_count)
        self.start_index = max(0, min(self.start_index - delta, max_start))
        self.stick_to_latest = self.start_index >= max_start

    def jump_to_mouse(self, mouse_y: int, total_count: int, visible_count: int) -> None:
        if total_count <= visible_count or self.track_rect.height <= 0:
            return
        max_start = self.max_start(total_count, visible_count)
        relative_y = mouse_y - self.track_rect.y
        ratio = max(0.0, min(1.0, relative_y / max(1, self.track_rect.height)))
        self.start_index = int(round(ratio * max_start))
        self.stick_to_latest = self.start_index >= max_start

    def update_from_mouse(self, mouse_y: int, total_count: int, visible_count: int) -> None:
        if total_count <= visible_count or self.track_rect.height <= 0 or self.thumb_rect.height <= 0:
            return
        max_start = self.max_start(total_count, visible_count)
        thumb_half = self.thumb_rect.height / 2
        relative_y = mouse_y - self.track_rect.y - thumb_half
        thumb_travel = max(1.0, self.track_rect.height - self.thumb_rect.height)
        ratio = max(0.0, min(1.0, relative_y / thumb_travel))
        self.start_index = int(round(ratio * max_start))
        self.stick_to_latest = self.start_index >= max_start

    def visible_lines(self, lines: list[str], visible_count: int) -> list[str]:
        visible = max(1, visible_count)
        return lines[self.start_index : self.start_index + visible]
