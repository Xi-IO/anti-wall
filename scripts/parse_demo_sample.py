from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from demoparser2 import DemoParser


def main() -> None:
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
        "--event-name",
        default="player_death",
        help="Event name to parse",
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
        help="Directory to write CSV files into",
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
    args = parser.parse_args()

    if not args.demo.exists():
        raise FileNotFoundError(f"Demo not found: {args.demo}")

    demo = DemoParser(str(args.demo))
    header = demo.parse_header()

    events = demo.parse_event(
        args.event_name,
        player=["X", "Y", "Z", "yaw", "pitch", "player_name", "player_steamid"],
        other=["total_rounds_played"],
    )
    ticks = demo.parse_ticks(args.tick_fields)
    jump_by_tick, round_start_ticks = infer_round_boundaries(
        ticks,
        jump_threshold=args.jump_threshold,
        min_jump_players=args.min_jump_players,
        min_gap_ticks=args.min_gap_ticks,
    )
    ticks = attach_inferred_round_id(ticks, round_start_ticks, tick_col="tick")
    events = attach_inferred_round_id(events, round_start_ticks, tick_col="tick")
    inferred_rounds = build_inferred_rounds_table(ticks, jump_by_tick, round_start_ticks)

    output_dir = args.output_dir / args.demo.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    events_csv = output_dir / f"{args.event_name}.csv"
    ticks_csv = output_dir / "ticks.csv"
    inferred_rounds_csv = output_dir / "inferred_rounds.csv"
    metadata_json = output_dir / "metadata.json"
    events.to_csv(events_csv, index=False)
    ticks.to_csv(ticks_csv, index=False)
    inferred_rounds.to_csv(inferred_rounds_csv, index=False)
    metadata = build_metadata(
        demo_path=args.demo,
        header=header,
        ticks=ticks,
        events=events,
        inferred_rounds=inferred_rounds,
        event_name=args.event_name,
        jump_threshold=args.jump_threshold,
        min_jump_players=args.min_jump_players,
        min_gap_ticks=args.min_gap_ticks,
    )
    metadata_json.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print(f"Demo: {args.demo}")
    print(f"Map: {header.get('map_name', 'unknown')}")
    print_summary("Events", events)
    print(f"Saved: {events_csv}")
    print()
    print_summary("Ticks", ticks)
    print(f"Saved: {ticks_csv}")
    print()
    print_summary("Inferred rounds", inferred_rounds)
    print(f"Saved: {inferred_rounds_csv}")
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


def attach_inferred_round_id(df, round_start_ticks: list[int], tick_col: str):
    out = df.copy()
    starts = np.array(sorted(round_start_ticks))
    out["inferred_round_id"] = np.searchsorted(starts, out[tick_col].to_numpy(), side="right")
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
    return round_table.sort_values("inferred_round_id").reset_index(drop=True)


def build_metadata(
    demo_path: Path,
    header: dict,
    ticks,
    events,
    inferred_rounds,
    event_name: str,
    jump_threshold: float,
    min_jump_players: int,
    min_gap_ticks: int,
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
        "tables": {
            "ticks": {
                "rows": int(len(ticks)),
                "columns": list(ticks.columns),
            },
            event_name: {
                "rows": int(len(events)),
                "columns": list(events.columns),
            },
            "inferred_rounds": {
                "rows": int(len(inferred_rounds)),
                "columns": list(inferred_rounds.columns),
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
