"""1Control SoloMini BLE integration for Home Assistant."""
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

DOMAIN = "onecontrol_ble"

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from .cover import async_setup_entry as cover_setup
    return await cover_setup(hass, entry)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from .cover import async_unload_entry as cover_unload
    return await cover_unload(hass, entry)
