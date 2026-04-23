"""Config flow pro 1Control SoloMini BLE."""
from __future__ import annotations
import logging, re
from typing import Any
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

_LOGGER = logging.getLogger(__name__)
DOMAIN = "onecontrol_ble"
SOLUMINI_SERVICE_UUID = "d973f2e0-b19e-11e2-9e96-0800200c9a66"


def parse_mitm_log(log_text: str) -> dict:
    result = {}
    for key, pattern in [
        ("ltk",         r'"ltk":"([0-9A-Fa-f]+)"'),
        ("session_key", r'"sessionKey":"([0-9A-Fa-f]+)"'),
        ("session_id",  r'"sessionID":"([0-9A-Fa-f]+)"'),
    ]:
        m = re.search(pattern, log_text)
        if m:
            result[key] = m.group(1).upper()
    return result


def _is_hex(s: str, length: int) -> bool:
    s = s.strip().lower().replace(" ", "")
    return len(s) == length and all(c in "0123456789abcdef" for c in s)


class OneControlConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._parsed = {}
        self._discovered_address = ""
        self._discovered_name = "SoloMini"

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> config_entries.FlowResult:
        """Automaticky objevené BLE zařízení."""
        address = discovery_info.address
        await self.async_set_unique_id(address)
        self._abort_if_unique_id_configured()
        self._discovered_address = address
        self._discovered_name = discovery_info.name or "SoloMini"
        self.context["title_placeholders"] = {
            "name": self._discovered_name,
            "address": address,
        }
        return await self.async_step_mitm()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Ruční spuštění — přeskoč rovnou na mitmproxy krok."""
        return await self.async_step_mitm(user_input)

    async def async_step_mitm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Krok 1: Volitelné vložení mitmproxy logu."""
        errors: dict[str, str] = {}

        if user_input is not None:
            mitm_log = user_input.get("mitm_log", "").strip()
            if mitm_log:
                parsed = parse_mitm_log(mitm_log)
                if parsed.get("ltk") and parsed.get("session_key") and parsed.get("session_id"):
                    self._parsed = parsed
                else:
                    errors["mitm_log"] = "parse_failed"
            if not errors:
                return await self.async_step_device()

        return self.async_show_form(
            step_id="mitm",
            data_schema=vol.Schema({
                vol.Optional("mitm_log", default=""): str,
            }),
            errors=errors,
        )

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Krok 2: BLE adresa a bezpečnostní klíče."""
        errors: dict[str, str] = {}

        if user_input is not None:
            ltk = user_input["ltk"].strip().lower().replace(" ", "")
            sk  = user_input["session_key"].strip().lower().replace(" ", "")
            sid = user_input["session_id"].strip().lower().replace(" ", "")

            if not _is_hex(ltk, 32):
                errors["ltk"] = "invalid_hex"
            elif not _is_hex(sk, 32):
                errors["session_key"] = "invalid_hex"
            elif not _is_hex(sid, 16):
                errors["session_id"] = "invalid_hex"
            else:
                address = user_input["address"].upper().strip()
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input.get("name", self._discovered_name),
                    data={
                        "address":     address,
                        "name":        user_input.get("name", self._discovered_name),
                        "ltk":         ltk,
                        "session_key": sk,
                        "session_id":  sid,
                        "user_id":     user_input.get("user_id", 0),
                        "action":      user_input.get("action", 0),
                    },
                )

        schema = vol.Schema({
            vol.Required("address", default=self._discovered_address): str,
            vol.Optional("name",        default=self._discovered_name):              str,
            vol.Required("ltk",         default=self._parsed.get("ltk", "")):         str,
            vol.Required("session_key", default=self._parsed.get("session_key", "")): str,
            vol.Required("session_id",  default=self._parsed.get("session_id", "")):  str,
            vol.Optional("user_id",     default=0):                                   int,
            vol.Optional("action",      default=0):                                   int,
        })
        return self.async_show_form(
            step_id="device",
            data_schema=schema,
            errors=errors,
        )
