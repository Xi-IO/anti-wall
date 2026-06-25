from __future__ import annotations

import unittest

import pandas as pd

from wall.dataset.rounds import get_round_data
from wall.viewer.player_frame import assemble_player_frame_presentation


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
    active_weapon_name: str = "",
) -> dict[str, object]:
    return {
        "tick": tick,
        "name": name,
        "steamid": steamid,
        "active_weapon_name": active_weapon_name,
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


def _round_data() -> object:
    ticks = pd.DataFrame(
        [
            _frame(tick=100, name="observer", steamid="s1", team_num=2, x=0.0, y=0.0, yaw=0.0, active_weapon_name="AK-47"),
            _frame(tick=100, name="enemy_front", steamid="s2", team_num=3, x=10.0, y=0.0, yaw=180.0),
            _frame(tick=101, name="observer", steamid="s1", team_num=2, x=1.0, y=0.0, yaw=0.0, active_weapon_name="AK-47"),
            _frame(tick=101, name="enemy_front", steamid="s2", team_num=3, x=10.0, y=0.0, yaw=180.0),
        ]
    )
    fires = pd.DataFrame(
        [
            {
                "tick": 101,
                "user_name": "observer",
                "user_steamid": "s1",
                "team_num": 2,
                "inferred_round_id": 1,
                "inferred_round_tick": 101,
                "inferred_round_seconds": 101 / 64.0,
            }
        ]
    )
    hurts = pd.DataFrame(
        [
            {
                "tick": 101,
                "attacker_name": "observer",
                "attacker_steamid": "s1",
                "user_name": "enemy_front",
                "inferred_round_id": 1,
                "inferred_round_tick": 101,
                "inferred_round_seconds": 101 / 64.0,
            }
        ]
    )
    return get_round_data(
        ticks=ticks,
        deaths=_empty_with_round_columns(),
        fires=fires,
        hurts=hurts,
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
        inferred_rounds=pd.DataFrame(
            [
                {
                    "inferred_round_id": 1,
                    "freeze_start_tick": 100,
                    "freeze_end_tick": 100,
                    "live_start_tick": 101,
                }
            ]
        ),
        round_id=1,
        tickrate=64.0,
    )


class PlayerFramePresentationTests(unittest.TestCase):
    def test_assemble_player_frame_presentation_includes_tracer_and_weapon_name(self) -> None:
        round_data = _round_data()
        timeline = round_data.round_players.get_by_name("observer")
        assert timeline is not None

        presentation = assemble_player_frame_presentation(
            player="observer",
            player_number=1,
            frame_tick=101,
            timeline=timeline,
            round_players=round_data.round_players,
            round_start_tick=round_data.round_start_tick,
            trail=24,
            damage_flash_duration_ticks=96,
            fire_flash_duration_ticks=32,
            hit_match_window_ticks=12,
            base_color=(217, 205, 33),
        )

        self.assertIsNotNone(presentation)
        assert presentation is not None
        self.assertTrue(presentation.is_alive)
        self.assertEqual(presentation.weapon_name, "AK-47")
        self.assertIsNotNone(presentation.tracer)
        assert presentation.tracer is not None
        self.assertEqual(presentation.tracer.team_num, 2)
        self.assertEqual(presentation.tracer.hit_position_world, (10.0, 0.0))

    def test_assemble_player_frame_presentation_includes_death_marker_for_dead_player(self) -> None:
        round_data = _round_data()
        timeline = round_data.round_players.get_by_name("enemy_front")
        assert timeline is not None
        timeline.death_tick = 101
        timeline.death_events = [pd.Series({"tick": 101, "user_X": 10.0, "user_Y": 0.0})]

        presentation = assemble_player_frame_presentation(
            player="enemy_front",
            player_number=2,
            frame_tick=101,
            timeline=timeline,
            round_players=round_data.round_players,
            round_start_tick=round_data.round_start_tick,
            trail=24,
            damage_flash_duration_ticks=96,
            fire_flash_duration_ticks=32,
            hit_match_window_ticks=12,
            base_color=(25, 145, 189),
        )

        self.assertIsNotNone(presentation)
        assert presentation is not None
        self.assertFalse(presentation.is_alive)
        self.assertIsNotNone(presentation.death)
        assert presentation.death is not None
        self.assertEqual(presentation.death.world_position, (10.0, 0.0))
        self.assertEqual(presentation.death.label, "enemy_front")


if __name__ == "__main__":
    unittest.main()
