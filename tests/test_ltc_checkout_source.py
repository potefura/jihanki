"""Regression checks for the vending-machine LTC checkout path."""

from pathlib import Path
import unittest


VENDING_COG = Path(__file__).parents[1] / "Cogs" / "vending.py"


class LTCCheckoutSourceTests(unittest.TestCase):
    def test_ltc_is_not_blocked_before_product_selection(self):
        source = VENDING_COG.read_text(encoding="utf-8")

        self.assertNotIn("安全な鍵管理が設定されるまで利用できません", source)
        self.assertIn("await start_ltc_order(", source)

    def test_missing_ltc_prices_are_not_treated_as_free(self):
        source = VENDING_COG.read_text(encoding="utf-8")

        self.assertIn("def get_yen_price(", source)
        self.assertIn("def convert_yen_to_ltc(", source)
        self.assertIn('Decimal("0.00000001")', source)
        self.assertIn("ltc_discount_percent", source)

    def test_product_editor_uses_shared_price_and_ltc_discount(self):
        source = VENDING_COG.read_text(encoding="utf-8")

        self.assertIn('label="共通価格（円）"', source)
        self.assertIn('label="LTC割引率（%）"', source)
        self.assertNotIn('label="PayPay価格"', source)
        self.assertNotIn('label="Kyash価格"', source)

    def test_dm_checkout_retains_the_originating_guild(self):
        source = VENDING_COG.read_text(encoding="utf-8")

        self.assertIn("purchase_guild = interaction.guild", source)
        self.assertIn("purchase_guild=purchase_guild", source)
        self.assertIn("purchase_guild or interaction.guild", source)

    def test_purchase_result_is_only_ephemeral_in_a_server(self):
        source = VENDING_COG.read_text(encoding="utf-8")

        self.assertIn("server_interaction = interaction.guild is not None", source)
        self.assertIn("defer(ephemeral=server_interaction)", source)
        self.assertIn("send(embed=embed, ephemeral=server_interaction)", source)


if __name__ == "__main__":
    unittest.main()
