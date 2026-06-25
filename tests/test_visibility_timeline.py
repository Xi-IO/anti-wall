from __future__ import annotations

import unittest

import pandas as pd

from wall.domain.player import RoundPlayers
from wall.domain.visibility import VisibilityTimeline
from wall.dataset.rounds import get_round_data


def _frame(
    *,
    tick: int,
    name: str,
    steamid: str,
    team_num: int,
    x: float,
    y: float,
    z: float = 0.0,
    yaw: float = 0.0,
    health: int = 100,
) -> dict[str, object]:
    return {
        "tick": tick,
        "name": name,
        "steamid": steamid,
        "active_weapon_name": "",
        "has_defuser": False,
        "X": x,
        "Y": y,
        "Z": z,
        "yaw": yaw,
        "pitch": 0.0,
        "team_num": team_num,
        "health": health,
        "ducking": 0,
        "is_airborne": 0,
        "velocity_X": 0.0,
        "velocity_Y": 0.0,
        "velocity_Z": 0.0,
        "inferred_round_id": 1,
        "inferred_round_tick": tick,
        "inferred_round_seconds": tick / 64.0,
    }


def _empty_with_round_columns() -> pd.DataFrame:
    return pd.DataFrame(columns=["tick", "inferred_round_id", "inferred_round_tick", "inferred_round_seconds"])


def _inferred_rounds_row() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "inferred_round_id": 1,
                "start_tick": 100,
                "end_tick": 100,
                "n_rows": 0,
                "n_players": 0,
                "n_jump_players": 0,
                "max_jump": None,
                "median_jump": None,
                "freeze_start_tick": 100,
                "live_start_tick": 100,
                "freeze_end_tick": 99,
                "freeze_duration_ticks": 0,
                "freeze_duration_seconds": 0.0,
                "duration_ticks": 0,
                "duration_seconds": 0.0,
            }
        ]
    )


class VisibilityTimelineTests(unittest.TestCase):
    def test_observer_target_visibility_at_returns_true_for_enemy_inside_fov(self) -> None:
        round_ticks = pd.DataFrame(
            [
                _frame(tick=100, name="observer", steamid="s1", team_num=2, x=0.0, y=0.0, yaw=0.0),
                _frame(tick=100, name="enemy_front", steamid="s2", team_num=3, x=10.0, y=0.0, yaw=180.0),
            ]
        )
        timeline = VisibilityTimeline(RoundPlayers.from_round_ticks(round_ticks), fov_deg=90.0)

        judgement = timeline.observer_target_visibility_at("observer", "enemy_front", 100)

        self.assertTrue(judgement.in_fov)
        self.assertIsNone(judgement.has_los)
        self.assertTrue(judgement.is_visible)
        self.assertIsNotNone(judgement.distance)
        self.assertIsNotNone(judgement.relative_yaw_deg)
        self.assertAlmostEqual(float(judgement.distance), 10.0)
        self.assertAlmostEqual(float(judgement.relative_yaw_deg), 0.0)

    def test_state_at_only_lists_enemies_within_fov(self) -> None:
        round_ticks = pd.DataFrame(
            [
                _frame(tick=100, name="observer", steamid="s1", team_num=2, x=0.0, y=0.0, yaw=0.0),
                _frame(tick=100, name="enemy_front", steamid="s2", team_num=3, x=10.0, y=0.0, yaw=180.0),
                _frame(tick=100, name="enemy_side", steamid="s3", team_num=3, x=0.0, y=10.0, yaw=180.0),
                _frame(tick=100, name="teammate", steamid="s4", team_num=2, x=5.0, y=0.0, yaw=0.0),
            ]
        )
        timeline = VisibilityTimeline(RoundPlayers.from_round_ticks(round_ticks), fov_deg=90.0)

        state = timeline.state_at("observer", 100)

        self.assertEqual(state.visible_enemies, ("enemy_front",))
        self.assertEqual([judgement.target for judgement in state.judgements], ["enemy_front", "enemy_side"])
        self.assertEqual(timeline.visible_enemies_at("observer", 100), ["enemy_front"])

    def test_observer_target_visibility_at_rejects_dead_or_friendly_targets(self) -> None:
        round_ticks = pd.DataFrame(
            [
                _frame(tick=100, name="observer", steamid="s1", team_num=2, x=0.0, y=0.0, yaw=0.0),
                _frame(tick=100, name="friendly", steamid="s2", team_num=2, x=10.0, y=0.0, yaw=180.0),
                _frame(tick=100, name="dead_enemy", steamid="s3", team_num=3, x=12.0, y=0.0, yaw=180.0, health=0),
            ]
        )
        timeline = VisibilityTimeline(RoundPlayers.from_round_ticks(round_ticks), fov_deg=90.0)

        friendly = timeline.observer_target_visibility_at("observer", "friendly", 100)
        dead_enemy = timeline.observer_target_visibility_at("observer", "dead_enemy", 100)

        self.assertFalse(friendly.in_fov)
        self.assertFalse(dead_enemy.in_fov)
        self.assertFalse(friendly.is_visible)
        self.assertFalse(dead_enemy.is_visible)

    def test_line_of_sight_blocks_visibility_even_when_target_is_in_fov(self) -> None:
        round_ticks = pd.DataFrame(
            [
                _frame(tick=100, name="observer", steamid="s1", team_num=2, x=0.0, y=0.0, yaw=0.0),
                _frame(tick=100, name="enemy_front", steamid="s2", team_num=3, x=10.0, y=0.0, yaw=180.0),
            ]
        )

        class FakeChecker:
            def is_visible(self, start, end):
                return False

        timeline = VisibilityTimeline(
            RoundPlayers.from_round_ticks(round_ticks),
            fov_deg=90.0,
            visibility_checker=FakeChecker(),
        )

        judgement = timeline.observer_target_visibility_at("observer", "enemy_front", 100)

        self.assertTrue(judgement.in_fov)
        self.assertFalse(bool(judgement.has_los))
        self.assertFalse(judgement.is_visible)
        self.assertEqual(timeline.visible_enemies_at("observer", 100), [])

    def test_round_data_exposes_visibility_timeline(self) -> None:
        ticks = pd.DataFrame(
            [
                _frame(tick=100, name="observer", steamid="s1", team_num=2, x=0.0, y=0.0, yaw=0.0),
                _frame(tick=100, name="enemy_front", steamid="s2", team_num=3, x=10.0, y=0.0, yaw=180.0),
            ]
        )
        deaths = _empty_with_round_columns()
        round_data = get_round_data(
            ticks=ticks,
            deaths=deaths,
            fires=pd.DataFrame(),
            hurts=pd.DataFrame(),
            hits=pd.DataFrame(),
            footsteps=pd.DataFrame(),
            smoke_detonates=pd.DataFrame(),
            flash_detonates=pd.DataFrame(),
            he_detonates=pd.DataFrame(),
            blinds=pd.DataFrame(),
            bomb_pickups=pd.DataFrame(),
            bomb_drops=pd.DataFrame(),
            bomb_begin_plants=pd.DataFrame(),
            bomb_plants=pd.DataFrame(),
            bomb_defuses=pd.DataFrame(),
            bomb_begin_defuses=pd.DataFrame(),
            bomb_abort_defuses=pd.DataFrame(),
            bomb_explodes=pd.DataFrame(),
            smoke_expires=pd.DataFrame(),
            inferno_starts=pd.DataFrame(),
            sound_effects=pd.DataFrame(),
            inferred_rounds=_inferred_rounds_row(),
            round_id=1,
            tickrate=64.0,
        )

        visible = round_data.visibility_timeline.visible_enemies_at("observer", 100)

        self.assertEqual(visible, ["enemy_front"])


if __name__ == "__main__":
    unittest.main()
