from __future__ import annotations

import unittest

import pandas as pd

from wall.viewer.session import LoadedViewerData


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame()


class LoadedViewerDataTests(unittest.TestCase):
    def test_build_demo_hud_numbers_assigns_team_slots_then_fallbacks(self) -> None:
        ticks = pd.DataFrame(
            [
                {"tick": 1, "name": "t1", "team_num": 2},
                {"tick": 2, "name": "t2", "team_num": 2},
                {"tick": 3, "name": "ct1", "team_num": 3},
                {"tick": 4, "name": "ct2", "team_num": 3},
                {"tick": 5, "name": "coach", "team_num": 0},
            ]
        )
        loaded = LoadedViewerData(
            ticks=ticks,
            deaths=_empty_df(),
            fires=_empty_df(),
            hurts=_empty_df(),
            hits=_empty_df(),
            footsteps=_empty_df(),
            smoke_detonates=_empty_df(),
            flash_detonates=_empty_df(),
            he_detonates=_empty_df(),
            blinds=_empty_df(),
            bomb_pickups=_empty_df(),
            bomb_drops=_empty_df(),
            bomb_begin_plants=_empty_df(),
            bomb_plants=_empty_df(),
            bomb_defuses=_empty_df(),
            bomb_begin_defuses=_empty_df(),
            bomb_abort_defuses=_empty_df(),
            bomb_explodes=_empty_df(),
            smoke_expires=_empty_df(),
            inferno_starts=_empty_df(),
            grenades=_empty_df(),
            sound_events=_empty_df(),
            inferred_rounds=pd.DataFrame([{"inferred_round_id": 1}]),
            metadata={"derived": {"map_name": "de_test"}},
        )

        player_numbers = loaded.build_demo_hud_numbers()

        self.assertEqual(player_numbers["t1"], 1)
        self.assertEqual(player_numbers["t2"], 2)
        self.assertEqual(player_numbers["ct1"], 6)
        self.assertEqual(player_numbers["ct2"], 7)
        self.assertEqual(player_numbers["coach"], 11)

    def test_round_ids_are_sorted(self) -> None:
        loaded = LoadedViewerData(
            ticks=_empty_df(),
            deaths=_empty_df(),
            fires=_empty_df(),
            hurts=_empty_df(),
            hits=_empty_df(),
            footsteps=_empty_df(),
            smoke_detonates=_empty_df(),
            flash_detonates=_empty_df(),
            he_detonates=_empty_df(),
            blinds=_empty_df(),
            bomb_pickups=_empty_df(),
            bomb_drops=_empty_df(),
            bomb_begin_plants=_empty_df(),
            bomb_plants=_empty_df(),
            bomb_defuses=_empty_df(),
            bomb_begin_defuses=_empty_df(),
            bomb_abort_defuses=_empty_df(),
            bomb_explodes=_empty_df(),
            smoke_expires=_empty_df(),
            inferno_starts=_empty_df(),
            grenades=_empty_df(),
            sound_events=_empty_df(),
            inferred_rounds=pd.DataFrame([{"inferred_round_id": 3}, {"inferred_round_id": 1}, {"inferred_round_id": 2}]),
            metadata={},
        )

        self.assertEqual(loaded.round_ids, [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
