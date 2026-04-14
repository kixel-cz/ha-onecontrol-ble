"""Cover entita pro 1Control SoloMini BLE."""
from __future__ import annotations
import logging
from typing import Any

from homeassistant.components.cover import (
    CoverDeviceClass, CoverEntity, CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.storage import Store

from .protocol import SecurityData
from .ble_client import SoloMiniClient

_LOGGER = logging.getLogger(__name__)

DOMAIN      = "onecontrol_ble"
STORAGE_KEY = "onecontrol_ble_security"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    ltk_hex = entry.data.get("ltk", "")
    store = Store(hass, 1, f"{STORAGE_KEY}_{entry.entry_id}")
    stored = await store.async_load()

    if stored and stored.get("ltk"):
        sec = SecurityData.from_dict(stored)
        _LOGGER.debug("Loaded LTK from storage")
    elif ltk_hex:
        sec = SecurityData(
            ltk=bytes.fromhex(ltk_hex),
            user_id=entry.data.get("user_id", 0),
        )
    else:
        sec = None
        _LOGGER.debug("No LTK — will pair on first open")

    def on_paired(new_sec: SecurityData) -> None:
        hass.async_create_task(store.async_save(new_sec.to_dict()))
        _LOGGER.info("Pairing complete, LTK saved")

    client = SoloMiniClient(
        address=entry.data["address"],
        security=sec,
        action=entry.data.get("action", 1),
        on_paired=on_paired,
    )
    hass.data[DOMAIN][entry.entry_id] = client
    async_add_entities([SoloMiniCover(client, entry)], True)


class SoloMiniCover(CoverEntity):
    _attr_device_class       = CoverDeviceClass.GARAGE
    _attr_supported_features = CoverEntityFeature.OPEN
    _attr_should_poll        = False
    _attr_assumed_state      = True
    _attr_is_closed          = None
    _attr_is_opening         = False
    _attr_has_entity_name    = True
    _attr_name               = None

    def __init__(self, client: SoloMiniClient, entry: ConfigEntry) -> None:
        self._client = client
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
        else:
            _LOGGER.error("Failed to open gate %s", self._client.address)
        self.async_write_ha_state()

    @property
    def is_closed(self) -> bool | None:
        return self._attr_is_closed

