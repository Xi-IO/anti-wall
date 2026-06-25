from __future__ import annotations

import unittest

import pandas as pd

from wall.io.sound_effects import build_gunfire_sound_effects, build_item_drop_sound_effects


class ItemDropSoundEventTests(unittest.TestCase):
    def test_item_drops_become_clean_sound_effect_rows(self) -> None:
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

        result = build_item_drop_sound_effects(item_drops)

        self.assertEqual(list(result["emitter_type"]), ["impulse", "impulse"])
        self.assertEqual(list(result["source_type"]), ["dropped_item", "dropped_item"])
        self.assertEqual(list(result["sound_class"]), ["item", "item"])
        self.assertEqual(list(result["sound_action"]), ["dropped", "dropped"])
        self.assertEqual(list(result["item_name"]), ["ak47", "flashbang"])
        self.assertEqual(list(result["position_mode"]), ["event_snapshot", "event_snapshot"])
        self.assertTrue((result["raw_source"] == "item_drop").all())
        self.assertEqual(list(result["radius"]), [650.0, 550.0])
        self.assertNotIn("c4", set(result["item_name"]))
        self.assertTrue(result["shot_count"].isna().all())

    def test_gunfire_bursts_are_compressed_by_player_weapon_and_tick_gap(self) -> None:
        fires = pd.DataFrame(
            [
                {
                    "tick": 7430,
                    "user_name": "entry",
                    "user_steamid": "steamid-entry",
                    "item_def_index": 17,
                    "inferred_round_id": 1,
                },
                {
                    "tick": 7435,
                    "user_name": "entry",
                    "user_steamid": "steamid-entry",
                    "item_def_index": 17,
                    "inferred_round_id": 1,
                },
                {
                    "tick": 7440,
                    "user_name": "entry",
                    "user_steamid": "steamid-entry",
                    "item_def_index": 17,
                    "inferred_round_id": 1,
                },
                {
                    "tick": 7445,
                    "user_name": "entry",
                    "user_steamid": "steamid-entry",
                    "item_def_index": 17,
                    "inferred_round_id": 1,
                },
                {
                    "tick": 7460,
                    "user_name": "entry",
                    "user_steamid": "steamid-entry",
                    "item_def_index": 17,
                    "inferred_round_id": 1,
                },
            ]
        )

        result = build_gunfire_sound_effects(fires)

        self.assertEqual(len(result), 2)
        self.assertEqual(list(result["emitter_type"]), ["continuous", "continuous"])
        self.assertEqual(list(result["sound_action"]), ["gunfire", "gunfire"])
        self.assertEqual(list(result["start_tick"]), [7430, 7460])
        self.assertEqual(list(result["end_tick"]), [7445, 7460])
        self.assertEqual(list(result["shot_count"]), [4, 1])
        self.assertTrue((result["raw_source"] == "fire_bullets").all())

    def test_gunfire_bursts_do_not_merge_different_weapons(self) -> None:
        fires = pd.DataFrame(
            [
                {
                    "tick": 100,
                    "user_name": "entry",
                    "user_steamid": "steamid-entry",
                    "item_def_index": 17,
                    "inferred_round_id": 1,
                },
                {
                    "tick": 104,
                    "user_name": "entry",
                    "user_steamid": "steamid-entry",
                    "item_def_index": 7,
                    "inferred_round_id": 1,
                },
            ]
        )

        result = build_gunfire_sound_effects(fires)

        self.assertEqual(len(result), 2)
        self.assertEqual(sorted(result["item_name"].tolist()), ["ak47", "mac10"])
        self.assertEqual(sorted(result["shot_count"].tolist()), [1, 1])

    def test_gunfire_burst_gap_uses_weapon_type_thresholds(self) -> None:
        fires = pd.DataFrame(
            [
                {
                    "tick": 100,
                    "user_name": "entry",
                    "user_steamid": "steamid-entry",
                    "item_def_index": 17,
                    "inferred_round_id": 1,
                },
                {
                    "tick": 130,
                    "user_name": "entry",
                    "user_steamid": "steamid-entry",
                    "item_def_index": 17,
                    "inferred_round_id": 1,
                },
                {
                    "tick": 200,
                    "user_name": "anchor",
                    "user_steamid": "steamid-anchor",
                    "item_def_index": 4,
                    "inferred_round_id": 1,
                },
                {
                    "tick": 230,
                    "user_name": "anchor",
                    "user_steamid": "steamid-anchor",
                    "item_def_index": 4,
                    "inferred_round_id": 1,
                },
            ]
        )

        result = build_gunfire_sound_effects(fires)
        mac10 = result[result["item_name"] == "mac10"].reset_index(drop=True)
        glock = result[result["item_name"] == "glock"].reset_index(drop=True)

        self.assertEqual(len(mac10), 2)
        self.assertEqual(list(mac10["start_tick"]), [100, 130])
        self.assertEqual(list(mac10["end_tick"]), [100, 130])
        self.assertEqual(list(mac10["shot_count"]), [1, 1])

        self.assertEqual(len(glock), 1)
        self.assertEqual(int(glock.loc[0, "start_tick"]), 200)
        self.assertEqual(int(glock.loc[0, "end_tick"]), 230)
        self.assertEqual(int(glock.loc[0, "shot_count"]), 2)


if __name__ == "__main__":
    unittest.main()
