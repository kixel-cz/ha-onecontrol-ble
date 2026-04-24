"""Battery sensor for 1Control SoloMini BLE."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
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

BATTERY_HIGH = 3200  # TODO
BATTERY_LOW = 1800  # TODO


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

    coordinator: DataUpdateCoordinator[dict[str, Any]] = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"onecontrol_{entry.data['address']}",
        update_method=client.get_system_info,
        update_interval=SCAN_INTERVAL,
    )
    await coordinator.async_config_entry_first_refresh()

    async_add_entities([SoloMiniBatterySensor(coordinator, client, entry)])


class SoloMiniBatterySensor(CoordinatorEntity[DataUpdateCoordinator[dict[str, Any]]], SensorEntity):
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_has_entity_name = True
    _attr_name = "Battery"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        client: SoloMiniClient,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._client = client
        self._entry = entry
        self._attr_unique_id = (
            f"onecontrol_{entry.data['address'].replace(':', '').lower()}_battery"
        )
        self._update_device_info()

    def _update_device_info(self) -> None:
        data = self.coordinator.data or {}
        version = data.get("version")
        sw_version = f"1.{version}" if version else None
        production = data.get("production")
        hw_version = (
            datetime.fromtimestamp(production, tz=UTC).strftime("%Y-%m-%d") if production else None
        )
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, self._entry.data["address"])},
            name=self._entry.data.get("name", "SoloMini"),
            suggested_area=None,
            manufacturer="1Control",
            model="SoloMini",
            sw_version=sw_version,
            hw_version=hw_version,
            serial_number=str(data.get("serial")) if data.get("serial") else None,
        )

    def _handle_coordinator_update(self) -> None:
        self._update_device_info()
        super()._handle_coordinator_update()

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
        data = self.coordinator.data or {}
        attrs: dict[str, Any] = {}

        if (raw := data.get("battery_raw")) is not None:
            attrs["battery_raw"] = raw

        if (serial := data.get("serial")) is not None:
            attrs["serial"] = serial

        if name := data.get("name"):
            attrs["device_name"] = name

        if (version := data.get("version")) is not None:
            attrs["firmware_version"] = f"1.{version}"

        if production := data.get("production"):
            attrs["production_date"] = datetime.fromtimestamp(production, tz=UTC).strftime(
                "%Y-%m-%d"
            )

        if (max_actions := data.get("max_actions")) is not None:
            attrs["max_actions"] = max_actions

        if (max_users := data.get("max_users")) is not None:
            attrs["max_users"] = max_users

        if (cloned := data.get("cloned_mask")) is not None:
            attrs["cloned_mask"] = cloned

        if (dst := data.get("dst")) is not None:
            attrs["dst_enabled"] = dst

        if (sys_opts := data.get("sys_options")) is not None:
            attrs["system_options"] = sys_opts

        return attrs
