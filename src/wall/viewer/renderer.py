from __future__ import annotations

import math
import time

try:
    import pygame
except ModuleNotFoundError as exc:
    raise SystemExit(
        "pygame is not installed in the current environment. "
        "Install it in the 'wall' environment first, then rerun this viewer."
    ) from exc

from wall.paths import awpy_maps_dir, resolve_asset_path
from wall.render.round_pygame_effects import load_flash_eye_texture
from wall.render.round_render import MAP_DATA, RoundData, game_to_pixel_axis, team_color
from wall.viewer.player_frame import PlayerFramePresentation, assemble_player_frame_presentation
from wall.viewer.render_bomb import (
    draw_carried_bomb_icon,
    draw_defuse_progress,
    draw_ground_bomb,
    draw_plant_attempts,
)
from wall.viewer.config import TEXT_COLOR
from wall.viewer.render_player import (
    draw_death_marker,
    draw_facing_wedge,
    draw_muzzle_flash,
    draw_player,
    draw_player_id_label,
    draw_tracer_line,
    offset_point,
)
from wall.viewer.render_config import (
    BOMB_PLANTED_DURATION_SECONDS,
    C4_CARRIED_COLOR,
    C4_DEFUSED_COLOR,
    C4_DEFUSED_GLOW_COLOR,
    C4_DROPPED_COLOR,
    C4_PLANTED_COLOR,
    DEFUSE_BAR_COLOR,
    DEFUSE_BAR_GLOW,
    DEFUSE_BAR_SHADOW,
    DEFUSE_SHAKE_TICKS,
    GRENADE_ICON_PATHS,
    GRENADE_TYPE_STYLES,
    HE_RADIUS_WORLD,
    HE_SMOKE_HOLE_FEATHER_RATIO,
    HE_SMOKE_HOLE_FULL_RECOVERY_SECONDS,
    HE_SMOKE_HOLE_RECOVERY_DELAY_SECONDS,
    INFERNO_GROWTH_SECONDS,
    INFERNO_INITIAL_RADIUS_SCALE,
    SMOKE_DEPLOY_TICKS,
    SMOKE_PULSE_AMPLITUDE,
    SMOKE_PULSE_FREQUENCY,
    SMOKE_RADIUS_WORLD,
    SOUND_BASE_ALPHA,
    SOUND_FILL_ALPHA,
    SOUND_LABEL_DISTANCE_PX,
    SOUND_PRESENTATION,
    TRACER_CT_COLOR,
    TRACER_NEUTRAL_COLOR,
    TRACER_T_COLOR,
)
from wall.viewer.render_sound import draw_sound_events
from wall.viewer.render_utility import draw_flash_effects, draw_he_effects, draw_infernos, draw_smokes
from wall.viewer.ui import tint_icon
from wall.profile import profile_log


PLAYER_WEAPON_ICON_COLOR = (230, 230, 230)
PLAYER_WEAPON_ICON_ALPHA = 178
DEFUSER_ICON_COLOR = team_color(3)

PLAYER_WEAPON_ICON_PATHS = {
    "AK-47": "icons/equipment/rifles/ak47.png",
    "AUG": "icons/equipment/rifles/aug.png",
    "AWP": "icons/equipment/rifles/awp.png",
    "Bayonet": "icons/equipment/melee/bayonet.png",
    "Bowie Knife": "icons/equipment/melee/knife_bowie.png",
    "Butterfly Knife": "icons/equipment/melee/knife_butterfly.png",
    "C4 Explosive": "icons/equipment/bomb/c4.png",
    "Classic Knife": "icons/equipment/melee/knife_css.png",
    "CZ75-Auto": "icons/equipment/pistols/cz75a.png",
    "Decoy Grenade": "icons/equipment/grenades/decoy.png",
    "Desert Eagle": "icons/equipment/pistols/deagle.png",
    "Deagle": "icons/equipment/pistols/deagle.png",
    "Dual Berettas": "icons/equipment/pistols/elite.png",
    "Dualies": "icons/equipment/pistols/elite.png",
    "FAMAS": "icons/equipment/rifles/famas.png",
    "Falchion Knife": "icons/equipment/melee/knife_falchion.png",
    "Five-SeveN": "icons/equipment/pistols/fiveseven.png",
    "Five-seveN": "icons/equipment/pistols/fiveseven.png",
    "Flashbang": "icons/equipment/grenades/flashbang.png",
    "Flip Knife": "icons/equipment/melee/knife_flip.png",
    "Galil AR": "icons/equipment/rifles/galilar.png",
    "G3SG1": "icons/equipment/rifles/g3sg1.png",
    "Glock-18": "icons/equipment/pistols/glock.png",
    "Gut Knife": "icons/equipment/melee/knife_gut.png",
    "Huntsman Knife": "icons/equipment/melee/knife_tactical.png",
    "High Explosive Grenade": "icons/equipment/grenades/hegrenade.png",
    "HE Grenade": "icons/equipment/grenades/hegrenade.png",
    "Incendiary Grenade": "icons/equipment/grenades/incgrenade.png",
    "Karambit": "icons/equipment/melee/knife_karambit.png",
    "Kukri Knife": "icons/equipment/melee/knife_kukri.png",
    "M4A1-S": "icons/equipment/rifles/m4a1_silencer.png",
    "M4A1-S Silenced": "icons/equipment/rifles/m4a1_silencer.png",
    "M4A4": "icons/equipment/rifles/m4a1.png",
    "M9 Bayonet": "icons/equipment/melee/knife_m9_bayonet.png",
    "MAC-10": "icons/equipment/smgs/mac10.png",
    "MAG-7": "icons/equipment/heavy/mag7.png",
    "M249": "icons/equipment/heavy/m249.png",
    "MP5-SD": "icons/equipment/smgs/mp5sd.png",
    "MP7": "icons/equipment/smgs/mp7.png",
    "MP9": "icons/equipment/smgs/mp9.png",
    "Molotov": "icons/equipment/grenades/molotov.png",
    "Negev": "icons/equipment/heavy/negev.png",
    "Navaja Knife": "icons/equipment/melee/knife_gypsy_jackknife.png",
    "Nomad Knife": "icons/equipment/melee/knife_outdoor.png",
    "Nova": "icons/equipment/heavy/nova.png",
    "P2000": "icons/equipment/pistols/p2000.png",
    "P250": "icons/equipment/pistols/p250.png",
    "P90": "icons/equipment/smgs/p90.png",
    "Paracord Knife": "icons/equipment/melee/knife_cord.png",
    "PP-Bizon": "icons/equipment/smgs/bizon.png",
    "PP-Bizon SMG": "icons/equipment/smgs/bizon.png",
    "R8 Revolver": "icons/equipment/pistols/revolver.png",
    "Sawed-Off": "icons/equipment/heavy/sawedoff.png",
    "SCAR-20": "icons/equipment/rifles/scar20.png",
    "SG 553": "icons/equipment/rifles/sg556.png",
    "SG553": "icons/equipment/rifles/sg556.png",
    "SSG 08": "icons/equipment/rifles/ssg08.png",
    "Shadow Daggers": "icons/equipment/melee/knife_push.png",
    "Skeleton Knife": "icons/equipment/melee/knife_skeleton.png",
    "Smoke Grenade": "icons/equipment/grenades/smokegrenade.png",
    "Scout": "icons/equipment/rifles/ssg08.png",
    "Survival Knife": "icons/equipment/melee/knife_canis.png",
    "Survival Bowie Knife": "icons/equipment/melee/knife_survival_bowie.png",
    "Talon Knife": "icons/equipment/melee/knife_widowmaker.png",
    "Tec-9": "icons/equipment/pistols/tec9.png",
    "UMP-45": "icons/equipment/smgs/ump45.png",
    "USP-S": "icons/equipment/pistols/usp_silencer.png",
    "USP-S Silenced": "icons/equipment/pistols/usp_silencer.png",
    "Ursus Knife": "icons/equipment/melee/knife_ursus.png",
    "XM1014": "icons/equipment/heavy/xm1014.png",
    "Zeus": "icons/equipment/gear/taser.png",
    "Zeus x27": "icons/equipment/gear/taser.png",
    "Healthshot": "icons/equipment/gear/healthshot.png",
    "Medi-Shot": "icons/equipment/gear/healthshot.png",
    "Stiletto Knife": "icons/equipment/melee/knife_stiletto.png",
    "knife": "icons/equipment/melee/knife.png",
    "knife_t": "icons/equipment/melee/knife_t.png",
}


def _normalize_weapon_icon_key(name: str) -> str:
    return " ".join(name.strip().lower().replace("_", " ").split())


class PygameRoundRenderer:
    def __init__(
        self,
        round_data: RoundData,
        player_numbers: dict[str, int] | None,
        width: int,
        height: int,
        trail: int,
        facing_radius: float,
        facing_fov: float,
        map_name: str | None,
        tickrate: float,
    ) -> None:
        init_started_at = time.perf_counter()
        profile_log("renderer.object_init.start", round_id=round_data.round_id, map_name=map_name)
        self.round_data = round_data
        self.round_ticks = round_data.round_ticks
        self.show_sound_effects = True
        self.width = width
        self.height = height
        self.trail = trail
        self.facing_radius = facing_radius
        self.facing_fov = facing_fov
        self.map_name = map_name
        self.tickrate = tickrate
        self.round_id = round_data.round_id
        self.round_start_tick = round_data.round_start_tick
        self.frame_ticks = round_data.frame_ticks
        # IMPORTANT: Phase 4 narrows viewer inputs here. Renderer should consume
        # semantic objects from RoundData instead of rebuilding them from raw tables.
        # IMPORTANT: renderer now acts as a coordinator for specialized draw helpers.
        # New visual features should prefer extending render_* modules instead of
        # expanding this class back into a monolith.
        self.round_players = round_data.round_players
        self.players = sorted(self.round_players.ordered_names)
        if player_numbers is None:
            self.player_numbers = {player: index + 1 for index, player in enumerate(self.players)}
        else:
            next_fallback = max(player_numbers.values(), default=0) + 1
            resolved_numbers: dict[str, int] = {}
            for player in self.players:
                if player in player_numbers:
                    resolved_numbers[player] = player_numbers[player]
                else:
                    resolved_numbers[player] = next_fallback
                    next_fallback += 1
            self.player_numbers = resolved_numbers
            self.players = sorted(self.players, key=lambda player: (self.player_numbers[player], player))
        self.utility_timeline = round_data.utility_timeline
        self.damage_flash_duration_ticks = 96
        self.fire_flash_duration_ticks = 32
        self.hit_match_window_ticks = 12
        self.bomb_tracker = round_data.bomb_timeline
        self.sound_timeline = round_data.sound_timeline

        asset_started_at = time.perf_counter()
        profile_log("renderer.map_asset_load.start", round_id=self.round_id, map_name=self.map_name)
        self.background_original = self._load_background_image()
        profile_log("renderer.map_asset_load.end", started_at=asset_started_at, round_id=self.round_id, map_name=self.map_name)
        surface_started_at = time.perf_counter()
        profile_log("renderer.surface_load.start", round_id=self.round_id, map_name=self.map_name)
        self.uses_map_background = self.background_original is not None and self.map_name in MAP_DATA and game_to_pixel_axis is not None
        self.background_surface = self._build_background_surface()
        profile_log("renderer.surface_load.end", started_at=surface_started_at, round_id=self.round_id, map_name=self.map_name)
        geometry_started_at = time.perf_counter()
        profile_log("renderer.geometry_cache.start", round_id=self.round_id, map_name=self.map_name)
        self.bounds = self._compute_bounds()
        profile_log("renderer.geometry_cache.end", started_at=geometry_started_at, round_id=self.round_id, map_name=self.map_name)
        self.font = pygame.font.SysFont("segoe ui", 18)
        self.player_number_font = pygame.font.SysFont("segoe ui", 11)
        self.small_font = pygame.font.SysFont("segoe ui", 14)
        self.title_font = pygame.font.SysFont("segoe ui", 22, bold=True)
        self.muzzle_flash_sprite = self._load_muzzle_flash_sprite()
        self.muzzle_flash_anchor = self._find_muzzle_flash_anchor(self.muzzle_flash_sprite)
        self.grenade_icons = self._load_grenade_icons()
        self.player_weapon_icons = self._load_player_weapon_icons()
        self.he_animation_frames = self._load_he_animation_frames()
        self.fire_animation_layers = self._load_fire_animation_layers()
        self.soft_circle_masks: dict[tuple[int, int], pygame.Surface] = {}
        self.sound_ring_cache: dict[tuple[int, int, tuple[int, int, int], int], pygame.Surface] = {}
        self.c4_icons = self._load_c4_icons()
        self.defuser_icon = self._load_defuser_icon()
        self.sound_toggle_icons = self._load_sound_toggle_icons()
        self.flash_eye_texture = load_flash_eye_texture()
        self.smoke_texture = self._build_smoke_texture()
        profile_log("renderer.object_init.end", started_at=init_started_at, round_id=self.round_id, map_name=self.map_name)

    def _load_background_image(self) -> pygame.Surface | None:
        if not self.map_name:
            return None
        map_path = awpy_maps_dir() / f"{self.map_name}.png"
        if not map_path.exists():
            return None
        return pygame.image.load(str(map_path)).convert()

    def _player_timeline(self, player_name: str | None):
        if not player_name:
            return None
        return self.round_players.get_by_name(player_name)

    def _get_soft_circle_mask(self, radius_px: int, inner_alpha: int) -> pygame.Surface:
        key = (radius_px, inner_alpha)
        cached = self.soft_circle_masks.get(key)
        if cached is not None:
            return cached
        diameter = max(2, radius_px * 2)
        mask = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
        center = radius_px
        feather_start = radius_px * max(0.0, min(0.95, 1.0 - HE_SMOKE_HOLE_FEATHER_RATIO))
        for y in range(diameter):
            dy = y - center
            for x in range(diameter):
                dx = x - center
                distance = math.sqrt(dx * dx + dy * dy)
                if distance >= radius_px:
                    alpha = 255
                elif distance <= feather_start:
                    alpha = inner_alpha
                else:
                    t = (distance - feather_start) / max(1e-6, radius_px - feather_start)
                    alpha = int(round(inner_alpha + (255 - inner_alpha) * t))
                value = max(0, min(255, alpha))
                mask.set_at((x, y), (value, value, value, value))
        self.soft_circle_masks[key] = mask
        return mask

    def _build_background_surface(self) -> pygame.Surface:
        if self.background_original is None:
            surface = pygame.Surface((self.width, self.height))
            surface.fill((245, 245, 245))
            return surface
        return pygame.transform.smoothscale(self.background_original, (self.width, self.height)).convert()

    def _load_muzzle_flash_sprite(self) -> pygame.Surface | None:
        sprite_path = resolve_asset_path("effects", "muzzle", "sprite.png")
        if not sprite_path.exists():
            return None
        return pygame.image.load(str(sprite_path)).convert_alpha()

    def _load_grenade_icons(self) -> dict[str, pygame.Surface]:
        icons: dict[str, pygame.Surface] = {}
        target_height = 14
        for grenade_type, filename in GRENADE_ICON_PATHS.items():
            icon_path = resolve_asset_path(filename)
            if not icon_path.exists():
                continue
            try:
                icon = pygame.image.load(str(icon_path)).convert_alpha()
            except pygame.error:
                continue
            width, height = icon.get_size()
            if width <= 0 or height <= 0:
                continue
            scale = target_height / height
            scaled_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
            icons[grenade_type] = pygame.transform.smoothscale(icon, scaled_size)
        for filename in ("icons/equipment/firebomb.png", "icons/equipment/incgrenade.png"):
            icon_path = resolve_asset_path(filename)
            if not icon_path.exists():
                continue
            try:
                icon = pygame.image.load(str(icon_path)).convert_alpha()
            except pygame.error:
                continue
            width, height = icon.get_size()
            if width <= 0 or height <= 0:
                continue
            scale = target_height / height
            scaled_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
            icons[filename] = pygame.transform.smoothscale(icon, scaled_size)
        return icons

    def _load_player_weapon_icons(self) -> dict[str, pygame.Surface]:
        icons: dict[str, pygame.Surface] = {}
        target_height = 13
        for weapon_name, filename in PLAYER_WEAPON_ICON_PATHS.items():
            icon_path = resolve_asset_path(filename)
            if not icon_path.exists():
                continue
            try:
                base = pygame.image.load(str(icon_path)).convert_alpha()
            except pygame.error:
                continue
            width, height = base.get_size()
            if width <= 0 or height <= 0:
                continue
            scale = target_height / height
            scaled_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
            icon = pygame.transform.smoothscale(base, scaled_size)
            icon = tint_icon(icon, PLAYER_WEAPON_ICON_COLOR)
            icon.set_alpha(PLAYER_WEAPON_ICON_ALPHA)
            icons[weapon_name] = icon
        return icons

    def _player_weapon_icon(self, weapon_name: str) -> pygame.Surface | None:
        if not weapon_name:
            return None
        icon = self.player_weapon_icons.get(weapon_name)
        if icon is not None:
            return icon
        normalized = _normalize_weapon_icon_key(weapon_name)
        for candidate_name, candidate_icon in self.player_weapon_icons.items():
            if _normalize_weapon_icon_key(candidate_name) == normalized:
                return candidate_icon
        fallback_name = self._fallback_weapon_icon_name(normalized)
        if not fallback_name:
            return None
        return self.player_weapon_icons.get(fallback_name)

    def _fallback_weapon_icon_name(self, normalized_name: str) -> str | None:
        if "c4" in normalized_name:
            return "C4 Explosive"
        if "healthshot" in normalized_name or "medi" in normalized_name:
            return "Healthshot"
        if "zeus" in normalized_name or "taser" in normalized_name:
            return "Zeus x27"
        if "flash" in normalized_name:
            return "Flashbang"
        if "smoke" in normalized_name:
            return "Smoke Grenade"
        if "molotov" in normalized_name:
            return "Molotov"
        if "incendiary" in normalized_name or "incgrenade" in normalized_name or "firebomb" in normalized_name:
            return "Incendiary Grenade"
        if "decoy" in normalized_name:
            return "Decoy Grenade"
        if "he grenade" in normalized_name or "hegrenade" in normalized_name or "high explosive" in normalized_name:
            return "High Explosive Grenade"
        if "grenade" in normalized_name:
            return "High Explosive Grenade"
        if any(
            token in normalized_name
            for token in (
                "knife",
                "bayonet",
                "daggers",
                "dagger",
                "karambit",
                "kukri",
                "falchion",
                "flip",
                "gut",
                "talon",
                "ursus",
                "stiletto",
                "skeleton",
                "bowie",
                "navaja",
                "nomad",
                "paracord",
                "survival",
                "huntsman",
                "classic",
            )
        ):
            return "knife"
        return None

    def _load_he_animation_frames(self) -> list[pygame.Surface]:
        frames: list[pygame.Surface] = []
        target_height = 60
        base_dir = resolve_asset_path("effects", "explosions", "he")
        for frame_index in range(1, 8):
            frame_path = base_dir / f"he{frame_index}.png"
            if not frame_path.exists():
                continue
            try:
                frame = pygame.image.load(str(frame_path)).convert_alpha()
            except pygame.error:
                continue
            width, height = frame.get_size()
            if width <= 0 or height <= 0:
                continue
            scale = target_height / height
            scaled_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
            frames.append(pygame.transform.smoothscale(frame, scaled_size))
        return frames

    def _load_fire_animation_layers(self) -> dict[str, list[pygame.Surface]]:
        layers: dict[str, list[pygame.Surface]] = {"01": [], "02": []}
        base_dir = resolve_asset_path("effects", "fire")
        target_height = 34
        for layer_name in ("01", "02"):
            for frame_index in range(1, 6):
                frame_path = base_dir / f"Fire0_{layer_name}_{frame_index}.png"
                if not frame_path.exists():
                    continue
                try:
                    frame = pygame.image.load(str(frame_path)).convert_alpha()
                except pygame.error:
                    continue
                width, height = frame.get_size()
                if width <= 0 or height <= 0:
                    continue
                scale = target_height / height
                scaled_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
                layers[layer_name].append(pygame.transform.smoothscale(frame, scaled_size))
        return layers

    def _load_c4_icons(self) -> dict[str, pygame.Surface]:
        icon_path = resolve_asset_path("icons", "equipment", "c4.png")
        if not icon_path.exists():
            return {}
        try:
            icon = pygame.image.load(str(icon_path)).convert_alpha()
        except pygame.error:
            return {}
        width, height = icon.get_size()
        if width <= 0 or height <= 0:
            return {}
        target_height = 15
        scale = target_height / height
        scaled_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
        base = pygame.transform.scale(icon, scaled_size)
        return {
            "carried": tint_icon(base, C4_CARRIED_COLOR),
            "dropped": tint_icon(base, C4_DROPPED_COLOR),
            "planted": tint_icon(base, C4_PLANTED_COLOR),
            "defused": tint_icon(base, C4_DEFUSED_COLOR),
        }

    def _load_defuser_icon(self) -> pygame.Surface | None:
        icon_path = resolve_asset_path("icons", "equipment", "gear", "defuser.png")
        if not icon_path.exists():
            return None
        try:
            icon = pygame.image.load(str(icon_path)).convert_alpha()
        except pygame.error:
            return None
        width, height = icon.get_size()
        if width <= 0 or height <= 0:
            return None
        target_height = 15
        scale = target_height / height
        scaled_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
        return tint_icon(pygame.transform.scale(icon, scaled_size), DEFUSER_ICON_COLOR)

    def _load_sound_toggle_icons(self) -> dict[str, pygame.Surface]:
        icons: dict[str, pygame.Surface] = {}
        for key, filename in (("sound_on", "ui/icons/sound_on.png"), ("sound_off", "ui/icons/sound_off.png")):
            icon_path = resolve_asset_path(filename)
            if not icon_path.exists():
                continue
            try:
                icon = pygame.image.load(str(icon_path)).convert_alpha()
            except pygame.error:
                continue
            width, height = icon.get_size()
            if width <= 0 or height <= 0:
                continue
            target_height = 19
            scale = target_height / height
            scaled_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
            icons[key] = pygame.transform.smoothscale(icon, scaled_size)
        return icons

    def _blit_icon_with_shadow(self, surface: pygame.Surface, icon: pygame.Surface, center: tuple[int, int]) -> None:
        shadow = icon.copy()
        shadow.fill((18, 18, 18, 170), special_flags=pygame.BLEND_RGBA_MULT)
        shadow_rect = shadow.get_rect(center=(center[0] + 1, center[1] + 1))
        icon_rect = icon.get_rect(center=center)
        surface.blit(shadow, shadow_rect)
        surface.blit(icon, icon_rect)

    def _blit_icon_with_glow(
        self,
        surface: pygame.Surface,
        icon: pygame.Surface,
        center: tuple[int, int],
        glow_color: tuple[int, int, int, int],
    ) -> None:
        glow = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        glow_radius = max(icon.get_width(), icon.get_height()) // 2 + 4
        pygame.draw.circle(glow, glow_color, (center[0] + 1, center[1] + 1), glow_radius)
        surface.blit(glow, (0, 0))
        self._blit_icon_with_shadow(surface, icon, center)

    def _build_smoke_texture(self) -> pygame.Surface:
        asset_path = resolve_asset_path("effects", "smoke", "smoke_texture.png")
        if asset_path.exists():
            try:
                return pygame.image.load(str(asset_path)).convert_alpha()
            except pygame.error:
                pass
        size = 384
        center = size // 2
        max_radius = size // 2 - 8
        surface = pygame.Surface((size, size), pygame.SRCALPHA)

        core_layers = [
            (0.82, 230, (92, 98, 104)),
            (0.92, 214, (100, 106, 112)),
            (1.02, 195, (110, 116, 122)),
        ]
        for scale, alpha, color in core_layers:
            pygame.draw.circle(
                surface,
                color + (alpha,),
                (center, center),
                int(round(max_radius * scale / 1.02)),
            )

        edge_layers = [
            (-0.14, -0.04, 1.05, 54),
            (0.13, -0.09, 1.03, 48),
            (-0.03, 0.16, 1.04, 44),
            (0.12, 0.11, 1.02, 52),
        ]
        for offset_x, offset_y, scale, alpha in edge_layers:
            pygame.draw.circle(
                surface,
                (118, 124, 130, alpha),
                (
                    int(round(center + max_radius * offset_x / 1.02)),
                    int(round(center + max_radius * offset_y / 1.02)),
                ),
                int(round(max_radius * scale / 1.02)),
            )
        return surface

    def _find_muzzle_flash_anchor(self, sprite: pygame.Surface | None) -> tuple[float, float] | None:
        if sprite is None:
            return None
        alpha = pygame.surfarray.array_alpha(sprite)
        non_zero = alpha > 0
        if not non_zero.any():
            return (0.0, sprite.get_height() / 2)
        xs, ys = non_zero.nonzero()
        left = int(xs.min())
        right = int(xs.max()) + 1
        top = int(ys.min())
        bottom = int(ys.max()) + 1
        band_width = max(6, int(round((right - left) * 0.12)))
        band_right = min(sprite.get_width(), left + band_width)
        weighted_y = 0.0
        total_alpha = 0.0
        for x in range(left, band_right):
            for y in range(top, bottom):
                value = int(alpha[x, y])
                if value <= 0:
                    continue
                weighted_y += y * value
                total_alpha += value
        anchor_y = (weighted_y / total_alpha) if total_alpha > 0 else ((top + bottom) / 2)
        return (float(left), float(anchor_y))

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

    def world_to_px(self, x: float, y: float) -> tuple[float, float]:
        if self.uses_map_background:
            original_width = self.background_original.get_width() if self.background_original else self.width
            original_height = self.background_original.get_height() if self.background_original else self.height
            px = float(game_to_pixel_axis(self.map_name, x, "x"))
            py = float(game_to_pixel_axis(self.map_name, y, "y"))
            return (px / original_width * self.width, py / original_height * self.height)
        xmin, xmax, ymin, ymax = self.bounds
        px = (x - xmin) / (xmax - xmin) * (self.width - 1)
        py = (1 - (y - ymin) / (ymax - ymin)) * (self.height - 1)
        return px, py

    def world_dist_to_px(self, distance: float) -> float:
        if self.uses_map_background:
            scale = MAP_DATA[self.map_name]["scale"]
            original_width = self.background_original.get_width() if self.background_original else self.width
            return (distance / scale) * (self.width / original_width)
        xmin, xmax, _, _ = self.bounds
        return distance / (xmax - xmin) * (self.width - 1)

    def render_map_frame(self, frame_tick: int) -> pygame.Surface:
        surface = self.background_surface.copy()
        if self.background_original is None:
            self._draw_grid(surface)
        self._draw_title(surface, frame_tick)
        self._draw_infernos(surface, frame_tick)
        self._draw_smokes(surface, frame_tick)
        self._draw_grenades(surface, frame_tick)
        self._draw_flash_effects(surface, frame_tick)
        self._draw_he_effects(surface, frame_tick)
        self._draw_ground_bomb(surface, frame_tick)
        if self.show_sound_effects:
            self._draw_sound_events(surface, frame_tick)

        for player in self.players:
            presentation = self._player_presentation(player, frame_tick)
            if presentation is None:
                continue
            if not presentation.is_alive:
                self._draw_player_death(surface, presentation)
                continue

            tail_points = [self.world_to_px(x, y) for x, y in presentation.tail_world_points]
            if len(tail_points) >= 2:
                pygame.draw.lines(surface, presentation.draw_color, False, tail_points, 3)
            px, py = self.world_to_px(*presentation.world_position)
            draw_facing_wedge(
                surface=surface,
                overlay_size=(self.width, self.height),
                px=px,
                py=py,
                yaw=presentation.yaw,
                radius=self.world_dist_to_px(self.facing_radius),
                facing_fov=self.facing_fov,
                color=presentation.draw_color,
            )
            draw_player(
                surface=surface,
                overlay_size=(self.width, self.height),
                player_number_font=self.player_number_font,
                small_font=self.small_font,
                player_number=presentation.player_number,
                px=px,
                py=py,
                player=presentation.player,
                color=presentation.draw_color,
                id_color=presentation.base_color,
                team_num=presentation.team_num,
                health=presentation.health,
                blind_strength=presentation.blind_strength,
                draw_carried_bomb_icon=self._draw_carried_bomb_icon,
                draw_defuser_icon=self._draw_defuser_icon,
                frame_tick=frame_tick,
                weapon_icon=self._player_weapon_icon(presentation.weapon_name),
            )
            self._draw_player_tracer_and_flash(surface, presentation)
            self._draw_player_death(surface, presentation)
        self._draw_plant_attempts(surface, frame_tick)
        return surface

    def _draw_grid(self, surface: pygame.Surface) -> None:
        step = 100
        for x in range(0, self.width, step):
            pygame.draw.line(surface, (220, 220, 220), (x, 0), (x, self.height), 1)
        for y in range(0, self.height, step):
            pygame.draw.line(surface, (220, 220, 220), (0, y), (self.width, y), 1)

    def _draw_title(self, surface: pygame.Surface, frame_tick: int) -> None:
        relative_tick = frame_tick - self.round_start_tick
        relative_seconds = relative_tick / self.tickrate if self.tickrate > 0 else 0.0
        title = f"Inferred round {self.round_id} | rtick={relative_tick} | t={relative_seconds:.2f}s"
        text_surface = self.title_font.render(title, True, TEXT_COLOR)
        shadow_surface = self.title_font.render(title, True, (10, 10, 10))
        surface.blit(shadow_surface, (18, 18))
        surface.blit(text_surface, (16, 16))

    def _draw_grenades(self, surface: pygame.Surface, frame_tick: int) -> None:
        if not self.utility_timeline.has_grenade_trails():
            return
        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        for trail in self.utility_timeline.active_grenade_trails_at(
            frame_tick,
            recent_window_ticks=8,
            smoke_deploy_ticks=SMOKE_DEPLOY_TICKS,
        ):
            grenade_type = str(trail.grenade_type)
            style = GRENADE_TYPE_STYLES.get(grenade_type, {"color": (220, 220, 220), "radius": 4})
            line_points = [
                self.world_to_px(float(point.x), float(point.y))
                for point in trail.recent_points
            ]
            if len(line_points) >= 2:
                pygame.draw.lines(overlay, style["color"] + (110,), False, line_points, 2)
            px, py = self.world_to_px(float(trail.current_x), float(trail.current_y))
            icon_key = trail.burn_icon_path
            if not icon_key:
                icon_key = grenade_type
            icon = self.grenade_icons.get(str(icon_key))
            if icon is not None:
                icon_rect = icon.get_rect(center=(int(round(px)), int(round(py))))
                overlay.blit(icon, icon_rect)
            else:
                pygame.draw.circle(overlay, style["color"] + (220,), (int(round(px)), int(round(py))), int(style["radius"]))
                pygame.draw.circle(surface, (20, 20, 20), (int(round(px)), int(round(py))), int(style["radius"]), 1)
        surface.blit(overlay, (0, 0))

    def _draw_sound_events(self, surface: pygame.Surface, frame_tick: int) -> None:
        draw_sound_events(
            surface=surface,
            frame_tick=frame_tick,
            width=self.width,
            height=self.height,
            font=self.small_font,
            sound_timeline=self.sound_timeline,
            round_players=self.round_players,
            world_to_px=self.world_to_px,
            world_dist_to_px=self.world_dist_to_px,
            presentation=SOUND_PRESENTATION,
            ring_cache=self.sound_ring_cache,
            sound_fill_alpha=SOUND_FILL_ALPHA,
            sound_base_alpha=SOUND_BASE_ALPHA,
            sound_label_distance_px=SOUND_LABEL_DISTANCE_PX,
        )

    def _draw_smokes(self, surface: pygame.Surface, frame_tick: int) -> None:
        draw_smokes(
            surface=surface,
            frame_tick=frame_tick,
            tickrate=self.tickrate,
            utility_timeline=self.utility_timeline,
            world_to_px=self.world_to_px,
            world_dist_to_px=self.world_dist_to_px,
            smoke_radius_world=SMOKE_RADIUS_WORLD,
            he_radius_world=HE_RADIUS_WORLD,
            he_smoke_hole_recovery_delay_seconds=HE_SMOKE_HOLE_RECOVERY_DELAY_SECONDS,
            he_smoke_hole_full_recovery_seconds=HE_SMOKE_HOLE_FULL_RECOVERY_SECONDS,
            smoke_deploy_ticks=SMOKE_DEPLOY_TICKS,
            smoke_pulse_frequency=SMOKE_PULSE_FREQUENCY,
            smoke_pulse_amplitude=SMOKE_PULSE_AMPLITUDE,
            smoke_texture=self.smoke_texture,
            get_soft_circle_mask=self._get_soft_circle_mask,
        )

    def _draw_infernos(self, surface: pygame.Surface, frame_tick: int) -> None:
        draw_infernos(
            surface=surface,
            overlay_size=(self.width, self.height),
            frame_tick=frame_tick,
            tickrate=self.tickrate,
            utility_timeline=self.utility_timeline,
            world_to_px=self.world_to_px,
            inferno_growth_seconds=INFERNO_GROWTH_SECONDS,
            inferno_initial_radius_scale=INFERNO_INITIAL_RADIUS_SCALE,
            fire_animation_layers=self.fire_animation_layers,
        )

    def _draw_flash_effects(self, surface: pygame.Surface, frame_tick: int) -> None:
        draw_flash_effects(
            surface=surface,
            frame_tick=frame_tick,
            width=self.width,
            height=self.height,
            utility_timeline=self.utility_timeline,
            world_to_px=self.world_to_px,
            world_dist_to_px=self.world_dist_to_px,
            flash_eye_texture=self.flash_eye_texture,
        )

    def _draw_he_effects(self, surface: pygame.Surface, frame_tick: int) -> None:
        draw_he_effects(
            surface=surface,
            frame_tick=frame_tick,
            utility_timeline=self.utility_timeline,
            world_to_px=self.world_to_px,
            he_animation_frames=self.he_animation_frames,
        )

    def _draw_ground_bomb(self, surface: pygame.Surface, frame_tick: int) -> None:
        draw_ground_bomb(
            surface=surface,
            overlay_size=(self.width, self.height),
            frame_tick=frame_tick,
            tickrate=self.tickrate,
            planted_duration_seconds=BOMB_PLANTED_DURATION_SECONDS,
            defuse_shake_ticks=DEFUSE_SHAKE_TICKS,
            bomb_tracker=self.bomb_tracker,
            world_to_px=self.world_to_px,
            c4_icons=self.c4_icons,
            defused_glow_color=C4_DEFUSED_GLOW_COLOR,
            blit_icon_with_shadow=self._blit_icon_with_shadow,
            blit_icon_with_glow=self._blit_icon_with_glow,
        )
        total_ticks = max(1, int(round(self.tickrate * BOMB_PLANTED_DURATION_SECONDS)))
        render_state = self.bomb_tracker.render_state_at(
            frame_tick,
            planted_total_ticks=total_ticks,
            abort_shake_ticks=DEFUSE_SHAKE_TICKS,
        )
        if render_state.icon_state == "planted" and render_state.world_position is not None:
            px, py = self.world_to_px(*render_state.world_position)
            draw_defuse_progress(
                surface=surface,
                overlay_size=(self.width, self.height),
                center=(int(round(px)), int(round(py))),
                visual=render_state.defuse_visual,
                defuse_bar_glow=DEFUSE_BAR_GLOW,
                defuse_bar_shadow=DEFUSE_BAR_SHADOW,
                defuse_bar_color=DEFUSE_BAR_COLOR,
            )

    def _draw_plant_attempts(self, surface: pygame.Surface, frame_tick: int) -> None:
        draw_plant_attempts(
            surface=surface,
            overlay_size=(self.width, self.height),
            frame_tick=frame_tick,
            tickrate=self.tickrate,
            planted_duration_seconds=BOMB_PLANTED_DURATION_SECONDS,
            defuse_shake_ticks=DEFUSE_SHAKE_TICKS,
            bomb_tracker=self.bomb_tracker,
            world_to_px=self.world_to_px,
            c4_icons=self.c4_icons,
        )

    def _draw_carried_bomb_icon(self, surface: pygame.Surface, player: str, center: tuple[int, int], frame_tick: int) -> None:
        draw_carried_bomb_icon(
            surface=surface,
            frame_tick=frame_tick,
            tickrate=self.tickrate,
            planted_duration_seconds=BOMB_PLANTED_DURATION_SECONDS,
            defuse_shake_ticks=DEFUSE_SHAKE_TICKS,
            bomb_tracker=self.bomb_tracker,
            player=player,
            center=center,
            c4_icons=self.c4_icons,
            blit_icon_with_shadow=self._blit_icon_with_shadow,
        )

    def _draw_defuser_icon(self, surface: pygame.Surface, player: str, center: tuple[int, int], frame_tick: int) -> None:
        if self.defuser_icon is None:
            return
        timeline = self._player_timeline(player)
        frame = None if timeline is None else timeline.frame_at(frame_tick)
        if frame is None or not frame.has_defuser or frame.team_num != 3:
            return
        self._blit_icon_with_shadow(surface, self.defuser_icon, (center[0] - 8, center[1] + 8))

    def _player_presentation(self, player: str, frame_tick: int) -> PlayerFramePresentation | None:
        timeline = self._player_timeline(player)
        if timeline is None:
            return None
        current = timeline.frame_at(frame_tick)
        if current is None:
            return None
        return assemble_player_frame_presentation(
            player=player,
            player_number=self.player_numbers[player],
            frame_tick=frame_tick,
            timeline=timeline,
            round_players=self.round_players,
            round_start_tick=self.round_start_tick,
            trail=self.trail,
            damage_flash_duration_ticks=self.damage_flash_duration_ticks,
            fire_flash_duration_ticks=self.fire_flash_duration_ticks,
            hit_match_window_ticks=self.hit_match_window_ticks,
            base_color=team_color(current.team_num),
        )

    def _draw_player_death(self, surface: pygame.Surface, presentation: PlayerFramePresentation) -> None:
        if presentation.death is None:
            return
        death_px, death_py = self.world_to_px(*presentation.death.world_position)
        draw_death_marker(surface=surface, px=death_px, py=death_py, color=presentation.base_color)
        draw_player_id_label(
            surface=surface,
            font=self.small_font,
            px=death_px,
            py=death_py,
            player_label=presentation.death.label,
            color=presentation.base_color,
        )

    def _draw_player_tracer_and_flash(self, surface: pygame.Surface, presentation: PlayerFramePresentation) -> None:
        tracer = presentation.tracer
        if tracer is None:
            return
        px, py = self.world_to_px(*presentation.world_position)
        yaw = tracer.yaw
        muzzle_px, muzzle_py = offset_point(px, py, yaw, 8.0)
        self._draw_player_tracer_line(surface, tracer=tracer, start_x=muzzle_px, start_y=muzzle_py)
        draw_muzzle_flash(
            surface=surface,
            muzzle_flash_sprite=self.muzzle_flash_sprite,
            muzzle_flash_anchor=self.muzzle_flash_anchor,
            muzzle_px=muzzle_px,
            muzzle_py=muzzle_py,
            yaw=yaw,
            fade=tracer.flash_fade,
            scale_reference_px=self.world_dist_to_px(48.0),
        )

    def _draw_player_tracer_line(self, surface: pygame.Surface, *, tracer, start_x: float, start_y: float) -> None:
        if tracer.hit_position_world is None:
            tracer_length = max(48.0, self.world_dist_to_px(320.0))
            end_x, end_y = offset_point(start_x, start_y, tracer.yaw, tracer_length)
        else:
            end_x, end_y = self.world_to_px(*tracer.hit_position_world)
        if tracer.team_num == 2:
            tracer_color = TRACER_T_COLOR
        elif tracer.team_num == 3:
            tracer_color = TRACER_CT_COLOR
        else:
            tracer_color = TRACER_NEUTRAL_COLOR
        draw_tracer_line(
            surface=surface,
            overlay_size=(self.width, self.height),
            start_x=start_x,
            start_y=start_y,
            end_x=end_x,
            end_y=end_y,
            tracer_color=tracer_color,
        )
