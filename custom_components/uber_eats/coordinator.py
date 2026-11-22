"""Data update coordinator for Uber Eats."""

import logging
from dataclasses import replace
from datetime import UTC, datetime, tzinfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    Order,
    UberEatsApi,
    UberEatsApiError,
    UberEatsAuthError,
    UberEatsOrderNotActive,
)
from .const import ACTIVE_ORDERS_ID, CONF_ORDER_UUID, DOMAIN, UPDATE_INTERVAL
from .eta import parse_eta

_LOGGER = logging.getLogger(__name__)
TRANSIT_STAGES = {"ready_for_pickup", "en_route", "stop_before_delivery", "arriving"}


class UberEatsCoordinator(DataUpdateCoordinator[Order]):
    """Poll for the current Uber Eats order."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: UberEatsApi,
        timezone: tzinfo,
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.api = api
        self.timezone = timezone
        self.last_outcome: str | None = None
        self._timing: dict[str, str] = {}
        self._timing_store = Store[dict[str, str]](
            hass, 1, f"{DOMAIN}.{entry.entry_id}.timing"
        )
        order_uuid = entry.data.get(CONF_ORDER_UUID)
        self.entity_key = order_uuid or ACTIVE_ORDERS_ID
        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, self.entity_key)},
            name=f"Uber Eats order {order_uuid[:8]}" if order_uuid else "Uber Eats",
            manufacturer="Uber Eats",
        )

    async def _async_setup(self) -> None:
        """Restore the timings for the last tracked order."""
        self._timing = await self._timing_store.async_load() or {}

    @property
    def original_latest_eta(self) -> str | None:
        """Return the first latest ETA reported for this order."""
        return self._timing.get("original_latest_eta")

    @property
    def order_placed_at(self) -> datetime | None:
        """Return the first time this active order was observed."""
        placed = self._timing.get("order_first_seen")
        return datetime.fromisoformat(placed) if placed else None

    @property
    def transit_started_at(self) -> str | None:
        """Return when the restaurant-ready or pickup stage was first seen."""
        return self._timing.get("transit_started_at")

    @property
    def transit_start_source(self) -> str | None:
        """Return which stage started the timer."""
        return self._timing.get("transit_start_source")

    @property
    def transit_minutes(self) -> float | None:
        """Return elapsed minutes, frozen at the end of tracking."""
        if started := self.transit_started_at:
            ended = self._timing.get("ended_at")
            end = datetime.fromisoformat(ended) if ended else datetime.now(UTC)
            return round(
                max(0, (end - datetime.fromisoformat(started)).total_seconds()) / 60, 1
            )
        return None

    async def _async_record_timing(self, order: Order, now: datetime) -> None:
        """Keep the first ETA and start time for the same order across reloads."""
        timing = self._timing.copy()
        if order.uuid is not None and timing.get("order_id") != order.uuid:
            timing = {"order_id": order.uuid}
        if order.active:
            timing.setdefault("order_first_seen", now.isoformat())
        if order.eta_latest is not None:
            timing.setdefault("original_latest_eta", order.eta_latest.isoformat())
        if order.active:
            timing.pop("ended_at", None)
            if order.status in TRANSIT_STAGES and "transit_started_at" not in timing:
                timing["transit_started_at"] = now.isoformat()
                timing["transit_start_source"] = (
                    "restaurant_ready"
                    if order.status == "ready_for_pickup"
                    else "courier_pickup"
                )
        elif timing:
            timing.setdefault("ended_at", now.isoformat())

        if timing != self._timing:
            await self._timing_store.async_save(timing)
            self._timing = timing

    async def _async_update_data(self) -> Order:
        try:
            order = await self.api.async_get_order(
                self.data.uuid if self.data else None
            )
        except UberEatsAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except UberEatsOrderNotActive as err:
            if self.data is None or self.data.uuid is None:
                if self.entity_key != ACTIVE_ORDERS_ID:
                    raise UpdateFailed(str(err)) from err
                order = Order(uuid=None, status="no_active_order")
            elif self.data.outcome is not None:
                order = self.data
            else:
                order = Order(
                    uuid=self.data.uuid,
                    status="tracking_ended",
                    restaurant=self.data.restaurant,
                )
        except UberEatsApiError as err:
            raise UpdateFailed(str(err)) from err

        if order.outcome is not None:
            self.last_outcome = order.outcome
        elif self.data and self.data.active and self.data.uuid != order.uuid:
            self.last_outcome = "unconfirmed"

        now = datetime.now(UTC)
        if order.active and order.eta:
            earliest, latest = parse_eta(order.eta, now, self.timezone)
            order = replace(order, eta_earliest=earliest, eta_latest=latest)
        await self._async_record_timing(order, now)
        return order
