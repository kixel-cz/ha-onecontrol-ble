"""BLE protocol tests (protocol.py)"""
import hashlib
import pytest
from custom_components.onecontrol_ble.protocol import (
    SecurityData,
    derive_session,
    build_open_command,
    is_nack,
    extract_response_cc,
    NACK,
)
from tests.conftest import (
    TEST_LTK,
    TEST_RANDOM_A,
    TEST_RANDOM_B,
    TEST_SESSION_ID,
    TEST_SESSION_KEY,
)


class TestDeriveSession:
    def test_deterministic(self):
        ltk = bytes.fromhex(TEST_LTK)
        ra  = bytes.fromhex(TEST_RANDOM_A)
        rb  = bytes.fromhex(TEST_RANDOM_B)
        sid1, sk1 = derive_session(ltk, ra, rb)
        sid2, sk2 = derive_session(ltk, ra, rb)
        assert sid1 == sid2
        assert sk1 == sk2

    def test_known_values(self):
        ltk = bytes.fromhex(TEST_LTK)
        ra  = bytes.fromhex(TEST_RANDOM_A)
        rb  = bytes.fromhex(TEST_RANDOM_B)
        sid, sk = derive_session(ltk, ra, rb)
        assert sid.hex().upper() == TEST_SESSION_ID
        assert sk.hex().upper() == TEST_SESSION_KEY

    def test_session_id_is_8_bytes(self):
        ltk = bytes.fromhex(TEST_LTK)
        ra  = bytes.fromhex(TEST_RANDOM_A)
        rb  = bytes.fromhex(TEST_RANDOM_B)
        sid, _ = derive_session(ltk, ra, rb)
        assert len(sid) == 8

    def test_session_key_is_16_bytes(self):
        ltk = bytes.fromhex(TEST_LTK)
        ra  = bytes.fromhex(TEST_RANDOM_A)
        rb  = bytes.fromhex(TEST_RANDOM_B)
        _, sk = derive_session(ltk, ra, rb)
        assert len(sk) == 16

    def test_different_random_different_session(self):
        ltk = bytes.fromhex(TEST_LTK)
        ra  = bytes.fromhex(TEST_RANDOM_A)
        rb1 = bytes.fromhex(TEST_RANDOM_B)
        rb2 = bytes(reversed(bytes.fromhex(TEST_RANDOM_B)))
        sid1, sk1 = derive_session(ltk, ra, rb1)
        sid2, sk2 = derive_session(ltk, ra, rb2)
        assert sid1 != sid2
        assert sk1 != sk2

    def test_sk_derived_from_ltk_and_sid(self):
        """SK = SHA256(LTK || SID)[:16]."""
        ltk = bytes.fromhex(TEST_LTK)
        ra  = bytes.fromhex(TEST_RANDOM_A)
        rb  = bytes.fromhex(TEST_RANDOM_B)
        sid, sk = derive_session(ltk, ra, rb)
        expected_sk = hashlib.sha256(ltk + sid).digest()[:16]
        assert sk == expected_sk


class TestBuildOpenCommand:
    def test_length(self, security):
        pkt = build_open_command(
            security.session_key, security.session_id, 0, security.user_id)
        assert len(pkt) == 17  # 2B TLV header + 15B payload

    def test_tlv_header(self, security):
        pkt = build_open_command(
            security.session_key, security.session_id, 0, security.user_id)
        assert pkt[0] == 0x00
        assert pkt[1] == 0x0F  # payload length = 15

    def test_cmd_byte(self, security):
        pkt = build_open_command(
            security.session_key, security.session_id, 0, security.user_id)
        assert pkt[2] == 0x01

    def test_cc_in_packet(self, security):
        for last_cc in [0, 1, 42, 100, 500]:
            pkt = build_open_command(
                security.session_key, security.session_id, last_cc, security.user_id)
            cc_in_pkt = int.from_bytes(pkt[13:17], "little")
            assert cc_in_pkt == last_cc + 1

    def test_user_id_in_packet(self, security):
        for uid in [0, 1, 255]:
            pkt = build_open_command(
                security.session_key, security.session_id, 0, uid)
            uid_in_pkt = int.from_bytes(pkt[11:13], "little")
            assert uid_in_pkt == uid

    def test_different_cc_different_packet(self, security):
        pkt1 = build_open_command(security.session_key, security.session_id, 0)
        pkt2 = build_open_command(security.session_key, security.session_id, 1)
        assert pkt1 != pkt2

    def test_different_action_different_packet(self, security):
        pkt1 = build_open_command(security.session_key, security.session_id, 0, action=0)
        pkt2 = build_open_command(security.session_key, security.session_id, 0, action=1)
        assert pkt1 != pkt2

    def test_action_byte_clipped_to_byte(self, security):
        """action & 0xFF — hodnota nad 255 se ořízne."""
        pkt1 = build_open_command(security.session_key, security.session_id, 0, action=0)
        pkt2 = build_open_command(security.session_key, security.session_id, 0, action=256)
        assert pkt1 == pkt2


class TestIsNack:
    def test_nack_detected(self):
        assert is_nack(NACK) is True

    def test_nack_detected_with_trailing(self):
        assert is_nack(NACK + bytes(4)) is True

    def test_not_nack(self):
        assert is_nack(bytes([0x00, 0x0E, 0x01, 0x00])) is False

    def test_empty(self):
        assert is_nack(b"") is False

    def test_too_short(self):
        assert is_nack(bytes([0x00, 0x02])) is False


class TestExtractResponseCc:
    def test_extracts_cc(self):
        # 16B response, CC=565 on position [12:14]
        pkt = bytes([0x00, 0x0E, 0x01] + [0] * 9 + [0x35, 0x02, 0x00, 0x00])
        assert extract_response_cc(pkt) == 0x0235

    def test_cc_zero(self):
        pkt = bytes(16)
        assert extract_response_cc(pkt) == 0

    def test_too_short(self):
        assert extract_response_cc(bytes(4)) is None

    def test_exactly_16_bytes(self):
        pkt = bytes([0] * 12 + [0x01, 0x00, 0x00, 0x00])
        assert extract_response_cc(pkt) == 1