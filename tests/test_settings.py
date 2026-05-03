"""Tests for set_device_name, set_dst and _do_settings."""

from __future__ import annotations

import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.onecontrol_ble.ble_client import SoloMiniClient
from custom_components.onecontrol_ble.protocol import NACK, SecurityData
from tests.conftest import TEST_LTK, TEST_SESSION_ID, TEST_SESSION_KEY


def make_session_response(random_b: bytes) -> bytes:
    return bytes([0x00, 0x0A, 0x90, 0x00]) + random_b


def make_probe_response(cc: int) -> bytes:
    return bytes([0x00, 0x0E, 0x01] + [0] * 9 + list(struct.pack("<H", cc)) + [0x00, 0x00])


def make_settings_response(cc: int) -> bytes:
    return bytes([0x00, 0x0E, 0x10, 0x00] + [0] * 8 + list(struct.pack("<H", cc)) + [0x00, 0x00])


@pytest.fixture
def security() -> SecurityData:
    return SecurityData(
        ltk=bytes.fromhex(TEST_LTK),
        session_key=bytes.fromhex(TEST_SESSION_KEY),
        session_id=bytes.fromhex(TEST_SESSION_ID),
        user_id=0,
        last_cc=0,
    )


def make_client(security: SecurityData) -> SoloMiniClient:
    return SoloMiniClient(
        address="AA:BB:CC:DD:EE:FF",
        security=security,
        action=0,
    )


class FakeSettingsClient:
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


class TestDoSettings:
    @pytest.mark.asyncio
    async def test_settings_success(self, security):
        random_b = bytes(range(8))
        responses = [
            make_session_response(random_b),
            make_probe_response(cc=10),
            make_settings_response(cc=11),
        ]
        fake_ble = FakeSettingsClient(responses)
        client = make_client(security)

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient",
            return_value=fake_ble,
        ):
            result = await client._do_settings(bytes([0x02]) + b"test")  # type: ignore[attr-defined]

        assert result is not None

    @pytest.mark.asyncio
    async def test_settings_nack_returns_none(self, security):
        random_b = bytes(range(8))
        responses = [
            make_session_response(random_b),
            NACK,
        ]
        fake_ble = FakeSettingsClient(responses)
        client = make_client(security)

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient",
            return_value=fake_ble,
        ):
            result = await client._do_settings(bytes([0x03, 0x01]))  # type: ignore[attr-defined]

        assert result is None

    @pytest.mark.asyncio
    async def test_settings_sends_three_packets(self, security):
        random_b = bytes(range(8))
        responses = [
            make_session_response(random_b),
            make_probe_response(cc=10),
            make_settings_response(cc=11),
        ]
        fake_ble = FakeSettingsClient(responses)
        client = make_client(security)

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient",
            return_value=fake_ble,
        ):
            await client._do_settings(bytes([0x03, 0x01]))  # type: ignore[attr-defined]

        assert len(fake_ble.written) == 3

    @pytest.mark.asyncio
    async def test_settings_connection_error_returns_none(self, security):
        async def fail(*args, **kwargs):
            raise OSError("BLE error")

        fake_ctx = MagicMock()
        fake_ctx.__aenter__ = fail
        fake_ctx.__aexit__ = AsyncMock(return_value=False)
        client = make_client(security)

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient",
            return_value=fake_ctx,
        ):
            result = await client._do_settings(bytes([0x02]) + b"test")  # type: ignore[attr-defined]

        assert result is None


class TestSetDeviceName:
    @pytest.mark.asyncio
    async def test_set_device_name_success(self, security):
        random_b = bytes(range(8))
        responses = [
            make_session_response(random_b),
            make_probe_response(cc=10),
            make_settings_response(cc=11),
        ]
        fake_ble = FakeSettingsClient(responses)
        client = make_client(security)

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient",
            return_value=fake_ble,
        ):
            result = await client.set_device_name("test")  # type: ignore[attr-defined]

        assert result is True

    @pytest.mark.asyncio
    async def test_set_device_name_truncates_to_4(self, security):
        random_b = bytes(range(8))
        responses = [
            make_session_response(random_b),
            make_probe_response(cc=10),
            make_settings_response(cc=11),
        ]
        fake_ble = FakeSettingsClient(responses)
        client = make_client(security)

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient",
            return_value=fake_ble,
        ):
            result = await client.set_device_name("toolongname")  # type: ignore[attr-defined]

        assert result is True
        name_pkt = fake_ble.written[2]
        # Packet: [0x00][len][0x10][ct...][tag][uid][cc]
        # plaintext = [0x02][name_bytes] max 5B (1+4)
        assert len(name_pkt) <= 20

    @pytest.mark.asyncio
    async def test_set_device_name_nack_returns_false(self, security):
        random_b = bytes(range(8))
        responses = [
            make_session_response(random_b),
            NACK,
        ]
        fake_ble = FakeSettingsClient(responses)
        client = make_client(security)

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient",
            return_value=fake_ble,
        ):
            result = await client.set_device_name("test")  # type: ignore[attr-defined]

        assert result is False


class TestSetDst:
    @pytest.mark.asyncio
    async def test_set_dst_enable(self, security):
        random_b = bytes(range(8))
        responses = [
            make_session_response(random_b),
            make_probe_response(cc=10),
            make_settings_response(cc=11),
        ]
        fake_ble = FakeSettingsClient(responses)
        client = make_client(security)

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient",
            return_value=fake_ble,
        ):
            result = await client.set_dst(True)  # type: ignore[attr-defined]

        assert result is True

    @pytest.mark.asyncio
    async def test_set_dst_disable(self, security):
        random_b = bytes(range(8))
        responses = [
            make_session_response(random_b),
            make_probe_response(cc=10),
            make_settings_response(cc=11),
        ]
        fake_ble = FakeSettingsClient(responses)
        client = make_client(security)

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient",
            return_value=fake_ble,
        ):
            result = await client.set_dst(False)  # type: ignore[attr-defined]

        assert result is True

    @pytest.mark.asyncio
    async def test_set_dst_nack_returns_false(self, security):
        random_b = bytes(range(8))
        responses = [
            make_session_response(random_b),
            NACK,
        ]
        fake_ble = FakeSettingsClient(responses)
        client = make_client(security)

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient",
            return_value=fake_ble,
        ):
            result = await client.set_dst(True)  # type: ignore[attr-defined]

        assert result is False
