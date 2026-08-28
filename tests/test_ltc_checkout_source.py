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

        self.assertIn('return product.get("price_ltc")', source)
        self.assertIn("round(product_price * LITOSHI) < 1", source)
        self.assertIn('f"{amount:.8f}"', source)


if __name__ == "__main__":
    unittest.main()
