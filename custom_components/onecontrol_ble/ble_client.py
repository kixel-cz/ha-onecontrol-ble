"""1Control SoloMini — async BLE client."""
from __future__ import annotations
import asyncio, logging, os
from typing import Optional, Callable

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic

from .protocol import (
    SecurityData, TX_CHAR_UUID, RX_CHAR_UUID,
    generate_ec_keypair, pubkey_to_64b, ecdh_ltk,
    build_start_pairing, parse_greeting,
    parse_start_pairing_response, build_open_command, is_nack,
)

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT  = 20.0
RESPONSE_TIMEOUT = 10.0


def parse_session_response(packet: bytes) -> Optional[bytes]:
    """[00][0A][90][00][randomB_8B] → randomB"""
    if len(packet) < 12 or packet[2] != 0x90 or packet[3] != 0x00:
        return None
    return packet[4:12]


class SoloMiniClient:
    def __init__(self, address: str,
                 security=None, action: int = 1, on_paired=None):
        self.address    = address
        self.security   = security
        self.action     = action
        self._on_paired = on_paired
        self._responses: asyncio.Queue[bytes] = asyncio.Queue()
        self._lock = asyncio.Lock()

    async def open_gate(self, action=None) -> bool:
        if self._lock.locked():
            _LOGGER.warning("BLE operation already in progress, skipping")
            return False
        async with self._lock:
            try:
                return await self._do_connect()
            except Exception as exc:
                _LOGGER.error("Gate open failed: %s", exc)
                return False

    async def _do_connect(self) -> bool:
        while not self._responses.empty():
            self._responses.get_nowait()

        _LOGGER.debug("Connecting to %s", self.address)
        async with BleakClient(self.address, timeout=CONNECT_TIMEOUT) as client:
            await client.start_notify(RX_CHAR_UUID, self._on_notify)
            await asyncio.sleep(0.3)

            if self.security is None:
                sec = await self._do_pairing(client)
                if sec is None:
                    return False
                self.security = sec
                if self._on_paired:
                    self._on_paired(sec)

            # StartSession: [00][0A][90][02][randomA_8B]
            random_a = os.urandom(8)
            session_pkt = bytes([0x00, 0x0A, 0x90, 0x02]) + random_a
            _LOGGER.debug("TX StartSession: %s", session_pkt.hex())
            await client.write_gatt_char(TX_CHAR_UUID, session_pkt, response=True)

            resp = await self._wait()
            _LOGGER.debug("RX StartSession: %s", resp.hex())
            random_b = parse_session_response(resp)
            if not random_b:
                _LOGGER.error("Bad StartSession response: %s", resp.hex())
                return False
            self.security.update_session(random_a, random_b)

            # Greeting
            greeting = await self._wait()
            _LOGGER.debug("RX Greeting: %s", greeting.hex())
            parsed = parse_greeting(greeting)
            if not parsed:
                _LOGGER.error("Bad greeting: %s", greeting.hex())
                return False
            session_id, _, dev_uid, cc = parsed
            _LOGGER.debug("Greeting CC=%d", cc)
            self.security.session_id = session_id

            # Open
            open_pkt = build_open_command(
                self.security.session_key, self.security.session_id,
                cc, self.security.user_id, self.action,
            )
            _LOGGER.debug("TX Open: %s", open_pkt.hex())
            await client.write_gatt_char(TX_CHAR_UUID, open_pkt, response=True)

            try:
                ack = await asyncio.wait_for(self._wait(), timeout=2.0)
                if is_nack(ack):
                    _LOGGER.warning("NACK: %s", ack.hex())
                    return False
            except asyncio.TimeoutError:
                pass

            self.security.last_cc = cc + 1
            _LOGGER.info("Gate opened (action=%d)", self.action)
            return True

    async def _do_pairing(self, client: BleakClient):
        priv, pub = generate_ec_keypair()
        pkt = build_start_pairing(pubkey_to_64b(pub))

        _LOGGER.debug("TX StartPairing (%dB)", len(pkt))
        for i in range(0, len(pkt), 20):
            await client.write_gatt_char(TX_CHAR_UUID, pkt[i:i+20], response=True)
            await asyncio.sleep(0.05)

        try:
            resp = await asyncio.wait_for(self._wait(), timeout=5.0)
            _LOGGER.debug("RX pairing (%dB): %s", len(resp), resp.hex())
            device_pub64 = resp[4:68] if len(resp) >= 68 and resp[2] == 0x90 else parse_start_pairing_response(resp)
            if device_pub64 and len(device_pub64) == 64:
                ltk = ecdh_ltk(priv, device_pub64)
                _LOGGER.info("Pairing OK, LTK=%s", ltk.hex())
                from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
                pem = priv.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
                return SecurityData(ltk=ltk, private_key_pem=pem, user_id=0)
            _LOGGER.error("Bad pairing response: %s", resp.hex())
        except asyncio.TimeoutError:
            _LOGGER.error("Pairing timeout")
        return None

    def _on_notify(self, _, data: bytearray) -> None:
        _LOGGER.debug("RX: %s", bytes(data).hex())
        self._responses.put_nowait(bytes(data))

    async def _wait(self) -> bytes:
        return await asyncio.wait_for(self._responses.get(), timeout=RESPONSE_TIMEOUT)