"""Switch entity for SoloMini BLE."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
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
    coordinator: DataUpdateCoordinator[dict[str, Any]] | None = (
        hass.data[DOMAIN].get(f"{entry.entry_id}_coordinator")
    )
    async_add_entities([SoloMiniDSTSwitch(client, entry, coordinator)])


class SoloMiniDSTSwitch(
    CoordinatorEntity[DataUpdateCoordinator[dict[str, Any]]], SwitchEntity
):
    _attr_has_entity_name = True
    _attr_name = "Daylight saving time"
    _attr_icon = "mdi:clock-time-eight"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        client: SoloMiniClient,
        entry: ConfigEntry,
        coordinator: DataUpdateCoordinator[dict[str, Any]] | None,
    ) -> None:
        if coordinator is not None:
            super().__init__(coordinator)
        else:
            SwitchEntity.__init__(self)  # type: ignore[misc]
        self._client = client
        self._entry = entry
        self._attr_unique_id = (
            f"onecontrol_{entry.data['address'].replace(':', '').lower()}_dst"
        )
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, entry.data["address"])},
        )

    @property
    def is_on(self) -> bool | None:
        if hasattr(self, "coordinator") and self.coordinator.data:
            return self.coordinator.data.get("dst")
        return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        ok = await self._client.set_dst(True)  # type: ignore[attr-defined]
        if ok:
            _LOGGER.info("DST enabled")
            if hasattr(self, "coordinator"):
                await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Failed to enable DST")

    async def async_turn_off(self, **kwargs: Any) -> None:
        ok = await self._client.set_dst(False)  # type: ignore[attr-defined]
        if ok:
            _LOGGER.info("DST disabled")
            if hasattr(self, "coordinator"):
                await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Failed to disable DST")
