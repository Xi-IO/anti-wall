from __future__ import annotations

import argparse
from pathlib import Path

try:
    from scripts.round_render import RoundRenderer, get_round_data, load_round_data
except ModuleNotFoundError:
    from round_render import RoundRenderer, get_round_data, load_round_data


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a per-round player animation from parsed CSV files.")
    parser.add_argument("data_dir", type=Path, help="Directory containing ticks.csv and player_death.csv")
    parser.add_argument(
        "--round",
        dest="round_spec",
        type=str,
        help="Round selection like '2', '1-4', or '1,3,5-7'. Omit to render all inferred rounds.",
    )
    parser.add_argument("--frame-step", type=int, default=16, help="Animate every Nth tick")
    parser.add_argument("--trail", type=int, default=24, help="Number of past positions to keep as a trail")
    parser.add_argument("--facing-radius", type=float, default=70.0, help="Radius of the facing wedge in world units")
    parser.add_argument("--facing-fov", type=float, default=90.0, help="Angular width of the facing wedge")
    parser.add_argument("--width", type=int, default=1000, help="Output image width")
    parser.add_argument("--height", type=int, default=1000, help="Output image height")
    parser.add_argument(
        "--format",
        choices=["gif", "png"],
        default="gif",
        help="Output format. Use png for a single-frame snapshot at the last tick.",
    )
    parser.add_argument("--duration", type=int, default=80, help="GIF frame duration in milliseconds")
    parser.add_argument("--output", type=Path, default=None, help="Output file path")
    args = parser.parse_args()

    ticks, deaths, _, metadata = load_round_data(args.data_dir)
    map_name = metadata.get("derived", {}).get("map_name")
    available_round_ids = sorted(ticks["inferred_round_id"].dropna().astype(int).unique().tolist())
    round_ids = parse_round_ids(args.round_spec) if args.round_spec else available_round_ids
    round_ids = [int(round_id) for round_id in round_ids]

    for round_id in round_ids:
        round_data = get_round_data(ticks, deaths, round_id)
        output_path = default_output_path(args.data_dir, round_id, args.format)
        if args.output and len(round_ids) == 1:
            output_path = args.output
        output_path.parent.mkdir(parents=True, exist_ok=True)

        renderer = RoundRenderer(
            round_ticks=round_data.round_ticks,
            round_deaths=round_data.round_deaths,
            width=args.width,
            height=args.height,
            trail=args.trail,
            facing_radius=args.facing_radius,
            facing_fov=args.facing_fov,
            map_name=map_name,
        )

        if args.format == "png":
            image = renderer.render_frame(int(round_data.round_ticks["tick"].max()))
            image.save(output_path)
        else:
            frame_ticks = round_data.round_ticks["tick"].sort_values().unique()[:: args.frame_step]
            if frame_ticks[-1] != round_data.round_ticks["tick"].max():
                frame_ticks = list(frame_ticks) + [int(round_data.round_ticks["tick"].max())]
            frames = [renderer.render_frame(int(frame_tick)) for frame_tick in frame_ticks]
            frames[0].save(
                output_path,
                save_all=True,
                append_images=frames[1:],
                optimize=False,
                duration=args.duration,
                loop=0,
            )

        print(f"Saved: {output_path}")


def require_column(df, column: str, file_label: str) -> None:
    if column not in df.columns:
        raise ValueError(f"{file_label} is missing required column: {column}")


def default_output_path(data_dir: Path, round_id: int, output_format: str) -> Path:
    suffix = ".gif" if output_format == "gif" else ".png"
    return data_dir / f"round_{round_id:02d}{suffix}"


def parse_round_ids(round_spec: str) -> list[int]:
    round_ids: list[int] = []
    for part in round_spec.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if end < start:
                raise ValueError(f"Invalid round range: {token}")
            round_ids.extend(range(start, end + 1))
        else:
            round_ids.append(int(token))
    if not round_ids:
        raise ValueError("No rounds parsed from --round")
    return sorted(set(round_ids))


if __name__ == "__main__":
    main()
