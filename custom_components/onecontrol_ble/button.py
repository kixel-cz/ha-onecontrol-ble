"""Button entities for 1Control SoloMini BLE."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .ble_client import SoloMiniClient

_LOGGER = logging.getLogger(__name__)
DOMAIN = "onecontrol_ble"

BUTTON_DESCRIPTIONS: tuple[ButtonEntityDescription, ...] = (
    ButtonEntityDescription(
        key="clone_remote",
        name="Learn remote",
        icon="mdi:remote",
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client: SoloMiniClient = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [SoloMiniButton(client, entry, description) for description in BUTTON_DESCRIPTIONS]
    )


class SoloMiniButton(ButtonEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        client: SoloMiniClient,
        entry: ConfigEntry,
        description: ButtonEntityDescription,
    ) -> None:
        self._client = client
        self._entry = entry
        self.entity_description = description
        self._attr_unique_id = (
            f"onecontrol_{entry.data['address'].replace(':', '').lower()}_{description.key}"
        )
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, entry.data["address"])},
        )

    async def async_press(self, **kwargs: Any) -> None:
        if self.entity_description.key == "clone_remote":
            action = self._entry.data.get("action", 0)
            _LOGGER.info("Starting remote clone for action=%d", action)
            result = await self._client.clone_remote(action)
            if result is not None:
                _LOGGER.info("Remote cloned, slot=%d", result)
            else:
                _LOGGER.error("Remote clone failed")
