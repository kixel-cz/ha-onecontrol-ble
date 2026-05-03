"""Pairing tests via ECDH (ble_client.pair())."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.onecontrol_ble.ble_client import SoloMiniClient
from custom_components.onecontrol_ble.protocol import SecurityData


def make_dummy_security() -> SecurityData:
    return SecurityData(
        ltk=bytes(16),
        session_key=bytes(16),
        session_id=bytes(8),
    )


def make_device_pubkey_response(device_pub_bytes: bytes) -> bytes:
    # [00][42][90][00][device_pubkey_64B]
    return bytes([0x00, 0x42, 0x90, 0x00]) + device_pub_bytes


class FakePairingClient:

    def __init__(self, device_pub_bytes: bytes):
        self._device_pub = device_pub_bytes
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
        if self._notify_callback:
            resp = make_device_pubkey_response(self._device_pub)
            self._notify_callback(None, bytearray(resp))


class TestPairing:
    @pytest.mark.asyncio
    async def test_pair_returns_security_data(self):
        from cryptography.hazmat.primitives.asymmetric.ec import (
            SECP256R1,
            generate_private_key,
        )
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            PublicFormat,
        )

        device_private = generate_private_key(SECP256R1())
        device_public = device_private.public_key()
        device_pub_bytes = device_public.public_bytes(
            Encoding.X962, PublicFormat.UncompressedPoint
        )[1:]

        fake_ble = FakePairingClient(device_pub_bytes)
        client = SoloMiniClient(
            address="AA:BB:CC:DD:EE:FF",
            security=make_dummy_security(),
        )

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient",
            return_value=fake_ble,
        ):
            result = await client.pair()

        assert result is not None
        assert len(result.ltk) == 16
        assert result.ltk != bytes(16)

    @pytest.mark.asyncio
    async def test_pair_sends_correct_packet(self):
        from cryptography.hazmat.primitives.asymmetric.ec import (
            SECP256R1,
            generate_private_key,
        )
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            PublicFormat,
        )

        device_private = generate_private_key(SECP256R1())
        device_pub_bytes = device_private.public_key().public_bytes(
            Encoding.X962, PublicFormat.UncompressedPoint
        )[1:]

        fake_ble = FakePairingClient(device_pub_bytes)
        client = SoloMiniClient(
            address="AA:BB:CC:DD:EE:FF",
            security=make_dummy_security(),
        )

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient",
            return_value=fake_ble,
        ):
            await client.pair()

        assert len(fake_ble.written) == 1
        pkt = fake_ble.written[0]
        # [00][42][90][01][pubkey_64B] = 68B
        assert len(pkt) == 68
        assert pkt[0] == 0x00
        assert pkt[1] == 0x42
        assert pkt[2] == 0x90
        assert pkt[3] == 0x01

    @pytest.mark.asyncio
    async def test_pair_invalid_response_returns_none(self):

        class BadResponseClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def start_notify(self, uuid, cb, **kw):
                self._cb = cb

            async def write_gatt_char(self, uuid, data, response=True):
                self._cb(None, bytearray(bytes([0x00, 0x04, 0x90, 0x00])))

        client = SoloMiniClient(
            address="AA:BB:CC:DD:EE:FF",
            security=make_dummy_security(),
        )

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient",
            return_value=BadResponseClient(),
        ):
            result = await client.pair()

        assert result is None

    @pytest.mark.asyncio
    async def test_pair_two_devices_different_ltk(self):
        from cryptography.hazmat.primitives.asymmetric.ec import (
            SECP256R1,
            generate_private_key,
        )
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            PublicFormat,
        )

        results = []
        for _ in range(2):
            device_private = generate_private_key(SECP256R1())
            device_pub_bytes = device_private.public_key().public_bytes(
                Encoding.X962, PublicFormat.UncompressedPoint
            )[1:]
            fake_ble = FakePairingClient(device_pub_bytes)
            client = SoloMiniClient(
                address="AA:BB:CC:DD:EE:FF",
                security=make_dummy_security(),
            )
            with patch(
                "custom_components.onecontrol_ble.ble_client.BleakClient",
                return_value=fake_ble,
            ):
                result = await client.pair()
            assert result is not None
            results.append(result.ltk)

        assert results[0] != results[1]

    @pytest.mark.asyncio
    async def test_pair_connection_error_returns_none(self):
        client = SoloMiniClient(
            address="AA:BB:CC:DD:EE:FF",
            security=make_dummy_security(),
        )

        async def fail(*args, **kwargs):
            raise OSError("BLE error")

        fake_ctx = MagicMock()
        fake_ctx.__aenter__ = fail
        fake_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "custom_components.onecontrol_ble.ble_client.BleakClient",
            return_value=fake_ctx,
        ):
            result = await client.pair()

        assert result is None
