from __future__ import annotations

import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import uuid

import pandas as pd

from wall.dataset.index import DatasetIndex
from wall.visibility.context import MapVisibilityContext


TEST_TMP_ROOT = Path("F:/wall/tmp_test_dataset_index")


def make_test_dir() -> Path:
    TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = TEST_TMP_ROOT / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


class DatasetIndexTests(unittest.TestCase):
    def tearDown(self) -> None:
        shutil.rmtree(TEST_TMP_ROOT, ignore_errors=True)

    def test_from_data_dir_loads_only_minimal_startup_data(self) -> None:
        data_dir = make_test_dir()
        inferred_rounds = pd.DataFrame([{"inferred_round_id": 2}, {"inferred_round_id": 1}])
        inferred_rounds.to_parquet(data_dir / "inferred_rounds.parquet", index=False)
        pd.DataFrame([{"tick": 1, "name": "p1"}]).to_parquet(data_dir / "ticks.parquet", index=False)
        (data_dir / "metadata.json").write_text(json.dumps({"derived": {"map_name": "de_dust2"}}), encoding="utf-8")
        (data_dir / "visibility.parquet").write_bytes(b"stub")

        original_read_parquet = pd.read_parquet
        calls: list[str] = []

        def _recording_read_parquet(path, *args, **kwargs):
            calls.append(Path(path).name)
            return original_read_parquet(path, *args, **kwargs)

        with patch("pandas.read_parquet", side_effect=_recording_read_parquet):
            index = DatasetIndex.from_data_dir(data_dir)

        self.assertEqual(calls, ["inferred_rounds.parquet"])
        self.assertEqual(index.round_ids, [1, 2])
        self.assertEqual(index.map_name, "de_dust2")
        self.assertEqual(index.table_paths["ticks"], data_dir / "ticks.parquet")
        self.assertTrue(index.artifacts["visibility_parquet"])

    def test_build_round_data_reads_ticks_with_round_filter_and_projection(self) -> None:
        data_dir = make_test_dir()
        pd.DataFrame(
            [
                {"inferred_round_id": 1, "start_tick": 100, "end_tick": 101},
                {"inferred_round_id": 2, "start_tick": 200, "end_tick": 201},
            ]
        ).to_parquet(data_dir / "inferred_rounds.parquet", index=False)
        pd.DataFrame(
            [
                {
                    "tick": 100,
                    "inferred_round_id": 1,
                    "inferred_round_tick": 0,
                    "inferred_round_seconds": 0.0,
                    "name": "p1",
                    "steamid": "1",
                    "active_weapon_name": "ak47",
                    "has_defuser": 0,
                    "X": 1.0,
                    "Y": 2.0,
                    "Z": 3.0,
                    "yaw": 90.0,
                    "pitch": 0.0,
                    "team_num": 2,
                    "health": 100,
                    "ducking": 0,
                    "is_airborne": 0,
                    "velocity_X": 0.0,
                    "velocity_Y": 0.0,
                    "velocity_Z": 0.0,
                    "unused_big_column": "ignore-me",
                },
                {
                    "tick": 200,
                    "inferred_round_id": 2,
                    "inferred_round_tick": 0,
                    "inferred_round_seconds": 0.0,
                    "name": "p2",
                    "steamid": "2",
                    "active_weapon_name": "m4a1",
                    "has_defuser": 1,
                    "X": 4.0,
                    "Y": 5.0,
                    "Z": 6.0,
                    "yaw": 180.0,
                    "pitch": 0.0,
                    "team_num": 3,
                    "health": 100,
                    "ducking": 0,
                    "is_airborne": 0,
                    "velocity_X": 0.0,
                    "velocity_Y": 0.0,
                    "velocity_Z": 0.0,
                    "unused_big_column": "ignore-me-too",
                },
            ]
        ).to_parquet(data_dir / "ticks.parquet", index=False)
        pd.DataFrame(
            [
                {
                    "tick": 100,
                    "inferred_round_id": 1,
                    "inferred_round_tick": 0,
                    "inferred_round_seconds": 0.0,
                    "user_name": "p1",
                }
            ]
        ).to_parquet(data_dir / "player_death.parquet", index=False)

        index = DatasetIndex.from_data_dir(data_dir)
        original_read_parquet = pd.read_parquet
        parquet_calls: list[tuple[str, dict]] = []

        def _recording_read_parquet(path, *args, **kwargs):
            parquet_calls.append((Path(path).name, dict(kwargs)))
            return original_read_parquet(path, *args, **kwargs)

        with (
            patch("pandas.read_parquet", side_effect=_recording_read_parquet),
            patch("wall.dataset.index.get_round_data") as get_round_data,
        ):
            get_round_data.return_value = "round-data"
            result = index.build_round_data(2, tickrate=64.0)

        self.assertEqual(result, "round-data")
        ticks_call = next(kwargs for name, kwargs in parquet_calls if name == "ticks.parquet")
        self.assertEqual(ticks_call["filters"], [("inferred_round_id", "==", 2)])
        self.assertNotIn("unused_big_column", ticks_call["columns"])
        ticks_df = get_round_data.call_args.kwargs["ticks"]
        self.assertEqual(ticks_df["inferred_round_id"].astype(int).unique().tolist(), [2])
        self.assertEqual(ticks_df["tick"].astype(int).tolist(), [200])

    def test_build_round_data_uses_segment_artifact_without_grenades_table(self) -> None:
        data_dir = make_test_dir()
        pd.DataFrame([{"inferred_round_id": 1, "start_tick": 100, "end_tick": 102}]).to_parquet(
            data_dir / "inferred_rounds.parquet",
            index=False,
        )
        pd.DataFrame(
            [
                {
                    "tick": 100,
                    "inferred_round_id": 1,
                    "inferred_round_tick": 0,
                    "inferred_round_seconds": 0.0,
                    "name": "p1",
                    "steamid": "1",
                    "active_weapon_name": "ak47",
                    "has_defuser": 0,
                    "X": 1.0,
                    "Y": 2.0,
                    "Z": 3.0,
                    "yaw": 90.0,
                    "pitch": 0.0,
                    "team_num": 2,
                    "health": 100,
                    "ducking": 0,
                    "is_airborne": 0,
                    "velocity_X": 0.0,
                    "velocity_Y": 0.0,
                    "velocity_Z": 0.0,
                }
            ]
        ).to_parquet(data_dir / "ticks.parquet", index=False)
        pd.DataFrame(
            [{"tick": 100, "inferred_round_id": 1, "inferred_round_tick": 0, "inferred_round_seconds": 0.0, "user_name": "p1"}]
        ).to_parquet(data_dir / "player_death.parquet", index=False)
        pd.DataFrame(
            [
                {
                    "round_id": 1,
                    "grenade_id": "7",
                    "grenade_type": "CSmokeGrenadeProjectile",
                    "segment_index": 0,
                    "start_tick": 100,
                    "end_tick": 102,
                    "start_x": 0.0,
                    "start_y": 0.0,
                    "start_z": 0.0,
                    "end_x": 10.0,
                    "end_y": 10.0,
                    "end_z": 0.0,
                }
            ]
        ).to_parquet(data_dir / "grenade_trajectory_segments.parquet", index=False)

        index = DatasetIndex.from_data_dir(data_dir)

        with patch("wall.dataset.index.get_round_data") as get_round_data:
            get_round_data.return_value = "round-data"
            result = index.build_round_data(1, tickrate=64.0)

        self.assertEqual(result, "round-data")
        self.assertNotIn("grenades", index.table_paths)
        segments_df = get_round_data.call_args.kwargs["grenade_trajectory_segments"]
        self.assertEqual(segments_df["grenade_id"].tolist(), ["7"])

    def test_build_demo_hud_numbers_reads_only_requested_round(self) -> None:
        data_dir = make_test_dir()
        pd.DataFrame(
            [
                {"inferred_round_id": 1, "start_tick": 100, "end_tick": 101},
                {"inferred_round_id": 2, "start_tick": 200, "end_tick": 201},
            ]
        ).to_parquet(data_dir / "inferred_rounds.parquet", index=False)
        pd.DataFrame(
            [
                {"tick": 100, "inferred_round_id": 1, "name": "t1", "team_num": 2, "unused": "x"},
                {"tick": 101, "inferred_round_id": 1, "name": "ct1", "team_num": 3, "unused": "y"},
                {"tick": 200, "inferred_round_id": 2, "name": "t2", "team_num": 2, "unused": "z"},
                {"tick": 201, "inferred_round_id": 2, "name": "coach", "team_num": 0, "unused": "w"},
            ]
        ).to_parquet(data_dir / "ticks.parquet", index=False)

        index = DatasetIndex.from_data_dir(data_dir)
        original_read_parquet = pd.read_parquet
        parquet_calls: list[tuple[str, dict]] = []

        def _recording_read_parquet(path, *args, **kwargs):
            parquet_calls.append((Path(path).name, dict(kwargs)))
            return original_read_parquet(path, *args, **kwargs)

        with patch("pandas.read_parquet", side_effect=_recording_read_parquet):
            player_numbers = index.build_demo_hud_numbers(2)

        ticks_call = next(kwargs for name, kwargs in parquet_calls if name == "ticks.parquet")
        self.assertEqual(ticks_call["filters"], [("inferred_round_id", "==", 2)])
        self.assertEqual(ticks_call["columns"], ["tick", "inferred_round_id", "name", "team_num"])
        self.assertEqual(player_numbers["t2"], 1)
        self.assertEqual(player_numbers["coach"], 11)
        self.assertNotIn("ct1", player_numbers)

    def test_build_round_data_uses_precomputed_visibility_mode_without_geometry_checker(self) -> None:
        data_dir = make_test_dir()
        pd.DataFrame([{"inferred_round_id": 1}]).to_parquet(data_dir / "inferred_rounds.parquet", index=False)
        pd.DataFrame(
            [
                {
                    "tick": 100,
                    "inferred_round_id": 1,
                    "inferred_round_tick": 0,
                    "inferred_round_seconds": 0.0,
                    "name": "p1",
                    "steamid": "1",
                    "active_weapon_name": "ak47",
                    "has_defuser": 0,
                    "X": 1.0,
                    "Y": 2.0,
                    "Z": 3.0,
                    "yaw": 90.0,
                    "pitch": 0.0,
                    "team_num": 2,
                    "health": 100,
                    "ducking": 0,
                    "is_airborne": 0,
                    "velocity_X": 0.0,
                    "velocity_Y": 0.0,
                    "velocity_Z": 0.0,
                }
            ]
        ).to_parquet(data_dir / "ticks.parquet", index=False)
        pd.DataFrame(
            [{"tick": 100, "inferred_round_id": 1, "inferred_round_tick": 0, "inferred_round_seconds": 0.0, "user_name": "p1"}]
        ).to_parquet(data_dir / "player_death.parquet", index=False)
        (data_dir / "visibility.parquet").write_bytes(b"stub")

        index = DatasetIndex.from_data_dir(data_dir)

        with (
            patch.object(MapVisibilityContext, "for_map") as for_map,
            patch("wall.dataset.index.get_round_data") as get_round_data,
        ):
            get_round_data.return_value = "round-data"
            result = index.build_round_data(1, tickrate=64.0)

        self.assertEqual(result, "round-data")
        for_map.assert_not_called()
        self.assertIsNone(get_round_data.call_args.kwargs["visibility_checker"])

    def test_build_round_data_uses_unavailable_visibility_mode_without_geometry_checker(self) -> None:
        data_dir = make_test_dir()
        pd.DataFrame([{"inferred_round_id": 1}]).to_parquet(data_dir / "inferred_rounds.parquet", index=False)
        pd.DataFrame(
            [
                {
                    "tick": 100,
                    "inferred_round_id": 1,
                    "inferred_round_tick": 0,
                    "inferred_round_seconds": 0.0,
                    "name": "p1",
                    "steamid": "1",
                    "active_weapon_name": "ak47",
                    "has_defuser": 0,
                    "X": 1.0,
                    "Y": 2.0,
                    "Z": 3.0,
                    "yaw": 90.0,
                    "pitch": 0.0,
                    "team_num": 2,
                    "health": 100,
                    "ducking": 0,
                    "is_airborne": 0,
                    "velocity_X": 0.0,
                    "velocity_Y": 0.0,
                    "velocity_Z": 0.0,
                }
            ]
        ).to_parquet(data_dir / "ticks.parquet", index=False)
        pd.DataFrame(
            [{"tick": 100, "inferred_round_id": 1, "inferred_round_tick": 0, "inferred_round_seconds": 0.0, "user_name": "p1"}]
        ).to_parquet(data_dir / "player_death.parquet", index=False)

        index = DatasetIndex.from_data_dir(data_dir)

        with (
            patch.object(MapVisibilityContext, "for_map") as for_map,
            patch("wall.dataset.index.get_round_data") as get_round_data,
        ):
            get_round_data.return_value = "round-data"
            result = index.build_round_data(1, tickrate=64.0)

        self.assertEqual(result, "round-data")
        for_map.assert_not_called()
        self.assertIsNone(get_round_data.call_args.kwargs["visibility_checker"])


if __name__ == "__main__":
    unittest.main()
