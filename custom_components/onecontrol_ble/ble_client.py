"""1Control SoloMini — BLE client."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    establish_connection,
)

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
    def __init__(
        self,
        address: str,
        security: SecurityData,
        action: int = 0,
        ble_device: BLEDevice | None = None,
    ):
        self.address = address
        self.security = security
        self.action = action
        self.ble_device = ble_device
        self._lock = asyncio.Lock()

    def set_ble_device(self, ble_device: BLEDevice) -> None:
        self.ble_device = ble_device

    async def _get_client(self) -> BleakClient:
        if self.ble_device is not None:
            return await establish_connection(
                BleakClientWithServiceCache,
                self.ble_device,
                self.address,
                max_attempts=3,
            )
        return BleakClient(self.address, timeout=CONNECT_TIMEOUT)

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

        client = await self._get_client()
        async with client:
            _LOGGER.debug("Connected to %s", self.address)
            await client.start_notify(RX_CHAR_UUID, lambda _, d: q.put_nowait(bytes(d)))
            await asyncio.sleep(0.3)
            while not q.empty():
                q.get_nowait()

            await client.write_gatt_char(
                TX_CHAR_UUID,
                bytes([0x00, 0x0A, 0x90, 0x02]) + random_a,
                response=True,
            )
            resp = await asyncio.wait_for(q.get(), timeout=RESPONSE_TIMEOUT)
            _LOGGER.debug("Session: %s", resp.hex())
            our_sid, our_sk = derive_session(self.security.ltk, random_a, resp[4:12])

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

    async def get_system_info(self) -> dict[str, Any]:
        for attempt in range(3):
            if self._lock.locked():
                _LOGGER.debug("Lock busy, waiting... attempt %d", attempt + 1)
                await asyncio.sleep(5)
                continue
            async with self._lock:
                try:
                    return await self._do_get_system_info()
                except Exception as e:
                    _LOGGER.warning("get_system_info failed: %s", e)
                    if attempt < 2:
                        await asyncio.sleep(10)
        return {}

    async def _do_get_system_info(self) -> dict[str, Any]:
        from .protocol import (
            assemble_fragments,
            build_get_system_info,
            decrypt_system_info,
        )

        random_a = os.urandom(8)
        q: asyncio.Queue[bytes] = asyncio.Queue()

        client = await self._get_client()
        async with client:
            await client.start_notify(RX_CHAR_UUID, lambda _, d: q.put_nowait(bytes(d)))
            await asyncio.sleep(0.3)
            while not q.empty():
                q.get_nowait()

            # StartSession
            await client.write_gatt_char(
                TX_CHAR_UUID,
                bytes([0x00, 0x0A, 0x90, 0x02]) + random_a,
                response=True,
            )
            resp = await asyncio.wait_for(q.get(), timeout=RESPONSE_TIMEOUT)
            our_sid, our_sk = derive_session(self.security.ltk, random_a, resp[4:12])

            # Probe
            probe = build_open_command(our_sk, our_sid, 0, self.security.user_id)
            await client.write_gatt_char(TX_CHAR_UUID, probe, response=True)
            r = await asyncio.wait_for(q.get(), timeout=RESPONSE_TIMEOUT)
            if is_nack(r):
                return {}
            resp_cc = extract_response_cc(r)
            if resp_cc is None:
                return {}

            # GetSystemInfo
            pkt = build_get_system_info(
                self.security.session_key,
                self.security.session_id,
                resp_cc,
                self.security.user_id,
            )
            await client.write_gatt_char(TX_CHAR_UUID, pkt, response=True)

            # Get fragments
            frags: list[bytes] = []
            for _ in range(5):
                try:
                    rx = await asyncio.wait_for(q.get(), timeout=2.0)
                    frags.append(rx)
                    if (rx[0] >> 4) == 4:
                        total = rx[2]
                        if len(frags) >= total:
                            break
                    else:
                        break
                except TimeoutError:
                    break

            assembled = assemble_fragments(frags)
            if not assembled:
                return {}

            info = decrypt_system_info(
                self.security.session_key,
                self.security.session_id,
                assembled,
            )
            if info:
                self.security.battery_raw = info["battery_raw"]
                _LOGGER.debug("SystemInfo: %s", info)
                return info
            return {}
