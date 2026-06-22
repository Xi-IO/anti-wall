from __future__ import annotations

import unittest

from wall.viewer.runtime import ViewerRoundRuntime


class FakeConvertedSurface:
    def __init__(self, value: str) -> None:
        self.value = value

    def convert(self) -> str:
        return f"converted:{self.value}"


class FakeRenderer:
    def __init__(self, round_id: int, frame_ticks: list[int]) -> None:
        self.round_id = round_id
        self.frame_ticks = frame_ticks
        self.round_start_tick = frame_ticks[0]
        self.show_sound_effects = True
        self.player_numbers = {"player": 1}
        self.players = ["player"]
        self.rendered_ticks: list[int] = []

    def render_map_frame(self, frame_tick: int) -> FakeConvertedSurface:
        self.rendered_ticks.append(frame_tick)
        return FakeConvertedSurface(f"round{self.round_id}:{frame_tick}")


class FakeLoadedData:
    def __init__(self, round_ids: list[int]) -> None:
        self.round_ids = round_ids


class ViewerRoundRuntimeTest(unittest.TestCase):
    def test_select_round_applies_frame_step_and_last_tick(self) -> None:
        runtime = ViewerRoundRuntime(
            loaded_data=FakeLoadedData([1, 2]),
            initial_round_id=1,
            frame_step=2,
            tickrate=64.0,
            max_cached_frames=3,
            renderer_factory=lambda round_id: FakeRenderer(round_id, [0, 1, 2, 3, 4]),
        )

        cache = runtime.select_round(1, show_sound_effects=False)

        self.assertEqual(cache.frame_ticks, [0, 2, 4])
        self.assertFalse(cache.renderer.show_sound_effects)

    def test_change_round_updates_selection(self) -> None:
        runtime = ViewerRoundRuntime(
            loaded_data=FakeLoadedData([10, 11, 12]),
            initial_round_id=11,
            frame_step=1,
            tickrate=64.0,
            max_cached_frames=3,
            renderer_factory=lambda round_id: FakeRenderer(round_id, [0, 1]),
        )
        runtime.select_round(11, show_sound_effects=True)

        changed = runtime.change_round(1, show_sound_effects=True)

        self.assertTrue(changed)
        self.assertEqual(runtime.selected_round_id, 12)

    def test_ensure_cached_eviction_is_lru(self) -> None:
        renderer = FakeRenderer(1, [0, 1, 2, 3])
        runtime = ViewerRoundRuntime(
            loaded_data=FakeLoadedData([1]),
            initial_round_id=1,
            frame_step=1,
            tickrate=64.0,
            max_cached_frames=2,
            renderer_factory=lambda round_id: renderer,
        )
        runtime.select_round(1, show_sound_effects=True)

        runtime.ensure_cached(0)
        runtime.ensure_cached(1)
        runtime.ensure_cached(0)
        runtime.ensure_cached(2)

        self.assertEqual(list(runtime.round_cache.cache.keys()), [0, 2])
        self.assertEqual(runtime.round_cache.cache[2], "converted:round1:2")


if __name__ == "__main__":
    unittest.main()
