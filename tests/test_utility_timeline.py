from __future__ import annotations

import unittest

import pandas as pd

from wall.domain.utility import SmokeHole, UtilityTimeline


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame()


class UtilityTimelineTests(unittest.TestCase):
    def test_active_grenade_trails_hide_after_effect_start(self) -> None:
        segments = pd.DataFrame(
            [
                {
                    "round_id": 1,
                    "grenade_id": "1",
                    "grenade_type": "CSmokeGrenadeProjectile",
                    "thrower_key": "s1",
                    "thrower": "p1",
                    "segment_index": 0,
                    "start_tick": 100,
                    "end_tick": 102,
                    "start_x": 0.0,
                    "start_y": 0.0,
                    "start_z": 0.0,
                    "end_x": 2.0,
                    "end_y": 2.0,
                    "end_z": 0.0,
                },
            ]
        )
        smoke_detonates = pd.DataFrame([{"tick": 101, "x": 5.0, "y": 6.0, "entityid": 1}])
        timeline = UtilityTimeline(
            round_smoke_detonates=smoke_detonates,
            round_smoke_expires=_empty_df(),
            round_flash_detonates=_empty_df(),
            round_he_detonates=_empty_df(),
            round_inferno_starts=_empty_df(),
            round_grenade_trajectory_segments=segments,
            flash_effect_ticks=10,
            he_effect_ticks=10,
            inferno_duration_ticks=100,
            inferno_ct_radius_world=128.0,
            inferno_t_radius_world=144.0,
            smoke_radius_world=176.0,
            smoke_deploy_ticks=2,
            player_team_lookup=lambda _name, _steamid, _tick: 2,
        )

        visible = timeline.active_grenade_trails_at(102, recent_window_ticks=8, smoke_deploy_ticks=2)
        hidden = timeline.active_grenade_trails_at(103, recent_window_ticks=8, smoke_deploy_ticks=2)

        self.assertEqual(len(visible), 1)
        self.assertEqual(visible[0].current_x, 2.0)
        self.assertEqual(hidden, [])

    def test_smoke_holes_return_typed_objects(self) -> None:
        smoke_detonates = pd.DataFrame([{"tick": 100, "x": 0.0, "y": 0.0, "entityid": 1}])
        he_detonates = pd.DataFrame([{"tick": 110, "x": 20.0, "y": 20.0, "entityid": 2}])
        timeline = UtilityTimeline(
            round_smoke_detonates=smoke_detonates,
            round_smoke_expires=_empty_df(),
            round_flash_detonates=_empty_df(),
            round_he_detonates=he_detonates,
            round_inferno_starts=_empty_df(),
            round_grenade_trajectory_segments=_empty_df(),
            flash_effect_ticks=10,
            he_effect_ticks=12,
            inferno_duration_ticks=100,
            inferno_ct_radius_world=128.0,
            inferno_t_radius_world=144.0,
            smoke_radius_world=176.0,
            smoke_deploy_ticks=18,
            player_team_lookup=lambda _name, _steamid, _tick: 2,
        )

        holes = timeline.smoke_holes_for_window(0)

        self.assertEqual(len(holes), 1)
        self.assertIsInstance(holes[0], SmokeHole)
        self.assertEqual(holes[0].start_tick, 110)

    def test_active_grenade_trails_can_interpolate_from_segment_artifact(self) -> None:
        segments = pd.DataFrame(
            [
                {
                    "round_id": 1,
                    "grenade_id": "7",
                    "grenade_type": "CSmokeGrenadeProjectile",
                    "thrower_key": "s1",
                    "thrower": "p1",
                    "segment_index": 0,
                    "start_tick": 100,
                    "end_tick": 102,
                    "start_x": 0.0,
                    "start_y": 0.0,
                    "start_z": 0.0,
                    "end_x": 20.0,
                    "end_y": 20.0,
                    "end_z": 0.0,
                }
            ]
        )
        smoke_detonates = pd.DataFrame([{"tick": 110, "x": 5.0, "y": 6.0, "entityid": 7}])
        timeline = UtilityTimeline(
            round_smoke_detonates=smoke_detonates,
            round_smoke_expires=_empty_df(),
            round_flash_detonates=_empty_df(),
            round_he_detonates=_empty_df(),
            round_inferno_starts=_empty_df(),
            round_grenade_trajectory_segments=segments,
            flash_effect_ticks=10,
            he_effect_ticks=10,
            inferno_duration_ticks=100,
            inferno_ct_radius_world=128.0,
            inferno_t_radius_world=144.0,
            smoke_radius_world=176.0,
            smoke_deploy_ticks=2,
            player_team_lookup=lambda _name, _steamid, _tick: 2,
        )

        active = timeline.active_grenade_trails_at(101, recent_window_ticks=8, smoke_deploy_ticks=2)

        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].current_x, 10.0)
        self.assertEqual(active[0].current_y, 10.0)
        self.assertEqual([point.tick for point in active[0].recent_points], [100, 101])
if __name__ == "__main__":
    unittest.main()
