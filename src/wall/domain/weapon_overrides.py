from __future__ import annotations

from typing import Any


DEFAULT_LOUD_FIRE_RADIUS = 5000.0
DEFAULT_RELOAD_RADIUS = 550.0
DEFAULT_DROP_RADIUS = 650.0
DEFAULT_ZOOM_RADIUS = 275.0

SUPPRESSED_PISTOL_FIRE_RADIUS = 600.0
SUPPRESSED_RIFLE_FIRE_RADIUS = 800.0
SUPPRESSED_SMG_FIRE_RADIUS = 800.0
ZEUS_FIRE_RADIUS = 900.0

GRENADE_PIN_PULL_RADIUS = 450.0
GRENADE_DROP_RADIUS = 550.0


def loud_weapon() -> dict[str, Any]:
    return {
        "sound": {
            "fire_radius": DEFAULT_LOUD_FIRE_RADIUS,
            "reload_radius": DEFAULT_RELOAD_RADIUS,
            "drop_radius": DEFAULT_DROP_RADIUS,
            "global_fire": True,
        }
    }


def zoom_weapon() -> dict[str, Any]:
    return {
        "can_zoom": True,
        "sound": {
            "fire_radius": DEFAULT_LOUD_FIRE_RADIUS,
            "reload_radius": DEFAULT_RELOAD_RADIUS,
            "zoom_radius": DEFAULT_ZOOM_RADIUS,
            "drop_radius": DEFAULT_DROP_RADIUS,
            "global_fire": True,
        },
    }


def suppressed_weapon(fire_radius: float) -> dict[str, Any]:
    return {
        "has_silencer": True,
        "sound": {
            "fire_radius": fire_radius,
            "reload_radius": DEFAULT_RELOAD_RADIUS,
            "drop_radius": DEFAULT_DROP_RADIUS,
            "suppressed": True,
        },
    }


def quiet_equipment(fire_radius: float | None = None) -> dict[str, Any]:
    sound: dict[str, Any] = {
        "drop_radius": DEFAULT_DROP_RADIUS,
    }
    if fire_radius is not None:
        sound["fire_radius"] = fire_radius
    return {"sound": sound}


def grenade_item() -> dict[str, Any]:
    return {
        "sound": {
            "pin_pull_radius": GRENADE_PIN_PULL_RADIUS,
            "drop_radius": GRENADE_DROP_RADIUS,
        }
    }


# Project-local gameplay/audio interpretation layered on top of base_weapons.json.
# These values are viewer / sound-visualization assumptions, not authoritative CS2 engine data.
#
# Semantics:
# - global_fire=True means the shot is treated as globally audible for rules / inference.
# - fire_radius is primarily the display radius and the local audibility radius when
#   global_fire is False.
# - suppressed=True marks silenced weapons and should not be combined with global_fire.
WEAPON_OVERRIDES: dict[int, dict[str, Any]] = {
    # Pistols
    1: loud_weapon(),   # Desert Eagle
    2: loud_weapon(),   # Dual Berettas
    3: loud_weapon(),   # Five-SeveN
    4: loud_weapon(),   # Glock-18
    30: loud_weapon(),  # Tec-9
    32: loud_weapon(),  # P2000
    36: loud_weapon(),  # P250
    61: suppressed_weapon(SUPPRESSED_PISTOL_FIRE_RADIUS),  # USP-S
    63: loud_weapon(),  # CZ75-Auto
    64: loud_weapon(),  # R8 Revolver

    # Rifles
    7: loud_weapon(),   # AK-47
    8: zoom_weapon(),   # AUG
    10: loud_weapon(),  # FAMAS
    13: loud_weapon(),  # Galil AR
    16: loud_weapon(),  # M4A4
    39: zoom_weapon(),  # SG 553
    60: suppressed_weapon(SUPPRESSED_RIFLE_FIRE_RADIUS),  # M4A1-S

    # Snipers
    9: zoom_weapon(),   # AWP
    11: zoom_weapon(),  # G3SG1
    38: zoom_weapon(),  # SCAR-20
    40: zoom_weapon(),  # SSG 08

    # SMGs
    17: loud_weapon(),   # MAC-10
    19: loud_weapon(),   # P90
    23: suppressed_weapon(SUPPRESSED_SMG_FIRE_RADIUS),  # MP5-SD
    24: loud_weapon(),   # UMP-45
    26: loud_weapon(),   # PP-Bizon
    33: loud_weapon(),   # MP7
    34: loud_weapon(),   # MP9

    # Heavy
    14: loud_weapon(),  # M249
    25: loud_weapon(),  # XM1014
    27: loud_weapon(),  # MAG-7
    28: loud_weapon(),  # Negev
    29: loud_weapon(),  # Sawed-Off
    35: loud_weapon(),  # Nova

    # Equipment
    31: quiet_equipment(ZEUS_FIRE_RADIUS),  # Zeus x27

    # Grenades / utility
    # These are mainly useful if the sound system later models pin-pull/drop audio.
    43: grenade_item(),  # Flashbang
    44: grenade_item(),  # HE Grenade
    45: grenade_item(),  # Smoke Grenade
    46: grenade_item(),  # Molotov
    47: grenade_item(),  # Decoy Grenade
    48: grenade_item(),  # Incendiary Grenade
    49: quiet_equipment(),  # C4
}
