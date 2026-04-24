"""Battery and system sensors for 1Control SoloMini BLE."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory
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


SENSOR_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="battery_raw",
        name="Battery Raw",
        icon="mdi:battery-unknown",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="name",
        name="Device Name",
        icon="mdi:label",
    ),
    SensorEntityDescription(
        key="version",
        name="Firmware Version",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="production",
        name="Production Date",
        icon="mdi:calendar",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="serial",
        name="Serial Number",
        icon="mdi:identifier",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="max_actions",
        name="Max Actions",
        icon="mdi:counter",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="max_users",
        name="Max Users",
        icon="mdi:account-multiple",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="cloned_mask",
        name="Cloned Mask",
        icon="mdi:remote",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="dst",
        name="DST Enabled",
        icon="mdi:clock-time-eight",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="sys_options",
        name="System Options",
        icon="mdi:cog",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


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

    entities: list[SensorEntity] = [SoloMiniBatterySensor(coordinator, client, entry)]
    for description in SENSOR_DESCRIPTIONS:
        entities.append(SoloMiniInfoSensor(coordinator, entry, description))

    async_add_entities(entities)
    hass.async_create_task(coordinator.async_request_refresh())


def _device_info(entry: ConfigEntry, data: dict[str, Any]) -> dr.DeviceInfo:
    version = data.get("version")
    production = data.get("production")
    return dr.DeviceInfo(
        identifiers={(DOMAIN, entry.data["address"])},
        name=entry.data.get("name", "SoloMini"),
        manufacturer="1Control",
        model="SoloMini RE",
        sw_version=f"1.{version}" if version else None,
        hw_version=(
            datetime.fromtimestamp(production, tz=UTC).strftime("%Y-%m-%d") if production else None
        ),
        serial_number=str(data["serial"]) if data.get("serial") else None,
        connections={(dr.CONNECTION_BLUETOOTH, entry.data["address"])},
    )


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
        self._attr_device_info = _device_info(entry, coordinator.data or {})

    def _handle_coordinator_update(self) -> None:
        self._attr_device_info = _device_info(self._entry, self.coordinator.data or {})
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> int | None:
        if not self.coordinator.data:
            return None
        raw = self.coordinator.data.get("battery_raw")
        if raw is None:
            return None
        return raw_to_percent(raw)


class SoloMiniInfoSensor(CoordinatorEntity[DataUpdateCoordinator[dict[str, Any]]], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        entry: ConfigEntry,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = (
            f"onecontrol_{entry.data['address'].replace(':', '').lower()}_{description.key}"
        )
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, entry.data["address"])},
        )

    @property
    def native_value(self) -> Any:
        if not self.coordinator.data:
            return None
        value = self.coordinator.data.get(self.entity_description.key)
        # Převod epoch na datum
        if self.entity_description.key == "production" and value:
            return datetime.fromtimestamp(value, tz=UTC).strftime("%Y-%m-%d")
        # Převod version na string
        if self.entity_description.key == "version" and value is not None:
            return f"1.{value}"
        return value
