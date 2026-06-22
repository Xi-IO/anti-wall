from __future__ import annotations

from dataclasses import dataclass

import pygame

from wall.viewer.state import RoundDropdownState


@dataclass(frozen=True)
class RoundDropdownItemLayout:
    round_id: int
    rect: pygame.Rect
    is_selected: bool


@dataclass(frozen=True)
class RoundDropdownScrollLayout:
    up_rect: pygame.Rect
    down_rect: pygame.Rect
    track_rect: pygame.Rect
    thumb_rect: pygame.Rect


@dataclass(frozen=True)
class RoundDropdownOverlayLayout:
    list_rect: pygame.Rect
    items: list[RoundDropdownItemLayout]
    scroll: RoundDropdownScrollLayout | None


def build_round_dropdown_overlay(
    *,
    origin_x: int,
    origin_y: int,
    width: int,
    round_ids: list[int],
    selected_round_id: int,
    dropdown: RoundDropdownState,
) -> RoundDropdownOverlayLayout | None:
    if not dropdown.is_open:
        dropdown.reset_layout()
        return None
    dropdown.clamp_start(len(round_ids))
    visible_rounds = dropdown.visible_round_ids(round_ids)
    list_top = origin_y
    list_width = width
    scroll_enabled = len(round_ids) > dropdown.visible_count
    arrow_width = 22 if scroll_enabled else 0
    item_width = list_width - (arrow_width + 6 if scroll_enabled else 0)
    overlay_bottom = list_top
    items: list[RoundDropdownItemLayout] = []
    for round_id in visible_rounds:
        rect = pygame.Rect(origin_x, overlay_bottom, item_width, 26)
        items.append(
            RoundDropdownItemLayout(
                round_id=round_id,
                rect=rect,
                is_selected=round_id == selected_round_id,
            )
        )
        overlay_bottom += 30
    list_height = overlay_bottom - list_top
    list_rect = pygame.Rect(origin_x - 4, list_top - 4, list_width + 8, list_height + 8)
    dropdown.area_rect = pygame.Rect(origin_x, list_top, list_width, list_height)
    dropdown.track_rect = pygame.Rect(0, 0, 0, 0)
    dropdown.thumb_rect = pygame.Rect(0, 0, 0, 0)
    scroll_layout: RoundDropdownScrollLayout | None = None
    if scroll_enabled:
        track_x = origin_x + item_width + 6
        up_rect = pygame.Rect(track_x, list_top, arrow_width, 24)
        down_rect = pygame.Rect(track_x, list_top + list_height - 24, arrow_width, 24)
        track_rect = pygame.Rect(track_x, up_rect.bottom + 4, arrow_width, max(8, list_height - 56))
        dropdown.track_rect = track_rect
        visible_count = dropdown.visible_count
        thumb_height = max(20, int(round(track_rect.height * visible_count / len(round_ids))))
        max_start = max(1, len(round_ids) - visible_count)
        thumb_travel = max(0, track_rect.height - thumb_height)
        thumb_offset = int(round(thumb_travel * (dropdown.start_index / max_start)))
        thumb_rect = pygame.Rect(track_rect.x + 3, track_rect.y + thumb_offset, track_rect.width - 6, thumb_height)
        dropdown.thumb_rect = thumb_rect
        scroll_layout = RoundDropdownScrollLayout(
            up_rect=up_rect,
            down_rect=down_rect,
            track_rect=track_rect,
            thumb_rect=thumb_rect,
        )
    return RoundDropdownOverlayLayout(
        list_rect=list_rect,
        items=items,
        scroll=scroll_layout,
    )
