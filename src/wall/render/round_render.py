from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path

import pandas as pd
from PIL import Image, ImageColor, ImageDraw, ImageFont

try:
    from awpy.data.map_data import MAP_DATA
    from awpy.plot.utils import game_to_pixel_axis
except ModuleNotFoundError:
    MAP_DATA = {}
    game_to_pixel_axis = None

from wall.io.table_io import read_table_with_fallback
from wall.paths import awpy_maps_dir, resolve_asset_path


def require_column(df: pd.DataFrame, column: str, file_label: str) -> None:
    if column not in df.columns:
        raise ValueError(f"{file_label} is missing required column: {column}")


def require_round_time_columns(df: pd.DataFrame, file_label: str) -> None:
    for column in ("inferred_round_id", "inferred_round_tick", "inferred_round_seconds"):
        require_column(df, column, file_label)


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


def contrasting_text_color(_background: tuple[int, int, int]) -> tuple[int, int, int, int]:
    return (255, 255, 255, 255)


def team_color(team_num: int | float | None) -> tuple[int, int, int]:
    if team_num == 3:
        return ImageColor.getrgb("#1991BD")
    if team_num == 2:
        return ImageColor.getrgb("#D9CD21")
    return ImageColor.getrgb("#808080")


def tracer_color(team_num: int | float | None) -> tuple[int, int, int, int]:
    if team_num == 3:
        return (120, 205, 255, 210)
    if team_num == 2:
        return (255, 238, 170, 210)
    return (235, 235, 235, 200)


def load_round_data(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    ticks, ticks_label = read_table_with_fallback(data_dir, "ticks", required=True)
    deaths, deaths_label = read_table_with_fallback(data_dir, "player_death", required=True)
    fires, fires_label = read_table_with_fallback(data_dir, "fire_bullets")
    hurts, hurts_label = read_table_with_fallback(data_dir, "player_hurt")
    hits, hits_label = read_table_with_fallback(data_dir, "player_bullet_hit")
    footsteps, footsteps_label = read_table_with_fallback(data_dir, "player_footstep")
    smoke_detonates, smoke_detonates_label = read_table_with_fallback(data_dir, "smokegrenade_detonate")
    flash_detonates, flash_detonates_label = read_table_with_fallback(data_dir, "flashbang_detonate")
    he_detonates, he_detonates_label = read_table_with_fallback(data_dir, "hegrenade_detonate")
    blinds, blinds_label = read_table_with_fallback(data_dir, "player_blind")
    bomb_pickups, bomb_pickups_label = read_table_with_fallback(data_dir, "bomb_pickup")
    bomb_drops, bomb_drops_label = read_table_with_fallback(data_dir, "bomb_dropped")
    bomb_begin_plants, bomb_begin_plants_label = read_table_with_fallback(data_dir, "bomb_beginplant")
    bomb_plants, bomb_plants_label = read_table_with_fallback(data_dir, "bomb_planted")
    bomb_defuses, bomb_defuses_label = read_table_with_fallback(data_dir, "bomb_defused")
    bomb_begin_defuses, bomb_begin_defuses_label = read_table_with_fallback(data_dir, "bomb_begindefuse")
    bomb_abort_defuses, bomb_abort_defuses_label = read_table_with_fallback(data_dir, "bomb_abortdefuse")
    bomb_explodes, bomb_explodes_label = read_table_with_fallback(data_dir, "bomb_exploded")
    smoke_expires, smoke_expires_label = read_table_with_fallback(data_dir, "smokegrenade_expired")
    inferno_starts, inferno_starts_label = read_table_with_fallback(data_dir, "inferno_startburn")
    grenades, grenades_label = read_table_with_fallback(data_dir, "grenades")
    sound_events, sound_events_label = read_table_with_fallback(data_dir, "sound_events")
    inferred_rounds, inferred_rounds_label = read_table_with_fallback(data_dir, "inferred_rounds", required=True)
    metadata_path = data_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    require_round_time_columns(ticks, ticks_label)
    require_round_time_columns(deaths, deaths_label)
    if not fires.empty:
        require_round_time_columns(fires, fires_label)
    if not hurts.empty:
        require_round_time_columns(hurts, hurts_label)
    if not hits.empty:
        require_round_time_columns(hits, hits_label)
    if not footsteps.empty:
        require_round_time_columns(footsteps, footsteps_label)
    if not smoke_detonates.empty:
        require_round_time_columns(smoke_detonates, smoke_detonates_label)
    if not flash_detonates.empty:
        require_round_time_columns(flash_detonates, flash_detonates_label)
    if not he_detonates.empty:
        require_round_time_columns(he_detonates, he_detonates_label)
    if not blinds.empty:
        require_round_time_columns(blinds, blinds_label)
    if not bomb_pickups.empty:
        require_round_time_columns(bomb_pickups, bomb_pickups_label)
    if not bomb_drops.empty:
        require_round_time_columns(bomb_drops, bomb_drops_label)
    if not bomb_begin_plants.empty:
        require_round_time_columns(bomb_begin_plants, bomb_begin_plants_label)
    if not bomb_plants.empty:
        require_round_time_columns(bomb_plants, bomb_plants_label)
    if not bomb_defuses.empty:
        require_round_time_columns(bomb_defuses, bomb_defuses_label)
    if not bomb_begin_defuses.empty:
        require_round_time_columns(bomb_begin_defuses, bomb_begin_defuses_label)
    if not bomb_abort_defuses.empty:
        require_round_time_columns(bomb_abort_defuses, bomb_abort_defuses_label)
    if not bomb_explodes.empty:
        require_round_time_columns(bomb_explodes, bomb_explodes_label)
    if not smoke_expires.empty:
        require_round_time_columns(smoke_expires, smoke_expires_label)
    if not inferno_starts.empty:
        require_round_time_columns(inferno_starts, inferno_starts_label)
    if not grenades.empty:
        require_round_time_columns(grenades, grenades_label)
    if not sound_events.empty:
        require_round_time_columns(sound_events, sound_events_label)
    require_column(inferred_rounds, "inferred_round_id", inferred_rounds_label)
    return ticks, deaths, fires, hurts, hits, footsteps, smoke_detonates, flash_detonates, he_detonates, blinds, bomb_pickups, bomb_drops, bomb_begin_plants, bomb_plants, bomb_defuses, bomb_begin_defuses, bomb_abort_defuses, bomb_explodes, smoke_expires, inferno_starts, grenades, sound_events, inferred_rounds, metadata


@dataclass
class RoundData:
    round_ticks: pd.DataFrame
    round_deaths: pd.DataFrame
    round_fires: pd.DataFrame
    round_hurts: pd.DataFrame
    round_hits: pd.DataFrame
    round_footsteps: pd.DataFrame
    round_smoke_detonates: pd.DataFrame
    round_flash_detonates: pd.DataFrame
    round_he_detonates: pd.DataFrame
    round_blinds: pd.DataFrame
    round_bomb_pickups: pd.DataFrame
    round_bomb_drops: pd.DataFrame
    round_bomb_begin_plants: pd.DataFrame
    round_bomb_plants: pd.DataFrame
    round_bomb_defuses: pd.DataFrame
    round_bomb_begin_defuses: pd.DataFrame
    round_bomb_abort_defuses: pd.DataFrame
    round_bomb_explodes: pd.DataFrame
    round_smoke_expires: pd.DataFrame
    round_inferno_starts: pd.DataFrame
    round_grenades: pd.DataFrame
    round_sound_events: pd.DataFrame
    round_id: int


class RoundRenderer:
    def __init__(
        self,
        round_ticks: pd.DataFrame,
        round_deaths: pd.DataFrame,
        round_fires: pd.DataFrame,
        round_hurts: pd.DataFrame,
        round_hits: pd.DataFrame,
        width: int,
        height: int,
        trail: int,
        facing_radius: float,
        facing_fov: float,
        map_name: str | None = None,
    ) -> None:
        self.round_ticks = round_ticks.sort_values(["tick", "name"]).copy()
        self.round_deaths = self._sort_if_has_columns(round_deaths, ["tick"])
        self.round_fires = self._sort_if_has_columns(round_fires, ["tick"])
        self.round_hurts = self._sort_if_has_columns(round_hurts, ["tick"])
        self.round_hits = self._sort_if_has_columns(round_hits, ["tick"])
        self.output_width = width
        self.output_height = height
        self.trail = trail
        self.facing_radius = facing_radius
        self.facing_fov = facing_fov
        self.map_name = map_name
        self.legend_width = 220
        self.map_width = width
        self.map_height = height
        self.width = width + self.legend_width
        self.height = height
        self.players = sorted(self.round_ticks["name"].dropna().unique())
        self.player_numbers = {player: index + 1 for index, player in enumerate(self.players)}
        self.palette = build_player_palette(self.players)
        self.death_lookup = self._build_death_lookup()
        self.death_tick_lookup = self._build_death_tick_lookup()
        self.damage_flash_lookup = self._build_damage_flash_lookup()
        self.fire_lookup = self._build_fire_lookup()
        self.hurt_lookup = self._build_hurt_lookup()
        self.background_image = self._load_background_image()
        self.muzzle_flash_sprite = self._load_muzzle_flash_sprite()
        self.muzzle_flash_anchor = self._find_muzzle_flash_anchor(self.muzzle_flash_sprite)
        if self.background_image is not None:
            self.map_width, self.map_height = self.background_image.size
            self.width = self.map_width + self.legend_width
            self.height = self.map_height
        self.bounds = self._compute_bounds()
        self.round_id = int(self.round_ticks["inferred_round_id"].iloc[0])
        self.round_start_tick = int(self.round_ticks["tick"].min())
        self.frame_ticks = self.round_ticks["tick"].sort_values().unique()
        self.label_font = self._load_font(size=18)
        self.title_font = self._load_font(size=22)
        self.damage_flash_duration_ticks = 96
        self.fire_flash_duration_ticks = 32
        self.hit_match_window_ticks = 12

    def _sort_if_has_columns(self, df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        if not all(column in df.columns for column in columns):
            return df.copy()
        return df.sort_values(columns).copy()

    def _build_death_lookup(self) -> dict[str, list[pd.Series]]:
        death_lookup: dict[str, list[pd.Series]] = {}
        for _, row in self.round_deaths.iterrows():
            death_lookup.setdefault(row["user_name"], []).append(row)
        return death_lookup

    def _build_death_tick_lookup(self) -> dict[str, int]:
        death_tick_lookup: dict[str, int] = {}
        for player, rows in self.death_lookup.items():
            if rows:
                death_tick_lookup[player] = int(rows[0]["tick"])
        return death_tick_lookup

    def _build_damage_flash_lookup(self) -> dict[str, list[tuple[int, float]]]:
        if "health" not in self.round_ticks.columns:
            return {}

        work = self.round_ticks[["name", "tick", "health"]].copy()
        work["health"] = pd.to_numeric(work["health"], errors="coerce")
        flash_lookup: dict[str, list[tuple[int, float]]] = {}
        for player, group in work.groupby("name", sort=False):
            group = group.sort_values("tick").copy()
            group["prev_health"] = group["health"].shift(1)
            drops = group[
                group["health"].notna()
                & group["prev_health"].notna()
                & (group["health"] < group["prev_health"])
            ]
            if drops.empty:
                continue
            flash_lookup[player] = [
                (int(row["tick"]), float(row["prev_health"] - row["health"]))
                for _, row in drops.iterrows()
            ]
        return flash_lookup

    def _build_fire_lookup(self) -> dict[str, list[pd.Series]]:
        if self.round_fires.empty or "user_name" not in self.round_fires.columns:
            return {}
        fire_lookup: dict[str, list[pd.Series]] = {}
        for _, row in self.round_fires.iterrows():
            fire_lookup.setdefault(row["user_name"], []).append(row)
        return fire_lookup

    def _build_hurt_lookup(self) -> dict[str, list[pd.Series]]:
        if self.round_hurts.empty or "attacker_name" not in self.round_hurts.columns:
            return {}
        hurt_lookup: dict[str, list[pd.Series]] = {}
        for _, row in self.round_hurts.iterrows():
            attacker_name = row.get("attacker_name")
            if pd.isna(attacker_name):
                continue
            hurt_lookup.setdefault(str(attacker_name), []).append(row)
        return hurt_lookup

    def _compute_bounds(self) -> tuple[float, float, float, float]:
        if self.uses_map_background:
            return (0.0, float(self.map_width), 0.0, float(self.map_height))
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
        map_path = awpy_maps_dir() / f"{self.map_name}.png"
        if not map_path.exists():
            return None
        return Image.open(map_path).convert("RGBA")

    def _load_muzzle_flash_sprite(self):
        sprite_path = resolve_asset_path("sprite.png")
        if not sprite_path.exists():
            return None
        return Image.open(sprite_path).convert("RGBA")

    def _find_muzzle_flash_anchor(self, sprite: Image.Image | None) -> tuple[float, float] | None:
        if sprite is None:
            return None
        alpha = sprite.getchannel("A")
        bbox = alpha.getbbox()
        if bbox is None:
            return (0.0, sprite.height / 2)

        left, top, right, bottom = bbox
        band_width = max(6, int(round((right - left) * 0.12)))
        band_right = min(sprite.width, left + band_width)
        weighted_y = 0.0
        total_alpha = 0.0
        for x in range(left, band_right):
            for y in range(top, bottom):
                value = alpha.getpixel((x, y))
                if value <= 0:
                    continue
                weighted_y += y * value
                total_alpha += value

        anchor_y = (weighted_y / total_alpha) if total_alpha > 0 else ((top + bottom) / 2)
        return (float(left), float(anchor_y))

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
        px = (x - xmin) / (xmax - xmin) * (self.map_width - 1)
        py = (1 - (y - ymin) / (ymax - ymin)) * (self.map_height - 1)
        return px, py

    def world_dist_to_px(self, distance: float) -> float:
        if self.uses_map_background:
            scale = MAP_DATA[self.map_name]["scale"]
            return distance / scale
        xmin, xmax, _, _ = self.bounds
        return distance / (xmax - xmin) * (self.map_width - 1)

    def render_frame(self, frame_tick: int) -> Image.Image:
        if self.background_image is not None:
            image = Image.new("RGBA", (self.width, self.height), (18, 18, 18, 255))
            image.alpha_composite(self.background_image, (0, 0))
        else:
            image = Image.new("RGBA", (self.width, self.height), (250, 250, 250, 255))
        draw = ImageDraw.Draw(image, "RGBA")
        if self.background_image is None:
            self._draw_grid(draw)
        draw.rectangle((self.map_width, 0, self.width, self.height), fill=(30, 30, 30, 255), outline=None)
        self._draw_title(draw, frame_tick)
        legend_entries: list[tuple[str, tuple[int, int, int], int]] = []

        frame_slice = self.round_ticks[self.round_ticks["tick"] <= frame_tick]
        for player in self.players:
            player_hist = frame_slice[frame_slice["name"] == player].sort_values("tick")
            if player_hist.empty:
                continue

            if self._is_dead(player, frame_tick):
                current = player_hist.iloc[-1]
                color = team_color(current.get("team_num"))
                self._draw_death_marker(draw, player, frame_tick, color)
                legend_entries.append((player, color, self.player_numbers[player]))
                continue

            current = player_hist.iloc[-1]
            base_color = team_color(current.get("team_num"))
            color = self._resolve_player_color(player, frame_tick, base_color)
            legend_entries.append((player, base_color, self.player_numbers[player]))
            tail = player_hist.tail(self.trail)
            tail_points = [self.world_to_px(row.X, row.Y) for row in tail.itertuples()]
            if len(tail_points) >= 2:
                draw.line(tail_points, fill=color + (190,), width=3)

            self._draw_facing_wedge(draw, float(current["X"]), float(current["Y"]), float(current["yaw"]), color)
            self._draw_player(draw, float(current["X"]), float(current["Y"]), player, color)
            self._draw_muzzle_flash(image, player, current, frame_tick)
            self._draw_death_marker(draw, player, frame_tick, base_color)

        self._draw_player_legend(draw, legend_entries)

        if (self.width, self.height) != (self.output_width, self.output_height):
            return image.resize((self.output_width, self.output_height), Image.Resampling.LANCZOS)
        return image

    def _draw_grid(self, draw: ImageDraw.ImageDraw) -> None:
        step = 100
        for x in range(0, self.map_width, step):
            draw.line([(x, 0), (x, self.map_height)], fill=(220, 220, 220, 255), width=1)
        for y in range(0, self.map_height, step):
            draw.line([(0, y), (self.map_width, y)], fill=(220, 220, 220, 255), width=1)

    def _draw_title(self, draw: ImageDraw.ImageDraw, frame_tick: int) -> None:
        relative_tick = frame_tick - self.round_start_tick
        relative_seconds = relative_tick / 64.0
        self._draw_text(
            draw,
            (16, 16),
            f"Inferred round {self.round_id} | rtick={relative_tick} | t={relative_seconds:.2f}s",
            (255, 255, 255, 255),
            font=self.title_font,
            stroke_width=2,
        )

    def _draw_player(self, draw: ImageDraw.ImageDraw, x: float, y: float, player: str, color: tuple[int, int, int]) -> None:
        px, py = self.world_to_px(x, y)
        r = 8
        draw.ellipse((px - r, py - r, px + r, py + r), fill=color + (255,), outline=(0, 0, 0, 255))
        self._draw_player_number(draw, px, py, self.player_numbers[player], color)

    def _draw_player_number(
        self,
        draw: ImageDraw.ImageDraw,
        px: float,
        py: float,
        player_number: int,
        color: tuple[int, int, int],
    ) -> None:
        text = str(player_number)
        active_font = self.label_font
        if active_font is None:
            return
        bbox = draw.textbbox((0, 0), text, font=active_font, stroke_width=1)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        self._draw_text(
            draw,
            (px - (text_width / 2), py - (text_height / 2) - 1),
            text,
            contrasting_text_color(color),
            font=active_font,
            stroke_width=1,
        )

    def _draw_player_legend(
        self,
        draw: ImageDraw.ImageDraw,
        legend_entries: list[tuple[str, tuple[int, int, int], int]],
    ) -> None:
        if not legend_entries:
            return

        ordered = sorted(legend_entries, key=lambda item: item[2])
        x = self.map_width + 16
        y = 16
        line_height = 22
        for player, color, number in ordered:
            label = f"{number}. {player}"
            swatch_size = 12
            draw.rectangle(
                (x, y + 4, x + swatch_size, y + 4 + swatch_size),
                fill=color + (255,),
                outline=(0, 0, 0, 255),
            )
            self._draw_text(
                draw,
                (x + swatch_size + 8, y),
                label,
                (255, 255, 255, 255),
                font=self.label_font,
                stroke_width=2,
            )
            y += line_height

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

    def _draw_muzzle_flash(self, image: Image.Image, player: str, current: pd.Series, frame_tick: int) -> None:
        if self.muzzle_flash_sprite is None or self.muzzle_flash_anchor is None:
            return
        fire_event = self._latest_fire_event(player, frame_tick)
        if fire_event is None:
            return
        if not self._should_draw_muzzle_flash(fire_event):
            return

        fire_tick = int(fire_event["tick"])
        elapsed = frame_tick - fire_tick
        if elapsed < 0 or elapsed > self.fire_flash_duration_ticks:
            return

        fade = 1.0 - (elapsed / self.fire_flash_duration_ticks)
        px, py = self.world_to_px(float(current["X"]), float(current["Y"]))
        yaw = float(current["yaw"])
        muzzle_px, muzzle_py = self._offset_point(px, py, yaw, 8.0)
        self._draw_tracer_line(image, player, fire_event, muzzle_px, muzzle_py, yaw)
        flash_sprite = self.muzzle_flash_sprite.copy()
        alpha = flash_sprite.getchannel("A").point(lambda value: int(value * fade))
        flash_sprite.putalpha(alpha)

        sprite_width, sprite_height = flash_sprite.size
        scale = max(0.12, self.world_dist_to_px(48.0) / sprite_width)
        scaled_size = (
            max(1, int(round(sprite_width * scale))),
            max(1, int(round(sprite_height * scale))),
        )
        flash_sprite = flash_sprite.resize(scaled_size, Image.Resampling.LANCZOS)
        scale_x = scaled_size[0] / sprite_width
        scale_y = scaled_size[1] / sprite_height
        anchor_x = self.muzzle_flash_anchor[0] * scale_x
        anchor_y = self.muzzle_flash_anchor[1] * scale_y

        padded_size = max(flash_sprite.size) * 4
        centered = Image.new("RGBA", (padded_size, padded_size), (0, 0, 0, 0))
        center_x = padded_size / 2
        center_y = padded_size / 2
        paste_base_x = int(round(center_x - anchor_x))
        paste_base_y = int(round(center_y - anchor_y))
        centered.alpha_composite(flash_sprite, (paste_base_x, paste_base_y))
        rotated = centered.rotate(yaw, resample=Image.Resampling.BICUBIC, expand=False)

        paste_x = int(round(muzzle_px - center_x))
        paste_y = int(round(muzzle_py - center_y))
        image.alpha_composite(rotated, (paste_x, paste_y))

    def _draw_tracer_line(
        self,
        image: Image.Image,
        player: str,
        fire_event: pd.Series,
        start_x: float,
        start_y: float,
        yaw: float,
    ) -> None:
        draw = ImageDraw.Draw(image, "RGBA")
        hit_point = self._resolve_hit_point(fire_event)
        if hit_point is None:
            tracer_length = max(48.0, self.world_dist_to_px(320.0))
            end_x, end_y = self._offset_point(start_x, start_y, yaw, tracer_length)
        else:
            end_x, end_y = self.world_to_px(*hit_point)
        line_color = tracer_color(pd.to_numeric(fire_event.get("team_num"), errors="coerce"))
        draw.line(
            [(start_x, start_y), (end_x, end_y)],
            fill=line_color,
            width=2,
        )

    def _is_dead(self, player: str, frame_tick: int) -> bool:
        death_tick = self.death_tick_lookup.get(player)
        return death_tick is not None and frame_tick >= death_tick

    def _resolve_player_color(
        self,
        player: str,
        frame_tick: int,
        base_color: tuple[int, int, int],
    ) -> tuple[int, int, int]:
        flash = self._latest_damage_flash(player, frame_tick)
        if flash is None:
            return base_color

        damage_tick, _damage = flash
        elapsed = frame_tick - damage_tick
        if elapsed < 0 or elapsed > self.damage_flash_duration_ticks:
            return base_color

        fade = 1.0 - (elapsed / self.damage_flash_duration_ticks)
        return self._blend_color(base_color, (220, 48, 48), fade)

    def _latest_damage_flash(self, player: str, frame_tick: int) -> tuple[int, float] | None:
        flashes = self.damage_flash_lookup.get(player, [])
        latest: tuple[int, float] | None = None
        for damage_tick, damage in flashes:
            if damage_tick > frame_tick:
                break
            latest = (damage_tick, damage)
        return latest

    def _latest_fire_event(self, player: str, frame_tick: int) -> pd.Series | None:
        events = self.fire_lookup.get(player, [])
        latest: pd.Series | None = None
        for event in events:
            if int(event["tick"]) > frame_tick:
                break
            latest = event
        return latest

    def _resolve_hit_point(self, fire_event: pd.Series) -> tuple[float, float] | None:
        attacker_name = str(fire_event.get("user_name", ""))
        if not attacker_name:
            return None
        fire_tick = int(fire_event["tick"])
        hurts = self.hurt_lookup.get(attacker_name, [])
        for hurt in hurts:
            hurt_tick = int(hurt["tick"])
            if hurt_tick < fire_tick:
                continue
            if hurt_tick - fire_tick > self.hit_match_window_ticks:
                break
            hit_xy = self._extract_hurt_world_xy(hurt)
            if hit_xy is not None:
                return hit_xy
        return None

    def _extract_hurt_world_xy(self, hurt_event: pd.Series) -> tuple[float, float] | None:
        victim_name = hurt_event.get("user_name")
        if pd.isna(victim_name):
            return None
        hurt_tick = int(hurt_event["tick"])
        victim_rows = self.round_ticks[
            (self.round_ticks["name"] == str(victim_name))
            & (self.round_ticks["tick"] <= hurt_tick)
        ].sort_values("tick")
        if victim_rows.empty:
            return None
        victim_row = victim_rows.iloc[-1]
        return (float(victim_row["X"]), float(victim_row["Y"]))

    def _should_draw_muzzle_flash(self, fire_event: pd.Series) -> bool:
        weapon = str(fire_event.get("weapon", "")).lower()
        if not weapon:
            return True
        blocked_prefixes = (
            "weapon_knife",
            "weapon_hegrenade",
            "weapon_flashbang",
            "weapon_smokegrenade",
            "weapon_molotov",
            "weapon_incgrenade",
            "weapon_decoy",
            "weapon_c4",
        )
        return not weapon.startswith(blocked_prefixes)

    def _offset_point(self, px: float, py: float, yaw: float, distance: float) -> tuple[float, float]:
        radians = math.radians(-yaw)
        return (px + math.cos(radians) * distance, py + math.sin(radians) * distance)

    def _blend_color(
        self,
        base: tuple[int, int, int],
        overlay: tuple[int, int, int],
        amount: float,
    ) -> tuple[int, int, int]:
        clamped = max(0.0, min(1.0, amount))
        return tuple(
            int(round((1.0 - clamped) * base_channel + clamped * overlay_channel))
            for base_channel, overlay_channel in zip(base, overlay)
        )

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


def get_round_data(
    ticks: pd.DataFrame,
    deaths: pd.DataFrame,
    fires: pd.DataFrame,
    hurts: pd.DataFrame,
    hits: pd.DataFrame,
    footsteps: pd.DataFrame,
    smoke_detonates: pd.DataFrame,
    flash_detonates: pd.DataFrame,
    he_detonates: pd.DataFrame,
    blinds: pd.DataFrame,
    bomb_pickups: pd.DataFrame,
    bomb_drops: pd.DataFrame,
    bomb_begin_plants: pd.DataFrame,
    bomb_plants: pd.DataFrame,
    bomb_defuses: pd.DataFrame,
    bomb_begin_defuses: pd.DataFrame,
    bomb_abort_defuses: pd.DataFrame,
    bomb_explodes: pd.DataFrame,
    smoke_expires: pd.DataFrame,
    inferno_starts: pd.DataFrame,
    grenades: pd.DataFrame,
    sound_events: pd.DataFrame,
    round_id: int,
) -> RoundData:
    round_ticks = ticks[ticks["inferred_round_id"] == round_id].copy()
    round_deaths = deaths[deaths["inferred_round_id"] == round_id].copy()
    round_fires = fires[fires["inferred_round_id"] == round_id].copy() if not fires.empty else pd.DataFrame()
    round_hurts = hurts[hurts["inferred_round_id"] == round_id].copy() if not hurts.empty else pd.DataFrame()
    round_hits = hits[hits["inferred_round_id"] == round_id].copy() if not hits.empty else pd.DataFrame()
    round_footsteps = footsteps[footsteps["inferred_round_id"] == round_id].copy() if not footsteps.empty else pd.DataFrame()
    round_smoke_detonates = smoke_detonates[smoke_detonates["inferred_round_id"] == round_id].copy() if not smoke_detonates.empty else pd.DataFrame()
    round_flash_detonates = flash_detonates[flash_detonates["inferred_round_id"] == round_id].copy() if not flash_detonates.empty else pd.DataFrame()
    round_he_detonates = he_detonates[he_detonates["inferred_round_id"] == round_id].copy() if not he_detonates.empty else pd.DataFrame()
    round_blinds = blinds[blinds["inferred_round_id"] == round_id].copy() if not blinds.empty else pd.DataFrame()
    round_bomb_pickups = bomb_pickups[bomb_pickups["inferred_round_id"] == round_id].copy() if not bomb_pickups.empty else pd.DataFrame()
    round_bomb_drops = bomb_drops[bomb_drops["inferred_round_id"] == round_id].copy() if not bomb_drops.empty else pd.DataFrame()
    round_bomb_begin_plants = bomb_begin_plants[bomb_begin_plants["inferred_round_id"] == round_id].copy() if not bomb_begin_plants.empty else pd.DataFrame()
    round_bomb_plants = bomb_plants[bomb_plants["inferred_round_id"] == round_id].copy() if not bomb_plants.empty else pd.DataFrame()
    round_bomb_defuses = bomb_defuses[bomb_defuses["inferred_round_id"] == round_id].copy() if not bomb_defuses.empty else pd.DataFrame()
    round_bomb_begin_defuses = bomb_begin_defuses[bomb_begin_defuses["inferred_round_id"] == round_id].copy() if not bomb_begin_defuses.empty else pd.DataFrame()
    round_bomb_abort_defuses = bomb_abort_defuses[bomb_abort_defuses["inferred_round_id"] == round_id].copy() if not bomb_abort_defuses.empty else pd.DataFrame()
    round_bomb_explodes = bomb_explodes[bomb_explodes["inferred_round_id"] == round_id].copy() if not bomb_explodes.empty else pd.DataFrame()
    round_smoke_expires = smoke_expires[smoke_expires["inferred_round_id"] == round_id].copy() if not smoke_expires.empty else pd.DataFrame()
    round_inferno_starts = inferno_starts[inferno_starts["inferred_round_id"] == round_id].copy() if not inferno_starts.empty else pd.DataFrame()
    round_grenades = grenades[grenades["inferred_round_id"] == round_id].copy() if not grenades.empty else pd.DataFrame()
    round_sound_events = sound_events[sound_events["inferred_round_id"] == round_id].copy() if not sound_events.empty else pd.DataFrame()
    if round_ticks.empty:
        raise ValueError(f"No ticks found for inferred round {round_id}")
    return RoundData(
        round_ticks=round_ticks,
        round_deaths=round_deaths,
        round_fires=round_fires,
        round_hurts=round_hurts,
        round_hits=round_hits,
        round_footsteps=round_footsteps,
        round_smoke_detonates=round_smoke_detonates,
        round_flash_detonates=round_flash_detonates,
        round_he_detonates=round_he_detonates,
        round_blinds=round_blinds,
        round_bomb_pickups=round_bomb_pickups,
        round_bomb_drops=round_bomb_drops,
        round_bomb_begin_plants=round_bomb_begin_plants,
        round_bomb_plants=round_bomb_plants,
        round_bomb_defuses=round_bomb_defuses,
        round_bomb_begin_defuses=round_bomb_begin_defuses,
        round_bomb_abort_defuses=round_bomb_abort_defuses,
        round_bomb_explodes=round_bomb_explodes,
        round_smoke_expires=round_smoke_expires,
        round_inferno_starts=round_inferno_starts,
        round_grenades=round_grenades,
        round_sound_events=round_sound_events,
        round_id=round_id,
    )
