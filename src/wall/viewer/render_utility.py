from __future__ import annotations

import math

import pygame

from wall.render.round_pygame_effects import draw_flash_eye, draw_flash_eye_texture


def draw_smokes(
    *,
    surface: pygame.Surface,
    frame_tick: int,
    tickrate: float,
    utility_timeline,
    world_to_px,
    world_dist_to_px,
    smoke_radius_world: float,
    he_radius_world: float,
    he_smoke_hole_recovery_delay_seconds: float,
    he_smoke_hole_full_recovery_seconds: float,
    smoke_deploy_ticks: int,
    smoke_pulse_frequency: float,
    smoke_pulse_amplitude: float,
    smoke_texture: pygame.Surface,
    get_soft_circle_mask,
) -> None:
    if not utility_timeline.has_smokes():
        return
    radius_px = max(8, int(round(world_dist_to_px(smoke_radius_world))))
    he_hole_radius_px = max(10, int(round(world_dist_to_px(he_radius_world))))
    recovery_delay_ticks = int(round(tickrate * he_smoke_hole_recovery_delay_seconds))
    full_recovery_ticks = int(round(tickrate * he_smoke_hole_full_recovery_seconds))
    for smoke_index, smoke in utility_timeline.active_smoke_windows_at(frame_tick):
        start_tick = int(smoke.start_tick)
        end_tick = int(smoke.end_tick)
        fade_ticks = 16
        if frame_tick - start_tick < fade_ticks:
            alpha_scale = (frame_tick - start_tick + 1) / fade_ticks
        elif end_tick - frame_tick < fade_ticks:
            alpha_scale = (end_tick - frame_tick + 1) / fade_ticks
        else:
            alpha_scale = 1.0
        growth_scale = min(1.0, max(0.35, (frame_tick - start_tick + 1) / smoke_deploy_ticks))
        px, py = world_to_px(float(smoke.x), float(smoke.y))
        pulse = math.sin((frame_tick - start_tick) * smoke_pulse_frequency) * smoke_pulse_amplitude
        smoke_scale = max(0.2, (1.0 + pulse) * growth_scale)
        smoke_radius_px = max(1, int(round(radius_px * 1.02 * smoke_scale)))
        texture_size = smoke_radius_px * 2
        texture = pygame.transform.smoothscale(smoke_texture, (texture_size, texture_size)).copy()
        smoke_holes = utility_timeline.smoke_holes_for_window(smoke_index)
        if smoke_holes:
            texture_scale = smoke_radius_px / max(1, radius_px)
            scaled_hole_radius_px = max(1, int(round(he_hole_radius_px * texture_scale)))
            hole_mask = pygame.Surface((texture_size, texture_size), pygame.SRCALPHA)
            hole_mask.fill((255, 255, 255, 255))
            smoke_center_x = float(smoke.x)
            smoke_center_y = float(smoke.y)
            for hole in smoke_holes:
                hole_start_tick = int(hole.start_tick)
                if frame_tick < hole_start_tick:
                    continue
                if frame_tick <= hole_start_tick + recovery_delay_ticks:
                    hole_alpha_scale = 0.0
                elif frame_tick >= hole_start_tick + full_recovery_ticks:
                    hole_alpha_scale = 1.0
                else:
                    hole_alpha_scale = (
                        frame_tick - (hole_start_tick + recovery_delay_ticks)
                    ) / max(1, full_recovery_ticks - recovery_delay_ticks)
                if hole_alpha_scale >= 1.0:
                    continue
                local_x = texture_size / 2 + (float(hole.x) - smoke_center_x) * texture_scale
                local_y = texture_size / 2 - (float(hole.y) - smoke_center_y) * texture_scale
                inner_alpha = max(0, min(255, int(round(255 * hole_alpha_scale))))
                soft_mask = get_soft_circle_mask(scaled_hole_radius_px, inner_alpha)
                soft_rect = soft_mask.get_rect(center=(int(round(local_x)), int(round(local_y))))
                hole_mask.blit(soft_mask, soft_rect, special_flags=pygame.BLEND_RGBA_MULT)
            texture.blit(hole_mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        texture.set_alpha(max(0, min(255, int(255 * alpha_scale))))
        rect = texture.get_rect(center=(int(round(px)), int(round(py))))
        surface.blit(texture, rect)


def draw_infernos(
    *,
    surface: pygame.Surface,
    overlay_size: tuple[int, int],
    frame_tick: int,
    tickrate: float,
    utility_timeline,
    world_to_px,
    inferno_growth_seconds: float,
    inferno_initial_radius_scale: float,
    fire_animation_layers: dict[str, list[pygame.Surface]],
) -> None:
    if not utility_timeline.has_infernos() or not fire_animation_layers:
        return
    overlay = pygame.Surface(overlay_size, pygame.SRCALPHA)
    growth_ticks = max(1, int(round(tickrate * inferno_growth_seconds)))
    for effect in utility_timeline.active_infernos_at(frame_tick):
        start_tick = int(effect.start_tick)
        full_radius_world = float(effect.full_radius_world)
        elapsed = frame_tick - start_tick
        growth_progress = min(1.0, max(0.0, elapsed / growth_ticks))
        current_radius_world = full_radius_world * (
            inferno_initial_radius_scale + (1.0 - inferno_initial_radius_scale) * growth_progress
        )
        center_x = float(effect.x)
        center_y = float(effect.y)
        phase_tick = max(0, elapsed // 6)
        for tile in effect.tiles:
            tile_extinguish_tick = tile.extinguish_tick
            if tile_extinguish_tick is not None and frame_tick >= int(tile_extinguish_tick):
                continue
            tile_distance = math.sqrt(float(tile.offset_x) ** 2 + float(tile.offset_y) ** 2)
            if tile_distance > current_radius_world:
                continue
            layer_name = str(tile.layer)
            frames = fire_animation_layers.get(layer_name, [])
            if not frames:
                continue
            phase = int(tile.phase)
            frame = frames[(phase_tick + phase) % len(frames)]
            base_scale = float(tile.scale)
            world_scale = 0.72 + 0.28 * growth_progress
            scaled_size = (
                max(1, int(round(frame.get_width() * base_scale * world_scale))),
                max(1, int(round(frame.get_height() * base_scale * world_scale))),
            )
            sprite = pygame.transform.smoothscale(frame, scaled_size)
            norm = tile_distance / max(1.0, full_radius_world)
            if layer_name == "02":
                alpha = int(round(228 * max(0.24, 1.0 - norm * 0.50)))
            else:
                alpha = int(round(192 * max(0.30, 1.0 - norm * 0.60)))
            sprite.set_alpha(max(0, min(255, alpha)))
            px, py = world_to_px(center_x + float(tile.offset_x), center_y + float(tile.offset_y))
            rect = sprite.get_rect(center=(int(round(px)), int(round(py))))
            overlay.blit(sprite, rect)
    surface.blit(overlay, (0, 0))


def draw_flash_effects(
    *,
    surface: pygame.Surface,
    frame_tick: int,
    width: int,
    height: int,
    utility_timeline,
    world_to_px,
    world_dist_to_px,
    flash_eye_texture: pygame.Surface | None,
) -> None:
    if not utility_timeline.has_flashes():
        return
    for flash in utility_timeline.active_flashes_at(frame_tick):
        start_tick = int(flash.start_tick)
        end_tick = int(flash.end_tick)
        if frame_tick < start_tick or frame_tick > end_tick:
            continue
        progress = (frame_tick - start_tick) / max(1, end_tick - start_tick)
        fade = max(0.0, 1.0 - progress)
        px, py = world_to_px(float(flash.x), float(flash.y))
        if flash_eye_texture is not None:
            draw_flash_eye_texture(surface, flash_eye_texture, world_dist_to_px, px, py, fade)
        else:
            draw_flash_eye(surface, width, height, world_dist_to_px, px, py, fade)


def draw_he_effects(
    *,
    surface: pygame.Surface,
    frame_tick: int,
    utility_timeline,
    world_to_px,
    he_animation_frames: list[pygame.Surface],
) -> None:
    if not utility_timeline.has_he_effects() or not he_animation_frames:
        return
    for effect in utility_timeline.active_he_bursts_at(frame_tick):
        start_tick = int(effect.start_tick)
        end_tick = int(effect.end_tick)
        if frame_tick < start_tick or frame_tick > end_tick:
            continue
        progress = (frame_tick - start_tick) / max(1, end_tick - start_tick)
        px, py = world_to_px(float(effect.x), float(effect.y))
        frame_count = len(he_animation_frames)
        frame_index = min(frame_count - 1, max(0, int(progress * frame_count)))
        frame = he_animation_frames[frame_index].copy()
        frame.set_alpha(205)
        frame_rect = frame.get_rect(center=(int(round(px)), int(round(py))))
        surface.blit(frame, frame_rect)
