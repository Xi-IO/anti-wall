from __future__ import annotations

import argparse
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from PIL import ImageTk

try:
    from scripts.round_render import RoundRenderer, get_round_data, load_round_data
except ModuleNotFoundError:
    from round_render import RoundRenderer, get_round_data, load_round_data


class RoundViewerApp:
    def __init__(self, root: tk.Tk, data_dir: Path, allowed_round_ids: list[int] | None = None) -> None:
        self.root = root
        self.data_dir = data_dir
        self.root.title("wall round viewer")

        self.ticks, self.deaths, self.inferred_rounds, self.metadata = load_round_data(data_dir)
        all_round_ids = sorted(self.inferred_rounds["inferred_round_id"].astype(int).tolist())
        if allowed_round_ids is None:
            self.round_ids = all_round_ids
        else:
            allowed = set(allowed_round_ids)
            self.round_ids = [round_id for round_id in all_round_ids if round_id in allowed]
        if not self.round_ids:
            raise ValueError("No inferred rounds found in inferred_rounds.csv")

        self.width = 900
        self.height = 900
        self.frame_step = tk.IntVar(value=16)
        self.trail = tk.IntVar(value=24)
        self.facing_radius = tk.DoubleVar(value=70.0)
        self.facing_fov = tk.DoubleVar(value=90.0)
        self.round_var = tk.IntVar(value=self.round_ids[0])
        self.playing = False
        self.after_id: str | None = None
        self.current_renderer: RoundRenderer | None = None
        self.current_frame_ticks: list[int] = []
        self.current_frame_index = 0
        self.photo: ImageTk.PhotoImage | None = None
        self.map_name = self.metadata.get("derived", {}).get("map_name")
        self._updating_scale = False

        self._build_layout()
        self.load_round(self.round_ids[0])

    def _build_layout(self) -> None:
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        controls = ttk.Frame(self.root, padding=10)
        controls.grid(row=0, column=0, sticky="ns")

        viewer = ttk.Frame(self.root, padding=10)
        viewer.grid(row=0, column=1, sticky="nsew")
        viewer.columnconfigure(0, weight=1)
        viewer.rowconfigure(1, weight=1)

        ttk.Label(controls, text="Data dir").grid(row=0, column=0, sticky="w")
        ttk.Label(controls, text=str(self.data_dir)).grid(row=1, column=0, sticky="w")

        ttk.Label(controls, text=f"Map: {self.map_name or 'unknown'}").grid(row=2, column=0, sticky="w", pady=(6, 0))

        ttk.Label(controls, text="Round").grid(row=3, column=0, sticky="w", pady=(10, 0))
        round_menu = ttk.Combobox(
            controls,
            values=self.round_ids,
            textvariable=self.round_var,
            state="readonly",
            width=10,
        )
        round_menu.grid(row=4, column=0, sticky="ew")
        round_menu.bind("<<ComboboxSelected>>", lambda _event: self.on_round_change())

        ttk.Label(controls, text="Frame step").grid(row=5, column=0, sticky="w", pady=(10, 0))
        ttk.Spinbox(controls, from_=1, to=128, textvariable=self.frame_step, width=10).grid(row=6, column=0, sticky="ew")

        ttk.Label(controls, text="Trail").grid(row=7, column=0, sticky="w", pady=(10, 0))
        ttk.Spinbox(controls, from_=1, to=128, textvariable=self.trail, width=10).grid(row=8, column=0, sticky="ew")

        ttk.Label(controls, text="Facing radius").grid(row=9, column=0, sticky="w", pady=(10, 0))
        ttk.Spinbox(controls, from_=10, to=300, increment=5, textvariable=self.facing_radius, width=10).grid(row=10, column=0, sticky="ew")

        ttk.Label(controls, text="Facing FOV").grid(row=11, column=0, sticky="w", pady=(10, 0))
        ttk.Spinbox(controls, from_=10, to=180, increment=5, textvariable=self.facing_fov, width=10).grid(row=12, column=0, sticky="ew")

        ttk.Button(controls, text="Reload round", command=self.reload_current_round).grid(row=13, column=0, sticky="ew", pady=(12, 0))
        self.play_button = ttk.Button(controls, text="Play", command=self.toggle_playback)
        self.play_button.grid(row=14, column=0, sticky="ew", pady=(6, 0))

        self.info_label = ttk.Label(controls, text="", justify="left")
        self.info_label.grid(row=15, column=0, sticky="w", pady=(12, 0))

        ttk.Label(viewer, text="Frame").grid(row=0, column=0, sticky="w")
        self.frame_scale = ttk.Scale(viewer, from_=0, to=1, orient="horizontal", command=self.on_scale_move)
        self.frame_scale.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        self.image_label = ttk.Label(viewer)
        self.image_label.grid(row=1, column=0, sticky="nsew")

    def on_round_change(self) -> None:
        self.stop_playback()
        self.load_round(int(self.round_var.get()))

    def reload_current_round(self) -> None:
        self.stop_playback()
        self.load_round(int(self.round_var.get()))

    def load_round(self, round_id: int) -> None:
        round_data = get_round_data(self.ticks, self.deaths, round_id)
        self.current_renderer = RoundRenderer(
            round_ticks=round_data.round_ticks,
            round_deaths=round_data.round_deaths,
            width=self.width,
            height=self.height,
            trail=int(self.trail.get()),
            facing_radius=float(self.facing_radius.get()),
            facing_fov=float(self.facing_fov.get()),
            map_name=self.map_name,
        )
        frame_ticks = self.current_renderer.frame_ticks[:: max(1, int(self.frame_step.get()))]
        last_tick = int(self.current_renderer.frame_ticks[-1])
        if frame_ticks[-1] != last_tick:
            frame_ticks = list(frame_ticks) + [last_tick]
        self.current_frame_ticks = [int(tick) for tick in frame_ticks]
        self.current_frame_index = 0
        self.frame_scale.configure(from_=0, to=max(0, len(self.current_frame_ticks) - 1))
        self._set_scale_value(0)
        self._update_info()
        self.show_frame(0)

    def _update_info(self) -> None:
        if not self.current_renderer:
            self.info_label.configure(text="")
            return
        start_tick = int(self.current_renderer.frame_ticks[0])
        end_tick = int(self.current_renderer.frame_ticks[-1])
        players = len(self.current_renderer.players)
        text = f"round={self.current_renderer.round_id}\nplayers={players}\nticks={start_tick}..{end_tick}"
        self.info_label.configure(text=text)

    def show_frame(self, frame_index: int) -> None:
        if not self.current_renderer or not self.current_frame_ticks:
            return
        frame_index = max(0, min(frame_index, len(self.current_frame_ticks) - 1))
        self.current_frame_index = frame_index
        frame_tick = self.current_frame_ticks[frame_index]
        image = self.current_renderer.render_frame(frame_tick)
        self.photo = ImageTk.PhotoImage(image=image)
        self.image_label.configure(image=self.photo)
        self._set_scale_value(frame_index)

    def on_scale_move(self, value: str) -> None:
        if self.playing or self._updating_scale:
            return
        self.show_frame(int(float(value)))

    def _set_scale_value(self, value: int) -> None:
        self._updating_scale = True
        try:
            self.frame_scale.set(value)
        finally:
            self._updating_scale = False

    def toggle_playback(self) -> None:
        if self.playing:
            self.stop_playback()
        else:
            self.playing = True
            self.play_button.configure(text="Pause")
            self._schedule_next_frame()

    def stop_playback(self) -> None:
        self.playing = False
        self.play_button.configure(text="Play")
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)
            self.after_id = None

    def _schedule_next_frame(self) -> None:
        if not self.playing:
            return
        self.show_frame(self.current_frame_index)
        next_index = self.current_frame_index + 1
        if next_index >= len(self.current_frame_ticks):
            self.stop_playback()
            return
        self.current_frame_index = next_index
        self.after_id = self.root.after(80, self._schedule_next_frame)


def main() -> None:
    parser = argparse.ArgumentParser(description="Local GUI viewer for inferred CS rounds.")
    parser.add_argument("data_dir", type=Path, help="Directory containing ticks.csv, player_death.csv, inferred_rounds.csv")
    parser.add_argument(
        "--round",
        dest="round_spec",
        type=str,
        help="Round selection like '2', '1-4', or '1,3,5-7'. Omit to show all inferred rounds.",
    )
    args = parser.parse_args()

    root = tk.Tk()
    allowed_round_ids = parse_round_ids(args.round_spec) if args.round_spec else None
    app = RoundViewerApp(root, args.data_dir, allowed_round_ids=allowed_round_ids)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.stop_playback(), root.destroy()))
    root.mainloop()


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
