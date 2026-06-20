from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from demoparser2 import DemoParser

from wall.io.table_io import DEFAULT_TABLE_FORMAT, write_table


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
            "total_rounds_played",
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

    demo = DemoParser(str(args.demo))
    header = demo.parse_header()

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
    ticks = demo.parse_ticks(args.tick_fields)
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
    smoke_detonates = attach_inferred_round_info(smoke_detonates, round_start_ticks, tick_col="tick")
    flash_detonates = attach_inferred_round_info(flash_detonates, round_start_ticks, tick_col="tick")
    he_detonates = attach_inferred_round_info(he_detonates, round_start_ticks, tick_col="tick")
    blinds = attach_inferred_round_info(blinds, round_start_ticks, tick_col="tick")
    bomb_pickups = attach_inferred_round_info(bomb_pickups, round_start_ticks, tick_col="tick")
    bomb_drops = attach_inferred_round_info(bomb_drops, round_start_ticks, tick_col="tick")
    bomb_plants = attach_inferred_round_info(bomb_plants, round_start_ticks, tick_col="tick")
    bomb_defuses = attach_inferred_round_info(bomb_defuses, round_start_ticks, tick_col="tick")
    bomb_begin_defuses = attach_inferred_round_info(bomb_begin_defuses, round_start_ticks, tick_col="tick")
    bomb_abort_defuses = attach_inferred_round_info(bomb_abort_defuses, round_start_ticks, tick_col="tick")
    bomb_explodes = attach_inferred_round_info(bomb_explodes, round_start_ticks, tick_col="tick")
    smoke_expires = attach_inferred_round_info(smoke_expires, round_start_ticks, tick_col="tick")
    inferno_starts = attach_inferred_round_info(inferno_starts, round_start_ticks, tick_col="tick")
    grenades = attach_inferred_round_info(grenades, round_start_ticks, tick_col="tick")
    inferred_rounds = build_inferred_rounds_table(ticks, jump_by_tick, round_start_ticks)
    table_format = args.table_format
    ticks_format = args.ticks_format or table_format

    output_dir = args.output_dir / args.demo.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata_json = output_dir / "metadata.json"
    saved_paths = {
        "player_death": write_table(deaths, output_dir, "player_death", table_format),
        "fire_bullets": write_table(fires, output_dir, "fire_bullets", table_format),
        "player_hurt": write_table(hurts, output_dir, "player_hurt", table_format),
        "player_bullet_hit": write_table(hits, output_dir, "player_bullet_hit", table_format),
        "smokegrenade_detonate": write_table(smoke_detonates, output_dir, "smokegrenade_detonate", table_format),
        "flashbang_detonate": write_table(flash_detonates, output_dir, "flashbang_detonate", table_format),
        "hegrenade_detonate": write_table(he_detonates, output_dir, "hegrenade_detonate", table_format),
        "player_blind": write_table(blinds, output_dir, "player_blind", table_format),
        "bomb_pickup": write_table(bomb_pickups, output_dir, "bomb_pickup", table_format),
        "bomb_dropped": write_table(bomb_drops, output_dir, "bomb_dropped", table_format),
        "bomb_planted": write_table(bomb_plants, output_dir, "bomb_planted", table_format),
        "bomb_defused": write_table(bomb_defuses, output_dir, "bomb_defused", table_format),
        "bomb_begindefuse": write_table(bomb_begin_defuses, output_dir, "bomb_begindefuse", table_format),
        "bomb_abortdefuse": write_table(bomb_abort_defuses, output_dir, "bomb_abortdefuse", table_format),
        "bomb_exploded": write_table(bomb_explodes, output_dir, "bomb_exploded", table_format),
        "smokegrenade_expired": write_table(smoke_expires, output_dir, "smokegrenade_expired", table_format),
        "inferno_startburn": write_table(inferno_starts, output_dir, "inferno_startburn", table_format),
        "grenades": write_table(grenades, output_dir, "grenades", table_format),
        "ticks": write_table(ticks, output_dir, "ticks", ticks_format),
        "inferred_rounds": write_table(inferred_rounds, output_dir, "inferred_rounds", table_format),
    }
    metadata = build_metadata(
        demo_path=args.demo,
        header=header,
        ticks=ticks,
        deaths=deaths,
        fires=fires,
        hurts=hurts,
        hits=hits,
        smoke_detonates=smoke_detonates,
        flash_detonates=flash_detonates,
        he_detonates=he_detonates,
        blinds=blinds,
        bomb_pickups=bomb_pickups,
        bomb_drops=bomb_drops,
        bomb_plants=bomb_plants,
        bomb_defuses=bomb_defuses,
        bomb_begin_defuses=bomb_begin_defuses,
        bomb_abort_defuses=bomb_abort_defuses,
        bomb_explodes=bomb_explodes,
        smoke_expires=smoke_expires,
        inferno_starts=inferno_starts,
        grenades=grenades,
        inferred_rounds=inferred_rounds,
        jump_threshold=args.jump_threshold,
        min_jump_players=args.min_jump_players,
        min_gap_ticks=args.min_gap_ticks,
        table_format=table_format,
        ticks_format=ticks_format,
        saved_paths=saved_paths,
    )
    metadata_json.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print(f"Demo: {args.demo}")
    print(f"Map: {header.get('map_name', 'unknown')}")
    print_summary("player_death", deaths)
    print(f"Saved: {saved_paths['player_death']}")
    print_summary("fire_bullets", fires)
    print(f"Saved: {saved_paths['fire_bullets']}")
    print_summary("player_hurt", hurts)
    print(f"Saved: {saved_paths['player_hurt']}")
    print_summary("player_bullet_hit", hits)
    print(f"Saved: {saved_paths['player_bullet_hit']}")
    print_summary("smokegrenade_detonate", smoke_detonates)
    print(f"Saved: {saved_paths['smokegrenade_detonate']}")
    print_summary("flashbang_detonate", flash_detonates)
    print(f"Saved: {saved_paths['flashbang_detonate']}")
    print_summary("hegrenade_detonate", he_detonates)
    print(f"Saved: {saved_paths['hegrenade_detonate']}")
    print_summary("player_blind", blinds)
    print(f"Saved: {saved_paths['player_blind']}")
    print_summary("bomb_pickup", bomb_pickups)
    print(f"Saved: {saved_paths['bomb_pickup']}")
    print_summary("bomb_dropped", bomb_drops)
    print(f"Saved: {saved_paths['bomb_dropped']}")
    print_summary("bomb_planted", bomb_plants)
    print(f"Saved: {saved_paths['bomb_planted']}")
    print_summary("bomb_defused", bomb_defuses)
    print(f"Saved: {saved_paths['bomb_defused']}")
    print_summary("bomb_begindefuse", bomb_begin_defuses)
    print(f"Saved: {saved_paths['bomb_begindefuse']}")
    print_summary("bomb_abortdefuse", bomb_abort_defuses)
    print(f"Saved: {saved_paths['bomb_abortdefuse']}")
    print_summary("bomb_exploded", bomb_explodes)
    print(f"Saved: {saved_paths['bomb_exploded']}")
    print_summary("smokegrenade_expired", smoke_expires)
    print(f"Saved: {saved_paths['smokegrenade_expired']}")
    print_summary("inferno_startburn", inferno_starts)
    print(f"Saved: {saved_paths['inferno_startburn']}")
    print_summary("grenades", grenades)
    print(f"Saved: {saved_paths['grenades']}")
    print()
    print_summary("Ticks", ticks)
    print(f"Saved: {saved_paths['ticks']}")
    print()
    print_summary("Inferred rounds", inferred_rounds)
    print(f"Saved: {saved_paths['inferred_rounds']}")
    print(f"Saved: {metadata_json}")


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
    round_table["duration_ticks"] = round_table["end_tick"] - round_table["start_tick"]
    round_table["duration_seconds"] = round_table["duration_ticks"] / 64.0
    return round_table.sort_values("inferred_round_id").reset_index(drop=True)


def build_metadata(
    demo_path: Path,
    header: dict,
    ticks,
    deaths,
    fires,
    hurts,
    hits,
    smoke_detonates,
    flash_detonates,
    he_detonates,
    blinds,
    bomb_pickups,
    bomb_drops,
    bomb_plants,
    bomb_defuses,
    bomb_begin_defuses,
    bomb_abort_defuses,
    bomb_explodes,
    smoke_expires,
    inferno_starts,
    grenades,
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
            "inferred_rounds": {
                "rows": int(len(inferred_rounds)),
                "columns": list(inferred_rounds.columns),
            },
            "grenades": {
                "rows": int(len(grenades)),
                "columns": list(grenades.columns),
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


def print_summary(title: str, df) -> None:
    print(f"{title}: {len(df)} rows, {len(df.columns)} columns")
    print(f"Columns: {', '.join(df.columns)}")


if __name__ == "__main__":
    main()
