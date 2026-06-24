from __future__ import annotations

from contextlib import redirect_stdout
import io
import os
import unittest
from unittest.mock import patch

from wall.output import applied_output_mode
from wall.viewer import cli as viewer_cli
from wall.io import demo_parse


class OutputModeTests(unittest.TestCase):
    def test_parse_progress_is_quiet_by_default(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output), patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WALL_VERBOSE", None)
            os.environ.pop("WALL_VIEWER_PROFILE", None)
            demo_parse._print_parse_progress(1, 6, "Reading demo")

        self.assertEqual(output.getvalue(), "")

    def test_parse_progress_prints_in_verbose_mode(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output), patch.dict(os.environ, {"WALL_VERBOSE": "1"}, clear=False):
            demo_parse._print_parse_progress(1, 6, "Reading demo")

        rendered = output.getvalue()
        self.assertIn("parsing", rendered)
        self.assertIn("Reading demo", rendered)

    def test_viewer_cli_is_quiet_by_default(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output), patch.dict(os.environ, {}, clear=False), patch(
            "wall.viewer.cli.PygameRoundViewer"
        ) as viewer_cls:
            os.environ.pop("WALL_VERBOSE", None)
            os.environ.pop("WALL_VIEWER_PROFILE", None)
            viewer = viewer_cls.return_value
            viewer.run.return_value = None
            viewer_cli.main(["dummy-dataset"])

        self.assertEqual(output.getvalue(), "")

    def test_viewer_cli_prints_progress_in_verbose_mode(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output), patch.dict(os.environ, {"WALL_VERBOSE": "1"}, clear=False), patch(
            "wall.viewer.cli.PygameRoundViewer"
        ) as viewer_cls:
            viewer = viewer_cls.return_value
            viewer.run.return_value = None
            viewer_cli.main(["dummy-dataset"])

        rendered = output.getvalue()
        self.assertIn("viewer", rendered)
        self.assertIn("Loading dataset", rendered)
        self.assertIn("Opening window", rendered)

    def test_profile_flag_context_enables_profile_env_temporarily(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WALL_VIEWER_PROFILE", None)
            self.assertNotIn("WALL_VIEWER_PROFILE", os.environ)
            with applied_output_mode(profile=True):
                self.assertEqual(os.environ.get("WALL_VIEWER_PROFILE"), "1")
            self.assertNotIn("WALL_VIEWER_PROFILE", os.environ)


if __name__ == "__main__":
    unittest.main()
