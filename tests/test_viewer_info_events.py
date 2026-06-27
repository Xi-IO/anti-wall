from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from wall.cli import build_info_feed_audit_parser, handle_info_feed_audit
from wall.viewer.info_events import (
    INFO_FEED_AUDIT_COLUMNS,
    InfoEvent,
    SOUND_EVENT_KIND,
    VISIBILITY_EVENT_KIND,
    UNSUPPORTED_VISIBILITY_SCHEMA_MESSAGE,
    build_info_feed_audit_table,
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

    def _events_from_sound_rows(
        self,
        rows: list[dict[str, object]],
        *,
        tick_rows: list[dict[str, object]] | None = None,
        round_id: int | None = None,
    ) -> list[InfoEvent]:
        with tempfile.TemporaryDirectory(dir="F:/wall") as tmp_dir:
            data_dir = Path(tmp_dir)
            pd.DataFrame(rows).to_parquet(data_dir / "sound_exposure.parquet", index=False)
            if tick_rows is not None:
                pd.DataFrame(tick_rows).to_parquet(data_dir / "ticks.parquet", index=False)
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
            patch("wall.viewer.info_events._sound_exposure_artifact_path", return_value=Path("F:/wall/outputs/example/sound_exposure.parquet")),
            patch(
                "wall.viewer.info_events._visibility_artifact_columns",
                return_value=["round_id", "observer", "target", "start_tick", "end_tick", "state", "unused_col"],
            ),
            patch(
                "pathlib.Path.exists",
                new=lambda self: str(self).endswith("visibility.parquet"),
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

    def test_sound_exposure_gunfire_builds_sound_info_event(self) -> None:
        events = self._events_from_sound_rows(
            [
                {
                    "round_id": 1,
                    "effect_id": "snd_r01_000001",
                    "observer_id": "s_obs",
                    "source_type": "player",
                    "source_id": "s_src",
                    "start_tick": 112,
                    "end_tick": 112,
                    "sound_class": "weapon",
                    "sound_action": "gunfire",
                    "item_name": "ak47",
                    "shot_count": 3,
                    "raw_source": "weapon_fire",
                }
            ],
            tick_rows=[
                {"steamid": "s_obs", "name": "Observer"},
                {"steamid": "s_src", "name": "Shooter"},
            ],
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, SOUND_EVENT_KIND)
        self.assertEqual(events[0].observer_key, "s_obs")
        self.assertEqual(events[0].target_key, "s_src")
        self.assertEqual(events[0].message, "1.20s  Observer heard 3 ak47 shots from Shooter")

    def test_sound_exposure_gunfire_singular_message_does_not_sound_sustained(self) -> None:
        events = self._events_from_sound_rows(
            [
                {
                    "round_id": 1,
                    "effect_id": "snd_r01_000002",
                    "observer_id": "s_obs",
                    "source_type": "player",
                    "source_id": "s_src",
                    "start_tick": 120,
                    "end_tick": 124,
                    "sound_class": "weapon",
                    "sound_action": "gunfire",
                    "item_name": "AWP",
                    "shot_count": 1,
                    "raw_source": "weapon_fire",
                }
            ],
            tick_rows=[
                {"steamid": "s_obs", "name": "Observer"},
                {"steamid": "s_src", "name": "Shooter"},
            ],
        )

        self.assertEqual(events[0].message, "2.00s  Observer heard AWP shot from Shooter")
        self.assertNotIn("持续", events[0].message)

    def test_locomotion_rows_are_merged_into_single_feed_event(self) -> None:
        events = self._events_from_sound_rows(
            [
                {
                    "round_id": 1,
                    "effect_id": "snd_r01_000011",
                    "observer_id": "s_obs",
                    "source_type": "player",
                    "source_id": "s_src",
                    "start_tick": 100,
                    "end_tick": 118,
                    "sound_class": "movement",
                    "sound_action": "locomotion",
                    "item_name": "",
                    "shot_count": None,
                    "raw_source": "inferred_movement",
                    "distance_min": 400.0,
                },
                {
                    "round_id": 1,
                    "effect_id": "snd_r01_000012",
                    "observer_id": "s_obs",
                    "source_type": "player",
                    "source_id": "s_src",
                    "start_tick": 126,
                    "end_tick": 144,
                    "sound_class": "movement",
                    "sound_action": "locomotion",
                    "item_name": "",
                    "shot_count": None,
                    "raw_source": "inferred_movement",
                    "distance_min": 380.0,
                },
            ],
            tick_rows=[
                {"steamid": "s_obs", "name": "Observer"},
                {"steamid": "s_src", "name": "Runner"},
            ],
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].tick, 100)
        self.assertEqual(events[0].message, "0.00s  Observer heard movement from Runner")

    def test_short_locomotion_feed_event_is_filtered(self) -> None:
        events = self._events_from_sound_rows(
            [
                {
                    "round_id": 1,
                    "effect_id": "snd_r01_000013",
                    "observer_id": "s_obs",
                    "source_type": "player",
                    "source_id": "s_src",
                    "start_tick": 100,
                    "end_tick": 110,
                    "sound_class": "movement",
                    "sound_action": "locomotion",
                    "item_name": "",
                    "shot_count": None,
                    "raw_source": "inferred_movement",
                    "distance_min": 500.0,
                }
            ],
            tick_rows=[
                {"steamid": "s_obs", "name": "Observer"},
                {"steamid": "s_src", "name": "Runner"},
            ],
        )

        self.assertEqual(events, [])

    def test_hard_step_events_are_deduped_within_window(self) -> None:
        events = self._events_from_sound_rows(
            [
                {
                    "round_id": 1,
                    "effect_id": "snd_r01_000014",
                    "observer_id": "s_obs",
                    "source_type": "player",
                    "source_id": "s_src",
                    "start_tick": 100,
                    "end_tick": 100,
                    "sound_class": "movement",
                    "sound_action": "hard_step",
                    "item_name": "",
                    "shot_count": None,
                    "raw_source": "player_footstep",
                    "distance_min": 200.0,
                },
                {
                    "round_id": 1,
                    "effect_id": "snd_r01_000015",
                    "observer_id": "s_obs",
                    "source_type": "player",
                    "source_id": "s_src",
                    "start_tick": 120,
                    "end_tick": 120,
                    "sound_class": "movement",
                    "sound_action": "hard_step",
                    "item_name": "",
                    "shot_count": None,
                    "raw_source": "player_footstep",
                    "distance_min": 180.0,
                },
            ],
            tick_rows=[
                {"steamid": "s_obs", "name": "Observer"},
                {"steamid": "s_src", "name": "Runner"},
            ],
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].tick, 100)
        self.assertEqual(events[0].message, "0.00s  Observer heard hard step from Runner")

    def test_hard_step_events_outside_64_tick_window_both_remain(self) -> None:
        events = self._events_from_sound_rows(
            [
                {
                    "round_id": 1,
                    "effect_id": "snd_r01_000015a",
                    "observer_id": "s_obs",
                    "source_type": "player",
                    "source_id": "s_src",
                    "start_tick": 100,
                    "end_tick": 100,
                    "sound_class": "movement",
                    "sound_action": "hard_step",
                    "item_name": "",
                    "shot_count": None,
                    "raw_source": "player_footstep",
                    "distance_min": 200.0,
                },
                {
                    "round_id": 1,
                    "effect_id": "snd_r01_000015b",
                    "observer_id": "s_obs",
                    "source_type": "player",
                    "source_id": "s_src",
                    "start_tick": 165,
                    "end_tick": 165,
                    "sound_class": "movement",
                    "sound_action": "hard_step",
                    "item_name": "",
                    "shot_count": None,
                    "raw_source": "player_footstep",
                    "distance_min": 180.0,
                },
            ],
            tick_rows=[
                {"steamid": "s_obs", "name": "Observer"},
                {"steamid": "s_src", "name": "Runner"},
            ],
        )

        self.assertEqual([event.tick for event in events], [100, 165])

    def test_utility_actions_enter_feed_except_bounce(self) -> None:
        events = self._events_from_sound_rows(
            [
                {
                    "round_id": 1,
                    "effect_id": "snd_r01_000015c",
                    "observer_id": "s_obs",
                    "source_type": "grenade",
                    "source_id": "g1",
                    "start_tick": 100,
                    "end_tick": 100,
                    "sound_class": "utility",
                    "sound_action": "he_detonate",
                    "item_name": "hegrenade",
                    "shot_count": None,
                    "raw_source": "hegrenade_detonate",
                },
                {
                    "round_id": 1,
                    "effect_id": "snd_r01_000015d",
                    "observer_id": "s_obs",
                    "source_type": "grenade",
                    "source_id": "g2",
                    "start_tick": 120,
                    "end_tick": 120,
                    "sound_class": "utility",
                    "sound_action": "smoke_detonate",
                    "item_name": "smokegrenade",
                    "shot_count": None,
                    "raw_source": "smokegrenade_detonate",
                },
                {
                    "round_id": 1,
                    "effect_id": "snd_r01_000015e",
                    "observer_id": "s_obs",
                    "source_type": "grenade",
                    "source_id": "g3",
                    "start_tick": 140,
                    "end_tick": 140,
                    "sound_class": "utility",
                    "sound_action": "flash_detonate",
                    "item_name": "flashbang",
                    "shot_count": None,
                    "raw_source": "flashbang_detonate",
                },
                {
                    "round_id": 1,
                    "effect_id": "snd_r01_000015f",
                    "observer_id": "s_obs",
                    "source_type": "grenade",
                    "source_id": "g4",
                    "start_tick": 160,
                    "end_tick": 160,
                    "sound_class": "utility",
                    "sound_action": "inferno_startburn",
                    "item_name": "molotov",
                    "shot_count": None,
                    "raw_source": "inferno_startburn",
                },
                {
                    "round_id": 1,
                    "effect_id": "snd_r01_000015g",
                    "observer_id": "s_obs",
                    "source_type": "grenade",
                    "source_id": "g5",
                    "start_tick": 180,
                    "end_tick": 180,
                    "sound_class": "utility",
                    "sound_action": "bounce",
                    "item_name": "flashbang",
                    "shot_count": None,
                    "raw_source": "grenade_bounce",
                },
            ],
        )

        self.assertEqual(
            [event.message for event in events],
            [
                "0.00s  s_obs heard HE detonate",
                "2.00s  s_obs heard smoke bloom",
                "4.00s  s_obs heard flash detonate",
                "6.00s  s_obs heard fire start",
            ],
        )

    def test_damage_reload_and_zoom_still_do_not_enter_feed(self) -> None:
        events = self._events_from_sound_rows(
            [
                {
                    "round_id": 1,
                    "effect_id": "snd_r01_000015h",
                    "observer_id": "s_obs",
                    "source_type": "player",
                    "source_id": "s_src",
                    "start_tick": 100,
                    "end_tick": 100,
                    "sound_class": "damage",
                    "sound_action": "hurt",
                    "item_name": "",
                    "shot_count": None,
                    "raw_source": "player_hurt",
                },
                {
                    "round_id": 1,
                    "effect_id": "snd_r01_000015i",
                    "observer_id": "s_obs",
                    "source_type": "player",
                    "source_id": "s_src",
                    "start_tick": 120,
                    "end_tick": 120,
                    "sound_class": "weapon",
                    "sound_action": "reload",
                    "item_name": "ak47",
                    "shot_count": None,
                    "raw_source": "weapon_reload",
                },
                {
                    "round_id": 1,
                    "effect_id": "snd_r01_000015j",
                    "observer_id": "s_obs",
                    "source_type": "player",
                    "source_id": "s_src",
                    "start_tick": 140,
                    "end_tick": 140,
                    "sound_class": "weapon",
                    "sound_action": "zoom",
                    "item_name": "awp",
                    "shot_count": None,
                    "raw_source": "weapon_zoom",
                },
            ],
        )

        self.assertEqual(events, [])

    def test_invalid_sound_exposure_schema_is_ignored_without_breaking_visibility_events(self) -> None:
        with tempfile.TemporaryDirectory(dir="F:/wall") as tmp_dir:
            data_dir = Path(tmp_dir)
            pd.DataFrame(
                [
                    {"round_id": 1, "observer": "A", "target": "X", "start_tick": 100, "end_tick": 110, "start_seconds": 0.0, "end_seconds": 1.0, "state": "VISIBLE"},
                ]
            ).to_parquet(data_dir / "visibility.parquet", index=False)
            pd.DataFrame(
                [
                    {"round_id": 1, "observer_id": "s_obs", "start_tick": 112},
                ]
            ).to_parquet(data_dir / "sound_exposure.parquet", index=False)
            loaded_data = FakeLoadedData(data_dir=data_dir, inferred_rounds=self._inferred_rounds())

            events = load_info_events_for_dataset(loaded_data, tickrate=10.0)

        self.assertEqual([(event.kind, event.observer, event.target) for event in events], [(VISIBILITY_EVENT_KIND, "A", "X")])

    def test_invalid_sound_exposure_schema_logs_ignored_profile_stage(self) -> None:
        with tempfile.TemporaryDirectory(dir="F:/wall") as tmp_dir:
            data_dir = Path(tmp_dir)
            pd.DataFrame(
                [
                    {"round_id": 1, "observer": "A", "target": "X", "start_tick": 100, "end_tick": 110, "start_seconds": 0.0, "end_seconds": 1.0, "state": "VISIBLE"},
                ]
            ).to_parquet(data_dir / "visibility.parquet", index=False)
            pd.DataFrame(
                [
                    {"round_id": 1, "observer_id": "s_obs", "start_tick": 112},
                ]
            ).to_parquet(data_dir / "sound_exposure.parquet", index=False)
            loaded_data = FakeLoadedData(data_dir=data_dir, inferred_rounds=self._inferred_rounds())

            with patch("wall.viewer.info_events.profile_log") as profile_log:
                load_info_events_for_dataset(loaded_data, tickrate=10.0)

        ignored_calls = [call for call in profile_log.call_args_list if call.args and call.args[0] == "info_events.sound_exposure_ignored"]
        self.assertEqual(len(ignored_calls), 1)
        self.assertIn("reason=ValueError", ignored_calls[0].kwargs["note"])

    def test_sound_feed_profile_records_merge_and_dedupe_stats(self) -> None:
        with tempfile.TemporaryDirectory(dir="F:/wall") as tmp_dir:
            data_dir = Path(tmp_dir)
            pd.DataFrame(
                [
                    {
                        "round_id": 1,
                        "effect_id": "snd_r01_000016",
                        "observer_id": "s_obs",
                        "source_type": "player",
                        "source_id": "s_src",
                        "start_tick": 100,
                        "end_tick": 118,
                        "sound_class": "movement",
                        "sound_action": "locomotion",
                        "item_name": "",
                        "shot_count": None,
                        "raw_source": "inferred_movement",
                        "distance_min": 400.0,
                    },
                    {
                        "round_id": 1,
                        "effect_id": "snd_r01_000017",
                        "observer_id": "s_obs",
                        "source_type": "player",
                        "source_id": "s_src",
                        "start_tick": 126,
                        "end_tick": 144,
                        "sound_class": "movement",
                        "sound_action": "locomotion",
                        "item_name": "",
                        "shot_count": None,
                        "raw_source": "inferred_movement",
                        "distance_min": 380.0,
                    },
                    {
                        "round_id": 1,
                        "effect_id": "snd_r01_000018",
                        "observer_id": "s_obs",
                        "source_type": "player",
                        "source_id": "s_src",
                        "start_tick": 150,
                        "end_tick": 150,
                        "sound_class": "movement",
                        "sound_action": "hard_step",
                        "item_name": "",
                        "shot_count": None,
                        "raw_source": "player_footstep",
                        "distance_min": 210.0,
                    },
                    {
                        "round_id": 1,
                        "effect_id": "snd_r01_000019",
                        "observer_id": "s_obs",
                        "source_type": "player",
                        "source_id": "s_src",
                        "start_tick": 170,
                        "end_tick": 170,
                        "sound_class": "movement",
                        "sound_action": "hard_step",
                        "item_name": "",
                        "shot_count": None,
                        "raw_source": "player_footstep",
                        "distance_min": 205.0,
                    },
                ]
            ).to_parquet(data_dir / "sound_exposure.parquet", index=False)
            pd.DataFrame(
                [
                    {"steamid": "s_obs", "name": "Observer"},
                    {"steamid": "s_src", "name": "Runner"},
                ]
            ).to_parquet(data_dir / "ticks.parquet", index=False)
            loaded_data = FakeLoadedData(data_dir=data_dir, inferred_rounds=self._inferred_rounds())

            with patch("wall.viewer.info_events.profile_log") as profile_log:
                load_info_events_for_dataset(loaded_data, tickrate=10.0)

        build_calls = [call for call in profile_log.call_args_list if call.args and call.args[0] == "info_events.sound_feed_build"]
        self.assertEqual(len(build_calls), 1)
        note = build_calls[0].kwargs["note"]
        self.assertIn("sound_movement_exposures_merged=1", note)
        self.assertIn("sound_hard_step_events_deduped=1", note)
        self.assertIn("sound_exposure_rows_by_class_action=", note)
        self.assertIn("sound_info_events_generated_by_class_action=", note)
        self.assertIn("sound_info_events_dropped_by_class_action=", note)

    def test_load_info_events_combines_visibility_and_sound_events(self) -> None:
        with tempfile.TemporaryDirectory(dir="F:/wall") as tmp_dir:
            data_dir = Path(tmp_dir)
            pd.DataFrame(
                [
                    {"round_id": 1, "observer": "A", "target": "X", "start_tick": 100, "end_tick": 110, "start_seconds": 0.0, "end_seconds": 1.0, "state": "VISIBLE"},
                ]
            ).to_parquet(data_dir / "visibility.parquet", index=False)
            pd.DataFrame(
                [
                    {
                        "round_id": 1,
                        "effect_id": "snd_r01_000010",
                        "observer_id": "s_obs",
                        "source_type": "player",
                        "source_id": "s_src",
                        "start_tick": 112,
                        "end_tick": 112,
                        "sound_class": "weapon",
                        "sound_action": "gunfire",
                        "item_name": "glock",
                        "shot_count": 1,
                        "raw_source": "weapon_fire",
                    }
                ]
            ).to_parquet(data_dir / "sound_exposure.parquet", index=False)
            pd.DataFrame(
                [
                    {"steamid": "s_obs", "name": "Observer"},
                    {"steamid": "s_src", "name": "Shooter"},
                ]
            ).to_parquet(data_dir / "ticks.parquet", index=False)
            loaded_data = FakeLoadedData(data_dir=data_dir, inferred_rounds=self._inferred_rounds())

            events = load_info_events_for_dataset(loaded_data, tickrate=10.0)

        self.assertEqual([event.kind for event in events], [VISIBILITY_EVENT_KIND, SOUND_EVENT_KIND])

    def test_sound_feed_priority_orders_bomb_before_movement(self) -> None:
        events = self._events_from_sound_rows(
            [
                {
                    "round_id": 1,
                    "effect_id": "snd_r01_000020",
                    "observer_id": "s_obs",
                    "source_type": "player",
                    "source_id": "s_src",
                    "start_tick": 100,
                    "end_tick": 132,
                    "sound_class": "movement",
                    "sound_action": "locomotion",
                    "item_name": "",
                    "shot_count": None,
                    "raw_source": "inferred_movement",
                    "distance_min": 200.0,
                },
                {
                    "round_id": 1,
                    "effect_id": "snd_r01_000021",
                    "observer_id": "s_obs",
                    "source_type": "player",
                    "source_id": "s_src",
                    "start_tick": 100,
                    "end_tick": 100,
                    "sound_class": "bomb",
                    "sound_action": "dropped",
                    "item_name": "c4",
                    "shot_count": None,
                    "raw_source": "bomb_dropped",
                    "distance_min": 50.0,
                },
            ],
            tick_rows=[
                {"steamid": "s_obs", "name": "Observer"},
                {"steamid": "s_src", "name": "Player"},
            ],
        )

        self.assertEqual([event.message for event in events], [
            "0.00s  Observer heard bomb dropped",
            "0.00s  Observer heard movement from Player",
        ])

    def test_build_info_feed_audit_table_includes_sorted_visibility_and_sound_rows(self) -> None:
        with tempfile.TemporaryDirectory(dir="F:/wall") as tmp_dir:
            data_dir = Path(tmp_dir)
            pd.DataFrame(
                [
                    {"round_id": 1, "observer": "A", "target": "X", "observer_key": "sA", "target_key": "sX", "start_tick": 100, "end_tick": 110, "start_seconds": 0.0, "end_seconds": 1.0, "state": "VISIBLE"},
                ]
            ).to_parquet(data_dir / "visibility.parquet", index=False)
            pd.DataFrame(
                [
                    {
                        "round_id": 1,
                        "effect_id": "snd_r01_000030",
                        "observer_id": "s_obs",
                        "source_type": "player",
                        "source_id": "s_src",
                        "start_tick": 100,
                        "end_tick": 132,
                        "sound_class": "movement",
                        "sound_action": "locomotion",
                        "item_name": "",
                        "shot_count": None,
                        "raw_source": "inferred_movement",
                        "distance_min": 220.0,
                    },
                    {
                        "round_id": 1,
                        "effect_id": "snd_r01_000031",
                        "observer_id": "s_obs",
                        "source_type": "player",
                        "source_id": "s_src",
                        "start_tick": 100,
                        "end_tick": 100,
                        "sound_class": "bomb",
                        "sound_action": "dropped",
                        "item_name": "c4",
                        "shot_count": None,
                        "raw_source": "bomb_dropped",
                        "distance_min": 30.0,
                    },
                ]
            ).to_parquet(data_dir / "sound_exposure.parquet", index=False)
            pd.DataFrame(
                [
                    {"steamid": "s_obs", "name": "Observer"},
                    {"steamid": "s_src", "name": "Player"},
                ]
            ).to_parquet(data_dir / "ticks.parquet", index=False)
            loaded_data = FakeLoadedData(data_dir=data_dir, inferred_rounds=self._inferred_rounds())

            table = build_info_feed_audit_table(loaded_data, tickrate=10.0)

        self.assertEqual(table.columns.tolist(), INFO_FEED_AUDIT_COLUMNS)
        self.assertEqual(table["event_class"].tolist(), ["visibility", "sound", "sound"])
        self.assertEqual(table["priority"].tolist(), [-1, 0, 4])
        self.assertEqual(table["sound_class"].tolist(), ["", "bomb", "movement"])
        self.assertEqual(table["observer_name"].tolist(), ["A", "Observer", "Observer"])

    def test_handle_info_feed_audit_writes_output_table(self) -> None:
        with tempfile.TemporaryDirectory(dir="F:/wall") as tmp_dir:
            data_dir = Path(tmp_dir)
            pd.DataFrame(
                [
                    {"round_id": 1, "observer": "A", "target": "X", "observer_key": "sA", "target_key": "sX", "start_tick": 100, "end_tick": 110, "start_seconds": 0.0, "end_seconds": 1.0, "state": "VISIBLE"},
                ]
            ).to_parquet(data_dir / "visibility.parquet", index=False)
            pd.DataFrame(
                [
                    {"inferred_round_id": 1, "start_tick": 100},
                ]
            ).to_parquet(data_dir / "inferred_rounds.parquet", index=False)
            (data_dir / "metadata.json").write_text("{}", encoding="utf-8")
            args = build_info_feed_audit_parser().parse_args([str(data_dir), "--format", "csv"])

            exit_code = handle_info_feed_audit(args)

            self.assertEqual(exit_code, 0)
            exported = pd.read_csv(data_dir / "info_feed_audit.csv")
            self.assertEqual(exported.columns.tolist(), INFO_FEED_AUDIT_COLUMNS)
            self.assertEqual(exported.iloc[0]["event_class"], "visibility")

    def test_unsupported_message_constant_mentions_regeneration(self) -> None:
        self.assertIn("wall visibility <dataset_dir>", UNSUPPORTED_VISIBILITY_SCHEMA_MESSAGE)

    def test_no_visible_events_renders_placeholder_line(self) -> None:
        lines = visible_event_lines_for_tick([], round_id=1, current_tick=100)

        self.assertEqual(lines, ["No info events"])

    def test_format_info_event_line_matches_sidebar_text(self) -> None:
        event = InfoEvent(1, 100, 80.3, VISIBILITY_EVENT_KIND, "playerA", "playerB", "")

        self.assertEqual(format_info_event_line(event), "80.30s  playerA spotted playerB")


if __name__ == "__main__":
    unittest.main()
