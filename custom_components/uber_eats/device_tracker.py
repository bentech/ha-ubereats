"""The courier's position while the order is active."""

from homeassistant.components.device_tracker import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import UberEatsCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[UberEatsCoordinator],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Expose the courier on Home Assistant maps."""
    async_add_entities([UberEatsCourierTracker(entry.runtime_data)])


class UberEatsCourierTracker(CoordinatorEntity[UberEatsCoordinator], TrackerEntity):
    """A map pin that is available only with a current, valid location."""

    _attr_has_entity_name = True
    _attr_name = "Courier"
    _attr_icon = "mdi:bike-fast"

    def __init__(self, coordinator: UberEatsCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entity_key}_courier"
        self._attr_device_info = coordinator.device_info

    @property
    def available(self) -> bool:
        """Hide the pin when a refresh fails or order tracking ends."""
        order = self.coordinator.data
        return (
            super().available
            and order.active
            and order.courier_latitude is not None
            and -90 <= order.courier_latitude <= 90
            and order.courier_longitude is not None
            and -180 <= order.courier_longitude <= 180
        )

    @property
    def latitude(self) -> float | None:
        """Return the courier's latest valid latitude."""
        return self.coordinator.data.courier_latitude if self.available else None

    @property
    def longitude(self) -> float | None:
        """Return the courier's latest valid longitude."""
        return self.coordinator.data.courier_longitude if self.available else None
