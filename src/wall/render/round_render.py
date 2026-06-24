from __future__ import annotations

from PIL import ImageColor

try:
    from awpy.data.map_data import MAP_DATA
    from awpy.plot.utils import game_to_pixel_axis
except ModuleNotFoundError:
    MAP_DATA = {}
    game_to_pixel_axis = None

from wall.domain.bomb import BombTimeline
from wall.dataset.rounds import RoundData, get_round_data, load_round_data


def team_color(team_num: int | float | None) -> tuple[int, int, int]:
    if team_num == 3:
        return ImageColor.getrgb("#1991BD")
    if team_num == 2:
        return ImageColor.getrgb("#D9CD21")
    return ImageColor.getrgb("#808080")
