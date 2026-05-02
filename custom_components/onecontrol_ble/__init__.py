"""1Control SoloMini BLE integration for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
    async_register_callback,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .ble_client import SoloMiniClient
from .protocol import SecurityData

_LOGGER = logging.getLogger(__name__)
DOMAIN = "onecontrol_ble"
PLATFORMS = ["button", "cover", "number", "sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    sec = SecurityData(
        ltk=bytes.fromhex(entry.data["ltk"]),
        session_key=bytes.fromhex(entry.data["session_key"]),
        session_id=bytes.fromhex(entry.data["session_id"]),
        user_id=entry.data.get("user_id", 0),
        last_cc=entry.data.get("last_cc", 0),
    )

    address = entry.data["address"]
    ble_device = async_ble_device_from_address(hass, address, connectable=True)

    client = SoloMiniClient(
        address=address,
        security=sec,
        action=entry.data.get("action", 0),
        ble_device=ble_device,
    )
    hass.data[DOMAIN][entry.entry_id] = client

    @callback
    def _async_update_ble(
        service_info: BluetoothServiceInfoBleak,
        change: BluetoothChange,
    ) -> None:
        client.set_ble_device(service_info.device)
        _LOGGER.debug("BLE device updated: %s", service_info.address)

    entry.async_on_unload(
        async_register_callback(
            hass,
            _async_update_ble,
            BluetoothCallbackMatcher(address=address),
            BluetoothScanningMode.ACTIVE,
        )
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
