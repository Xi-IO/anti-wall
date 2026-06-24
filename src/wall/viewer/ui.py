from __future__ import annotations

from dataclasses import dataclass

import pygame

from wall.viewer.layout import RoundDropdownOverlayLayout


@dataclass(frozen=True)
class SidebarPlayerEntry:
    label: str
    color: tuple[int, int, int]


@dataclass(frozen=True)
class SidebarRenderResult:
    button_rects: dict[str, pygame.Rect]
    round_item_rects: dict[int, pygame.Rect]
    speed_rects: dict[float, pygame.Rect]


def format_hud_number(number: int) -> str:
    return "0" if number == 10 else str(number)


def tint_icon(base: pygame.Surface, color: tuple[int, int, int]) -> pygame.Surface:
    tinted = base.copy()
    tinted.fill((*color, 255), special_flags=pygame.BLEND_RGBA_MULT)
    return tinted


def draw_media_icon(
    screen: pygame.Surface,
    rect: pygame.Rect,
    kind: str,
    color: tuple[int, int, int],
    sound_toggle_icons: dict[str, pygame.Surface],
) -> None:
    cx, cy = rect.center
    icon_height = 12
    half_height = icon_height // 2
    if kind == "prev":
        group_left = cx - 6
        bar = pygame.Rect(group_left, cy - half_height, 2, icon_height)
        pygame.draw.rect(screen, color, bar, border_radius=1)
        points = [(group_left + 4, cy), (group_left + 11, cy - half_height), (group_left + 11, cy + half_height)]
        pygame.draw.polygon(screen, color, points)
    elif kind == "next":
        group_left = cx - 6
        bar = pygame.Rect(group_left + 9, cy - half_height, 2, icon_height)
        pygame.draw.rect(screen, color, bar, border_radius=1)
        points = [(group_left, cy - half_height), (group_left, cy + half_height), (group_left + 7, cy)]
        pygame.draw.polygon(screen, color, points)
    elif kind == "pause":
        left_bar = pygame.Rect(cx - 6, cy - half_height, 4, icon_height)
        right_bar = pygame.Rect(cx + 2, cy - half_height, 4, icon_height)
        pygame.draw.rect(screen, color, left_bar, border_radius=1)
        pygame.draw.rect(screen, color, right_bar, border_radius=1)
    elif kind in {"sound_on", "sound_off"}:
        icon = sound_toggle_icons.get(kind)
        if icon is not None:
            tinted = tint_icon(icon, color)
            icon_rect = tinted.get_rect(center=rect.center)
            screen.blit(tinted, icon_rect)
        else:
            body_rect = pygame.Rect(cx - 12, cy - 6, 6, 12)
            pygame.draw.rect(screen, color, body_rect, border_radius=2)
            cone_points = [(cx - 6, cy - 7), (cx + 3, cy - 13), (cx + 3, cy + 13), (cx - 6, cy + 7)]
            pygame.draw.polygon(screen, color, cone_points, width=2)
            if kind == "sound_on":
                for radius in (8, 13):
                    arc_rect = pygame.Rect(cx - 1, cy - radius, radius * 2, radius * 2)
                    pygame.draw.arc(screen, color, arc_rect, -0.75, 0.75, 2)
            else:
                inner_arc = pygame.Rect(cx - 1, cy - 8, 16, 16)
                outer_arc = pygame.Rect(cx - 1, cy - 13, 26, 26)
                pygame.draw.arc(screen, color, inner_arc, -0.75, 0.75, 2)
                pygame.draw.arc(screen, color, outer_arc, -0.75, 0.75, 2)
                pygame.draw.line(screen, color, (cx - 7, cy + 10), (cx + 15, cy - 12), 3)
    else:
        points = [(cx + 5, cy), (cx - 4, cy - half_height), (cx - 4, cy + half_height)]
        pygame.draw.polygon(screen, color, points)


def speed_button_rects(
    *,
    origin_x: int,
    origin_y: int,
    speed_options: list[float],
) -> dict[float, pygame.Rect]:
    rects: dict[float, pygame.Rect] = {}
    for index, speed in enumerate(speed_options):
        col = index % 3
        row = index // 3
        rects[speed] = pygame.Rect(origin_x + col * 84, origin_y + row * 36, 74, 28)
    return rects


def draw_round_dropdown_overlay(
    *,
    screen: pygame.Surface,
    small_font: pygame.font.Font,
    overlay: RoundDropdownOverlayLayout,
    text_color: tuple[int, int, int],
    button_color: tuple[int, int, int],
    accent_color: tuple[int, int, int],
    sidebar_color: tuple[int, int, int],
) -> None:
    pygame.draw.rect(screen, sidebar_color, overlay.list_rect, border_radius=6)
    pygame.draw.rect(screen, (66, 66, 66), overlay.list_rect, 1, border_radius=6)
    for item in overlay.items:
        color = accent_color if item.is_selected else button_color
        pygame.draw.rect(screen, color, item.rect, border_radius=4)
        label = small_font.render(f"Round {item.round_id}", True, text_color)
        screen.blit(label, (item.rect.x + 10, item.rect.y + 5))
    if overlay.scroll is None:
        return
    pygame.draw.rect(screen, button_color, overlay.scroll.up_rect, border_radius=4)
    pygame.draw.rect(screen, button_color, overlay.scroll.down_rect, border_radius=4)
    pygame.draw.rect(screen, (58, 58, 58), overlay.scroll.track_rect, border_radius=4)
    up_label = small_font.render("^", True, text_color)
    down_label = small_font.render("v", True, text_color)
    screen.blit(up_label, up_label.get_rect(center=overlay.scroll.up_rect.center))
    screen.blit(down_label, down_label.get_rect(center=overlay.scroll.down_rect.center))
    pygame.draw.rect(screen, accent_color, overlay.scroll.thumb_rect, border_radius=4)


def draw_sidebar(
    *,
    screen: pygame.Surface,
    content_origin_x: int,
    content_origin_y: int,
    map_width: int,
    map_height: int,
    sidebar_width: int,
    bottom_bar_height: int,
    font: pygame.font.Font,
    small_font: pygame.font.Font,
    text_color: tuple[int, int, int],
    muted_text_color: tuple[int, int, int],
    button_color: tuple[int, int, int],
    button_active_color: tuple[int, int, int],
    accent_color: tuple[int, int, int],
    sidebar_color: tuple[int, int, int],
    round_ids: list[int],
    selected_round_id: int,
    round_dropdown_open: bool,
    dropdown_overlay: RoundDropdownOverlayLayout | None,
    playback_playing: bool,
    show_sound_effects: bool,
    sound_toggle_icons: dict[str, pygame.Surface],
    cached_frame_count: int,
    relative_tick: int,
    relative_seconds: float,
    current_frame_number: int,
    total_frames: int,
    speed_options: list[float],
    speed_index: int,
    speed_label_formatter,
    player_entries: list[SidebarPlayerEntry],
) -> SidebarRenderResult:
    sidebar_rect = pygame.Rect(content_origin_x + map_width, content_origin_y, sidebar_width, map_height + bottom_bar_height)
    pygame.draw.rect(screen, sidebar_color, sidebar_rect)
    button_rects: dict[str, pygame.Rect] = {}
    round_item_rects: dict[int, pygame.Rect] = {}
    speed_rects: dict[float, pygame.Rect] = {}
    x = content_origin_x + map_width + 16
    y = content_origin_y + 16

    title = font.render("Controls", True, text_color)
    screen.blit(title, (x, y))
    y += 32

    round_title = small_font.render("Round", True, muted_text_color)
    screen.blit(round_title, (x, y))
    y += 22
    dropdown_rect = pygame.Rect(x, y, sidebar_width - 32, 32)
    button_rects["round_dropdown"] = dropdown_rect
    pygame.draw.rect(screen, button_active_color if round_dropdown_open else button_color, dropdown_rect, border_radius=4)
    dropdown_label = small_font.render(f"Round {selected_round_id}", True, text_color)
    screen.blit(dropdown_label, (dropdown_rect.x + 10, dropdown_rect.y + 7))
    arrow = "^" if round_dropdown_open else "v"
    arrow_label = small_font.render(arrow, True, text_color)
    screen.blit(arrow_label, (dropdown_rect.right - 22, dropdown_rect.y + 7))
    y += 40
    if dropdown_overlay is not None:
        for item in dropdown_overlay.items:
            round_item_rects[item.round_id] = item.rect
        if dropdown_overlay.scroll is not None:
            button_rects["round_scroll_up"] = dropdown_overlay.scroll.up_rect
            button_rects["round_scroll_down"] = dropdown_overlay.scroll.down_rect

    button_gap = 8
    button_width = (sidebar_width - 32 - button_gap * 3) // 4
    prev_rect = pygame.Rect(x, y, button_width, 32)
    play_rect = pygame.Rect(prev_rect.right + button_gap, y, button_width, 32)
    next_rect = pygame.Rect(play_rect.right + button_gap, y, button_width, 32)
    sound_rect = pygame.Rect(next_rect.right + button_gap, y, button_width, 32)
    button_rects["prev_round"] = prev_rect
    button_rects["play"] = play_rect
    button_rects["next_round"] = next_rect
    button_rects["sound_toggle"] = sound_rect
    prev_active = selected_round_id != round_ids[0]
    next_active = selected_round_id != round_ids[-1]
    icon_color = (214, 214, 214)
    inactive_icon = (112, 112, 112)
    pygame.draw.rect(screen, button_color if prev_active else (42, 42, 42), prev_rect, border_radius=4)
    pygame.draw.rect(screen, button_active_color if playback_playing else button_color, play_rect, border_radius=4)
    pygame.draw.rect(screen, button_color if next_active else (42, 42, 42), next_rect, border_radius=4)
    pygame.draw.rect(screen, button_active_color if not show_sound_effects else button_color, sound_rect, border_radius=4)
    draw_media_icon(screen, prev_rect, "prev", icon_color if prev_active else inactive_icon, sound_toggle_icons)
    draw_media_icon(screen, play_rect, "pause" if playback_playing else "play", icon_color, sound_toggle_icons)
    draw_media_icon(screen, next_rect, "next", icon_color if next_active else inactive_icon, sound_toggle_icons)
    draw_media_icon(screen, sound_rect, "sound_on" if show_sound_effects else "sound_off", icon_color, sound_toggle_icons)
    y += 48

    progress_text = small_font.render(f"Cached {cached_frame_count} frames", True, muted_text_color)
    screen.blit(progress_text, (x, y))
    y += 28

    tick_text = small_font.render(
        f"Round tick {relative_tick} | {relative_seconds:.2f}s | frame {current_frame_number}/{total_frames}",
        True,
        muted_text_color,
    )
    screen.blit(tick_text, (x, y))
    y += 36

    speed_title = font.render("Speed", True, text_color)
    screen.blit(speed_title, (x, y))
    y += 34
    speed_rects = speed_button_rects(origin_x=x, origin_y=y, speed_options=speed_options)
    for speed_value, rect in speed_rects.items():
        active = speed_value == speed_options[speed_index]
        pygame.draw.rect(screen, button_active_color if active else button_color, rect, border_radius=4)
        label = small_font.render(speed_label_formatter(speed_value), True, text_color)
        screen.blit(label, label.get_rect(center=rect.center))
    if speed_rects:
        y = max(rect.bottom for rect in speed_rects.values()) + 24

    legend_title = font.render("Players", True, text_color)
    screen.blit(legend_title, (x, y))
    y += 30
    for player in player_entries:
        pygame.draw.rect(screen, player.color, (x, y + 4, 12, 12))
        label = small_font.render(player.label, True, text_color)
        screen.blit(label, (x + 20, y))
        y += 22

    if dropdown_overlay is not None:
        draw_round_dropdown_overlay(
            screen=screen,
            small_font=small_font,
            overlay=dropdown_overlay,
            text_color=text_color,
            button_color=button_color,
            accent_color=accent_color,
            sidebar_color=sidebar_color,
        )
    return SidebarRenderResult(
        button_rects=button_rects,
        round_item_rects=round_item_rects,
        speed_rects=speed_rects,
    )


def draw_bottom_bar(
    *,
    screen: pygame.Surface,
    content_origin_x: int,
    content_origin_y: int,
    map_width: int,
    map_height: int,
    bottom_bar_height: int,
    small_font: pygame.font.Font,
    accent_color: tuple[int, int, int],
    muted_text_color: tuple[int, int, int],
    speed_label: str,
    tickrate: float,
    progress_ratio: float,
) -> pygame.Rect:
    bar_rect = pygame.Rect(content_origin_x, content_origin_y + map_height, map_width, bottom_bar_height)
    pygame.draw.rect(screen, (24, 24, 24), bar_rect)
    timeline_rect = pygame.Rect(content_origin_x + 16, content_origin_y + map_height + 20, map_width - 32, 16)
    pygame.draw.rect(screen, (70, 70, 70), timeline_rect, border_radius=8)
    fill_width = int(round(timeline_rect.width * progress_ratio))
    pygame.draw.rect(
        screen,
        accent_color,
        pygame.Rect(timeline_rect.x, timeline_rect.y, max(8, fill_width), timeline_rect.height),
        border_radius=8,
    )
    speed_text = small_font.render(f"{speed_label} | tickrate {tickrate:g}", True, muted_text_color)
    screen.blit(speed_text, (content_origin_x + 16, content_origin_y + map_height + 42))
    return timeline_rect
