"""Regression checks for direct-to-wallet LTC checkout."""

from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
LTC_COG = ROOT / "Cogs" / "ltc_cogs.py"
PAYMENT_COG = ROOT / "Cogs" / "payment.py"
REQUIREMENTS = ROOT / "requirements.txt"


class LTCCogSyntaxTests(unittest.TestCase):
    def test_checkout_uses_the_configured_wallet_directly(self):
        checkout = LTC_COG.read_text(encoding="utf-8")
        payment = PAYMENT_COG.read_text(encoding="utf-8")
        self.assertIn('address = settings.get("ltc_wallet")', checkout)
        self.assertIn('"initial_confirmed": initial_confirmed', checkout)
        self.assertIn("order_receipts(self.order, confirmed, pending)", checkout)
        self.assertIn("if address in ACTIVE_WALLETS", checkout)
        self.assertIn('ACTIVE_WALLETS.discard(self.order["address"])', checkout)
        self.assertIn("ltc_wallet=address", payment)
        self.assertNotIn("bitcoinlib", checkout + payment + REQUIREMENTS.read_text(encoding="utf-8"))
        self.assertNotIn("sweep_order", checkout)

    def test_payment_setup_only_accepts_a_public_ltc_address(self):
        payment = PAYMENT_COG.read_text(encoding="utf-8")

        self.assertIn("LTC_ADDRESS.fullmatch(address)", payment)
        self.assertIn("注文のLTCはこのアドレスへ直接送金されます", payment)
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

    def test_underpayment_needs_no_second_transfer(self):
        source = LTC_COG.read_text(encoding="utf-8")
        underpayment = source[source.index("if received < self.required"):source.index("target = received")]

        self.assertIn("入金先への着金は確認済みです", underpayment)
        self.assertNotIn("sweep", underpayment)


if __name__ == "__main__":
    unittest.main()
