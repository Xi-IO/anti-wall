from __future__ import annotations

import pygame

from wall.domain.bomb import BombTimeline, DefuseAttemptVisual
from wall.viewer.geometry import build_arc_points, build_arc_segment_points


def draw_defuse_progress(
    *,
    surface: pygame.Surface,
    overlay_size: tuple[int, int],
    center: tuple[int, int],
    visual: DefuseAttemptVisual | None,
    defuse_bar_glow: tuple[int, int, int, int],
    defuse_bar_shadow: tuple[int, int, int, int],
    defuse_bar_color: tuple[int, int, int],
) -> None:
    if visual is None:
        return
    progress = float(visual.progress)
    alpha_scale = float(visual.alpha_scale)
    shake = float(visual.shake)
    status = str(visual.status)
    if progress <= 0.0 and status != "aborted":
        return
    bar_width = 38
    bar_height = 7
    left = int(round(center[0] - bar_width / 2 + shake))
    top = int(round(center[1] - 18))
    shadow_rect = pygame.Rect(left + 1, top + 1, bar_width, bar_height)
    bg_rect = pygame.Rect(left, top, bar_width, bar_height)
    fill_width = max(0, min(bar_width, int(round(bar_width * progress))))
    fill_rect = pygame.Rect(left, top, fill_width, bar_height)
    overlay = pygame.Surface(overlay_size, pygame.SRCALPHA)
    shadow_alpha = int(round(180 * alpha_scale))
    fill_alpha = int(round(230 * alpha_scale))
    glow_alpha = int(round(110 * alpha_scale))
    glow_rect = pygame.Rect(left - 2, top - 2, bar_width + 4, bar_height + 4)
    pygame.draw.rect(overlay, defuse_bar_glow[:3] + (glow_alpha,), glow_rect, border_radius=5)
    pygame.draw.rect(overlay, defuse_bar_shadow[:3] + (shadow_alpha,), shadow_rect, border_radius=3)
    pygame.draw.rect(overlay, (16, 16, 16, int(round(195 * alpha_scale))), bg_rect, border_radius=3)
    if fill_width > 0:
        pygame.draw.rect(overlay, defuse_bar_color + (fill_alpha,), fill_rect, border_radius=3)
        highlight_width = max(1, fill_width - 2)
        if highlight_width > 0:
            highlight_rect = pygame.Rect(left + 1, top + 1, highlight_width, max(1, bar_height // 2))
            pygame.draw.rect(overlay, (220, 255, 210, int(round(120 * alpha_scale))), highlight_rect, border_radius=2)
    pygame.draw.rect(overlay, (12, 12, 12, int(round(230 * alpha_scale))), bg_rect, width=1, border_radius=3)
    surface.blit(overlay, (0, 0))


def draw_planted_bomb_timer(
    *,
    surface: pygame.Surface,
    overlay_size: tuple[int, int],
    center: tuple[int, int],
    progress: float | None,
    icon: pygame.Surface | None,
) -> None:
    if progress is None:
        return
    remaining_fraction = max(0.0, 1.0 - progress)
    if remaining_fraction <= 0.0:
        return

    icon_radius = max(6, (icon.get_width() // 2) if icon is not None else 6)
    ring_radius = icon_radius + 7
    ring_width = 3
    shadow_points = build_arc_points(center[0] + 1, center[1] + 1, ring_radius, remaining_fraction)
    ring_points = build_arc_points(center[0], center[1], ring_radius, remaining_fraction)
    overlay = pygame.Surface(overlay_size, pygame.SRCALPHA)
    if len(shadow_points) >= 2:
        pygame.draw.lines(overlay, (18, 18, 18, 170), False, shadow_points, ring_width + 1)
    if len(ring_points) >= 2:
        pygame.draw.lines(overlay, (220, 72, 72, 230), False, ring_points, ring_width)
    surface.blit(overlay, (0, 0))


def draw_plant_attempts(
    *,
    surface: pygame.Surface,
    overlay_size: tuple[int, int],
    frame_tick: int,
    tickrate: float,
    planted_duration_seconds: float,
    defuse_shake_ticks: int,
    bomb_tracker: BombTimeline,
    world_to_px,
    c4_icons: dict[str, pygame.Surface],
) -> None:
    total_ticks = max(1, int(round(tickrate * planted_duration_seconds)))
    visual = bomb_tracker.render_state_at(
        frame_tick,
        planted_total_ticks=total_ticks,
        abort_shake_ticks=defuse_shake_ticks,
    ).plant_visual
    if visual is None:
        return
    overlay = pygame.Surface(overlay_size, pygame.SRCALPHA)
    icon = c4_icons.get("carried") or c4_icons.get("planted")
    icon_radius = max(6, (icon.get_width() // 2) if icon is not None else 6)
    ring_radius = max(icon_radius + 14, 22)
    ring_width = 4
    progress_color = (214, 126, 54)
    track_color = (70, 42, 22)
    fade = float(visual.fade)
    center_x, center_y = world_to_px(float(visual.center_x), float(visual.center_y))
    start_angle = float(visual.start_angle)
    end_angle = float(visual.end_angle)
    center = (int(round(center_x)), int(round(center_y)))
    if icon is not None:
        icon_alpha = max(0, min(255, int(round(255 * fade))))
        icon_surface = icon.copy()
        icon_surface.set_alpha(icon_alpha)
        shadow = icon_surface.copy()
        shadow.fill((18, 18, 18, 170), special_flags=pygame.BLEND_RGBA_MULT)
        overlay.blit(shadow, shadow.get_rect(center=(center[0] + 1, center[1] + 1)))
        overlay.blit(icon_surface, icon_surface.get_rect(center=center))
    track_alpha = max(0, min(255, int(round(130 * fade))))
    pygame.draw.circle(overlay, track_color + (track_alpha,), center, ring_radius, ring_width)
    shadow_points = build_arc_segment_points(center[0] + 1, center[1] + 1, ring_radius, start_angle, end_angle)
    ring_points = build_arc_segment_points(center[0], center[1], ring_radius, start_angle, end_angle)
    shadow_alpha = max(0, min(255, int(round(170 * fade))))
    ring_alpha = max(0, min(255, int(round(220 * fade))))
    if len(shadow_points) >= 2:
        pygame.draw.lines(overlay, (18, 18, 18, shadow_alpha), False, shadow_points, ring_width + 1)
    if len(ring_points) >= 2:
        pygame.draw.lines(overlay, progress_color + (ring_alpha,), False, ring_points, ring_width)
    surface.blit(overlay, (0, 0))


def draw_ground_bomb(
    *,
    surface: pygame.Surface,
    overlay_size: tuple[int, int],
    frame_tick: int,
    tickrate: float,
    planted_duration_seconds: float,
    defuse_shake_ticks: int,
    bomb_tracker: BombTimeline,
    world_to_px,
    c4_icons: dict[str, pygame.Surface],
    defused_glow_color: tuple[int, int, int, int],
    blit_icon_with_shadow,
    blit_icon_with_glow,
) -> None:
    total_ticks = max(1, int(round(tickrate * planted_duration_seconds)))
    render_state = bomb_tracker.render_state_at(
        frame_tick,
        planted_total_ticks=total_ticks,
        abort_shake_ticks=defuse_shake_ticks,
    )
    kind = render_state.icon_state
    if kind not in {"dropped", "planted", "defused"}:
        return
    icon = c4_icons.get(kind)
    if icon is None or render_state.world_position is None:
        return
    px, py = world_to_px(*render_state.world_position)
    center = (int(round(px)), int(round(py)))
    if kind == "planted":
        draw_planted_bomb_timer(
            surface=surface,
            overlay_size=overlay_size,
            center=center,
            progress=render_state.planted_timer_progress,
            icon=c4_icons.get("planted"),
        )
        blit_icon_with_shadow(surface, icon, center)
        return
    if kind == "defused":
        blit_icon_with_glow(surface, icon, center, defused_glow_color)
        return
    blit_icon_with_shadow(surface, icon, center)


def draw_carried_bomb_icon(
    *,
    surface: pygame.Surface,
    frame_tick: int,
    tickrate: float,
    planted_duration_seconds: float,
    defuse_shake_ticks: int,
    bomb_tracker: BombTimeline,
    player: str,
    center: tuple[int, int],
    c4_icons: dict[str, pygame.Surface],
    blit_icon_with_shadow,
) -> None:
    total_ticks = max(1, int(round(tickrate * planted_duration_seconds)))
    carrier = bomb_tracker.render_state_at(
        frame_tick,
        planted_total_ticks=total_ticks,
        abort_shake_ticks=defuse_shake_ticks,
    ).carrier
    if carrier != player:
        return
    icon = c4_icons.get("carried")
    if icon is None:
        return
    blit_icon_with_shadow(surface, icon, (center[0] - 8, center[1] + 8))
