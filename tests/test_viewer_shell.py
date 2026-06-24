from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
import unittest
from unittest.mock import patch

from wall.visibility.dataset import MatchDataset
from wall.viewer.info_events import InfoEvent, VISIBILITY_EVENT_KIND
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
                        "round_players": type(
                            "RoundPlayers",
                            (),
                            {
                                "ordered_steamids": ["player"],
                                "get_by_steamid": lambda self, steamid: type(
                                    "Timeline",
                                    (),
                                    {
                                        "display_name": "player",
                                        "team_at": lambda self, tick: 2,
                                    },
                                )()
                                if steamid == "player"
                                else None,
                            },
                        )(),
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
        fake_events = [
            InfoEvent(4, 100, 0.0, VISIBILITY_EVENT_KIND, "A", "X", "0.00s  A spotted X"),
        ]
        with (
            patch("wall.viewer.shell.ViewerRoundRuntime", FakeRuntime),
            patch("wall.viewer.shell.load_info_events_for_dataset", return_value=fake_events) as load_info_events,
        ):
            viewer._advance_startup()
            self.assertEqual(viewer.load_state.status, "loading")
            self.assertIsNone(viewer.loaded_data)
            self.assertEqual(viewer.startup_stage, "waiting_for_dataset")

            viewer._advance_startup()
            self.assertIs(viewer.loaded_data, fake_loaded)
            self.assertEqual(viewer.visibility_events, fake_events)
            self.assertIsNotNone(viewer.runtime)
            self.assertEqual(viewer.startup_stage, "select_round")
            load_info_events.assert_called_once_with(fake_loaded, tickrate=64.0)

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

    def test_mousewheel_scrolls_info_panel_only_when_hovered(self) -> None:
        viewer = self._build_viewer()
        viewer.button_rects = {
            "info_panel_viewport": type("Rect", (), {"collidepoint": lambda self, pos: pos == (10, 10)})(),
            "info_scroll_track": type("Rect", (), {"width": 0, "collidepoint": lambda self, pos: False})(),
            "info_scroll_thumb": type("Rect", (), {"width": 0, "collidepoint": lambda self, pos: False})(),
        }
        calls: list[int] = []

        with patch.object(viewer, "_scroll_info_panel", side_effect=lambda delta: calls.append(delta)):
            viewer._handle_mousewheel(1, (10, 10))
            viewer._handle_mousewheel(1, (50, 50))

        self.assertEqual(calls, [1])

    def test_sidebar_event_lines_show_placeholder_when_no_visibility_artifact(self) -> None:
        viewer = self._build_viewer()
        viewer.visibility_events = []
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

        lines = viewer._sidebar_event_lines(100)

        self.assertEqual(lines, ["No visibility events"])

    def test_sidebar_event_lines_show_all_when_no_players_selected(self) -> None:
        viewer = self._build_viewer()
        viewer.visibility_events = [
            InfoEvent(4, 100, 0.0, VISIBILITY_EVENT_KIND, "A", "X", "0.00s  A spotted X"),
            InfoEvent(4, 120, 2.0, VISIBILITY_EVENT_KIND, "B", "A", "2.00s  B spotted A"),
            InfoEvent(4, 140, 4.0, VISIBILITY_EVENT_KIND, "C", "Z", "4.00s  C spotted Z"),
        ]
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

        lines = viewer._sidebar_event_lines(130)

        self.assertEqual(lines, ["0.00s  A spotted X", "2.00s  B spotted A"])

    def test_sidebar_event_lines_filter_by_selected_observer_or_target(self) -> None:
        viewer = self._build_viewer()
        viewer.visibility_events = [
            InfoEvent(4, 100, 0.0, VISIBILITY_EVENT_KIND, "AIKUUUUUU", "X", "0.00s  AIKUUUUUU spotted X", observer_key="sA", target_key="sX"),
            InfoEvent(4, 120, 2.0, VISIBILITY_EVENT_KIND, "Y", "AIKUUUUUU", "2.00s  Y spotted AIKUUUUUU", observer_key="sY", target_key="sA"),
            InfoEvent(4, 130, 3.0, VISIBILITY_EVENT_KIND, "B", "Z", "3.00s  B spotted Z", observer_key="sB", target_key="sZ"),
        ]
        viewer.selected_players = {"sA"}
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

        lines = viewer._sidebar_event_lines(140)

        self.assertEqual(lines, ["0.00s  AIKUUUUUU spotted X", "2.00s  Y spotted AIKUUUUUU"])

    def test_sidebar_event_lines_filter_by_selected_steamid_when_event_keys_fallback_to_names(self) -> None:
        viewer = self._build_viewer()
        viewer.visibility_events = [
            InfoEvent(
                4,
                100,
                0.0,
                VISIBILITY_EVENT_KIND,
                "RealDevice",
                "Potato pope",
                "0.00s  RealDevice spotted Potato pope",
                observer_key="RealDevice",
                target_key="Potato pope",
            ),
            InfoEvent(
                4,
                120,
                2.0,
                VISIBILITY_EVENT_KIND,
                "Potato Khan Jr",
                "RealDevice",
                "2.00s  Potato Khan Jr spotted RealDevice",
                observer_key="Potato Khan Jr",
                target_key="RealDevice",
            ),
            InfoEvent(
                4,
                130,
                3.0,
                VISIBILITY_EVENT_KIND,
                "Other",
                "Else",
                "3.00s  Other spotted Else",
                observer_key="Other",
                target_key="Else",
            ),
        ]
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
        viewer._sidebar_player_keys = lambda: ["76561198000000008"]  # type: ignore[method-assign]
        viewer._player_display_name = lambda key: "RealDevice"  # type: ignore[method-assign]
        viewer._team_num_at_tick = lambda key, tick: 3  # type: ignore[method-assign]
        viewer.selected_players = {"76561198000000008"}

        lines = viewer._sidebar_event_lines(140)

        self.assertEqual(
            lines,
            ["0.00s  RealDevice spotted Potato pope", "2.00s  Potato Khan Jr spotted RealDevice"],
        )

    def test_sidebar_event_lines_filter_by_selected_steamid_when_event_keys_are_steamids(self) -> None:
        viewer = self._build_viewer()
        viewer.visibility_events = [
            InfoEvent(
                4,
                100,
                0.0,
                VISIBILITY_EVENT_KIND,
                "RealDevice",
                "Potato pope",
                "0.00s  RealDevice spotted Potato pope",
                observer_key="76561198000000008",
                target_key="76561198000000004",
            ),
            InfoEvent(
                4,
                120,
                2.0,
                VISIBILITY_EVENT_KIND,
                "Potato Khan Jr",
                "RealDevice",
                "2.00s  Potato Khan Jr spotted RealDevice",
                observer_key="76561198000000003",
                target_key="76561198000000008",
            ),
        ]
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
        viewer._sidebar_player_keys = lambda: ["76561198000000008"]  # type: ignore[method-assign]
        viewer._player_display_name = lambda key: "RealDevice"  # type: ignore[method-assign]
        viewer._team_num_at_tick = lambda key, tick: 3  # type: ignore[method-assign]
        viewer.selected_players = {"76561198000000008"}

        lines = viewer._sidebar_event_lines(140)

        self.assertEqual(
            lines,
            ["0.00s  RealDevice spotted Potato pope", "2.00s  Potato Khan Jr spotted RealDevice"],
        )

    def test_player_click_toggles_selection_without_reloading_visibility(self) -> None:
        viewer = self._build_viewer()
        viewer.player_rects = {"player": type("Rect", (), {"collidepoint": lambda self, pos: pos == (10, 10)})()}
        viewer.button_rects = {}
        viewer.round_item_rects = {}
        viewer.speed_rects = {}

        with patch("wall.viewer.shell.load_info_events_for_dataset") as load_info_events:
            viewer._handle_mouse_down((10, 10))
            self.assertEqual(viewer.selected_players, {"player"})
            viewer._handle_mouse_down((10, 10))
            self.assertEqual(viewer.selected_players, set())

        load_info_events.assert_not_called()

    def test_visibility_feed_title_reflects_selection(self) -> None:
        viewer = self._build_viewer()
        self.assertEqual(viewer._visibility_feed_title(), "Visibility Feed")

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

        viewer.selected_players = {"player"}
        self.assertEqual(viewer._visibility_feed_title(), "Visibility Feed · player")

        viewer.selected_players = {"AIKUUUUUU", "Eggo"}
        self.assertEqual(viewer._visibility_feed_title(), "Visibility Feed · 2 players")

    def test_visibility_feed_empty_text_reflects_selection(self) -> None:
        viewer = self._build_viewer()
        self.assertEqual(viewer._visibility_feed_empty_text(), "No visibility events")

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

        viewer.selected_players = {"player"}
        self.assertEqual(viewer._visibility_feed_empty_text(), "No visibility events for player")

        viewer.selected_players = {"AIKUUUUUU", "Eggo"}
        self.assertEqual(viewer._visibility_feed_empty_text(), "No visibility events for selected players")

    def test_sidebar_event_lines_use_contextual_empty_state_for_selected_player(self) -> None:
        viewer = self._build_viewer()
        viewer.visibility_events = [
            InfoEvent(4, 100, 0.0, VISIBILITY_EVENT_KIND, "B", "Z", "0.00s  B spotted Z", observer_key="sB", target_key="sZ"),
        ]
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
        viewer.selected_players = {"player"}
        viewer.playback.reset(viewer.round_cache.frame_ticks)

        lines = viewer._sidebar_event_lines(120)

        self.assertEqual(lines, ["No visibility events for player"])

    def test_sidebar_player_entries_sort_by_display_number_not_steamid(self) -> None:
        viewer = self._build_viewer()
        viewer.runtime = type(
            "Runtime",
            (),
            {
                "round_cache": type(
                    "RoundCache",
                    (),
                    {
                        "frame_ticks": [100],
                        "renderer": type(
                            "Renderer",
                            (),
                            {
                                "player_numbers": {"T1": 1, "T2": 2, "CT6": 6, "CT7": 7},
                            },
                        )(),
                    },
                )(),
            },
        )()
        viewer._sidebar_player_keys = lambda: ["steam_ct7", "steam_t1", "steam_ct6", "steam_t2"]  # type: ignore[method-assign]
        viewer._player_display_name = lambda key: {  # type: ignore[method-assign]
            "steam_ct7": "CT7",
            "steam_t1": "T1",
            "steam_ct6": "CT6",
            "steam_t2": "T2",
        }[key]
        viewer._team_num_at_tick = lambda key, tick: 3 if "ct" in key else 2  # type: ignore[method-assign]

        entries = viewer._sidebar_player_entries(100)

        self.assertEqual([entry.player_id for entry in entries], ["steam_t1", "steam_t2", "steam_ct6", "steam_ct7"])
        self.assertEqual([entry.label for entry in entries], ["1. T1", "2. T2", "6. CT6", "7. CT7"])

    def test_sidebar_player_entries_keep_steamid_as_player_id(self) -> None:
        viewer = self._build_viewer()
        viewer.runtime = type(
            "Runtime",
            (),
            {
                "round_cache": type(
                    "RoundCache",
                    (),
                    {
                        "frame_ticks": [100],
                        "renderer": type("Renderer", (), {"player_numbers": {"player": 1}})(),
                    },
                )(),
            },
        )()
        viewer._sidebar_player_keys = lambda: ["76561198000000001"]  # type: ignore[method-assign]
        viewer._player_display_name = lambda key: "player"  # type: ignore[method-assign]
        viewer._team_num_at_tick = lambda key, tick: 2  # type: ignore[method-assign]

        entries = viewer._sidebar_player_entries(100)

        self.assertEqual(entries[0].player_id, "76561198000000001")
        self.assertEqual(entries[0].display_name, "player")
        self.assertEqual(entries[0].label, "1. player")
        self.assertEqual(entries[0].match_keys, frozenset({"76561198000000001", "player"}))


if __name__ == "__main__":
    unittest.main()
