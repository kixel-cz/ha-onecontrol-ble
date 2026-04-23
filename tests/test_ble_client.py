"""BLE client tests (ble_client.py)."""

import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.onecontrol_ble.ble_client import SoloMiniClient
from custom_components.onecontrol_ble.protocol import (
    NACK,
    SecurityData,
)
from tests.conftest import TEST_LTK, TEST_SESSION_ID, TEST_SESSION_KEY


def make_session_response(random_b: bytes) -> bytes:
    return bytes([0x00, 0x0A, 0x90, 0x00]) + random_b


def make_open_response(cc: int) -> bytes:
    return bytes([0x00, 0x0E, 0x01] + [0] * 9 + list(struct.pack("<H", cc)) + [0x00, 0x00])


class FakeBleakClient:
    def __init__(self, responses: list[bytes]):
        self._responses = list(responses)
        self._notify_callback = None
        self.written = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def start_notify(self, uuid, callback, **kwargs):
        self._notify_callback = callback

    async def write_gatt_char(self, uuid, data, response=True):
        self.written.append(bytes(data))
        if self._responses and self._notify_callback:
            resp = self._responses.pop(0)
            self._notify_callback(None, bytearray(resp))


@pytest.fixture
def security() -> SecurityData:
    return SecurityData(
        ltk=bytes.fromhex(TEST_LTK),
        session_key=bytes.fromhex(TEST_SESSION_KEY),
        session_id=bytes.fromhex(TEST_SESSION_ID),
        user_id=0,
        last_cc=0,
    )


def make_client(
    security: SecurityData, responses: list[bytes]
) -> tuple[SoloMiniClient, FakeBleakClient]:
    fake_ble = FakeBleakClient(responses)
    client = SoloMiniClient(
        address="AA:BB:CC:DD:EE:FF",
        security=security,
        action=0,
    )
    return client, fake_ble


class TestOpenGate:
    @pytest.mark.asyncio
    async def test_successful_open_direct(self, security):
        random_b = bytes(range(8))
        session_resp = make_session_response(random_b)
        probe_resp = make_open_response(cc=5)  # probe response
        open_resp = make_open_response(cc=6)  # open response

        client, fake_ble = make_client(security, [session_resp, probe_resp, open_resp])

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient", return_value=fake_ble
        ):
            result = await client.open_gate()

        assert result is True
        assert len(fake_ble.written) == 3
        assert fake_ble.written[0][:4] == bytes([0x00, 0x0A, 0x90, 0x02])

    @pytest.mark.asyncio
    async def test_nack_triggers_probe(self, security):
        random_b = bytes(range(8))
        session_resp = make_session_response(random_b)
        nack_resp = NACK
        probe_resp = make_open_response(cc=50)
        open_resp = make_open_response(cc=51)

        client, fake_ble = make_client(security, [session_resp, nack_resp, probe_resp, open_resp])

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient", return_value=fake_ble
        ):
            result = await client.open_gate()

        assert result is True
        assert len(fake_ble.written) == 4

    @pytest.mark.asyncio
    async def test_lock_prevents_concurrent(self, security):
        client = SoloMiniClient(
            address="AA:BB:CC:DD:EE:FF",
            security=security,
            action=0,
        )

        await client._lock.acquire()
        try:
            result = await client.open_gate()
            assert result is False
        finally:
            client._lock.release()

    @pytest.mark.asyncio
    async def test_last_cc_updated_after_open(self, security):
        security.last_cc = 0
        random_b = bytes(range(8))
        session_resp = make_session_response(random_b)
        probe_resp = make_open_response(cc=42)
        open_resp = make_open_response(cc=43)

        client, fake_ble = make_client(security, [session_resp, probe_resp, open_resp])

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient", return_value=fake_ble
        ):
            await client.open_gate()

        assert client.security.last_cc > 0

    @pytest.mark.asyncio
    async def test_connection_error_retries(self, security):
        call_count = 0

        async def failing_context(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise OSError("BLE connection failed")

        fake_ctx = MagicMock()
        fake_ctx.__aenter__ = failing_context
        fake_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient", return_value=fake_ctx
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await security_client(security).open_gate()

        assert result is False
        assert call_count == 3


def security_client(security: SecurityData) -> SoloMiniClient:
    return SoloMiniClient(
        address="AA:BB:CC:DD:EE:FF",
        security=security,
        action=0,
    )


class TestParseMitmLog:
    def test_parses_all_fields(self):
        from custom_components.onecontrol_ble.protocol import parse_mitm_log

        log = (
            '"ltk":"AABBCCDDAABBCCDDAABBCCDDAABBCCDD"'
            '"sessionKey":"11223344112233441122334411223344"'
            '"sessionID":"5566778855667788"'
            '"lastCC":42'
        )
        result = parse_mitm_log(log)
        assert result["ltk"] == "AABBCCDDAABBCCDDAABBCCDDAABBCCDD"
        assert result["session_key"] == "11223344112233441122334411223344"
        assert result["session_id"] == "5566778855667788"
        assert result["last_cc"] == 42

    def test_empty_log(self):
        from custom_components.onecontrol_ble.protocol import parse_mitm_log

        assert parse_mitm_log("") == {}

    def test_partial_log(self):
        from custom_components.onecontrol_ble.protocol import parse_mitm_log

        result = parse_mitm_log('"ltk":"AABB"')
        assert result.get("ltk") == "AABB"
        assert "session_key" not in result

    def test_uppercase_output(self):
        from custom_components.onecontrol_ble.protocol import parse_mitm_log

        result = parse_mitm_log('"ltk":"aabbccdd"')
        assert result["ltk"] == "AABBCCDD"
