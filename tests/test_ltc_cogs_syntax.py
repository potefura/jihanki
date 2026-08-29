"""Regression checks for the LTC extension source."""

import ast
from pathlib import Path
import unittest


LTC_COG = Path(__file__).parents[1] / "Cogs" / "ltc_cogs.py"


class LTCCogSyntaxTests(unittest.TestCase):
    def test_wallet_creation_is_a_complete_single_line_call(self):
        source = LTC_COG.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(LTC_COG))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "create"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "BitcoinWallet"
        ]

        self.assertEqual(1, len(calls))
        call = calls[0]
        self.assertEqual(call.lineno, call.end_lineno)
        self.assertEqual({"name", "network", "db_uri"}, {keyword.arg for keyword in call.keywords})

    def test_order_metadata_does_not_duplicate_private_keys(self):
        source = LTC_COG.read_text(encoding="utf-8")

        self.assertNotIn('"wif":', source)
        self.assertNotIn('"mnemonic":', source)
        self.assertIn("os.chmod(database_file, 0o600)", source)

    def test_checkout_acknowledges_before_creating_the_wallet(self):
        source = LTC_COG.read_text(encoding="utf-8")

        defer_position = source.index("await interaction.response.defer(ephemeral=True)", source.index("async def start_ltc_order"))
        wallet_position = source.index("create_order_wallet", defer_position)
        self.assertLess(defer_position, wallet_position)

    def test_dm_statuses_use_embeds_and_copyable_amount(self):
        source = LTC_COG.read_text(encoding="utf-8")

        self.assertIn('name="送金額（タップしてコピー）"', source)
        self.assertIn('order_embed("決済が完了しました"', source)
        self.assertNotIn('interaction.response.send_message("DMを受信できるようにしてからやり直してください。"', source)

    def test_order_has_expiry_and_paid_button_rate_limit(self):
        source = LTC_COG.read_text(encoding="utf-8")

        self.assertIn("timeout=3600", source)
        self.assertIn("async def on_timeout", source)
        self.assertIn("timedelta(hours=1)", source)
        self.assertIn("len(attempts) >= 5", source)
        self.assertIn('"DMを送信しました", "決済用ウォレットをDMに送りました。"), ephemeral=True', source)

    def test_underpayment_is_forwarded_to_the_recipient(self):
        source = LTC_COG.read_text(encoding="utf-8")

        underpayment = source[source.index("if received < self.required"):source.index("target = received")]
        self.assertIn("sweep_order", underpayment)
        self.assertIn("受領済みLTCは受取先へ送金しました", underpayment)
        self.assertIn("confirmed < received", underpayment)

    def test_customer_messages_do_not_call_the_recipient_a_seller(self):
        source = LTC_COG.read_text(encoding="utf-8")

        self.assertIn("受領済みLTCは受取先へ送金しました", source)

    def test_sweep_imports_litecoinspace_utxos_and_handles_wallet_errors(self):
        source = LTC_COG.read_text(encoding="utf-8")

        self.assertIn('f"{LTC_API}/address/{address}/utxo"', source)
        self.assertIn('f"{LTC_API}/tx/{txid}"', source)
        self.assertIn('wallet.utxos_update(networks="litecoin", utxos=utxos)', source)
        self.assertIn("ValueError, WalletError", source)
        self.assertNotIn("wallet.scan()", source)


if __name__ == "__main__":
    unittest.main()
