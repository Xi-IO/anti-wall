from __future__ import annotations

import math

import pygame

from wall.render.round_pygame_effects import draw_blind_glow, mix_with_white
from wall.viewer.geometry import offset_point
from wall.viewer.player_palette import player_marker_number_color
from wall.viewer.ui import format_hud_number


def draw_player_id_label(
    *,
    surface: pygame.Surface,
    font: pygame.font.Font,
    px: float,
    py: float,
    player_label: str,
    color: tuple[int, int, int],
    blind_strength: float = 0.0,
    leading_offset_px: float = 10.0,
    vertical_offset_px: float = 10.0,
) -> None:
    text_color = mix_with_white(color, blind_strength * 0.60)
    shadow_color = mix_with_white((12, 12, 12), blind_strength * 0.18)
    text_surface = font.render(player_label, True, text_color)
    shadow_surface = font.render(player_label, True, shadow_color)
    label_x = int(round(px + leading_offset_px))
    label_y = int(round(py + vertical_offset_px))
    text_rect = text_surface.get_rect(midleft=(label_x, label_y))
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        shadow_rect = text_rect.move(dx, dy)
        surface.blit(shadow_surface, shadow_rect)
    surface.blit(text_surface, text_rect)


def draw_player_weapon_icon(
    *,
    surface: pygame.Surface,
    icon: pygame.Surface | None,
    center: tuple[int, int],
) -> None:
    if icon is None:
        return
    icon_center = (center[0] + 15, center[1] + 15)
    icon_rect = icon.get_rect(center=icon_center)
    shadow = icon.copy()
    shadow.fill((16, 16, 16, 120), special_flags=pygame.BLEND_RGBA_MULT)
    surface.blit(shadow, icon_rect.move(1, 1))
    surface.blit(icon, icon_rect)


def _health_arc_color(health: int | None) -> tuple[int, int, int] | None:
    if health is None or health <= 0:
        return None
    ratio = max(0.0, min(1.0, health / 100.0))
    if ratio >= 0.5:
        t = (ratio - 0.5) / 0.5
        return (
            int(round(242 * (1.0 - t) + 110 * t)),
            int(round(196 * (1.0 - t) + 214 * t)),
            int(round(64 * (1.0 - t) + 124 * t)),
        )
    t = ratio / 0.5
    return (
        int(round(220 * (1.0 - t) + 242 * t)),
        int(round(72 * (1.0 - t) + 196 * t)),
        int(round(72 * (1.0 - t) + 64 * t)),
    )


def draw_player_health_arc(
    *,
    surface: pygame.Surface,
    center: tuple[int, int],
    health: int | None,
    blind_strength: float,
) -> None:
    if health is None or health <= 0:
        return
    ratio = max(0.0, min(1.0, health / 100.0))
    if ratio <= 0.0:
        return
    color = _health_arc_color(health)
    if color is None:
        return
    color = mix_with_white(color, blind_strength * 0.35)
    arc_rect = pygame.Rect(0, 0, 34, 34)
    arc_rect.center = center
    max_sweep = math.radians(65)
    start_angle = math.radians(110)
    full_end_angle = start_angle + max_sweep
    current_start_angle = full_end_angle - max_sweep * ratio
    supersample = 4
    hi_size = (arc_rect.width * supersample, arc_rect.height * supersample)
    shadow_hi_surface = pygame.Surface(hi_size, pygame.SRCALPHA)
    shadow_hi_rect = pygame.Rect(supersample, supersample, *hi_size)
    pygame.draw.arc(
        shadow_hi_surface,
        (18, 18, 18, 52),
        shadow_hi_rect,
        start_angle,
        full_end_angle,
        max(1, 3 * supersample),
    )
    shadow_surface = pygame.transform.smoothscale(shadow_hi_surface, arc_rect.size)
    surface.blit(shadow_surface, arc_rect.topleft)
    track_hi_surface = pygame.Surface(hi_size, pygame.SRCALPHA)
    track_hi_rect = pygame.Rect(0, 0, *hi_size)
    pygame.draw.arc(
        track_hi_surface,
        (110, 110, 110, 102),
        track_hi_rect,
        start_angle,
        full_end_angle,
        max(1, 3 * supersample),
    )
    track_surface = pygame.transform.smoothscale(track_hi_surface, arc_rect.size)
    surface.blit(track_surface, arc_rect.topleft)
    hi_surface = pygame.Surface(hi_size, pygame.SRCALPHA)
    hi_rect = pygame.Rect(0, 0, *hi_size)
    pygame.draw.arc(
        hi_surface,
        (*color, 230),
        hi_rect,
        current_start_angle,
        full_end_angle,
        max(1, 3 * supersample),
    )
    arc_surface = pygame.transform.smoothscale(hi_surface, arc_rect.size)
    surface.blit(arc_surface, arc_rect.topleft)


def draw_facing_wedge(
    *,
    surface: pygame.Surface,
    overlay_size: tuple[int, int],
    px: float,
    py: float,
    yaw: float,
    radius: float,
    facing_fov: float,
    color: tuple[int, int, int],
) -> None:
    overlay = pygame.Surface(overlay_size, pygame.SRCALPHA)
    points = [(px, py)]
    step_count = max(6, int(facing_fov / 12))
    for index in range(step_count + 1):
        angle = -yaw - (facing_fov / 2) + (facing_fov * index / step_count)
        radians = math.radians(angle)
        points.append((px + math.cos(radians) * radius, py + math.sin(radians) * radius))
    pygame.draw.polygon(overlay, color + (110,), points)
    surface.blit(overlay, (0, 0))


def draw_death_marker(
    *,
    surface: pygame.Surface,
    px: float,
    py: float,
    color: tuple[int, int, int],
) -> None:
    size = 5
    stroke_width = 2
    shadow_color = (18, 18, 18)
    shadow_offset = 1
    points_a = [
        (int(round(px - size)), int(round(py - size))),
        (int(round(px)), int(round(py))),
        (int(round(px + size)), int(round(py + size))),
    ]
    points_b = [
        (int(round(px - size)), int(round(py + size))),
        (int(round(px)), int(round(py))),
        (int(round(px + size)), int(round(py - size))),
    ]
    shadow_points_a = [(x + shadow_offset, y + shadow_offset) for x, y in points_a]
    shadow_points_b = [(x + shadow_offset, y + shadow_offset) for x, y in points_b]
    pygame.draw.lines(surface, shadow_color, False, shadow_points_a, stroke_width + 1)
    pygame.draw.lines(surface, shadow_color, False, shadow_points_b, stroke_width + 1)
    pygame.draw.lines(surface, color, False, points_a, stroke_width)
    pygame.draw.lines(surface, color, False, points_b, stroke_width)


def draw_player(
    *,
    surface: pygame.Surface,
    overlay_size: tuple[int, int],
    player_number_font: pygame.font.Font,
    small_font: pygame.font.Font,
    player_number: int,
    px: float,
    py: float,
    player: str,
    color: tuple[int, int, int],
    id_color: tuple[int, int, int],
    team_num: int | float | None,
    health: int | None,
    blind_strength: float,
    draw_carried_bomb_icon,
    draw_defuser_icon,
    frame_tick: int,
    weapon_icon: pygame.Surface | None,
) -> None:
    center = (int(round(px)), int(round(py)))
    if blind_strength > 0.0:
        draw_blind_glow(surface, overlay_size[0], overlay_size[1], center, blind_strength)
    draw_player_health_arc(surface=surface, center=center, health=health, blind_strength=blind_strength)
    pygame.draw.circle(surface, color, center, 8)
    pygame.draw.circle(surface, (0, 0, 0), center, 8, 1)
    number_color = player_marker_number_color(team_num)
    number_color = mix_with_white(number_color, blind_strength * 0.45)
    number_surface = player_number_font.render(format_hud_number(player_number), True, number_color)
    rect = number_surface.get_rect(center=(center[0], center[1] - 1))
    surface.blit(number_surface, rect)
    draw_carried_bomb_icon(surface, player, center, frame_tick)
    draw_defuser_icon(surface, player, center, frame_tick)
    draw_player_weapon_icon(surface=surface, icon=weapon_icon, center=center)
    draw_player_id_label(
        surface=surface,
        font=small_font,
        px=px,
        py=py,
        player_label=player,
        color=id_color,
        blind_strength=blind_strength,
        leading_offset_px=14.0,
        vertical_offset_px=-1.0,
    )


def draw_tracer_line(
    *,
    surface: pygame.Surface,
    overlay_size: tuple[int, int],
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    tracer_color: tuple[int, int, int, int],
) -> None:
    overlay = pygame.Surface(overlay_size, pygame.SRCALPHA)
    pygame.draw.line(overlay, tracer_color, (start_x, start_y), (end_x, end_y), 2)
    surface.blit(overlay, (0, 0))


def draw_muzzle_flash(
    *,
    surface: pygame.Surface,
    muzzle_flash_sprite: pygame.Surface | None,
    muzzle_flash_anchor: tuple[float, float] | None,
    muzzle_px: float,
    muzzle_py: float,
    yaw: float,
    fade: float,
    scale_reference_px: float,
) -> None:
    if muzzle_flash_sprite is None or muzzle_flash_anchor is None:
        return
    sprite = muzzle_flash_sprite.copy()
    sprite_width, sprite_height = sprite.get_size()
    scale = max(0.12, scale_reference_px / sprite_width)
    sprite = pygame.transform.smoothscale(sprite, (max(1, int(sprite_width * scale)), max(1, int(sprite_height * scale))))
    alpha = max(0, min(255, int(255 * fade)))
    sprite.set_alpha(alpha)

    scaled_anchor_x = muzzle_flash_anchor[0] * (sprite.get_width() / sprite_width)
    scaled_anchor_y = muzzle_flash_anchor[1] * (sprite.get_height() / sprite_height)
    padded_size = max(sprite.get_width(), sprite.get_height()) * 4
    centered = pygame.Surface((padded_size, padded_size), pygame.SRCALPHA)
    center_x = padded_size / 2
    center_y = padded_size / 2
    centered.blit(sprite, (center_x - scaled_anchor_x, center_y - scaled_anchor_y))
    rotated = pygame.transform.rotozoom(centered, yaw, 1.0)
    rect = rotated.get_rect(center=(int(round(muzzle_px)), int(round(muzzle_py))))
    surface.blit(rotated, rect)
