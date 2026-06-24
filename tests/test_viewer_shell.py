from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
import unittest
from unittest.mock import patch

from wall.visibility.dataset import MatchDataset
from wall.viewer.shell import PygameRoundViewer
from wall.viewer.loading import ViewerLoadState


class FakeScreen:
    def __init__(self, size: tuple[int, int]) -> None:
        self.width, self.height = size

    def get_size(self) -> tuple[int, int]:
        return self.width, self.height

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def fill(self, color) -> None:
        return None

    def blit(self, surface, rect) -> None:
        return None


class FakeRenderedSurface:
    def get_rect(self, *, center: tuple[int, int]):
        return center


class FakeFont:
    def render(self, text: str, antialias: bool, color) -> FakeRenderedSurface:
        _ = text, antialias, color
        return FakeRenderedSurface()


class FakeClock:
    def tick(self, fps: int) -> int:
        _ = fps
        return 16


class FakeLoadedData:
    def __init__(self) -> None:
        self.map_name = None
        self.round_ids = [3, 4]

    def build_demo_hud_numbers(self) -> dict[str, int]:
        return {"player": 1}

    def build_round_data(self, round_id: int, *, tickrate: float):
        _ = round_id, tickrate
        raise AssertionError("build_round_data should not be used in startup state tests")


class FakeRuntime:
    def __init__(
        self,
        *,
        loaded_data,
        initial_round_id: int | None,
        frame_step: int,
        tickrate: float,
        max_cached_frames: int,
        renderer_factory,
    ) -> None:
        _ = loaded_data, frame_step, tickrate, max_cached_frames, renderer_factory
        self.round_ids = [3, 4]
        self.selected_round_id = 4 if initial_round_id == 4 else 3
        self.round_cache = None
        self.select_round_calls: list[tuple[int, bool]] = []
        self.ensure_cached_calls: list[int] = []

    def select_round(self, round_id: int, *, show_sound_effects: bool):
        self.selected_round_id = round_id
        self.select_round_calls.append((round_id, show_sound_effects))
        self.round_cache = type(
            "RoundCache",
            (),
            {
                "frame_ticks": [100, 108],
                "cache": OrderedDict(),
                "renderer": type(
                    "Renderer",
                    (),
                    {
                        "round_start_tick": 100,
                        "show_sound_effects": show_sound_effects,
                        "player_numbers": {"player": 1},
                        "players": ["player"],
                    },
                )(),
            },
        )()
        return self.round_cache

    def ensure_cached(self, frame_index: int) -> None:
        self.ensure_cached_calls.append(frame_index)
        if self.round_cache is not None:
            self.round_cache.cache[frame_index] = "frame"


class FakeLoader:
    def __init__(self, states: list[ViewerLoadState]) -> None:
        self.states = list(states)
        self.state = states[0] if states else ViewerLoadState(status="not_started")
        self.start_calls = 0
        self.poll_calls = 0
        self.shutdown_calls = 0

    def start(self):
        self.start_calls += 1
        if self.states:
            self.state = self.states[0]
        return self.state

    def poll(self):
        self.poll_calls += 1
        if self.states:
            self.state = self.states.pop(0)
        return self.state

    def shutdown(self) -> None:
        self.shutdown_calls += 1


class ViewerShellTests(unittest.TestCase):
    def _build_viewer(self) -> PygameRoundViewer:
        screen = FakeScreen((1520, 960))
        with (
            patch("wall.viewer.shell.pygame.init"),
            patch("wall.viewer.shell.pygame.font.init"),
            patch("wall.viewer.shell.pygame.display.set_mode", return_value=screen),
            patch("wall.viewer.shell.pygame.display.set_caption"),
            patch("wall.viewer.shell.pygame.time.Clock", return_value=FakeClock()),
            patch("wall.viewer.shell.pygame.font.SysFont", return_value=FakeFont()),
            patch.object(PygameRoundViewer, "_load_viewer_sound_toggle_icons", return_value={}),
        ):
            return PygameRoundViewer(
                data_dir=Path("F:/wall/outputs/example"),
                initial_round_id=4,
                map_width=1200,
                map_height=900,
                fps=60,
                frame_step=1,
                tickrate=64.0,
            )

    def test_init_does_not_load_dataset(self) -> None:
        with patch("wall.viewer.shell.DatasetIndex.from_data_dir") as from_data_dir, patch.object(
            MatchDataset, "from_data_dir"
        ) as match_dataset_from_data_dir:
            viewer = self._build_viewer()

        from_data_dir.assert_not_called()
        match_dataset_from_data_dir.assert_not_called()
        self.assertEqual(viewer.startup_stage, "waiting_for_dataset")
        self.assertIsNone(viewer.loaded_data)
        self.assertIsNone(viewer.runtime)
        self.assertEqual(viewer.load_state.status, "not_started")

    def test_loading_completion_installs_dataset_and_selects_initial_round(self) -> None:
        viewer = self._build_viewer()
        fake_loaded = FakeLoadedData()
        viewer.dataset_loader = FakeLoader(
            [
                ViewerLoadState(status="loading"),
                ViewerLoadState(status="complete", value=fake_loaded),
            ]
        )
        viewer.load_state = viewer.dataset_loader.state
        with patch("wall.viewer.shell.ViewerRoundRuntime", FakeRuntime):
            viewer._advance_startup()
            self.assertEqual(viewer.load_state.status, "loading")
            self.assertIsNone(viewer.loaded_data)
            self.assertEqual(viewer.startup_stage, "waiting_for_dataset")

            viewer._advance_startup()
            self.assertIs(viewer.loaded_data, fake_loaded)
            self.assertIsNotNone(viewer.runtime)
            self.assertEqual(viewer.startup_stage, "select_round")

            runtime = viewer.runtime
            assert runtime is not None
            viewer._advance_startup()
            self.assertEqual(runtime.select_round_calls, [(4, True)])
            self.assertEqual(viewer.startup_stage, "cache_first_frame")

            viewer._advance_startup()
            self.assertEqual(runtime.ensure_cached_calls, [0])
            self.assertEqual(viewer.startup_stage, "ready")

    def test_resize_path_defers_round_rebuild(self) -> None:
        viewer = self._build_viewer()
        viewer.startup_stage = "ready"
        runtime = FakeRuntime(
            loaded_data=FakeLoadedData(),
            initial_round_id=4,
            frame_step=1,
            tickrate=64.0,
            max_cached_frames=240,
            renderer_factory=lambda round_id: round_id,
        )
        runtime.select_round(4, show_sound_effects=True)
        viewer.runtime = runtime
        viewer.playback.reset(viewer.round_cache.frame_ticks)

        viewer._apply_window_size(1400, 1000)
        viewer._flush_pending_window_size()

        self.assertEqual(runtime.select_round_calls, [(4, True)])
        self.assertTrue(viewer.resize_rebuild_pending)

    def test_loading_failure_is_recorded(self) -> None:
        viewer = self._build_viewer()
        viewer.dataset_loader = FakeLoader(
            [ViewerLoadState(status="failed", error=RuntimeError("boom"))]
        )
        viewer.load_state = viewer.dataset_loader.state

        viewer._advance_startup()

        self.assertEqual(viewer.startup_stage, "failed")
        self.assertEqual(viewer.load_state.status, "failed")
        self.assertIn("RuntimeError", viewer.loading_message)


if __name__ == "__main__":
    unittest.main()
