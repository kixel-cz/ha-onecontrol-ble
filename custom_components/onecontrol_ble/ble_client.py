"""
1Control SoloMini RE — BLE client.
"""
from __future__ import annotations
import asyncio, logging, os
from bleak import BleakClient
from .protocol import (
    SecurityData, TX_CHAR_UUID, RX_CHAR_UUID,
    derive_session, build_open_command, is_nack,
)

_LOGGER = logging.getLogger(__name__)
CONNECT_TIMEOUT  = 20.0
RESPONSE_TIMEOUT = 8.0

class SoloMiniClient:
    def __init__(self, address: str, security: SecurityData, action: int = 0):
        self.address  = address
        self.security = security
        self.action   = action
        self._lock    = asyncio.Lock()

    async def open_gate(self) -> bool:
        if self._lock.locked():
            _LOGGER.warning("Already in progress")
            return False
        async with self._lock:
            for attempt in range(3):
                try:
                    return await self._do_open()
                except Exception as e:
                    _LOGGER.warning("Attempt %d failed: %s", attempt + 1, e)
                    if attempt < 2:
                        await asyncio.sleep(3)
            return False

    async def _do_open(self) -> bool:
        random_a = os.urandom(8)
        q: asyncio.Queue[bytes] = asyncio.Queue()

        async with BleakClient(self.address, timeout=CONNECT_TIMEOUT) as client:
            _LOGGER.debug("Connected to %s", self.address)
            await client.start_notify(RX_CHAR_UUID,
                lambda _, d: q.put_nowait(bytes(d)))
            await asyncio.sleep(0.3)
            while not q.empty(): q.get_nowait()

            # 1. StartSession — BLE handshake
            await client.write_gatt_char(TX_CHAR_UUID,
                bytes([0x00, 0x0A, 0x90, 0x02]) + random_a, response=True)
            resp = await asyncio.wait_for(q.get(), timeout=RESPONSE_TIMEOUT)
            _LOGGER.debug("Session: %s", resp.hex())
            our_sid, our_sk = derive_session(
                self.security.ltk, random_a, resp[4:12])

            # 2. Probe — get current CC
            probe = build_open_command(our_sk, our_sid, 0, self.security.user_id)
            await client.write_gatt_char(TX_CHAR_UUID, probe, response=True)
            r = await asyncio.wait_for(q.get(), timeout=RESPONSE_TIMEOUT)
            resp_cc = int.from_bytes(r[12:14], 'little')
            _LOGGER.debug("Probe CC=%d", resp_cc)

            # 3. Open
            pkt = build_open_command(
                self.security.session_key,
                self.security.session_id,
                resp_cc,
                self.security.user_id,
                self.action,
            )
            _LOGGER.debug("TX Open: %s", pkt.hex())
            await client.write_gatt_char(TX_CHAR_UUID, pkt, response=True)

            try:
                ack = await asyncio.wait_for(q.get(), timeout=3.0)
                _LOGGER.debug("RX: %s", ack.hex())
                if is_nack(ack):
                    _LOGGER.warning("NACK")
                    return False
            except asyncio.TimeoutError:
                pass

            _LOGGER.info("Gate opened!")
            return True
