"""Sensor platform for Uber Eats."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import UberEatsCoordinator


@dataclass(frozen=True, kw_only=True)
class UberEatsSensorDescription(SensorEntityDescription):
    """Describe a sensor backed by a normalized order field."""

    value: Callable[[UberEatsCoordinator], str | datetime | None]


SENSORS = (
    UberEatsSensorDescription(
        key="restaurant",
        name="Restaurant",
        icon="mdi:store",
        value=lambda coordinator: coordinator.data.restaurant,
    ),
    UberEatsSensorDescription(
        key="earliest_eta",
        name="Earliest ETA",
        device_class=SensorDeviceClass.TIMESTAMP,
        value=lambda coordinator: coordinator.data.eta_earliest,
    ),
    UberEatsSensorDescription(
        key="latest_eta",
        name="Latest ETA",
        device_class=SensorDeviceClass.TIMESTAMP,
        value=lambda coordinator: coordinator.data.eta_latest,
    ),
    UberEatsSensorDescription(
        key="order_placed",
        name="Order placed",
        device_class=SensorDeviceClass.TIMESTAMP,
        value=lambda coordinator: coordinator.order_placed_at,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[UberEatsCoordinator],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the order sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            UberEatsOrderSensor(coordinator),
            *(UberEatsFieldSensor(coordinator, description) for description in SENSORS),
            UberEatsOutcomeSensor(coordinator),
            UberEatsTransitSensor(coordinator),
        ]
    )


class UberEatsOrderSensor(CoordinatorEntity[UberEatsCoordinator], SensorEntity):
    """Represent the current state of an Uber Eats order."""

    _attr_has_entity_name = True
    _attr_name = "Status"
    _attr_icon = "mdi:food-takeout-box"

    def __init__(self, coordinator: UberEatsCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entity_key}_status"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> str:
        """Return the order status."""
        return self.coordinator.data.status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return useful normalized order details."""
        order = self.coordinator.data
        return {
            "order_uuid": order.uuid,
            "restaurant": order.restaurant,
            "estimated_delivery_time": order.eta,
            "courier_name": order.courier_name,
            "courier_latitude": order.courier_latitude,
            "courier_longitude": order.courier_longitude,
            "status_detail": order.status_detail,
            "progress": order.progress,
            "progress_segments": order.progress_segments,
            "stops_before_delivery": order.stops_before_delivery,
        }


class UberEatsFieldSensor(CoordinatorEntity[UberEatsCoordinator], SensorEntity):
    """Expose one order field as a sensor."""

    _attr_has_entity_name = True
    entity_description: UberEatsSensorDescription

    def __init__(
        self, coordinator: UberEatsCoordinator, description: UberEatsSensorDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entity_key}_{description.key}"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> str | datetime | None:
        """Return the selected order field."""
        return self.entity_description.value(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, str | None] | None:
        """Expose the original latest time beside the current estimate."""
        if self.entity_description.key == "latest_eta":
            return {"original_latest_eta": self.coordinator.original_latest_eta}
        if (
            self.entity_description.key == "order_placed"
            and self.native_value is not None
        ):
            return {"time_source": "first_seen"}
        return None


class UberEatsTransitSensor(CoordinatorEntity[UberEatsCoordinator], SensorEntity):
    """Time since the first restaurant-ready or collected stage."""

    _attr_has_entity_name = True
    _attr_name = "Time in transit"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: UberEatsCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entity_key}_time_in_transit"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> float | None:
        """Return the elapsed minutes."""
        return self.coordinator.transit_minutes

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Identify the timestamp and evidence used to start the timer."""
        return {
            "started_at": self.coordinator.transit_started_at,
            "start_source": self.coordinator.transit_start_source,
        }


class UberEatsOutcomeSensor(CoordinatorEntity[UberEatsCoordinator], RestoreSensor):
    """Keep the most recently observed order outcome."""

    _attr_has_entity_name = True
    _attr_name = "Last order outcome"
    _attr_icon = "mdi:clipboard-check-outline"
    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(self, coordinator: UberEatsCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entity_key}_last_order_outcome"
        self._attr_device_info = coordinator.device_info
        self._attr_options = ["delivered", "cancelled", "unconfirmed"]
        self._restored_outcome: str | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the outcome from before a Home Assistant restart."""
        if (last := await self.async_get_last_sensor_data()) and (
            last.native_value in self._attr_options
        ):
            self._restored_outcome = last.native_value
        await super().async_added_to_hass()

    @property
    def available(self) -> bool:
        """Keep an observed outcome readable while updates are unavailable."""
        return self.native_value is not None or super().available

    @property
    def native_value(self) -> str | None:
        """Return the last terminal result."""
        return self.coordinator.last_outcome or self._restored_outcome
