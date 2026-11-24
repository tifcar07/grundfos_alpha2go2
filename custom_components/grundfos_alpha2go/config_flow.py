"""Config flow Grundfos Alpha2 Go."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import (
    CONF_ADDRESS,
    CONF_NAME,
    DEFAULT_NAME,
    DEVICE_NAME_PREFIX,
    DOMAIN,
    GRUNDFOS_MANUFACTURER_ID,
)
from .genibus import GENI_SERVICE_UUID

MANUAL = "manual"
MAC_RE = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")


def _is_pump(info: BluetoothServiceInfoBleak) -> bool:
    return (
        GRUNDFOS_MANUFACTURER_ID in info.manufacturer_data
        or GENI_SERVICE_UUID in [s.lower() for s in info.service_uuids]
        or bool(info.name and info.name.startswith(DEVICE_NAME_PREFIX))
    )


class Alpha2GoConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovered: dict[str, str] = {}
        self._address = ""
        self._name = DEFAULT_NAME

    async def _create(self, address: str, name: str) -> ConfigFlowResult:
        await self.async_set_unique_id(address)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=name, data={CONF_ADDRESS: address, CONF_NAME: name}
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            if user_input[CONF_ADDRESS] == MANUAL:
                return await self.async_step_manual()
            return await self._create(
                user_input[CONF_ADDRESS], user_input.get(CONF_NAME) or DEFAULT_NAME
            )

        current = self._async_current_ids()
        self._discovered = {
            info.address.upper(): f"{info.name or DEFAULT_NAME} ({info.address})"
            for info in async_discovered_service_info(self.hass)
            if _is_pump(info) and info.address.upper() not in current
        }
        if not self._discovered:
            return await self.async_step_manual()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {**self._discovered, MANUAL: "Saisir manuellement"}
                    ),
                    vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
                }
            ),
        )

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper()
            if MAC_RE.match(address):
                return await self._create(address, user_input.get(CONF_NAME) or DEFAULT_NAME)
            errors[CONF_ADDRESS] = "invalid_address"
        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): str,
                    vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
                }
            ),
            errors=errors,
        )

    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak) -> ConfigFlowResult:
        self._address = discovery_info.address.upper()
        self._name = discovery_info.name or DEFAULT_NAME
        await self.async_set_unique_id(self._address)
        self._abort_if_unique_id_configured()
        self.context["title_placeholders"] = {"name": self._name, "address": self._address}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return await self._create(self._address, self._name)
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": self._name, "address": self._address},
        )
