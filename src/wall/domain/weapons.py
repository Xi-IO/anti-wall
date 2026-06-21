from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from wall.paths import PROJECT_ROOT


BASE_WEAPONS_JSON = PROJECT_ROOT / "base_weapons.json"


@dataclass(frozen=True)
class WeaponCategory:
    id: str
    name: str


@dataclass(frozen=True)
class SoundProfile:
    fire_radius: float | None = None
    reload_radius: float | None = None
    zoom_radius: float | None = None
    drop_radius: float | None = None
    pin_pull_radius: float | None = None
    global_fire: bool = False
    suppressed: bool = False


@dataclass(frozen=True)
class WeaponSpec:
    def_index: int
    weapon_id: str
    name: str
    category: WeaponCategory
    description: str = ""
    image_url: str | None = None
    can_zoom: bool = False
    has_silencer: bool = False
    sound: SoundProfile = field(default_factory=SoundProfile)
    raw: dict[str, Any] = field(default_factory=dict)


def _load_base_weapon_rows(json_path: Path = BASE_WEAPONS_JSON) -> list[dict[str, Any]]:
    if not json_path.exists():
        return []
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected a top-level list in {json_path}")
    rows: list[dict[str, Any]] = []
    for item in payload:
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _weapon_id_from_row(row: dict[str, Any]) -> str:
    raw_id = str(row.get("id", "") or "").strip()
    if raw_id.startswith("base_weapon-"):
        return raw_id.removeprefix("base_weapon-")
    return raw_id


def _category_from_row(row: dict[str, Any]) -> WeaponCategory:
    category = row.get("category")
    if isinstance(category, dict):
        return WeaponCategory(
            id=str(category.get("id", "") or ""),
            name=str(category.get("name", "") or ""),
        )
    return WeaponCategory(id="", name="")


def weapon_spec_from_row(
    row: dict[str, Any],
    *,
    sound: SoundProfile | None = None,
    can_zoom: bool = False,
    has_silencer: bool = False,
) -> WeaponSpec:
    def_index = int(row["def_index"])
    return WeaponSpec(
        def_index=def_index,
        weapon_id=_weapon_id_from_row(row),
        name=str(row.get("name", "") or ""),
        description=str(row.get("description", "") or ""),
        image_url=str(row.get("image", "") or "") or None,
        category=_category_from_row(row),
        can_zoom=can_zoom,
        has_silencer=has_silencer,
        sound=sound or SoundProfile(),
        raw=dict(row),
    )


def load_base_weapon_specs(json_path: Path = BASE_WEAPONS_JSON) -> dict[int, WeaponSpec]:
    specs: dict[int, WeaponSpec] = {}
    for row in _load_base_weapon_rows(json_path):
        if "def_index" not in row:
            continue
        spec = weapon_spec_from_row(row)
        specs[spec.def_index] = spec
    return specs


def merge_weapon_specs(
    base_specs: dict[int, WeaponSpec],
    overrides: dict[int, dict[str, Any]],
) -> dict[int, WeaponSpec]:
    merged = dict(base_specs)
    for def_index, override in overrides.items():
        base = merged.get(def_index)
        if base is None:
            continue
        sound_override = override.get("sound", {})
        if not isinstance(sound_override, dict):
            sound_override = {}
        merged[def_index] = WeaponSpec(
            def_index=base.def_index,
            weapon_id=str(override.get("weapon_id", base.weapon_id)),
            name=str(override.get("name", base.name)),
            description=str(override.get("description", base.description)),
            image_url=override.get("image_url", base.image_url),
            category=override.get("category", base.category),
            can_zoom=bool(override.get("can_zoom", base.can_zoom)),
            has_silencer=bool(override.get("has_silencer", base.has_silencer)),
            sound=SoundProfile(
                fire_radius=sound_override.get("fire_radius", base.sound.fire_radius),
                reload_radius=sound_override.get("reload_radius", base.sound.reload_radius),
                zoom_radius=sound_override.get("zoom_radius", base.sound.zoom_radius),
                drop_radius=sound_override.get("drop_radius", base.sound.drop_radius),
                pin_pull_radius=sound_override.get("pin_pull_radius", base.sound.pin_pull_radius),
                global_fire=bool(sound_override.get("global_fire", base.sound.global_fire)),
                suppressed=bool(sound_override.get("suppressed", base.sound.suppressed)),
            ),
            raw=base.raw,
        )
    return merged


def find_weapon_spec(specs: dict[int, WeaponSpec], def_index: int | float | None) -> WeaponSpec | None:
    if def_index is None:
        return None
    try:
        key = int(def_index)
    except (TypeError, ValueError):
        return None
    return specs.get(key)
