"""Sensor platform for Grundfos Alpha2 Go v1.2.0"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import Alpha2GoCoordinator
from .const import CONF_ADDRESS, CONF_NAME, DOMAIN
from .genibus import PumpData


@dataclass(frozen=True)
class Alpha2GoSensorDescription(SensorEntityDescription):
    value_fn: Callable[[PumpData], str | float | int | None] = field(
        default=lambda d: None
    )


SENSOR_DESCRIPTIONS: tuple[Alpha2GoSensorDescription, ...] = (
    Alpha2GoSensorDescription(
        key="connected",
        name="Statut",
        icon="mdi:bluetooth-connect",
        value_fn=lambda d: "Connecté" if d.connected else "Déconnecté",
    ),
    Alpha2GoSensorDescription(
        key="device_name",
        name="Nom",
        icon="mdi:tag",
        value_fn=lambda d: d.device_name,
    ),
    Alpha2GoSensorDescription(
        key="model",
        name="Modèle",
        icon="mdi:water-pump",
        value_fn=lambda d: d.model,
    ),
    Alpha2GoSensorDescription(
        key="firmware",
        name="Firmware",
        icon="mdi:chip",
        value_fn=lambda d: d.firmware,
    ),
    Alpha2GoSensorDescription(
        key="notifications",
        name="Activité (notifications)",
        icon="mdi:wave",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: d.notifications,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: Alpha2GoCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        Alpha2GoSensorEntity(coordinator, entry, desc)
        for desc in SENSOR_DESCRIPTIONS
    )


class Alpha2GoSensorEntity(CoordinatorEntity[Alpha2GoCoordinator], SensorEntity):
    entity_description: Alpha2GoSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: Alpha2GoCoordinator,
        entry: ConfigEntry,
        description: Alpha2GoSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.data[CONF_ADDRESS]}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data[CONF_ADDRESS])},
            name=entry.data.get(CONF_NAME, "Alpha2 Go"),
            manufacturer="Grundfos",
            model="Alpha2 Go",
        )

    @property
    def native_value(self) -> str | float | int | None:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
