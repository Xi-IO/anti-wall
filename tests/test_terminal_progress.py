from __future__ import annotations

import unittest

from wall.io.demo_parse import _render_progress_line


class TerminalProgressTests(unittest.TestCase):
    def test_parse_progress_line_is_compact_and_includes_stage(self) -> None:
        line = _render_progress_line("parsing", 3, 6, detail="Building round and sound tables")

        self.assertIn("parsing", line)
        self.assertIn("3/6", line)
        self.assertIn("Building round and sound tables", line)
        self.assertIn("[", line)
        self.assertIn("]", line)


if __name__ == "__main__":
    unittest.main()
