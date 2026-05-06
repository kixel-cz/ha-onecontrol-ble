"""1Control SoloMini BLE integration for Home Assistant."""

from __future__ import annotations

import logging
from datetime import timedelta

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
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .ble_client import SoloMiniClient
from .protocol import SecurityData

_LOGGER = logging.getLogger(__name__)
DOMAIN = "onecontrol_ble"
PLATFORMS = ["button", "cover", "number", "sensor", "switch", "text"]
SCAN_INTERVAL = timedelta(hours=1)


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

    coordinator: DataUpdateCoordinator[dict] = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"onecontrol_{address}",
        update_method=client.get_system_info,
        update_interval=SCAN_INTERVAL,
    )

    hass.data[DOMAIN][entry.entry_id] = client
    hass.data[DOMAIN][f"{entry.entry_id}_coordinator"] = coordinator

    from datetime import timedelta

    users_coordinator: DataUpdateCoordinator[list] = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"onecontrol_{address}_users",
        update_method=client.get_users,
        update_interval=timedelta(hours=6),
    )
    hass.data[DOMAIN][f"{entry.entry_id}_users_coordinator"] = users_coordinator

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

    hass.async_create_task(coordinator.async_request_refresh())
    hass.async_create_task(users_coordinator.async_request_refresh())

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
