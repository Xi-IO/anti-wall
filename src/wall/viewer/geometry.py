from __future__ import annotations

import math


def offset_point(px: float, py: float, yaw: float, distance: float) -> tuple[float, float]:
    radians = math.radians(-yaw)
    return (px + math.cos(radians) * distance, py + math.sin(radians) * distance)


def build_arc_segment_points(
    center_x: int,
    center_y: int,
    radius: int,
    start_angle: float,
    end_angle: float,
) -> list[tuple[int, int]]:
    angle_span = abs(end_angle - start_angle)
    if angle_span <= 0.0:
        return []
    step_count = max(24, int(round(72 * (angle_span / (2 * math.pi)))))
    points: list[tuple[int, int]] = []
    for index in range(step_count + 1):
        t = index / step_count
        angle = start_angle + (end_angle - start_angle) * t
        points.append(
            (
                int(round(center_x + math.cos(angle) * radius)),
                int(round(center_y + math.sin(angle) * radius)),
            )
        )
    return points


def build_arc_points(
    center_x: int,
    center_y: int,
    radius: int,
    remaining_fraction: float,
) -> list[tuple[int, int]]:
    if remaining_fraction <= 0.0:
        return []
    start_angle = -math.pi / 2
    visible_start = start_angle + (2 * math.pi * (1.0 - remaining_fraction))
    visible_end = start_angle + (2 * math.pi)
    return build_arc_segment_points(center_x, center_y, radius, visible_start, visible_end)
