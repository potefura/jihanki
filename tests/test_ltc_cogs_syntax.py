"""Regression checks for watch-only LTC checkout."""

from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
LTC_COG = ROOT / "Cogs" / "ltc_cogs.py"
PAYMENT_COG = ROOT / "Cogs" / "payment.py"
REQUIREMENTS = ROOT / "requirements.txt"


class LTCCogSyntaxTests(unittest.TestCase):
    def test_checkout_uses_a_unique_zpub_address_without_global_locks(self):
        checkout = LTC_COG.read_text(encoding="utf-8")
        payment = PAYMENT_COG.read_text(encoding="utf-8")
        self.assertIn("derive_ltc_address(zpub, address_index)", checkout)
        self.assertIn("ltc_address_index=address_index + 1", checkout)
        self.assertIn("ltc_zpub=zpub", payment)
        self.assertNotIn("ACTIVE_WALLETS", checkout)
        self.assertNotIn("order_receipts", checkout)
        self.assertNotIn("bitcoinlib", checkout + payment + REQUIREMENTS.read_text(encoding="utf-8"))
        self.assertNotIn("sweep_order", checkout)

    def test_payment_setup_only_accepts_a_public_zpub(self):
        payment = PAYMENT_COG.read_text(encoding="utf-8")

        self.assertIn("derive_ltc_address(zpub, 0)", payment)
        self.assertIn("シードフレーズ・秘密鍵はBOTへ送信しないでください", payment)

    def test_dm_statuses_use_embeds_and_copyable_amount(self):
        source = LTC_COG.read_text(encoding="utf-8")

        self.assertIn('name="送金額（タップしてコピー）"', source)
        self.assertIn('order_embed("決済が完了しました"', source)
        self.assertIn("await interaction.response.defer(ephemeral=True)", source)

    def test_order_has_expiry_and_paid_button_rate_limit(self):
        source = LTC_COG.read_text(encoding="utf-8")

        self.assertIn("timeout=3600", source)
        self.assertIn("async def on_timeout", source)
        self.assertIn("timedelta(hours=1)", source)
        self.assertIn("len(attempts) >= 5", source)

    def test_cancel_is_immediate_and_confirmation_does_not_poll(self):
        source = LTC_COG.read_text(encoding="utf-8")
        settle = source[source.index("async def _settle"):source.index('@ui.button(label="送金完了"')]

        self.assertIn("if cancelled:", settle)
        self.assertLess(settle.index("if cancelled:"), settle.index("address_balance"))
        self.assertNotIn("for _ in range", settle)
        self.assertNotIn("asyncio.sleep(30)", settle)

    def test_underpayment_needs_no_second_transfer(self):
        source = LTC_COG.read_text(encoding="utf-8")
        underpayment = source[source.index("if received < self.required"):source.index("if confirmed < self.required")]

        self.assertIn("入金先への着金は確認済みです", underpayment)
        self.assertNotIn("sweep", underpayment)


if __name__ == "__main__":
    unittest.main()
