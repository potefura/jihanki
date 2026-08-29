"""Minimal watch-only zpub derivation for Litecoin native SegWit addresses."""
from __future__ import annotations

import hashlib
import hmac


P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
G = (
    0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
    0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8,
)
ZPUB_VERSION = bytes.fromhex("04b24746")
ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BECH32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _base58check(value: str) -> bytes:
    number = 0
    for character in value:
        if character not in ALPHABET:
            raise ValueError("zpubの形式が正しくありません。")
        number = number * 58 + ALPHABET.index(character)
    byte_length = max(1, (number.bit_length() + 7) // 8)
    raw = b"\0" * (len(value) - len(value.lstrip("1"))) + number.to_bytes(byte_length, "big")
    if len(raw) != 82 or hashlib.sha256(hashlib.sha256(raw[:-4]).digest()).digest()[:4] != raw[-4:]:
        raise ValueError("zpubのチェックサムが正しくありません。")
    return raw[:-4]


def _point_add(left, right):
    if left is None:
        return right
    if right is None:
        return left
    if left[0] == right[0] and (left[1] + right[1]) % P == 0:
        return None
    slope = ((3 * left[0] * left[0]) * pow(2 * left[1], P - 2, P)) % P if left == right else (
        (right[1] - left[1]) * pow((right[0] - left[0]) % P, P - 2, P)
    ) % P
    x = (slope * slope - left[0] - right[0]) % P
    return x, (slope * (left[0] - x) - left[1]) % P


def _multiply(number: int, point=G):
    result = None
    while number:
        if number & 1:
            result = _point_add(result, point)
        point = _point_add(point, point)
        number >>= 1
    return result


def _decode_point(public_key: bytes):
    if len(public_key) != 33 or public_key[0] not in (2, 3):
        raise ValueError("圧縮公開鍵の形式が正しくありません。")
    x = int.from_bytes(public_key[1:], "big")
    if x >= P:
        raise ValueError("公開鍵が曲線上にありません。")
    y = pow((pow(x, 3, P) + 7) % P, (P + 1) // 4, P)
    if pow(y, 2, P) != (pow(x, 3, P) + 7) % P:
        raise ValueError("公開鍵が曲線上にありません。")
    if y & 1 != public_key[0] & 1:
        y = P - y
    return x, y


def _encode_point(point) -> bytes:
    return bytes([2 | (point[1] & 1)]) + point[0].to_bytes(32, "big")


def _child(public_key: bytes, chain_code: bytes, index: int):
    digest = hmac.new(chain_code, public_key + index.to_bytes(4, "big"), hashlib.sha512).digest()
    tweak = int.from_bytes(digest[:32], "big")
    if tweak == 0 or tweak >= N:
        raise ValueError("アドレスを導出できませんでした。")
    point = _point_add(_multiply(tweak), _decode_point(public_key))
    if point is None:
        raise ValueError("アドレスを導出できませんでした。")
    return _encode_point(point), digest[32:]


def _polymod(values):
    result = 1
    generators = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    for value in values:
        top, result = result >> 25, ((result & 0x1FFFFFF) << 5) ^ value
        for index, generator in enumerate(generators):
            if (top >> index) & 1:
                result ^= generator
    return result


def _bech32(program: bytes) -> str:
    if len(program) != 20:
        raise ValueError("P2WPKH witness programは20バイトである必要があります。")
    data, accumulator, bits = [0], 0, 0
    for byte in program:
        accumulator = (accumulator << 8) | byte
        bits += 8
        while bits >= 5:
            bits -= 5
            data.append((accumulator >> bits) & 31)
    # HASH160 is exactly 160 bits, so a P2WPKH program must not need padding.
    if bits:
        raise ValueError("witness programのビット長が正しくありません。")
    expanded = [ord(c) >> 5 for c in "ltc"] + [0] + [ord(c) & 31 for c in "ltc"]
    polymod = _polymod(expanded + data + [0] * 6) ^ 1
    checksum = [(polymod >> (5 * (5 - index))) & 31 for index in range(6)]
    return "ltc1" + "".join(BECH32[value] for value in data + checksum)


def derive_ltc_address(zpub: str, index: int) -> str:
    """Derive external-chain address ``m/.../0/index`` from an account zpub."""
    payload = _base58check(zpub.strip())
    if payload[:4] != ZPUB_VERSION or payload[45] not in (2, 3) or index < 0 or index >= 2**31:
        raise ValueError("Litecoin用zpubの形式が正しくありません。")
    public_key, chain_code = payload[45:78], payload[13:45]
    public_key, chain_code = _child(public_key, chain_code, 0)
    public_key, _ = _child(public_key, chain_code, index)
    digest = hashlib.new("ripemd160", hashlib.sha256(public_key).digest()).digest()
    return _bech32(digest)
