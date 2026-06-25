from __future__ import annotations

import argparse
from pathlib import Path

from wall.output import print_milestone, progress_enabled
from wall.viewer.shell import PygameRoundViewer


def _render_progress_line(label: str, current: int, total: int, *, detail: str | None = None) -> str:
    resolved_total = max(1, int(total))
    resolved_current = max(0, min(int(current), resolved_total))
    width = 20
    filled = int(round((resolved_current / resolved_total) * width))
    bar = "#" * filled + "-" * (width - filled)
    suffix = f"  {detail}" if detail else ""
    return f"{label:<10} [{bar}] {resolved_current}/{resolved_total}{suffix}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pygame viewer for inferred CS rounds.")
    parser.add_argument("data_dir", type=Path, help="Directory containing parsed output tables")
    parser.add_argument("--round", dest="round_id", type=int, help="Initial round to select")
    parser.add_argument("--map-width", type=int, default=1200, help="Map viewport width")
    parser.add_argument("--map-height", type=int, default=900, help="Map viewport height")
    parser.add_argument("--fps", type=int, default=60, help="Target viewer refresh rate")
    parser.add_argument("--frame-step", type=int, default=1, help="Animate every Nth tick")
    parser.add_argument("--tickrate", type=float, default=64.0, help="Playback tickrate for real-time speed sync")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    print_milestone(f"[viewer] Loading dataset index: {args.data_dir}")
    if progress_enabled():
        print(_render_progress_line("viewer", 1, 2, detail="Loading dataset"), flush=True)
    viewer = PygameRoundViewer(
        data_dir=args.data_dir,
        initial_round_id=args.round_id,
        map_width=args.map_width,
        map_height=args.map_height,
        fps=args.fps,
        frame_step=args.frame_step,
        tickrate=args.tickrate,
    )
    print_milestone("[viewer] Dataset loaded, opening pygame window")
    if progress_enabled():
        print(_render_progress_line("viewer", 2, 2, detail="Opening window"), flush=True)
    viewer.run()


if __name__ == "__main__":
    main()
