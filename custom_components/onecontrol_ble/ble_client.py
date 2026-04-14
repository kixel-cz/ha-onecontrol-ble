"""1Control SoloMini — async BLE client s fragmentací."""
from __future__ import annotations
import asyncio, logging, os
from typing import Optional, Callable

from bleak import BleakClient, BleakError
from bleak.backends.characteristic import BleakGATTCharacteristic

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
MAX_RETRIES      = 3
BLE_MTU_REQUEST  = 128  # požadovaná MTU — pokud zařízení souhlasí, vejde se vše
FRAG_PAYLOAD     = 17   # max data bytů na fragment (20B MTU - 3B header)


def _fragment(data: bytes) -> list[bytes]:
    """
    Rozdělí velký paket na BLE fragmenty po 20 bytů.
    Formát z Tlv.java:
      [0x04][total_len][seq] + data_chunk   (mezifragment)
      [0x05][total_len][seq] + data_chunk   (poslední fragment)
    """
    total = len(data)
    chunks = [data[i:i+FRAG_PAYLOAD] for i in range(0, total, FRAG_PAYLOAD)]
    frags = []
    for seq, chunk in enumerate(chunks):
        is_last = (seq == len(chunks) - 1)
        ftype = 0x05 if is_last else 0x04
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
        while not self._responses.empty():
            self._responses.get_nowait()

        async with BleakClient(self.address, timeout=CONNECT_TIMEOUT) as client:

            # Negotiate větší MTU — pokud uspěje, fragmentace není potřeba
            try:
                await client.request_mtu(BLE_MTU_REQUEST)
                mtu = getattr(client, 'mtu_size', 23)
                _LOGGER.debug("Connected, MTU=%d", mtu)
            except Exception:
                mtu = 23
                _LOGGER.debug("MTU negotiation not supported, using default %d", mtu)

            await client.start_notify(RX_CHAR_UUID, self._on_notify)

            if self.security is None:
                sec = await self._do_pairing(client, mtu)
                if sec is None:
                    return False
                self.security = sec
                if self._on_paired:
                    self._on_paired(sec)

            # StartSession (12B — vejde se vždy)
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

            # Open (17B — vejde se vždy)
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
                pass  # SoloMini neposílá ACK pro open

            self.security.last_cc = cc + 1
            _LOGGER.info("Gate opened (action=%d)", self.action)
            return True

    async def _do_pairing(self, client: BleakClient, mtu: int) -> Optional[SecurityData]:
        priv, pub = generate_ec_keypair()
        pub64 = pubkey_to_64b(pub)
        pkt = build_start_pairing(pub64)

        _LOGGER.debug("TX StartPairing (%dB)", len(pkt))
        await self._write(client, pkt, mtu)

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

    async def _write(self, client: BleakClient, data: bytes, mtu: int = 23) -> None:
        """Zapíše data — pokud je větší než MTU, fragmentuje."""
        max_payload = mtu - 3
        if len(data) <= max_payload:
            # Vejde se do jednoho paketu
            await client.write_gatt_char(TX_CHAR_UUID, data, response=False)
        else:
            # Fragmentace
            frags = _fragment(data)
            _LOGGER.debug("Fragmenting %dB into %d fragments", len(data), len(frags))
            for frag in frags:
                await client.write_gatt_char(TX_CHAR_UUID, frag, response=False)
                await asyncio.sleep(0.05)  # krátká pauza mezi fragmenty

    def _on_notify(self, _: BleakGATTCharacteristic, data: bytearray) -> None:
        _LOGGER.debug("RX: %s", bytes(data).hex())
        self._responses.put_nowait(bytes(data))

    async def _wait(self) -> bytes:
        return await asyncio.wait_for(self._responses.get(), timeout=RESPONSE_TIMEOUT)