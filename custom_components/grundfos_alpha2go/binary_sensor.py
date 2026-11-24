"""Capteurs binaires : pompe joignable (passif) et pompe en marche (GENIbus)."""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import Alpha2GoCoordinator, build_device_info
from .const import CONF_ADDRESS


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: Alpha2GoCoordinator = entry.runtime_data
    async_add_entities(
        [Alpha2GoReachable(entry), Alpha2GoRunning(coordinator, entry)]
    )


class Alpha2GoReachable(BinarySensorEntity):
    """Joignable = annonces BLE reçues récemment. Aucune connexion ouverte."""

    _attr_has_entity_name = True
    _attr_name = "Joignable"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._address: str = entry.data[CONF_ADDRESS].upper()
        self._attr_unique_id = f"{entry.data[CONF_ADDRESS]}_reachable"
        self._attr_device_info = build_device_info(entry)

    async def async_added_to_hass(self) -> None:
        self._attr_is_on = bluetooth.async_address_present(
            self.hass, self._address, connectable=False
        )
        self.async_on_remove(
            bluetooth.async_register_callback(
                self.hass,
                self._on_advertisement,
                bluetooth.BluetoothCallbackMatcher(address=self._address, connectable=False),
                bluetooth.BluetoothScanningMode.PASSIVE,
            )
        )
        self.async_on_remove(
            bluetooth.async_track_unavailable(
                self.hass, self._on_unavailable, self._address, connectable=False
            )
        )

    @callback
    def _on_advertisement(
        self,
        _info: bluetooth.BluetoothServiceInfoBleak,
        _change: bluetooth.BluetoothChange,
    ) -> None:
        if not self._attr_is_on:  # écriture d'état uniquement sur changement
            self._attr_is_on = True
            self.async_write_ha_state()

    @callback
    def _on_unavailable(self, _info: bluetooth.BluetoothServiceInfoBleak) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()


class Alpha2GoRunning(CoordinatorEntity[Alpha2GoCoordinator], BinarySensorEntity):
    """En marche = puissance ou vitesse au-dessus du seuil."""

    _attr_has_entity_name = True
    _attr_name = "En marche"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator: Alpha2GoCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data[CONF_ADDRESS]}_running"
        self._attr_device_info = build_device_info(entry)

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.data is not None
            and self.coordinator.data.running is not None
        )

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.running if self.coordinator.data else None
