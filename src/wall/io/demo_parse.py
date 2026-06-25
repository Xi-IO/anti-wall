from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from demoparser2 import DemoParser

from wall.domain.weapon_overrides import WEAPON_OVERRIDES
from wall.domain.weapons import find_weapon_spec, load_base_weapon_specs, merge_weapon_specs
from wall.io.grenade_segments import build_grenade_trajectory_segments_table
from wall.io.table_io import DEFAULT_TABLE_FORMAT, write_table
from wall.output import progress_enabled, print_status
from wall.profile import profile_log, profile_note


WEAPON_SPECS = merge_weapon_specs(load_base_weapon_specs(), WEAPON_OVERRIDES)


def _render_progress_line(label: str, current: int, total: int, *, detail: str | None = None) -> str:
    resolved_total = max(1, int(total))
    resolved_current = max(0, min(int(current), resolved_total))
    width = 20
    filled = int(round((resolved_current / resolved_total) * width))
    bar = "#" * filled + "-" * (width - filled)
    suffix = f"  {detail}" if detail else ""
    return f"{label:<10} [{bar}] {resolved_current}/{resolved_total}{suffix}"


def _print_parse_progress(current: int, total: int, detail: str) -> None:
    if not progress_enabled():
        return
    print(_render_progress_line("parsing", current, total, detail=detail), flush=True)


def _remove_legacy_grenade_tables(output_dir: Path) -> None:
    for suffix in (".parquet", ".csv"):
        legacy_path = output_dir / f"grenades{suffix}"
        if legacy_path.exists():
            legacy_path.unlink()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Parse a CS2 demo with demoparser2.")
    parser.add_argument("demo", type=Path, help="Path to the .dem file")
    parser.add_argument(
        "--tick-fields",
        nargs="*",
        default=[
            "X",
            "Y",
            "Z",
            "yaw",
            "pitch",
            "health",
            "team_num",
            "player_name",
            "active_weapon_name",
            "has_defuser",
            "total_rounds_played",
            "ducking",
            "is_airborne",
            "velocity_X",
            "velocity_Y",
            "velocity_Z",
        ],
        help="Tick fields to request from demoparser2",
    )
    parser.add_argument(
        "--head",
        type=int,
        default=5,
        help="Number of sample rows to print",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs"),
        help="Directory that will contain per-demo output folders",
    )
    parser.add_argument(
        "--table-format",
        choices=["parquet", "csv"],
        default=DEFAULT_TABLE_FORMAT,
        help="Storage format for parsed tables",
    )
    parser.add_argument(
        "--ticks-format",
        choices=["parquet", "csv"],
        default=None,
        help="Optional override for ticks only; defaults to --table-format",
    )
    parser.add_argument(
        "--jump-threshold",
        type=float,
        default=800.0,
        help="Minimum per-player XY jump distance to count as a round-reset jump",
    )
    parser.add_argument(
        "--min-jump-players",
        type=int,
        default=6,
        help="Minimum number of players jumping at the same tick to infer a round boundary",
    )
    parser.add_argument(
        "--min-gap-ticks",
        type=int,
        default=1000,
        help="Minimum gap between inferred round boundaries",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.demo.exists():
        raise FileNotFoundError(f"Demo not found: {args.demo}")

    total_stages = 6
    _print_parse_progress(1, total_stages, f"Reading demo {args.demo.name}")
    demo = DemoParser(str(args.demo))
    header = demo.parse_header()

    _print_parse_progress(2, total_stages, "Parsing event tables")
    deaths = normalize_event_table(demo.parse_event(
        "player_death",
        player=["X", "Y", "Z", "yaw", "pitch", "player_name", "player_steamid"],
        other=["total_rounds_played"],
    ))
    fires = normalize_event_table(demo.parse_event(
        "fire_bullets",
    ))
    hurts = normalize_event_table(demo.parse_event(
        "player_hurt",
    ))
    hits = normalize_event_table(demo.parse_event(
        "player_bullet_hit",
    ))
    item_drops = normalize_event_table(demo.parse_event(
        "item_drop",
    ))
    item_pickups = normalize_event_table(demo.parse_event(
        "item_pickup",
    ))
    weapon_reloads = normalize_event_table(demo.parse_event(
        "weapon_reload",
    ))
    weapon_zooms = normalize_event_table(demo.parse_event(
        "weapon_zoom",
    ))
    footsteps = normalize_event_table(demo.parse_event(
        "player_footstep",
    ))
    smoke_detonates = normalize_event_table(demo.parse_event(
        "smokegrenade_detonate",
    ))
    flash_detonates = normalize_event_table(demo.parse_event(
        "flashbang_detonate",
    ))
    he_detonates = normalize_event_table(demo.parse_event(
        "hegrenade_detonate",
    ))
    blinds = normalize_event_table(demo.parse_event(
        "player_blind",
    ))
    bomb_pickups = normalize_event_table(demo.parse_event(
        "bomb_pickup",
        player=["X", "Y", "Z", "yaw", "pitch", "player_name", "player_steamid"],
    ))
    bomb_drops = normalize_event_table(demo.parse_event(
        "bomb_dropped",
        player=["X", "Y", "Z", "yaw", "pitch", "player_name", "player_steamid"],
    ))
    bomb_begin_plants = normalize_event_table(demo.parse_event(
        "bomb_beginplant",
    ))
    bomb_plants = normalize_event_table(demo.parse_event(
        "bomb_planted",
        player=["X", "Y", "Z", "yaw", "pitch", "player_name", "player_steamid"],
    ))
    bomb_defuses = normalize_event_table(demo.parse_event(
        "bomb_defused",
        player=["X", "Y", "Z", "yaw", "pitch", "player_name", "player_steamid"],
    ))
    bomb_begin_defuses = normalize_event_table(demo.parse_event(
        "bomb_begindefuse",
    ))
    bomb_abort_defuses = normalize_event_table(demo.parse_event(
        "bomb_abortdefuse",
    ))
    bomb_explodes = normalize_event_table(demo.parse_event(
        "bomb_exploded",
        player=["X", "Y", "Z", "yaw", "pitch", "player_name", "player_steamid"],
    ))
    smoke_expires = normalize_event_table(demo.parse_event(
        "smokegrenade_expired",
    ))
    inferno_starts = normalize_event_table(demo.parse_event(
        "inferno_startburn",
    ))
    grenades = normalize_event_table(demo.parse_grenades())

    _print_parse_progress(3, total_stages, "Parsing tick frames")
    ticks = demo.parse_ticks(args.tick_fields)

    _print_parse_progress(4, total_stages, "Building round and sound tables")
    jump_by_tick, round_start_ticks = infer_round_boundaries(
        ticks,
        jump_threshold=args.jump_threshold,
        min_jump_players=args.min_jump_players,
        min_gap_ticks=args.min_gap_ticks,
    )
    ticks = attach_inferred_round_info(ticks, round_start_ticks, tick_col="tick")
    deaths = attach_inferred_round_info(deaths, round_start_ticks, tick_col="tick")
    fires = attach_inferred_round_info(fires, round_start_ticks, tick_col="tick")
    hurts = attach_inferred_round_info(hurts, round_start_ticks, tick_col="tick")
    hits = attach_inferred_round_info(hits, round_start_ticks, tick_col="tick")
    item_drops = attach_inferred_round_info(item_drops, round_start_ticks, tick_col="tick")
    item_pickups = attach_inferred_round_info(item_pickups, round_start_ticks, tick_col="tick")
    weapon_reloads = attach_inferred_round_info(weapon_reloads, round_start_ticks, tick_col="tick")
    weapon_zooms = attach_inferred_round_info(weapon_zooms, round_start_ticks, tick_col="tick")
    footsteps = attach_inferred_round_info(footsteps, round_start_ticks, tick_col="tick")
    smoke_detonates = attach_inferred_round_info(smoke_detonates, round_start_ticks, tick_col="tick")
    flash_detonates = attach_inferred_round_info(flash_detonates, round_start_ticks, tick_col="tick")
    he_detonates = attach_inferred_round_info(he_detonates, round_start_ticks, tick_col="tick")
    blinds = attach_inferred_round_info(blinds, round_start_ticks, tick_col="tick")
    bomb_pickups = attach_inferred_round_info(bomb_pickups, round_start_ticks, tick_col="tick")
    bomb_drops = attach_inferred_round_info(bomb_drops, round_start_ticks, tick_col="tick")
    bomb_begin_plants = attach_inferred_round_info(bomb_begin_plants, round_start_ticks, tick_col="tick")
    bomb_plants = attach_inferred_round_info(bomb_plants, round_start_ticks, tick_col="tick")
    bomb_defuses = attach_inferred_round_info(bomb_defuses, round_start_ticks, tick_col="tick")
    bomb_begin_defuses = attach_inferred_round_info(bomb_begin_defuses, round_start_ticks, tick_col="tick")
    bomb_abort_defuses = attach_inferred_round_info(bomb_abort_defuses, round_start_ticks, tick_col="tick")
    bomb_explodes = attach_inferred_round_info(bomb_explodes, round_start_ticks, tick_col="tick")
    smoke_expires = attach_inferred_round_info(smoke_expires, round_start_ticks, tick_col="tick")
    inferno_starts = attach_inferred_round_info(inferno_starts, round_start_ticks, tick_col="tick")
    grenades = attach_inferred_round_info(grenades, round_start_ticks, tick_col="tick")
    bomb_pickups = build_c4_pickup_events(bomb_pickups, item_pickups, ticks)
    bomb_drops = build_c4_drop_events(bomb_drops, item_drops, ticks)
    bomb_drops = classify_drop_reasons(bomb_drops, deaths)
    sound_events = build_sound_events(
        ticks=ticks,
        footsteps=footsteps,
        fires=fires,
        hurts=hurts,
        item_drops=item_drops,
        weapon_reloads=weapon_reloads,
        weapon_zooms=weapon_zooms,
        grenades=grenades,
        smoke_detonates=smoke_detonates,
        flash_detonates=flash_detonates,
        he_detonates=he_detonates,
        inferno_starts=inferno_starts,
        bomb_begin_plants=bomb_begin_plants,
        bomb_plants=bomb_plants,
        bomb_begin_defuses=bomb_begin_defuses,
        bomb_abort_defuses=bomb_abort_defuses,
        bomb_defuses=bomb_defuses,
        bomb_pickups=bomb_pickups,
        bomb_drops=bomb_drops,
        bomb_explodes=bomb_explodes,
    )
    inferred_rounds = build_inferred_rounds_table(ticks, jump_by_tick, round_start_ticks)
    grenade_trajectory_segments = build_grenade_trajectory_segments_table(grenades, tickrate=64.0)
    table_format = args.table_format
    ticks_format = args.ticks_format or table_format

    output_dir = args.output_dir / args.demo.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    _remove_legacy_grenade_tables(output_dir)
    _print_parse_progress(5, total_stages, f"Writing dataset {output_dir}")

    metadata_json = output_dir / "metadata.json"
    saved_paths = {
        "player_death": write_table(deaths, output_dir, "player_death", table_format),
        "fire_bullets": write_table(fires, output_dir, "fire_bullets", table_format),
        "player_hurt": write_table(hurts, output_dir, "player_hurt", table_format),
        "player_bullet_hit": write_table(hits, output_dir, "player_bullet_hit", table_format),
        "item_drop": write_table(item_drops, output_dir, "item_drop", table_format),
        "item_pickup": write_table(item_pickups, output_dir, "item_pickup", table_format),
        "weapon_reload": write_table(weapon_reloads, output_dir, "weapon_reload", table_format),
        "weapon_zoom": write_table(weapon_zooms, output_dir, "weapon_zoom", table_format),
        "player_footstep": write_table(footsteps, output_dir, "player_footstep", table_format),
        "smokegrenade_detonate": write_table(smoke_detonates, output_dir, "smokegrenade_detonate", table_format),
        "flashbang_detonate": write_table(flash_detonates, output_dir, "flashbang_detonate", table_format),
        "hegrenade_detonate": write_table(he_detonates, output_dir, "hegrenade_detonate", table_format),
        "player_blind": write_table(blinds, output_dir, "player_blind", table_format),
        "bomb_pickup": write_table(bomb_pickups, output_dir, "bomb_pickup", table_format),
        "bomb_dropped": write_table(bomb_drops, output_dir, "bomb_dropped", table_format),
        "bomb_beginplant": write_table(bomb_begin_plants, output_dir, "bomb_beginplant", table_format),
        "bomb_planted": write_table(bomb_plants, output_dir, "bomb_planted", table_format),
        "bomb_defused": write_table(bomb_defuses, output_dir, "bomb_defused", table_format),
        "bomb_begindefuse": write_table(bomb_begin_defuses, output_dir, "bomb_begindefuse", table_format),
        "bomb_abortdefuse": write_table(bomb_abort_defuses, output_dir, "bomb_abortdefuse", table_format),
        "bomb_exploded": write_table(bomb_explodes, output_dir, "bomb_exploded", table_format),
        "smokegrenade_expired": write_table(smoke_expires, output_dir, "smokegrenade_expired", table_format),
        "inferno_startburn": write_table(inferno_starts, output_dir, "inferno_startburn", table_format),
        "grenade_trajectory_segments": write_table(
            grenade_trajectory_segments,
            output_dir,
            "grenade_trajectory_segments",
            table_format,
        ),
        "sound_events": write_table(sound_events, output_dir, "sound_events", table_format),
        "ticks": write_table(ticks, output_dir, "ticks", ticks_format),
        "inferred_rounds": write_table(inferred_rounds, output_dir, "inferred_rounds", table_format),
    }
    profile_log(
        "grenade_segments.write",
        df=grenade_trajectory_segments,
        note=profile_note(
            f"output={saved_paths['grenade_trajectory_segments']}",
            f"rows={len(grenade_trajectory_segments)}",
        ),
    )
    metadata = build_metadata(
        demo_path=args.demo,
        header=header,
        ticks=ticks,
        deaths=deaths,
        fires=fires,
        hurts=hurts,
        hits=hits,
        item_drops=item_drops,
        item_pickups=item_pickups,
        weapon_reloads=weapon_reloads,
        weapon_zooms=weapon_zooms,
        footsteps=footsteps,
        smoke_detonates=smoke_detonates,
        flash_detonates=flash_detonates,
        he_detonates=he_detonates,
        blinds=blinds,
        bomb_pickups=bomb_pickups,
        bomb_drops=bomb_drops,
        bomb_begin_plants=bomb_begin_plants,
        bomb_plants=bomb_plants,
        bomb_defuses=bomb_defuses,
        bomb_begin_defuses=bomb_begin_defuses,
        bomb_abort_defuses=bomb_abort_defuses,
        bomb_explodes=bomb_explodes,
        smoke_expires=smoke_expires,
        inferno_starts=inferno_starts,
        grenade_trajectory_segments=grenade_trajectory_segments,
        sound_events=sound_events,
        inferred_rounds=inferred_rounds,
        jump_threshold=args.jump_threshold,
        min_jump_players=args.min_jump_players,
        min_gap_ticks=args.min_gap_ticks,
        table_format=table_format,
        ticks_format=ticks_format,
        saved_paths=saved_paths,
    )
    metadata_json.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    _print_parse_progress(6, total_stages, "Done")

    player_count = int(ticks["name"].dropna().nunique()) if "name" in ticks.columns else 0
    print_status("")
    print_status("Parse Summary")
    print_status(f"demo: {args.demo.name}")
    print_status(f"map: {header.get('map_name', 'unknown')}")
    print_status(f"rounds: {len(inferred_rounds)}")
    print_status(f"players: {player_count}")
    print_status(f"ticks: {len(ticks):,}")
    print_status(f"tables: {len(saved_paths)} + metadata")
    print_status(f"output: {output_dir}")


def infer_round_boundaries(
    ticks,
    jump_threshold: float,
    min_jump_players: int,
    min_gap_ticks: int,
):
    work = ticks.sort_values(["name", "tick"]).copy()
    work["dx"] = work.groupby("name")["X"].diff()
    work["dy"] = work.groupby("name")["Y"].diff()
    work["jump_dist"] = np.sqrt(work["dx"] ** 2 + work["dy"] ** 2)

    jump_counts = (
        work.assign(is_jump=work["jump_dist"] > jump_threshold)
        .groupby("tick")
        .agg(
            n_players=("name", "nunique"),
            n_jump_players=("is_jump", "sum"),
            max_jump=("jump_dist", "max"),
            median_jump=("jump_dist", "median"),
        )
        .reset_index()
    )
    jump_counts["n_jump_players"] = jump_counts["n_jump_players"].astype(int)
    candidates = jump_counts[jump_counts["n_jump_players"] >= min_jump_players].sort_values("tick")

    selected = []
    last_tick = None
    for row in candidates.itertuples(index=False):
        if last_tick is None or row.tick - last_tick >= min_gap_ticks:
            selected.append(int(row.tick))
            last_tick = int(row.tick)

    first_tick = int(ticks["tick"].min())
    round_start_ticks = sorted(set([first_tick] + selected))
    return jump_counts, round_start_ticks


def attach_inferred_round_info(df, round_start_ticks: list[int], tick_col: str):
    out = df.copy()
    if out.empty:
        out["inferred_round_id"] = pd.Series(dtype="int64")
        out["inferred_round_tick"] = pd.Series(dtype="int64")
        out["inferred_round_seconds"] = pd.Series(dtype="float64")
        return out
    if tick_col not in out.columns:
        raise ValueError(f"Missing required tick column '{tick_col}' in event table")
    starts = np.array(sorted(round_start_ticks))
    tick_values = pd.to_numeric(out[tick_col], errors="coerce").to_numpy()
    round_ids = np.searchsorted(starts, tick_values, side="right")
    start_indices = np.clip(round_ids - 1, 0, len(starts) - 1)
    relative_ticks = tick_values - starts[start_indices]
    out["inferred_round_id"] = round_ids.astype("int64")
    out["inferred_round_tick"] = relative_ticks.astype("int64")
    out["inferred_round_seconds"] = out["inferred_round_tick"] / 64.0
    return out


def normalize_event_table(event_data) -> pd.DataFrame:
    if isinstance(event_data, pd.DataFrame):
        return event_data.copy()
    if event_data is None:
        return pd.DataFrame()
    if isinstance(event_data, list):
        if not event_data:
            return pd.DataFrame()
        return pd.DataFrame(event_data)
    if isinstance(event_data, dict):
        return pd.DataFrame([event_data])
    raise TypeError(f"Unsupported event data type: {type(event_data)!r}")


def _normalize_identifier(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip()
    return text.fillna("")


def _coalesce_numeric(df: pd.DataFrame, columns: list[str]) -> pd.Series:
    result = pd.Series(np.nan, index=df.index, dtype="float64")
    for column in columns:
        if column in df.columns:
            values = pd.to_numeric(df[column], errors="coerce")
            result = result.where(result.notna(), values)
    return result


def _empty_sound_events() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "tick": pd.Series(dtype="int64"),
            "sound_kind": pd.Series(dtype="string"),
            "sound_source": pd.Series(dtype="string"),
            "emitter_name": pd.Series(dtype="string"),
            "emitter_steamid": pd.Series(dtype="string"),
            "grenade_entity_id": pd.Series(dtype="Int64"),
            "weapon_id": pd.Series(dtype="string"),
            "audible_rule": pd.Series(dtype="string"),
            "is_global": pd.Series(dtype="boolean"),
            "is_suppressed": pd.Series(dtype="boolean"),
            "x": pd.Series(dtype="float64"),
            "y": pd.Series(dtype="float64"),
            "z": pd.Series(dtype="float64"),
            "radius_world": pd.Series(dtype="float64"),
            "duration_ticks": pd.Series(dtype="int64"),
            "detail": pd.Series(dtype="string"),
            "impact_speed_z": pd.Series(dtype="float64"),
            "inferred_round_id": pd.Series(dtype="int64"),
            "inferred_round_tick": pd.Series(dtype="int64"),
            "inferred_round_seconds": pd.Series(dtype="float64"),
        }
    )


GRENADE_BOUNCE_CLUSTER_GAP_TICKS = 6
GRENADE_BOUNCE_DURATION_TICKS = 12


def _position_lookup_from_ticks(ticks: pd.DataFrame) -> pd.DataFrame:
    work = ticks.copy()
    work["steamid_key"] = _normalize_identifier(work.get("steamid", pd.Series(index=work.index, dtype="object")))
    work["name_key"] = _normalize_identifier(work.get("name", pd.Series(index=work.index, dtype="object")))
    columns = [
        "tick",
        "steamid_key",
        "name_key",
        "name",
        "steamid",
        "X",
        "Y",
        "Z",
        "ducking",
        "is_airborne",
        "velocity_X",
        "velocity_Y",
        "velocity_Z",
        "inferred_round_id",
        "inferred_round_tick",
        "inferred_round_seconds",
    ]
    existing = [column for column in columns if column in work.columns]
    return work[existing].copy()


def enrich_sound_event_positions(events: pd.DataFrame, ticks: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return events.copy()
    work = events.copy()
    if "tick" not in work.columns:
        raise ValueError("sound source table is missing required tick column")
    work["emitter_steamid"] = _normalize_identifier(work.get("emitter_steamid", pd.Series(index=work.index, dtype="object")))
    work["emitter_name"] = _normalize_identifier(work.get("emitter_name", pd.Series(index=work.index, dtype="object")))
    work["x"] = _coalesce_numeric(work, ["x", "X", "origin_x", "ent_origin_x"])
    work["y"] = _coalesce_numeric(work, ["y", "Y", "origin_y", "ent_origin_y"])
    work["z"] = _coalesce_numeric(work, ["z", "Z", "origin_z", "ent_origin_z"])
    needs_position = work[["x", "y", "z"]].isna().any(axis=1)
    if not needs_position.any():
        return work

    lookup = _position_lookup_from_ticks(ticks)
    steamid_match = lookup.rename(
        columns={
            "X": "tick_x",
            "Y": "tick_y",
            "Z": "tick_z",
            "name": "tick_name",
            "steamid": "tick_steamid",
        }
    )
    steamid_match = steamid_match[steamid_match["steamid_key"] != ""].drop_duplicates(["tick", "steamid_key"], keep="first")
    work = work.merge(
        steamid_match[["tick", "steamid_key", "tick_x", "tick_y", "tick_z", "tick_name", "tick_steamid"]],
        left_on=["tick", "emitter_steamid"],
        right_on=["tick", "steamid_key"],
        how="left",
    )
    for target, source in (("x", "tick_x"), ("y", "tick_y"), ("z", "tick_z")):
        work[target] = work[target].where(work[target].notna(), work[source])
    work["emitter_name"] = work["emitter_name"].where(work["emitter_name"] != "", _normalize_identifier(work["tick_name"]))
    work["emitter_steamid"] = work["emitter_steamid"].where(work["emitter_steamid"] != "", _normalize_identifier(work["tick_steamid"]))
    work = work.drop(columns=[column for column in ["steamid_key", "tick_x", "tick_y", "tick_z", "tick_name", "tick_steamid"] if column in work.columns])

    still_missing = work[["x", "y", "z"]].isna().any(axis=1)
    if not still_missing.any():
        return work

    name_match = lookup.rename(
        columns={
            "X": "tick_x",
            "Y": "tick_y",
            "Z": "tick_z",
            "name": "tick_name",
            "steamid": "tick_steamid",
        }
    )
    name_match = name_match[name_match["name_key"] != ""].drop_duplicates(["tick", "name_key"], keep="first")
    work = work.merge(
        name_match[["tick", "name_key", "tick_x", "tick_y", "tick_z", "tick_name", "tick_steamid"]],
        left_on=["tick", "emitter_name"],
        right_on=["tick", "name_key"],
        how="left",
    )
    for target, source in (("x", "tick_x"), ("y", "tick_y"), ("z", "tick_z")):
        work[target] = work[target].where(work[target].notna(), work[source])
    work["emitter_name"] = work["emitter_name"].where(work["emitter_name"] != "", _normalize_identifier(work["tick_name"]))
    work["emitter_steamid"] = work["emitter_steamid"].where(work["emitter_steamid"] != "", _normalize_identifier(work["tick_steamid"]))
    return work.drop(columns=[column for column in ["name_key", "tick_x", "tick_y", "tick_z", "tick_name", "tick_steamid"] if column in work.columns])


def build_c4_pickup_events(
    bomb_pickups: pd.DataFrame,
    item_pickups: pd.DataFrame,
    ticks: pd.DataFrame,
) -> pd.DataFrame:
    def finalize(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        if out.empty:
            return out
        if "tick" in out.columns:
            out["tick"] = pd.to_numeric(out["tick"], errors="coerce").astype("Int64")
        for column in ("user_name", "user_player_name", "pickup_event_source"):
            if column in out.columns:
                out[column] = out[column].astype("string").fillna("")
        for column in ("user_steamid",):
            if column in out.columns:
                out[column] = _normalize_identifier(out[column])
        for column in ("user_player_steamid",):
            if column in out.columns:
                out[column] = pd.to_numeric(out[column], errors="coerce").astype("Int64")
        for column in ("inferred_round_id", "inferred_round_tick"):
            if column in out.columns:
                out[column] = pd.to_numeric(out[column], errors="coerce").astype("Int64")
        if "inferred_round_seconds" in out.columns:
            out["inferred_round_seconds"] = pd.to_numeric(out["inferred_round_seconds"], errors="coerce").astype("float64")
        for column in ("user_X", "user_Y", "user_Z", "user_yaw", "user_pitch"):
            if column in out.columns:
                out[column] = pd.to_numeric(out[column], errors="coerce").astype("float64")
        if "tick" in out.columns:
            out = out.dropna(subset=["tick"]).sort_values(["tick", "user_name"]).reset_index(drop=True)
        return out

    base = bomb_pickups.copy()
    if base.empty and item_pickups.empty:
        return finalize(base)

    if not base.empty:
        base["pickup_event_source"] = "bomb_pickup"

    if item_pickups.empty:
        return finalize(base)

    required = {"tick", "user_name", "user_steamid"}
    if not required.issubset(item_pickups.columns):
        return finalize(base)

    item_work = item_pickups.copy()
    defindex = pd.to_numeric(item_work.get("defindex"), errors="coerce")
    item_name = item_work.get("item", pd.Series(index=item_work.index, dtype="object")).astype("string")
    c4_mask = (defindex == 49) | item_name.str.contains("c4", case=False, na=False)
    item_work = item_work[c4_mask].copy()
    if item_work.empty:
        return finalize(base)

    supplemental = pd.DataFrame(index=item_work.index)
    supplemental["tick"] = pd.to_numeric(item_work["tick"], errors="coerce").astype("Int64")
    supplemental["user_name"] = item_work["user_name"].astype("string").fillna("")
    supplemental["user_player_name"] = supplemental["user_name"]
    supplemental["user_steamid"] = _normalize_identifier(item_work["user_steamid"])
    supplemental["user_player_steamid"] = pd.to_numeric(item_work["user_steamid"], errors="coerce").astype("Int64")
    supplemental["pickup_event_source"] = "item_pickup_c4"
    if "inferred_round_id" in item_work.columns:
        supplemental["inferred_round_id"] = item_work["inferred_round_id"]
    if "inferred_round_tick" in item_work.columns:
        supplemental["inferred_round_tick"] = item_work["inferred_round_tick"]
    if "inferred_round_seconds" in item_work.columns:
        supplemental["inferred_round_seconds"] = item_work["inferred_round_seconds"]

    lookup = ticks.copy()
    if not lookup.empty and "tick" in lookup.columns:
        lookup["steamid_key"] = _normalize_identifier(lookup.get("steamid", pd.Series(index=lookup.index, dtype="object")))
        lookup["name_key"] = _normalize_identifier(lookup.get("name", pd.Series(index=lookup.index, dtype="object")))
        tick_columns = ["tick", "steamid_key", "name_key", "X", "Y", "Z", "yaw", "pitch"]
        existing = [column for column in tick_columns if column in lookup.columns]
        lookup = lookup[existing].copy()

        steamid_lookup = lookup[lookup["steamid_key"] != ""].drop_duplicates(["tick", "steamid_key"], keep="first")
        supplemental = supplemental.merge(
            steamid_lookup.rename(
                columns={
                    "X": "user_X",
                    "Y": "user_Y",
                    "Z": "user_Z",
                    "yaw": "user_yaw",
                    "pitch": "user_pitch",
                }
            )[
                [column for column in ["tick", "steamid_key", "user_X", "user_Y", "user_Z", "user_yaw", "user_pitch"] if column in steamid_lookup.rename(columns={"X": "user_X"}).columns]
            ],
            left_on=["tick", "user_steamid"],
            right_on=["tick", "steamid_key"],
            how="left",
        )
        supplemental = supplemental.drop(columns=[column for column in ["steamid_key"] if column in supplemental.columns])

        missing_pos = supplemental[["user_X", "user_Y", "user_Z"]].isna().any(axis=1) if {"user_X", "user_Y", "user_Z"}.issubset(supplemental.columns) else pd.Series(True, index=supplemental.index)
        if missing_pos.any():
            name_lookup = lookup[lookup["name_key"] != ""].drop_duplicates(["tick", "name_key"], keep="first")
            fallback = supplemental.loc[missing_pos].merge(
                name_lookup.rename(
                    columns={
                        "X": "fallback_X",
                        "Y": "fallback_Y",
                        "Z": "fallback_Z",
                        "yaw": "fallback_yaw",
                        "pitch": "fallback_pitch",
                    }
                )[
                    [column for column in ["tick", "name_key", "fallback_X", "fallback_Y", "fallback_Z", "fallback_yaw", "fallback_pitch"] if column in name_lookup.rename(columns={"X": "fallback_X"}).columns]
                ],
                left_on=["tick", "user_name"],
                right_on=["tick", "name_key"],
                how="left",
            )
            for target, source in (
                ("user_X", "fallback_X"),
                ("user_Y", "fallback_Y"),
                ("user_Z", "fallback_Z"),
                ("user_yaw", "fallback_yaw"),
                ("user_pitch", "fallback_pitch"),
            ):
                if source in fallback.columns:
                    fallback[target] = fallback[target].where(fallback[target].notna(), fallback[source]) if target in fallback.columns else fallback[source]
            fallback = fallback.drop(columns=[column for column in ["name_key", "fallback_X", "fallback_Y", "fallback_Z", "fallback_yaw", "fallback_pitch"] if column in fallback.columns])
            supplemental.loc[missing_pos, fallback.columns] = fallback.to_numpy()

    if base.empty:
        return finalize(supplemental)

    base_key = pd.DataFrame(index=base.index)
    base_key["tick"] = pd.to_numeric(base.get("tick"), errors="coerce").astype("Int64")
    base_key["steamid_key"] = _normalize_identifier(base.get("user_steamid", pd.Series(index=base.index, dtype="object")))
    base_key["name_key"] = _normalize_identifier(base.get("user_name", pd.Series(index=base.index, dtype="object")))
    supplemental_key = pd.DataFrame(index=supplemental.index)
    supplemental_key["tick"] = pd.to_numeric(supplemental.get("tick"), errors="coerce").astype("Int64")
    supplemental_key["steamid_key"] = _normalize_identifier(supplemental.get("user_steamid", pd.Series(index=supplemental.index, dtype="object")))
    supplemental_key["name_key"] = _normalize_identifier(supplemental.get("user_name", pd.Series(index=supplemental.index, dtype="object")))

    base_exact_keys = set(
        zip(
            base_key["tick"].astype("int64", errors="ignore"),
            base_key["steamid_key"],
            base_key["name_key"],
        )
    )
    keep_mask = []
    for row in supplemental_key.itertuples(index=False):
        keep_mask.append((row.tick, row.steamid_key, row.name_key) not in base_exact_keys)
    supplemental = supplemental[pd.Series(keep_mask, index=supplemental.index)].copy()
    combined = pd.concat([base, supplemental], ignore_index=True, sort=False)
    return finalize(combined)


def build_c4_drop_events(
    bomb_drops: pd.DataFrame,
    item_drops: pd.DataFrame,
    ticks: pd.DataFrame,
) -> pd.DataFrame:
    def finalize(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        if out.empty:
            return out
        if "tick" in out.columns:
            out["tick"] = pd.to_numeric(out["tick"], errors="coerce").astype("Int64")
        if "entindex" in out.columns:
            out["entindex"] = pd.to_numeric(out["entindex"], errors="coerce").astype("Int64")
        for column in ("user_name", "user_player_name", "drop_event_source"):
            if column in out.columns:
                out[column] = out[column].astype("string").fillna("")
        for column in ("user_steamid",):
            if column in out.columns:
                out[column] = _normalize_identifier(out[column])
        for column in ("user_player_steamid",):
            if column in out.columns:
                out[column] = pd.to_numeric(out[column], errors="coerce").astype("Int64")
        for column in ("inferred_round_id", "inferred_round_tick"):
            if column in out.columns:
                out[column] = pd.to_numeric(out[column], errors="coerce").astype("Int64")
        if "inferred_round_seconds" in out.columns:
            out["inferred_round_seconds"] = pd.to_numeric(out["inferred_round_seconds"], errors="coerce").astype("float64")
        for column in ("user_X", "user_Y", "user_Z", "user_yaw", "user_pitch"):
            if column in out.columns:
                out[column] = pd.to_numeric(out[column], errors="coerce").astype("float64")
        if "tick" in out.columns:
            out = out.dropna(subset=["tick"]).sort_values(["tick", "user_name"]).reset_index(drop=True)
        return out

    base = bomb_drops.copy()
    if base.empty and item_drops.empty:
        return finalize(base)

    if not base.empty:
        base["drop_event_source"] = "bomb_dropped"

    if item_drops.empty:
        return finalize(base)

    required = {"tick", "user_name", "user_steamid"}
    if not required.issubset(item_drops.columns):
        return finalize(base)

    item_work = item_drops.copy()
    defindex = pd.to_numeric(item_work.get("defindex"), errors="coerce")
    item_name = item_work.get("item", pd.Series(index=item_work.index, dtype="object")).astype("string")
    c4_mask = (defindex == 49) | item_name.str.contains("c4", case=False, na=False)
    item_work = item_work[c4_mask].copy()
    if item_work.empty:
        return finalize(base)

    supplemental = pd.DataFrame(index=item_work.index)
    supplemental["tick"] = pd.to_numeric(item_work["tick"], errors="coerce").astype("Int64")
    supplemental["entindex"] = pd.Series(pd.NA, index=item_work.index, dtype="Int64")
    supplemental["user_name"] = item_work["user_name"].astype("string").fillna("")
    supplemental["user_player_name"] = supplemental["user_name"]
    supplemental["user_steamid"] = _normalize_identifier(item_work["user_steamid"])
    supplemental["user_player_steamid"] = pd.to_numeric(item_work["user_steamid"], errors="coerce").astype("Int64")
    supplemental["drop_event_source"] = "item_drop_c4"
    if "inferred_round_id" in item_work.columns:
        supplemental["inferred_round_id"] = item_work["inferred_round_id"]
    if "inferred_round_tick" in item_work.columns:
        supplemental["inferred_round_tick"] = item_work["inferred_round_tick"]
    if "inferred_round_seconds" in item_work.columns:
        supplemental["inferred_round_seconds"] = item_work["inferred_round_seconds"]

    lookup = ticks.copy()
    if not lookup.empty and "tick" in lookup.columns:
        lookup["steamid_key"] = _normalize_identifier(lookup.get("steamid", pd.Series(index=lookup.index, dtype="object")))
        lookup["name_key"] = _normalize_identifier(lookup.get("name", pd.Series(index=lookup.index, dtype="object")))
        tick_columns = ["tick", "steamid_key", "name_key", "X", "Y", "Z", "yaw", "pitch"]
        existing = [column for column in tick_columns if column in lookup.columns]
        lookup = lookup[existing].copy()

        steamid_lookup = lookup[lookup["steamid_key"] != ""].drop_duplicates(["tick", "steamid_key"], keep="first")
        steamid_lookup = steamid_lookup.rename(
            columns={
                "X": "user_X",
                "Y": "user_Y",
                "Z": "user_Z",
                "yaw": "user_yaw",
                "pitch": "user_pitch",
            }
        )
        columns = [column for column in ["tick", "steamid_key", "user_X", "user_Y", "user_Z", "user_yaw", "user_pitch"] if column in steamid_lookup.columns]
        supplemental = supplemental.merge(
            steamid_lookup[columns],
            left_on=["tick", "user_steamid"],
            right_on=["tick", "steamid_key"],
            how="left",
        )
        supplemental = supplemental.drop(columns=[column for column in ["steamid_key"] if column in supplemental.columns])

        missing_pos = supplemental[["user_X", "user_Y", "user_Z"]].isna().any(axis=1) if {"user_X", "user_Y", "user_Z"}.issubset(supplemental.columns) else pd.Series(True, index=supplemental.index)
        if missing_pos.any():
            name_lookup = lookup[lookup["name_key"] != ""].drop_duplicates(["tick", "name_key"], keep="first")
            name_lookup = name_lookup.rename(
                columns={
                    "X": "fallback_X",
                    "Y": "fallback_Y",
                    "Z": "fallback_Z",
                    "yaw": "fallback_yaw",
                    "pitch": "fallback_pitch",
                }
            )
            columns = [column for column in ["tick", "name_key", "fallback_X", "fallback_Y", "fallback_Z", "fallback_yaw", "fallback_pitch"] if column in name_lookup.columns]
            fallback = supplemental.loc[missing_pos].merge(
                name_lookup[columns],
                left_on=["tick", "user_name"],
                right_on=["tick", "name_key"],
                how="left",
            )
            for target, source in (
                ("user_X", "fallback_X"),
                ("user_Y", "fallback_Y"),
                ("user_Z", "fallback_Z"),
                ("user_yaw", "fallback_yaw"),
                ("user_pitch", "fallback_pitch"),
            ):
                if source in fallback.columns:
                    fallback[target] = fallback[target].where(fallback[target].notna(), fallback[source]) if target in fallback.columns else fallback[source]
            fallback = fallback.drop(columns=[column for column in ["name_key", "fallback_X", "fallback_Y", "fallback_Z", "fallback_yaw", "fallback_pitch"] if column in fallback.columns])
            supplemental.loc[missing_pos, fallback.columns] = fallback.to_numpy()

    if base.empty:
        return finalize(supplemental)

    base_key = pd.DataFrame(index=base.index)
    base_key["tick"] = pd.to_numeric(base.get("tick"), errors="coerce").astype("Int64")
    base_key["steamid_key"] = _normalize_identifier(base.get("user_steamid", pd.Series(index=base.index, dtype="object")))
    base_key["name_key"] = _normalize_identifier(base.get("user_name", pd.Series(index=base.index, dtype="object")))
    supplemental_key = pd.DataFrame(index=supplemental.index)
    supplemental_key["tick"] = pd.to_numeric(supplemental.get("tick"), errors="coerce").astype("Int64")
    supplemental_key["steamid_key"] = _normalize_identifier(supplemental.get("user_steamid", pd.Series(index=supplemental.index, dtype="object")))
    supplemental_key["name_key"] = _normalize_identifier(supplemental.get("user_name", pd.Series(index=supplemental.index, dtype="object")))

    base_exact_keys = set(zip(base_key["tick"], base_key["steamid_key"], base_key["name_key"]))
    keep_mask: list[bool] = []
    for row in supplemental_key.itertuples(index=False):
        keep_mask.append((row.tick, row.steamid_key, row.name_key) not in base_exact_keys)
    supplemental = supplemental[pd.Series(keep_mask, index=supplemental.index)].copy()
    combined = pd.concat([base, supplemental], ignore_index=True, sort=False)
    return finalize(combined)


def classify_drop_reasons(
    drops: pd.DataFrame,
    deaths: pd.DataFrame,
    *,
    death_window_ticks: int = 2,
) -> pd.DataFrame:
    out = drops.copy()
    if out.empty:
        out["drop_reason"] = pd.Series(dtype="string")
        out["drop_is_death"] = pd.Series(dtype="boolean")
        return out

    out["drop_reason"] = pd.Series(["throw"] * len(out), index=out.index, dtype="string")
    out["drop_is_death"] = pd.Series([False] * len(out), index=out.index, dtype="boolean")
    if deaths.empty or "tick" not in out.columns or "tick" not in deaths.columns:
        return out

    death_lookup: dict[tuple[str, str], list[int]] = {}
    for _, row in deaths.iterrows():
        death_tick = pd.to_numeric(row.get("tick"), errors="coerce")
        if pd.isna(death_tick):
            continue
        steamid = _normalize_identifier(pd.Series([row.get("user_steamid", "")])).iloc[0]
        name = _normalize_identifier(pd.Series([row.get("user_name", "")])).iloc[0]
        death_lookup.setdefault((steamid, name), []).append(int(death_tick))

    for key in death_lookup:
        death_lookup[key].sort()

    reasons: list[str] = []
    death_flags: list[bool] = []
    for _, row in out.iterrows():
        drop_tick = pd.to_numeric(row.get("tick"), errors="coerce")
        if pd.isna(drop_tick):
            reasons.append("unknown")
            death_flags.append(False)
            continue
        steamid = _normalize_identifier(pd.Series([row.get("user_steamid", "")])).iloc[0]
        name = _normalize_identifier(pd.Series([row.get("user_name", "")])).iloc[0]
        candidate_ticks = death_lookup.get((steamid, name)) or death_lookup.get(("", name)) or []
        is_death = any(abs(int(drop_tick) - tick) <= death_window_ticks for tick in candidate_ticks)
        reasons.append("death" if is_death else "throw")
        death_flags.append(is_death)

    out["drop_reason"] = pd.Series(reasons, index=out.index, dtype="string")
    out["drop_is_death"] = pd.Series(death_flags, index=out.index, dtype="boolean")
    return out


def build_landing_sound_events(ticks: pd.DataFrame) -> pd.DataFrame:
    required = {"tick", "name", "steamid", "X", "Y", "Z", "is_airborne", "velocity_Z", "inferred_round_id", "inferred_round_tick", "inferred_round_seconds"}
    if ticks.empty or not required.issubset(ticks.columns):
        return _empty_sound_events()

    selected_columns = list(required)
    if "ducking" in ticks.columns:
        selected_columns.append("ducking")
    work = ticks[selected_columns].copy()
    work["steamid_key"] = _normalize_identifier(work["steamid"])
    work["name"] = _normalize_identifier(work["name"])
    work["tick"] = pd.to_numeric(work["tick"], errors="coerce")
    work["X"] = pd.to_numeric(work["X"], errors="coerce")
    work["Y"] = pd.to_numeric(work["Y"], errors="coerce")
    work["Z"] = pd.to_numeric(work["Z"], errors="coerce")
    work["velocity_Z"] = pd.to_numeric(work["velocity_Z"], errors="coerce")
    work["is_airborne"] = work["is_airborne"].fillna(False).astype(bool)
    if "ducking" in work.columns:
        work["ducking"] = work["ducking"].fillna(False).astype(bool)
    work = work.dropna(subset=["tick"]).sort_values(["steamid_key", "name", "tick"]).copy()

    player_keys = ["steamid_key", "name"]
    prev_airborne = work.groupby(player_keys, sort=False)["is_airborne"].shift(1).fillna(False).astype(bool)
    airborne_start = work["is_airborne"] & ~prev_airborne
    airborne_run_id = airborne_start.groupby([work["steamid_key"], work["name"]]).cumsum()
    work["airborne_run_id"] = airborne_run_id.where(work["is_airborne"], np.nan)

    airborne_rows = work[work["is_airborne"] & work["airborne_run_id"].notna()].copy()
    if airborne_rows.empty:
        return _empty_sound_events()
    airborne_summary = (
        airborne_rows.groupby(player_keys + ["airborne_run_id"], sort=False)
        .agg(
            peak_height=("Z", "max"),
            min_velocity_z=("velocity_Z", "min"),
            max_velocity_z=("velocity_Z", "max"),
            airborne_ticks=("tick", "size"),
        )
        .reset_index()
    )
    airborne_summary["impact_speed_z"] = airborne_summary["min_velocity_z"].abs()
    airborne_summary["had_upward_launch"] = airborne_summary["max_velocity_z"] > 200.0

    landing_mask = ~work["is_airborne"] & prev_airborne
    landing_rows = work[landing_mask].copy()
    if landing_rows.empty:
        return _empty_sound_events()
    landing_rows["airborne_run_id"] = airborne_run_id.groupby([work["steamid_key"], work["name"]]).shift(1)[landing_mask]
    landing_rows = landing_rows[landing_rows["airborne_run_id"].notna()].copy()
    if landing_rows.empty:
        return _empty_sound_events()

    merged = landing_rows.merge(
        airborne_summary,
        on=player_keys + ["airborne_run_id"],
        how="left",
    )
    merged["vertical_drop"] = merged["peak_height"] - merged["Z"]
    merged = merged[merged["airborne_ticks"] >= 2].copy()
    merged["is_fall_land"] = merged["impact_speed_z"] > 300.0
    merged["is_jump_land"] = merged["had_upward_launch"] & (
        (merged["impact_speed_z"] >= 200.0) | (merged["vertical_drop"] >= 12.0)
    )
    merged = merged[merged["is_fall_land"] | merged["is_jump_land"]].copy()
    if merged.empty:
        return _empty_sound_events()

    merged["detail"] = np.where(merged["is_jump_land"], "jump_land", "fall_land")
    merged["detail"] = (
        merged["detail"].astype(str)
        + "|air_ticks="
        + merged["airborne_ticks"].fillna(0).astype(int).astype(str)
        + "|drop="
        + merged["vertical_drop"].fillna(0.0).map(lambda value: f"{value:.1f}")
    )

    result = pd.DataFrame(
        {
            "tick": merged["tick"].astype("int64"),
            "sound_kind": "landing",
            "sound_source": "inferred_landing",
            "emitter_name": merged["name"].astype(str),
            "emitter_steamid": merged["steamid_key"].astype(str),
            "x": merged["X"].astype("float64"),
            "y": merged["Y"].astype("float64"),
            "z": merged["Z"].astype("float64"),
            "radius_world": 1062.0,
            "duration_ticks": 6,
            "detail": merged["detail"].astype("string"),
            "impact_speed_z": merged["impact_speed_z"].astype("float64"),
            "inferred_round_id": merged["inferred_round_id"].astype("int64"),
            "inferred_round_tick": merged["inferred_round_tick"].astype("int64"),
            "inferred_round_seconds": merged["inferred_round_seconds"].astype("float64"),
        }
    )
    return result.sort_values(["tick", "emitter_name"]).reset_index(drop=True)


def build_movement_sound_events(ticks: pd.DataFrame) -> pd.DataFrame:
    required = {
        "tick",
        "name",
        "steamid",
        "X",
        "Y",
        "Z",
        "ducking",
        "is_airborne",
        "velocity_X",
        "velocity_Y",
        "inferred_round_id",
        "inferred_round_tick",
        "inferred_round_seconds",
    }
    if ticks.empty or not required.issubset(ticks.columns):
        return _empty_sound_events()

    work = ticks[list(required)].copy()
    work["name"] = _normalize_identifier(work["name"])
    work["steamid_key"] = _normalize_identifier(work["steamid"])
    work["tick"] = pd.to_numeric(work["tick"], errors="coerce")
    work["X"] = pd.to_numeric(work["X"], errors="coerce")
    work["Y"] = pd.to_numeric(work["Y"], errors="coerce")
    work["Z"] = pd.to_numeric(work["Z"], errors="coerce")
    work["velocity_X"] = pd.to_numeric(work["velocity_X"], errors="coerce")
    work["velocity_Y"] = pd.to_numeric(work["velocity_Y"], errors="coerce")
    work["ducking"] = work["ducking"].fillna(False).astype(bool)
    work["is_airborne"] = work["is_airborne"].fillna(False).astype(bool)
    work = work.dropna(subset=["tick"]).sort_values(["steamid_key", "name", "tick"]).copy()

    work["speed_xy"] = np.sqrt(work["velocity_X"].fillna(0.0) ** 2 + work["velocity_Y"].fillna(0.0) ** 2)
    work["is_audible_move"] = (
        (work["speed_xy"] > 135.0)
        & (work["speed_xy"] < 320.0)
        & (~work["is_airborne"])
        & (~work["ducking"])
    )
    if not bool(work["is_audible_move"].any()):
        return _empty_sound_events()

    player_keys = ["steamid_key", "name"]
    prev_move = work.groupby(player_keys, sort=False)["is_audible_move"].shift(1).fillna(False).astype(bool)
    move_start = work["is_audible_move"] & ~prev_move
    move_run_id = move_start.groupby([work["steamid_key"], work["name"]]).cumsum()
    work["move_run_id"] = move_run_id.where(work["is_audible_move"], np.nan)

    moving = work[work["is_audible_move"] & work["move_run_id"].notna()].copy()
    if moving.empty:
        return _empty_sound_events()

    moving["move_index"] = moving.groupby(player_keys + ["move_run_id"], sort=False).cumcount()
    sampled = moving[(moving["move_index"] % 8) == 0].copy()
    if sampled.empty:
        return _empty_sound_events()

    sampled["detail"] = "movement_inferred|speed_xy=" + sampled["speed_xy"].map(lambda value: f"{value:.1f}")
    result = pd.DataFrame(
        {
            "tick": sampled["tick"].astype("int64"),
            "sound_kind": "footstep",
            "sound_source": "inferred_movement",
            "emitter_name": sampled["name"].astype(str),
            "emitter_steamid": sampled["steamid_key"].astype(str),
            "x": sampled["X"].astype("float64"),
            "y": sampled["Y"].astype("float64"),
            "z": sampled["Z"].astype("float64"),
            "radius_world": 850.0,
            "duration_ticks": 7,
            "detail": sampled["detail"].astype("string"),
            "impact_speed_z": np.nan,
            "inferred_round_id": sampled["inferred_round_id"].astype("int64"),
            "inferred_round_tick": sampled["inferred_round_tick"].astype("int64"),
            "inferred_round_seconds": sampled["inferred_round_seconds"].astype("float64"),
        }
    )
    return result.sort_values(["tick", "emitter_name"]).reset_index(drop=True)


def build_grenade_bounce_sound_events(grenades: pd.DataFrame) -> pd.DataFrame:
    required = {"grenade_type", "grenade_entity_id", "x", "y", "z", "tick", "steamid", "name"}
    if grenades.empty or not required.issubset(grenades.columns):
        return _empty_sound_events()

    work = grenades[list(required | {"inferred_round_id", "inferred_round_tick", "inferred_round_seconds"})].copy()
    work["tick"] = pd.to_numeric(work["tick"], errors="coerce")
    work["x"] = pd.to_numeric(work["x"], errors="coerce")
    work["y"] = pd.to_numeric(work["y"], errors="coerce")
    work["z"] = pd.to_numeric(work["z"], errors="coerce")
    work["grenade_entity_id"] = pd.to_numeric(work["grenade_entity_id"], errors="coerce")
    work["steamid_key"] = _normalize_identifier(work["steamid"])
    work["name"] = _normalize_identifier(work["name"])
    work["grenade_type"] = work["grenade_type"].astype("string")
    work = work.dropna(subset=["tick", "x", "y", "z", "grenade_entity_id"]).copy()
    work = work[work["grenade_type"].str.contains("Projectile", na=False)].copy()
    if work.empty:
        return _empty_sound_events()

    work = work.sort_values(["grenade_entity_id", "tick"]).copy()
    entity_keys = ["grenade_entity_id"]
    work["prev_x"] = work.groupby(entity_keys, sort=False)["x"].shift(1)
    work["prev_y"] = work.groupby(entity_keys, sort=False)["y"].shift(1)
    work["prev_z"] = work.groupby(entity_keys, sort=False)["z"].shift(1)
    work["next_x"] = work.groupby(entity_keys, sort=False)["x"].shift(-1)
    work["next_y"] = work.groupby(entity_keys, sort=False)["y"].shift(-1)
    work["next_z"] = work.groupby(entity_keys, sort=False)["z"].shift(-1)

    work["vx_in"] = work["x"] - work["prev_x"]
    work["vy_in"] = work["y"] - work["prev_y"]
    work["vz_in"] = work["z"] - work["prev_z"]
    work["vx_out"] = work["next_x"] - work["x"]
    work["vy_out"] = work["next_y"] - work["y"]
    work["vz_out"] = work["next_z"] - work["z"]
    work["speed_in"] = np.sqrt(work["vx_in"] ** 2 + work["vy_in"] ** 2 + work["vz_in"] ** 2)
    work["speed_out"] = np.sqrt(work["vx_out"] ** 2 + work["vy_out"] ** 2 + work["vz_out"] ** 2)
    work["speed_in_xy"] = np.sqrt(work["vx_in"] ** 2 + work["vy_in"] ** 2)
    work["speed_out_xy"] = np.sqrt(work["vx_out"] ** 2 + work["vy_out"] ** 2)
    work["planar_turn"] = (work["vx_in"] * work["vx_out"]) + (work["vy_in"] * work["vy_out"])
    work["planar_turn_cos"] = work["planar_turn"] / (
        work["speed_in_xy"] * work["speed_out_xy"]
    )
    work["vertical_bounce"] = (work["vz_in"] < -1.5) & (work["vz_out"] > 1.5)
    work["hard_turn"] = (
        (work["speed_in_xy"] > 1.5)
        & (work["speed_out_xy"] > 1.5)
        & work["planar_turn_cos"].notna()
        & (work["planar_turn_cos"] < 0.985)
    )
    work["bounce_candidate"] = work["vertical_bounce"] | work["hard_turn"]
    candidates = work[work["bounce_candidate"]].copy()
    if candidates.empty:
        return _empty_sound_events()

    # A single wall impact often produces several adjacent trajectory kinks.
    # Collapse short same-grenade runs into one semantic bounce event.
    # IMPORTANT: this is semantic deduplication, not a visual tweak. Viewer code should
    # receive one bounce event per short impact burst instead of re-implementing this.
    candidates = candidates.sort_values(["grenade_entity_id", "tick"]).copy()
    tick_gap = candidates.groupby("grenade_entity_id", sort=False)["tick"].diff()
    candidates["bounce_cluster_start"] = tick_gap.isna() | (tick_gap > GRENADE_BOUNCE_CLUSTER_GAP_TICKS)
    candidates["bounce_cluster"] = (
        candidates.groupby("grenade_entity_id", sort=False)["bounce_cluster_start"].cumsum().astype("int64")
    )
    vertical_score = candidates["vertical_bounce"].astype("int64") * 1000
    impact_score = (
        candidates["vz_out"].abs().fillna(0.0)
        + candidates["vz_in"].abs().fillna(0.0)
        + candidates["speed_in_xy"].fillna(0.0)
        + candidates["speed_out_xy"].fillna(0.0)
    )
    candidates["bounce_pick_score"] = vertical_score + impact_score
    candidates = (
        candidates.sort_values(
            ["grenade_entity_id", "bounce_cluster", "bounce_pick_score", "tick"],
            ascending=[True, True, False, True],
        )
        .drop_duplicates(["grenade_entity_id", "bounce_cluster"], keep="first")
        .sort_values(["tick", "grenade_entity_id"])
        .copy()
    )

    candidates["detail"] = np.where(candidates["vertical_bounce"], "grenade_bounce_vertical", "grenade_bounce_turn")
    result = pd.DataFrame(
        {
            "tick": candidates["tick"].astype("int64"),
            "sound_kind": "grenade_bounce",
            "sound_source": "grenade_bounce",
            "emitter_name": candidates["name"].astype(str),
            "emitter_steamid": candidates["steamid_key"].astype(str),
            "grenade_entity_id": candidates["grenade_entity_id"].astype("Int64"),
            "x": candidates["x"].astype("float64"),
            "y": candidates["y"].astype("float64"),
            "z": candidates["z"].astype("float64"),
            "radius_world": 650.0,
            "duration_ticks": GRENADE_BOUNCE_DURATION_TICKS,
            "detail": (candidates["detail"].astype(str) + "|" + candidates["grenade_type"].astype(str)).astype("string"),
            "impact_speed_z": np.nan,
            "inferred_round_id": candidates["inferred_round_id"].astype("int64"),
            "inferred_round_tick": candidates["inferred_round_tick"].astype("int64"),
            "inferred_round_seconds": candidates["inferred_round_seconds"].astype("float64"),
        }
    )
    return result.sort_values(["tick", "emitter_name"]).reset_index(drop=True)


def normalize_sound_source(
    events: pd.DataFrame,
    *,
    sound_kind: str,
    sound_source: str,
    radius_world: float,
    duration_ticks: int,
    emitter_name_col: str | None,
    emitter_steamid_col: str | None,
    detail_value: str = "",
    x_candidates: list[str] | None = None,
    y_candidates: list[str] | None = None,
    z_candidates: list[str] | None = None,
) -> pd.DataFrame:
    if events.empty:
        return _empty_sound_events()
    if "tick" not in events.columns:
        raise ValueError(f"{sound_source} is missing required tick column")
    out = pd.DataFrame()
    out["tick"] = pd.to_numeric(events["tick"], errors="coerce").astype("Int64")
    out["sound_kind"] = sound_kind
    out["sound_source"] = sound_source
    out["emitter_name"] = _normalize_identifier(events[emitter_name_col]) if emitter_name_col and emitter_name_col in events.columns else ""
    out["emitter_steamid"] = _normalize_identifier(events[emitter_steamid_col]) if emitter_steamid_col and emitter_steamid_col in events.columns else ""
    out["grenade_entity_id"] = pd.Series(pd.NA, index=events.index, dtype="Int64")
    out["x"] = _coalesce_numeric(events, x_candidates or [])
    out["y"] = _coalesce_numeric(events, y_candidates or [])
    out["z"] = _coalesce_numeric(events, z_candidates or [])
    out["radius_world"] = float(radius_world)
    out["duration_ticks"] = int(duration_ticks)
    out["detail"] = detail_value
    out["impact_speed_z"] = np.nan
    for column in ("inferred_round_id", "inferred_round_tick", "inferred_round_seconds"):
        if column in events.columns:
            out[column] = events[column]
    out = out.dropna(subset=["tick"]).copy()
    out["tick"] = out["tick"].astype("int64")
    return out


def build_gunfire_sound_events(fires: pd.DataFrame) -> pd.DataFrame:
    if fires.empty:
        return _empty_sound_events()
    out = normalize_sound_source(
        fires,
        sound_kind="gunfire",
        sound_source="fire_bullets",
        radius_world=1600.0,
        duration_ticks=4,
        emitter_name_col="user_name",
        emitter_steamid_col="user_steamid",
        detail_value="event",
        x_candidates=["origin_x", "ent_origin_x", "X"],
        y_candidates=["origin_y", "ent_origin_y", "Y"],
        z_candidates=["origin_z", "ent_origin_z", "Z"],
    )
    if out.empty:
        return out

    item_def_index = pd.to_numeric(fires.get("item_def_index"), errors="coerce")
    radii: list[float] = []
    details: list[str] = []
    weapon_ids: list[str] = []
    audible_rules: list[str] = []
    is_globals: list[bool] = []
    is_suppressed: list[bool] = []
    for value in item_def_index.tolist():
        spec = find_weapon_spec(WEAPON_SPECS, value)
        if spec is None:
            radii.append(5000.0)
            weapon_ids.append("unknown")
            audible_rules.append("global")
            is_globals.append(True)
            is_suppressed.append(False)
            details.append("unknown_global")
            continue
        fire_radius = spec.sound.fire_radius if spec.sound.fire_radius is not None else 5000.0
        radii.append(float(fire_radius))
        weapon_ids.append(spec.weapon_id)
        if spec.sound.global_fire:
            audible_rules.append("global")
            is_globals.append(True)
            is_suppressed.append(False)
            details.append(f"{spec.weapon_id}_global")
        elif spec.sound.suppressed:
            audible_rules.append("radius")
            is_globals.append(False)
            is_suppressed.append(True)
            details.append(f"{spec.weapon_id}_suppressed")
        else:
            audible_rules.append("radius")
            is_globals.append(False)
            is_suppressed.append(False)
            details.append(spec.weapon_id)
    out["weapon_id"] = pd.Series(weapon_ids, index=out.index, dtype="string")
    out["audible_rule"] = pd.Series(audible_rules, index=out.index, dtype="string")
    out["is_global"] = pd.Series(is_globals, index=out.index, dtype="boolean")
    out["is_suppressed"] = pd.Series(is_suppressed, index=out.index, dtype="boolean")
    out["radius_world"] = radii
    out["detail"] = pd.Series(details, index=out.index, dtype="string")
    return out


def build_weapon_reload_sound_events(weapon_reloads: pd.DataFrame) -> pd.DataFrame:
    if weapon_reloads.empty:
        return _empty_sound_events()
    out = normalize_sound_source(
        weapon_reloads,
        sound_kind="utility",
        sound_source="weapon_reload",
        radius_world=550.0,
        duration_ticks=8,
        emitter_name_col="user_name",
        emitter_steamid_col="user_steamid",
        detail_value="reload",
    )
    if out.empty:
        return out
    if "defindex" not in weapon_reloads.columns:
        out["weapon_id"] = pd.Series(["unknown"] * len(out), index=out.index, dtype="string")
        out["audible_rule"] = pd.Series(["radius"] * len(out), index=out.index, dtype="string")
        out["is_global"] = pd.Series([False] * len(out), index=out.index, dtype="boolean")
        out["is_suppressed"] = pd.Series([False] * len(out), index=out.index, dtype="boolean")
        out["detail"] = pd.Series(["reload_default"] * len(out), index=out.index, dtype="string")
        return out
    defindex = pd.to_numeric(weapon_reloads.get("defindex"), errors="coerce")
    radii: list[float] = []
    details: list[str] = []
    weapon_ids: list[str] = []
    audible_rules: list[str] = []
    is_globals: list[bool] = []
    is_suppressed: list[bool] = []
    for value in defindex.tolist():
        spec = find_weapon_spec(WEAPON_SPECS, value)
        if spec is None:
            radii.append(550.0)
            weapon_ids.append("unknown")
            audible_rules.append("radius")
            is_globals.append(False)
            is_suppressed.append(False)
            details.append("reload_default")
            continue
        reload_radius = spec.sound.reload_radius if spec.sound.reload_radius is not None else 550.0
        radii.append(float(reload_radius))
        weapon_ids.append(spec.weapon_id)
        audible_rules.append("radius")
        is_globals.append(False)
        is_suppressed.append(bool(spec.sound.suppressed))
        details.append(f"{spec.weapon_id}_reload")
    out["weapon_id"] = pd.Series(weapon_ids, index=out.index, dtype="string")
    out["audible_rule"] = pd.Series(audible_rules, index=out.index, dtype="string")
    out["is_global"] = pd.Series(is_globals, index=out.index, dtype="boolean")
    out["is_suppressed"] = pd.Series(is_suppressed, index=out.index, dtype="boolean")
    out["radius_world"] = radii
    out["detail"] = pd.Series(details, index=out.index, dtype="string")
    return out


def build_weapon_zoom_sound_events(weapon_zooms: pd.DataFrame) -> pd.DataFrame:
    if weapon_zooms.empty:
        return _empty_sound_events()
    out = normalize_sound_source(
        weapon_zooms,
        sound_kind="utility",
        sound_source="weapon_zoom",
        radius_world=275.0,
        duration_ticks=6,
        emitter_name_col="user_name",
        emitter_steamid_col="user_steamid",
        detail_value="zoom",
    )
    if out.empty:
        return out
    if "defindex" not in weapon_zooms.columns:
        out["weapon_id"] = pd.Series(["unknown"] * len(out), index=out.index, dtype="string")
        out["audible_rule"] = pd.Series(["radius"] * len(out), index=out.index, dtype="string")
        out["is_global"] = pd.Series([False] * len(out), index=out.index, dtype="boolean")
        out["is_suppressed"] = pd.Series([False] * len(out), index=out.index, dtype="boolean")
        out["detail"] = pd.Series(["zoom_default"] * len(out), index=out.index, dtype="string")
        return out
    defindex = pd.to_numeric(weapon_zooms.get("defindex"), errors="coerce")
    radii: list[float] = []
    details: list[str] = []
    weapon_ids: list[str] = []
    audible_rules: list[str] = []
    is_globals: list[bool] = []
    is_suppressed: list[bool] = []
    for value in defindex.tolist():
        spec = find_weapon_spec(WEAPON_SPECS, value)
        if spec is None:
            radii.append(275.0)
            weapon_ids.append("unknown")
            audible_rules.append("radius")
            is_globals.append(False)
            is_suppressed.append(False)
            details.append("zoom_default")
            continue
        zoom_radius = spec.sound.zoom_radius if spec.sound.zoom_radius is not None else 275.0
        radii.append(float(zoom_radius))
        weapon_ids.append(spec.weapon_id)
        audible_rules.append("radius")
        is_globals.append(False)
        is_suppressed.append(bool(spec.sound.suppressed))
        details.append(f"{spec.weapon_id}_zoom")
    out["weapon_id"] = pd.Series(weapon_ids, index=out.index, dtype="string")
    out["audible_rule"] = pd.Series(audible_rules, index=out.index, dtype="string")
    out["is_global"] = pd.Series(is_globals, index=out.index, dtype="boolean")
    out["is_suppressed"] = pd.Series(is_suppressed, index=out.index, dtype="boolean")
    out["radius_world"] = radii
    out["detail"] = pd.Series(details, index=out.index, dtype="string")
    return out


def build_item_drop_sound_events(item_drops: pd.DataFrame) -> pd.DataFrame:
    if item_drops.empty:
        return _empty_sound_events()
    out = normalize_sound_source(
        item_drops,
        sound_kind="weapon_drop",
        sound_source="item_drop",
        radius_world=650.0,
        duration_ticks=10,
        emitter_name_col="user_name",
        emitter_steamid_col="user_steamid",
        detail_value="item_drop_unknown",
        x_candidates=["X", "x"],
        y_candidates=["Y", "y"],
        z_candidates=["Z", "z"],
    )
    if out.empty:
        return out
    if "defindex" not in item_drops.columns:
        out["weapon_id"] = pd.Series(["unknown"] * len(out), index=out.index, dtype="string")
        out["audible_rule"] = pd.Series(["radius"] * len(out), index=out.index, dtype="string")
        out["is_global"] = pd.Series([False] * len(out), index=out.index, dtype="boolean")
        out["is_suppressed"] = pd.Series([False] * len(out), index=out.index, dtype="boolean")
        return out

    defindex = pd.to_numeric(item_drops.get("defindex"), errors="coerce")
    item_name = _normalize_identifier(item_drops.get("item_name", pd.Series(index=item_drops.index, dtype="object"))).str.lower()
    keep_mask: list[bool] = []
    sound_kinds: list[str] = []
    radii: list[float] = []
    details: list[str] = []
    weapon_ids: list[str] = []
    audible_rules: list[str] = []
    is_globals: list[bool] = []
    is_suppressed: list[bool] = []

    grenade_weapon_ids = {
        "weapon_flashbang",
        "weapon_hegrenade",
        "weapon_smokegrenade",
        "weapon_molotov",
        "weapon_decoy",
        "weapon_incgrenade",
    }

    for index, value in enumerate(defindex.tolist()):
        name_value = item_name.iloc[index]
        spec = find_weapon_spec(WEAPON_SPECS, value)
        weapon_id = spec.weapon_id if spec is not None else "unknown"
        if value == 49 or "c4" in name_value or weapon_id == "weapon_c4":
            keep_mask.append(False)
            sound_kinds.append("bomb")
            radii.append(0.0)
            details.append("c4_drop")
            weapon_ids.append("weapon_c4")
            audible_rules.append("radius")
            is_globals.append(False)
            is_suppressed.append(False)
            continue

        keep_mask.append(True)
        drop_radius = spec.sound.drop_radius if spec is not None and spec.sound.drop_radius is not None else 650.0
        category_id = spec.category.id if spec is not None else ""
        category_name = spec.category.name if spec is not None else ""
        category_text = f"{category_id} {category_name}".lower()
        is_grenade = weapon_id in grenade_weapon_ids or "grenade" in weapon_id or "grenade" in category_text or "molotov" in weapon_id or "decoy" in weapon_id
        if is_grenade:
            sound_kind = "utility_drop"
            detail_prefix = "utility_drop"
        else:
            sound_kind = "weapon_drop"
            detail_prefix = "weapon_drop"
        sound_kinds.append(sound_kind)
        radii.append(float(drop_radius))
        details.append(f"{detail_prefix}|{weapon_id}")
        weapon_ids.append(weapon_id)
        audible_rules.append("radius")
        is_globals.append(False)
        is_suppressed.append(bool(spec.sound.suppressed) if spec is not None else False)

    out["sound_kind"] = pd.Series(sound_kinds, index=out.index, dtype="string")
    out["weapon_id"] = pd.Series(weapon_ids, index=out.index, dtype="string")
    out["audible_rule"] = pd.Series(audible_rules, index=out.index, dtype="string")
    out["is_global"] = pd.Series(is_globals, index=out.index, dtype="boolean")
    out["is_suppressed"] = pd.Series(is_suppressed, index=out.index, dtype="boolean")
    out["radius_world"] = radii
    out["detail"] = pd.Series(details, index=out.index, dtype="string")
    keep = pd.Series(keep_mask, index=out.index, dtype="boolean")
    out = out[keep.fillna(False)].copy()
    return out.reset_index(drop=True)


def build_sound_events(
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
    bomb_plants: pd.DataFrame,
    bomb_begin_defuses: pd.DataFrame,
    bomb_abort_defuses: pd.DataFrame,
    bomb_defuses: pd.DataFrame,
    bomb_pickups: pd.DataFrame,
    bomb_drops: pd.DataFrame,
    bomb_explodes: pd.DataFrame,
) -> pd.DataFrame:
    sound_tables = [
        normalize_sound_source(
            footsteps,
            sound_kind="footstep",
            sound_source="player_footstep",
            radius_world=850.0,
            duration_ticks=6,
            emitter_name_col="user_name",
            emitter_steamid_col="user_steamid",
            detail_value="event",
        ),
        build_gunfire_sound_events(fires),
        normalize_sound_source(
            hurts,
            sound_kind="damage",
            sound_source="player_hurt",
            radius_world=900.0,
            duration_ticks=8,
            emitter_name_col="user_name",
            emitter_steamid_col="user_steamid",
            detail_value="hurt",
        ),
        build_item_drop_sound_events(item_drops),
        build_weapon_reload_sound_events(weapon_reloads),
        build_weapon_zoom_sound_events(weapon_zooms),
        normalize_sound_source(
            smoke_detonates,
            sound_kind="utility",
            sound_source="smokegrenade_detonate",
            radius_world=1000.0,
            duration_ticks=10,
            emitter_name_col="user_name",
            emitter_steamid_col="user_steamid",
            detail_value="smoke",
            x_candidates=["x", "X"],
            y_candidates=["y", "Y"],
            z_candidates=["z", "Z"],
        ),
        normalize_sound_source(
            flash_detonates,
            sound_kind="utility",
            sound_source="flashbang_detonate",
            radius_world=1000.0,
            duration_ticks=10,
            emitter_name_col="user_name",
            emitter_steamid_col="user_steamid",
            detail_value="flash",
            x_candidates=["x", "X"],
            y_candidates=["y", "Y"],
            z_candidates=["z", "Z"],
        ),
        normalize_sound_source(
            he_detonates,
            sound_kind="utility",
            sound_source="hegrenade_detonate",
            radius_world=1200.0,
            duration_ticks=12,
            emitter_name_col="user_name",
            emitter_steamid_col="user_steamid",
            detail_value="he",
            x_candidates=["x", "X"],
            y_candidates=["y", "Y"],
            z_candidates=["z", "Z"],
        ),
        normalize_sound_source(
            inferno_starts,
            sound_kind="utility",
            sound_source="inferno_startburn",
            radius_world=1100.0,
            duration_ticks=16,
            emitter_name_col="user_name",
            emitter_steamid_col="user_steamid",
            detail_value="inferno",
            x_candidates=["x", "X"],
            y_candidates=["y", "Y"],
            z_candidates=["z", "Z"],
        ),
        build_grenade_bounce_sound_events(grenades),
        normalize_sound_source(
            bomb_pickups,
            sound_kind="bomb",
            sound_source="bomb_pickup",
            radius_world=700.0,
            duration_ticks=8,
            emitter_name_col="user_name",
            emitter_steamid_col="user_steamid",
            detail_value="pickup",
            x_candidates=["X"],
            y_candidates=["Y"],
            z_candidates=["Z"],
        ),
        normalize_sound_source(
            bomb_drops,
            sound_kind="bomb",
            sound_source="bomb_dropped",
            radius_world=700.0,
            duration_ticks=8,
            emitter_name_col="user_name",
            emitter_steamid_col="user_steamid",
            detail_value="drop",
            x_candidates=["X"],
            y_candidates=["Y"],
            z_candidates=["Z"],
        ),
        normalize_sound_source(
            bomb_begin_plants,
            sound_kind="bomb",
            sound_source="bomb_beginplant",
            radius_world=1200.0,
            duration_ticks=12,
            emitter_name_col="user_name",
            emitter_steamid_col="user_steamid",
            detail_value="begin_plant",
        ),
        normalize_sound_source(
            bomb_begin_defuses,
            sound_kind="bomb",
            sound_source="bomb_begindefuse",
            radius_world=1062.0,
            duration_ticks=16,
            emitter_name_col="user_name",
            emitter_steamid_col="user_steamid",
            detail_value="begin_defuse",
        ),
        normalize_sound_source(
            bomb_abort_defuses,
            sound_kind="bomb",
            sound_source="bomb_abortdefuse",
            radius_world=800.0,
            duration_ticks=10,
            emitter_name_col="user_name",
            emitter_steamid_col="user_steamid",
            detail_value="abort_defuse",
        ),
        normalize_sound_source(
            bomb_defuses,
            sound_kind="bomb",
            sound_source="bomb_defused",
            radius_world=1062.0,
            duration_ticks=16,
            emitter_name_col="user_name",
            emitter_steamid_col="user_steamid",
            detail_value="defused",
            x_candidates=["X"],
            y_candidates=["Y"],
            z_candidates=["Z"],
        ),
        normalize_sound_source(
            bomb_explodes,
            sound_kind="bomb",
            sound_source="bomb_exploded",
            radius_world=3000.0,
            duration_ticks=32,
            emitter_name_col="user_name",
            emitter_steamid_col="user_steamid",
            detail_value="exploded",
            x_candidates=["X"],
            y_candidates=["Y"],
            z_candidates=["Z"],
        ),
        build_movement_sound_events(ticks),
        build_landing_sound_events(ticks),
    ]
    combined = pd.concat(sound_tables, ignore_index=True)
    combined = enrich_sound_event_positions(combined, ticks)
    combined["detail"] = combined["detail"].astype("string").fillna("")
    combined["sound_kind"] = combined["sound_kind"].astype("string")
    combined["sound_source"] = combined["sound_source"].astype("string")
    combined["emitter_name"] = combined["emitter_name"].astype("string").fillna("")
    combined["emitter_steamid"] = combined["emitter_steamid"].astype("string").fillna("")
    if "weapon_id" in combined.columns:
        combined["weapon_id"] = combined["weapon_id"].astype("string").fillna("")
    if "audible_rule" in combined.columns:
        combined["audible_rule"] = combined["audible_rule"].astype("string").fillna("")
    if "is_global" in combined.columns:
        combined["is_global"] = combined["is_global"].astype("boolean")
    if "is_suppressed" in combined.columns:
        combined["is_suppressed"] = combined["is_suppressed"].astype("boolean")
    if "grenade_entity_id" in combined.columns:
        combined["grenade_entity_id"] = pd.to_numeric(combined["grenade_entity_id"], errors="coerce").astype("Int64")
    combined = combined.dropna(subset=["tick"]).copy()
    combined["tick"] = pd.to_numeric(combined["tick"], errors="coerce").astype("int64")
    if "inferred_round_id" in combined.columns:
        combined["inferred_round_id"] = pd.to_numeric(combined["inferred_round_id"], errors="coerce").astype("Int64")
        combined = combined[combined["inferred_round_id"].notna()].copy()
        combined["inferred_round_id"] = combined["inferred_round_id"].astype("int64")
    if "inferred_round_tick" in combined.columns:
        combined["inferred_round_tick"] = pd.to_numeric(combined["inferred_round_tick"], errors="coerce").fillna(0).astype("int64")
    if "inferred_round_seconds" in combined.columns:
        combined["inferred_round_seconds"] = pd.to_numeric(combined["inferred_round_seconds"], errors="coerce")
    combined["radius_world"] = pd.to_numeric(combined["radius_world"], errors="coerce")
    combined["duration_ticks"] = pd.to_numeric(combined["duration_ticks"], errors="coerce").fillna(0).astype("int64")
    combined["impact_speed_z"] = pd.to_numeric(combined["impact_speed_z"], errors="coerce")
    combined["x"] = pd.to_numeric(combined["x"], errors="coerce")
    combined["y"] = pd.to_numeric(combined["y"], errors="coerce")
    combined["z"] = pd.to_numeric(combined["z"], errors="coerce")
    combined = combined.sort_values(["tick", "sound_kind", "sound_source", "emitter_name"]).reset_index(drop=True)
    return combined


def build_inferred_rounds_table(ticks, jump_by_tick, round_start_ticks: list[int]):
    round_table = (
        ticks.groupby("inferred_round_id")
        .agg(
            start_tick=("tick", "min"),
            end_tick=("tick", "max"),
            n_rows=("tick", "size"),
            n_players=("name", "nunique"),
        )
        .reset_index()
    )
    boundary_info = jump_by_tick.loc[
        jump_by_tick["tick"].isin(round_start_ticks),
        ["tick", "n_jump_players", "max_jump", "median_jump"],
    ].rename(columns={"tick": "start_tick"})
    round_table = round_table.merge(boundary_info, on="start_tick", how="left")
    round_table["n_jump_players"] = round_table["n_jump_players"].fillna(0).astype(int)
    movement_info = infer_live_start_ticks(ticks)
    round_table = round_table.merge(movement_info, on="inferred_round_id", how="left")
    round_table["duration_ticks"] = round_table["end_tick"] - round_table["start_tick"]
    round_table["duration_seconds"] = round_table["duration_ticks"] / 64.0
    return round_table.sort_values("inferred_round_id").reset_index(drop=True)


def infer_live_start_ticks(ticks: pd.DataFrame, movement_epsilon: float = 1e-3) -> pd.DataFrame:
    if ticks.empty:
        return pd.DataFrame(
            columns=[
                "inferred_round_id",
                "freeze_start_tick",
                "live_start_tick",
                "freeze_end_tick",
                "freeze_duration_ticks",
                "freeze_duration_seconds",
            ]
        )
    work = ticks.sort_values(["inferred_round_id", "name", "tick"]).copy()
    work["dx_round"] = work.groupby(["inferred_round_id", "name"], sort=False)["X"].diff()
    work["dy_round"] = work.groupby(["inferred_round_id", "name"], sort=False)["Y"].diff()
    work["move_dist_round"] = np.sqrt((work["dx_round"] ** 2) + (work["dy_round"] ** 2))
    work["is_moving_after_reset"] = work["move_dist_round"] > movement_epsilon
    movement_by_tick = (
        work.groupby(["inferred_round_id", "tick"], as_index=False)
        .agg(n_moving_players=("is_moving_after_reset", "sum"))
    )
    initial_moving_ticks = (
        work.loc[work["is_moving_after_reset"], ["inferred_round_id", "tick"]]
        .groupby("inferred_round_id", as_index=False)
        .agg(live_start_tick=("tick", "min"))
    )
    round_bounds = (
        work.groupby("inferred_round_id", as_index=False)
        .agg(
            start_tick=("tick", "min"),
            end_tick=("tick", "max"),
        )
    )
    movement_info = round_bounds.merge(initial_moving_ticks, on="inferred_round_id", how="left")
    movement_info["live_start_tick"] = movement_info["live_start_tick"].fillna(movement_info["start_tick"]).astype("int64")
    movement_info["freeze_start_tick"] = movement_info["start_tick"]
    for index, row in movement_info.iterrows():
        if int(row["inferred_round_id"]) != 1:
            continue
        freeze_start_tick = _infer_round_one_freeze_start_tick(
            movement_by_tick=movement_by_tick,
            start_tick=int(row["start_tick"]),
            end_tick=int(row["end_tick"]),
        )
        movement_info.at[index, "freeze_start_tick"] = int(freeze_start_tick)
        movement_info.at[index, "live_start_tick"] = int(
            _infer_first_moving_tick_after(
                movement_by_tick=movement_by_tick,
                inferred_round_id=1,
                start_tick=int(freeze_start_tick),
                default_tick=int(row["live_start_tick"]),
            )
        )
    movement_info["freeze_start_tick"] = movement_info["freeze_start_tick"].astype("int64")
    movement_info["freeze_end_tick"] = (movement_info["live_start_tick"] - 1).clip(lower=movement_info["freeze_start_tick"]).astype("int64")
    movement_info["freeze_duration_ticks"] = (movement_info["live_start_tick"] - movement_info["freeze_start_tick"]).clip(lower=0).astype("int64")
    movement_info["freeze_duration_seconds"] = movement_info["freeze_duration_ticks"] / 64.0
    return movement_info[
        [
            "inferred_round_id",
            "freeze_start_tick",
            "live_start_tick",
            "freeze_end_tick",
            "freeze_duration_ticks",
            "freeze_duration_seconds",
        ]
    ]


def _infer_round_one_freeze_start_tick(
    *,
    movement_by_tick: pd.DataFrame,
    start_tick: int,
    end_tick: int,
    min_static_ticks: int = 32,
) -> int:
    if end_tick <= start_tick:
        return start_tick
    window = movement_by_tick[
        (movement_by_tick["inferred_round_id"] == 1)
        & (movement_by_tick["tick"] >= start_tick)
        & (movement_by_tick["tick"] <= end_tick)
    ].sort_values("tick")
    if window.empty:
        return start_tick
    quiet = window[window["n_moving_players"] == 0]["tick"].astype(int).tolist()
    if not quiet:
        return start_tick
    best_start = start_tick
    best_len = 0
    run_start = quiet[0]
    prev_tick = quiet[0]
    for tick_value in quiet[1:]:
        if tick_value == prev_tick + 1:
            prev_tick = tick_value
            continue
        run_len = prev_tick - run_start + 1
        if run_len >= min_static_ticks and run_len > best_len:
            best_start = run_start
            best_len = run_len
        run_start = tick_value
        prev_tick = tick_value
    run_len = prev_tick - run_start + 1
    if run_len >= min_static_ticks and run_len > best_len:
        best_start = run_start
        best_len = run_len
    return int(best_start if best_len > 0 else start_tick)


def _infer_first_moving_tick_after(
    *,
    movement_by_tick: pd.DataFrame,
    inferred_round_id: int,
    start_tick: int,
    default_tick: int,
) -> int:
    moving = movement_by_tick[
        (movement_by_tick["inferred_round_id"] == inferred_round_id)
        & (movement_by_tick["tick"] > start_tick)
        & (movement_by_tick["n_moving_players"] > 0)
    ].sort_values("tick")
    if moving.empty:
        return int(default_tick)
    return int(moving.iloc[0]["tick"])


def build_metadata(
    demo_path: Path,
    header: dict,
    ticks,
    deaths,
    fires,
    hurts,
    hits,
    item_drops,
    item_pickups,
    weapon_reloads,
    weapon_zooms,
    footsteps,
    smoke_detonates,
    flash_detonates,
    he_detonates,
    blinds,
    bomb_pickups,
    bomb_drops,
    bomb_begin_plants,
    bomb_plants,
    bomb_defuses,
    bomb_begin_defuses,
    bomb_abort_defuses,
    bomb_explodes,
    smoke_expires,
    inferno_starts,
    grenade_trajectory_segments,
    sound_events,
    inferred_rounds,
    jump_threshold: float,
    min_jump_players: int,
    min_gap_ticks: int,
    table_format: str,
    ticks_format: str,
    saved_paths: dict[str, Path],
):
    return {
        "demo_file": {
            "name": demo_path.name,
            "path": str(demo_path),
            "size_bytes": demo_path.stat().st_size,
        },
        "header": header,
        "derived": {
            "map_name": header.get("map_name"),
            "server_name": header.get("server_name"),
            "client_name": header.get("client_name"),
            "patch_version": header.get("patch_version"),
        },
        "storage": {
            "default_table_format": table_format,
            "ticks_format": ticks_format,
            "table_paths": {name: str(path) for name, path in saved_paths.items()},
        },
        "tables": {
            "ticks": {
                "rows": int(len(ticks)),
                "columns": list(ticks.columns),
            },
            "player_death": {
                "rows": int(len(deaths)),
                "columns": list(deaths.columns),
            },
            "fire_bullets": {
                "rows": int(len(fires)),
                "columns": list(fires.columns),
            },
            "player_hurt": {
                "rows": int(len(hurts)),
                "columns": list(hurts.columns),
            },
            "player_bullet_hit": {
                "rows": int(len(hits)),
                "columns": list(hits.columns),
            },
            "item_drop": {
                "rows": int(len(item_drops)),
                "columns": list(item_drops.columns),
            },
            "item_pickup": {
                "rows": int(len(item_pickups)),
                "columns": list(item_pickups.columns),
            },
            "weapon_reload": {
                "rows": int(len(weapon_reloads)),
                "columns": list(weapon_reloads.columns),
            },
            "weapon_zoom": {
                "rows": int(len(weapon_zooms)),
                "columns": list(weapon_zooms.columns),
            },
            "player_footstep": {
                "rows": int(len(footsteps)),
                "columns": list(footsteps.columns),
            },
            "inferred_rounds": {
                "rows": int(len(inferred_rounds)),
                "columns": list(inferred_rounds.columns),
            },
            "grenade_trajectory_segments": {
                "rows": int(len(grenade_trajectory_segments)),
                "columns": list(grenade_trajectory_segments.columns),
            },
            "inferno_startburn": {
                "rows": int(len(inferno_starts)),
                "columns": list(inferno_starts.columns),
            },
            "smokegrenade_detonate": {
                "rows": int(len(smoke_detonates)),
                "columns": list(smoke_detonates.columns),
            },
            "flashbang_detonate": {
                "rows": int(len(flash_detonates)),
                "columns": list(flash_detonates.columns),
            },
            "hegrenade_detonate": {
                "rows": int(len(he_detonates)),
                "columns": list(he_detonates.columns),
            },
            "player_blind": {
                "rows": int(len(blinds)),
                "columns": list(blinds.columns),
            },
            "bomb_pickup": {
                "rows": int(len(bomb_pickups)),
                "columns": list(bomb_pickups.columns),
            },
            "bomb_dropped": {
                "rows": int(len(bomb_drops)),
                "columns": list(bomb_drops.columns),
            },
            "bomb_beginplant": {
                "rows": int(len(bomb_begin_plants)),
                "columns": list(bomb_begin_plants.columns),
            },
            "bomb_planted": {
                "rows": int(len(bomb_plants)),
                "columns": list(bomb_plants.columns),
            },
            "bomb_defused": {
                "rows": int(len(bomb_defuses)),
                "columns": list(bomb_defuses.columns),
            },
            "bomb_begindefuse": {
                "rows": int(len(bomb_begin_defuses)),
                "columns": list(bomb_begin_defuses.columns),
            },
            "bomb_abortdefuse": {
                "rows": int(len(bomb_abort_defuses)),
                "columns": list(bomb_abort_defuses.columns),
            },
            "bomb_exploded": {
                "rows": int(len(bomb_explodes)),
                "columns": list(bomb_explodes.columns),
            },
            "smokegrenade_expired": {
                "rows": int(len(smoke_expires)),
                "columns": list(smoke_expires.columns),
            },
            "sound_events": {
                "rows": int(len(sound_events)),
                "columns": list(sound_events.columns),
            },
        },
        "round_inference": {
            "method": "global_jump_sync",
            "jump_threshold": jump_threshold,
            "min_jump_players": min_jump_players,
            "min_gap_ticks": min_gap_ticks,
            "round_ids": inferred_rounds["inferred_round_id"].astype(int).tolist(),
            "round_start_ticks": inferred_rounds["start_tick"].astype(int).tolist(),
        },
        "players": sorted([name for name in ticks["name"].dropna().unique().tolist()]),
    }
if __name__ == "__main__":
    main()
