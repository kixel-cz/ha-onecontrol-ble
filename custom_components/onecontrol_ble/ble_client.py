"""1Control SoloMini — async BLE client."""
from __future__ import annotations
import asyncio, logging, os
from typing import Optional, Callable

from bleak import BleakClient, BleakError
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak_retry_connector import establish_connection, BleakClientWithServiceCache

from .protocol import (
    SecurityData, TX_CHAR_UUID, RX_CHAR_UUID,
    generate_ec_keypair, pubkey_to_64b, ecdh_ltk,
    build_start_pairing, build_start_session,
    parse_greeting, parse_start_pairing_response,
    parse_start_session_response, build_open_command, is_nack,
)

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT  = 20.0
RESPONSE_TIMEOUT = 10.0
BLE_MTU_REQUEST  = 128
FRAG_PAYLOAD     = 17   # 20B MTU - 3B header


def _fragment(data: bytes) -> list[bytes]:
    """Fragmentace velkých paketů per Tlv.java."""
    total = len(data)
    chunks = [data[i:i+FRAG_PAYLOAD] for i in range(0, total, FRAG_PAYLOAD)]
    frags = []
    for seq, chunk in enumerate(chunks):
        ftype = 0x05 if seq == len(chunks) - 1 else 0x04
        frags.append(bytes([ftype, total, seq]) + chunk)
    return frags


class SoloMiniClient:
    def __init__(self, address: str,
                 security: Optional[SecurityData] = None,
                 action: int = 1,
                 on_paired: Optional[Callable[[SecurityData], None]] = None):
        self.address    = address
        self.security   = security
        self.action     = action
        self._on_paired = on_paired
        self._responses: asyncio.Queue[bytes] = asyncio.Queue()
        self._lock = asyncio.Lock()  # zabrání paralelním pokusům

    async def open_gate(self, action: Optional[int] = None) -> bool:
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

        # Použij bleak-retry-connector pro spolehlivé připojení
        client = await establish_connection(
            BleakClientWithServiceCache,
            self.address,
            name=self.address,
            max_attempts=3,
        )

        try:
            # MTU negotiation
            mtu = 23
            try:
                await client.request_mtu(BLE_MTU_REQUEST)
                mtu = getattr(client, 'mtu_size', 23)
                _LOGGER.debug("MTU=%d", mtu)
            except Exception:
                _LOGGER.debug("MTU negotiation not supported, using %d", mtu)

            await client.start_notify(RX_CHAR_UUID, self._on_notify)

            # Pairing pokud nemáme LTK
            if self.security is None:
                sec = await self._do_pairing(client, mtu)
                if sec is None:
                    return False
                self.security = sec
                if self._on_paired:
                    self._on_paired(sec)

            # StartSession
            random_a = os.urandom(8)
            await self._write(client, build_start_session(random_a), mtu)
            resp = await self._wait()
            random_b = parse_start_session_response(resp)
            if not random_b:
                _LOGGER.error("Bad StartSession response: %s", resp.hex())
                return False
            self.security.update_session(random_a, random_b)

            # Greeting
            greeting = await self._wait()
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
            await self._write(client, open_pkt, mtu)

            try:
                ack = await asyncio.wait_for(self._wait(), timeout=2.0)
                if is_nack(ack):
                    _LOGGER.warning("NACK: %s", ack.hex())
                    return False
            except asyncio.TimeoutError:
                pass  # normální — SoloMini neposílá ACK pro open

            self.security.last_cc = cc + 1
            _LOGGER.info("Gate opened (action=%d)", self.action)
            return True

        finally:
            await client.disconnect()

    async def _do_pairing(self, client: BleakClient, mtu: int) -> Optional[SecurityData]:
        priv, pub = generate_ec_keypair()
        pkt = build_start_pairing(pubkey_to_64b(pub))
        _LOGGER.debug("TX StartPairing (%dB)", len(pkt))

        await self._write(client, pkt, mtu)
        resp = await self._wait()
        _LOGGER.debug("RX StartPairing (%dB): %s", len(resp), resp.hex())

        device_pub64 = parse_start_pairing_response(resp)
        if not device_pub64:
            _LOGGER.error("Bad pairing response: %s", resp.hex())
            return None

        ltk = ecdh_ltk(priv, device_pub64)
        _LOGGER.info("Pairing OK, LTK=%s", ltk.hex())

        from cryptography.hazmat.primitives.serialization import (
            Encoding, PrivateFormat, NoEncryption,
        )
        pem = priv.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        return SecurityData(ltk=ltk, private_key_pem=pem, user_id=0)

    async def _write(self, client: BleakClient, data: bytes, mtu: int = 23) -> None:
        max_payload = mtu - 3
        if len(data) <= max_payload:
            await client.write_gatt_char(TX_CHAR_UUID, data, response=False)
        else:
            for frag in _fragment(data):
                await client.write_gatt_char(TX_CHAR_UUID, frag, response=False)
                await asyncio.sleep(0.05)

    def _on_notify(self, _: BleakGATTCharacteristic, data: bytearray) -> None:
        _LOGGER.debug("RX: %s", bytes(data).hex())
        self._responses.put_nowait(bytes(data))

    async def _wait(self) -> bytes:
        return await asyncio.wait_for(self._responses.get(), timeout=RESPONSE_TIMEOUT)