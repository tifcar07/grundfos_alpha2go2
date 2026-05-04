"""Config flow for Grundfos Alpha2 Go integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from bleak import BleakScanner

from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_ADDRESS, CONF_NAME, DEFAULT_NAME, DEVICE_NAME_PREFIX, DOMAIN
from .genibus import GENI_SERVICE_UUID

_LOGGER = logging.getLogger(__name__)

# Volume schema when the user types the address manually
MANUAL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ADDRESS): str,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
    }
)


class Alpha2GoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Grundfos Alpha2 Go."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered: dict[str, str] = {}   # address → name

    # ── step: user ─────────────────────────────────────────────────────────────

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """
        First step: show any auto-discovered pumps (or fall back to manual entry).
        """
        errors: dict[str, str] = {}

        # Collect already-discovered BLE devices that look like Grundfos pumps
        self._discovered = {
            info.address: info.name or info.address
            for info in async_discovered_service_info(self.hass)
            if (
                GENI_SERVICE_UUID.lower() in [s.lower() for s in info.service_uuids]
                or (info.name and info.name.startswith(DEVICE_NAME_PREFIX))
            )
        }

        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper()
            name    = user_input.get(CONF_NAME, DEFAULT_NAME)

            # Prevent duplicate entries
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=name,
                data={CONF_ADDRESS: address, CONF_NAME: name},
            )

        # Build a selector: discovered devices + manual option
        device_options: dict[str, str] = {**self._discovered, "manual": "➕ Saisir manuellement"}

        if self._discovered:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_ADDRESS): vol.In(device_options),
                        vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
                    }
                ),
                errors=errors,
                description_placeholders={
                    "count": str(len(self._discovered)),
                },
            )

        # No auto-discovery – show manual form directly
        return self.async_show_form(
            step_id="user",
            data_schema=MANUAL_SCHEMA,
            errors=errors,
        )

    # ── step: bluetooth (passive discovery via HA bluetooth integration) ───────

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """
        Called automatically when HA's Bluetooth scanner finds a matching device.
        Uses the manufacturer_id / service UUID declared in manifest.json.
        """
        address = discovery_info.address
        name    = discovery_info.name or DEFAULT_NAME

        await self.async_set_unique_id(address)
        self._abort_if_unique_id_configured()

        self.context["title_placeholders"] = {"name": name, "address": address}

        # Store for the confirmation step
        self._discovered_address = address
        self._discovered_name    = name

        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Let the user confirm the auto-discovered pump."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovered_name,
                data={
                    CONF_ADDRESS: self._discovered_address,
                    CONF_NAME:    self._discovered_name,
                },
            )

        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={
                "name":    self._discovered_name,
                "address": self._discovered_address,
            },
        )
