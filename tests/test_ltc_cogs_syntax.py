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


if __name__ == "__main__":
    unittest.main()
