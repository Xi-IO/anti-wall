from __future__ import annotations

import unittest

from wall.viewer.player_palette import player_marker_number_color
from wall.viewer.ui import player_row_style


class ViewerUiTests(unittest.TestCase):
    def test_player_marker_number_color_matches_ct_and_t_palette(self) -> None:
        self.assertEqual(player_marker_number_color(3), (255, 255, 255))
        self.assertEqual(player_marker_number_color(2), (24, 22, 2))

    def test_selected_player_row_uses_selected_style(self) -> None:
        style = player_row_style(
            player_color=(220, 210, 60),
            text_color=(230, 230, 230),
            muted_text_color=(160, 160, 160),
            accent_color=(120, 176, 236),
            selected=True,
            hovered=False,
        )

        self.assertIsNotNone(style.background_color)
        self.assertTrue(style.show_checkmark)
        self.assertEqual(style.text_color, (240, 240, 240))
        self.assertEqual(style.swatch_border_color, (232, 236, 240))

    def test_hover_does_not_override_selected_style(self) -> None:
        selected_style = player_row_style(
            player_color=(220, 210, 60),
            text_color=(230, 230, 230),
            muted_text_color=(160, 160, 160),
            accent_color=(120, 176, 236),
            selected=True,
            hovered=False,
        )
        selected_hover_style = player_row_style(
            player_color=(220, 210, 60),
            text_color=(230, 230, 230),
            muted_text_color=(160, 160, 160),
            accent_color=(120, 176, 236),
            selected=True,
            hovered=True,
        )

        self.assertTrue(selected_hover_style.show_checkmark)
        self.assertIsNotNone(selected_hover_style.background_color)
        self.assertNotEqual(selected_hover_style.background_color, (52, 52, 52))
        self.assertNotEqual(selected_hover_style.text_color, selected_style.text_color)

    def test_unselected_hover_uses_background_only_without_checkmark(self) -> None:
        style = player_row_style(
            player_color=(25, 145, 189),
            text_color=(230, 230, 230),
            muted_text_color=(160, 160, 160),
            accent_color=(120, 176, 236),
            selected=False,
            hovered=True,
        )

        self.assertEqual(style.background_color, (52, 52, 52))
        self.assertFalse(style.show_checkmark)
        self.assertIsNone(style.swatch_border_color)


if __name__ == "__main__":
    unittest.main()
