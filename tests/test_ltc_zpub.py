"""Unit tests for dependency-free zpub address derivation."""

import hashlib
import unittest

from Cogs.ltc_zpub import ALPHABET, G, ZPUB_VERSION, derive_ltc_address


def base58check(payload: bytes) -> str:
    raw = payload + hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    number, encoded = int.from_bytes(raw, "big"), ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = ALPHABET[remainder] + encoded
    return "1" * (len(raw) - len(raw.lstrip(b"\0"))) + encoded


class LTCZpubTests(unittest.TestCase):
    def setUp(self):
        public_key = bytes([2 | (G[1] & 1)]) + G[0].to_bytes(32, "big")
        payload = ZPUB_VERSION + b"\x03" + b"\0" * 4 + b"\0" * 4 + b"\x01" * 32 + public_key
        self.zpub = base58check(payload)

    def test_derives_distinct_litecoin_bech32_addresses(self):
        first = derive_ltc_address(self.zpub, 0)
        second = derive_ltc_address(self.zpub, 1)

        self.assertTrue(first.startswith("ltc1q"))
        self.assertNotEqual(first, second)

    def test_rejects_invalid_zpub(self):
        with self.assertRaises(ValueError):
            derive_ltc_address("zpub-invalid", 0)


if __name__ == "__main__":
    unittest.main()
