"""1Control SoloMini RE — BLE client."""

from __future__ import annotations

import asyncio
import logging
import os

from bleak import BleakClient

from .protocol import (
    RX_CHAR_UUID,
    TX_CHAR_UUID,
    SecurityData,
    build_open_command,
    derive_session,
    extract_response_cc,
    is_nack,
)

_LOGGER = logging.getLogger(__name__)
CONNECT_TIMEOUT = 20.0
RESPONSE_TIMEOUT = 8.0


class SoloMiniClient:
    def __init__(self, address: str, security: SecurityData, action: int = 0):
        self.address = address
        self.security = security
        self.action = action
        self._lock = asyncio.Lock()

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
            await client.start_notify(RX_CHAR_UUID, lambda _, d: q.put_nowait(bytes(d)))
            await asyncio.sleep(0.3)
            while not q.empty():
                q.get_nowait()

            # 1. StartSession — nutný pro BLE handshake
            await client.write_gatt_char(
                TX_CHAR_UUID, bytes([0x00, 0x0A, 0x90, 0x02]) + random_a, response=True
            )
            resp = await asyncio.wait_for(q.get(), timeout=RESPONSE_TIMEOUT)
            _LOGGER.debug("Session: %s", resp.hex())
            our_sid, our_sk = derive_session(self.security.ltk, random_a, resp[4:12])

            # 2. Zkus open přímo s uloženým last_cc
            #    Pokud last_cc > aktuální CC zařízení → NACK, pak probe
            #    Pokud last_cc < aktuální CC → zařízení vrátí aktuální CC
            current_cc = self.security.last_cc
            _LOGGER.debug("Trying with last_cc=%d", current_cc)

            pkt = build_open_command(
                self.security.session_key,
                self.security.session_id,
                current_cc,
                self.security.user_id,
                self.action,
            )
            await client.write_gatt_char(TX_CHAR_UUID, pkt, response=True)

            try:
                r = await asyncio.wait_for(q.get(), timeout=RESPONSE_TIMEOUT)
                _LOGGER.debug("RX: %s", r.hex())

                if is_nack(r):
                    # NACK — last_cc je příliš vysoké, potřebujeme probe
                    _LOGGER.debug("NACK on last_cc=%d, probing...", current_cc)
                    probe = build_open_command(our_sk, our_sid, 0, self.security.user_id)
                    await client.write_gatt_char(TX_CHAR_UUID, probe, response=True)
                    r2 = await asyncio.wait_for(q.get(), timeout=RESPONSE_TIMEOUT)
                    resp_cc = extract_response_cc(r2)
                    if resp_cc is None:
                        return False
                    _LOGGER.debug("Probe CC=%d", resp_cc)
                    # Skutečný open s aktuálním CC
                    pkt2 = build_open_command(
                        self.security.session_key,
                        self.security.session_id,
                        resp_cc,
                        self.security.user_id,
                        self.action,
                    )
                    await client.write_gatt_char(TX_CHAR_UUID, pkt2, response=True)
                    try:
                        ack = await asyncio.wait_for(q.get(), timeout=3.0)
                        if is_nack(ack):
                            return False
                        new_cc = extract_response_cc(ack) or resp_cc + 1
                    except TimeoutError:
                        new_cc = resp_cc + 1

                elif len(r) == 16:
                    # Response — zkontroluj zda CC v odpovědi odpovídá
                    resp_cc = extract_response_cc(r)
                    if resp_cc is not None and resp_cc != current_cc + 1:
                        # last_cc byl nízký — zařízení vrátilo aktuální CC
                        # Pošli open se správným CC
                        _LOGGER.debug("CC mismatch, retrying with CC=%d", resp_cc)
                        pkt3 = build_open_command(
                            self.security.session_key,
                            self.security.session_id,
                            resp_cc,
                            self.security.user_id,
                            self.action,
                        )
                        await client.write_gatt_char(TX_CHAR_UUID, pkt3, response=True)
                        try:
                            ack2 = await asyncio.wait_for(q.get(), timeout=3.0)
                            if is_nack(ack2):
                                return False
                            new_cc = extract_response_cc(ack2) or resp_cc + 1
                        except TimeoutError:
                            new_cc = resp_cc + 1
                    else:
                        new_cc = resp_cc or current_cc + 1
                else:
                    new_cc = current_cc + 1

            except TimeoutError:
                new_cc = current_cc + 1

            # Ulož aktuální CC pro příští volání
            self.security.last_cc = new_cc
            _LOGGER.info("Gate opened! last_cc updated to %d", new_cc)
            return True
