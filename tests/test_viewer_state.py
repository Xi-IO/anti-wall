from __future__ import annotations

import unittest

import pygame

from wall.viewer.state import PlaybackState, RoundDropdownState


class PlaybackStateTests(unittest.TestCase):
    def test_reset_defaults_to_playing(self) -> None:
        state = PlaybackState(playing=False)

        state.reset([100, 110, 120])

        self.assertEqual(state.current_frame_index, 0)
        self.assertEqual(state.current_playback_tick, 100.0)
        self.assertTrue(state.playing)

    def test_seek_to_timeline_position_updates_frame_and_tick(self) -> None:
        state = PlaybackState()
        timeline_rect = pygame.Rect(10, 0, 100, 16)
        frame_index = state.seek_to_timeline_position(60, timeline_rect, [100, 110, 120, 130, 140])

        self.assertEqual(frame_index, 2)
        self.assertEqual(state.current_frame_index, 2)
        self.assertEqual(state.current_playback_tick, 120.0)

    def test_advance_stops_at_last_tick(self) -> None:
        state = PlaybackState(current_frame_index=0, current_playback_tick=100.0, playing=True)

        frame_index = state.advance(1.0, tickrate=64.0, speed=1.0, frame_ticks=[100, 110, 120])

        self.assertEqual(frame_index, 2)
        self.assertEqual(state.current_playback_tick, 120.0)
        self.assertFalse(state.playing)


class RoundDropdownStateTests(unittest.TestCase):
    def test_toggle_aligns_to_selected_round(self) -> None:
        state = RoundDropdownState(visible_count=5)

        state.toggle(selected_index=7, total_count=10)

        self.assertTrue(state.is_open)
        self.assertEqual(state.start_index, 5)

    def test_drag_updates_start_index_from_thumb_position(self) -> None:
        state = RoundDropdownState(visible_count=5)
        state.track_rect = pygame.Rect(0, 20, 20, 100)
        state.thumb_rect = pygame.Rect(3, 20, 14, 40)

        state.update_from_mouse(90, total_count=10)

        self.assertGreater(state.start_index, 0)


if __name__ == "__main__":
    unittest.main()
