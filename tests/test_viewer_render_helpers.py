from __future__ import annotations

import math
import unittest

from wall.viewer.geometry import build_arc_points, build_arc_segment_points, offset_point


class ViewerRenderHelpersTest(unittest.TestCase):
    def test_offset_point_uses_viewer_yaw_convention(self) -> None:
        x, y = offset_point(10.0, 20.0, 0.0, 5.0)
        self.assertAlmostEqual(x, 15.0)
        self.assertAlmostEqual(y, 20.0)

        x, y = offset_point(10.0, 20.0, 90.0, 5.0)
        self.assertAlmostEqual(x, 10.0, places=6)
        self.assertAlmostEqual(y, 15.0, places=6)

    def test_build_arc_points_returns_empty_for_zero_fraction(self) -> None:
        self.assertEqual(build_arc_points(50, 50, 10, 0.0), [])

    def test_build_arc_points_covers_full_circle_when_fraction_is_one(self) -> None:
        points = build_arc_points(100, 200, 20, 1.0)
        self.assertGreaterEqual(len(points), 24)
        self.assertEqual(points[0], (100, 180))
        self.assertEqual(points[-1], (100, 180))

    def test_build_arc_segment_points_respects_radius(self) -> None:
        points = build_arc_segment_points(0, 0, 12, 0.0, math.pi / 2)
        self.assertGreaterEqual(len(points), 24)
        self.assertEqual(points[0], (12, 0))
        self.assertEqual(points[-1], (0, 12))


if __name__ == "__main__":
    unittest.main()
