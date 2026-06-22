from __future__ import annotations

import math

import pygame

from wall.render.round_pygame_effects import draw_blind_glow, mix_with_white
from wall.viewer.geometry import offset_point
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
) -> None:
    text_color = mix_with_white(color, blind_strength * 0.60)
    shadow_color = mix_with_white((12, 12, 12), blind_strength * 0.18)
    text_surface = font.render(player_label, True, text_color)
    shadow_surface = font.render(player_label, True, shadow_color)
    label_x = int(round(px + 10.0))
    label_y = int(round(py + 10.0))
    text_rect = text_surface.get_rect(midleft=(label_x, label_y))
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        shadow_rect = text_rect.move(dx, dy)
        surface.blit(shadow_surface, shadow_rect)
    surface.blit(text_surface, text_rect)


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
    blind_strength: float,
    draw_carried_bomb_icon,
    frame_tick: int,
) -> None:
    center = (int(round(px)), int(round(py)))
    if blind_strength > 0.0:
        draw_blind_glow(surface, overlay_size[0], overlay_size[1], center, blind_strength)
    pygame.draw.circle(surface, color, center, 8)
    pygame.draw.circle(surface, (0, 0, 0), center, 8, 1)
    number_color = (24, 22, 2) if team_num == 2 else (255, 255, 255)
    number_color = mix_with_white(number_color, blind_strength * 0.45)
    number_surface = player_number_font.render(format_hud_number(player_number), True, number_color)
    rect = number_surface.get_rect(center=(center[0], center[1] - 1))
    surface.blit(number_surface, rect)
    draw_carried_bomb_icon(surface, player, center, frame_tick)
    draw_player_id_label(
        surface=surface,
        font=small_font,
        px=px,
        py=py,
        player_label=player,
        color=id_color,
        blind_strength=blind_strength,
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
