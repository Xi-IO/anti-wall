from __future__ import annotations

import pygame

from wall.domain.sound import SoundPresentationConfig, SoundTimeline


def get_sound_ring_surface(
    *,
    cache: dict[tuple[int, int, tuple[int, int, int], int, float], pygame.Surface],
    radius_px: int,
    color: tuple[int, int, int],
    alpha: int,
    ring_width: int,
    fill_alpha_mult: float,
    sound_fill_alpha: int,
    sound_base_alpha: int,
) -> pygame.Surface:
    key = (radius_px, alpha, color, ring_width, round(fill_alpha_mult, 3))
    cached = cache.get(key)
    if cached is not None:
        return cached
    diameter = max(4, radius_px * 2 + ring_width * 4)
    surface = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
    center = diameter // 2
    fill_alpha = max(0, min(255, int(round(alpha * (sound_fill_alpha / max(1, sound_base_alpha)) * fill_alpha_mult))))
    if fill_alpha > 0:
        pygame.draw.circle(surface, color + (fill_alpha,), (center, center), radius_px)
    pygame.draw.circle(surface, color + (alpha,), (center, center), radius_px, ring_width)
    inner_radius = max(0, radius_px - ring_width - 1)
    if inner_radius > 0:
        pygame.draw.circle(surface, (255, 255, 255, min(60, alpha // 3)), (center, center), inner_radius, 1)
    cache[key] = surface
    return surface


def draw_sound_cap_label(
    *,
    surface: pygame.Surface,
    font: pygame.font.Font,
    px: float,
    py: float,
    radius_px: int,
    label: str,
    color: tuple[int, int, int],
    alpha: int,
    sound_label_distance_px: int,
) -> None:
    text = font.render(label, True, color)
    shadow = font.render(label, True, (12, 12, 12))
    text.set_alpha(alpha)
    shadow.set_alpha(max(0, min(255, alpha)))
    rect = text.get_rect(midleft=(int(round(px + radius_px + sound_label_distance_px)), int(round(py))))
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        surface.blit(shadow, rect.move(dx, dy))
    surface.blit(text, rect)


def draw_sound_events(
    *,
    surface: pygame.Surface,
    frame_tick: int,
    width: int,
    height: int,
    font: pygame.font.Font,
    sound_timeline: SoundTimeline,
    world_to_px,
    world_dist_to_px,
    presentation: SoundPresentationConfig,
    ring_cache: dict[tuple[int, int, tuple[int, int, int], int, float], pygame.Surface],
    sound_fill_alpha: int,
    sound_base_alpha: int,
    sound_label_distance_px: int,
) -> None:
    if not sound_timeline.has_events():
        return
    active = sound_timeline.present_events_at(
        frame_tick,
        world_to_px=world_to_px,
        world_dist_to_px=world_dist_to_px,
        viewport_width=width,
        viewport_height=height,
        presentation=presentation,
    )
    if not active:
        return
    overlay = pygame.Surface((width, height), pygame.SRCALPHA)
    for sound in active:
        px, py = sound.center_px
        color = sound.color
        ring = get_sound_ring_surface(
            cache=ring_cache,
            radius_px=sound.radius_px,
            color=color,
            alpha=sound.alpha,
            ring_width=sound.ring_width,
            fill_alpha_mult=sound.fill_alpha_mult,
            sound_fill_alpha=sound_fill_alpha,
            sound_base_alpha=sound_base_alpha,
        )
        rect = ring.get_rect(center=(int(round(px)), int(round(py))))
        overlay.blit(ring, rect)
        if sound.center_marker_radius > 0:
            pygame.draw.circle(
                overlay,
                color + (min(sound.center_marker_alpha_cap, sound.alpha),),
                (int(round(px)), int(round(py))),
                sound.center_marker_radius,
            )
        if sound.is_capped:
            draw_sound_cap_label(
                surface=overlay,
                font=font,
                px=px,
                py=py,
                radius_px=sound.radius_px,
                label=sound.label or "MAP",
                color=color,
                alpha=sound.alpha,
                sound_label_distance_px=sound_label_distance_px,
            )
    surface.blit(overlay, (0, 0))
