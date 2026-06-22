from __future__ import annotations

import unittest

import pandas as pd

from wall.domain.sound import SoundPresentationConfig, SoundTimeline


PRESENTATION = SoundPresentationConfig(
    max_display_radius_ratio=0.40,
    base_alpha=170,
    global_alpha_boost=24,
    start_expand_ticks=4,
    end_shrink_ticks=4,
    suppression_distance_px=44.0,
)


def _present(df: pd.DataFrame, frame_tick: int):
    timeline = SoundTimeline(df)
    return timeline.present_events_at(
        frame_tick,
        world_to_px=lambda x, y: (x, y),
        world_dist_to_px=lambda distance: distance / 10.0,
        viewport_width=1200,
        viewport_height=900,
        presentation=PRESENTATION,
    )


class SoundTimelineTests(unittest.TestCase):
    def test_same_emitter_smaller_ring_is_suppressed(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "tick": 10,
                    "sound_kind": "utility",
                    "x": 100.0,
                    "y": 200.0,
                    "radius_world": 1600.0,
                    "duration_ticks": 8,
                    "emitter_name": "player",
                    "emitter_steamid": "steamid-1",
                },
                {
                    "tick": 11,
                    "sound_kind": "footstep",
                    "x": 100.0,
                    "y": 200.0,
                    "radius_world": 400.0,
                    "duration_ticks": 8,
                    "emitter_name": "player",
                    "emitter_steamid": "steamid-1",
                },
            ]
        )

        shown = _present(df, 10)

        self.assertEqual([event.sound_kind for event in shown], ["utility"])

        shown_next_tick = _present(df, 11)
        self.assertEqual([event.sound_kind for event in shown_next_tick], ["utility"])

    def test_grenade_bounce_is_not_suppressed_by_other_sounds(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "tick": 10,
                    "sound_kind": "footstep",
                    "x": 100.0,
                    "y": 200.0,
                    "radius_world": 850.0,
                    "duration_ticks": 8,
                    "emitter_name": "player",
                    "emitter_steamid": "steamid-1",
                },
                {
                    "tick": 10,
                    "sound_kind": "grenade_bounce",
                    "x": 100.0,
                    "y": 200.0,
                    "radius_world": 650.0,
                    "duration_ticks": 12,
                    "emitter_name": "player",
                    "emitter_steamid": "steamid-1",
                    "grenade_entity_id": 42,
                },
            ]
        )

        shown = _present(df, 10)

        self.assertEqual({event.sound_kind for event in shown}, {"footstep", "grenade_bounce"})

    def test_sound_style_metadata_is_exposed_to_viewer(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "tick": 10,
                    "sound_kind": "grenade_bounce",
                    "x": 100.0,
                    "y": 200.0,
                    "radius_world": 650.0,
                    "duration_ticks": 12,
                    "emitter_name": "player",
                    "emitter_steamid": "steamid-1",
                    "grenade_entity_id": 42,
                }
            ]
        )

        shown = _present(df, 10)

        self.assertEqual(len(shown), 1)
        event = shown[0]
        self.assertEqual(event.color, (188, 224, 236))
        self.assertEqual(event.center_marker_radius, 1)
        self.assertEqual(event.center_marker_alpha_cap, 120)

    def test_capped_gunfire_exposes_map_label(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "tick": 10,
                    "sound_kind": "gunfire",
                    "x": 100.0,
                    "y": 200.0,
                    "radius_world": 8000.0,
                    "duration_ticks": 4,
                    "emitter_name": "player",
                    "emitter_steamid": "steamid-1",
                }
            ]
        )

        shown = _present(df, 10)

        self.assertEqual(len(shown), 1)
        self.assertTrue(shown[0].is_capped)
        self.assertEqual(shown[0].label, "MAP")


if __name__ == "__main__":
    unittest.main()
