"""Cover entita pro 1Control SoloMini BLE."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .ble_client import SoloMiniClient
from .protocol import SecurityData

_LOGGER = logging.getLogger(__name__)
DOMAIN = "onecontrol_ble"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    sec = SecurityData(
        ltk=bytes.fromhex(entry.data["ltk"]),
        session_key=bytes.fromhex(entry.data["session_key"]),
        session_id=bytes.fromhex(entry.data["session_id"]),
        user_id=entry.data.get("user_id", 0),
        last_cc=entry.data.get("last_cc", 0),
    )
    client = SoloMiniClient(
        address=entry.data["address"],
        security=sec,
        action=entry.data.get("action", 0),
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = client
    async_add_entities([SoloMiniCover(client, entry)], True)


class SoloMiniCover(CoverEntity):
    _attr_device_class = CoverDeviceClass.GARAGE
    _attr_supported_features = CoverEntityFeature.OPEN
    _attr_should_poll = False
    _attr_assumed_state = True
    _attr_is_closed = None
    _attr_is_opening = False
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, client: SoloMiniClient, entry: ConfigEntry) -> None:
        self._client = client
        self._entry = entry
        self._attr_unique_id = f"onecontrol_{entry.data['address'].replace(':', '').lower()}"
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, entry.data["address"])},
            name=entry.data.get("name", "SoloMini"),
            manufacturer="1Control",
            model="SoloMini RE",
            sw_version="1.7",
        )

    async def async_open_cover(self, **kwargs: Any) -> None:
        self._attr_is_opening = True
        self.async_write_ha_state()
        success = await self._client.open_gate()
        self._attr_is_opening = False
        if success:
            self._attr_is_closed = False
            # Ulož aktualizovaný last_cc do config entry
            self.hass.config_entries.async_update_entry(
                self._entry,
                data={**self._entry.data, "last_cc": self._client.security.last_cc},
            )
        else:
            _LOGGER.error("Failed to open gate %s", self._client.address)
        self.async_write_ha_state()

    @property
    def is_closed(self) -> bool | None:
        return self._attr_is_closed
