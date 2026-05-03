"""Text entity for SoloMini BLE."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client: SoloMiniClient = hass.data[DOMAIN][entry.entry_id]
    coordinator: DataUpdateCoordinator[dict[str, Any]] = hass.data[DOMAIN][
        f"{entry.entry_id}_coordinator"
    ]
    async_add_entities([SoloMiniDeviceName(client, entry, coordinator)])


class SoloMiniDeviceName(CoordinatorEntity[DataUpdateCoordinator[dict[str, Any]]], TextEntity):
    _attr_has_entity_name = True
    _attr_name = "Device name"
    _attr_icon = "mdi:label"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = TextMode.TEXT
    _attr_native_min = 1
    _attr_native_max = 4  # BLE MTU limit 20B -> max 4 chars

    def __init__(
        self,
        client: SoloMiniClient,
        entry: ConfigEntry,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
    ) -> None:
        super().__init__(coordinator)
        self._client = client
        self._entry = entry
        self._attr_unique_id = (
            f"onecontrol_{entry.data['address'].replace(':', '').lower()}_device_name"
        )
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, entry.data["address"])},
        )

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data:
            name = self.coordinator.data.get("name", "")
            return name[:4] if name else None
        return None

    async def async_set_value(self, value: str) -> None:
        if len(value) > 4:
            _LOGGER.warning("Device name truncated to 4 characters (BLE MTU limit)")
            value = value[:4]
        ok = await self._client.set_device_name(value)  # type: ignore[attr-defined]
        if ok:
            _LOGGER.info("Device name set to '%s'", value)
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Failed to set device name")
