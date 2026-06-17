from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import pandas as pd
from PIL import Image, ImageColor, ImageDraw, ImageFont

try:
    from awpy.data.map_data import MAP_DATA
    from awpy.plot.utils import game_to_pixel_axis
except ModuleNotFoundError:
    MAP_DATA = {}
    game_to_pixel_axis = None


def require_column(df: pd.DataFrame, column: str, file_label: str) -> None:
    if column not in df.columns:
        raise ValueError(f"{file_label} is missing required column: {column}")


def build_player_palette(players: list[str]) -> dict[str, tuple[int, int, int]]:
    palette = [
        "#1f77b4",
        "#ff7f0e",
        "#2ca02c",
        "#d62728",
        "#9467bd",
        "#8c564b",
        "#e377c2",
        "#7f7f7f",
        "#bcbd22",
        "#17becf",
    ]
    return {player: ImageColor.getrgb(palette[i % len(palette)]) for i, player in enumerate(players)}


def team_color(team_num: int | float | None) -> tuple[int, int, int]:
    if team_num == 3:
        return ImageColor.getrgb("#1991BD")
    if team_num == 2:
        return ImageColor.getrgb("#D9CD21")
    return ImageColor.getrgb("#808080")


def load_round_data(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    ticks = pd.read_csv(data_dir / "ticks.csv")
    deaths = pd.read_csv(data_dir / "player_death.csv")
    inferred_rounds = pd.read_csv(data_dir / "inferred_rounds.csv")
    metadata_path = data_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    require_column(ticks, "inferred_round_id", "ticks.csv")
    require_column(deaths, "inferred_round_id", "player_death.csv")
    return ticks, deaths, inferred_rounds, metadata


@dataclass
class RoundData:
    round_ticks: pd.DataFrame
    round_deaths: pd.DataFrame
    round_id: int


class RoundRenderer:
    def __init__(
        self,
        round_ticks: pd.DataFrame,
        round_deaths: pd.DataFrame,
        width: int,
        height: int,
        trail: int,
        facing_radius: float,
        facing_fov: float,
        map_name: str | None = None,
    ) -> None:
        self.round_ticks = round_ticks.sort_values(["tick", "name"]).copy()
        self.round_deaths = round_deaths.sort_values("tick").copy()
        self.output_width = width
        self.output_height = height
        self.trail = trail
        self.facing_radius = facing_radius
        self.facing_fov = facing_fov
        self.map_name = map_name
        self.width = width
        self.height = height
        self.players = sorted(self.round_ticks["name"].dropna().unique())
        self.palette = build_player_palette(self.players)
        self.death_lookup = self._build_death_lookup()
        self.background_image = self._load_background_image()
        if self.background_image is not None:
            self.width, self.height = self.background_image.size
        self.bounds = self._compute_bounds()
        self.round_id = int(self.round_ticks["inferred_round_id"].iloc[0])
        self.frame_ticks = self.round_ticks["tick"].sort_values().unique()
        self.label_font = self._load_font(size=18)
        self.title_font = self._load_font(size=22)

    def _build_death_lookup(self) -> dict[str, list[pd.Series]]:
        death_lookup: dict[str, list[pd.Series]] = {}
        for _, row in self.round_deaths.iterrows():
            death_lookup.setdefault(row["user_name"], []).append(row)
        return death_lookup

    def _compute_bounds(self) -> tuple[float, float, float, float]:
        if self.uses_map_background:
            return (0.0, float(self.width), 0.0, float(self.height))
        xmin = float(self.round_ticks["X"].min())
        xmax = float(self.round_ticks["X"].max())
        ymin = float(self.round_ticks["Y"].min())
        ymax = float(self.round_ticks["Y"].max())
        xpad = max(50.0, (xmax - xmin) * 0.05)
        ypad = max(50.0, (ymax - ymin) * 0.05)
        return xmin - xpad, xmax + xpad, ymin - ypad, ymax + ypad

    @property
    def uses_map_background(self) -> bool:
        return self.background_image is not None and self.map_name in MAP_DATA and game_to_pixel_axis is not None

    def _load_background_image(self):
        if not self.map_name:
            return None
        map_path = Path.home() / ".awpy" / "maps" / f"{self.map_name}.png"
        if not map_path.exists():
            return None
        return Image.open(map_path).convert("RGBA")

    def _load_font(self, size: int):
        font_candidates = [
            Path("C:/Windows/Fonts/segoeuib.ttf"),
            Path("C:/Windows/Fonts/segoeui.ttf"),
            Path("C:/Windows/Fonts/arialbd.ttf"),
            Path("C:/Windows/Fonts/arial.ttf"),
        ]
        for font_path in font_candidates:
            if font_path.exists():
                try:
                    return ImageFont.truetype(str(font_path), size=size)
                except Exception:
                    continue
        try:
            return ImageFont.load_default_imagefont()
        except Exception:
            return None

    def world_to_px(self, x: float, y: float) -> tuple[float, float]:
        if self.uses_map_background:
            return (
                float(game_to_pixel_axis(self.map_name, x, "x")),
                float(game_to_pixel_axis(self.map_name, y, "y")),
            )
        xmin, xmax, ymin, ymax = self.bounds
        px = (x - xmin) / (xmax - xmin) * (self.width - 1)
        py = (1 - (y - ymin) / (ymax - ymin)) * (self.height - 1)
        return px, py

    def world_dist_to_px(self, distance: float) -> float:
        if self.uses_map_background:
            scale = MAP_DATA[self.map_name]["scale"]
            return distance / scale
        xmin, xmax, _, _ = self.bounds
        return distance / (xmax - xmin) * (self.width - 1)

    def render_frame(self, frame_tick: int) -> Image.Image:
        if self.background_image is not None:
            image = self.background_image.copy()
        else:
            image = Image.new("RGBA", (self.width, self.height), (250, 250, 250, 255))
        draw = ImageDraw.Draw(image, "RGBA")
        if self.background_image is None:
            self._draw_grid(draw)
        self._draw_title(draw, frame_tick)

        frame_slice = self.round_ticks[self.round_ticks["tick"] <= frame_tick]
        for player in self.players:
            player_hist = frame_slice[frame_slice["name"] == player].sort_values("tick")
            if player_hist.empty:
                continue

            current = player_hist.iloc[-1]
            color = team_color(current.get("team_num"))
            tail = player_hist.tail(self.trail)
            tail_points = [self.world_to_px(row.X, row.Y) for row in tail.itertuples()]
            if len(tail_points) >= 2:
                draw.line(tail_points, fill=color + (190,), width=3)

            self._draw_facing_wedge(draw, float(current["X"]), float(current["Y"]), float(current["yaw"]), color)
            self._draw_player(draw, float(current["X"]), float(current["Y"]), player, color)
            self._draw_death_marker(draw, player, frame_tick, color)

        if (self.width, self.height) != (self.output_width, self.output_height):
            return image.resize((self.output_width, self.output_height), Image.Resampling.LANCZOS)
        return image

    def _draw_grid(self, draw: ImageDraw.ImageDraw) -> None:
        step = 100
        for x in range(0, self.width, step):
            draw.line([(x, 0), (x, self.height)], fill=(220, 220, 220, 255), width=1)
        for y in range(0, self.height, step):
            draw.line([(0, y), (self.width, y)], fill=(220, 220, 220, 255), width=1)

    def _draw_title(self, draw: ImageDraw.ImageDraw, frame_tick: int) -> None:
        self._draw_text(
            draw,
            (16, 16),
            f"Inferred round {self.round_id} | tick={frame_tick}",
            (255, 255, 255, 255),
            font=self.title_font,
            stroke_width=2,
        )

    def _draw_player(self, draw: ImageDraw.ImageDraw, x: float, y: float, player: str, color: tuple[int, int, int]) -> None:
        px, py = self.world_to_px(x, y)
        r = 8
        draw.ellipse((px - r, py - r, px + r, py + r), fill=color + (255,), outline=(0, 0, 0, 255))
        self._draw_text(
            draw,
            (px + 12, py - 14),
            player,
            (255, 255, 255, 255),
            font=self.label_font,
            stroke_width=2,
        )

    def _draw_facing_wedge(
        self,
        draw: ImageDraw.ImageDraw,
        x: float,
        y: float,
        yaw: float,
        color: tuple[int, int, int],
    ) -> None:
        px, py = self.world_to_px(x, y)
        radius = self.world_dist_to_px(self.facing_radius)
        bbox = (px - radius, py - radius, px + radius, py + radius)
        start_angle = -yaw - self.facing_fov / 2
        end_angle = -yaw + self.facing_fov / 2
        draw.pieslice(bbox, start=start_angle, end=end_angle, fill=color + (153,), outline=None)

    def _draw_death_marker(
        self,
        draw: ImageDraw.ImageDraw,
        player: str,
        frame_tick: int,
        color: tuple[int, int, int],
    ) -> None:
        shown = [row for row in self.death_lookup.get(player, []) if int(row["tick"]) <= frame_tick]
        if not shown:
            return
        death_row = shown[0]
        px, py = self.world_to_px(float(death_row["user_X"]), float(death_row["user_Y"]))
        size = 8
        draw.line((px - size, py - size, px + size, py + size), fill=color + (255,), width=3)
        draw.line((px - size, py + size, px + size, py - size), fill=color + (255,), width=3)

    def _draw_text(self, draw: ImageDraw.ImageDraw, position, text: str, fill, font=None, stroke_width: int = 0) -> None:
        active_font = font or self.label_font
        if active_font is None:
            return
        draw.text(
            position,
            text,
            fill=fill,
            font=active_font,
            stroke_width=stroke_width,
            stroke_fill=(15, 15, 15, 220),
        )


def get_round_data(ticks: pd.DataFrame, deaths: pd.DataFrame, round_id: int) -> RoundData:
    round_ticks = ticks[ticks["inferred_round_id"] == round_id].copy()
    round_deaths = deaths[deaths["inferred_round_id"] == round_id].copy()
    if round_ticks.empty:
        raise ValueError(f"No ticks found for inferred round {round_id}")
    return RoundData(round_ticks=round_ticks, round_deaths=round_deaths, round_id=round_id)
