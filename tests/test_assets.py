from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import uuid
import zipfile

from wall import assets
from wall.cli import handle_assets, resolve_dataset_map_name


TEST_TMP_ROOT = Path("F:/wall/tmp_test_assets")


def make_test_dir() -> Path:
    TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = TEST_TMP_ROOT / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


class AssetsTests(unittest.TestCase):
    def test_required_artifacts_for_feature(self) -> None:
        self.assertEqual(assets.required_artifacts_for_feature("viewer"), ("maps",))
        self.assertEqual(assets.required_artifacts_for_feature("visibility"), ("maps", "tris"))
        self.assertEqual(assets.required_artifacts_for_feature("analysis"), ("maps", "navs", "tris"))

    def test_collect_missing_artifacts_checks_map_specific_files(self) -> None:
        root = make_test_dir()
        try:
            maps_dir = root / "maps"
            navs_dir = root / "navs"
            tris_dir = root / "tris"
            maps_dir.mkdir()
            navs_dir.mkdir()
            tris_dir.mkdir()
            (maps_dir / "de_dust2.png").write_bytes(b"png")
            (tris_dir / "de_dust2.tri").write_bytes(b"tri")

            with (
                patch("wall.assets.awpy_data_dir", return_value=root),
                patch("wall.assets.awpy_maps_dir", return_value=maps_dir),
                patch("wall.assets.awpy_navs_dir", return_value=navs_dir),
                patch("wall.assets.awpy_tris_dir", return_value=tris_dir),
            ):
                missing = assets.collect_missing_artifacts(("maps", "navs", "tris"), "de_dust2")

            self.assertEqual([status.artifact for status in missing], ["navs"])
            self.assertEqual(missing[0].path, navs_dir / "de_dust2.nav")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_resolve_dataset_map_name_reads_metadata(self) -> None:
        dataset_dir = make_test_dir()
        try:
            (dataset_dir / "metadata.json").write_text(
                json.dumps({"derived": {"map_name": "de_ancient"}}),
                encoding="utf-8",
            )
            self.assertEqual(resolve_dataset_map_name(dataset_dir), "de_ancient")
        finally:
            shutil.rmtree(dataset_dir, ignore_errors=True)

    def test_handle_assets_init_uses_dataset_map_name(self) -> None:
        dataset_dir = make_test_dir()
        try:
            (dataset_dir / "metadata.json").write_text(
                json.dumps({"derived": {"map_name": "de_inferno"}}),
                encoding="utf-8",
            )
            (dataset_dir / "ticks.parquet").write_text("", encoding="utf-8")
            (dataset_dir / "inferred_rounds.parquet").write_text("", encoding="utf-8")

            args = argparse.Namespace(
                action="init",
                feature="viewer",
                map_name=None,
                dataset=dataset_dir,
                yes=False,
            )
            missing_status = assets.AssetStatus(
                artifact="maps",
                present=False,
                path=Path("placeholder"),
                detail="map asset",
            )

            with (
                patch("wall.cli.collect_missing_artifacts", side_effect=[[missing_status], []]),
                patch("wall.cli.check_or_raise_for_feature") as ensure_feature,
            ):
                result = handle_assets(args)

            self.assertEqual(result, 0)
            ensure_feature.assert_called_once_with("viewer", map_name="de_inferno", prompt=True)
        finally:
            shutil.rmtree(dataset_dir, ignore_errors=True)

    def test_download_artifact_uses_requests_and_extracts_zip(self) -> None:
        root = make_test_dir()
        try:
            maps_dir = root / "maps"
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w") as archive:
                archive.writestr("de_dust2.png", b"png-bytes")
            zip_bytes = zip_buffer.getvalue()

            class FakeResponse:
                ok = True
                status_code = 200

                def iter_content(self, chunk_size: int):
                    for index in range(0, len(zip_bytes), chunk_size):
                        yield zip_bytes[index : index + chunk_size]

                def close(self) -> None:
                    return None

            with (
                patch("wall.assets.awpy_data_dir", return_value=root),
                patch("wall.assets.awpy_maps_dir", return_value=maps_dir),
                patch("wall.assets.requests.get", return_value=FakeResponse()) as get_mock,
            ):
                assets.download_artifact("maps", patch=17595823)

            self.assertTrue((maps_dir / "de_dust2.png").exists())
            self.assertEqual((maps_dir / ".patch").read_text(encoding="utf-8"), "17595823")
            get_mock.assert_called_once()
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
