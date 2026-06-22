from __future__ import annotations

import argparse
from pathlib import Path

from wall.viewer.shell import PygameRoundViewer


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

    viewer = PygameRoundViewer(
        data_dir=args.data_dir,
        initial_round_id=args.round_id,
        map_width=args.map_width,
        map_height=args.map_height,
        fps=args.fps,
        frame_step=args.frame_step,
        tickrate=args.tickrate,
    )
    viewer.run()


if __name__ == "__main__":
    main()
