"""1Control SoloMini — async BLE client."""
from __future__ import annotations
import asyncio, logging, os
from typing import Optional, Callable

from bleak import BleakClient, BleakError
from bleak.backends.characteristic import BleakGATTCharacteristic

from .protocol import (
    SecurityData, SERVICE_UUID, TX_CHAR_UUID, RX_CHAR_UUID,
    generate_ec_keypair, pubkey_to_64b, ecdh_ltk,
    build_start_pairing, build_start_session,
    parse_greeting, parse_start_pairing_response,
    parse_start_session_response, build_open_command, is_nack,
)

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT  = 20.0
RESPONSE_TIMEOUT = 10.0
MAX_RETRIES      = 3


class SoloMiniClient:
    def __init__(self, address: str,
                 security: Optional[SecurityData] = None,
                 action: int = 1,
                 on_paired: Optional[Callable[[SecurityData], None]] = None):
        self.address   = address
        self.security  = security
        self.action    = action
        self._on_paired = on_paired
        self._responses: asyncio.Queue[bytes] = asyncio.Queue()

    async def open_gate(self, action: Optional[int] = None) -> bool:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return await self._do_connect()
            except (BleakError, asyncio.TimeoutError, Exception) as exc:
                _LOGGER.warning("Attempt %d/%d failed: %s", attempt, MAX_RETRIES, exc)
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(2.0)
        return False

    async def _do_connect(self) -> bool:
        # Vyprázdni frontu
        while not self._responses.empty():
            self._responses.get_nowait()

        async with BleakClient(
            self.address,
            timeout=CONNECT_TIMEOUT,
        ) as client:
            _LOGGER.debug("Connected to %s, MTU=%s", self.address,
                          getattr(client, 'mtu_size', '?'))

            await client.start_notify(RX_CHAR_UUID, self._on_notify)

            if self.security is None:
                sec = await self._do_pairing(client)
                if sec is None:
                    return False
                self.security = sec
                if self._on_paired:
                    self._on_paired(sec)

            # StartSession
            random_a = os.urandom(8)
            await self._write(client, build_start_session(random_a))
            resp = await self._wait()
            random_b = parse_start_session_response(resp)
            if not random_b:
                _LOGGER.error("Bad StartSession response: %s", resp.hex())
                return False
            self.security.update_session(random_a, random_b)
            _LOGGER.debug("Session: ID=%s", self.security.session_id.hex())

            # Greeting
            greeting = await self._wait()
            parsed = parse_greeting(greeting)
            if not parsed:
                _LOGGER.error("Bad greeting: %s", greeting.hex())
                return False
            session_id, _, dev_uid, cc = parsed
            _LOGGER.debug("Greeting: CC=%d", cc)
            self.security.session_id = session_id

            # Open
            open_pkt = build_open_command(
                self.security.session_key,
                self.security.session_id,
                cc, self.security.user_id, self.action,
            )
            await self._write(client, open_pkt)

            try:
                ack = await asyncio.wait_for(self._wait(), timeout=2.0)
                if is_nack(ack):
                    _LOGGER.warning("NACK: %s", ack.hex())
                    return False
            except asyncio.TimeoutError:
                pass  # SoloMini neposílá ACK pro open — normální

            self.security.last_cc = cc + 1
            _LOGGER.info("Gate opened (action=%d, CC=%d)", self.action, cc + 1)
            return True

    async def _do_pairing(self, client: BleakClient) -> Optional[SecurityData]:
        """ECDH pairing — posílá 68B paket, vyžaduje MTU >= 69."""
        priv, pub = generate_ec_keypair()
        pub64 = pubkey_to_64b(pub)
        pkt = build_start_pairing(pub64)

        _LOGGER.debug("TX StartPairing (%dB): %s", len(pkt), pkt.hex())

        # Pošli jako Write Without Response pokud je paket větší než MTU
        # bleak automaticky použije Write Long pro response=True
        await self._write(client, pkt, response=True)

        resp = await self._wait()
        _LOGGER.debug("RX StartPairing resp (%dB): %s", len(resp), resp.hex())

        device_pub64 = parse_start_pairing_response(resp)
        if not device_pub64:
            _LOGGER.error("Bad StartPairing response: %s", resp.hex())
            return None

        ltk = ecdh_ltk(priv, device_pub64)
        _LOGGER.info("Pairing OK, LTK=%s", ltk.hex())

        from cryptography.hazmat.primitives.serialization import (
            Encoding, PrivateFormat, NoEncryption,
        )
        pem = priv.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        return SecurityData(ltk=ltk, private_key_pem=pem, user_id=0)

    async def _write(self, client: BleakClient, data: bytes,
                     response: bool = True) -> None:
        """Zapíše data na TX charakteristiku. Použije Write Long pokud je potřeba."""
        mtu = getattr(client, 'mtu_size', 23)
        if len(data) > mtu - 3:
            # Větší než MTU — bleak s response=True použije Write Long (ATT)
            _LOGGER.debug("Writing %dB (MTU=%d), using Write Long", len(data), mtu)
        await client.write_gatt_char(TX_CHAR_UUID, data, response=response)

    def _on_notify(self, _: BleakGATTCharacteristic, data: bytearray) -> None:
        _LOGGER.debug("RX notify: %s", bytes(data).hex())
        self._responses.put_nowait(bytes(data))

    async def _wait(self) -> bytes:
        return await asyncio.wait_for(
            self._responses.get(), timeout=RESPONSE_TIMEOUT
        )