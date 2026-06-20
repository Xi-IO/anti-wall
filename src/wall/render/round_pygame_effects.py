from __future__ import annotations

import math
from pathlib import Path
from typing import Callable

import pygame

from wall.paths import resolve_asset_path


def mix_with_white(color: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    amount = max(0.0, min(1.0, amount))
    return tuple(
        int(round((1.0 - amount) * channel + amount * 255))
        for channel in color
    )


def draw_blind_glow(
    surface: pygame.Surface,
    width: int,
    height: int,
    center: tuple[int, int],
    strength: float,
) -> None:
    overlay = pygame.Surface((width, height), pygame.SRCALPHA)
    glow_radius = max(13, int(round(13 + 6 * strength)))
    core_radius = max(10, int(round(9 + 3 * strength)))
    glow_alpha = int(round(26 + 70 * strength))
    core_alpha = int(round(18 + 42 * strength))
    pygame.draw.circle(overlay, (255, 255, 255, glow_alpha), center, glow_radius)
    pygame.draw.circle(overlay, (255, 255, 255, core_alpha), center, core_radius)
    surface.blit(overlay, (0, 0))


def draw_flash_eye(
    surface: pygame.Surface,
    width: int,
    height: int,
    world_dist_to_px: Callable[[float], float],
    px: float,
    py: float,
    fade: float,
) -> None:
    outer_radius = max(12, int(round(world_dist_to_px(176.0))))
    mid_radius = max(10, int(round(outer_radius * 0.72)))
    inner_radius = max(8, int(round(outer_radius * 0.38)))
    center = (int(round(px)), int(round(py)))

    overlay = pygame.Surface((width, height), pygame.SRCALPHA)
    pygame.draw.circle(overlay, (255, 255, 255, int(round(92 * fade))), center, outer_radius)
    pygame.draw.circle(overlay, (255, 255, 255, int(round(128 * fade))), center, mid_radius)
    pygame.draw.circle(overlay, (255, 255, 255, int(round(166 * fade))), center, inner_radius)

    eye_width = max(30, int(round(inner_radius * 1.46)))
    eye_height = max(14, int(round(inner_radius * 0.66)))
    eye_outline_width = max(2, int(round(eye_height * 0.22)))
    eye_points = _build_eye_outline_points(center, eye_width, eye_height)
    pygame.draw.polygon(overlay, (255, 255, 255, int(round(255 * fade))), eye_points, width=eye_outline_width)

    pupil_radius = max(6, int(round(eye_height * 0.42)))
    pygame.draw.circle(
        overlay,
        (255, 255, 255, int(round(255 * fade))),
        center,
        pupil_radius,
        width=max(2, pupil_radius // 2),
    )

    spike_alpha = int(round(188 * fade))
    spike_gap = max(5, int(round(inner_radius * 0.15)))
    center_spike_height = max(9, int(round(inner_radius * 0.66)))
    side_spike_height = max(7, int(round(inner_radius * 0.52)))
    center_spike_half_width = max(6, int(round(inner_radius * 0.26)))
    side_spike_half_width = max(7, int(round(inner_radius * 0.27)))
    spike_color = (255, 255, 255, spike_alpha)

    def build_spike(anchor_x: float, anchor_y: float, height_px: float, half_width: float, angle_deg: float) -> list[tuple[int, int]]:
        angle = math.radians(angle_deg)
        normal_x = math.cos(angle)
        normal_y = math.sin(angle)
        tangent_x = -normal_y
        tangent_y = normal_x
        tip_x = anchor_x + normal_x * height_px
        tip_y = anchor_y + normal_y * height_px
        left_x = anchor_x - tangent_x * half_width
        left_y = anchor_y - tangent_y * half_width
        right_x = anchor_x + tangent_x * half_width
        right_y = anchor_y + tangent_y * half_width
        return [
            (int(round(tip_x)), int(round(tip_y))),
            (int(round(left_x)), int(round(left_y))),
            (int(round(right_x)), int(round(right_y))),
        ]

    center_anchor = (center[0], center[1] - eye_height / 2 - spike_gap)
    side_anchor_y = center[1] - eye_height / 2 - spike_gap + max(3, int(round(eye_height * 0.18)))
    side_offset_x = max(14, int(round(eye_width * 0.32)))

    left_spike = build_spike(center[0] - side_offset_x, side_anchor_y, side_spike_height, side_spike_half_width, -124)
    center_spike = build_spike(center_anchor[0], center_anchor[1], center_spike_height, center_spike_half_width, -90)
    right_spike = build_spike(center[0] + side_offset_x, side_anchor_y, side_spike_height, side_spike_half_width, -56)

    pygame.draw.polygon(overlay, spike_color, left_spike)
    pygame.draw.polygon(overlay, spike_color, center_spike)
    pygame.draw.polygon(overlay, spike_color, right_spike)

    surface.blit(overlay, (0, 0))


def _build_eye_outline_points(
    center: tuple[int, int],
    eye_width: int,
    eye_height: int,
) -> list[tuple[int, int]]:
    cx, cy = center
    half_width = eye_width / 2
    half_height = eye_height / 2
    steps = 20
    top_points: list[tuple[int, int]] = []
    bottom_points: list[tuple[int, int]] = []
    for index in range(steps + 1):
        t = index / steps
        x = cx - half_width + eye_width * t
        curve = math.sin(math.pi * t)
        y_top = cy - half_height * curve
        y_bottom = cy + half_height * curve
        top_points.append((int(round(x)), int(round(y_top))))
        bottom_points.append((int(round(x)), int(round(y_bottom))))
    return top_points + list(reversed(bottom_points))


def load_flash_eye_texture() -> pygame.Surface | None:
    texture_path = resolve_asset_path("flash_eye.png")
    if not texture_path.exists():
        return None
    try:
        return pygame.image.load(str(texture_path)).convert_alpha()
    except pygame.error:
        return None


def draw_flash_eye_texture(
    surface: pygame.Surface,
    texture: pygame.Surface,
    world_dist_to_px: Callable[[float], float],
    px: float,
    py: float,
    fade: float,
) -> None:
    outer_radius = max(12, int(round(world_dist_to_px(176.0))))
    target_size = max(outer_radius * 2, 24)
    scaled = pygame.transform.smoothscale(texture, (target_size, target_size)).copy()
    scaled.set_alpha(max(0, min(255, int(round(255 * fade)))))
    rect = scaled.get_rect(center=(int(round(px)), int(round(py))))
    surface.blit(scaled, rect)
