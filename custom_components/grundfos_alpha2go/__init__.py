"""Intégration Grundfos Alpha2 Go (BLE / GENIbus) pour Home Assistant."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_ADDRESS,
    CONF_NAME,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LEGACY_SENSOR_KEYS,
)
from .genibus import Alpha2GoClient, GenibusError, PumpData

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR]


def build_device_info(entry: ConfigEntry) -> DeviceInfo:
    address: str = entry.data[CONF_ADDRESS]
    return DeviceInfo(
        identifiers={(DOMAIN, address)},
        connections={(CONNECTION_BLUETOOTH, address.upper())},
        name=entry.data.get(CONF_NAME) or entry.title or DEFAULT_NAME,
        manufacturer="Grundfos",
        model="Alpha2 Go",
    )


class Alpha2GoCoordinator(DataUpdateCoordinator[PumpData]):
    """Lecture GENIbus périodique (connexion courte à chaque cycle)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: Alpha2GoClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{client.address}",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.client = client

    async def _async_update_data(self) -> PumpData:
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self.client.address, connectable=True
        )
        if ble_device is None:
            raise UpdateFailed("pompe non visible par le Bluetooth de Home Assistant")
        try:
            return await self.client.async_read(ble_device)
        except GenibusError as err:
            raise UpdateFailed(str(err)) from err


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    address: str = entry.data[CONF_ADDRESS]

    # Nettoyage des entités de la v1.x (Statut, Nom, Modèle, Firmware, Notifications)
    registry = er.async_get(hass)
    for key in LEGACY_SENSOR_KEYS:
        if entity_id := registry.async_get_entity_id("sensor", DOMAIN, f"{address}_{key}"):
            registry.async_remove(entity_id)

    coordinator = Alpha2GoCoordinator(hass, entry, Alpha2GoClient(address))
    # Pas de ConfigEntryNotReady : le capteur "Joignable" doit fonctionner
    # même si la lecture GENIbus échoue au démarrage.
    await coordinator.async_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
