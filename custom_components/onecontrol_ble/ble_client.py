"""1Control SoloMini RE — BLE client."""

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
        persistent_connection: bool = True,
    ):
        self.address = address
        self.security = security
        self.action = action
        self.ble_device = ble_device
        self.persistent_connection = persistent_connection
        self._lock = asyncio.Lock()
        self._conn: BleakClientWithServiceCache | BleakClient | None = None
        self._notify_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._last_disconnect: float = 0.0

    def set_ble_device(self, ble_device: BLEDevice) -> None:
        self.ble_device = ble_device

    def _on_disconnect(self, _client: BleakClient) -> None:
        _LOGGER.debug("BLE disconnected from %s", self.address)
        self._conn = None
        self._last_disconnect = asyncio.get_event_loop().time()
        while not self._notify_queue.empty():
            self._notify_queue.get_nowait()

    async def _ensure_connected(self) -> BleakClient:
        """Return the persistent BLE connection, establishing it if needed."""
        if self._conn is not None and self._conn.is_connected:
            return self._conn

        # Brief cooldown so the device is ready after self-disconnecting
        since = asyncio.get_event_loop().time() - self._last_disconnect
        if 0 < since < 1.5:
            await asyncio.sleep(1.5 - since)

        _LOGGER.debug("Connecting to %s", self.address)
        if self.ble_device is not None:
            client = await establish_connection(
                BleakClientWithServiceCache,
                self.ble_device,
                self.address,
                disconnected_callback=self._on_disconnect,
                max_attempts=3,
            )
        else:
            client = BleakClient(
                self.address,
                timeout=CONNECT_TIMEOUT,
                disconnected_callback=self._on_disconnect,
            )
            await client.connect()

        try:
            if hasattr(client, "_backend"):
                client._backend._mtu_size = 247  # type: ignore[attr-defined]
        except Exception:
            pass

        await client.start_notify(
            RX_CHAR_UUID,
            lambda _, d: self._notify_queue.put_nowait(bytes(d)),
        )
        await asyncio.sleep(0.1)

        self._conn = client
        _LOGGER.debug("Connected to %s", self.address)
        return client

    async def _release(self) -> None:
        """Disconnect after a command when not in persistent mode."""
        if not self.persistent_connection and self._conn is not None:
            try:
                await self._conn.disconnect()
            except Exception:
                pass
            self._conn = None

    def _drain_queue(self) -> None:
        while not self._notify_queue.empty():
            self._notify_queue.get_nowait()

    async def _handshake(self, client: BleakClient) -> tuple[bytes, bytes] | None:
        """Run StartSession; return (our_sk, our_sid) for use in commands."""
        random_a = os.urandom(8)
        self._drain_queue()
        await client.write_gatt_char(
            TX_CHAR_UUID,
            bytes([0x00, 0x0A, 0x90, 0x02]) + random_a,
            response=True,
        )
        resp = await asyncio.wait_for(self._notify_queue.get(), timeout=RESPONSE_TIMEOUT)
        our_sid, our_sk = derive_session(self.security.ltk, random_a, resp[4:12])
        return our_sk, our_sid

    async def _probe(self, client: BleakClient, our_sk: bytes, our_sid: bytes) -> int | None:
        """Send a CC=0 probe; return the device's current resp_cc or None on failure."""
        probe = build_open_command(our_sk, our_sid, 0, self.security.user_id)
        await client.write_gatt_char(TX_CHAR_UUID, probe, response=True)
        r = await asyncio.wait_for(self._notify_queue.get(), timeout=RESPONSE_TIMEOUT)
        if is_nack(r):
            return None
        return extract_response_cc(r)

    async def _session_with_probe(self, client: BleakClient) -> int | None:
        """Handshake + probe; return resp_cc for use in all commands except open_gate."""
        result = await self._handshake(client)
        if result is None:
            return None
        our_sk, our_sid = result
        return await self._probe(client, our_sk, our_sid)

    async def open_gate(self) -> bool:
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=20.0)
        except asyncio.TimeoutError:
            _LOGGER.warning("open_gate timed out waiting for lock")
            return False
        try:
            for attempt in range(3):
                try:
                    return await self._do_open()
                except Exception as e:
                    _LOGGER.warning("Attempt %d failed: %s", attempt + 1, e)
                    self._conn = None
                    if attempt < 2:
                        await asyncio.sleep(2)
            return False
        finally:
            self._lock.release()

    async def _do_open(self) -> bool:
        client = await self._ensure_connected()

        result = await self._handshake(client)
        if result is None:
            return False
        our_sk, our_sid = result

        # Try stored CC first (saves one round-trip in the common case)
        current_cc = self.security.last_cc
        pkt = build_open_command(
            self.security.session_key,
            self.security.session_id,
            current_cc,
            self.security.user_id,
            self.action,
        )
        await client.write_gatt_char(TX_CHAR_UUID, pkt, response=True)

        try:
            r = await asyncio.wait_for(self._notify_queue.get(), timeout=RESPONSE_TIMEOUT)
        except TimeoutError:
            self.security.last_cc = current_cc + 1
            _LOGGER.info("Gate opened (timeout, assuming OK) last_cc=%d", current_cc + 1)
            return True

        if is_nack(r):
            # Stored CC is stale — probe to get the current one and retry
            _LOGGER.debug("NACK on last_cc=%d, probing for current CC", current_cc)
            resp_cc = await self._probe(client, our_sk, our_sid)
            if resp_cc is None:
                return False
            pkt2 = build_open_command(
                self.security.session_key,
                self.security.session_id,
                resp_cc,
                self.security.user_id,
                self.action,
            )
            await client.write_gatt_char(TX_CHAR_UUID, pkt2, response=True)
            try:
                r = await asyncio.wait_for(self._notify_queue.get(), timeout=RESPONSE_TIMEOUT)
            except TimeoutError:
                self.security.last_cc = resp_cc + 1
                _LOGGER.info("Gate opened (timeout after probe) last_cc=%d", resp_cc + 1)
                return True
            new_cc = await self._collect_response(resp_cc, first=r)
        else:
            new_cc = await self._collect_response(current_cc, first=r)

        self.security.last_cc = new_cc
        _LOGGER.info("Gate opened! last_cc=%d battery_raw=%s", new_cc, self.security.battery_raw)
        await self._release()
        return True

    async def _collect_response(self, last_cc: int, first: bytes | None = None) -> int:
        new_cc = last_cc + 1
        packets: list[bytes] = [first] if first is not None else []

        for _ in range(3):
            try:
                pkt = await asyncio.wait_for(self._notify_queue.get(), timeout=2.0)
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
                    _LOGGER.debug("Greeting: battery_raw=%d, CC=%d", battery_raw, greeting_cc)
            elif len(pkt) == 16:
                cc_from_resp = extract_response_cc(pkt)
                if cc_from_resp:
                    new_cc = cc_from_resp

        return new_cc

    async def get_system_info(self) -> dict[str, Any]:
        for attempt in range(3):
            async with self._lock:
                try:
                    return await self._do_get_system_info()
                except Exception as e:
                    _LOGGER.warning("get_system_info failed: %s", e)
                    self._conn = None
            # Release lock during retry sleep so open_gate can run
            if attempt < 2:
                await asyncio.sleep(10)
        return {}

    async def _do_get_system_info(self) -> dict[str, Any]:
        from .protocol import (
            assemble_fragments,
            build_get_system_info,
            decrypt_system_info,
        )

        client = await self._ensure_connected()
        resp_cc = await self._session_with_probe(client)
        if resp_cc is None:
            return {}

        pkt = build_get_system_info(
            self.security.session_key,
            self.security.session_id,
            resp_cc,
            self.security.user_id,
        )
        await client.write_gatt_char(TX_CHAR_UUID, pkt, response=True)

        frags: list[bytes] = []
        for _ in range(5):
            try:
                rx = await asyncio.wait_for(self._notify_queue.get(), timeout=2.0)
                frags.append(rx)
                if (rx[0] >> 4) == 4:
                    if len(frags) >= rx[2]:
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
            await self._release()
            return info
        await self._release()
        return {}

    async def clone_remote(self, action: int = 0) -> int | None:
        return await self._do_transmit(bytes([0x02, action & 0xFF]))

    async def set_opening_time(self, action: int = 0, time_s: int = 0) -> int | None:
        return await self._do_transmit(
            bytes([0x07, action & 0xFF, time_s & 0xFF, (time_s >> 8) & 0xFF])
        )

    async def _do_transmit(self, plaintext: bytes, timeout: float = 15.0) -> int | None:
        import struct as _struct

        from Crypto.Cipher import AES as _AES

        from .protocol import CCM_TAG_LEN, build_tlv

        try:
            client = await self._ensure_connected()
            resp_cc = await self._session_with_probe(client)
            if resp_cc is None:
                return None

            cc = resp_cc + 1
            nonce = self.security.session_id[:8] + _struct.pack("<I", cc)
            aad = _struct.pack("<H", self.security.user_id) + _struct.pack("<I", cc) + b"\x01"
            cipher = _AES.new(
                self.security.session_key, _AES.MODE_CCM, nonce=nonce, mac_len=CCM_TAG_LEN
            )
            cipher.update(aad)
            ct, tag = cipher.encrypt_and_digest(plaintext)
            payload = (
                b"\x01"
                + ct
                + tag
                + _struct.pack("<H", self.security.user_id)
                + _struct.pack("<I", cc)
            )
            await client.write_gatt_char(TX_CHAR_UUID, build_tlv(payload), response=True)

            ack = await asyncio.wait_for(self._notify_queue.get(), timeout=timeout)
            _LOGGER.debug("_do_transmit RX: %s", ack.hex())

            if is_nack(ack):
                await self._release()
                return None
            result = ack[3] & 0xFF if len(ack) >= 8 else 0
            await self._release()
            return result

        except Exception as e:
            _LOGGER.error("_do_transmit failed: %s", e)
            self._conn = None
            return None

    async def pair(self) -> SecurityData | None:
        """Pairing uses a fresh disposable connection (device is in factory-reset state)."""
        import hashlib

        from cryptography.hazmat.primitives.asymmetric.ec import (
            ECDH,
            SECP256R1,
            EllipticCurvePublicNumbers,
            generate_private_key,
        )
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

        try:
            private_key = generate_private_key(SECP256R1())
            pub_bytes = private_key.public_key().public_bytes(
                Encoding.X962, PublicFormat.UncompressedPoint
            )[1:]

            q: asyncio.Queue[bytes] = asyncio.Queue()
            async with BleakClient(self.address, timeout=CONNECT_TIMEOUT) as client:
                try:
                    if hasattr(client, "_backend"):
                        client._backend._mtu_size = 247  # type: ignore[attr-defined]
                except Exception:
                    pass
                await client.start_notify(RX_CHAR_UUID, lambda _, d: q.put_nowait(bytes(d)))
                await asyncio.sleep(0.2)

                pkt = bytes([0x00, 0x42, 0x90, 0x01]) + pub_bytes
                _LOGGER.debug("TX StartPairing (%dB): %s", len(pkt), pkt.hex())
                await client.write_gatt_char(TX_CHAR_UUID, pkt, response=True)

                resp = await asyncio.wait_for(q.get(), timeout=10.0)
                _LOGGER.debug("RX StartPairing (%dB): %s", len(resp), resp.hex())

                if len(resp) < 66 or resp[2] != 0x90:
                    _LOGGER.error("Unexpected pairing response: %s", resp.hex())
                    return None

                device_pub_bytes = resp[4:68]
                x = int.from_bytes(device_pub_bytes[:32], "big")
                y = int.from_bytes(device_pub_bytes[32:], "big")
                device_pub = EllipticCurvePublicNumbers(x, y, SECP256R1()).public_key()

                shared = private_key.exchange(ECDH(), device_pub)
                ltk = hashlib.sha256(shared).digest()[:16]
                _LOGGER.info("Pairing complete, LTK=%s", ltk.hex())

                return SecurityData(ltk=ltk, session_key=bytes(16), session_id=bytes(8), user_id=0)

        except Exception as e:
            _LOGGER.error("Pairing failed: %s", e)
            return None

    async def start_scanner(self, action: int = 0) -> bool:
        result = await self._do_transmit(bytes([0x0C, action & 0xFF]), timeout=30.0)
        return result is not None

    async def confirm_scanner(self, action: int = 0) -> bool:
        result = await self._do_transmit(bytes([0x0D, action & 0xFF]))
        return result is not None

    async def complete_scanner(self, action: int = 0) -> bool:
        result = await self._do_transmit(bytes([0x0E, action & 0xFF]))
        return result is not None

    async def undo_scanner(self, action: int = 0) -> bool:
        result = await self._do_transmit(bytes([0x0F, action & 0xFF]))
        return result is not None

    async def set_device_name(self, name: str) -> bool:
        name_bytes = name.encode("utf-8")[:4]
        result = await self._do_settings(bytes([0x02]) + name_bytes)
        return result is not None

    async def set_dst(self, enabled: bool) -> bool:
        result = await self._do_settings(bytes([0x03, 0x01 if enabled else 0x00]))
        return result is not None

    async def _do_settings(self, plaintext: bytes) -> int | None:
        import struct as _struct

        from Crypto.Cipher import AES as _AES

        from .protocol import CCM_TAG_LEN, build_tlv

        try:
            client = await self._ensure_connected()
            resp_cc = await self._session_with_probe(client)
            if resp_cc is None:
                return None

            cc = resp_cc + 1
            nonce = self.security.session_id[:8] + _struct.pack("<I", cc)
            aad = _struct.pack("<H", self.security.user_id) + _struct.pack("<I", cc) + b"\x10"
            cipher = _AES.new(
                self.security.session_key, _AES.MODE_CCM, nonce=nonce, mac_len=CCM_TAG_LEN
            )
            cipher.update(aad)
            ct, tag = cipher.encrypt_and_digest(plaintext)
            payload = (
                b"\x10"
                + ct
                + tag
                + _struct.pack("<H", self.security.user_id)
                + _struct.pack("<I", cc)
            )
            await client.write_gatt_char(TX_CHAR_UUID, build_tlv(payload), response=True)

            ack = await asyncio.wait_for(self._notify_queue.get(), timeout=RESPONSE_TIMEOUT)
            _LOGGER.debug("_do_settings RX: %s", ack.hex())
            if is_nack(ack):
                await self._release()
                return None
            result = ack[3] & 0xFF if len(ack) >= 4 else 0
            await self._release()
            return result

        except Exception as e:
            _LOGGER.error("_do_settings failed: %s", e)
            self._conn = None
            return None

    async def get_users_count(self) -> int | None:
        result = await self._do_user_cmd(bytes([0x02]))
        if result and len(result) >= 2:
            return int.from_bytes(result[:2], "little")
        return None

    async def get_user(self, uid: int) -> dict | None:
        result = await self._do_user_cmd(bytes([0x01, uid & 0xFF, (uid >> 8) & 0xFF]))
        return self._parse_user(result) if result else None

    def _parse_user(self, bArr: bytes) -> dict:
        if len(bArr) < 22:
            return {}
        return {
            "uid": int.from_bytes(bArr[0:2], "little"),
            "type": bArr[2],
            "id_token": int.from_bytes(bArr[3:5], "little"),
            "options_mask": bArr[5],
            "actions_mask": bArr[6],
            "day_mask": bArr[7],
            "start_date": int.from_bytes(bArr[16:20], "little"),
            "duration_hours": int.from_bytes(bArr[20:22], "little"),
            "name": bArr[22:-1].decode("utf-8", "ignore") if len(bArr) > 23 else "",
        }

    async def _do_user_cmd(self, plaintext: bytes) -> bytes | None:
        import struct as _struct

        from Crypto.Cipher import AES as _AES

        from .protocol import CCM_TAG_LEN, assemble_fragments, build_tlv

        try:
            client = await self._ensure_connected()
            resp_cc = await self._session_with_probe(client)
            if resp_cc is None:
                return None

            cc = resp_cc + 1
            nonce = self.security.session_id[:8] + _struct.pack("<I", cc)
            aad = _struct.pack("<H", self.security.user_id) + _struct.pack("<I", cc) + b"\x07"
            cipher = _AES.new(
                self.security.session_key, _AES.MODE_CCM, nonce=nonce, mac_len=CCM_TAG_LEN
            )
            cipher.update(aad)
            ct, tag = cipher.encrypt_and_digest(plaintext)
            payload = (
                b"\x07"
                + ct
                + tag
                + _struct.pack("<H", self.security.user_id)
                + _struct.pack("<I", cc)
            )
            await client.write_gatt_char(TX_CHAR_UUID, build_tlv(payload), response=True)

            frags: list[bytes] = []
            for _ in range(5):
                try:
                    rx = await asyncio.wait_for(self._notify_queue.get(), timeout=2.0)
                    frags.append(rx)
                    if (rx[0] >> 4) == 4:
                        if len(frags) >= rx[2]:
                            break
                    else:
                        break
                except TimeoutError:
                    break

            assembled = assemble_fragments(frags)
            if not assembled:
                return None

            d = assembled
            cc_r = int.from_bytes(d[-4:], "little")
            b_arr = assembled[1:-6]
            cmd = assembled[0]
            nonce2 = self.security.session_id[:8] + _struct.pack("<I", cc_r)
            aad2 = _struct.pack("<H", 0) + _struct.pack("<I", cc_r) + bytes([cmd])
            c2 = _AES.new(
                self.security.session_key, _AES.MODE_CCM, nonce=nonce2, mac_len=CCM_TAG_LEN
            )
            c2.update(aad2)
            pt = c2.decrypt_and_verify(b_arr[:-CCM_TAG_LEN], b_arr[-CCM_TAG_LEN:])
            if pt[0] != 0:
                await self._release()
                return None
            await self._release()
            return pt[1:]

        except Exception as e:
            _LOGGER.error("_do_user_cmd failed: %s", e)
            self._conn = None
            return None

    async def get_users(self) -> list[dict]:
        try:
            return await self._do_get_users()
        except Exception as e:
            _LOGGER.error("get_users failed: %s", e)
            return []

    async def _do_get_users(self) -> list[dict]:
        import struct as _struct

        from Crypto.Cipher import AES as _AES

        from .protocol import CCM_TAG_LEN, assemble_fragments, build_tlv

        def build_user_cmd(last_cc: int, plaintext: bytes) -> bytes:
            cc = last_cc + 1
            nonce = self.security.session_id[:8] + _struct.pack("<I", cc)
            aad = _struct.pack("<H", self.security.user_id) + _struct.pack("<I", cc) + b"\x07"
            cipher = _AES.new(
                self.security.session_key, _AES.MODE_CCM, nonce=nonce, mac_len=CCM_TAG_LEN
            )
            cipher.update(aad)
            ct, tag = cipher.encrypt_and_digest(plaintext)
            payload = (
                b"\x07"
                + ct
                + tag
                + _struct.pack("<H", self.security.user_id)
                + _struct.pack("<I", cc)
            )
            return build_tlv(payload)

        def decrypt_user_response(assembled: bytes) -> tuple[int, bytes, int]:
            cc = int.from_bytes(assembled[-4:], "little")
            b_arr = assembled[1:-6]
            cmd = assembled[0]
            nonce = self.security.session_id[:8] + _struct.pack("<I", cc)
            aad = _struct.pack("<H", 0) + _struct.pack("<I", cc) + bytes([cmd])
            cipher = _AES.new(
                self.security.session_key, _AES.MODE_CCM, nonce=nonce, mac_len=CCM_TAG_LEN
            )
            cipher.update(aad)
            pt = cipher.decrypt_and_verify(b_arr[:-CCM_TAG_LEN], b_arr[-CCM_TAG_LEN:])
            return pt[0], pt[1:], cc

        def parse_user(bArr: bytes) -> dict:
            if len(bArr) < 22:
                return {}
            import datetime

            start = int.from_bytes(bArr[16:20], "little")
            return {
                "uid": int.from_bytes(bArr[0:2], "little"),
                "type": bArr[2],
                "options_mask": bArr[5],
                "actions_mask": bArr[6],
                "day_mask": bArr[7],
                "start_date": datetime.datetime.fromtimestamp(start, tz=datetime.UTC).strftime(
                    "%Y-%m-%d"
                )
                if start
                else None,
                "duration_h": int.from_bytes(bArr[20:22], "little"),
                "name": bArr[22:].rstrip(b"\x00").decode("utf-8", "ignore"),
            }

        client = await self._ensure_connected()
        resp_cc = await self._session_with_probe(client)
        if resp_cc is None:
            return []

        async def send_and_recv(last_cc: int, plaintext: bytes) -> tuple[int, bytes, int]:
            await client.write_gatt_char(TX_CHAR_UUID, build_user_cmd(last_cc, plaintext), response=True)
            frags: list[bytes] = []
            for _ in range(5):
                try:
                    rx = await asyncio.wait_for(self._notify_queue.get(), timeout=2.0)
                    frags.append(rx)
                    if (rx[0] >> 4) == 4:
                        if len(frags) >= rx[2]:
                            break
                    else:
                        break
                except TimeoutError:
                    break
            assembled = assemble_fragments(frags)
            if not assembled:
                return -1, b"", last_cc + 1
            return decrypt_user_response(assembled)

        users: list[dict] = []
        offset = 0
        while True:
            rc, payload, resp_cc = await send_and_recv(
                resp_cc, bytes([0x03, offset & 0xFF, (offset >> 8) & 0xFF])
            )
            if rc != 0 or not payload:
                break
            user = parse_user(payload)
            if user:
                users.append(user)
            offset += 1

        _LOGGER.debug("Loaded %d users", len(users))
        await self._release()
        return users

    async def add_user(self) -> dict | None:
        result = await self._do_user_cmd(bytes([0x0C]))
        if result and len(result) >= 18:
            uid = int.from_bytes(result[0:2], "little")
            ltk = result[2:18].hex().upper()
            _LOGGER.info("User added: uid=%d, ltk=%s", uid, ltk)
            return {"uid": uid, "ltk": ltk}
        return None

    async def delete_user(self, uid: int) -> bool:
        result = await self._do_user_cmd(bytes([0x06, uid & 0xFF, (uid >> 8) & 0xFF]))
        return result is not None

    async def set_user_name(self, uid: int, name: str) -> bool:
        name_bytes = name.encode("utf-8")[:4]
        plaintext = bytes([0x04, uid & 0xFF, (uid >> 8) & 0xFF]) + name_bytes
        result = await self._do_user_cmd(plaintext)
        return result is not None
