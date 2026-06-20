from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from wall.paths import DEFAULT_OUTPUTS_DIR, dataset_dir_for_demo, looks_like_dataset_dir


def build_playback_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wall",
        description="Open a CS2 demo or parsed dataset in the viewer.",
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Path to a .dem file or a parsed dataset directory",
    )
    parser.add_argument(
        "--renew",
        action="store_true",
        help="Force rebuilding the parsed dataset before opening",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUTS_DIR,
        help="Directory that will contain per-demo output folders",
    )
    parser.add_argument(
        "--table-format",
        choices=["parquet", "csv"],
        default=None,
        help="Storage format for parsed tables",
    )
    parser.add_argument(
        "--ticks-format",
        choices=["parquet", "csv"],
        default=None,
        help="Optional override for ticks only",
    )
    parser.add_argument("--tick-fields", nargs="*", default=None, help="Tick fields to request")
    parser.add_argument("--jump-threshold", type=float, default=None)
    parser.add_argument("--min-jump-players", type=int, default=None)
    parser.add_argument("--min-gap-ticks", type=int, default=None)
    parser.add_argument("--round", dest="round_id", type=int, default=None)
    parser.add_argument("--map-width", type=int, default=1200)
    parser.add_argument("--map-height", type=int, default=900)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--frame-step", type=int, default=1)
    parser.add_argument("--tickrate", type=float, default=64.0)
    return parser


def build_catalog_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wall catalog",
        description="Build a DuckDB catalog for a parsed dataset.",
    )
    parser.add_argument("dataset", type=Path, help="Directory containing parsed output tables")
    parser.add_argument("--db-path", type=Path, default=None)
    return parser


def build_parse_argv(args: argparse.Namespace, demo_path: Path, output_dir: Path) -> list[str]:
    argv = [str(demo_path), "--output-dir", str(output_dir)]
    if args.table_format is not None:
        argv.extend(["--table-format", args.table_format])
    if args.ticks_format is not None:
        argv.extend(["--ticks-format", args.ticks_format])
    if args.tick_fields is not None:
        argv.extend(["--tick-fields", *args.tick_fields])
    if args.jump_threshold is not None:
        argv.extend(["--jump-threshold", str(args.jump_threshold)])
    if args.min_jump_players is not None:
        argv.extend(["--min-jump-players", str(args.min_jump_players)])
    if args.min_gap_ticks is not None:
        argv.extend(["--min-gap-ticks", str(args.min_gap_ticks)])
    return argv


def handle_parse(args: argparse.Namespace, demo_path: Path, output_dir: Path) -> int:
    from wall.io.demo_parse import main as parse_main

    parse_main(build_parse_argv(args, demo_path, output_dir))
    return 0


def handle_view(dataset: Path, args: argparse.Namespace) -> int:
    from wall.viewer.app import main as view_main

    if not looks_like_dataset_dir(dataset):
        raise FileNotFoundError(f"Dataset directory not found or invalid: {dataset}")
    argv = [str(dataset)]
    if args.round_id is not None:
        argv.extend(["--round", str(args.round_id)])
    argv.extend(
        [
            "--map-width",
            str(args.map_width),
            "--map-height",
            str(args.map_height),
            "--fps",
            str(args.fps),
            "--frame-step",
            str(args.frame_step),
            "--tickrate",
            str(args.tickrate),
        ]
    )
    view_main(argv)
    return 0


def resolve_dataset_demo_path(dataset_dir: Path) -> Path | None:
    metadata_path = dataset_dir / "metadata.json"
    if not metadata_path.exists():
        return None
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    demo_path = metadata.get("demo_file", {}).get("path")
    if not demo_path:
        return None
    return Path(demo_path)


def handle_playback(args: argparse.Namespace) -> int:
    source = args.source
    if source.suffix.lower() == ".dem":
        demo_path = source
        dataset_dir = dataset_dir_for_demo(demo_path, args.output_dir)
        should_parse = args.renew or not looks_like_dataset_dir(dataset_dir)
        if should_parse:
            handle_parse(args, demo_path=demo_path, output_dir=args.output_dir)
        return handle_view(dataset_dir, args)

    if looks_like_dataset_dir(source):
        dataset_dir = source
        if args.renew:
            demo_path = resolve_dataset_demo_path(dataset_dir)
            if demo_path is None:
                raise FileNotFoundError(
                    f"Cannot renew dataset without metadata demo path: {dataset_dir}"
                )
            if not demo_path.exists():
                raise FileNotFoundError(
                    f"Original demo referenced by metadata no longer exists: {demo_path}"
                )
            handle_parse(args, demo_path=demo_path, output_dir=dataset_dir.parent)
        return handle_view(dataset_dir, args)

    raise FileNotFoundError(
        "Input must be either a .dem file or a parsed dataset directory. "
        f"For raw demos use the full .dem path; got: {source}"
    )


def handle_catalog(args: argparse.Namespace) -> int:
    from wall.io.duckdb_catalog import main as catalog_main

    if not looks_like_dataset_dir(args.dataset):
        raise FileNotFoundError(f"Dataset directory not found or invalid: {args.dataset}")
    argv = [str(args.dataset)]
    if args.db_path is not None:
        argv.extend(["--db-path", str(args.db_path)])
    catalog_main(argv)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "catalog":
        parser = build_catalog_parser()
        args = parser.parse_args(argv[1:])
        return int(handle_catalog(args))

    parser = build_playback_parser()
    args = parser.parse_args(argv)
    return int(handle_playback(args))


if __name__ == "__main__":
    raise SystemExit(main())
