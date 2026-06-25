from __future__ import annotations

import unittest

import pandas as pd

from wall.io.grenade_segments import (
    GRENADE_SEGMENT_SCHEMA_COLUMNS,
    GrenadeSegmentCompressionConfig,
    build_grenade_trajectory_segments_table,
)


def _row(
    *,
    tick: int,
    x: float,
    y: float,
    z: float,
    round_id: int = 1,
    grenade_entity_id: int = 7,
    grenade_type: str = "CSmokeGrenadeProjectile",
    steamid: str = "s1",
    name: str = "thrower",
) -> dict[str, object]:
    return {
        "tick": tick,
        "x": x,
        "y": y,
        "z": z,
        "grenade_entity_id": grenade_entity_id,
        "grenade_type": grenade_type,
        "steamid": steamid,
        "name": name,
        "inferred_round_id": round_id,
        "inferred_round_tick": tick - 100,
        "inferred_round_seconds": (tick - 100) / 64.0,
    }


class GrenadeSegmentsTests(unittest.TestCase):
    def test_straight_line_trajectory_compresses_to_one_segment(self) -> None:
        grenades = pd.DataFrame(
            [
                _row(tick=100, x=0.0, y=0.0, z=0.0),
                _row(tick=101, x=10.0, y=0.0, z=0.0),
                _row(tick=102, x=20.0, y=0.0, z=0.0),
            ]
        )

        table = build_grenade_trajectory_segments_table(grenades)

        self.assertEqual(len(table), 1)
        self.assertEqual(table.iloc[0]["start_tick"], 100)
        self.assertEqual(table.iloc[0]["end_tick"], 102)
        self.assertEqual(table.iloc[0]["reason_end"], "end")

    def test_bent_trajectory_splits_into_multiple_segments(self) -> None:
        grenades = pd.DataFrame(
            [
                _row(tick=100, x=0.0, y=0.0, z=0.0),
                _row(tick=101, x=10.0, y=0.0, z=0.0),
                _row(tick=102, x=20.0, y=0.0, z=0.0),
                _row(tick=103, x=20.0, y=100.0, z=0.0),
            ]
        )

        table = build_grenade_trajectory_segments_table(grenades)

        self.assertEqual(len(table), 2)
        self.assertEqual(table["reason_end"].tolist(), ["max_error_2d", "end"])

    def test_large_z_deviation_splits_segment(self) -> None:
        grenades = pd.DataFrame(
            [
                _row(tick=100, x=0.0, y=0.0, z=0.0),
                _row(tick=101, x=10.0, y=0.0, z=0.0),
                _row(tick=102, x=20.0, y=0.0, z=100.0),
            ]
        )

        table = build_grenade_trajectory_segments_table(grenades)

        self.assertEqual(len(table), 2)
        self.assertEqual(table.iloc[0]["reason_end"], "max_error_z")

    def test_tick_gap_splits_segment(self) -> None:
        grenades = pd.DataFrame(
            [
                _row(tick=100, x=0.0, y=0.0, z=0.0),
                _row(tick=101, x=10.0, y=0.0, z=0.0),
                _row(tick=110, x=20.0, y=0.0, z=0.0),
            ]
        )

        table = build_grenade_trajectory_segments_table(grenades)

        self.assertEqual(len(table), 2)
        self.assertEqual(table.iloc[0]["reason_end"], "tick_gap")
        self.assertEqual(table.iloc[1]["start_tick"], 110)

    def test_max_segment_ticks_splits_long_segment(self) -> None:
        grenades = pd.DataFrame([_row(tick=100 + index, x=float(index), y=0.0, z=0.0) for index in range(6)])

        table = build_grenade_trajectory_segments_table(
            grenades,
            config=GrenadeSegmentCompressionConfig(max_segment_ticks=4),
        )

        self.assertEqual(len(table), 2)
        self.assertEqual(table.iloc[0]["reason_end"], "max_segment_ticks")
        self.assertEqual(table.iloc[0]["end_tick"], 103)
        self.assertEqual(table.iloc[1]["start_tick"], 103)

    def test_segment_start_and_end_coordinates_are_preserved(self) -> None:
        grenades = pd.DataFrame(
            [
                _row(tick=100, x=1.0, y=2.0, z=3.0),
                _row(tick=101, x=4.0, y=5.0, z=6.0),
                _row(tick=102, x=7.0, y=8.0, z=9.0),
            ]
        )

        table = build_grenade_trajectory_segments_table(grenades)
        row = table.iloc[0]

        self.assertEqual((row["start_x"], row["start_y"], row["start_z"]), (1.0, 2.0, 3.0))
        self.assertEqual((row["end_x"], row["end_y"], row["end_z"]), (7.0, 8.0, 9.0))

    def test_segments_share_boundary_points_when_split_by_error(self) -> None:
        grenades = pd.DataFrame(
            [
                _row(tick=100, x=0.0, y=0.0, z=0.0),
                _row(tick=101, x=10.0, y=0.0, z=0.0),
                _row(tick=102, x=20.0, y=0.0, z=0.0),
                _row(tick=103, x=20.0, y=100.0, z=0.0),
            ]
        )

        table = build_grenade_trajectory_segments_table(grenades)

        self.assertEqual(table.iloc[0]["end_tick"], table.iloc[1]["start_tick"])

    def test_point_count_is_recorded_per_segment(self) -> None:
        grenades = pd.DataFrame(
            [
                _row(tick=100, x=0.0, y=0.0, z=0.0),
                _row(tick=101, x=10.0, y=10.0, z=10.0),
                _row(tick=102, x=20.0, y=0.0, z=0.0),
            ]
        )

        table = build_grenade_trajectory_segments_table(
            grenades,
            config=GrenadeSegmentCompressionConfig(max_error_2d=32.0, max_error_z=32.0),
        )

        self.assertEqual(table.iloc[0]["point_count"], 3)

    def test_max_error_fields_are_recorded(self) -> None:
        grenades = pd.DataFrame(
            [
                _row(tick=100, x=0.0, y=0.0, z=0.0),
                _row(tick=101, x=10.0, y=10.0, z=10.0),
                _row(tick=102, x=20.0, y=0.0, z=0.0),
            ]
        )

        table = build_grenade_trajectory_segments_table(grenades)
        row = table.iloc[0]

        self.assertAlmostEqual(float(row["max_error_2d"]), 10.0, places=6)
        self.assertAlmostEqual(float(row["max_error_z"]), 10.0, places=6)

    def test_output_schema_is_stable(self) -> None:
        grenades = pd.DataFrame(
            [
                _row(tick=100, x=0.0, y=0.0, z=0.0),
                _row(tick=101, x=10.0, y=0.0, z=0.0),
            ]
        )

        table = build_grenade_trajectory_segments_table(grenades)

        self.assertEqual(table.columns.tolist(), GRENADE_SEGMENT_SCHEMA_COLUMNS)


if __name__ == "__main__":
    unittest.main()
