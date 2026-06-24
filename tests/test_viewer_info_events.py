from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from wall.viewer.info_events import (
    InfoEvent,
    VISIBILITY_EVENT_KIND,
    build_visibility_spotted_events,
    filter_events_by_players,
    format_info_event_line,
    load_info_events_for_dataset,
    resolve_visibility_artifact_schema,
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

    def test_schema_resolution_accepts_current_visibility_columns(self) -> None:
        schema = resolve_visibility_artifact_schema(
            ["tick", "round_id", "observer", "target", "is_visible"]
        )

        assert schema is not None
        self.assertEqual(schema.round_id_column, "round_id")
        self.assertEqual(schema.observer_column, "observer")
        self.assertEqual(schema.target_column, "target")

    def test_load_info_events_for_dataset_can_scope_to_single_round(self) -> None:
        events = self._events_from_rows(
            [
                {"round_id": 1, "tick": 100, "observer": "A", "target": "X", "is_visible": True},
                {"round_id": 2, "tick": 200, "observer": "B", "target": "Y", "is_visible": True},
            ],
            round_id=2,
        )

        self.assertEqual([(event.round_id, event.observer, event.target) for event in events], [(2, "B", "Y")])

    def test_load_info_events_prefers_steamid_as_internal_keys(self) -> None:
        events = self._events_from_rows(
            [
                {
                    "round_id": 1,
                    "tick": 100,
                    "observer": "A",
                    "target": "X",
                    "observer_steamid": "76561198000000001",
                    "target_steamid": "76561198000000002",
                    "is_visible": True,
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
                {"round_id": 1, "tick": 100, "observer": "A", "target": "X", "is_visible": True},
            ]
        )

        with (
            patch("wall.viewer.info_events._visibility_artifact_path", return_value=Path("F:/wall/outputs/example/visibility.parquet")),
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "wall.viewer.info_events._visibility_artifact_columns",
                return_value=["round_id", "tick", "observer", "target", "is_visible", "unused_col"],
            ),
            patch("wall.viewer.info_events.pd.read_parquet", return_value=projected_frame) as read_parquet,
        ):
            load_info_events_for_dataset(loaded_data, tickrate=10.0)

        read_parquet.assert_called_once_with(
            Path("F:/wall/outputs/example/visibility.parquet"),
            columns=["round_id", "tick", "observer", "target", "is_visible"],
        )

    def test_continuous_visible_pair_generates_single_spotted_event(self) -> None:
        events = self._events_from_rows(
            [
                {"round_id": 1, "tick": 100, "observer": "A", "target": "X", "is_visible": True},
                {"round_id": 1, "tick": 105, "observer": "A", "target": "X", "is_visible": True},
            ]
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].message, "0.00s  A spotted X")

    def test_short_gap_does_not_generate_new_spotted_event(self) -> None:
        events = self._events_from_rows(
            [
                {"round_id": 1, "tick": 100, "observer": "A", "target": "X", "is_visible": True},
                {"round_id": 1, "tick": 110, "observer": "A", "target": "X", "is_visible": False},
                {"round_id": 1, "tick": 118, "observer": "A", "target": "X", "is_visible": True},
            ]
        )

        self.assertEqual(len(events), 1)

    def test_long_gap_generates_new_spotted_event(self) -> None:
        events = self._events_from_rows(
            [
                {"round_id": 1, "tick": 100, "observer": "A", "target": "X", "is_visible": True},
                {"round_id": 1, "tick": 110, "observer": "A", "target": "X", "is_visible": False},
                {"round_id": 1, "tick": 130, "observer": "A", "target": "X", "is_visible": True},
            ]
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(events[1].seconds, 3.0)

    def test_pair_local_state_does_not_cross_contaminate_other_pairs(self) -> None:
        events = self._events_from_rows(
            [
                {"round_id": 1, "tick": 100, "observer": "A", "target": "X", "is_visible": True},
                {"round_id": 1, "tick": 105, "observer": "B", "target": "X", "is_visible": True},
                {"round_id": 1, "tick": 110, "observer": "A", "target": "Y", "is_visible": True},
            ]
        )

        self.assertEqual(
            [(event.observer, event.target) for event in events],
            [("A", "X"), ("B", "X"), ("A", "Y")],
        )

    def test_same_team_pairs_are_filtered_when_team_columns_exist(self) -> None:
        decoded_rows = pd.DataFrame(
            [
                {
                    "round_id": 1,
                    "tick": 100,
                    "observer": "A",
                    "target": "B",
                    "is_visible": True,
                    "seconds": 0.0,
                    "observer_team": 2,
                    "target_team": 2,
                },
                {
                    "round_id": 1,
                    "tick": 101,
                    "observer": "A",
                    "target": "X",
                    "is_visible": True,
                    "seconds": 0.1,
                    "observer_team": 2,
                    "target_team": 3,
                },
            ]
        )

        events = build_visibility_spotted_events(decoded_rows)

        self.assertEqual([(event.observer, event.target) for event in events], [("A", "X")])

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

    def test_no_visible_events_renders_placeholder_line(self) -> None:
        lines = visible_event_lines_for_tick([], round_id=1, current_tick=100)

        self.assertEqual(lines, ["No visibility events"])

    def test_format_info_event_line_matches_sidebar_text(self) -> None:
        event = InfoEvent(1, 100, 80.3, VISIBILITY_EVENT_KIND, "playerA", "playerB", "")

        self.assertEqual(format_info_event_line(event), "80.30s  playerA spotted playerB")


if __name__ == "__main__":
    unittest.main()
