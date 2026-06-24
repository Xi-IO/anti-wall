from __future__ import annotations

import unittest

import pandas as pd

from wall.io.demo_parse import build_inferred_rounds_table


class RoundInferenceTests(unittest.TestCase):
    def test_build_inferred_rounds_table_infers_live_start_from_first_movement(self) -> None:
        ticks = pd.DataFrame(
            [
                {"tick": 100, "name": "p1", "X": 0.0, "Y": 0.0, "inferred_round_id": 1},
                {"tick": 100, "name": "p2", "X": 10.0, "Y": 0.0, "inferred_round_id": 1},
                {"tick": 101, "name": "p1", "X": 0.0, "Y": 0.0, "inferred_round_id": 1},
                {"tick": 101, "name": "p2", "X": 10.0, "Y": 0.0, "inferred_round_id": 1},
                {"tick": 102, "name": "p1", "X": 1.0, "Y": 0.0, "inferred_round_id": 1},
                {"tick": 102, "name": "p2", "X": 10.0, "Y": 0.0, "inferred_round_id": 1},
                {"tick": 103, "name": "p1", "X": 2.0, "Y": 0.0, "inferred_round_id": 1},
                {"tick": 103, "name": "p2", "X": 10.0, "Y": 0.0, "inferred_round_id": 1},
            ]
        )
        jump_by_tick = pd.DataFrame(
            [
                {"tick": 100, "n_jump_players": 0, "max_jump": None, "median_jump": None},
            ]
        )

        round_table = build_inferred_rounds_table(ticks, jump_by_tick, [100])

        self.assertEqual(int(round_table.loc[0, "start_tick"]), 100)
        self.assertEqual(int(round_table.loc[0, "freeze_start_tick"]), 100)
        self.assertEqual(int(round_table.loc[0, "live_start_tick"]), 102)
        self.assertEqual(int(round_table.loc[0, "freeze_end_tick"]), 101)
        self.assertEqual(int(round_table.loc[0, "freeze_duration_ticks"]), 2)
        self.assertAlmostEqual(float(round_table.loc[0, "freeze_duration_seconds"]), 2 / 64.0)

    def test_build_inferred_rounds_table_defaults_freeze_duration_to_zero_when_no_one_moves(self) -> None:
        ticks = pd.DataFrame(
            [
                {"tick": 200, "name": "p1", "X": 0.0, "Y": 0.0, "inferred_round_id": 1},
                {"tick": 200, "name": "p2", "X": 10.0, "Y": 0.0, "inferred_round_id": 1},
                {"tick": 201, "name": "p1", "X": 0.0, "Y": 0.0, "inferred_round_id": 1},
                {"tick": 201, "name": "p2", "X": 10.0, "Y": 0.0, "inferred_round_id": 1},
            ]
        )
        jump_by_tick = pd.DataFrame(
            [
                {"tick": 200, "n_jump_players": 0, "max_jump": None, "median_jump": None},
            ]
        )

        round_table = build_inferred_rounds_table(ticks, jump_by_tick, [200])

        self.assertEqual(int(round_table.loc[0, "freeze_start_tick"]), 200)
        self.assertEqual(int(round_table.loc[0, "live_start_tick"]), 200)
        self.assertEqual(int(round_table.loc[0, "freeze_end_tick"]), 200)
        self.assertEqual(int(round_table.loc[0, "freeze_duration_ticks"]), 0)

    def test_round_one_freeze_start_skips_opening_movement_and_uses_stable_window(self) -> None:
        rows: list[dict[str, object]] = []
        for tick in range(1, 81):
            p1_x = float(tick) if tick <= 8 else 8.0
            p2_x = 100.0 + float(tick) if tick <= 8 else 108.0
            if tick >= 41:
                p1_x += float(tick - 40)
            rows.append({"tick": tick, "name": "p1", "X": p1_x, "Y": 0.0, "inferred_round_id": 1})
            rows.append({"tick": tick, "name": "p2", "X": p2_x, "Y": 0.0, "inferred_round_id": 1})
        ticks = pd.DataFrame(rows)
        jump_by_tick = pd.DataFrame(
            [
                {"tick": 1, "n_jump_players": 0, "max_jump": None, "median_jump": None},
            ]
        )

        round_table = build_inferred_rounds_table(ticks, jump_by_tick, [1])

        self.assertEqual(int(round_table.loc[0, "start_tick"]), 1)
        self.assertEqual(int(round_table.loc[0, "freeze_start_tick"]), 9)
        self.assertEqual(int(round_table.loc[0, "live_start_tick"]), 41)
        self.assertEqual(int(round_table.loc[0, "freeze_end_tick"]), 40)
        self.assertEqual(int(round_table.loc[0, "freeze_duration_ticks"]), 32)


if __name__ == "__main__":
    unittest.main()
