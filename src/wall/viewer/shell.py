from __future__ import annotations

import bisect
from pathlib import Path
import time
from typing import Literal

try:
    import pygame
except ModuleNotFoundError as exc:
    raise SystemExit(
        "pygame is not installed in the current environment. "
        "Install it in the 'wall' environment first, then rerun this viewer."
    ) from exc

from wall.paths import awpy_maps_dir, resolve_asset_path
from wall.render.round_render import team_color
from wall.dataset.index import DatasetIndex
from wall.profile import profile_log
from wall.viewer.config import (
    ACCENT_COLOR,
    BACKGROUND_COLOR,
    BOTTOM_BAR_HEIGHT,
    BUTTON_ACTIVE_COLOR,
    BUTTON_COLOR,
    MUTED_TEXT_COLOR,
    SIDEBAR_COLOR,
    SIDEBAR_WIDTH,
    SPEED_OPTIONS,
    TEXT_COLOR,
)
from wall.viewer.layout import build_round_dropdown_overlay
from wall.viewer.loading import ViewerDatasetLoader, ViewerLoadState
from wall.viewer.renderer import PygameRoundRenderer
from wall.viewer.runtime import ViewerRoundRuntime
from wall.viewer.state import PlaybackState, RoundDropdownState
from wall.viewer.ui import SidebarPlayerEntry, draw_bottom_bar, draw_sidebar, format_hud_number


class PygameRoundViewer:
    def __init__(
        self,
        data_dir: Path,
        initial_round_id: int | None,
        map_width: int,
        map_height: int,
        fps: int,
        frame_step: int,
        tickrate: float,
    ) -> None:
        init_started_at = time.perf_counter()
        profile_log("viewer.init.start")
        pygame.init()
        pygame.font.init()
        self.data_dir = data_dir
        self.fps = fps
        self.tickrate = tickrate
        self.frame_step = max(1, frame_step)
        self.initial_map_width = map_width
        self.initial_map_height = map_height
        self.initial_round_id = initial_round_id
        self.loaded_data: DatasetIndex | None = None
        self.runtime: ViewerRoundRuntime | None = None
        self.player_numbers: dict[str, int] = {}
        self.map_width = map_width
        self.map_height = map_height
        self.screen = pygame.display.set_mode(
            (self.map_width + SIDEBAR_WIDTH, self.map_height + BOTTOM_BAR_HEIGHT),
            pygame.RESIZABLE,
        )
        pygame.display.set_caption("wall pygame viewer")
        self.clock = pygame.time.Clock()
        self.playback = PlaybackState()
        self.show_sound_effects = True
        self.max_cached_frames = 240
        self.speed_index = SPEED_OPTIONS.index(1.0)
        self.font = pygame.font.SysFont("segoe ui", 18)
        self.small_font = pygame.font.SysFont("segoe ui", 14)
        self.sound_toggle_icons = self._load_viewer_sound_toggle_icons()
        self.button_rects: dict[str, pygame.Rect] = {}
        self.round_item_rects: dict[int, pygame.Rect] = {}
        self.speed_rects: dict[float, pygame.Rect] = {}
        self.round_dropdown = RoundDropdownState()
        self.dataset_loader = ViewerDatasetLoader(self.data_dir)
        self.load_state: ViewerLoadState[DatasetIndex] = self.dataset_loader.state
        self.startup_stage: Literal["waiting_for_dataset", "select_round", "cache_first_frame", "ready", "failed"] = "waiting_for_dataset"
        self.loading_message = "Loading dataset"
        self.pending_resize_dimensions: tuple[int, int] | None = None
        self.resize_rebuild_pending = False
        profile_log("viewer.init.end", started_at=init_started_at)

    def _resolve_map_viewport_size(self, target_width: int, target_height: int) -> tuple[int, int]:
        if self.loaded_data is None:
            return target_width, target_height
        map_name = self.loaded_data.map_name
        if not map_name:
            return target_width, target_height
        map_path = awpy_maps_dir() / f"{map_name}.png"
        if not map_path.exists():
            return target_width, target_height
        try:
            map_surface = pygame.image.load(str(map_path))
            original_width, original_height = map_surface.get_size()
        except pygame.error:
            return target_width, target_height
        if original_width <= 0 or original_height <= 0:
            return target_width, target_height
        scale = min(target_width / original_width, target_height / original_height)
        width = max(1, int(round(original_width * scale)))
        height = max(1, int(round(original_height * scale)))
        return width, height

    @property
    def round_ids(self) -> list[int]:
        if self.runtime is None:
            return []
        return self.runtime.round_ids

    @property
    def selected_round_id(self) -> int:
        if self.runtime is None:
            if self.initial_round_id is not None:
                return int(self.initial_round_id)
            raise ValueError("Viewer round selection is not ready yet.")
        return self.runtime.selected_round_id

    @property
    def round_cache(self):
        if self.runtime is None:
            return None
        return self.runtime.round_cache

    def _build_renderer(self, round_id: int) -> PygameRoundRenderer:
        # IMPORTANT: shell owns orchestration and wiring only.
        # Semantic assembly stays in session/domain, while draw behavior stays in renderer.
        renderer_started_at = time.perf_counter()
        profile_log("renderer.init.start", round_id=round_id, map_name=None if self.loaded_data is None else self.loaded_data.map_name)
        self.player_numbers = self.loaded_data.build_demo_hud_numbers(round_id)
        profile_log("dataset.build_round_data.before_call", round_id=round_id, map_name=None if self.loaded_data is None else self.loaded_data.map_name)
        round_data = self.loaded_data.build_round_data(round_id, tickrate=self.tickrate)
        profile_log("renderer.round_data.ready", started_at=renderer_started_at, round_id=round_id, map_name=None if self.loaded_data is None else self.loaded_data.map_name)
        renderer = PygameRoundRenderer(
            round_data=round_data,
            player_numbers=self.player_numbers,
            width=self.map_width,
            height=self.map_height,
            trail=24,
            facing_radius=70.0,
            facing_fov=90.0,
            map_name=self.loaded_data.map_name,
            tickrate=self.tickrate,
        )
        profile_log("renderer.init.end", started_at=renderer_started_at, round_id=round_id, map_name=self.loaded_data.map_name)
        return renderer

    def _apply_window_size(self, window_width: int, window_height: int) -> None:
        self.pending_resize_dimensions = (int(window_width), int(window_height))

    def _flush_pending_window_size(self) -> None:
        if self.pending_resize_dimensions is None:
            return
        window_width, window_height = self.pending_resize_dimensions
        self.pending_resize_dimensions = None
        requested_map_width = max(320, int(window_width) - SIDEBAR_WIDTH)
        requested_map_height = max(240, int(window_height) - BOTTOM_BAR_HEIGHT)
        self.map_width, self.map_height = self._resolve_map_viewport_size(requested_map_width, requested_map_height)
        self.screen = pygame.display.set_mode(
            (self.map_width + SIDEBAR_WIDTH, self.map_height + BOTTOM_BAR_HEIGHT),
            pygame.RESIZABLE,
        )
        self.resize_rebuild_pending = self.round_cache is not None

    def _rebuild_after_resize_if_needed(self) -> None:
        if not self.resize_rebuild_pending or self.round_cache is None or self.runtime is None:
            self.resize_rebuild_pending = False
            return
        selected_round_id = self.selected_round_id
        current_tick = self.round_cache.frame_ticks[self.playback.current_frame_index]
        was_playing = self.playback.playing
        self.runtime.select_round(selected_round_id, show_sound_effects=self.show_sound_effects)
        frame_ticks = self.round_cache.frame_ticks
        frame_index = max(0, bisect.bisect_right(frame_ticks, current_tick) - 1)
        self.playback.set_frame_index(frame_index, frame_ticks)
        self.playback.current_playback_tick = float(current_tick)
        self.playback.playing = was_playing
        self._ensure_cached(self.playback.current_frame_index)
        self.resize_rebuild_pending = False

    def select_round(self, round_id: int, *, cache_first_frame: bool = True) -> None:
        if self.runtime is None:
            raise RuntimeError("Viewer runtime is not ready yet.")
        select_started_at = time.perf_counter()
        profile_log("viewer.select_round.start", round_id=round_id, map_name=None if self.loaded_data is None else self.loaded_data.map_name)
        self.round_dropdown.close()
        selected_index = self.round_ids.index(round_id)
        self.round_dropdown.align_to_selected(selected_index, len(self.round_ids))
        self.runtime.select_round(round_id, show_sound_effects=self.show_sound_effects)
        self.playback.reset(self.round_cache.frame_ticks)
        if cache_first_frame:
            profile_log("viewer.first_frame_cache.start", round_id=round_id, map_name=None if self.loaded_data is None else self.loaded_data.map_name)
            self.runtime.ensure_cached(0)
            profile_log("viewer.first_frame_cache.end", round_id=round_id, map_name=None if self.loaded_data is None else self.loaded_data.map_name)
        profile_log("viewer.select_round.end", started_at=select_started_at, round_id=round_id, map_name=None if self.loaded_data is None else self.loaded_data.map_name)

    def _ensure_cached(self, frame_index: int) -> None:
        if self.runtime is None:
            return
        self.runtime.ensure_cached(frame_index)

    def _install_loaded_dataset(self, loaded_data: DatasetIndex) -> None:
        self.loaded_data = loaded_data
        self.runtime = ViewerRoundRuntime(
            loaded_data=self.loaded_data,
            initial_round_id=self.initial_round_id,
            frame_step=self.frame_step,
            tickrate=self.tickrate,
            max_cached_frames=self.max_cached_frames,
            renderer_factory=self._build_renderer,
        )
        self.pending_resize_dimensions = self.screen.get_size()
        self._flush_pending_window_size()
        self.startup_stage = "select_round"
        profile_log("viewer.dataset_ready", note=f"rounds={len(self.runtime.round_ids)}")

    def _advance_startup(self) -> None:
        if self.startup_stage == "waiting_for_dataset":
            self.dataset_loader.start()
            self.load_state = self.dataset_loader.poll()
            if self.load_state.status == "loading":
                self.loading_message = "Loading dataset"
                return
            if self.load_state.status == "failed":
                self.loading_message = f"Loading failed: {type(self.load_state.error).__name__}"
                self.startup_stage = "failed"
                return
            if self.load_state.status == "complete":
                assert self.load_state.value is not None
                self._install_loaded_dataset(self.load_state.value)
                return
        if self.startup_stage == "select_round":
            self.loading_message = "Preparing initial round"
            self.select_round(self.selected_round_id, cache_first_frame=False)
            self.startup_stage = "cache_first_frame"
            profile_log("viewer.initial_round_selected", round_id=self.selected_round_id)
            return
        if self.startup_stage == "cache_first_frame":
            self.loading_message = "Rendering first frame"
            profile_log("viewer.first_frame_cache.start", round_id=self.selected_round_id, map_name=None if self.loaded_data is None else self.loaded_data.map_name)
            self._ensure_cached(0)
            profile_log("viewer.first_frame_cache.end", round_id=self.selected_round_id, map_name=None if self.loaded_data is None else self.loaded_data.map_name)
            self.startup_stage = "ready"
            self.loading_message = "Ready"
            profile_log("viewer.first_frame_ready", round_id=self.selected_round_id)

    def _draw_loading(self) -> None:
        self.screen.fill(BACKGROUND_COLOR)
        title = self.font.render("wall viewer", True, TEXT_COLOR)
        message = self.small_font.render(self.loading_message, True, MUTED_TEXT_COLOR)
        title_rect = title.get_rect(center=(self.screen.get_width() // 2, self.screen.get_height() // 2 - 14))
        message_rect = message.get_rect(center=(self.screen.get_width() // 2, self.screen.get_height() // 2 + 14))
        self.screen.blit(title, title_rect)
        self.screen.blit(message, message_rect)

    def run(self) -> None:
        running = True
        try:
            while running:
                dt_seconds = self.clock.tick(self.fps) / 1000.0
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                    elif event.type == pygame.KEYDOWN:
                        running = self._handle_keydown(event)
                    elif event.type == pygame.MOUSEBUTTONDOWN:
                        button = getattr(event, "button", None)
                        if button == 4:
                            self._handle_mousewheel(1, event.pos)
                        elif button == 5:
                            self._handle_mousewheel(-1, event.pos)
                        elif button == 1:
                            self._handle_mouse_down(event.pos)
                    elif event.type == pygame.MOUSEWHEEL:
                        self._handle_mousewheel(event.y, pygame.mouse.get_pos())
                    elif event.type == pygame.MOUSEBUTTONUP:
                        self.playback.dragging_timeline = False
                        self.round_dropdown.dragging_scroll = False
                    elif event.type == pygame.MOUSEMOTION:
                        if self.playback.dragging_timeline:
                            self._update_timeline_from_mouse(event.pos)
                        elif self.round_dropdown.dragging_scroll:
                            self._update_round_scroll_from_mouse(event.pos)
                    elif event.type == pygame.VIDEORESIZE:
                        self._apply_window_size(event.w, event.h)
                    elif hasattr(pygame, "WINDOWSIZECHANGED") and event.type == pygame.WINDOWSIZECHANGED:
                        self._apply_window_size(event.x, event.y)

                self._flush_pending_window_size()
                if self.startup_stage not in {"ready", "failed"}:
                    self._advance_startup()
                elif self.resize_rebuild_pending:
                    self._rebuild_after_resize_if_needed()
                if self.startup_stage == "ready" and self.playback.playing and self.round_cache is not None:
                    self._advance_playback(dt_seconds)
                self._draw()
                pygame.display.flip()
        finally:
            self.dataset_loader.shutdown()
            pygame.quit()

    def _handle_keydown(self, event: pygame.event.Event) -> bool:
        if event.key == pygame.K_ESCAPE:
            return False
        if self.round_cache is None:
            return True
        if event.key == pygame.K_SPACE:
            self.playback.playing = not self.playback.playing
        elif event.key == pygame.K_RIGHT:
            self._ensure_cached(self.playback.step_frame(1, self.round_cache.frame_ticks))
        elif event.key == pygame.K_LEFT:
            self._ensure_cached(self.playback.step_frame(-1, self.round_cache.frame_ticks))
        elif event.key == pygame.K_DOWN:
            self._change_round(1)
        elif event.key == pygame.K_UP:
            self._change_round(-1)
        elif event.key == pygame.K_m:
            self._toggle_sound_effects()
        elif event.key in (pygame.K_MINUS, pygame.K_LEFTBRACKET):
            self._change_speed(-1)
        elif event.key in (pygame.K_EQUALS, pygame.K_RIGHTBRACKET):
            self._change_speed(1)
        elif event.key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5, pygame.K_6):
            self.speed_index = event.key - pygame.K_1
        return True

    def _handle_mouse_down(self, position: tuple[int, int]) -> None:
        dropdown_rect = self.button_rects.get("round_dropdown")
        if dropdown_rect and dropdown_rect.collidepoint(position):
            self.round_dropdown.toggle(self.round_ids.index(self.selected_round_id), len(self.round_ids))
            return
        if self.button_rects.get("round_scroll_up") and self.button_rects["round_scroll_up"].collidepoint(position):
            self._scroll_round_dropdown(1)
            return
        if self.button_rects.get("round_scroll_down") and self.button_rects["round_scroll_down"].collidepoint(position):
            self._scroll_round_dropdown(-1)
            return
        if self.round_dropdown.thumb_rect.collidepoint(position):
            self.round_dropdown.dragging_scroll = True
            self._update_round_scroll_from_mouse(position)
            return
        if self.round_dropdown.track_rect.collidepoint(position):
            self._jump_round_scroll_to_mouse(position)
            return
        for round_id, rect in self.round_item_rects.items():
            if rect.collidepoint(position):
                self.select_round(round_id)
                return
        if self.button_rects.get("prev_round") and self.button_rects["prev_round"].collidepoint(position):
            self._change_round(-1)
            return
        if self.button_rects.get("play") and self.button_rects["play"].collidepoint(position):
            self.playback.playing = not self.playback.playing
            return
        if self.button_rects.get("next_round") and self.button_rects["next_round"].collidepoint(position):
            self._change_round(1)
            return
        if self.button_rects.get("sound_toggle") and self.button_rects["sound_toggle"].collidepoint(position):
            self._toggle_sound_effects()
            return
        for speed_value, rect in self.speed_rects.items():
            if rect.collidepoint(position):
                self.speed_index = SPEED_OPTIONS.index(speed_value)
                return
        if self.button_rects.get("timeline") and self.button_rects["timeline"].collidepoint(position):
            self.playback.dragging_timeline = True
            self._update_timeline_from_mouse(position)
            return
        self.round_dropdown.close()

    def _handle_mousewheel(self, delta: int, position: tuple[int, int] | None = None) -> None:
        if not self.round_dropdown.is_open or len(self.round_ids) <= self.round_dropdown.visible_count:
            return
        if position is not None:
            hit_dropdown = (
                self.round_dropdown.area_rect.collidepoint(position)
                or self.round_dropdown.track_rect.collidepoint(position)
                or self.round_dropdown.thumb_rect.collidepoint(position)
                or (self.button_rects.get("round_dropdown") and self.button_rects["round_dropdown"].collidepoint(position))
            )
            if not hit_dropdown:
                return
        self._scroll_round_dropdown(delta)

    def _scroll_round_dropdown(self, delta: int) -> None:
        self.round_dropdown.scroll(delta, len(self.round_ids))

    def _jump_round_scroll_to_mouse(self, position: tuple[int, int]) -> None:
        self.round_dropdown.jump_to_mouse(position[1], len(self.round_ids))

    def _update_round_scroll_from_mouse(self, position: tuple[int, int]) -> None:
        self.round_dropdown.update_from_mouse(position[1], len(self.round_ids))

    def _update_timeline_from_mouse(self, position: tuple[int, int]) -> None:
        if self.round_cache is None:
            return
        timeline_rect = self.button_rects.get("timeline")
        if timeline_rect is None:
            return
        frame_index = self.playback.seek_to_timeline_position(position[0], timeline_rect, self.round_cache.frame_ticks)
        self._ensure_cached(frame_index)

    def _advance_playback(self, dt_seconds: float) -> None:
        if self.round_cache is None:
            return
        speed = SPEED_OPTIONS[self.speed_index]
        frame_index = self.playback.advance(
            dt_seconds,
            tickrate=self.tickrate,
            speed=speed,
            frame_ticks=self.round_cache.frame_ticks,
        )
        self._ensure_cached(frame_index)

    def _change_speed(self, delta: int) -> None:
        self.speed_index = max(0, min(self.speed_index + delta, len(SPEED_OPTIONS) - 1))

    def _change_round(self, delta: int) -> None:
        if self.runtime.change_round(delta, show_sound_effects=self.show_sound_effects):
            self.round_dropdown.close()
            self.round_dropdown.align_to_selected(self.round_ids.index(self.selected_round_id), len(self.round_ids))
            self.playback.reset(self.round_cache.frame_ticks)
            self.runtime.ensure_cached(0)

    def _load_viewer_sound_toggle_icons(self) -> dict[str, pygame.Surface]:
        icons: dict[str, pygame.Surface] = {}
        for key, filename in (("sound_on", "ui/icons/sound_on.png"), ("sound_off", "ui/icons/sound_off.png")):
            icon_path = resolve_asset_path(filename)
            if not icon_path.exists():
                continue
            try:
                icon = pygame.image.load(str(icon_path)).convert_alpha()
            except pygame.error:
                continue
            width, height = icon.get_size()
            if width <= 0 or height <= 0:
                continue
            target_height = 17
            scale = target_height / height
            scaled_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
            icons[key] = pygame.transform.smoothscale(icon, scaled_size)
        return icons

    def _toggle_sound_effects(self) -> None:
        self.show_sound_effects = not self.show_sound_effects
        if self.round_cache is None:
            return
        self.round_cache.renderer.show_sound_effects = self.show_sound_effects
        self.round_cache.cache.clear()
        self._ensure_cached(self.playback.current_frame_index)

    def _content_origin(self) -> tuple[int, int]:
        screen_width, screen_height = self.screen.get_size()
        content_width = self.map_width + SIDEBAR_WIDTH
        content_height = self.map_height + BOTTOM_BAR_HEIGHT
        origin_x = max(0, (screen_width - content_width) // 2)
        origin_y = max(0, (screen_height - content_height) // 2)
        return origin_x, origin_y

    def _draw(self) -> None:
        if self.startup_stage != "ready":
            self._draw_loading()
            return
        self.screen.fill(BACKGROUND_COLOR)
        content_origin_x, content_origin_y = self._content_origin()
        if self.round_cache is not None:
            self._ensure_cached(self.playback.current_frame_index)
            map_surface = self.round_cache.cache[self.playback.current_frame_index]
            self.screen.blit(map_surface, (content_origin_x, content_origin_y))
        self._draw_sidebar(content_origin_x=content_origin_x, content_origin_y=content_origin_y)
        self._draw_bottom_bar(content_origin_x=content_origin_x, content_origin_y=content_origin_y)

    def _draw_sidebar(self, *, content_origin_x: int, content_origin_y: int) -> None:
        self.button_rects = {key: value for key, value in self.button_rects.items() if key == "timeline"}
        self.round_item_rects = {}
        self.speed_rects = {}
        self.round_dropdown.reset_layout()
        dropdown_overlay = build_round_dropdown_overlay(
            origin_x=content_origin_x + self.map_width + 16,
            origin_y=content_origin_y + 110,
            width=SIDEBAR_WIDTH - 32,
            round_ids=self.round_ids,
            selected_round_id=self.selected_round_id,
            dropdown=self.round_dropdown,
        )
        if self.round_cache is None:
            return
        current_tick = self.round_cache.frame_ticks[self.playback.current_frame_index]
        relative_tick = current_tick - self.round_cache.renderer.round_start_tick
        relative_seconds = relative_tick / self.tickrate if self.tickrate > 0 else 0.0
        player_entries = [
            SidebarPlayerEntry(
                label=self._sidebar_player_label(player, current_tick),
                color=team_color(self._team_num_at_tick(player, current_tick)),
            )
            for player in self.round_cache.renderer.players
        ]
        sidebar = draw_sidebar(
            screen=self.screen,
            content_origin_x=content_origin_x,
            content_origin_y=content_origin_y,
            map_width=self.map_width,
            map_height=self.map_height,
            sidebar_width=SIDEBAR_WIDTH,
            bottom_bar_height=BOTTOM_BAR_HEIGHT,
            font=self.font,
            small_font=self.small_font,
            text_color=TEXT_COLOR,
            muted_text_color=MUTED_TEXT_COLOR,
            button_color=BUTTON_COLOR,
            button_active_color=BUTTON_ACTIVE_COLOR,
            accent_color=ACCENT_COLOR,
            sidebar_color=SIDEBAR_COLOR,
            round_ids=self.round_ids,
            selected_round_id=self.selected_round_id,
            round_dropdown_open=self.round_dropdown.is_open,
            dropdown_overlay=dropdown_overlay,
            playback_playing=self.playback.playing,
            show_sound_effects=self.show_sound_effects,
            sound_toggle_icons=self.sound_toggle_icons,
            cached_frame_count=len(self.round_cache.cache),
            relative_tick=relative_tick,
            relative_seconds=relative_seconds,
            current_frame_number=self.playback.current_frame_index + 1,
            total_frames=len(self.round_cache.frame_ticks),
            speed_options=SPEED_OPTIONS,
            speed_index=self.speed_index,
            speed_label_formatter=self._format_speed_label,
            player_entries=player_entries,
        )
        self.button_rects.update(sidebar.button_rects)
        self.round_item_rects = sidebar.round_item_rects
        self.speed_rects = sidebar.speed_rects

    def _team_num_at_tick(self, player: str, frame_tick: int) -> int | float | None:
        if self.round_cache is None:
            return None
        timeline = self.round_cache.renderer._player_timeline(player)
        if timeline is None:
            return None
        return timeline.team_at(frame_tick)

    def _sidebar_player_label(self, player: str, frame_tick: int) -> str:
        number = format_hud_number(self.round_cache.renderer.player_numbers[player])
        return f"{number}. {player}"

    def _draw_bottom_bar(self, *, content_origin_x: int, content_origin_y: int) -> None:
        if self.round_cache is None:
            return
        progress_ratio = 0.0
        if len(self.round_cache.frame_ticks) > 1:
            progress_ratio = self.playback.current_frame_index / (len(self.round_cache.frame_ticks) - 1)
        timeline_rect = draw_bottom_bar(
            screen=self.screen,
            content_origin_x=content_origin_x,
            content_origin_y=content_origin_y,
            map_width=self.map_width,
            map_height=self.map_height,
            bottom_bar_height=BOTTOM_BAR_HEIGHT,
            small_font=self.small_font,
            accent_color=ACCENT_COLOR,
            muted_text_color=MUTED_TEXT_COLOR,
            speed_label=self._format_speed_label(SPEED_OPTIONS[self.speed_index]),
            tickrate=self.tickrate,
            progress_ratio=progress_ratio,
        )
        self.button_rects["timeline"] = timeline_rect

    def _format_speed_label(self, speed: float) -> str:
        if speed < 1.0:
            return f"1/{int(round(1.0 / speed))}x"
        if float(speed).is_integer():
            return f"{int(speed)}x"
        return f"{speed:g}x"
