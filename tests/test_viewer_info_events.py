from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from wall.viewer.info_events import (
    InfoEvent,
    VISIBILITY_EVENT_KIND,
    UNSUPPORTED_VISIBILITY_SCHEMA_MESSAGE,
    build_visibility_spotted_events,
    filter_events_by_players,
    format_info_event_line,
    load_info_events_for_dataset,
    resolve_visibility_interval_schema,
    validate_visibility_interval_schema,
    visible_event_lines_for_tick,
)


class FakeLoadedData:
    def __init__(self, data_dir: Path, inferred_rounds: pd.DataFrame) -> None:
        self.data_dir = data_dir
        self.inferred_rounds = inferred_rounds


class ViewerInfoEventsTests(unittest.TestCase):
    def _inferred_rounds(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"inferred_round_id": 1, "start_tick": 100},
                {"inferred_round_id": 2, "start_tick": 200},
            ]
        )

    def _events_from_rows(self, rows: list[dict[str, object]], *, round_id: int | None = None) -> list[InfoEvent]:
        with tempfile.TemporaryDirectory(dir="F:/wall") as tmp_dir:
            data_dir = Path(tmp_dir)
            pd.DataFrame(rows).to_parquet(data_dir / "visibility.parquet", index=False)
            loaded_data = FakeLoadedData(data_dir=data_dir, inferred_rounds=self._inferred_rounds())
            return load_info_events_for_dataset(loaded_data, round_id=round_id, tickrate=10.0)

    def test_interval_schema_validation_accepts_interval_columns(self) -> None:
        validate_visibility_interval_schema(
            ["round_id", "observer", "target", "start_tick", "end_tick", "state"]
        )

    def test_interval_schema_resolution_accepts_interval_columns(self) -> None:
        schema = resolve_visibility_interval_schema(
            ["round_id", "observer_key", "observer", "target_key", "target", "start_tick", "end_tick", "start_seconds", "end_seconds", "state"]
        )

        self.assertEqual(schema.round_id_column, "round_id")
        self.assertEqual(schema.observer_column, "observer")
        self.assertEqual(schema.target_column, "target")
        self.assertEqual(schema.start_tick_column, "start_tick")

    def test_missing_start_tick_or_end_tick_fails_schema_validation(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported visibility schema"):
            validate_visibility_interval_schema(["round_id", "observer", "target", "is_visible"])

    def test_old_pair_schema_is_rejected_as_deprecated(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported visibility schema"):
            resolve_visibility_interval_schema(["round_id", "tick", "observer", "target", "is_visible"])

    def test_load_info_events_for_dataset_can_scope_to_single_round(self) -> None:
        events = self._events_from_rows(
            [
                {"round_id": 1, "observer": "A", "target": "X", "start_tick": 100, "end_tick": 110, "start_seconds": 0.0, "end_seconds": 1.0, "state": "VISIBLE"},
                {"round_id": 2, "observer": "B", "target": "Y", "start_tick": 200, "end_tick": 210, "start_seconds": 0.0, "end_seconds": 1.0, "state": "VISIBLE"},
            ],
            round_id=2,
        )

        self.assertEqual([(event.round_id, event.observer, event.target) for event in events], [(2, "B", "Y")])

    def test_load_info_events_prefers_steamid_as_internal_keys(self) -> None:
        events = self._events_from_rows(
            [
                {
                    "round_id": 1,
                    "observer": "A",
                    "target": "X",
                    "observer_key": "76561198000000001",
                    "target_key": "76561198000000002",
                    "start_tick": 100,
                    "end_tick": 110,
                    "start_seconds": 0.0,
                    "end_seconds": 1.0,
                    "state": "VISIBLE",
                },
            ]
        )

        self.assertEqual(events[0].observer, "A")
        self.assertEqual(events[0].target, "X")
        self.assertEqual(events[0].observer_key, "76561198000000001")
        self.assertEqual(events[0].target_key, "76561198000000002")

    def test_load_info_events_reads_only_projected_columns(self) -> None:
        loaded_data = FakeLoadedData(data_dir=Path("F:/wall/outputs/example"), inferred_rounds=self._inferred_rounds())
        projected_frame = pd.DataFrame(
            [
                {"round_id": 1, "observer": "A", "target": "X", "start_tick": 100, "end_tick": 110, "state": "VISIBLE"},
            ]
        )

        with (
            patch("wall.viewer.info_events._visibility_artifact_path", return_value=Path("F:/wall/outputs/example/visibility.parquet")),
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "wall.viewer.info_events._visibility_artifact_columns",
                return_value=["round_id", "observer", "target", "start_tick", "end_tick", "state", "unused_col"],
            ),
            patch("wall.viewer.info_events.pd.read_parquet", return_value=projected_frame) as read_parquet,
        ):
            load_info_events_for_dataset(loaded_data, tickrate=10.0)

        read_parquet.assert_called_once_with(
            Path("F:/wall/outputs/example/visibility.parquet"),
            columns=["round_id", "observer", "target", "start_tick", "end_tick", "state"],
        )

    def test_interval_state_visible_generates_spotted_event(self) -> None:
        events = self._events_from_rows(
            [
                {"round_id": 1, "observer": "A", "target": "X", "start_tick": 100, "end_tick": 105, "start_seconds": 0.0, "end_seconds": 0.5, "state": "VISIBLE"},
            ]
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].message, "0.00s  A spotted X")
        self.assertEqual(events[0].tick, 100)
        self.assertEqual(events[0].seconds, 0.0)

    def test_interval_state_not_visible_does_not_generate_spotted_event(self) -> None:
        events = self._events_from_rows(
            [
                {"round_id": 1, "observer": "A", "target": "X", "start_tick": 100, "end_tick": 110, "start_seconds": 0.0, "end_seconds": 1.0, "state": "OUT_OF_FOV", "is_visible": False},
            ]
        )

        self.assertEqual(events, [])

    def test_interval_is_visible_true_also_generates_spotted_event(self) -> None:
        events = self._events_from_rows(
            [
                {"round_id": 1, "observer": "A", "target": "X", "start_tick": 100, "end_tick": 110, "start_seconds": 0.0, "end_seconds": 1.0, "is_visible": True},
            ]
        )

        self.assertEqual(len(events), 1)

    def test_short_gap_between_visible_intervals_does_not_generate_new_spotted_event(self) -> None:
        events = self._events_from_rows(
            [
                {"round_id": 1, "observer": "A", "target": "X", "start_tick": 100, "end_tick": 110, "start_seconds": 0.0, "end_seconds": 1.0, "state": "VISIBLE"},
                {"round_id": 1, "observer": "A", "target": "X", "start_tick": 115, "end_tick": 120, "start_seconds": 1.5, "end_seconds": 1.8, "state": "VISIBLE"},
            ]
        )

        self.assertEqual(len(events), 1)

    def test_long_gap_between_visible_intervals_generates_new_spotted_event(self) -> None:
        events = self._events_from_rows(
            [
                {"round_id": 1, "observer": "A", "target": "X", "start_tick": 100, "end_tick": 110, "start_seconds": 0.0, "end_seconds": 1.0, "state": "VISIBLE"},
                {"round_id": 1, "observer": "A", "target": "X", "start_tick": 130, "end_tick": 135, "start_seconds": 3.0, "end_seconds": 3.5, "state": "VISIBLE"},
            ]
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(events[1].seconds, 3.0)

    def test_interval_pair_state_does_not_cross_contaminate_other_pairs(self) -> None:
        events = self._events_from_rows(
            [
                {"round_id": 1, "observer": "A", "target": "X", "start_tick": 100, "end_tick": 105, "start_seconds": 0.0, "end_seconds": 0.5, "state": "VISIBLE"},
                {"round_id": 1, "observer": "B", "target": "X", "start_tick": 105, "end_tick": 110, "start_seconds": 0.5, "end_seconds": 1.0, "state": "VISIBLE"},
                {"round_id": 1, "observer": "A", "target": "Y", "start_tick": 110, "end_tick": 115, "start_seconds": 1.0, "end_seconds": 1.5, "state": "VISIBLE"},
            ]
        )

        self.assertEqual([(event.observer, event.target) for event in events], [("A", "X"), ("B", "X"), ("A", "Y")])

    def test_build_visibility_spotted_events_falls_back_to_display_names_for_keys(self) -> None:
        decoded_rows = pd.DataFrame(
            [
                {"round_id": 1, "observer": "A", "target": "X", "observer_key": "", "target_key": "", "start_tick": 100, "end_tick": 105, "start_seconds": 0.0, "end_seconds": 0.5, "is_visible": True, "state": ""},
            ]
        )

        events = build_visibility_spotted_events(decoded_rows)

        self.assertEqual(events[0].observer_key, "A")
        self.assertEqual(events[0].target_key, "X")

    def test_loading_old_pair_schema_raises_clear_error(self) -> None:
        with tempfile.TemporaryDirectory(dir="F:/wall") as tmp_dir:
            data_dir = Path(tmp_dir)
            pd.DataFrame([{"round_id": 1, "tick": 100, "observer": "A", "target": "X", "is_visible": True}]).to_parquet(
                data_dir / "visibility.parquet",
                index=False,
            )
            loaded_data = FakeLoadedData(data_dir=data_dir, inferred_rounds=self._inferred_rounds())

            with self.assertRaisesRegex(ValueError, "Re-run `wall visibility <dataset_dir>`"):
                load_info_events_for_dataset(loaded_data, tickrate=64.0)

    def test_current_tick_filter_hides_future_events(self) -> None:
        events = [
            InfoEvent(1, 100, 0.0, VISIBILITY_EVENT_KIND, "A", "X", "0.00s  A spotted X"),
            InfoEvent(1, 130, 3.0, VISIBILITY_EVENT_KIND, "A", "Y", "3.00s  A spotted Y"),
        ]

        lines = visible_event_lines_for_tick(events, round_id=1, current_tick=120)

        self.assertEqual(lines, ["0.00s  A spotted X"])

    def test_filter_events_by_players_returns_all_when_none_selected(self) -> None:
        events = [
            InfoEvent(1, 100, 0.0, VISIBILITY_EVENT_KIND, "A", "X", "0.00s  A spotted X"),
            InfoEvent(1, 110, 1.0, VISIBILITY_EVENT_KIND, "B", "Y", "1.00s  B spotted Y"),
        ]

        self.assertEqual(filter_events_by_players(events, set()), events)

    def test_filter_events_by_players_matches_selected_observer(self) -> None:
        events = [
            InfoEvent(1, 100, 0.0, VISIBILITY_EVENT_KIND, "A", "X", "0.00s  A spotted X", observer_key="sA", target_key="sX"),
            InfoEvent(1, 110, 1.0, VISIBILITY_EVENT_KIND, "B", "Y", "1.00s  B spotted Y", observer_key="sB", target_key="sY"),
        ]

        filtered = filter_events_by_players(events, {"sA"})

        self.assertEqual(filtered, [events[0]])

    def test_filter_events_by_players_matches_selected_target(self) -> None:
        events = [
            InfoEvent(1, 100, 0.0, VISIBILITY_EVENT_KIND, "A", "X", "0.00s  A spotted X", observer_key="sA", target_key="sX"),
            InfoEvent(1, 110, 1.0, VISIBILITY_EVENT_KIND, "B", "Y", "1.00s  B spotted Y", observer_key="sB", target_key="sY"),
        ]

        filtered = filter_events_by_players(events, {"sY"})

        self.assertEqual(filtered, [events[1]])

    def test_filter_events_by_players_uses_or_logic_for_multiple_players(self) -> None:
        events = [
            InfoEvent(1, 100, 0.0, VISIBILITY_EVENT_KIND, "A", "X", "0.00s  A spotted X", observer_key="sA", target_key="sX"),
            InfoEvent(1, 110, 1.0, VISIBILITY_EVENT_KIND, "B", "Y", "1.00s  B spotted Y", observer_key="sB", target_key="sY"),
            InfoEvent(1, 120, 2.0, VISIBILITY_EVENT_KIND, "C", "Z", "2.00s  C spotted Z", observer_key="sC", target_key="sZ"),
        ]

        filtered = filter_events_by_players(events, {"sA", "sY"})

        self.assertEqual(filtered, [events[0], events[1]])

    def test_missing_visibility_artifact_returns_empty_events(self) -> None:
        with tempfile.TemporaryDirectory(dir="F:/wall") as tmp_dir:
            loaded_data = FakeLoadedData(data_dir=Path(tmp_dir), inferred_rounds=self._inferred_rounds())
            events = load_info_events_for_dataset(loaded_data, tickrate=64.0)

        self.assertEqual(events, [])

    def test_unsupported_message_constant_mentions_regeneration(self) -> None:
        self.assertIn("wall visibility <dataset_dir>", UNSUPPORTED_VISIBILITY_SCHEMA_MESSAGE)

    def test_no_visible_events_renders_placeholder_line(self) -> None:
        lines = visible_event_lines_for_tick([], round_id=1, current_tick=100)

        self.assertEqual(lines, ["No visibility events"])

    def test_format_info_event_line_matches_sidebar_text(self) -> None:
        event = InfoEvent(1, 100, 80.3, VISIBILITY_EVENT_KIND, "playerA", "playerB", "")

        self.assertEqual(format_info_event_line(event), "80.30s  playerA spotted playerB")


if __name__ == "__main__":
    unittest.main()
