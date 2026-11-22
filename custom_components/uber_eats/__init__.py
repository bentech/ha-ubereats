"""Uber Eats order tracking integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .api import UberEatsApi
from .const import CONF_COOKIE, CONF_LOCALE, CONF_ORDER_UUID, CONF_TIMEZONE
from .coordinator import UberEatsCoordinator

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.DEVICE_TRACKER,
    Platform.BUTTON,
]
type UberEatsConfigEntry = ConfigEntry[UberEatsCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: UberEatsConfigEntry) -> bool:
    """Set up Uber Eats from a config entry."""
    api = UberEatsApi(
        async_get_clientsession(hass),
        cookie=entry.data[CONF_COOKIE],
        order_uuid=entry.data.get(CONF_ORDER_UUID),
        timezone=entry.data[CONF_TIMEZONE],
        locale=entry.data[CONF_LOCALE],
    )
    timezone = await dt_util.async_get_time_zone(entry.data[CONF_TIMEZONE])
    coordinator = UberEatsCoordinator(hass, entry, api, timezone or dt_util.UTC)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: UberEatsConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
