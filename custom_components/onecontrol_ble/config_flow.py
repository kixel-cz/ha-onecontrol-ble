"""Config flow pro 1Control SoloMini BLE."""
from __future__ import annotations
import logging
from typing import Any
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
DOMAIN = "onecontrol_ble"

CONF_ADDRESS = "address"
CONF_LTK     = "ltk"
CONF_USER_ID = "user_id"
CONF_ACTION  = "action"
CONF_SERIAL  = "serial"
CONF_NAME    = "name"


class OneControlConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow — LTK je volitelné, pairing proběhne automaticky."""
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            ltk = user_input.get(CONF_LTK, "").strip().lower().replace(" ", "")
            if ltk and (
                len(ltk) != 32
                or not all(c in "0123456789abcdef" for c in ltk)
            ):
                errors[CONF_LTK] = "ltk_invalid"
            else:
                address = user_input[CONF_ADDRESS].upper().strip()
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME, "SoloMini"),
                    data={
                        CONF_ADDRESS: address,
                        CONF_LTK:     ltk,
                        CONF_USER_ID: user_input.get(CONF_USER_ID, 0),
                        CONF_ACTION:  user_input.get(CONF_ACTION, 1),
                        CONF_SERIAL:  user_input.get(CONF_SERIAL, 0),
                        CONF_NAME:    user_input.get(CONF_NAME, "SoloMini"),
                    },
                )

        schema = vol.Schema({
            vol.Required(CONF_ADDRESS): str,
            vol.Optional(CONF_NAME,    default="SoloMini"): str,
            vol.Optional(CONF_ACTION,  default=1): int,
            vol.Optional(CONF_LTK,     default=""): str,
            vol.Optional(CONF_USER_ID, default=0): int,
            vol.Optional(CONF_SERIAL,  default=0): int,
        })
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )
