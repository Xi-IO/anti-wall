from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch
import uuid

import pandas as pd

import wall.visibility.export as visibility_export
from wall.cli import ensure_default_visibility_artifact, handle_playback


TEST_TMP_ROOT = Path("F:/wall/tmp_test_cli_visibility_artifact")


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
        "inferred_round_tick": 0,
        "inferred_round_seconds": 0.0,
    }


def _write_dataset(dataset_dir: Path, *, demo_path: Path | None = None) -> None:
    ticks = pd.DataFrame(
        [
            _frame(tick=100, name="observer", steamid="s1", team_num=2, x=0.0, y=0.0, yaw=0.0),
            _frame(tick=100, name="enemy_front", steamid="s2", team_num=3, x=10.0, y=0.0, yaw=180.0),
        ]
    )
    inferred_rounds = pd.DataFrame(
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
    dataset_dir.mkdir(parents=True, exist_ok=True)
    ticks.to_parquet(dataset_dir / "ticks.parquet", index=False)
    pd.DataFrame(columns=["tick", "inferred_round_id", "inferred_round_tick", "inferred_round_seconds"]).to_parquet(
        dataset_dir / "player_death.parquet",
        index=False,
    )
    inferred_rounds.to_parquet(dataset_dir / "inferred_rounds.parquet", index=False)
    metadata = {"derived": {"map_name": "de_dust2"}}
    if demo_path is not None:
        metadata["demo_file"] = {"path": str(demo_path)}
    (dataset_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")


def _playback_args(source: Path, **overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "source": source,
        "renew": False,
        "no_visibility": False,
        "renew_visibility": False,
        "output_dir": source.parent if source.suffix.lower() == ".dem" else source.parent,
        "table_format": None,
        "ticks_format": None,
        "tick_fields": None,
        "jump_threshold": None,
        "min_jump_players": None,
        "min_gap_ticks": None,
        "round_id": None,
        "map_width": 1200,
        "map_height": 900,
        "fps": 60,
        "frame_step": 1,
        "tickrate": 64.0,
        "verbose": False,
        "profile": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class CliVisibilityArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_process_pool_executor = visibility_export.ProcessPoolExecutor
        self._original_as_completed = visibility_export.as_completed
        visibility_export.ProcessPoolExecutor = _InlineProcessPoolExecutor
        visibility_export.as_completed = lambda futures: list(futures)

    def tearDown(self) -> None:
        visibility_export.ProcessPoolExecutor = self._original_process_pool_executor
        visibility_export.as_completed = self._original_as_completed
        shutil.rmtree(TEST_TMP_ROOT, ignore_errors=True)

    def test_demo_input_generates_visibility_parquet_by_default(self) -> None:
        root = make_test_dir()
        demo_path = root / "match.dem"
        demo_path.write_bytes(b"demo")
        dataset_dir = root / "outputs" / "match"

        def _fake_parse(args, demo_path: Path, output_dir: Path) -> int:
            _write_dataset(dataset_dir, demo_path=demo_path)
            return 0

        args = _playback_args(demo_path, output_dir=root / "outputs")
        with patch("wall.cli.handle_parse", side_effect=_fake_parse), patch("wall.cli.handle_view", return_value=0):
            exit_code = handle_playback(args)

        self.assertEqual(exit_code, 0)
        artifact_path = dataset_dir / "visibility.parquet"
        self.assertTrue(artifact_path.exists())

    def test_existing_dataset_generates_visibility_parquet_when_missing(self) -> None:
        dataset_dir = make_test_dir()
        _write_dataset(dataset_dir)

        args = _playback_args(dataset_dir)
        with patch("wall.cli.handle_view", return_value=0):
            exit_code = handle_playback(args)

        self.assertEqual(exit_code, 0)
        artifact_path = dataset_dir / "visibility.parquet"
        self.assertTrue(artifact_path.exists())

    def test_existing_visibility_parquet_is_skipped_by_default(self) -> None:
        dataset_dir = make_test_dir()
        _write_dataset(dataset_dir)
        (dataset_dir / "visibility.parquet").write_bytes(b"existing")

        with patch("wall.cli.resolve_dataset_map_name", return_value="de_dust2"), patch(
            "wall.visibility.export.run_visibility_exports"
        ) as run_exports:
            result = ensure_default_visibility_artifact(dataset_dir, force=False)

        self.assertIsNone(result)
        run_exports.assert_not_called()

    def test_renew_visibility_regenerates_it(self) -> None:
        dataset_dir = make_test_dir()
        _write_dataset(dataset_dir)
        args = _playback_args(dataset_dir, renew_visibility=True)

        with patch("wall.cli.handle_view", return_value=0), patch(
            "wall.cli.ensure_default_visibility_artifact", return_value=dataset_dir / "visibility.parquet"
        ) as ensure_visibility:
            exit_code = handle_playback(args)

        self.assertEqual(exit_code, 0)
        ensure_visibility.assert_called_once_with(dataset_dir, force=True, tickrate=64.0)

    def test_no_visibility_skips_it(self) -> None:
        root = make_test_dir()
        demo_path = root / "match.dem"
        demo_path.write_bytes(b"demo")
        dataset_dir = root / "outputs" / "match"

        def _fake_parse(args, demo_path: Path, output_dir: Path) -> int:
            _write_dataset(dataset_dir, demo_path=demo_path)
            return 0

        args = _playback_args(demo_path, output_dir=root / "outputs", no_visibility=True)
        with patch("wall.cli.handle_parse", side_effect=_fake_parse), patch(
            "wall.cli.handle_view", return_value=0
        ), patch("wall.cli.ensure_default_visibility_artifact") as ensure_visibility:
            exit_code = handle_playback(args)

        self.assertEqual(exit_code, 0)
        ensure_visibility.assert_not_called()
        self.assertFalse((dataset_dir / "visibility.parquet").exists())

    def test_profile_flag_sets_profile_env_for_view_path(self) -> None:
        dataset_dir = make_test_dir()
        _write_dataset(dataset_dir)
        args = _playback_args(dataset_dir, profile=True, no_visibility=True)

        seen: dict[str, str | None] = {}

        def _fake_view(path: Path, passed_args: argparse.Namespace) -> int:
            _ = path, passed_args
            seen["profile"] = os.environ.get("WALL_VIEWER_PROFILE")
            seen["verbose"] = os.environ.get("WALL_VERBOSE")
            return 0

        with patch("wall.cli.handle_view", side_effect=_fake_view):
            exit_code = handle_playback(args)

        self.assertEqual(exit_code, 0)
        self.assertEqual(seen["profile"], "1")
        self.assertIsNone(seen["verbose"])

    def test_verbose_flag_sets_verbose_env_for_view_path_without_profile(self) -> None:
        dataset_dir = make_test_dir()
        _write_dataset(dataset_dir)
        args = _playback_args(dataset_dir, verbose=True, no_visibility=True)

        seen: dict[str, str | None] = {}

        def _fake_view(path: Path, passed_args: argparse.Namespace) -> int:
            _ = path, passed_args
            seen["profile"] = os.environ.get("WALL_VIEWER_PROFILE")
            seen["verbose"] = os.environ.get("WALL_VERBOSE")
            return 0

        with patch("wall.cli.handle_view", side_effect=_fake_view):
            exit_code = handle_playback(args)

        self.assertEqual(exit_code, 0)
        self.assertIsNone(seen["profile"])
        self.assertEqual(seen["verbose"], "1")

    def test_wall_visibility_does_not_import_wall_viewer(self) -> None:
        for module_name in list(sys.modules):
            if module_name.startswith("wall.viewer") or module_name == "wall.visibility.export":
                sys.modules.pop(module_name, None)

        __import__("wall.visibility.export")

        self.assertFalse(any(module_name.startswith("wall.viewer") for module_name in sys.modules))

    def test_output_schema_matches_expected_pair_fields(self) -> None:
        dataset_dir = make_test_dir()
        _write_dataset(dataset_dir)

        output_path = ensure_default_visibility_artifact(dataset_dir, force=True)

        self.assertIsNotNone(output_path)
        assert output_path is not None
        exported = pd.read_parquet(output_path)
        self.assertEqual(
            exported.columns.tolist(),
            [
                "tick",
                "round_id",
                "observer",
                "target",
                "distance",
                "relative_yaw_deg",
                "in_fov",
                "has_los",
                "is_visible",
            ],
        )

    def test_automatic_visibility_generation_prints_progress(self) -> None:
        dataset_dir = make_test_dir()
        _write_dataset(dataset_dir)

        output = io.StringIO()
        with redirect_stdout(output):
            with patch.dict("os.environ", {"WALL_VERBOSE": "1"}, clear=False):
                ensure_default_visibility_artifact(dataset_dir, force=True)

        rendered = output.getvalue()
        self.assertIn("Visibility Progress", rendered)
        self.assertIn("1/1", rendered)
        self.assertIn("Visibility pair table written to:", rendered)

    def test_automatic_visibility_generation_is_quiet_by_default(self) -> None:
        dataset_dir = make_test_dir()
        _write_dataset(dataset_dir)

        output = io.StringIO()
        with redirect_stdout(output):
            ensure_default_visibility_artifact(dataset_dir, force=True)

        self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
