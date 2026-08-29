"""Regression checks for the button-based gacha panel."""

from pathlib import Path
import unittest


GACHA_COG = Path(__file__).parents[1] / "Cogs" / "gacha.py"


class GachaPanelSourceTests(unittest.TestCase):
    def test_panel_uses_a_public_persistent_button(self):
        source = GACHA_COG.read_text(encoding="utf-8")

        self.assertIn("class GachaPanelView", source)
        self.assertIn("super().__init__(timeout=None)", source)
        self.assertIn('custom_id=f"gacha_draw_{gacha_id}"', source)
        self.assertIn("interaction.channel.send(embed=embed, view=GachaPanelView", source)

    def test_server_button_responses_remain_ephemeral(self):
        source = GACHA_COG.read_text(encoding="utf-8")

        self.assertIn('f"結果をDMに送りました。商品名:', source)
        self.assertIn("ephemeral=True", source)
        self.assertIn("await interaction.response.defer(ephemeral=True)", source)


if __name__ == "__main__":
    unittest.main()
