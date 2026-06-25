from __future__ import annotations

from contextlib import redirect_stdout
import io
import shutil
from pathlib import Path
import unittest
import uuid

import pandas as pd

import wall.analysis.visibility_export as visibility_export
import wall.visibility.export as visibility_export_impl
from wall.analysis.visibility_export import (
    build_visibility_summary_table,
    build_visibility_table,
    build_visibility_result_set,
    export_visibility_table,
    VisibilityResultRow,
    profile_los_overlap,
    run_visibility_export,
    run_visibility_exports,
)
from wall.cli import build_visibility_parser, handle_visibility
from wall.dataset.rounds import get_round_data
from wall.domain.visibility_profile import VisibilityProfile
from wall.visibility.context import MapVisibilityContext
from wall.visibility.dataset import MatchDataset


TEST_TMP_ROOT = Path("F:/wall/tmp_test_visibility_export")


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

    def map(self, fn, iterable):
        return [fn(item) for item in iterable]

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


def _inferred_rounds_row(
    *,
    round_id: int = 1,
    start_tick: int = 100,
    end_tick: int = 102,
    freeze_start_tick: int = 100,
    freeze_end_tick: int = 100,
    live_start_tick: int = 101,
) -> dict[str, object]:
    return {
        "inferred_round_id": round_id,
        "start_tick": start_tick,
        "end_tick": end_tick,
        "n_rows": 0,
        "n_players": 0,
        "n_jump_players": 0,
        "max_jump": None,
        "median_jump": None,
        "freeze_start_tick": freeze_start_tick,
        "live_start_tick": live_start_tick,
        "freeze_end_tick": freeze_end_tick,
        "freeze_duration_ticks": live_start_tick - freeze_start_tick,
        "freeze_duration_seconds": (live_start_tick - freeze_start_tick) / 64.0,
        "duration_ticks": end_tick - start_tick,
        "duration_seconds": (end_tick - start_tick) / 64.0,
    }


def _round_data():
    ticks = pd.DataFrame(
        [
            _frame(tick=100, name="observer", steamid="s1", team_num=2, x=0.0, y=0.0, yaw=0.0),
            _frame(tick=100, name="enemy_front", steamid="s2", team_num=3, x=10.0, y=0.0, yaw=180.0),
            _frame(tick=100, name="enemy_side", steamid="s3", team_num=3, x=0.0, y=10.0, yaw=180.0),
            _frame(tick=101, name="observer", steamid="s1", team_num=2, x=0.0, y=0.0, yaw=0.0),
            _frame(tick=101, name="enemy_front", steamid="s2", team_num=3, x=10.0, y=0.0, yaw=180.0),
            _frame(tick=101, name="enemy_side", steamid="s3", team_num=3, x=0.0, y=10.0, yaw=180.0),
        ]
    )
    return get_round_data(
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
        sound_events=pd.DataFrame(),
        inferred_rounds=pd.DataFrame([_inferred_rounds_row(end_tick=101)]),
        round_id=1,
        tickrate=64.0,
    )


def _write_visibility_dataset(data_dir: Path, *, rounds: list[dict[str, int]]) -> None:
    tick_rows: list[dict[str, object]] = []
    inferred_round_rows: list[dict[str, object]] = []
    for round_spec in rounds:
        round_id = int(round_spec["round_id"])
        tick = int(round_spec["tick"])
        inferred_round_rows.append(
            _inferred_rounds_row(
                round_id=round_id,
                start_tick=tick,
                end_tick=tick,
                freeze_start_tick=tick,
                freeze_end_tick=tick - 1,
                live_start_tick=tick,
            )
        )
        tick_rows.extend(
            [
                _frame(
                    tick=tick,
                    name=f"observer_{round_id}",
                    steamid=f"s_obs_{round_id}",
                    team_num=2,
                    x=0.0,
                    y=0.0,
                    yaw=0.0,
                    health=100,
                ),
                _frame(
                    tick=tick,
                    name=f"enemy_front_{round_id}",
                    steamid=f"s_enemy_{round_id}",
                    team_num=3,
                    x=10.0,
                    y=0.0,
                    yaw=180.0,
                    health=100,
                ),
            ]
        )
        tick_rows[-1]["inferred_round_id"] = round_id
        tick_rows[-2]["inferred_round_id"] = round_id
        tick_rows[-1]["inferred_round_tick"] = 0
        tick_rows[-2]["inferred_round_tick"] = 0
        tick_rows[-1]["inferred_round_seconds"] = 0.0
        tick_rows[-2]["inferred_round_seconds"] = 0.0
    pd.DataFrame(tick_rows).to_csv(data_dir / "ticks.csv", index=False)
    _empty_with_round_columns().to_csv(data_dir / "player_death.csv", index=False)
    pd.DataFrame(inferred_round_rows).to_csv(data_dir / "inferred_rounds.csv", index=False)


class VisibilityExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_process_pool_executor = visibility_export.ProcessPoolExecutor
        self._original_as_completed = visibility_export.as_completed

    def tearDown(self) -> None:
        visibility_export.ProcessPoolExecutor = self._original_process_pool_executor
        visibility_export.as_completed = self._original_as_completed

    def test_build_visibility_table_respects_filters(self) -> None:
        table = build_visibility_table(
            _round_data(),
            observer="observer",
            tick=100,
            only_visible=True,
        )

        self.assertEqual(table["observer"].tolist(), ["observer"])
        self.assertEqual(table["target"].tolist(), ["enemy_front"])
        self.assertEqual(table["start_tick"].tolist(), [100])
        self.assertEqual(table["end_tick"].tolist(), [100])
        self.assertEqual(table["state"].tolist(), ["UNKNOWN"])

    def test_build_visibility_table_samples_ticks(self) -> None:
        ticks = pd.DataFrame(
            [
                _frame(tick=100, name="observer", steamid="s1", team_num=2, x=0.0, y=0.0, yaw=0.0),
                _frame(tick=100, name="enemy_front", steamid="s2", team_num=3, x=10.0, y=0.0, yaw=180.0),
                _frame(tick=101, name="observer", steamid="s1", team_num=2, x=0.0, y=0.0, yaw=0.0),
                _frame(tick=101, name="enemy_front", steamid="s2", team_num=3, x=10.0, y=0.0, yaw=180.0),
                _frame(tick=102, name="observer", steamid="s1", team_num=2, x=0.0, y=0.0, yaw=0.0),
                _frame(tick=102, name="enemy_front", steamid="s2", team_num=3, x=10.0, y=0.0, yaw=180.0),
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
            sound_events=pd.DataFrame(),
            inferred_rounds=pd.DataFrame([_inferred_rounds_row(end_tick=102, live_start_tick=101)]),
            round_id=1,
            tickrate=64.0,
        )
        table = build_visibility_table(round_data, tick_step=2)

        self.assertEqual(sorted(table["start_tick"].unique().tolist()), [102])

    def test_build_visibility_summary_table_aggregates_visible_targets(self) -> None:
        table = build_visibility_summary_table(
            _round_data(),
            observer="observer",
            tick=101,
        )

        self.assertEqual(table["observer"].tolist(), ["observer"])
        self.assertEqual(table["visible_targets"].tolist(), ["enemy_front"])
        self.assertEqual(table["visible_count"].tolist(), [1])

    def test_build_visibility_summary_table_drops_rows_with_zero_fov_count(self) -> None:
        table = build_visibility_summary_table(
            _round_data(),
            observer="enemy_side",
            tick=100,
        )

        self.assertTrue(table.empty)

    def test_build_visibility_table_explicit_tick_can_include_freeze_time(self) -> None:
        table = build_visibility_table(
            _round_data(),
            observer="observer",
            tick=100,
        )

        self.assertEqual(sorted(table["start_tick"].unique().tolist()), [100])

    def test_export_visibility_table_writes_csv(self) -> None:
        data_dir = make_test_dir()
        try:
            ticks = pd.DataFrame(
                [
                    _frame(tick=100, name="observer", steamid="s1", team_num=2, x=0.0, y=0.0, yaw=0.0),
                    _frame(tick=100, name="enemy_front", steamid="s2", team_num=3, x=10.0, y=0.0, yaw=180.0),
                ]
            )
            ticks.to_csv(data_dir / "ticks.csv", index=False)
            _empty_with_round_columns().to_csv(data_dir / "player_death.csv", index=False)
            pd.DataFrame([_inferred_rounds_row(end_tick=100, live_start_tick=100, freeze_end_tick=99)]).to_csv(
                data_dir / "inferred_rounds.csv",
                index=False,
            )
            (data_dir / "metadata.json").write_text('{"derived":{"map_name":"de_dust2"}}', encoding="utf-8")

            output_path = export_visibility_table(
                data_dir,
                round_id=1,
                observer="observer",
                tick=100,
                only_visible=True,
                tickrate=64.0,
                table_format="csv",
            )

            self.assertTrue(output_path.exists())
            exported = pd.read_csv(output_path)
            self.assertEqual(exported["target"].tolist(), ["enemy_front"])
            self.assertIn("start_tick", exported.columns)
            self.assertIn("distance_mean", exported.columns)
            self.assertIn("state", exported.columns)
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)

    def test_export_visibility_summary_writes_csv(self) -> None:
        data_dir = make_test_dir()
        try:
            ticks = pd.DataFrame(
                [
                    _frame(tick=100, name="observer", steamid="s1", team_num=2, x=0.0, y=0.0, yaw=0.0),
                    _frame(tick=100, name="enemy_front", steamid="s2", team_num=3, x=10.0, y=0.0, yaw=180.0),
                ]
            )
            ticks.to_csv(data_dir / "ticks.csv", index=False)
            _empty_with_round_columns().to_csv(data_dir / "player_death.csv", index=False)
            pd.DataFrame([_inferred_rounds_row(end_tick=100, live_start_tick=100, freeze_end_tick=99)]).to_csv(
                data_dir / "inferred_rounds.csv",
                index=False,
            )
            (data_dir / "metadata.json").write_text('{"derived":{"map_name":"de_dust2"}}', encoding="utf-8")

            output_path = export_visibility_table(
                data_dir,
                round_id=1,
                observer="observer",
                tick=100,
                summary=True,
                tickrate=64.0,
                table_format="csv",
            )

            self.assertTrue(output_path.exists())
            exported = pd.read_csv(output_path)
            self.assertEqual(exported["visible_targets"].tolist(), ["enemy_front"])
            self.assertIn("visible_count", exported.columns)
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)

    def test_run_visibility_export_can_collect_profile(self) -> None:
        data_dir = make_test_dir()
        try:
            ticks = pd.DataFrame(
                [
                    _frame(tick=100, name="observer", steamid="s1", team_num=2, x=0.0, y=0.0, yaw=0.0),
                    _frame(tick=100, name="enemy_front", steamid="s2", team_num=3, x=10.0, y=0.0, yaw=180.0),
                ]
            )
            ticks.to_csv(data_dir / "ticks.csv", index=False)
            _empty_with_round_columns().to_csv(data_dir / "player_death.csv", index=False)
            pd.DataFrame([_inferred_rounds_row(end_tick=100, live_start_tick=100, freeze_end_tick=99)]).to_csv(
                data_dir / "inferred_rounds.csv",
                index=False,
            )

            result = run_visibility_export(
                data_dir,
                round_id=1,
                observer="observer",
                tick=100,
                summary=True,
                tickrate=64.0,
                table_format="csv",
                profile_visibility=True,
            )

            self.assertTrue(result.output_path.exists())
            self.assertIsNotNone(result.profile)
            assert result.profile is not None
            self.assertEqual(result.profile.total_ticks_visited, 1)
            self.assertEqual(result.profile.sampled_ticks_visited, 1)
            self.assertGreaterEqual(result.profile.raw_observer_target_pairs, 1)
            self.assertEqual(
                result.profile.pairs_sent_to_checker,
                result.profile.visible_pairs + result.profile.invisible_pairs,
            )
            self.assertIn("summary", result.profile.los_requests_by_source)
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)

    def test_run_visibility_export_accepts_match_dataset_input(self) -> None:
        data_dir = make_test_dir()
        try:
            ticks = pd.DataFrame(
                [
                    _frame(tick=100, name="observer", steamid="s1", team_num=2, x=0.0, y=0.0, yaw=0.0),
                    _frame(tick=100, name="enemy_front", steamid="s2", team_num=3, x=10.0, y=0.0, yaw=180.0),
                ]
            )
            ticks.to_csv(data_dir / "ticks.csv", index=False)
            _empty_with_round_columns().to_csv(data_dir / "player_death.csv", index=False)
            pd.DataFrame([_inferred_rounds_row(end_tick=100, live_start_tick=100, freeze_end_tick=99)]).to_csv(
                data_dir / "inferred_rounds.csv",
                index=False,
            )

            dataset = MatchDataset.from_data_dir(data_dir)
            result = run_visibility_export(
                data_dir,
                round_id=1,
                observer="observer",
                tick=100,
                tickrate=64.0,
                table_format="csv",
                dataset=dataset,
            )

            self.assertTrue(result.output_path.exists())
            exported = pd.read_csv(result.output_path)
            self.assertEqual(exported["target"].tolist(), ["enemy_front"])
            self.assertIn("state", exported.columns)
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)

    def test_profile_los_overlap_reports_shared_keys(self) -> None:
        data_dir = make_test_dir()
        try:
            ticks = pd.DataFrame(
                [
                    _frame(tick=100, name="observer", steamid="s1", team_num=2, x=0.0, y=0.0, yaw=0.0),
                    _frame(tick=100, name="enemy_front", steamid="s2", team_num=3, x=10.0, y=0.0, yaw=180.0),
                ]
            )
            ticks.to_csv(data_dir / "ticks.csv", index=False)
            _empty_with_round_columns().to_csv(data_dir / "player_death.csv", index=False)
            pd.DataFrame([_inferred_rounds_row(end_tick=100, live_start_tick=100, freeze_end_tick=99)]).to_csv(
                data_dir / "inferred_rounds.csv",
                index=False,
            )
            (data_dir / "metadata.json").write_text('{"derived":{"map_name":"de_dust2"}}', encoding="utf-8")

            overlap = profile_los_overlap(
                data_dir,
                round_id=1,
                observer="observer",
                tick=100,
                tickrate=64.0,
            )

            self.assertGreaterEqual(overlap.summary_unique_keys, 1)
            self.assertGreaterEqual(overlap.pair_unique_keys, 1)
            self.assertGreaterEqual(overlap.shared_keys, 1)
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)

    def test_unified_result_set_summary_matches_expected_output(self) -> None:
        result_set = build_visibility_result_set(_round_data(), observer="observer", tick=101, output_kind="summary")
        table = visibility_export._result_rows_to_summary_table(result_set, only_visible=False)

        self.assertEqual(table["observer"].tolist(), ["observer"])
        self.assertEqual(table["visible_targets"].tolist(), ["enemy_front"])
        self.assertEqual(table["visible_count"].tolist(), [1])

    def test_unified_result_set_pair_matches_expected_output(self) -> None:
        result_set = build_visibility_result_set(_round_data(), observer="observer", tick=100, output_kind="pair")
        table = visibility_export._result_rows_to_pair_table(result_set, only_visible=True)

        self.assertEqual(
            table.columns.tolist(),
            [
                "tick",
                "round_id",
                "observer",
                "target",
                "observer_key",
                "target_key",
                "distance",
                "relative_yaw_deg",
                "in_fov",
                "has_los",
                "is_visible",
            ],
        )
        self.assertEqual(table["observer"].tolist(), ["observer"])
        self.assertEqual(table["target"].tolist(), ["enemy_front"])
        self.assertEqual(table["in_fov"].tolist(), [True])
        self.assertEqual(table["is_visible"].tolist(), [True])

    def test_both_mode_does_not_double_checker_calls(self) -> None:
        round_data = _round_data()

        class FakeChecker:
            def __init__(self) -> None:
                self.calls = 0

            def is_visible(self, start, end):
                self.calls += 1
                return True

        checker = FakeChecker()
        profile = VisibilityProfile(output_kind="both")
        round_data.visibility_timeline.visibility_checker = checker
        round_data.visibility_timeline.visibility_profile = profile

        result_set = build_visibility_result_set(round_data, observer="observer", tick=100, output_kind="both")
        pair_calls = checker.calls
        _ = visibility_export._result_rows_to_pair_table(result_set, only_visible=False)
        _ = visibility_export._result_rows_to_summary_table(result_set, only_visible=False)

        self.assertEqual(pair_calls, checker.calls)
        self.assertEqual(profile.checker_is_visible_call_count, checker.calls)

    def test_result_set_writer_shape_stays_stable(self) -> None:
        result_set = build_visibility_result_set(_round_data(), observer="observer", tick=100, output_kind="both")

        self.assertEqual(
            set(result_set.rows[0].__dict__.keys()),
            {
                "tick",
                "round_id",
                "observer",
                "target",
                "observer_key",
                "target_key",
                "observer_team",
                "target_team",
                "observer_x",
                "observer_y",
                "observer_z",
                "target_x",
                "target_y",
                "target_z",
                "observer_yaw",
                "distance",
                "relative_yaw_deg",
                "in_fov",
                "has_los",
                "is_visible",
            },
        )

    def test_interval_writer_merges_same_state_and_aggregates_metrics(self) -> None:
        result_set = visibility_export.VisibilityResultSet(
            round_id=1,
            output_kind="interval",
            rows=(
                VisibilityResultRow(100, 1, "obs", "tgt", "s_obs", "s_tgt", 2, 3, None, None, None, None, None, None, None, 10.0, -20.0, True, True, True),
                VisibilityResultRow(101, 1, "obs", "tgt", "s_obs", "s_tgt", 2, 3, None, None, None, None, None, None, None, 20.0, 10.0, True, True, True),
                VisibilityResultRow(102, 1, "obs", "tgt", "s_obs", "s_tgt", 2, 3, None, None, None, None, None, None, None, 15.0, -30.0, True, True, True),
            ),
        )

        table = visibility_export_impl._result_rows_to_interval_table(
            result_set,
            tick_to_seconds={100: 0.0, 101: 1.0, 102: 2.0},
            only_visible=False,
        )

        self.assertEqual(len(table), 1)
        row = table.iloc[0]
        self.assertEqual(row["start_tick"], 100)
        self.assertEqual(row["end_tick"], 102)
        self.assertEqual(row["sample_count"], 3)
        self.assertEqual(row["state"], "VISIBLE")
        self.assertEqual(row["distance_start"], 10.0)
        self.assertEqual(row["distance_end"], 15.0)
        self.assertEqual(row["distance_min"], 10.0)
        self.assertEqual(row["distance_max"], 20.0)
        self.assertEqual(row["distance_mean"], 15.0)
        self.assertEqual(row["relative_yaw_start"], -20.0)
        self.assertEqual(row["relative_yaw_end"], -30.0)
        self.assertEqual(row["relative_yaw_min"], -30.0)
        self.assertEqual(row["relative_yaw_max"], 10.0)
        self.assertEqual(row["relative_yaw_abs_min"], 10.0)
        self.assertEqual(row["relative_yaw_abs_mean"], 20.0)
        self.assertEqual(row["relative_yaw_abs_max"], 30.0)

    def test_interval_writer_splits_on_state_changes_and_preserves_out_of_fov_null_los(self) -> None:
        result_set = visibility_export.VisibilityResultSet(
            round_id=1,
            output_kind="interval",
            rows=(
                VisibilityResultRow(100, 1, "obs", "tgt", "s_obs", "s_tgt", 2, 3, None, None, None, None, None, None, None, 10.0, 0.0, False, None, False),
                VisibilityResultRow(101, 1, "obs", "tgt", "s_obs", "s_tgt", 2, 3, None, None, None, None, None, None, None, 11.0, 1.0, False, None, False),
                VisibilityResultRow(102, 1, "obs", "tgt", "s_obs", "s_tgt", 2, 3, None, None, None, None, None, None, None, 12.0, 2.0, True, False, False),
                VisibilityResultRow(103, 1, "obs", "tgt", "s_obs", "s_tgt", 2, 3, None, None, None, None, None, None, None, 13.0, 3.0, True, True, True),
            ),
        )

        table = visibility_export_impl._result_rows_to_interval_table(
            result_set,
            tick_to_seconds={100: 0.0, 101: 1.0, 102: 2.0, 103: 3.0},
            only_visible=False,
        )

        self.assertEqual(table["state"].tolist(), ["OUT_OF_FOV", "IN_FOV_BLOCKED", "VISIBLE"])
        self.assertTrue(pd.isna(table.iloc[0]["has_los"]))
        self.assertEqual(table.iloc[0]["start_tick"], 100)
        self.assertEqual(table.iloc[0]["end_tick"], 101)
        self.assertEqual(table.iloc[1]["start_tick"], 102)
        self.assertEqual(table.iloc[2]["start_tick"], 103)

    def test_run_visibility_exports_centralizes_map_context_for_single_dataset(self) -> None:
        data_dir = make_test_dir()
        original_for_map = MapVisibilityContext.__dict__["for_map"]
        calls: list[str | None] = []

        def _recording_for_map(cls, map_name, *, visibility_profile=None):
            calls.append(map_name)
            return original_for_map.__func__(cls, map_name, visibility_profile=visibility_profile)

        try:
            _write_visibility_dataset(
                data_dir,
                rounds=[{"round_id": 1, "tick": 100}, {"round_id": 2, "tick": 200}],
            )
            (data_dir / "metadata.json").write_text('{"derived":{"map_name":"de_dust2"}}', encoding="utf-8")
            MapVisibilityContext.for_map = classmethod(_recording_for_map)

            result = run_visibility_exports(
                data_dir,
                round_ids=[1, 2],
                output_kind="interval",
                tickrate=64.0,
                table_format="csv",
                jobs=1,
                combine_rounds=True,
            )

            self.assertIsNotNone(result.output_paths)
            self.assertEqual(calls, ["de_dust2"])
        finally:
            MapVisibilityContext.for_map = original_for_map
            shutil.rmtree(data_dir, ignore_errors=True)

    def test_run_visibility_exports_jobs_1_matches_jobs_2_outputs(self) -> None:
        data_dir = make_test_dir()
        try:
            visibility_export.ProcessPoolExecutor = _InlineProcessPoolExecutor
            visibility_export.as_completed = lambda futures: list(futures)
            _write_visibility_dataset(
                data_dir,
                rounds=[{"round_id": 1, "tick": 100}, {"round_id": 2, "tick": 200}],
            )
            sequential = run_visibility_exports(
                data_dir,
                round_ids=[1, 2],
                output_kind="interval",
                tickrate=64.0,
                table_format="csv",
                profile_visibility=True,
                jobs=1,
                combine_rounds=False,
            )
            sequential_tables = {
                result.round_id: pd.read_csv(result.output_path)
                for result in sequential.round_results
            }

            parallel = run_visibility_exports(
                data_dir,
                round_ids=[1, 2],
                output_kind="interval",
                tickrate=64.0,
                table_format="csv",
                profile_visibility=True,
                jobs=2,
                combine_rounds=False,
            )
            parallel_tables = {
                result.round_id: pd.read_csv(result.output_path)
                for result in parallel.round_results
            }

            self.assertEqual(sorted(sequential_tables), sorted(parallel_tables))
            for round_id in sequential_tables:
                pd.testing.assert_frame_equal(sequential_tables[round_id], parallel_tables[round_id])
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)

    def test_run_visibility_exports_parallel_profile_tracks_workers(self) -> None:
        data_dir = make_test_dir()
        try:
            visibility_export.ProcessPoolExecutor = _InlineProcessPoolExecutor
            visibility_export.as_completed = lambda futures: list(futures)
            _write_visibility_dataset(
                data_dir,
                rounds=[{"round_id": 1, "tick": 100}, {"round_id": 2, "tick": 200}],
            )
            result = run_visibility_exports(
                data_dir,
                round_ids=[1, 2],
                output_kind="interval",
                tickrate=64.0,
                table_format="csv",
                profile_visibility=True,
                jobs=2,
            )

            self.assertIsNotNone(result.aggregate_profile)
            assert result.aggregate_profile is not None
            self.assertEqual(result.aggregate_profile.jobs, 2)
            self.assertEqual(result.aggregate_profile.worker_count, 2)
            self.assertEqual(len(result.aggregate_profile.per_worker_assigned_rounds), 2)
            self.assertGreaterEqual(result.aggregate_profile.wall_clock_elapsed_seconds, 0.0)
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)

    def test_run_visibility_exports_can_combine_pair_rounds(self) -> None:
        data_dir = make_test_dir()
        try:
            visibility_export.ProcessPoolExecutor = _InlineProcessPoolExecutor
            visibility_export.as_completed = lambda futures: list(futures)
            _write_visibility_dataset(
                data_dir,
                rounds=[{"round_id": 1, "tick": 100}, {"round_id": 2, "tick": 200}],
            )
            result = run_visibility_exports(
                data_dir,
                round_ids=[1, 2],
                output_kind="interval",
                tickrate=64.0,
                table_format="csv",
                jobs=2,
                combine_rounds=True,
            )

            self.assertIsNotNone(result.output_paths)
            assert result.output_paths is not None
            combined_path = result.output_paths["interval"]
            self.assertTrue(combined_path.exists())
            self.assertEqual(combined_path.name, "visibility.csv")
            exported = pd.read_csv(combined_path)
            self.assertEqual(sorted(exported["round_id"].unique().tolist()), [1, 2])
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)

    def test_run_visibility_exports_can_combine_summary_rounds(self) -> None:
        data_dir = make_test_dir()
        try:
            visibility_export.ProcessPoolExecutor = _InlineProcessPoolExecutor
            visibility_export.as_completed = lambda futures: list(futures)
            _write_visibility_dataset(
                data_dir,
                rounds=[{"round_id": 1, "tick": 100}, {"round_id": 2, "tick": 200}],
            )
            result = run_visibility_exports(
                data_dir,
                round_ids=[1, 2],
                output_kind="summary",
                tickrate=64.0,
                table_format="csv",
                jobs=2,
                combine_rounds=True,
            )

            self.assertIsNotNone(result.output_paths)
            assert result.output_paths is not None
            combined_path = result.output_paths["summary"]
            self.assertTrue(combined_path.exists())
            self.assertIn("all_rounds", combined_path.name)
            exported = pd.read_csv(combined_path)
            self.assertEqual(sorted(exported["round_id"].unique().tolist()), [1, 2])
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)

    def test_handle_visibility_parallel_profile_prints_aggregate(self) -> None:
        data_dir = make_test_dir()
        try:
            visibility_export.ProcessPoolExecutor = _InlineProcessPoolExecutor
            visibility_export.as_completed = lambda futures: list(futures)
            _write_visibility_dataset(
                data_dir,
                rounds=[{"round_id": 1, "tick": 100}, {"round_id": 2, "tick": 200}],
            )
            args = build_visibility_parser().parse_args(
                [
                    str(data_dir),
                    "--round",
                    "1",
                    "2",
                    "--jobs",
                    "2",
                    "--profile-visibility",
                    "--format",
                    "csv",
                ]
            )

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = handle_visibility(args)

            self.assertEqual(exit_code, 0)
            rendered = output.getvalue()
            self.assertIn("Visibility Profile Summary", rendered)
            self.assertIn("Concurrency", rendered)
            self.assertIn("worker count", rendered)
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)

    def test_handle_visibility_defaults_to_combined_multi_round_output(self) -> None:
        data_dir = make_test_dir()
        try:
            visibility_export.ProcessPoolExecutor = _InlineProcessPoolExecutor
            visibility_export.as_completed = lambda futures: list(futures)
            _write_visibility_dataset(
                data_dir,
                rounds=[{"round_id": 1, "tick": 100}, {"round_id": 2, "tick": 200}],
            )
            args = build_visibility_parser().parse_args(
                [
                    str(data_dir),
                    "--round",
                    "1",
                    "2",
                    "--format",
                    "csv",
                ]
            )

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = handle_visibility(args)

            self.assertEqual(exit_code, 0)
            rendered = output.getvalue()
            self.assertIn("Visibility Progress", rendered)
            self.assertIn("1/2", rendered)
            self.assertIn("2/2", rendered)
            self.assertIn("visibility.csv", rendered)
            self.assertNotIn("round_01", rendered)
            self.assertNotIn("round_02", rendered)
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
