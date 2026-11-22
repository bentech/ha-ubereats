"""Order activity and arrival indicators."""

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Order
from .coordinator import UberEatsCoordinator


@dataclass(frozen=True, kw_only=True)
class UberEatsBinarySensorDescription(BinarySensorEntityDescription):
    """Describe an order condition."""

    is_on: Callable[[Order], bool]


SENSORS = (
    UberEatsBinarySensorDescription(
        key="order_active",
        name="Order active",
        icon="mdi:food-takeout-box",
        is_on=lambda order: order.active,
    ),
    UberEatsBinarySensorDescription(
        key="courier_arriving",
        name="Courier arriving",
        icon="mdi:map-marker-check",
        is_on=lambda order: order.active and order.status == "arriving",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[UberEatsCoordinator],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add both order conditions."""
    async_add_entities(
        UberEatsBinarySensor(entry.runtime_data, description) for description in SENSORS
    )


class UberEatsBinarySensor(CoordinatorEntity[UberEatsCoordinator], BinarySensorEntity):
    """Expose one order condition as an on/off entity."""

    _attr_has_entity_name = True
    entity_description: UberEatsBinarySensorDescription

    def __init__(
        self,
        coordinator: UberEatsCoordinator,
        description: UberEatsBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entity_key}_{description.key}"
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool:
        """Return whether this order condition applies."""
        return self.entity_description.is_on(self.coordinator.data)
