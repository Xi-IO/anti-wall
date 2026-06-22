from __future__ import annotations

import unittest

import pandas as pd

from wall.io.demo_parse import build_item_drop_sound_events


class ItemDropSoundEventTests(unittest.TestCase):
    def test_item_drops_are_classified_for_analysis_and_viewer(self) -> None:
        item_drops = pd.DataFrame(
            [
                {
                    "tick": 100,
                    "user_name": "rifler",
                    "user_steamid": "steamid-rifle",
                    "defindex": 7,
                    "item_name": "weapon_ak47",
                    "X": 10.0,
                    "Y": 20.0,
                    "Z": 30.0,
                    "inferred_round_id": 1,
                    "inferred_round_tick": 36,
                    "inferred_round_seconds": 0.5625,
                },
                {
                    "tick": 110,
                    "user_name": "support",
                    "user_steamid": "steamid-util",
                    "defindex": 43,
                    "item_name": "weapon_flashbang",
                    "X": 15.0,
                    "Y": 25.0,
                    "Z": 35.0,
                    "inferred_round_id": 1,
                    "inferred_round_tick": 46,
                    "inferred_round_seconds": 0.71875,
                },
                {
                    "tick": 120,
                    "user_name": "carrier",
                    "user_steamid": "steamid-c4",
                    "defindex": 49,
                    "item_name": "weapon_c4",
                    "X": 18.0,
                    "Y": 28.0,
                    "Z": 38.0,
                    "inferred_round_id": 1,
                    "inferred_round_tick": 56,
                    "inferred_round_seconds": 0.875,
                },
            ]
        )

        result = build_item_drop_sound_events(item_drops)

        self.assertEqual(list(result["sound_kind"]), ["weapon_drop", "utility_drop"])
        self.assertEqual(list(result["weapon_id"]), ["weapon_ak47", "weapon_flashbang"])
        self.assertEqual(list(result["detail"]), ["weapon_drop|weapon_ak47", "utility_drop|weapon_flashbang"])
        self.assertTrue((result["sound_source"] == "item_drop").all())
        self.assertTrue((result["audible_rule"] == "radius").all())
        self.assertEqual(list(result["radius_world"]), [650.0, 550.0])
        self.assertNotIn("weapon_c4", set(result["weapon_id"]))


if __name__ == "__main__":
    unittest.main()
