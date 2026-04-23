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
    parse_greeting,
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

            # 1. StartSession
            await client.write_gatt_char(
                TX_CHAR_UUID,
                bytes([0x00, 0x0A, 0x90, 0x02]) + random_a,
                response=True,
            )
            resp = await asyncio.wait_for(q.get(), timeout=RESPONSE_TIMEOUT)
            _LOGGER.debug("Session: %s", resp.hex())
            our_sid, our_sk = derive_session(self.security.ltk, random_a, resp[4:12])

            # 2. Try stored last_cc first
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
                    # NACK — probe required
                    _LOGGER.debug("NACK on last_cc=%d, probing...", current_cc)
                    probe = build_open_command(our_sk, our_sid, 0, self.security.user_id)
                    await client.write_gatt_char(TX_CHAR_UUID, probe, response=True)
                    r2 = await asyncio.wait_for(q.get(), timeout=RESPONSE_TIMEOUT)
                    resp_cc = extract_response_cc(r2)
                    if resp_cc is None:
                        return False
                    _LOGGER.debug("Probe CC=%d", resp_cc)
                    pkt2 = build_open_command(
                        self.security.session_key,
                        self.security.session_id,
                        resp_cc,
                        self.security.user_id,
                        self.action,
                    )
                    await client.write_gatt_char(TX_CHAR_UUID, pkt2, response=True)
                    new_cc = await self._collect_response(q, resp_cc)

                elif len(r) == 16:
                    resp_cc = extract_response_cc(r)
                    if resp_cc is not None and resp_cc != current_cc + 1:
                        # last_cc too low — got current CC
                        _LOGGER.debug("CC mismatch, retrying with CC=%d", resp_cc)
                        pkt3 = build_open_command(
                            self.security.session_key,
                            self.security.session_id,
                            resp_cc,
                            self.security.user_id,
                            self.action,
                        )
                        await client.write_gatt_char(TX_CHAR_UUID, pkt3, response=True)
                        new_cc = await self._collect_response(q, resp_cc)
                    else:
                        new_cc = await self._collect_response(q, current_cc, first=r)
                else:
                    new_cc = current_cc + 1

            except TimeoutError:
                new_cc = current_cc + 1

            self.security.last_cc = new_cc
            _LOGGER.info(
                "Gate opened! last_cc=%d battery_raw=%s",
                new_cc,
                self.security.battery_raw,
            )
            return True

    async def _collect_response(
        self,
        q: asyncio.Queue[bytes],
        last_cc: int,
        first: bytes | None = None,
    ) -> int:
        new_cc = last_cc + 1
        packets: list[bytes] = [first] if first is not None else []

        for _ in range(3):
            try:
                pkt = await asyncio.wait_for(q.get(), timeout=2.0)
                packets.append(pkt)
            except TimeoutError:
                break

        for pkt in packets:
            _LOGGER.debug("collect RX: %s", pkt.hex())
            if is_nack(pkt):
                _LOGGER.warning("NACK in collect_response")
                return new_cc
            if len(pkt) == 19 and pkt[1] == 0x11:
                parsed = parse_greeting(pkt)
                if parsed:
                    _, battery_raw, _, greeting_cc = parsed
                    self.security.battery_raw = battery_raw
                    new_cc = greeting_cc
                    _LOGGER.debug(
                        "Greeting: battery_raw=%d, CC=%d",
                        battery_raw,
                        greeting_cc,
                    )
            elif len(pkt) == 16:
                cc_from_resp = extract_response_cc(pkt)
                if cc_from_resp:
                    new_cc = cc_from_resp

        return new_cc
