from __future__ import annotations

import numpy as np
import pandas as pd

from wall.domain.weapon_overrides import WEAPON_OVERRIDES
from wall.domain.weapons import find_weapon_spec, load_base_weapon_specs, merge_weapon_specs


WEAPON_SPECS = merge_weapon_specs(load_base_weapon_specs(), WEAPON_OVERRIDES)
GUNFIRE_BURST_GAP_TICKS_UNKNOWN = 16
GUNFIRE_BURST_GAP_TICKS_AUTOMATIC = 12
GUNFIRE_BURST_GAP_TICKS_PISTOL = 40
GUNFIRE_BURST_GAP_TICKS_SNIPER_OR_DEAGLE = 32

SOUND_EFFECT_COLUMNS = [
    "round_id",
    "effect_id",
    "emitter_type",
    "source_type",
    "source_id",
    "start_tick",
    "end_tick",
    "sound_class",
    "sound_action",
    "item_name",
    "radius",
    "position_mode",
    "x",
    "y",
    "z",
    "raw_source",
    "shot_count",
]


def _empty_sound_effects() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "round_id": pd.Series(dtype="int64"),
            "effect_id": pd.Series(dtype="string"),
            "emitter_type": pd.Series(dtype="string"),
            "source_type": pd.Series(dtype="string"),
            "source_id": pd.Series(dtype="string"),
            "start_tick": pd.Series(dtype="int64"),
            "end_tick": pd.Series(dtype="int64"),
            "sound_class": pd.Series(dtype="string"),
            "sound_action": pd.Series(dtype="string"),
            "item_name": pd.Series(dtype="string"),
            "radius": pd.Series(dtype="float64"),
            "position_mode": pd.Series(dtype="string"),
            "x": pd.Series(dtype="float64"),
            "y": pd.Series(dtype="float64"),
            "z": pd.Series(dtype="float64"),
            "raw_source": pd.Series(dtype="string"),
            "shot_count": pd.Series(dtype="Int64"),
        }
    )


def _normalize_text(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip()
    return text.fillna("")


def _clean_item_name(value: object) -> str:
    text = str(value or "").strip().lower()
    if text in {"", "nan", "none", "<na>"}:
        return ""
    if text.startswith("weapon_"):
        text = text[len("weapon_") :]
    if text.endswith("_projectile"):
        text = text[: -len("_projectile")]
    return text


def _coalesce_numeric(df: pd.DataFrame, columns: list[str]) -> pd.Series:
    out = pd.Series(np.nan, index=df.index, dtype="float64")
    for column in columns:
        if column in df.columns:
            values = pd.to_numeric(df[column], errors="coerce")
            out = out.where(out.notna(), values)
    return out


def _numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(df.get(column, pd.Series(index=df.index, dtype="float64")), errors="coerce")


def _source_id_for_player(names: pd.Series, steamids: pd.Series) -> pd.Series:
    name_values = _normalize_text(names)
    steamid_values = _normalize_text(steamids)
    return steamid_values.where(steamid_values != "", "name:" + name_values)


def _event_round_id(events: pd.DataFrame) -> pd.Series:
    if "inferred_round_id" not in events.columns:
        return pd.Series(pd.NA, index=events.index, dtype="Int64")
    return pd.to_numeric(events["inferred_round_id"], errors="coerce").astype("Int64")


def _base_effect_frame(events: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=events.index)
    out["round_id"] = _event_round_id(events)
    out["effect_id"] = pd.Series("", index=events.index, dtype="string")
    out["source_id"] = pd.Series("", index=events.index, dtype="string")
    out["item_name"] = pd.Series("", index=events.index, dtype="string")
    out["x"] = pd.Series(np.nan, index=events.index, dtype="float64")
    out["y"] = pd.Series(np.nan, index=events.index, dtype="float64")
    out["z"] = pd.Series(np.nan, index=events.index, dtype="float64")
    out["shot_count"] = pd.Series(pd.NA, index=events.index, dtype="Int64")
    return out


def _normalize_impulse_effects(
    events: pd.DataFrame,
    *,
    source_type: str,
    sound_class: str,
    sound_action: str,
    item_name: str = "",
    radius: float,
    position_mode: str,
    raw_source: str,
    source_id: pd.Series | None = None,
    x_candidates: list[str] | None = None,
    y_candidates: list[str] | None = None,
    z_candidates: list[str] | None = None,
) -> pd.DataFrame:
    if events.empty or "tick" not in events.columns:
        return _empty_sound_effects()
    out = _base_effect_frame(events)
    ticks = pd.to_numeric(events["tick"], errors="coerce").astype("Int64")
    out["emitter_type"] = "impulse"
    out["source_type"] = source_type
    out["start_tick"] = ticks
    out["end_tick"] = ticks
    out["sound_class"] = sound_class
    out["sound_action"] = sound_action
    out["item_name"] = item_name
    out["radius"] = float(radius)
    out["position_mode"] = position_mode
    out["raw_source"] = raw_source
    if source_id is not None:
        out["source_id"] = source_id.astype("string").fillna("")
    if position_mode == "event_snapshot":
        out["x"] = _coalesce_numeric(events, x_candidates or [])
        out["y"] = _coalesce_numeric(events, y_candidates or [])
        out["z"] = _coalesce_numeric(events, z_candidates or [])
    out = out.dropna(subset=["round_id", "start_tick", "end_tick"]).copy()
    return out


def _finalize_sound_effects(table: pd.DataFrame) -> pd.DataFrame:
    if table.empty:
        return _empty_sound_effects()
    out = table.copy()
    out["round_id"] = pd.to_numeric(out["round_id"], errors="coerce").astype("Int64")
    out["start_tick"] = pd.to_numeric(out["start_tick"], errors="coerce").astype("Int64")
    out["end_tick"] = pd.to_numeric(out["end_tick"], errors="coerce").astype("Int64")
    out["radius"] = pd.to_numeric(out["radius"], errors="coerce")
    out["x"] = pd.to_numeric(out["x"], errors="coerce")
    out["y"] = pd.to_numeric(out["y"], errors="coerce")
    out["z"] = pd.to_numeric(out["z"], errors="coerce")
    if "shot_count" not in out.columns:
        out["shot_count"] = pd.Series(pd.NA, index=out.index, dtype="Int64")
    out["shot_count"] = pd.to_numeric(out["shot_count"], errors="coerce").astype("Int64")
    for column in (
        "effect_id",
        "emitter_type",
        "source_type",
        "source_id",
        "sound_class",
        "sound_action",
        "item_name",
        "position_mode",
        "raw_source",
    ):
        out[column] = out[column].astype("string").fillna("")
    out = out.dropna(subset=["round_id", "start_tick", "end_tick", "radius"]).copy()
    out["round_id"] = out["round_id"].astype("int64")
    out["start_tick"] = out["start_tick"].astype("int64")
    out["end_tick"] = out["end_tick"].astype("int64")
    out = out[out["end_tick"] >= out["start_tick"]].copy()
    out = out.sort_values(
        ["round_id", "start_tick", "end_tick", "sound_class", "sound_action", "source_type", "source_id", "raw_source"]
    ).reset_index(drop=True)
    out["effect_id"] = pd.Series(
        [f"snd_r{int(round_id):02d}_{index:06d}" for index, round_id in enumerate(out["round_id"].tolist(), start=1)],
        index=out.index,
        dtype="string",
    )
    return out.loc[:, SOUND_EFFECT_COLUMNS]


def _gunfire_burst_gap_ticks_for_item(item_name: object) -> int:
    cleaned = _clean_item_name(item_name)
    if cleaned in {"awp", "ssg08", "scar20", "g3sg1", "deagle"}:
        return GUNFIRE_BURST_GAP_TICKS_SNIPER_OR_DEAGLE
    if cleaned in {"glock", "hkp2000", "usp_silencer", "p250", "fiveseven", "tec9", "cz75a", "elite", "revolver"}:
        return GUNFIRE_BURST_GAP_TICKS_PISTOL
    if cleaned in {
        "ak47",
        "m4a1",
        "m4a1_silencer",
        "famas",
        "galilar",
        "aug",
        "sg553",
        "mac10",
        "mp9",
        "mp7",
        "ump45",
        "bizon",
        "p90",
        "m249",
        "negev",
    }:
        return GUNFIRE_BURST_GAP_TICKS_AUTOMATIC
    return GUNFIRE_BURST_GAP_TICKS_UNKNOWN


def _compress_gunfire_bursts(
    gunfire_effects: pd.DataFrame,
) -> pd.DataFrame:
    if gunfire_effects.empty:
        return gunfire_effects
    work = gunfire_effects.copy()
    work["round_id"] = pd.to_numeric(work["round_id"], errors="coerce")
    work["start_tick"] = pd.to_numeric(work["start_tick"], errors="coerce")
    work["end_tick"] = pd.to_numeric(work["end_tick"], errors="coerce")
    work = work.dropna(subset=["round_id", "start_tick", "end_tick"]).copy()
    if work.empty:
        return work
    work = work.sort_values(["round_id", "source_id", "item_name", "start_tick", "end_tick"]).copy()
    burst_keys = ["round_id", "source_id", "item_name"]
    tick_gap = work.groupby(burst_keys, sort=False)["start_tick"].diff()
    work["burst_gap_ticks"] = work["item_name"].map(_gunfire_burst_gap_ticks_for_item).astype("int64")
    work["burst_start"] = tick_gap.isna() | (tick_gap > work["burst_gap_ticks"])
    work["burst_id"] = work.groupby(burst_keys, sort=False)["burst_start"].cumsum().astype("int64")
    grouped = (
        work.groupby(burst_keys + ["burst_id"], sort=False)
        .agg(
            emitter_type=("emitter_type", "first"),
            source_type=("source_type", "first"),
            start_tick=("start_tick", "min"),
            end_tick=("end_tick", "max"),
            sound_class=("sound_class", "first"),
            sound_action=("sound_action", "first"),
            radius=("radius", "first"),
            position_mode=("position_mode", "first"),
            raw_source=("raw_source", "first"),
            shot_count=("start_tick", "size"),
        )
        .reset_index()
    )
    grouped["emitter_type"] = "continuous"
    grouped["effect_id"] = ""
    grouped["x"] = np.nan
    grouped["y"] = np.nan
    grouped["z"] = np.nan
    grouped["shot_count"] = grouped["shot_count"].astype("Int64")
    return grouped.loc[:, SOUND_EFFECT_COLUMNS]


def build_movement_sound_effects(ticks: pd.DataFrame) -> pd.DataFrame:
    required = {
        "tick",
        "name",
        "steamid",
        "ducking",
        "is_airborne",
        "velocity_X",
        "velocity_Y",
        "inferred_round_id",
    }
    if ticks.empty or not required.issubset(ticks.columns):
        return _empty_sound_effects()
    work = ticks.loc[:, list(required)].copy()
    work["tick"] = pd.to_numeric(work["tick"], errors="coerce")
    work["round_id"] = pd.to_numeric(work["inferred_round_id"], errors="coerce")
    work["name"] = _normalize_text(work["name"])
    work["steamid_key"] = _normalize_text(work["steamid"])
    work["velocity_X"] = pd.to_numeric(work["velocity_X"], errors="coerce")
    work["velocity_Y"] = pd.to_numeric(work["velocity_Y"], errors="coerce")
    work["ducking"] = work["ducking"].fillna(False).astype(bool)
    work["is_airborne"] = work["is_airborne"].fillna(False).astype(bool)
    work = work.dropna(subset=["tick", "round_id"]).sort_values(["round_id", "steamid_key", "name", "tick"]).copy()
    work["speed_xy"] = np.sqrt(work["velocity_X"].fillna(0.0) ** 2 + work["velocity_Y"].fillna(0.0) ** 2)
    work["is_audible_move"] = (
        (work["speed_xy"] > 135.0)
        & (work["speed_xy"] < 320.0)
        & (~work["is_airborne"])
        & (~work["ducking"])
    )
    moving = work[work["is_audible_move"]].copy()
    if moving.empty:
        return _empty_sound_effects()
    player_keys = ["round_id", "steamid_key", "name"]
    tick_gap = moving.groupby(player_keys, sort=False)["tick"].diff()
    moving["segment_start"] = tick_gap.isna() | (tick_gap > 1)
    moving["segment_id"] = moving.groupby(player_keys, sort=False)["segment_start"].cumsum().astype("int64")
    grouped = (
        moving.groupby(player_keys + ["segment_id"], sort=False)
        .agg(start_tick=("tick", "min"), end_tick=("tick", "max"))
        .reset_index()
    )
    out = pd.DataFrame(index=grouped.index)
    out["round_id"] = grouped["round_id"].astype("int64")
    out["effect_id"] = ""
    out["emitter_type"] = "continuous"
    out["source_type"] = "player"
    out["source_id"] = _source_id_for_player(grouped["name"], grouped["steamid_key"])
    out["start_tick"] = grouped["start_tick"].astype("int64")
    out["end_tick"] = grouped["end_tick"].astype("int64")
    out["sound_class"] = "movement"
    out["sound_action"] = "locomotion"
    out["item_name"] = ""
    out["radius"] = 850.0
    out["position_mode"] = "entity_at_tick"
    out["x"] = np.nan
    out["y"] = np.nan
    out["z"] = np.nan
    out["raw_source"] = "inferred_movement"
    return _finalize_sound_effects(out)


def build_player_footstep_sound_effects(footsteps: pd.DataFrame) -> pd.DataFrame:
    if footsteps.empty:
        return _empty_sound_effects()
    return _finalize_sound_effects(
        _normalize_impulse_effects(
            footsteps,
            source_type="player",
            sound_class="movement",
            sound_action="hard_step",
            radius=850.0,
            position_mode="entity_at_tick",
            raw_source="player_footstep",
            source_id=_source_id_for_player(
                footsteps.get("user_name", pd.Series(index=footsteps.index, dtype="object")),
                footsteps.get("user_steamid", pd.Series(index=footsteps.index, dtype="object")),
            ),
        )
    )


def build_landing_sound_effects(ticks: pd.DataFrame) -> pd.DataFrame:
    required = {"tick", "name", "steamid", "Z", "is_airborne", "velocity_Z", "inferred_round_id"}
    if ticks.empty or not required.issubset(ticks.columns):
        return _empty_sound_effects()
    selected = list(required)
    work = ticks[selected].copy()
    work["steamid_key"] = _normalize_text(work["steamid"])
    work["name"] = _normalize_text(work["name"])
    work["tick"] = pd.to_numeric(work["tick"], errors="coerce")
    work["Z"] = pd.to_numeric(work["Z"], errors="coerce")
    work["velocity_Z"] = pd.to_numeric(work["velocity_Z"], errors="coerce")
    work["round_id"] = pd.to_numeric(work["inferred_round_id"], errors="coerce")
    work["is_airborne"] = work["is_airborne"].fillna(False).astype(bool)
    work = work.dropna(subset=["tick", "round_id"]).sort_values(["round_id", "steamid_key", "name", "tick"]).copy()
    player_keys = ["round_id", "steamid_key", "name"]
    prev_airborne = work.groupby(player_keys, sort=False)["is_airborne"].shift(1).fillna(False).astype(bool)
    airborne_start = work["is_airborne"] & ~prev_airborne
    airborne_run_id = airborne_start.groupby([work["round_id"], work["steamid_key"], work["name"]]).cumsum()
    work["airborne_run_id"] = airborne_run_id.where(work["is_airborne"], np.nan)
    airborne_rows = work[work["is_airborne"] & work["airborne_run_id"].notna()].copy()
    if airborne_rows.empty:
        return _empty_sound_effects()
    airborne_summary = (
        airborne_rows.groupby(player_keys + ["airborne_run_id"], sort=False)
        .agg(peak_height=("Z", "max"), min_velocity_z=("velocity_Z", "min"), max_velocity_z=("velocity_Z", "max"), airborne_ticks=("tick", "size"))
        .reset_index()
    )
    airborne_summary["impact_speed_z"] = airborne_summary["min_velocity_z"].abs()
    airborne_summary["had_upward_launch"] = airborne_summary["max_velocity_z"] > 200.0
    landing_rows = work[(~work["is_airborne"]) & prev_airborne].copy()
    if landing_rows.empty:
        return _empty_sound_effects()
    landing_rows["airborne_run_id"] = airborne_run_id.groupby([work["round_id"], work["steamid_key"], work["name"]]).shift(1)[landing_rows.index]
    landing_rows = landing_rows[landing_rows["airborne_run_id"].notna()].copy()
    if landing_rows.empty:
        return _empty_sound_effects()
    merged = landing_rows.merge(airborne_summary, on=player_keys + ["airborne_run_id"], how="left")
    merged["vertical_drop"] = merged["peak_height"] - merged["Z"]
    merged = merged[merged["airborne_ticks"] >= 2].copy()
    merged["is_fall_land"] = merged["impact_speed_z"] > 300.0
    merged["is_jump_land"] = merged["had_upward_launch"] & ((merged["impact_speed_z"] >= 200.0) | (merged["vertical_drop"] >= 12.0))
    merged = merged[merged["is_fall_land"] | merged["is_jump_land"]].copy()
    if merged.empty:
        return _empty_sound_effects()
    out = pd.DataFrame(index=merged.index)
    out["round_id"] = merged["round_id"].astype("int64")
    out["effect_id"] = ""
    out["emitter_type"] = "impulse"
    out["source_type"] = "player"
    out["source_id"] = _source_id_for_player(merged["name"], merged["steamid_key"])
    out["start_tick"] = merged["tick"].astype("int64")
    out["end_tick"] = merged["tick"].astype("int64")
    out["sound_class"] = "movement"
    out["sound_action"] = "hard_step"
    out["item_name"] = ""
    out["radius"] = 1062.0
    out["position_mode"] = "entity_at_tick"
    out["x"] = np.nan
    out["y"] = np.nan
    out["z"] = np.nan
    out["raw_source"] = "inferred_landing"
    return _finalize_sound_effects(out)


def build_gunfire_sound_effects(fires: pd.DataFrame) -> pd.DataFrame:
    if fires.empty or "tick" not in fires.columns:
        return _empty_sound_effects()
    out = _normalize_impulse_effects(
        fires,
        source_type="player",
        sound_class="weapon",
        sound_action="gunfire",
        radius=1600.0,
        position_mode="entity_at_tick",
        raw_source="fire_bullets",
        source_id=_source_id_for_player(
            fires.get("user_name", pd.Series(index=fires.index, dtype="object")),
            fires.get("user_steamid", pd.Series(index=fires.index, dtype="object")),
        ),
    )
    item_def_index = _numeric_series(fires, "item_def_index")
    item_names: list[str] = []
    radii: list[float] = []
    for value in item_def_index.tolist():
        spec = find_weapon_spec(WEAPON_SPECS, value)
        if spec is None:
            item_names.append("")
            radii.append(5000.0)
            continue
        item_names.append(_clean_item_name(spec.weapon_id))
        fire_radius = spec.sound.fire_radius if spec.sound.fire_radius is not None else 5000.0
        radii.append(float(fire_radius))
    out["item_name"] = pd.Series(item_names, index=out.index, dtype="string")
    out["radius"] = radii
    return _finalize_sound_effects(_compress_gunfire_bursts(out))


def _build_weapon_impulse_effects(
    events: pd.DataFrame,
    *,
    raw_source: str,
    sound_action: str,
    default_radius: float,
) -> pd.DataFrame:
    if events.empty or "tick" not in events.columns:
        return _empty_sound_effects()
    out = _normalize_impulse_effects(
        events,
        source_type="player",
        sound_class="weapon",
        sound_action=sound_action,
        radius=default_radius,
        position_mode="entity_at_tick",
        raw_source=raw_source,
        source_id=_source_id_for_player(
            events.get("user_name", pd.Series(index=events.index, dtype="object")),
            events.get("user_steamid", pd.Series(index=events.index, dtype="object")),
        ),
    )
    defindex = _numeric_series(events, "defindex")
    item_names: list[str] = []
    radii: list[float] = []
    for value in defindex.tolist():
        spec = find_weapon_spec(WEAPON_SPECS, value)
        if spec is None:
            item_names.append("")
            radii.append(default_radius)
            continue
        item_names.append(_clean_item_name(spec.weapon_id))
        if sound_action == "reload":
            resolved = spec.sound.reload_radius if spec.sound.reload_radius is not None else default_radius
        else:
            resolved = spec.sound.zoom_radius if spec.sound.zoom_radius is not None else default_radius
        radii.append(float(resolved))
    out["item_name"] = pd.Series(item_names, index=out.index, dtype="string")
    out["radius"] = radii
    return _finalize_sound_effects(out)


def build_reload_sound_effects(weapon_reloads: pd.DataFrame) -> pd.DataFrame:
    return _build_weapon_impulse_effects(
        weapon_reloads,
        raw_source="weapon_reload",
        sound_action="reload",
        default_radius=550.0,
    )


def build_zoom_sound_effects(weapon_zooms: pd.DataFrame) -> pd.DataFrame:
    return _build_weapon_impulse_effects(
        weapon_zooms,
        raw_source="weapon_zoom",
        sound_action="zoom",
        default_radius=275.0,
    )


def build_hurt_sound_effects(hurts: pd.DataFrame) -> pd.DataFrame:
    if hurts.empty:
        return _empty_sound_effects()
    return _finalize_sound_effects(
        _normalize_impulse_effects(
            hurts,
            source_type="player",
            sound_class="damage",
            sound_action="hurt",
            radius=900.0,
            position_mode="entity_at_tick",
            raw_source="player_hurt",
            source_id=_source_id_for_player(
                hurts.get("user_name", pd.Series(index=hurts.index, dtype="object")),
                hurts.get("user_steamid", pd.Series(index=hurts.index, dtype="object")),
            ),
        )
    )


def build_item_drop_sound_effects(item_drops: pd.DataFrame) -> pd.DataFrame:
    if item_drops.empty or "tick" not in item_drops.columns:
        return _empty_sound_effects()
    defindex = _numeric_series(item_drops, "defindex")
    raw_item_name = _normalize_text(item_drops.get("item_name", pd.Series(index=item_drops.index, dtype="object"))).str.lower()
    keep_mask: list[bool] = []
    item_names: list[str] = []
    radii: list[float] = []
    for index, value in enumerate(defindex.tolist()):
        spec = find_weapon_spec(WEAPON_SPECS, value)
        weapon_id = spec.weapon_id if spec is not None else raw_item_name.iloc[index]
        cleaned_item_name = _clean_item_name(weapon_id)
        if value == 49 or cleaned_item_name == "c4" or "c4" in raw_item_name.iloc[index]:
            keep_mask.append(False)
            item_names.append("c4")
            radii.append(0.0)
            continue
        keep_mask.append(True)
        drop_radius = spec.sound.drop_radius if spec is not None and spec.sound.drop_radius is not None else 650.0
        item_names.append(cleaned_item_name)
        radii.append(float(drop_radius))
    base = _normalize_impulse_effects(
        item_drops,
        source_type="dropped_item",
        sound_class="item",
        sound_action="dropped",
        radius=650.0,
        position_mode="event_snapshot",
        raw_source="item_drop",
        x_candidates=["X", "x"],
        y_candidates=["Y", "y"],
        z_candidates=["Z", "z"],
    )
    base["item_name"] = pd.Series(item_names, index=base.index, dtype="string")
    base["radius"] = pd.Series(radii, index=base.index, dtype="float64")
    keep = pd.Series(keep_mask, index=base.index, dtype="boolean")
    out = base[keep.fillna(False)].copy().reset_index(drop=True)
    return _finalize_sound_effects(out)


def _utility_item_name(raw_source: str) -> str:
    mapping = {
        "smokegrenade_detonate": "smokegrenade",
        "flashbang_detonate": "flashbang",
        "hegrenade_detonate": "hegrenade",
        "inferno_startburn": "molotov",
    }
    return mapping.get(raw_source, "")


def build_utility_detonate_effects(events: pd.DataFrame, *, raw_source: str, sound_action: str, radius: float) -> pd.DataFrame:
    if events.empty:
        return _empty_sound_effects()
    source_ids = (
        pd.to_numeric(events.get("entityid"), errors="coerce").astype("Int64").astype("string").fillna("")
        if "entityid" in events.columns
        else pd.Series([""] * len(events), index=events.index, dtype="string")
    )
    return _finalize_sound_effects(
        _normalize_impulse_effects(
            events,
            source_type="grenade",
            sound_class="utility",
            sound_action=sound_action,
            item_name=_utility_item_name(raw_source),
            radius=radius,
            position_mode="event_snapshot",
            raw_source=raw_source,
            source_id=source_ids,
            x_candidates=["x", "X"],
            y_candidates=["y", "Y"],
            z_candidates=["z", "Z"],
        )
    )


def build_grenade_bounce_sound_effects(grenades: pd.DataFrame) -> pd.DataFrame:
    required = {"grenade_type", "grenade_entity_id", "x", "y", "z", "tick", "inferred_round_id"}
    if grenades.empty or not required.issubset(grenades.columns):
        return _empty_sound_effects()
    work = grenades.loc[:, list(required)].copy()
    work["tick"] = pd.to_numeric(work["tick"], errors="coerce")
    work["round_id"] = pd.to_numeric(work["inferred_round_id"], errors="coerce")
    work["x"] = pd.to_numeric(work["x"], errors="coerce")
    work["y"] = pd.to_numeric(work["y"], errors="coerce")
    work["z"] = pd.to_numeric(work["z"], errors="coerce")
    work["grenade_entity_id"] = pd.to_numeric(work["grenade_entity_id"], errors="coerce")
    work["grenade_type"] = work["grenade_type"].astype("string")
    work = work.dropna(subset=["tick", "round_id", "x", "y", "z", "grenade_entity_id"]).copy()
    work = work[work["grenade_type"].str.contains("Projectile", na=False)].copy()
    if work.empty:
        return _empty_sound_effects()
    work = work.sort_values(["grenade_entity_id", "tick"]).copy()
    work["prev_x"] = work.groupby("grenade_entity_id", sort=False)["x"].shift(1)
    work["prev_y"] = work.groupby("grenade_entity_id", sort=False)["y"].shift(1)
    work["prev_z"] = work.groupby("grenade_entity_id", sort=False)["z"].shift(1)
    work["next_x"] = work.groupby("grenade_entity_id", sort=False)["x"].shift(-1)
    work["next_y"] = work.groupby("grenade_entity_id", sort=False)["y"].shift(-1)
    work["next_z"] = work.groupby("grenade_entity_id", sort=False)["z"].shift(-1)
    work["vx_in"] = work["x"] - work["prev_x"]
    work["vy_in"] = work["y"] - work["prev_y"]
    work["vz_in"] = work["z"] - work["prev_z"]
    work["vx_out"] = work["next_x"] - work["x"]
    work["vy_out"] = work["next_y"] - work["y"]
    work["vz_out"] = work["next_z"] - work["z"]
    work["speed_in_xy"] = np.sqrt(work["vx_in"] ** 2 + work["vy_in"] ** 2)
    work["speed_out_xy"] = np.sqrt(work["vx_out"] ** 2 + work["vy_out"] ** 2)
    work["planar_turn"] = (work["vx_in"] * work["vx_out"]) + (work["vy_in"] * work["vy_out"])
    work["planar_turn_cos"] = work["planar_turn"] / (work["speed_in_xy"] * work["speed_out_xy"])
    work["vertical_bounce"] = (work["vz_in"] < -1.5) & (work["vz_out"] > 1.5)
    work["hard_turn"] = (
        (work["speed_in_xy"] > 1.5)
        & (work["speed_out_xy"] > 1.5)
        & work["planar_turn_cos"].notna()
        & (work["planar_turn_cos"] < 0.985)
    )
    candidates = work[work["vertical_bounce"] | work["hard_turn"]].copy()
    if candidates.empty:
        return _empty_sound_effects()
    tick_gap = candidates.groupby("grenade_entity_id", sort=False)["tick"].diff()
    candidates["cluster_start"] = tick_gap.isna() | (tick_gap > 6)
    candidates["cluster_id"] = candidates.groupby("grenade_entity_id", sort=False)["cluster_start"].cumsum().astype("int64")
    vertical_score = candidates["vertical_bounce"].astype("int64") * 1000
    impact_score = candidates["vz_out"].abs().fillna(0.0) + candidates["vz_in"].abs().fillna(0.0)
    candidates["pick_score"] = vertical_score + impact_score + candidates["speed_in_xy"].fillna(0.0) + candidates["speed_out_xy"].fillna(0.0)
    candidates = (
        candidates.sort_values(["grenade_entity_id", "cluster_id", "pick_score", "tick"], ascending=[True, True, False, True])
        .drop_duplicates(["grenade_entity_id", "cluster_id"], keep="first")
        .reset_index(drop=True)
    )
    out = pd.DataFrame(index=candidates.index)
    out["round_id"] = candidates["round_id"].astype("int64")
    out["effect_id"] = ""
    out["emitter_type"] = "impulse"
    out["source_type"] = "grenade"
    out["source_id"] = candidates["grenade_entity_id"].astype("Int64").astype("string").fillna("")
    out["start_tick"] = candidates["tick"].astype("int64")
    out["end_tick"] = candidates["tick"].astype("int64")
    out["sound_class"] = "utility"
    out["sound_action"] = "bounce"
    out["item_name"] = candidates["grenade_type"].map(_clean_item_name).astype("string")
    out["radius"] = 650.0
    out["position_mode"] = "event_snapshot"
    out["x"] = candidates["x"].astype("float64")
    out["y"] = candidates["y"].astype("float64")
    out["z"] = candidates["z"].astype("float64")
    out["raw_source"] = "grenade_bounce"
    return _finalize_sound_effects(out)


def build_bomb_dropped_sound_effects(bomb_drops: pd.DataFrame) -> pd.DataFrame:
    if bomb_drops.empty:
        return _empty_sound_effects()
    return _finalize_sound_effects(
        _normalize_impulse_effects(
            bomb_drops,
            source_type="bomb",
            sound_class="bomb",
            sound_action="dropped",
            item_name="c4",
            radius=700.0,
            position_mode="event_snapshot",
            raw_source="bomb_dropped",
            source_id=pd.Series(["c4"] * len(bomb_drops), index=bomb_drops.index, dtype="string"),
            x_candidates=["X"],
            y_candidates=["Y"],
            z_candidates=["Z"],
        )
    )


def build_bomb_player_sound_effects(
    events: pd.DataFrame,
    *,
    raw_source: str,
    sound_action: str,
    radius: float,
) -> pd.DataFrame:
    if events.empty:
        return _empty_sound_effects()
    return _finalize_sound_effects(
        _normalize_impulse_effects(
            events,
            source_type="player",
            sound_class="bomb",
            sound_action=sound_action,
            item_name="c4",
            radius=radius,
            position_mode="entity_at_tick",
            raw_source=raw_source,
            source_id=_source_id_for_player(
                events.get("user_name", pd.Series(index=events.index, dtype="object")),
                events.get("user_steamid", pd.Series(index=events.index, dtype="object")),
            ),
        )
    )


def build_bomb_snapshot_sound_effects(
    events: pd.DataFrame,
    *,
    raw_source: str,
    sound_action: str,
    radius: float,
) -> pd.DataFrame:
    if events.empty:
        return _empty_sound_effects()
    return _finalize_sound_effects(
        _normalize_impulse_effects(
            events,
            source_type="bomb",
            sound_class="bomb",
            sound_action=sound_action,
            item_name="c4",
            radius=radius,
            position_mode="event_snapshot",
            raw_source=raw_source,
            source_id=pd.Series(["c4"] * len(events), index=events.index, dtype="string"),
            x_candidates=["X"],
            y_candidates=["Y"],
            z_candidates=["Z"],
        )
    )


def build_sound_effects(
    *,
    ticks: pd.DataFrame,
    footsteps: pd.DataFrame,
    fires: pd.DataFrame,
    hurts: pd.DataFrame,
    item_drops: pd.DataFrame,
    weapon_reloads: pd.DataFrame,
    weapon_zooms: pd.DataFrame,
    grenades: pd.DataFrame,
    smoke_detonates: pd.DataFrame,
    flash_detonates: pd.DataFrame,
    he_detonates: pd.DataFrame,
    inferno_starts: pd.DataFrame,
    bomb_begin_plants: pd.DataFrame,
    bomb_begin_defuses: pd.DataFrame,
    bomb_abort_defuses: pd.DataFrame,
    bomb_defuses: pd.DataFrame,
    bomb_drops: pd.DataFrame,
    bomb_explodes: pd.DataFrame,
) -> pd.DataFrame:
    tables = [
        build_movement_sound_effects(ticks),
        build_player_footstep_sound_effects(footsteps),
        build_landing_sound_effects(ticks),
        build_gunfire_sound_effects(fires),
        build_hurt_sound_effects(hurts),
        build_item_drop_sound_effects(item_drops),
        build_reload_sound_effects(weapon_reloads),
        build_zoom_sound_effects(weapon_zooms),
        build_utility_detonate_effects(
            smoke_detonates,
            raw_source="smokegrenade_detonate",
            sound_action="smoke_detonate",
            radius=1000.0,
        ),
        build_utility_detonate_effects(
            flash_detonates,
            raw_source="flashbang_detonate",
            sound_action="flash_detonate",
            radius=1000.0,
        ),
        build_utility_detonate_effects(
            he_detonates,
            raw_source="hegrenade_detonate",
            sound_action="he_detonate",
            radius=1200.0,
        ),
        build_utility_detonate_effects(
            inferno_starts,
            raw_source="inferno_startburn",
            sound_action="inferno_startburn",
            radius=1100.0,
        ),
        build_grenade_bounce_sound_effects(grenades),
        build_bomb_dropped_sound_effects(bomb_drops),
        build_bomb_player_sound_effects(
            bomb_begin_plants,
            raw_source="bomb_beginplant",
            sound_action="begin_plant",
            radius=1200.0,
        ),
        build_bomb_player_sound_effects(
            bomb_begin_defuses,
            raw_source="bomb_begindefuse",
            sound_action="begin_defuse",
            radius=1062.0,
        ),
        build_bomb_player_sound_effects(
            bomb_abort_defuses,
            raw_source="bomb_abortdefuse",
            sound_action="abort_defuse",
            radius=800.0,
        ),
        build_bomb_player_sound_effects(
            bomb_defuses,
            raw_source="bomb_defused",
            sound_action="defused",
            radius=1062.0,
        ),
        build_bomb_snapshot_sound_effects(
            bomb_explodes,
            raw_source="bomb_exploded",
            sound_action="exploded",
            radius=3000.0,
        ),
    ]
    non_empty = [table for table in tables if not table.empty]
    if not non_empty:
        return _empty_sound_effects()
    combined = pd.concat(non_empty, ignore_index=True)
    return _finalize_sound_effects(combined)
