"""Sensor platform for Grundfos Alpha2 Go."""

from __future__ import annotations

from dataclasses import dataclass
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
    UnitOfSpeed,
    REVOLUTIONS_PER_MINUTE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import Alpha2GoCoordinator
from .const import CONF_ADDRESS, CONF_NAME, DOMAIN
from .genibus import PumpData

# Unit not yet in HA constants for older versions – define locally as fallback
try:
    from homeassistant.const import UnitOfVolumeFlowRate
    UNIT_FLOW = UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR
except ImportError:
    UNIT_FLOW = "m³/h"

UNIT_HEAD = "m"   # metres of head (pressure height)


@dataclass(frozen=True)
class Alpha2GoSensorDescription(SensorEntityDescription):
    """Describes a single Alpha2 Go sensor."""
    value_fn: Callable[[PumpData], float | int | None] = lambda d: None


SENSOR_DESCRIPTIONS: tuple[Alpha2GoSensorDescription, ...] = (
    Alpha2GoSensorDescription(
        key="flow",
        name="Débit",
        native_unit_of_measurement=UNIT_FLOW,
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:water-pump",
        value_fn=lambda d: d.flow,
    ),
    Alpha2GoSensorDescription(
        key="head",
        name="Hauteur manométrique",
        native_unit_of_measurement=UNIT_HEAD,
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:arrow-up-bold",
        value_fn=lambda d: d.head,
    ),
    Alpha2GoSensorDescription(
        key="speed",
        name="Vitesse",
        native_unit_of_measurement=REVOLUTIONS_PER_MINUTE,
        device_class=None,
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
    """Set up Alpha2 Go sensors from a config entry."""
    coordinator: Alpha2GoCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        Alpha2GoSensorEntity(coordinator, entry, description)
        for description in SENSOR_DESCRIPTIONS
    )


class Alpha2GoSensorEntity(CoordinatorEntity[Alpha2GoCoordinator], SensorEntity):
    """A single sensor entity backed by the Alpha2Go coordinator."""

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
        self._entry = entry
        self._attr_unique_id = f"{entry.data[CONF_ADDRESS]}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data[CONF_ADDRESS])},
            name=entry.data.get(CONF_NAME, "Alpha2 Go"),
            manufacturer="Grundfos",
            model="Alpha2 Go",
        )

    @property
    def native_value(self) -> float | int | None:
        """Return current sensor value from the coordinator's data."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
