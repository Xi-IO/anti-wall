from __future__ import annotations


def player_marker_number_color(team_num: int | float | None) -> tuple[int, int, int]:
    if team_num == 2:
        return (24, 22, 2)
    return (255, 255, 255)
