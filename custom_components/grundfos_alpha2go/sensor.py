"""Sensor platform for Grundfos Alpha2 Go - v1.0.2"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import Alpha2GoCoordinator
from .const import CONF_ADDRESS, CONF_NAME, DOMAIN
from .genibus import PumpData

UNIT_FLOW = "m³/h"
UNIT_HEAD = "m"
UNIT_RPM  = "rpm"


@dataclass(frozen=True)
class Alpha2GoSensorDescription(SensorEntityDescription):
    value_fn: Callable[[PumpData], float | int | None] = field(default=lambda d: None)


SENSOR_DESCRIPTIONS: tuple[Alpha2GoSensorDescription, ...] = (
    Alpha2GoSensorDescription(
        key="flow",
        name="Débit",
        native_unit_of_measurement=UNIT_FLOW,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:water-pump",
        value_fn=lambda d: d.flow,
    ),
    Alpha2GoSensorDescription(
        key="head",
        name="Hauteur manométrique",
        native_unit_of_measurement=UNIT_HEAD,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:arrow-up-bold",
        value_fn=lambda d: d.head,
    ),
    Alpha2GoSensorDescription(
        key="speed",
        name="Vitesse",
        native_unit_of_measurement=UNIT_RPM,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:rotate-right",
        value_fn=lambda d: d.speed,
    ),
    Alpha2GoSensorDescription(
        key="power",
        name="Puissance",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:lightning-bolt",
        value_fn=lambda d: d.power,
    ),
    Alpha2GoSensorDescription(
        key="voltage",
        name="Tension",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:sine-wave",
        value_fn=lambda d: d.voltage,
    ),
    Alpha2GoSensorDescription(
        key="current",
        name="Intensité",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:current-ac",
        value_fn=lambda d: d.current,
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
    def native_value(self) -> float | int | None:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
