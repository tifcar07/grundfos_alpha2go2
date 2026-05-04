"""Grundfos Alpha2 Go BLE integration for Home Assistant."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_ADDRESS, DEFAULT_SCAN_INTERVAL, DOMAIN
from .genibus import Alpha2GoClient, PumpData

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Grundfos Alpha2 Go from a config entry."""

    address: str = entry.data[CONF_ADDRESS]
    client = Alpha2GoClient(address)

    coordinator = Alpha2GoCoordinator(hass, client, entry.title)

    # Perform first refresh – raises ConfigEntryNotReady if the pump is unreachable
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as exc:
        raise ConfigEntryNotReady(
            f"Cannot reach Alpha2 Go at {address}: {exc}"
        ) from exc

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator: Alpha2GoCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.client.disconnect()
    return unload_ok


# ── Coordinator ────────────────────────────────────────────────────────────────

class Alpha2GoCoordinator(DataUpdateCoordinator[PumpData]):
    """Coordinator that polls the pump on a schedule."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: Alpha2GoClient,
        name: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=name,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.client = client

    async def _async_update_data(self) -> PumpData:
        data = await self.client.poll()
        if data is None:
            raise UpdateFailed("No data received from Alpha2 Go pump")
        return data
