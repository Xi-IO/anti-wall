from __future__ import annotations

import unittest

import pandas as pd

from wall.domain.bomb import BombTimeline
from wall.domain.player import RoundPlayers


def _empty_event_table() -> pd.DataFrame:
    return pd.DataFrame()


class BombTimelineTests(unittest.TestCase):
    def test_render_state_exposes_planted_bomb_fields(self) -> None:
        round_ticks = pd.DataFrame(
            [
                {"tick": 100, "name": "p1", "steamid": "s1", "X": 10.0, "Y": 20.0, "Z": 0.0, "yaw": 0.0, "pitch": 0.0, "team_num": 2, "health": 100, "ducking": 0, "is_airborne": 0, "velocity_X": 0.0, "velocity_Y": 0.0, "velocity_Z": 0.0},
                {"tick": 101, "name": "p1", "steamid": "s1", "X": 10.0, "Y": 20.0, "Z": 0.0, "yaw": 0.0, "pitch": 0.0, "team_num": 2, "health": 100, "ducking": 0, "is_airborne": 0, "velocity_X": 0.0, "velocity_Y": 0.0, "velocity_Z": 0.0},
            ]
        )
        round_players = RoundPlayers.from_round_ticks(round_ticks)
        bomb_plants = pd.DataFrame([{"tick": 100, "user_X": 10.0, "user_Y": 20.0, "user_name": "p1"}])
        timeline = BombTimeline(
            round_bomb_pickups=_empty_event_table(),
            round_bomb_drops=_empty_event_table(),
            round_bomb_begin_plants=_empty_event_table(),
            round_bomb_plants=bomb_plants,
            round_bomb_defuses=_empty_event_table(),
            round_bomb_begin_defuses=_empty_event_table(),
            round_bomb_abort_defuses=_empty_event_table(),
            round_bomb_explodes=_empty_event_table(),
            frame_ticks=[100, 101],
            tickrate=64.0,
            round_players=round_players,
        )

        render_state = timeline.render_state_at(101, planted_total_ticks=2560, abort_shake_ticks=20)

        self.assertEqual(render_state.icon_state, "planted")
        self.assertEqual(render_state.world_position, (10.0, 20.0))
        self.assertIsNone(render_state.carrier)
        self.assertIsNotNone(render_state.planted_timer_progress)


if __name__ == "__main__":
    unittest.main()
