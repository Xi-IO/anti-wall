from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from demoparser2 import DemoParser

from wall.io.grenade_segments import build_grenade_trajectory_segments_table
from wall.io.sound_effects import build_sound_effects
from wall.io.table_io import DEFAULT_TABLE_FORMAT, write_table
from wall.output import print_milestone, progress_enabled, print_status
from wall.profile import profile_log, profile_note


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
    print_milestone(f"[parse] Opening demo: {args.demo}")
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
    print_milestone(
        "[parse] Event tables ready: "
        f"fires={len(fires):,}, hurts={len(hurts):,}, footsteps={len(footsteps):,}, grenades={len(grenades):,}"
    )

    _print_parse_progress(3, total_stages, "Parsing tick frames")
    ticks = demo.parse_ticks(args.tick_fields)
    print_milestone(f"[parse] Tick frames ready: {len(ticks):,} rows")

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
    sound_effects = build_sound_effects(
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
        bomb_begin_defuses=bomb_begin_defuses,
        bomb_abort_defuses=bomb_abort_defuses,
        bomb_defuses=bomb_defuses,
        bomb_drops=bomb_drops,
        bomb_explodes=bomb_explodes,
    )
    inferred_rounds = build_inferred_rounds_table(ticks, jump_by_tick, round_start_ticks)
    grenade_trajectory_segments = build_grenade_trajectory_segments_table(grenades, tickrate=64.0)
    print_milestone(
        "[parse] Derived tables ready: "
        f"rounds={len(inferred_rounds):,}, sound_effects={len(sound_effects):,}, "
        f"grenade_segments={len(grenade_trajectory_segments):,}"
    )
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
        "sound_effect": write_table(sound_effects, output_dir, "sound_effect", table_format),
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
        sound_effects=sound_effects,
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
    print_milestone(f"[parse] Metadata written: {metadata_json}")

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
    sound_effects,
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
            "sound_effect": {
                "rows": int(len(sound_effects)),
                "columns": list(sound_effects.columns),
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
