"""Battery sensor for 1Control SoloMini BLE."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .ble_client import SoloMiniClient

_LOGGER = logging.getLogger(__name__)
DOMAIN = "onecontrol_ble"
SCAN_INTERVAL = timedelta(hours=1)

BATTERY_HIGH = 3200  # TODO: calibrate
BATTERY_MED = 2400  # TODO: calibrate
BATTERY_LOW = 1800  # TODO: calibrate


def raw_to_percent(raw: int) -> int:
    if raw >= BATTERY_HIGH:
        return 100
    if raw <= BATTERY_LOW:
        return 0
    return int((raw - BATTERY_LOW) / (BATTERY_HIGH - BATTERY_LOW) * 100)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client: SoloMiniClient = hass.data[DOMAIN][entry.entry_id]

    coordinator: DataUpdateCoordinator[dict[str, Any] | None] = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"onecontrol_{entry.data['address']}",
        update_method=client.get_system_info,
        update_interval=SCAN_INTERVAL,
    )
    await coordinator.async_config_entry_first_refresh()

    async_add_entities([SoloMiniBatterySensor(coordinator, client, entry)])


class SoloMiniBatterySensor(CoordinatorEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_has_entity_name = True
    _attr_name = "Battery"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[dict[str, Any] | None],
        client: SoloMiniClient,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._client = client
        self._attr_unique_id = (
            f"onecontrol_{entry.data['address'].replace(':', '').lower()}_battery"
        )
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, entry.data["address"])},
            name=entry.data.get("name", "SoloMini"),
            manufacturer="1Control",
            model="SoloMini RE",
            sw_version=str(self.coordinator.data.get("version", ""))
            if self.coordinator.data
            else None,
        )

    @property
    def native_value(self) -> int | None:
        if not self.coordinator.data:
            return None
        raw = self.coordinator.data.get("battery_raw")
        if raw is None:
            return None
        return raw_to_percent(raw)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self.coordinator.data:
            return {}
        data = self.coordinator.data
        return {
            "battery_raw": data.get("battery_raw"),
            "name": data.get("name"),
            "version": data.get("version"),
            "serial": data.get("serial"),
            "max_actions": data.get("max_actions"),
            "production": data.get("production"),
        }
