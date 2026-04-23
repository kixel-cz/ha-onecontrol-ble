"""1Control SoloMini RE — BLE protocol."""

from __future__ import annotations

import hashlib
import re
import struct
from dataclasses import dataclass

from Crypto.Cipher import AES

TX_CHAR_UUID = "d973f2e1-b19e-11e2-9e96-0800200c9a66"
RX_CHAR_UUID = "d973f2e2-b19e-11e2-9e96-0800200c9a66"
NACK = bytes([0x00, 0x02, 0x01, 0xCE])
CCM_TAG_LEN = 6


@dataclass
class SecurityData:
    ltk: bytes  # Long Term Key — from pairing
    session_key: bytes  # SHA256(LTK+sessionID)[:16]
    session_id: bytes  # sessionID
    user_id: int = 0
    last_cc: int = 0  # Last known CC - optional
    battery_raw: int | None = None  # Raw battery value?


def derive_session(ltk: bytes, random_a: bytes, random_b: bytes) -> tuple[bytes, bytes]:
    data = random_a[:8] + random_b[:8]
    sid = hashlib.sha256(data).digest()[:8]
    sk = hashlib.sha256(ltk[:16] + sid).digest()[:16]
    return sid, sk


def build_tlv(payload: bytes) -> bytes:
    return bytes([0x00, len(payload)]) + payload


def build_open_command(
    session_key: bytes,
    session_id: bytes,
    last_cc: int,
    user_id: int = 0,
    action: int = 0,
) -> bytes:
    cc = last_cc + 1
    nonce = session_id[:8] + struct.pack("<I", cc)
    aad = struct.pack("<H", user_id) + struct.pack("<I", cc) + b"\x01"
    cipher = AES.new(session_key, AES.MODE_CCM, nonce=nonce, mac_len=CCM_TAG_LEN)
    cipher.update(aad)
    ct, tag = cipher.encrypt_and_digest(bytes([0x01, action & 0xFF]))
    payload = b"\x01" + ct + tag + struct.pack("<H", user_id) + struct.pack("<I", cc)
    return build_tlv(payload)


def is_nack(packet: bytes) -> bool:
    return packet[:4] == NACK


def extract_response_cc(packet: bytes) -> int | None:
    if len(packet) >= 16:
        return int.from_bytes(packet[12:14], "little")
    return None


def parse_greeting(packet: bytes) -> tuple[bytes, int, int, int] | None:
    if len(packet) < 19 or packet[0] != 0x00 or packet[1] != 0x11:
        return None
    p = packet[2:]
    sid = p[1:9]
    battery_raw = int.from_bytes(p[9:11], "little")
    uid = int.from_bytes(p[11:13], "little")
    cc = int.from_bytes(p[13:15], "little")
    return sid, battery_raw, uid, cc


def parse_mitm_log(log_text: str) -> dict:
    result: dict = {}
    for key, pattern in [
        ("ltk", r'"ltk":"([0-9A-Fa-f]+)"'),
        ("session_key", r'"sessionKey":"([0-9A-Fa-f]+)"'),
        ("session_id", r'"sessionID":"([0-9A-Fa-f]+)"'),
        ("last_cc", r'"lastCC":(\d+)'),
    ]:
        m = re.search(pattern, log_text)
        if m:
            result[key] = m.group(1).upper() if key != "last_cc" else int(m.group(1))
    return result
