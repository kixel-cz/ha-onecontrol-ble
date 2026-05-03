"""Text entity pro nastavení názvu zařízení SoloMini BLE."""
from __future__ import annotations

import logging

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
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
    async_add_entities([SoloMiniDeviceName(client, entry)])


class SoloMiniDeviceName(TextEntity):
    _attr_has_entity_name = True
    _attr_name = "Device name"
    _attr_icon = "mdi:label"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = TextMode.TEXT
    _attr_native_min = 1
    _attr_native_max = 4  # BLE MTU limit 20B → max 4 znaky
    _attr_native_value = ""

    def __init__(self, client: SoloMiniClient, entry: ConfigEntry) -> None:
        self._client = client
        self._entry = entry
        self._attr_unique_id = (
            f"onecontrol_{entry.data['address'].replace(':', '').lower()}_device_name"
        )
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, entry.data["address"])},
        )

    async def async_set_value(self, value: str) -> None:
        """Nastav název zařízení (max 4 znaky)."""
        if len(value) > 4:
            _LOGGER.warning("Device name truncated to 4 characters (BLE MTU limit)")
            value = value[:4]
        ok = await self._client.set_device_name(value)  # type: ignore[attr-defined]
        if ok:
            self._attr_native_value = value
            self.async_write_ha_state()
            _LOGGER.info("Device name set to '%s'", value)
        else:
            _LOGGER.error("Failed to set device name")
