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
        round_players=None,
        world_to_px=lambda x, y: (x, y),
        world_dist_to_px=lambda distance: distance / 10.0,
        viewport_width=1200,
        viewport_height=900,
        presentation=PRESENTATION,
    )


def _effect(
    *,
    effect_id: str,
    emitter_type: str,
    source_type: str,
    source_id: str,
    start_tick: int,
    end_tick: int,
    sound_class: str,
    sound_action: str,
    item_name: str = "",
    radius: float,
    position_mode: str = "event_snapshot",
    x: float = 100.0,
    y: float = 200.0,
    z: float = 0.0,
    raw_source: str = "test",
) -> dict[str, object]:
    return {
        "round_id": 1,
        "effect_id": effect_id,
        "emitter_type": emitter_type,
        "source_type": source_type,
        "source_id": source_id,
        "start_tick": start_tick,
        "end_tick": end_tick,
        "sound_class": sound_class,
        "sound_action": sound_action,
        "item_name": item_name,
        "radius": radius,
        "position_mode": position_mode,
        "x": x,
        "y": y,
        "z": z,
        "raw_source": raw_source,
    }


class SoundTimelineTests(unittest.TestCase):
    def test_same_emitter_smaller_ring_is_suppressed(self) -> None:
        df = pd.DataFrame(
            [
                _effect(effect_id="a", emitter_type="impulse", source_type="world_event", source_id="e1", start_tick=10, end_tick=10, sound_class="utility", sound_action="smoke_detonate", radius=1600.0),
                _effect(effect_id="b", emitter_type="impulse", source_type="world_event", source_id="e1", start_tick=11, end_tick=11, sound_class="damage", sound_action="hurt", radius=400.0),
            ]
        )

        shown = _present(df, 10)

        self.assertEqual([event.sound_kind for event in shown], ["smoke_detonate"])

        shown_next_tick = _present(df, 11)
        self.assertEqual([event.sound_kind for event in shown_next_tick], ["smoke_detonate"])

    def test_grenade_bounce_is_not_suppressed_by_other_sounds(self) -> None:
        df = pd.DataFrame(
            [
                _effect(effect_id="a", emitter_type="impulse", source_type="world_event", source_id="e1", start_tick=10, end_tick=10, sound_class="movement", sound_action="hard_step", radius=850.0),
                _effect(effect_id="b", emitter_type="impulse", source_type="grenade", source_id="42", start_tick=10, end_tick=10, sound_class="utility", sound_action="bounce", item_name="flashbang", radius=650.0),
            ]
        )

        shown = _present(df, 10)

        self.assertEqual({event.sound_kind for event in shown}, {"hard_step", "bounce"})

    def test_sound_style_metadata_is_exposed_to_viewer(self) -> None:
        df = pd.DataFrame(
            [
                _effect(effect_id="b", emitter_type="impulse", source_type="grenade", source_id="42", start_tick=10, end_tick=10, sound_class="utility", sound_action="bounce", item_name="flashbang", radius=650.0)
            ]
        )

        shown = _present(df, 10)

        self.assertEqual(len(shown), 1)
        event = shown[0]
        self.assertEqual(event.color, (188, 224, 236))
        self.assertEqual(event.center_marker_radius, 1)
        self.assertEqual(event.center_marker_alpha_cap, 120)

    def test_drop_sound_styles_are_distinct(self) -> None:
        df = pd.DataFrame(
            [
                _effect(effect_id="a", emitter_type="impulse", source_type="dropped_item", source_id="item-a", start_tick=10, end_tick=10, sound_class="item", sound_action="dropped", item_name="ak47", radius=650.0),
                _effect(effect_id="b", emitter_type="impulse", source_type="dropped_item", source_id="item-b", start_tick=10, end_tick=10, sound_class="item", sound_action="dropped", item_name="flashbang", radius=650.0, x=180.0, y=260.0),
            ]
        )

        shown = _present(df, 10)

        self.assertEqual(len(shown), 2)
        by_kind = {event.sound_kind: event for event in shown}
        self.assertEqual(by_kind["dropped"].color, (164, 196, 214))
        self.assertEqual(by_kind["utility_drop"].color, (198, 182, 244))

    def test_capped_gunfire_exposes_map_label(self) -> None:
        df = pd.DataFrame(
            [
                _effect(effect_id="a", emitter_type="impulse", source_type="world_event", source_id="g1", start_tick=10, end_tick=10, sound_class="weapon", sound_action="gunfire", radius=8000.0)
            ]
        )

        shown = _present(df, 10)

        self.assertEqual(len(shown), 1)
        self.assertTrue(shown[0].is_capped)
        self.assertEqual(shown[0].label, "MAP")


if __name__ == "__main__":
    unittest.main()
