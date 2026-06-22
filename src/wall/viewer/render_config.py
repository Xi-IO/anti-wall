from __future__ import annotations

from wall.domain.sound import SoundPresentationConfig


TRACER_T_COLOR = (255, 238, 170, 210)
TRACER_CT_COLOR = (120, 205, 255, 210)
TRACER_NEUTRAL_COLOR = (235, 235, 235, 200)
SMOKE_RADIUS_WORLD = 176.0
SMOKE_DEPLOY_TICKS = 18
HE_RADIUS_WORLD = 384.0
HE_SMOKE_HOLE_RECOVERY_DELAY_SECONDS = 1.5
HE_SMOKE_HOLE_FULL_RECOVERY_SECONDS = 3.5
HE_SMOKE_HOLE_FEATHER_RATIO = 0.35
INFERNO_GROWTH_SECONDS = 2.0
INFERNO_INITIAL_RADIUS_SCALE = 0.45
SMOKE_PULSE_FREQUENCY = 0.075
SMOKE_PULSE_AMPLITUDE = 0.02
GRENADE_TYPE_STYLES = {
    "CSmokeGrenadeProjectile": {"color": (210, 210, 210), "radius": 5},
    "CFlashbangProjectile": {"color": (245, 245, 200), "radius": 4},
    "CHEGrenadeProjectile": {"color": (110, 190, 110), "radius": 4},
    "CMolotovProjectile": {"color": (255, 140, 60), "radius": 4},
    "CIncendiaryGrenadeProjectile": {"color": (255, 110, 50), "radius": 4},
    "CDecoyProjectile": {"color": (150, 150, 150), "radius": 4},
}
GRENADE_ICON_PATHS = {
    "CSmokeGrenadeProjectile": "icons/equipment/smokegrenade.png",
    "CFlashbangProjectile": "icons/equipment/flashbang.png",
    "CHEGrenadeProjectile": "icons/equipment/frag_grenade.png",
    "CMolotovProjectile": "icons/equipment/firebomb.png",
    "CDecoyProjectile": "icons/equipment/decoy.png",
}
C4_CARRIED_COLOR = (217, 205, 33)
C4_DROPPED_COLOR = (255, 255, 255)
C4_PLANTED_COLOR = (220, 72, 72)
C4_DEFUSED_COLOR = (135, 255, 89)
C4_DEFUSED_GLOW_COLOR = (200, 255, 178, 150)
DEFUSE_BAR_COLOR = C4_DEFUSED_COLOR
DEFUSE_BAR_SHADOW = (34, 54, 34, 220)
DEFUSE_BAR_GLOW = (170, 255, 150, 120)
DEFUSE_SHAKE_TICKS = 20
BOMB_PLANTED_DURATION_SECONDS = 40.0
SOUND_MAX_DISPLAY_RADIUS_RATIO = 0.40
# These remain viewer-only because they control surface drawing, not gameplay semantics.
SOUND_FILL_ALPHA = 28
SOUND_BASE_ALPHA = 170
SOUND_GLOBAL_ALPHA_BOOST = 24
SOUND_START_EXPAND_TICKS = 4
SOUND_END_SHRINK_TICKS = 4
SOUND_LABEL_DISTANCE_PX = 6
SOUND_SUPPRESSION_DISTANCE_PX = 44.0
SOUND_PRESENTATION = SoundPresentationConfig(
    max_display_radius_ratio=SOUND_MAX_DISPLAY_RADIUS_RATIO,
    base_alpha=SOUND_BASE_ALPHA,
    global_alpha_boost=SOUND_GLOBAL_ALPHA_BOOST,
    start_expand_ticks=SOUND_START_EXPAND_TICKS,
    end_shrink_ticks=SOUND_END_SHRINK_TICKS,
    suppression_distance_px=SOUND_SUPPRESSION_DISTANCE_PX,
)
