"""Manual refresh button for Uber Eats tracking."""

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import UberEatsCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[UberEatsCoordinator],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a button to refresh the active order."""
    async_add_entities([UberEatsRefreshButton(entry.runtime_data)])


class UberEatsRefreshButton(ButtonEntity):
    """Request an immediate coordinator update."""

    _attr_has_entity_name = True
    _attr_name = "Refresh"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: UberEatsCoordinator) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entity_key}_refresh"
        self._attr_device_info = coordinator.device_info

    async def async_press(self) -> None:
        """Refresh the order now."""
        await self.coordinator.async_request_refresh()
