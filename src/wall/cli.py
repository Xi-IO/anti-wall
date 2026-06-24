from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from wall.output import applied_output_mode, progress_enabled, print_status
from wall.assets import (
    FEATURE_ARTIFACTS,
    AssetError,
    artifact_status,
    check_or_raise_for_feature,
    collect_missing_artifacts,
    download_artifact,
    required_artifacts_for_feature,
)
from wall.paths import DEFAULT_OUTPUTS_DIR, dataset_dir_for_demo, looks_like_dataset_dir


def _build_visibility_progress_callback(total_rounds: int):
    print("", flush=True)
    print("Visibility Progress", flush=True)
    print(f"{'progress':>12}  {'round':>8}", flush=True)
    print(f"{'-' * 12}  {'-' * 8}", flush=True)

    def _print_progress(round_id: int, completed: int, total: int) -> None:
        _ = total
        print(f"{(str(completed) + '/' + str(total_rounds)):>12}  {('round ' + str(round_id)):>8}", flush=True)

    return _print_progress


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
        "--no-visibility",
        action="store_true",
        help="Skip automatic visibility artifact generation before opening.",
    )
    parser.add_argument(
        "--renew-visibility",
        action="store_true",
        help="Regenerate visibility.parquet even if it already exists.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print user-facing status updates for parse, visibility, and viewer startup.",
    )
    parser.add_argument(
        "--profile",
        action="store_true",
        help="Enable viewer profiling output. Equivalent to WALL_VIEWER_PROFILE=1 for this run.",
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


def build_assets_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wall assets",
        description="Check or download local Awpy map assets used by wall.",
    )
    parser.add_argument(
        "action",
        choices=["check", "init"],
        help="Check local assets or download missing ones.",
    )
    parser.add_argument(
        "--feature",
        choices=sorted(FEATURE_ARTIFACTS),
        default="analysis",
        help="Feature profile that determines required artifacts.",
    )
    parser.add_argument("--map-name", default=None, help="Optional map name such as de_dust2")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help="Optional dataset directory used to infer the map name from metadata.json.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Download missing assets without prompting.",
    )
    return parser


def build_visibility_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wall visibility",
        description="Export visibility judgements or summaries for a parsed dataset.",
    )
    parser.add_argument("dataset", type=Path, help="Directory containing parsed output tables")
    parser.add_argument(
        "--round",
        dest="round_ids",
        type=int,
        nargs="+",
        default=None,
        help="Optional round ids to export. Omit to export all inferred rounds in the dataset.",
    )
    parser.add_argument("--tick", type=int, default=None, help="Optional single tick to export")
    parser.add_argument("--tick-step", type=int, default=8, help="Sample every Nth tick when --tick is not set. Default: 8")
    parser.add_argument("--observer", default=None, help="Optional observer name filter")
    parser.add_argument("--only-visible", action="store_true", help="Keep only rows where is_visible is true")
    parser.add_argument("--summary", action="store_true", help="Export one row per observer per tick instead of pair rows")
    parser.add_argument(
        "--output-kind",
        choices=["pair", "summary", "both"],
        default=None,
        help="Output kind. Defaults to pair unless --summary is set.",
    )
    parser.add_argument(
        "--include-freeze-time",
        action="store_true",
        help="Include ticks before live_start_tick when exporting a whole round.",
    )
    parser.add_argument(
        "--format",
        choices=["parquet", "csv"],
        default=None,
        help="Output format. Defaults to parquet when available, otherwise csv.",
    )
    parser.add_argument(
        "--profile-visibility",
        action="store_true",
        help="Print timing and counter breakdown for the visibility pipeline.",
    )
    parser.add_argument(
        "--profile-los-overlap",
        action="store_true",
        help="Diagnostic only: compare LOS request key overlap between summary and pair paths.",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=4,
        help="Number of worker processes for round-level visibility export. Default: 4",
    )
    parser.add_argument(
        "--split-rounds",
        action="store_true",
        help="Write one output file per round instead of the default combined multi-round table.",
    )
    parser.add_argument("--output", type=Path, default=None, help="Explicit output file path")
    parser.add_argument("--tickrate", type=float, default=64.0, help="Tickrate used to build round data")
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


def ensure_default_visibility_artifact(
    dataset_dir: Path,
    *,
    force: bool = False,
    tickrate: float = 64.0,
) -> Path | None:
    if not looks_like_dataset_dir(dataset_dir):
        raise FileNotFoundError(f"Dataset directory not found or invalid: {dataset_dir}")
    output_path = dataset_dir / "visibility.parquet"
    if output_path.exists() and not force:
        return None
    map_name = resolve_dataset_map_name(dataset_dir)
    if map_name:
        check_or_raise_for_feature("visibility", map_name=map_name, prompt=True)
    from wall.visibility.dataset import MatchDataset
    from wall.visibility.export import run_visibility_exports

    loaded = MatchDataset.from_data_dir(dataset_dir)
    round_ids = [int(round_id) for round_id in loaded.round_ids]
    if not round_ids:
        raise ValueError(f"No inferred rounds available for visibility export: {dataset_dir}")
    progress_callback = _build_visibility_progress_callback(len(round_ids)) if progress_enabled() else None
    result = run_visibility_exports(
        dataset_dir,
        round_ids=round_ids,
        output_path=output_path,
        tick_step=8,
        tickrate=tickrate,
        table_format="parquet",
        dataset=loaded if len(round_ids) == 1 else None,
        jobs=4,
        combine_rounds=True,
        output_kind="pair",
        progress_callback=progress_callback,
    )
    if result.output_paths is None or "pair" not in result.output_paths:
        raise RuntimeError(f"Visibility export did not produce pair output for {dataset_dir}")
    print_status(f"Visibility pair table written to: {result.output_paths['pair']}")
    return result.output_paths["pair"]


def handle_view(dataset: Path, args: argparse.Namespace) -> int:
    if not looks_like_dataset_dir(dataset):
        raise FileNotFoundError(f"Dataset directory not found or invalid: {dataset}")
    demo_map_name = resolve_dataset_map_name(dataset)
    if demo_map_name:
        check_or_raise_for_feature("viewer", map_name=str(demo_map_name), prompt=True)
    from wall.viewer.cli import main as view_main

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


def resolve_dataset_map_name(dataset_dir: Path) -> str | None:
    metadata_path = dataset_dir / "metadata.json"
    if not metadata_path.exists():
        return None
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    map_name = metadata.get("derived", {}).get("map_name")
    return str(map_name) if map_name else None


def handle_playback(args: argparse.Namespace) -> int:
    with applied_output_mode(
        verbose=bool(getattr(args, "verbose", False)),
        profile=bool(getattr(args, "profile", False)),
    ):
        source = args.source
        if source.suffix.lower() == ".dem":
            demo_path = source
            dataset_dir = dataset_dir_for_demo(demo_path, args.output_dir)
            should_parse = args.renew or not looks_like_dataset_dir(dataset_dir)
            if should_parse:
                handle_parse(args, demo_path=demo_path, output_dir=args.output_dir)
            if not args.no_visibility:
                ensure_default_visibility_artifact(
                    dataset_dir,
                    force=bool(args.renew or args.renew_visibility),
                    tickrate=float(args.tickrate),
                )
            return handle_view(dataset_dir, args)

        if looks_like_dataset_dir(source):
            dataset_dir = source
            rebuilt_dataset = False
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
                rebuilt_dataset = True
            if not args.no_visibility:
                ensure_default_visibility_artifact(
                    dataset_dir,
                    force=bool(rebuilt_dataset or args.renew_visibility),
                    tickrate=float(args.tickrate),
                )
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


def handle_assets(args: argparse.Namespace) -> int:
    map_name = args.map_name
    if map_name is None and args.dataset is not None:
        if not looks_like_dataset_dir(args.dataset):
            raise FileNotFoundError(f"Dataset directory not found or invalid: {args.dataset}")
        map_name = resolve_dataset_map_name(args.dataset)
    artifacts = required_artifacts_for_feature(args.feature)
    if args.action == "check":
        missing = collect_missing_artifacts(artifacts, map_name)
        if not missing:
            print(f"Awpy assets ready for {args.feature}.")
            for artifact in artifacts:
                status = artifact_status(artifact, map_name)
                print(f"- {artifact}: {status.path}")
            return 0
        print(f"Missing Awpy assets for {args.feature}:")
        for status in missing:
            print(f"- {status.artifact}: {status.path}")
        return 1

    missing = collect_missing_artifacts(artifacts, map_name)
    if not missing:
        print(f"Awpy assets already ready for {args.feature}.")
        return 0
    if args.yes:
        for status in missing:
            download_artifact(status.artifact)
    else:
        check_or_raise_for_feature(args.feature, map_name=map_name, prompt=True)
    still_missing = collect_missing_artifacts(artifacts, map_name)
    if still_missing:
        raise AssetError(
            "Awpy asset initialization did not complete: "
            + ", ".join(f"{status.artifact} ({status.path})" for status in still_missing)
        )
    print(f"Awpy assets ready for {args.feature}.")
    return 0


def handle_visibility(args: argparse.Namespace) -> int:
    from wall.visibility.dataset import MatchDataset
    from wall.analysis.visibility_export import profile_los_overlap, run_visibility_exports

    def _visibility_print(message: str = "") -> None:
        print(message, flush=True)

    if not looks_like_dataset_dir(args.dataset):
        raise FileNotFoundError(f"Dataset directory not found or invalid: {args.dataset}")
    if args.jobs < 1:
        raise ValueError("--jobs must be at least 1.")
    map_name = resolve_dataset_map_name(args.dataset)
    if map_name:
        check_or_raise_for_feature("visibility", map_name=map_name, prompt=True)
    loaded = MatchDataset.from_data_dir(args.dataset) if args.jobs == 1 else None
    loaded_for_rounds = loaded if loaded is not None else MatchDataset.from_data_dir(args.dataset)
    if args.round_ids is None:
        round_ids = [int(round_id) for round_id in loaded_for_rounds.round_ids]
    else:
        round_ids = [int(round_id) for round_id in args.round_ids]
    progress_callback = None
    if not args.profile_visibility:
        progress_callback = _build_visibility_progress_callback(len(round_ids))
    combine_rounds = not args.split_rounds
    if len(round_ids) > 1 and args.output is not None and args.split_rounds:
        raise ValueError("Use the default per-round output names when exporting multiple rounds.")
    batch_result = run_visibility_exports(
        args.dataset,
        round_ids=round_ids,
        output_path=args.output,
        observer=args.observer,
        tick=args.tick,
        tick_step=args.tick_step,
        skip_freeze_time=not args.include_freeze_time,
        only_visible=args.only_visible,
        summary=args.summary,
        output_kind=args.output_kind,
        tickrate=args.tickrate,
        table_format=args.format,
        profile_visibility=args.profile_visibility,
        dataset=loaded,
        jobs=args.jobs,
        combine_rounds=combine_rounds,
        progress_callback=progress_callback,
    )
    if combine_rounds and batch_result.output_paths:
        for kind, path in batch_result.output_paths.items():
            _visibility_print(f"Visibility {kind} table written to: {path}")
    else:
        for round_result in batch_result.round_results:
            for kind, path in round_result.output_paths.items():
                _visibility_print(f"Visibility {kind} table written to: {path}")
            if round_result.profile is not None:
                _visibility_print(
                    round_result.profile.render_summary(
                        dataset=str(args.dataset),
                        round_id=round_result.round_id,
                        output_path=str(round_result.output_path),
                    )
                )
            if args.profile_los_overlap:
                overlap = profile_los_overlap(
                    args.dataset,
                    round_id=round_result.round_id,
                    observer=args.observer,
                    tick=args.tick,
                    tick_step=args.tick_step,
                    skip_freeze_time=not args.include_freeze_time,
                    only_visible=args.only_visible,
                    tickrate=args.tickrate,
                    dataset=loaded,
                )
                _visibility_print(overlap.render_summary(dataset=str(args.dataset), round_id=round_result.round_id))
    if batch_result.aggregate_profile is not None and (len(round_ids) > 1 or args.jobs > 1):
        _visibility_print(
            batch_result.aggregate_profile.render_summary(
                dataset=str(args.dataset),
                round_id=0,
                output_path=f"{len(round_ids)} round exports",
            ).replace("Round: 0", "Round: all")
        )
    return 0


def _should_fast_exit(argv: list[str], *, argv_was_provided: bool) -> bool:
    return (not argv_was_provided) and bool(argv) and argv[0] == "visibility"


def main(argv: list[str] | None = None) -> int:
    argv_was_provided = argv is not None
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if argv and argv[0] == "catalog":
            parser = build_catalog_parser()
            args = parser.parse_args(argv[1:])
            exit_code = int(handle_catalog(args))
        elif argv and argv[0] == "assets":
            parser = build_assets_parser()
            args = parser.parse_args(argv[1:])
            exit_code = int(handle_assets(args))
        elif argv and argv[0] == "visibility":
            parser = build_visibility_parser()
            args = parser.parse_args(argv[1:])
            exit_code = int(handle_visibility(args))
        else:
            parser = build_playback_parser()
            args = parser.parse_args(argv)
            exit_code = int(handle_playback(args))
    except AssetError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    # Awpy's visibility checker can make interpreter teardown extremely slow on
    # Windows after the export has already completed. For direct CLI use,
    # bypass normal shutdown once we've flushed the result to the terminal.
    if _should_fast_exit(argv, argv_was_provided=argv_was_provided):
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
