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
XPUB_VERSION = bytes.fromhex("0488b21e")
LPUB_VERSION = bytes.fromhex("019da462")
MPUB_VERSION = bytes.fromhex("01b26ef6")
VALID_VERSIONS = {ZPUB_VERSION, XPUB_VERSION, LPUB_VERSION, MPUB_VERSION}
ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BECH32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"

_RIPEMD_R = (
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 7, 4, 13, 1, 10, 6, 15, 3, 12, 0, 9, 5,
    2, 14, 11, 8, 3, 10, 14, 4, 9, 15, 8, 1, 2, 7, 0, 6, 13, 11, 5, 12, 1, 9, 11, 10, 0, 8, 12, 4,
    13, 3, 7, 15, 14, 5, 6, 2, 4, 0, 5, 9, 7, 12, 2, 10, 14, 1, 3, 8, 11, 6, 15, 13,
)
_RIPEMD_R_PRIME = (
    5, 14, 7, 0, 9, 2, 11, 4, 13, 6, 15, 8, 1, 10, 3, 12, 6, 11, 3, 7, 0, 13, 5, 10, 14, 15, 8, 12,
    4, 9, 1, 2, 15, 5, 1, 3, 7, 14, 6, 9, 11, 8, 12, 2, 10, 0, 4, 13, 8, 6, 4, 1, 3, 11, 15, 0,
    5, 12, 2, 13, 9, 7, 10, 14, 12, 15, 10, 4, 1, 5, 8, 7, 6, 2, 13, 14, 0, 3, 9, 11,
)
_RIPEMD_S = (
    11, 14, 15, 12, 5, 8, 7, 9, 11, 13, 14, 15, 6, 7, 9, 8, 7, 6, 8, 13, 11, 9, 7, 15, 7, 12, 15, 9,
    11, 7, 13, 12, 11, 13, 6, 7, 14, 9, 13, 15, 14, 8, 13, 6, 5, 12, 7, 5, 11, 12, 14, 15, 14, 15,
    9, 8, 9, 14, 5, 6, 8, 6, 5, 12, 9, 15, 5, 11, 6, 8, 13, 12, 5, 12, 13, 14, 11, 8, 5, 6,
)
_RIPEMD_S_PRIME = (
    8, 9, 9, 11, 13, 15, 15, 5, 7, 7, 8, 11, 14, 14, 12, 6, 9, 13, 15, 7, 12, 8, 9, 11, 7, 7, 12, 7,
    6, 15, 13, 11, 9, 7, 15, 11, 8, 6, 6, 14, 12, 13, 5, 14, 13, 13, 7, 5, 15, 5, 8, 11, 14, 14,
    6, 14, 6, 9, 12, 9, 12, 5, 15, 8, 8, 5, 12, 9, 12, 5, 14, 6, 8, 13, 6, 5, 15, 13, 11, 11,
)


def _base58check(value: str) -> bytes:
    padding = len(value) - len(value.lstrip("1"))
    number = 0
    for character in value:
        if character not in ALPHABET:
            raise ValueError("公開鍵の形式が正しくありません。")
        number = number * 58 + ALPHABET.index(character)
    byte_length = (number.bit_length() + 7) // 8
    raw = b"\0" * padding + (number.to_bytes(byte_length, "big") if number else b"")
    if len(raw) != 82:
        raise ValueError("公開鍵の長さが正しくありません。")
    if hashlib.sha256(hashlib.sha256(raw[:-4]).digest()).digest()[:4] != raw[-4:]:
        raise ValueError("公開鍵のチェックサムが正しくありません。")
    return raw[:-4]


def _rotate_left(value: int, count: int) -> int:
    return ((value << count) | (value >> (32 - count))) & 0xFFFFFFFF


def _ripemd_function(round_index: int, x: int, y: int, z: int) -> int:
    if round_index < 16:
        return x ^ y ^ z
    if round_index < 32:
        return (x & y) | (~x & z)
    if round_index < 48:
        return (x | ~y) ^ z
    if round_index < 64:
        return (x & z) | (y & ~z)
    return x ^ (y | ~z)


def ripemd160(data: bytes) -> bytes:
    """Return RIPEMD-160 without relying on the OpenSSL hashlib backend."""
    bit_length = len(data) * 8
    padded = data + b"\x80"
    padded += b"\0" * ((56 - len(padded) % 64) % 64) + bit_length.to_bytes(8, "little")
    state = [0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0]
    left_constants = (0x00000000, 0x5A827999, 0x6ED9EBA1, 0x8F1BBCDC, 0xA953FD4E)
    right_constants = (0x50A28BE6, 0x5C4DD124, 0x6D703EF3, 0x7A6D76E9, 0x00000000)
    for offset in range(0, len(padded), 64):
        words = [int.from_bytes(padded[offset + index:offset + index + 4], "little") for index in range(0, 64, 4)]
        left = state.copy()
        right = state.copy()
        for index in range(80):
            value = (_rotate_left(
                (left[0] + _ripemd_function(index, left[1], left[2], left[3])
                 + words[_RIPEMD_R[index]] + left_constants[index // 16]) & 0xFFFFFFFF,
                _RIPEMD_S[index],
            ) + left[4]) & 0xFFFFFFFF
            left = [left[4], value, left[1], _rotate_left(left[2], 10), left[3]]
            value = (_rotate_left(
                (right[0] + _ripemd_function(79 - index, right[1], right[2], right[3])
                 + words[_RIPEMD_R_PRIME[index]] + right_constants[index // 16]) & 0xFFFFFFFF,
                _RIPEMD_S_PRIME[index],
            ) + right[4]) & 0xFFFFFFFF
            right = [right[4], value, right[1], _rotate_left(right[2], 10), right[3]]
        combined = (state[1] + left[2] + right[3]) & 0xFFFFFFFF
        state = [
            combined,
            (state[2] + left[3] + right[4]) & 0xFFFFFFFF,
            (state[3] + left[4] + right[0]) & 0xFFFFFFFF,
            (state[4] + left[0] + right[1]) & 0xFFFFFFFF,
            (state[0] + left[1] + right[2]) & 0xFFFFFFFF,
        ]
    return b"".join(value.to_bytes(4, "little") for value in state)


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


def derive_ltc_address(extended_public_key: str, index: int) -> str:
    """Derive ``m/.../0/index`` from a supported account extended public key."""
    payload = _base58check(extended_public_key.strip())
    if payload[:4] not in VALID_VERSIONS or payload[45] not in (2, 3) or index < 0 or index >= 2**31:
        raise ValueError("Litecoin用zpub/xpub/Lpub/Mpubの形式が正しくありません。")
    public_key, chain_code = payload[45:78], payload[13:45]
    public_key, chain_code = _child(public_key, chain_code, 0)
    public_key, _ = _child(public_key, chain_code, index)
    digest = ripemd160(hashlib.sha256(public_key).digest())
    return _bech32(digest)
