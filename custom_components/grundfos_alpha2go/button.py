"""Bouton d'appairage BLE de la pompe."""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import Alpha2GoCoordinator, build_device_info
from .const import CONF_ADDRESS
from .genibus import GenibusError


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([Alpha2GoPairButton(entry.runtime_data, entry)])


class Alpha2GoPairButton(ButtonEntity):
    """Appairer : appuyer d'abord sur le bouton de connectivité de la pompe."""

    _attr_has_entity_name = True
    _attr_name = "Appairer"
    _attr_icon = "mdi:bluetooth-connect"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: Alpha2GoCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.data[CONF_ADDRESS]}_pair"
        self._attr_device_info = build_device_info(entry)

    async def async_press(self) -> None:
        client = self._coordinator.client
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, client.address, connectable=True
        )
        if ble_device is None:
            raise HomeAssistantError("Pompe non visible par le Bluetooth de Home Assistant")
        try:
            await client.async_pair(ble_device)
        except GenibusError as err:
            raise HomeAssistantError(f"Échec de l'appairage : {err}") from err
        await self._coordinator.async_request_refresh()
