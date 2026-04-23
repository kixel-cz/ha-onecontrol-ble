"""Battery sensor for 1Control SoloMini BLE."""

from __future__ import annotations

import logging
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

from .ble_client import SoloMiniClient

_LOGGER = logging.getLogger(__name__)
DOMAIN = "onecontrol_ble"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client: SoloMiniClient = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SoloMiniBatterySensor(client, entry)], True)


class SoloMiniBatterySensor(SensorEntity):
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = "Battery"

    def __init__(self, client: SoloMiniClient, entry: ConfigEntry) -> None:
        self._client = client
        self._attr_unique_id = (
            f"onecontrol_{entry.data['address'].replace(':', '').lower()}_battery"
        )
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, entry.data["address"])},
        )

    @property
    def native_value(self) -> int | None:
        raw = self._client.security.battery_raw
        if raw is None:
            return None
        return _raw_to_percent(raw)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"battery_raw": self._client.security.battery_raw}


def _raw_to_percent(raw: int) -> int:
    # Just a placeholder for now
    FULL = 16000  # TODO: calibrate
    EMPTY = 11000  # TODO: calibrate
    pct = int((raw - EMPTY) / (FULL - EMPTY) * 100)
    return max(0, min(100, pct))
