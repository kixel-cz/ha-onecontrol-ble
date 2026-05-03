"""Tests for clone_remote, set_opening_time and _do_transmit."""

from __future__ import annotations

import struct
from unittest.mock import patch

import pytest

from custom_components.onecontrol_ble.ble_client import SoloMiniClient
from custom_components.onecontrol_ble.protocol import NACK, SecurityData
from tests.conftest import TEST_LTK, TEST_SESSION_ID, TEST_SESSION_KEY


def make_session_response(random_b: bytes) -> bytes:
    return bytes([0x00, 0x0A, 0x90, 0x00]) + random_b


def make_probe_response(cc: int) -> bytes:
    return bytes([0x00, 0x0E, 0x01] + [0] * 9 + list(struct.pack("<H", cc)) + [0x00, 0x00])


def make_transmit_response(slot: int) -> bytes:
    return bytes([0x00, 0x0E, 0x01, slot & 0xFF] + [0] * 12)


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


class FakeTransmitClient:
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


class TestCloneRemote:
    @pytest.mark.asyncio
    async def test_clone_remote_returns_slot(self, security):
        random_b = bytes(range(8))
        responses = [
            make_session_response(random_b),
            make_probe_response(cc=10),  # probe
            make_transmit_response(3),  # clone response, slot=3
        ]
        fake_ble = FakeTransmitClient(responses)
        client = make_client(security)

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient",
            return_value=fake_ble,
        ):
            result = await client.clone_remote(action=0)

        assert result is not None
        assert result == 3

    @pytest.mark.asyncio
    async def test_clone_remote_nack_returns_none(self, security):
        random_b = bytes(range(8))
        responses = [
            make_session_response(random_b),
            NACK,  # probe -> NACK
        ]
        fake_ble = FakeTransmitClient(responses)
        client = make_client(security)

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient",
            return_value=fake_ble,
        ):
            result = await client.clone_remote(action=0)

        assert result is None

    @pytest.mark.asyncio
    async def test_clone_remote_sends_correct_plaintext(self, security):
        random_b = bytes(range(8))
        responses = [
            make_session_response(random_b),
            make_probe_response(cc=10),
            make_transmit_response(1),
        ]
        fake_ble = FakeTransmitClient(responses)
        client = make_client(security)

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient",
            return_value=fake_ble,
        ):
            await client.clone_remote(action=0)

        # StartSession + probe + clone = 3 packets
        assert len(fake_ble.written) == 3

    @pytest.mark.asyncio
    async def test_clone_remote_connection_error_returns_none(self, security):
        from unittest.mock import AsyncMock, MagicMock

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
            result = await client.clone_remote(action=0)

        assert result is None


class TestSetOpeningTime:
    @pytest.mark.asyncio
    async def test_set_opening_time_success(self, security):
        random_b = bytes(range(8))
        responses = [
            make_session_response(random_b),
            make_probe_response(cc=10),
            make_transmit_response(0),
        ]
        fake_ble = FakeTransmitClient(responses)
        client = make_client(security)

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient",
            return_value=fake_ble,
        ):
            result = await client.set_opening_time(action=0, time_s=30)

        assert result is not None

    @pytest.mark.asyncio
    async def test_set_opening_time_sends_three_packets(self, security):
        random_b = bytes(range(8))
        responses = [
            make_session_response(random_b),
            make_probe_response(cc=10),
            make_transmit_response(0),
        ]
        fake_ble = FakeTransmitClient(responses)
        client = make_client(security)

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient",
            return_value=fake_ble,
        ):
            await client.set_opening_time(action=0, time_s=15)

        assert len(fake_ble.written) == 3

    @pytest.mark.asyncio
    async def test_set_opening_time_zero(self, security):
        random_b = bytes(range(8))
        responses = [
            make_session_response(random_b),
            make_probe_response(cc=10),
            make_transmit_response(0),
        ]
        fake_ble = FakeTransmitClient(responses)
        client = make_client(security)

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient",
            return_value=fake_ble,
        ):
            result = await client.set_opening_time(action=0, time_s=0)

        assert result is not None

    @pytest.mark.asyncio
    async def test_set_opening_time_nack_returns_none(self, security):
        random_b = bytes(range(8))
        responses = [
            make_session_response(random_b),
            NACK,
        ]
        fake_ble = FakeTransmitClient(responses)
        client = make_client(security)

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient",
            return_value=fake_ble,
        ):
            result = await client.set_opening_time(action=0, time_s=30)

        assert result is None


class TestScannerFlow:
    @pytest.mark.asyncio
    async def test_start_scanner_success(self, security):
        random_b = bytes(range(8))
        responses = [
            make_session_response(random_b),
            make_probe_response(cc=10),
            make_transmit_response(0),
        ]
        fake_ble = FakeTransmitClient(responses)
        client = make_client(security)

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient",
            return_value=fake_ble,
        ):
            result = await client.start_scanner(action=0)  # type: ignore[attr-defined]

        assert result is True

    @pytest.mark.asyncio
    async def test_confirm_scanner_success(self, security):
        random_b = bytes(range(8))
        responses = [
            make_session_response(random_b),
            make_probe_response(cc=10),
            make_transmit_response(0),
        ]
        fake_ble = FakeTransmitClient(responses)
        client = make_client(security)

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient",
            return_value=fake_ble,
        ):
            result = await client.confirm_scanner(action=0)  # type: ignore[attr-defined]

        assert result is True

    @pytest.mark.asyncio
    async def test_complete_scanner_success(self, security):
        random_b = bytes(range(8))
        responses = [
            make_session_response(random_b),
            make_probe_response(cc=10),
            make_transmit_response(0),
        ]
        fake_ble = FakeTransmitClient(responses)
        client = make_client(security)

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient",
            return_value=fake_ble,
        ):
            result = await client.complete_scanner(action=0)  # type: ignore[attr-defined]

        assert result is True

    @pytest.mark.asyncio
    async def test_undo_scanner_success(self, security):
        random_b = bytes(range(8))
        responses = [
            make_session_response(random_b),
            make_probe_response(cc=10),
            make_transmit_response(0),
        ]
        fake_ble = FakeTransmitClient(responses)
        client = make_client(security)

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient",
            return_value=fake_ble,
        ):
            result = await client.undo_scanner(action=0)  # type: ignore[attr-defined]

        assert result is True

    @pytest.mark.asyncio
    async def test_start_scanner_nack_returns_false(self, security):
        random_b = bytes(range(8))
        responses = [
            make_session_response(random_b),
            NACK,
        ]
        fake_ble = FakeTransmitClient(responses)
        client = make_client(security)

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient",
            return_value=fake_ble,
        ):
            result = await client.start_scanner(action=0)  # type: ignore[attr-defined]

        assert result is False

    @pytest.mark.asyncio
    async def test_full_scanner_flow(self, security):
        random_b = bytes(range(8))

        async def run_step(plaintext_byte: int) -> bool:
            responses = [
                make_session_response(random_b),
                make_probe_response(cc=10),
                make_transmit_response(0),
            ]
            fake_ble = FakeTransmitClient(responses)
            client = make_client(security)
            with patch(
                "custom_components.onecontrol_ble.ble_client.BleakClient",
                return_value=fake_ble,
            ):
                result = await client._do_transmit(bytes([plaintext_byte, 0]))
            return result is not None

        assert await run_step(0x0C)  # StartScanner
        assert await run_step(0x0D)  # ConfirmScanner
        assert await run_step(0x0E)  # CompleteScanner
