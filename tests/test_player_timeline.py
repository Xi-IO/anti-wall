from __future__ import annotations

import unittest

import pandas as pd

from wall.domain.player import PlayerTimeline


class PlayerTimelineTests(unittest.TestCase):
    def test_frame_at_exposes_active_weapon_name(self) -> None:
        frames = pd.DataFrame(
            [
                {
                    "tick": 10,
                    "name": "p1",
                    "steamid": "s1",
                    "active_weapon_name": "AK-47",
                    "has_defuser": True,
                    "X": 0.0,
                    "Y": 0.0,
                    "Z": 0.0,
                    "yaw": 0.0,
                    "pitch": 0.0,
                    "team_num": 2,
                    "health": 100,
                    "ducking": 0,
                    "is_airborne": 0,
                    "velocity_X": 0.0,
                    "velocity_Y": 0.0,
                    "velocity_Z": 0.0,
                },
            ]
        )
        timeline = PlayerTimeline("s1", frames)

        frame = timeline.frame_at(10)

        self.assertIsNotNone(frame)
        self.assertEqual(frame.active_weapon_name, "AK-47")
        self.assertTrue(frame.has_defuser)

    def test_frame_at_defaults_missing_active_weapon_name_to_empty_string(self) -> None:
        frames = pd.DataFrame(
            [
                {
                    "tick": 10,
                    "name": "p1",
                    "steamid": "s1",
                    "X": 0.0,
                    "Y": 0.0,
                    "Z": 0.0,
                    "yaw": 0.0,
                    "pitch": 0.0,
                    "team_num": 2,
                    "health": 100,
                    "ducking": 0,
                    "is_airborne": 0,
                    "velocity_X": 0.0,
                    "velocity_Y": 0.0,
                    "velocity_Z": 0.0,
                },
            ]
        )
        timeline = PlayerTimeline("s1", frames)

        frame = timeline.frame_at(10)

        self.assertIsNotNone(frame)
        self.assertEqual(frame.active_weapon_name, "")
        self.assertFalse(frame.has_defuser)

    def test_overlay_state_combines_damage_flash_and_blind_strength(self) -> None:
        frames = pd.DataFrame(
            [
                {"tick": 10, "name": "p1", "steamid": "s1", "X": 0.0, "Y": 0.0, "Z": 0.0, "yaw": 0.0, "pitch": 0.0, "team_num": 2, "health": 100, "ducking": 0, "is_airborne": 0, "velocity_X": 0.0, "velocity_Y": 0.0, "velocity_Z": 0.0},
                {"tick": 11, "name": "p1", "steamid": "s1", "X": 0.0, "Y": 0.0, "Z": 0.0, "yaw": 0.0, "pitch": 0.0, "team_num": 2, "health": 70, "ducking": 0, "is_airborne": 0, "velocity_X": 0.0, "velocity_Y": 0.0, "velocity_Z": 0.0},
                {"tick": 12, "name": "p1", "steamid": "s1", "X": 0.0, "Y": 0.0, "Z": 0.0, "yaw": 0.0, "pitch": 0.0, "team_num": 2, "health": 70, "ducking": 0, "is_airborne": 0, "velocity_X": 0.0, "velocity_Y": 0.0, "velocity_Z": 0.0},
            ]
        )
        timeline = PlayerTimeline(
            "s1",
            frames,
            blind_events=[{"start_tick": 10, "end_tick": 14, "severity": 0.8}],
        )

        overlay = timeline.overlay_state_at(12, damage_flash_duration_ticks=10)

        self.assertGreater(overlay.damage_flash_fade, 0.0)
        self.assertGreater(overlay.blind_strength, 0.0)

    def test_resolve_hit_position_for_fire_event_uses_victim_lookup(self) -> None:
        frames = pd.DataFrame(
            [
                {"tick": 10, "name": "attacker", "steamid": "s1", "X": 0.0, "Y": 0.0, "Z": 0.0, "yaw": 0.0, "pitch": 0.0, "team_num": 2, "health": 100, "ducking": 0, "is_airborne": 0, "velocity_X": 0.0, "velocity_Y": 0.0, "velocity_Z": 0.0},
            ]
        )
        fire_event = pd.Series({"tick": 10})
        hurt_event = pd.Series({"tick": 12, "user_name": "victim"})
        timeline = PlayerTimeline(
            "s1",
            frames,
            fire_events=[fire_event],
            hurt_events=[hurt_event],
        )

        hit_position = timeline.resolve_hit_position_for_fire_event(
            fire_event,
            max_tick=14,
            victim_position_lookup=lambda hurt: (10.0, 20.0) if hurt.get("user_name") == "victim" else None,
        )

        self.assertEqual(hit_position, (10.0, 20.0))


if __name__ == "__main__":
    unittest.main()
