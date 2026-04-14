"""
1Control SoloMini BLE Protocol — kompletní implementace
Reverse-engineered z it.onecontrol.apk v2.6.4
"""
from __future__ import annotations
import hashlib, logging, struct
from dataclasses import dataclass, field
from typing import Optional
from Crypto.Cipher import AES
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric.ec import (
    ECDH, SECP256R1, EllipticCurvePublicNumbers, generate_private_key,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, PublicFormat,
)

_LOGGER = logging.getLogger(__name__)

SERVICE_UUID = "d973f2e0-b19e-11e2-9e96-0800200c9a66"
TX_CHAR_UUID = "d973f2e1-b19e-11e2-9e96-0800200c9a66"
RX_CHAR_UUID = "d973f2e2-b19e-11e2-9e96-0800200c9a66"
SECURITY_REQUEST_ID = 0x90
CCM_TAG_LEN = 6
NACK = bytes([0x0A, 0x00, 0xFF, 0xFF])

def sha256_n(data: bytes, n: int) -> bytes:
    return hashlib.sha256(data).digest()[:n]

def generate_ec_keypair():
    priv = generate_private_key(SECP256R1(), default_backend())
    return priv, priv.public_key()

def pubkey_to_64b(public_key) -> bytes:
    raw = public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return raw[1:]  # strip 0x04

def pubkey_from_64b(data: bytes):
    assert len(data) == 64
    nums = EllipticCurvePublicNumbers(
        int.from_bytes(data[:32], "big"),
        int.from_bytes(data[32:], "big"),
        SECP256R1()
    )
    return nums.public_key(default_backend())

def ecdh_ltk(private_key, device_pubkey_64: bytes) -> bytes:
    """x2.java: LTK = SHA256(ECDH_shared_secret)[0:16]"""
    shared = private_key.exchange(ECDH(), pubkey_from_64b(device_pubkey_64))
    return sha256_n(shared, 16)

def derive_session(ltk: bytes, random_a: bytes, random_b: bytes):
    """w2.java: sessionID=SHA256(rA||rB)[0:8], sessionKey=SHA256(LTK||sessionID)[0:16]"""
    sid = sha256_n(random_a[:8] + random_b[:8], 8)
    sk  = sha256_n(ltk[:16] + sid, 16)
    return sid, sk

def build_tlv(payload: bytes) -> bytes:
    return bytes([0x00, len(payload)]) + payload

def build_start_pairing(phone_pubkey_64: bytes) -> bytes:
    """x2.java + StartPairingRequest: [00][42][90][01][pubkey_64B] = 68B"""
    return build_tlv(bytes([SECURITY_REQUEST_ID, 0x01]) + phone_pubkey_64)

def build_start_session(random_a: bytes) -> bytes:
    """w2.java + StartSessionRequest: [00][0A][90][02][randomA_8B] = 12B"""
    return build_tlv(bytes([SECURITY_REQUEST_ID, 0x02]) + random_a[:8])

def parse_greeting(packet: bytes):
    """[00][11][01][sessionID_8B][extra_2B][userID_2B][CC_lo][CC_hi][00][00]"""
    if len(packet) < 19 or packet[0] != 0x00 or packet[1] != 0x11:
        return None
    p = packet[2:]
    return p[1:9], p[9:11], p[11] | (p[12] << 8), p[13] | (p[14] << 8)

def build_open_command(session_key, session_id, cc, user_id=0, action=1) -> bytes:
    """e.h(): 17B open packet s AES-CCM-128"""
    cc_open = cc + 1
    nonce  = session_id[:8] + struct.pack("<I", cc_open)
    aad    = struct.pack("<H", user_id) + struct.pack("<I", cc_open) + b"\x01"
    cipher = AES.new(session_key, AES.MODE_CCM, nonce=nonce, mac_len=CCM_TAG_LEN)
    cipher.update(aad)
    ct, tag = cipher.encrypt_and_digest(struct.pack("<H", action))
    payload = b"\x01" + ct + tag + struct.pack("<H", user_id) + struct.pack("<H", cc_open) + b"\x00\x00"
    return build_tlv(payload)

def is_nack(packet: bytes) -> bool:
    return packet[:4] == NACK or (len(packet) >= 1 and packet[0] == 0x0A)

def parse_start_pairing_response(packet: bytes) -> Optional[bytes]:
    """Extrahuje 64B device pubkey z StartPairing response."""
    if len(packet) < 3:
        return None
    payload = packet[2:]  # skip type+len
    # Response: [status_byte][device_pubkey_64B...]
    if len(payload) >= 65:
        return payload[1:65]  # skip status byte
    elif len(payload) >= 64:
        return payload[:64]
    return None

def parse_start_session_response(packet: bytes) -> Optional[bytes]:
    """Extrahuje 8B randomB z StartSession response."""
    if len(packet) < 3:
        return None
    payload = packet[2:]
    if len(payload) >= 9:
        return payload[1:9]  # skip status
    elif len(payload) >= 8:
        return payload[:8]
    return None

@dataclass
class SecurityData:
    ltk:             bytes
    private_key_pem: Optional[bytes] = field(default=None, repr=False)
    user_id:         int = 0
    last_cc:         int = 0
    session_id:      Optional[bytes] = field(default=None, repr=False)
    session_key:     Optional[bytes] = field(default=None, repr=False)

    def update_session(self, random_a, random_b):
        self.session_id, self.session_key = derive_session(self.ltk, random_a, random_b)

    def to_dict(self):
        d = {"ltk": self.ltk.hex(), "user_id": self.user_id, "last_cc": self.last_cc}
        if self.private_key_pem:
            d["private_key_pem"] = self.private_key_pem.decode()
        return d

    @classmethod
    def from_dict(cls, d):
        pem = d.get("private_key_pem")
        return cls(
            ltk=bytes.fromhex(d["ltk"]),
            private_key_pem=pem.encode() if pem else None,
            user_id=d.get("user_id", 0),
            last_cc=d.get("last_cc", 0),
        )
