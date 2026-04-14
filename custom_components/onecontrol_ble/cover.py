"""
Home Assistant Cover entity + Config Flow pro 1Control SoloMini BLE.
Podporuje automatický ECDH pairing — uživatel nemusí znát LTK.
"""
from __future__ import annotations
import logging
from typing import Any
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.cover import (
    CoverDeviceClass, CoverEntity, CoverEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
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


class OneControlConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow — LTK je volitelné (pairing proběhne automaticky)."""
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            ltk = user_input.get(CONF_LTK, "").strip().lower().replace(" ", "")
            if ltk and (len(ltk) != 32 or not all(c in "0123456789abcdef" for c in ltk)):
                errors[CONF_LTK] = "ltk_invalid"
            else:
                await self.async_set_unique_id(user_input[CONF_ADDRESS].upper())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME, "SoloMini"),
                    data={
                        CONF_ADDRESS: user_input[CONF_ADDRESS].upper(),
                        CONF_LTK:     ltk or "",   # prázdné = spáruj automaticky
                        CONF_USER_ID: user_input.get(CONF_USER_ID, 0),
                        CONF_ACTION:  user_input.get(CONF_ACTION, 1),
                        CONF_SERIAL:  user_input.get(CONF_SERIAL, 0),
                        CONF_NAME:    user_input.get(CONF_NAME, "SoloMini"),
                    },
                )

        schema = vol.Schema({
            vol.Required(CONF_ADDRESS): str,
            vol.Optional(CONF_LTK, default=""): str,
            vol.Optional(CONF_USER_ID, default=0): int,
            vol.Optional(CONF_ACTION,  default=1): int,
            vol.Optional(CONF_SERIAL,  default=0): int,
            vol.Optional(CONF_NAME,    default="SoloMini"): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


async def async_setup_entry(hass: HomeAssistant, entry: config_entries.ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    ltk_hex = entry.data.get(CONF_LTK, "")

    # Zkus načíst uloženou SecurityData ze storage
    store = hass.helpers.storage.Store(1, f"{STORAGE_KEY}_{entry.entry_id}")
    stored = await store.async_load()

    if stored and stored.get("ltk"):
        sec = SecurityData.from_dict(stored)
        _LOGGER.debug("Loaded SecurityData from storage")
    elif ltk_hex:
        sec = SecurityData(
            ltk=bytes.fromhex(ltk_hex),
            user_id=entry.data.get(CONF_USER_ID, 0),
        )
    else:
        sec = None  # bude spárováno při prvním open

    def on_paired(new_sec: SecurityData):
        """Callback po úspěšném ECDH párování — uloží LTK."""
        hass.async_create_task(store.async_save(new_sec.to_dict()))
        _LOGGER.info("Pairing complete, LTK saved")

    client = SoloMiniClient(
        address=entry.data[CONF_ADDRESS],
        security=sec,
        action=entry.data.get(CONF_ACTION, 1),
        on_paired=on_paired,
    )
    hass.data[DOMAIN][entry.entry_id] = client
    await hass.config_entries.async_forward_entry_setups(entry, ["cover"])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: config_entries.ConfigEntry) -> bool:
    await hass.config_entries.async_unload_platforms(entry, ["cover"])
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True


async def async_setup_entry_cover(hass, entry, async_add_entities):
    client = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SoloMiniCover(client, entry)])


class SoloMiniCover(CoverEntity):
    _attr_device_class       = CoverDeviceClass.GARAGE
    _attr_supported_features = CoverEntityFeature.OPEN
    _attr_should_poll        = False
    _attr_assumed_state      = True
    _attr_is_closed          = None

    def __init__(self, client: SoloMiniClient, entry):
        self._client = client
        self._attr_name       = entry.data.get(CONF_NAME, "SoloMini")
        self._attr_unique_id  = f"onecontrol_{entry.data[CONF_ADDRESS].replace(':', '')}"
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, entry.data[CONF_ADDRESS])},
            name=self._attr_name,
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
        self.async_write_ha_state()
