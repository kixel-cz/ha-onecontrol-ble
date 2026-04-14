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
from .protocol import SecurityData
from .ble_client import SoloMiniClient

_LOGGER = logging.getLogger(__name__)

DOMAIN       = "onecontrol_ble"
CONF_ADDRESS = "address"
CONF_LTK     = "ltk"
CONF_USER_ID = "user_id"
CONF_ACTION  = "action"
CONF_SERIAL  = "serial"
CONF_NAME    = "name"
STORAGE_KEY  = "onecontrol_ble_security"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Nastaví Cover entitu z config entry."""
    hass.data.setdefault(DOMAIN, {})

    ltk_hex = entry.data.get(CONF_LTK, "")

    # Zkus načíst uloženou SecurityData (po předchozím párování)
    store = hass.helpers.storage.Store(1, f"{STORAGE_KEY}_{entry.entry_id}")
    stored = await store.async_load()

    if stored and stored.get("ltk"):
        sec = SecurityData.from_dict(stored)
        _LOGGER.debug("Loaded SecurityData from storage, LTK=%s...", sec.ltk.hex()[:8])
    elif ltk_hex:
        sec = SecurityData(
            ltk=bytes.fromhex(ltk_hex),
            user_id=entry.data.get(CONF_USER_ID, 0),
        )
        _LOGGER.debug("Using LTK from config")
    else:
        sec = None
        _LOGGER.debug("No LTK — will pair on first open")

    def on_paired(new_sec: SecurityData) -> None:
        """Uloží LTK po úspěšném ECDH párování."""
        hass.async_create_task(store.async_save(new_sec.to_dict()))
        _LOGGER.info("Pairing complete, LTK saved to storage")

    client = SoloMiniClient(
        address=entry.data[CONF_ADDRESS],
        security=sec,
        action=entry.data.get(CONF_ACTION, 1),
        on_paired=on_paired,
    )
    hass.data[DOMAIN][entry.entry_id] = client

    async_add_entities([SoloMiniCover(client, entry)])


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Odstraní integraci."""
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True


class SoloMiniCover(CoverEntity):
    """Cover entita pro SoloMini garážový ovladač."""

    _attr_device_class       = CoverDeviceClass.GARAGE
    _attr_supported_features = CoverEntityFeature.OPEN
    _attr_should_poll        = False
    _attr_assumed_state      = True
    _attr_is_closed          = None
    _attr_is_opening         = False

    def __init__(self, client: SoloMiniClient, entry: ConfigEntry) -> None:
        self._client = client
        self._attr_name      = entry.data.get(CONF_NAME, "SoloMini")
        self._attr_unique_id = f"onecontrol_{entry.data[CONF_ADDRESS].replace(':', '')}"
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, entry.data[CONF_ADDRESS])},
            name=self._attr_name,
            manufacturer="1Control",
            model="SoloMini RE",
            sw_version="1.7",
        )

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Otevře bránu přes BLE."""
        self._attr_is_opening = True
        self.async_write_ha_state()

        success = await self._client.open_gate()

        self._attr_is_opening = False
        if success:
            self._attr_is_closed = False
        else:
            _LOGGER.error("Failed to open gate %s", self._client.address)
        self.async_write_ha_state()
