from __future__ import annotations

from contextlib import redirect_stdout
import io
import os
import shutil
from pathlib import Path
import unittest
import uuid

import pandas as pd

import wall.sound.exposure as sound_exposure
from wall.cli import build_sound_exposure_parser, handle_sound_exposure
from wall.dataset.rounds import get_round_data
from wall.sound.exposure import build_sound_exposure_table, run_sound_exposure_exports


TEST_TMP_ROOT = Path("F:/wall/tmp_test_sound_exposure_export")


class _InlineProcessPoolExecutor:
    class _InlineFuture:
        def __init__(self, fn, arg) -> None:
            self._fn = fn
            self._arg = arg

        def result(self):
            return self._fn(self._arg)

    def __init__(self, max_workers: int) -> None:
        self.max_workers = max_workers

    def __enter__(self) -> "_InlineProcessPoolExecutor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def submit(self, fn, arg):
        return self._InlineFuture(fn, arg)


def make_test_dir() -> Path:
    TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = TEST_TMP_ROOT / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


def _frame(
    *,
    tick: int,
    name: str,
    steamid: str,
    team_num: int,
    x: float,
    y: float,
    z: float = 0.0,
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
        "yaw": 0.0,
        "pitch": 0.0,
        "team_num": team_num,
        "health": health,
        "ducking": 0,
        "is_airborne": 0,
        "velocity_X": 0.0,
        "velocity_Y": 0.0,
        "velocity_Z": 0.0,
        "inferred_round_id": 1,
        "inferred_round_tick": tick - 100,
        "inferred_round_seconds": (tick - 100) / 64.0,
    }


def _effect(
    *,
    effect_id: str,
    emitter_type: str,
    source_type: str,
    source_id: str,
    start_tick: int,
    end_tick: int,
    sound_class: str,
    sound_action: str,
    radius: float,
    raw_source: str,
    item_name: str = "",
    position_mode: str = "entity_at_tick",
    x: float | None = None,
    y: float | None = None,
    z: float | None = None,
    shot_count: int | None = None,
) -> dict[str, object]:
    return {
        "round_id": 1,
        "effect_id": effect_id,
        "emitter_type": emitter_type,
        "source_type": source_type,
        "source_id": source_id,
        "start_tick": start_tick,
        "end_tick": end_tick,
        "sound_class": sound_class,
        "sound_action": sound_action,
        "item_name": item_name,
        "radius": radius,
        "position_mode": position_mode,
        "x": x,
        "y": y,
        "z": z,
        "raw_source": raw_source,
        "shot_count": shot_count,
    }


def _empty_with_round_columns() -> pd.DataFrame:
    return pd.DataFrame(columns=["tick", "inferred_round_id", "inferred_round_tick", "inferred_round_seconds"])


def _inferred_rounds() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "inferred_round_id": 1,
                "start_tick": 100,
                "end_tick": 103,
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
                "duration_ticks": 3,
                "duration_seconds": 3 / 64.0,
            }
        ]
    )


class SoundExposureExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_process_pool_executor = sound_exposure.ProcessPoolExecutor
        self._original_as_completed = sound_exposure.as_completed

    def tearDown(self) -> None:
        sound_exposure.ProcessPoolExecutor = self._original_process_pool_executor
        sound_exposure.as_completed = self._original_as_completed
        shutil.rmtree(TEST_TMP_ROOT, ignore_errors=True)

    def test_build_sound_exposure_table_filters_to_enemy_alive_observers_and_compresses_continuous(self) -> None:
        ticks = pd.DataFrame(
            [
                _frame(tick=100, name="source", steamid="s_src", team_num=2, x=0.0, y=0.0),
                _frame(tick=100, name="teammate", steamid="s_tm", team_num=2, x=5.0, y=0.0),
                _frame(tick=100, name="enemy_near", steamid="s_e1", team_num=3, x=10.0, y=0.0),
                _frame(tick=100, name="enemy_dead", steamid="s_e2", team_num=3, x=8.0, y=0.0),
                _frame(tick=101, name="source", steamid="s_src", team_num=2, x=0.0, y=0.0),
                _frame(tick=101, name="teammate", steamid="s_tm", team_num=2, x=5.0, y=0.0),
                _frame(tick=101, name="enemy_near", steamid="s_e1", team_num=3, x=11.0, y=0.0),
                _frame(tick=101, name="enemy_dead", steamid="s_e2", team_num=3, x=9.0, y=0.0),
                _frame(tick=102, name="source", steamid="s_src", team_num=2, x=0.0, y=0.0),
                _frame(tick=102, name="teammate", steamid="s_tm", team_num=2, x=5.0, y=0.0),
                _frame(tick=102, name="enemy_near", steamid="s_e1", team_num=3, x=40.0, y=0.0),
                _frame(tick=102, name="enemy_dead", steamid="s_e2", team_num=3, x=9.0, y=0.0, health=0),
                _frame(tick=103, name="source", steamid="s_src", team_num=2, x=0.0, y=0.0),
                _frame(tick=103, name="teammate", steamid="s_tm", team_num=2, x=5.0, y=0.0),
                _frame(tick=103, name="enemy_near", steamid="s_e1", team_num=3, x=12.0, y=0.0),
                _frame(tick=103, name="enemy_dead", steamid="s_e2", team_num=3, x=9.0, y=0.0, health=0),
            ]
        )
        sound_effects = pd.DataFrame(
            [
                _effect(
                    effect_id="impulse_1",
                    emitter_type="impulse",
                    source_type="player",
                    source_id="s_src",
                    start_tick=100,
                    end_tick=100,
                    sound_class="weapon",
                    sound_action="reload",
                    radius=20.0,
                    raw_source="weapon_reload",
                ),
                _effect(
                    effect_id="move_1",
                    emitter_type="continuous",
                    source_type="player",
                    source_id="s_src",
                    start_tick=100,
                    end_tick=103,
                    sound_class="movement",
                    sound_action="locomotion",
                    radius=20.0,
                    raw_source="inferred_movement",
                ),
            ]
        )
        deaths = pd.DataFrame(
            [
                {
                    "tick": 102,
                    "user_name": "enemy_dead",
                    "user_steamid": "s_e2",
                    "inferred_round_id": 1,
                    "inferred_round_tick": 2,
                    "inferred_round_seconds": 2 / 64.0,
                }
            ]
        )
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
            sound_effects=sound_effects,
            inferred_rounds=_inferred_rounds(),
            round_id=1,
            tickrate=64.0,
        )

        table = build_sound_exposure_table(round_data, tick_step=1)

        self.assertNotIn("exposure_id", table.columns)
        self.assertEqual(set(table["observer_id"]), {"s_e1", "s_e2"})
        self.assertNotIn("s_src", set(table["observer_id"]))
        self.assertNotIn("s_tm", set(table["observer_id"]))

        impulse_rows = table[table["exposure_type"] == "heard_impulse"].sort_values("observer_id")
        self.assertEqual(impulse_rows["observer_id"].tolist(), ["s_e1", "s_e2"])
        self.assertTrue((impulse_rows["start_tick"] == 100).all())
        self.assertTrue((impulse_rows["end_tick"] == 100).all())

        interval_rows = table[table["exposure_type"] == "heard_interval"].sort_values(["observer_id", "start_tick"])
        self.assertEqual(interval_rows["observer_id"].tolist(), ["s_e1", "s_e1", "s_e2"])
        self.assertEqual(interval_rows["start_tick"].tolist(), [100, 103, 100])
        self.assertEqual(interval_rows["end_tick"].tolist(), [101, 103, 101])
        self.assertEqual(interval_rows["distance_at_start"].tolist(), [10.0, 12.0, 8.0])
        self.assertEqual(interval_rows["distance_min"].tolist(), [10.0, 12.0, 8.0])

    def test_build_sound_exposure_table_uses_grenade_owner_team_for_enemy_filtering(self) -> None:
        ticks = pd.DataFrame(
            [
                _frame(tick=100, name="thrower", steamid="s_throw", team_num=2, x=0.0, y=0.0),
                _frame(tick=100, name="enemy", steamid="s_enemy", team_num=3, x=5.0, y=0.0),
                _frame(tick=100, name="friend", steamid="s_friend", team_num=2, x=5.0, y=0.0),
            ]
        )
        sound_effects = pd.DataFrame(
            [
                _effect(
                    effect_id="bounce_1",
                    emitter_type="impulse",
                    source_type="grenade",
                    source_id="g1",
                    start_tick=100,
                    end_tick=100,
                    sound_class="utility",
                    sound_action="bounce",
                    radius=20.0,
                    raw_source="grenade_bounce",
                    position_mode="event_snapshot",
                    x=0.0,
                    y=0.0,
                    z=0.0,
                )
            ]
        )
        grenade_segments = pd.DataFrame(
            [
                {
                    "round_id": 1,
                    "grenade_id": "g1",
                    "grenade_type": "CSmokeGrenadeProjectile",
                    "segment_index": 0,
                    "start_tick": 99,
                    "end_tick": 100,
                    "start_x": -5.0,
                    "start_y": 0.0,
                    "start_z": 0.0,
                    "end_x": 0.0,
                    "end_y": 0.0,
                    "end_z": 0.0,
                    "thrower_key": "s_throw",
                    "thrower": "thrower",
                }
            ]
        )
        round_data = get_round_data(
            ticks=ticks,
            deaths=_empty_with_round_columns(),
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
            sound_effects=sound_effects,
            inferred_rounds=_inferred_rounds(),
            round_id=1,
            tickrate=64.0,
            grenade_trajectory_segments=grenade_segments,
        )

        table = build_sound_exposure_table(round_data, tick_step=1)

        self.assertEqual(table["observer_id"].tolist(), ["s_enemy"])
        self.assertEqual(table["source_type"].tolist(), ["grenade"])
        self.assertEqual(table["raw_source"].tolist(), ["grenade_bounce"])

    def test_handle_sound_exposure_writes_independent_artifact_without_touching_visibility(self) -> None:
        data_dir = make_test_dir()
        ticks = pd.DataFrame(
            [
                _frame(tick=100, name="source", steamid="s_src", team_num=2, x=0.0, y=0.0),
                _frame(tick=100, name="enemy", steamid="s_enemy", team_num=3, x=10.0, y=0.0),
            ]
        )
        sound_effects = pd.DataFrame(
            [
                _effect(
                    effect_id="impulse_1",
                    emitter_type="impulse",
                    source_type="player",
                    source_id="s_src",
                    start_tick=100,
                    end_tick=100,
                    sound_class="damage",
                    sound_action="hurt",
                    radius=20.0,
                    raw_source="player_hurt",
                )
            ]
        )
        ticks.to_parquet(data_dir / "ticks.parquet", index=False)
        _empty_with_round_columns().to_parquet(data_dir / "player_death.parquet", index=False)
        sound_effects.to_parquet(data_dir / "sound_effect.parquet", index=False)
        _inferred_rounds().to_parquet(data_dir / "inferred_rounds.parquet", index=False)
        (data_dir / "metadata.json").write_text('{"derived":{"map_name":"de_dust2"}}', encoding="utf-8")
        original_visibility = b"existing visibility"
        (data_dir / "visibility.parquet").write_bytes(original_visibility)

        args = build_sound_exposure_parser().parse_args([str(data_dir)])
        exit_code = handle_sound_exposure(args)

        self.assertEqual(exit_code, 0)
        artifact_path = data_dir / "sound_exposure.parquet"
        self.assertTrue(artifact_path.exists())
        exported = pd.read_parquet(artifact_path)
        self.assertEqual(exported["observer_id"].tolist(), ["s_enemy"])
        self.assertEqual(exported["exposure_type"].tolist(), ["heard_impulse"])
        self.assertEqual((data_dir / "visibility.parquet").read_bytes(), original_visibility)

    def test_build_sound_exposure_table_defaults_to_stratified_tick_steps(self) -> None:
        tick_rows: list[dict[str, object]] = []
        for tick in range(100, 117):
            tick_rows.append(_frame(tick=tick, name="source", steamid="s_src", team_num=2, x=0.0, y=0.0))
            tick_rows.append(_frame(tick=tick, name="enemy", steamid="s_enemy", team_num=3, x=10.0, y=0.0))
        ticks = pd.DataFrame(tick_rows)
        inferred_rounds = pd.DataFrame(
            [
                {
                    "inferred_round_id": 1,
                    "start_tick": 100,
                    "end_tick": 116,
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
                    "duration_ticks": 16,
                    "duration_seconds": 16 / 64.0,
                }
            ]
        )
        sound_effects = pd.DataFrame(
            [
                _effect(
                    effect_id="move_1",
                    emitter_type="continuous",
                    source_type="player",
                    source_id="s_src",
                    start_tick=100,
                    end_tick=116,
                    sound_class="movement",
                    sound_action="locomotion",
                    radius=20.0,
                    raw_source="inferred_movement",
                ),
                _effect(
                    effect_id="bomb_1",
                    emitter_type="continuous",
                    source_type="player",
                    source_id="s_src",
                    start_tick=100,
                    end_tick=116,
                    sound_class="bomb",
                    sound_action="begin_defuse",
                    radius=20.0,
                    raw_source="bomb_begindefuse",
                ),
            ]
        )
        round_data = get_round_data(
            ticks=ticks,
            deaths=_empty_with_round_columns(),
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
            sound_effects=sound_effects,
            inferred_rounds=inferred_rounds,
            round_id=1,
            tickrate=64.0,
        )

        table = build_sound_exposure_table(round_data)

        interval_rows = table[table["exposure_type"] == "heard_interval"].sort_values(["effect_id", "start_tick"])
        movement_rows = interval_rows[interval_rows["effect_id"] == "move_1"]
        bomb_rows = interval_rows[interval_rows["effect_id"] == "bomb_1"]
        self.assertEqual(movement_rows["start_tick"].tolist(), [100])
        self.assertEqual(movement_rows["end_tick"].tolist(), [116])
        self.assertEqual(bomb_rows["start_tick"].tolist(), [100])
        self.assertEqual(bomb_rows["end_tick"].tolist(), [116])

    def test_handle_sound_exposure_tick_step_1_can_preserve_finer_intervals(self) -> None:
        data_dir = make_test_dir()
        ticks = pd.DataFrame(
            [
                _frame(tick=100, name="source", steamid="s_src", team_num=2, x=0.0, y=0.0),
                _frame(tick=100, name="enemy", steamid="s_enemy", team_num=3, x=10.0, y=0.0),
                _frame(tick=101, name="source", steamid="s_src", team_num=2, x=0.0, y=0.0),
                _frame(tick=101, name="enemy", steamid="s_enemy", team_num=3, x=40.0, y=0.0),
                _frame(tick=102, name="source", steamid="s_src", team_num=2, x=0.0, y=0.0),
                _frame(tick=102, name="enemy", steamid="s_enemy", team_num=3, x=10.0, y=0.0),
            ]
        )
        inferred_rounds = pd.DataFrame(
            [
                {
                    "inferred_round_id": 1,
                    "start_tick": 100,
                    "end_tick": 102,
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
                    "duration_ticks": 2,
                    "duration_seconds": 2 / 64.0,
                }
            ]
        )
        sound_effects = pd.DataFrame(
            [
                _effect(
                    effect_id="move_1",
                    emitter_type="continuous",
                    source_type="player",
                    source_id="s_src",
                    start_tick=100,
                    end_tick=102,
                    sound_class="movement",
                    sound_action="locomotion",
                    radius=20.0,
                    raw_source="inferred_movement",
                )
            ]
        )
        ticks.to_parquet(data_dir / "ticks.parquet", index=False)
        _empty_with_round_columns().to_parquet(data_dir / "player_death.parquet", index=False)
        sound_effects.to_parquet(data_dir / "sound_effect.parquet", index=False)
        inferred_rounds.to_parquet(data_dir / "inferred_rounds.parquet", index=False)
        (data_dir / "metadata.json").write_text('{"derived":{"map_name":"de_dust2"}}', encoding="utf-8")

        args = build_sound_exposure_parser().parse_args([str(data_dir), "--tick-step", "1"])
        exit_code = handle_sound_exposure(args)

        self.assertEqual(exit_code, 0)
        exported = pd.read_parquet(data_dir / "sound_exposure.parquet")
        interval_rows = exported[exported["exposure_type"] == "heard_interval"].sort_values("start_tick")
        self.assertEqual(interval_rows["start_tick"].tolist(), [100, 102])
        self.assertEqual(interval_rows["end_tick"].tolist(), [100, 102])

    def test_movement_bbox_prefilter_reports_skips_in_profile_log(self) -> None:
        tick_rows: list[dict[str, object]] = []
        for tick in range(100, 181):
            tick_rows.append(_frame(tick=tick, name="source", steamid="s_src", team_num=2, x=0.0, y=0.0))
            tick_rows.append(_frame(tick=tick, name="enemy_far", steamid="s_enemy_far", team_num=3, x=5000.0, y=5000.0))
        ticks = pd.DataFrame(tick_rows)
        inferred_rounds = pd.DataFrame(
            [
                {
                    "inferred_round_id": 1,
                    "start_tick": 100,
                    "end_tick": 180,
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
                    "duration_ticks": 80,
                    "duration_seconds": 80 / 64.0,
                }
            ]
        )
        sound_effects = pd.DataFrame(
            [
                _effect(
                    effect_id="move_far",
                    emitter_type="continuous",
                    source_type="player",
                    source_id="s_src",
                    start_tick=100,
                    end_tick=180,
                    sound_class="movement",
                    sound_action="locomotion",
                    radius=850.0,
                    raw_source="inferred_movement",
                )
            ]
        )
        round_data = get_round_data(
            ticks=ticks,
            deaths=_empty_with_round_columns(),
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
            sound_effects=sound_effects,
            inferred_rounds=inferred_rounds,
            round_id=1,
            tickrate=64.0,
        )

        output = io.StringIO()
        old = os.environ.get("WALL_VIEWER_PROFILE")
        os.environ["WALL_VIEWER_PROFILE"] = "1"
        try:
            with redirect_stdout(output):
                table = build_sound_exposure_table(round_data)
        finally:
            if old is None:
                os.environ.pop("WALL_VIEWER_PROFILE", None)
            else:
                os.environ["WALL_VIEWER_PROFILE"] = old

        self.assertTrue(table.empty)
        rendered = output.getvalue()
        self.assertIn("movement_pairs_total=1", rendered)
        self.assertIn("movement_pairs_skipped_by_bbox=1", rendered)
        self.assertIn("movement_pairs_after_prefilter=0", rendered)

    def test_movement_adaptive_sampling_merges_adjacent_intervals(self) -> None:
        tick_rows: list[dict[str, object]] = []
        for tick in range(100, 132):
            tick_rows.append(_frame(tick=tick, name="source", steamid="s_src", team_num=2, x=0.0, y=0.0))
            tick_rows.append(_frame(tick=tick, name="enemy", steamid="s_enemy", team_num=3, x=10.0, y=0.0))
        ticks = pd.DataFrame(tick_rows)
        inferred_rounds = pd.DataFrame(
            [
                {
                    "inferred_round_id": 1,
                    "start_tick": 100,
                    "end_tick": 131,
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
                    "duration_ticks": 31,
                    "duration_seconds": 31 / 64.0,
                }
            ]
        )
        sound_effects = pd.DataFrame(
            [
                _effect(
                    effect_id="move_merge",
                    emitter_type="continuous",
                    source_type="player",
                    source_id="s_src",
                    start_tick=100,
                    end_tick=131,
                    sound_class="movement",
                    sound_action="locomotion",
                    radius=20.0,
                    raw_source="inferred_movement",
                )
            ]
        )
        round_data = get_round_data(
            ticks=ticks,
            deaths=_empty_with_round_columns(),
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
            sound_effects=sound_effects,
            inferred_rounds=inferred_rounds,
            round_id=1,
            tickrate=64.0,
        )

        table = build_sound_exposure_table(round_data)

        movement_rows = table[table["effect_id"] == "move_merge"]
        self.assertEqual(len(movement_rows), 1)
        self.assertEqual(movement_rows.iloc[0]["start_tick"], 100)
        self.assertEqual(movement_rows.iloc[0]["end_tick"], 131)

    def test_run_sound_exposure_exports_jobs_1_matches_jobs_2_outputs(self) -> None:
        data_dir = make_test_dir()
        sound_exposure.ProcessPoolExecutor = _InlineProcessPoolExecutor
        sound_exposure.as_completed = lambda futures: list(futures)
        tick_rows: list[dict[str, object]] = []
        round_rows: list[dict[str, object]] = []
        sound_rows: list[dict[str, object]] = []
        for round_id, tick in [(1, 100), (2, 200)]:
            tick_rows.extend(
                [
                    {**_frame(tick=tick, name=f"source_{round_id}", steamid=f"s_src_{round_id}", team_num=2, x=0.0, y=0.0), "inferred_round_id": round_id, "inferred_round_tick": 0, "inferred_round_seconds": 0.0},
                    {**_frame(tick=tick, name=f"enemy_{round_id}", steamid=f"s_enemy_{round_id}", team_num=3, x=10.0, y=0.0), "inferred_round_id": round_id, "inferred_round_tick": 0, "inferred_round_seconds": 0.0},
                ]
            )
            round_rows.append(
                {
                    "inferred_round_id": round_id,
                    "start_tick": tick,
                    "end_tick": tick,
                    "n_rows": 0,
                    "n_players": 0,
                    "n_jump_players": 0,
                    "max_jump": None,
                    "median_jump": None,
                    "freeze_start_tick": tick,
                    "live_start_tick": tick,
                    "freeze_end_tick": tick - 1,
                    "freeze_duration_ticks": 0,
                    "freeze_duration_seconds": 0.0,
                    "duration_ticks": 0,
                    "duration_seconds": 0.0,
                }
            )
            sound_rows.append(
                {
                    **_effect(
                        effect_id=f"hurt_{round_id}",
                        emitter_type="impulse",
                        source_type="player",
                        source_id=f"s_src_{round_id}",
                        start_tick=tick,
                        end_tick=tick,
                        sound_class="damage",
                        sound_action="hurt",
                        radius=20.0,
                        raw_source="player_hurt",
                    ),
                    "round_id": round_id,
                }
            )
        pd.DataFrame(tick_rows).to_csv(data_dir / "ticks.csv", index=False)
        _empty_with_round_columns().to_csv(data_dir / "player_death.csv", index=False)
        pd.DataFrame(sound_rows).to_csv(data_dir / "sound_effect.csv", index=False)
        pd.DataFrame(round_rows).to_csv(data_dir / "inferred_rounds.csv", index=False)

        sequential = run_sound_exposure_exports(
            data_dir,
            round_ids=[1, 2],
            table_format="csv",
            jobs=1,
            combine_rounds=False,
        )
        sequential_tables = {result.round_id: pd.read_csv(result.output_path) for result in sequential.round_results}

        parallel = run_sound_exposure_exports(
            data_dir,
            round_ids=[1, 2],
            table_format="csv",
            jobs=2,
            combine_rounds=False,
        )
        parallel_tables = {result.round_id: pd.read_csv(result.output_path) for result in parallel.round_results}

        self.assertEqual(sorted(sequential_tables), sorted(parallel_tables))
        for round_id in sequential_tables:
            pd.testing.assert_frame_equal(sequential_tables[round_id], parallel_tables[round_id])

    def test_handle_sound_exposure_accepts_jobs_and_combines_multi_round_output(self) -> None:
        data_dir = make_test_dir()
        sound_exposure.ProcessPoolExecutor = _InlineProcessPoolExecutor
        sound_exposure.as_completed = lambda futures: list(futures)
        tick_rows: list[dict[str, object]] = []
        round_rows: list[dict[str, object]] = []
        sound_rows: list[dict[str, object]] = []
        for round_id, tick in [(1, 100), (2, 200)]:
            tick_rows.extend(
                [
                    {**_frame(tick=tick, name=f"source_{round_id}", steamid=f"s_src_{round_id}", team_num=2, x=0.0, y=0.0), "inferred_round_id": round_id, "inferred_round_tick": 0, "inferred_round_seconds": 0.0},
                    {**_frame(tick=tick, name=f"enemy_{round_id}", steamid=f"s_enemy_{round_id}", team_num=3, x=10.0, y=0.0), "inferred_round_id": round_id, "inferred_round_tick": 0, "inferred_round_seconds": 0.0},
                ]
            )
            round_rows.append(
                {
                    "inferred_round_id": round_id,
                    "start_tick": tick,
                    "end_tick": tick,
                    "n_rows": 0,
                    "n_players": 0,
                    "n_jump_players": 0,
                    "max_jump": None,
                    "median_jump": None,
                    "freeze_start_tick": tick,
                    "live_start_tick": tick,
                    "freeze_end_tick": tick - 1,
                    "freeze_duration_ticks": 0,
                    "freeze_duration_seconds": 0.0,
                    "duration_ticks": 0,
                    "duration_seconds": 0.0,
                }
            )
            sound_rows.append(
                {
                    **_effect(
                        effect_id=f"hurt_{round_id}",
                        emitter_type="impulse",
                        source_type="player",
                        source_id=f"s_src_{round_id}",
                        start_tick=tick,
                        end_tick=tick,
                        sound_class="damage",
                        sound_action="hurt",
                        radius=20.0,
                        raw_source="player_hurt",
                    ),
                    "round_id": round_id,
                }
            )
        pd.DataFrame(tick_rows).to_csv(data_dir / "ticks.csv", index=False)
        _empty_with_round_columns().to_csv(data_dir / "player_death.csv", index=False)
        pd.DataFrame(sound_rows).to_csv(data_dir / "sound_effect.csv", index=False)
        pd.DataFrame(round_rows).to_csv(data_dir / "inferred_rounds.csv", index=False)

        args = build_sound_exposure_parser().parse_args([str(data_dir), "--round", "1", "2", "--jobs", "2", "--format", "csv"])
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = handle_sound_exposure(args)

        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn("sound_exposure.csv", rendered)
        exported = pd.read_csv(data_dir / "sound_exposure.csv")
        self.assertEqual(sorted(exported["round_id"].unique().tolist()), [1, 2])


if __name__ == "__main__":
    unittest.main()
