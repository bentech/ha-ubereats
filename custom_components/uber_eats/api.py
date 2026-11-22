"""Small client for Uber Eats' web order endpoint.

The endpoint is used by the public Uber Eats web application and is not a
documented public API. Keeping it isolated here makes future endpoint changes
easier to accommodate.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from aiohttp import ClientError, ClientResponseError, ClientSession

API_URL = "https://www.ubereats.com/_p/api/getActiveOrdersV1"


class UberEatsApiError(Exception):
    """Base exception raised by the client."""


class UberEatsAuthError(UberEatsApiError):
    """Raised when the browser session is no longer accepted."""


class UberEatsOrderNotActive(UberEatsApiError):
    """Raised when a successful response no longer includes the order."""


TRACKING_STATUSES = (
    (
        "order_received",
        ("order received", "confirming your order", "placing your order"),
    ),
    ("preparing", ("preparing", "your order is being prepared")),
    ("ready_for_pickup", ("ready for pickup", "your order is ready for pickup")),
    ("courier_to_store", ("heading to store", "heading to the store")),
    ("shopping", ("shopping in progress",)),
    ("awaiting_pickup", ("waiting for pickup", "picking up", "picking your order up")),
    ("en_route", ("heading your way", "on the way", "on their way")),
    ("arriving", ("almost here", "arriving now")),
    ("delivered", ("delivered", "order delivered", "your order was delivered")),
    (
        "cancelled",
        (
            "cancelled",
            "canceled",
            "order cancelled",
            "order canceled",
            "your order was cancelled",
            "your order was canceled",
        ),
    ),
)

ORDER_OUTCOMES = {
    "delivered": "delivered",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "tracking_ended": "unconfirmed",
}

_STOP_COUNTS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
_STOPS_ALONG_THE_WAY = re.compile(
    r"\b(one|two|three|four|five|[1-9]\d?) stops? along the way\b", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class Order:
    """Normalized order details exposed to Home Assistant."""

    uuid: str | None
    status: str
    restaurant: str | None = None
    eta: str | None = None
    courier_name: str | None = None
    courier_latitude: float | None = None
    courier_longitude: float | None = None
    raw: dict[str, Any] | None = None
    status_detail: str | None = None
    progress: int | None = None
    progress_segments: int | None = None
    eta_earliest: datetime | None = None
    eta_latest: datetime | None = None
    stops_before_delivery: int | None = None

    @property
    def outcome(self) -> str | None:
        """Return the terminal outcome when active tracking has ended."""
        return ORDER_OUTCOMES.get(self.status)

    @property
    def active(self) -> bool:
        """Whether the current order is still being tracked."""
        return self.uuid is not None and self.outcome is None


class UberEatsApi:
    """Access the Uber Eats web endpoint using an existing browser cookie."""

    def __init__(
        self,
        session: ClientSession,
        *,
        cookie: str,
        order_uuid: str | None = None,
        timezone: str,
        locale: str,
    ) -> None:
        self._session = session
        self._cookie = cookie
        self._order_uuid = order_uuid
        self._timezone = timezone
        self._locale = locale.lower()

    async def async_get_order(self, preferred_uuid: str | None = None) -> Order:
        """Fetch the configured order or find the active order for the account."""
        orders_page = f"https://www.ubereats.com/{self._locale}/orders"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Cookie": self._cookie,
            "Origin": "https://www.ubereats.com",
            "Referer": f"{orders_page}/{self._order_uuid}"
            if self._order_uuid
            else orders_page,
            "User-Agent": "Mozilla/5.0 HomeAssistant-UberEats/1.0",
            "x-csrf-token": "x",
        }
        payload = {
            "orderUuid": self._order_uuid,
            "timezone": self._timezone,
            "showAppUpsellIllustration": True,
            "isDirectTracking": False,
        }
        try:
            async with self._session.post(
                API_URL,
                params={"localeCode": self._locale},
                json=payload,
                headers=headers,
                allow_redirects=False,
                timeout=20,
            ) as response:
                if response.status in (401, 403):
                    raise UberEatsAuthError("Uber Eats rejected the browser session")
                if 300 <= response.status < 400:
                    raise UberEatsApiError("Uber Eats redirected the tracking request")
                response.raise_for_status()
                body = await response.json(content_type=None)
        except UberEatsAuthError:
            raise
        except (ClientError, ClientResponseError, TimeoutError, ValueError) as err:
            raise UberEatsApiError(f"Unable to fetch order: {err}") from err

        orders = _first(body, "data.orders") if isinstance(body, dict) else None
        if self._order_uuid is None:
            if not isinstance(orders, list) or body.get("status") != "success":
                raise UberEatsApiError("Uber Eats did not return an active orders list")
            if not orders:
                raise UberEatsOrderNotActive(
                    "The order was not present in the response"
                )
            if preferred_uuid and (current := _find_order(body, preferred_uuid)):
                return _normalize_order(current, preferred_uuid)
            for order in orders:
                if isinstance(order, dict):
                    identifier = _first(order, "uuid", "orderUuid", "orderUUID")
                    if isinstance(identifier, str):
                        return _normalize_order(order, identifier)
            raise UberEatsApiError("Uber Eats did not identify an active order")

        order_data = _find_order(body, self._order_uuid)
        if order_data is None:
            if (
                isinstance(body, dict)
                and body.get("status") == "success"
                and isinstance(orders, list)
            ):
                raise UberEatsOrderNotActive(
                    "The order was not present in the response"
                )
            raise UberEatsApiError("The order was not present in the response")
        return _normalize_order(order_data, self._order_uuid)


def _find_order(value: Any, order_uuid: str) -> dict[str, Any] | None:
    """Find the requested order without relying on a single response layout."""
    if isinstance(value, dict) and isinstance(
        orders := _first(value, "data.orders"), list
    ):
        return next(
            (
                order
                for order in orders
                if isinstance(order, dict) and order_uuid in _identifiers(order)
            ),
            None,
        )

    unidentified = []
    found_other_order = False
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, list):
            stack.extend(current)
        elif isinstance(current, dict):
            identifiers = _identifiers(current)
            if order_uuid in identifiers:
                return current
            if any(key in current for key in ("orderStatus", "orderState")):
                if any(identifiers):
                    found_other_order = True
                    continue
                unidentified.append(current)
            stack.extend(current.values())
    if len(unidentified) == 1 and not found_other_order:
        return unidentified[0]
    return None


def _identifiers(order: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(order.get(key) for key in ("uuid", "orderUuid", "orderUUID"))


def _first(value: dict[str, Any], *paths: str) -> Any:
    for path in paths:
        current: Any = value
        for part in path.split("."):
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(part)
        if current not in (None, ""):
            return current
    return None


def _as_float(value: Any) -> float | None:
    try:
        coordinate = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return coordinate if math.isfinite(coordinate) else None


def _card_items(data: dict[str, Any], cards_key: str, item_key: str):
    """Yield the objects in the named lists on tracking cards."""
    cards = data.get(cards_key)
    if isinstance(cards, list):
        for card in cards:
            items = card.get(item_key) if isinstance(card, dict) else None
            if isinstance(items, list):
                yield from (item for item in items if isinstance(item, dict))


def _tracking_card(data: dict[str, Any]) -> dict[str, Any]:
    """Find the status card used by the Orders page."""
    cards = data.get("feedCards")
    if isinstance(cards, list):
        for card in cards:
            if isinstance(card, dict) and isinstance(
                status := card.get("status"), dict
            ):
                label = _first(status, "titleSummary.summary.text")
                if isinstance(label, str) and label.strip():
                    return status
    return {}


def _normalize_order(data: dict[str, Any], order_uuid: str) -> Order:
    status = _first(
        data, "status", "orderStatus", "orderState", "state", "feedCard.status"
    )
    phase = _first(data, "orderInfo.orderPhase")
    tracking_card = _tracking_card(data)
    status_detail = _first(tracking_card, "titleSummary.summary.text") or _first(
        data, "activeOrderStatus.titleSummary.summary.text"
    )
    if not isinstance(status_detail, str):
        status_detail = None
    if isinstance(phase, str) and phase.lower() in ORDER_OUTCOMES:
        status = phase
    elif not isinstance(status, str):
        label = (status_detail or "").strip().casefold()
        status = next(
            (
                state
                for state, prefixes in TRACKING_STATUSES
                if label.startswith(prefixes)
            ),
            phase if isinstance(phase, str) else "unknown",
        )
    status = status.lower()
    stops = None
    if status == "en_route":
        timeline = _first(tracking_card, "timelineSummary.text", "timelineSummary")
        if isinstance(timeline, str) and (
            match := _STOPS_ALONG_THE_WAY.search(timeline)
        ):
            count = match.group(1).lower()
            stops = int(count) if count.isdigit() else _STOP_COUNTS[count]
            status = "stop_before_delivery"
    restaurant = _first(
        data,
        "restaurant.name",
        "store.name",
        "storeInfo.title",
        "feedCard.restaurant.name",
        "orderInfo.storeInfo.name",
    )
    eta = _first(
        data,
        "eta",
        "estimatedDeliveryTime",
        "eaterTrip.eta",
        "feedCard.eta",
    )
    if (
        eta is None
        and _first(data, "activeOrderStatus.subtitle") == "Estimated arrival"
    ):
        eta = _first(data, "activeOrderStatus.title")
    if isinstance(eta, (int, float)):
        try:
            eta = datetime.fromtimestamp(
                eta / 1000 if eta > 10_000_000_000 else eta, UTC
            ).isoformat()
        except (OverflowError, OSError, ValueError):
            eta = None
    courier = _first(data, "courier", "courierInfo", "eaterTrip.courier")
    location = _first(
        data,
        "courier.location",
        "courierInfo.location",
        "eaterTrip.courier.location",
        "eaterTrip.vehicleView.location",
    )
    courier_name = None
    if isinstance(courier, dict):
        courier_name = _first(courier, "name", "firstName")
    if not isinstance(location, dict):
        location = next(
            (
                item
                for item in _card_items(data, "backgroundFeedCards", "mapEntity")
                if item.get("type") == "COURIER"
            ),
            {},
        )
    if not courier_name:
        courier_card = next(_card_items(data, "feedCards", "courier"), {})
        courier_name = _first(courier_card, "title")
    progress = _first(data, "activeOrderStatus.currentProgress")
    progress_segments = _first(data, "activeOrderStatus.totalProgressSegments")
    return Order(
        uuid=order_uuid,
        status=status or "unknown",
        restaurant=str(restaurant) if restaurant else None,
        eta=str(eta) if eta else None,
        courier_name=str(courier_name) if courier_name else None,
        courier_latitude=_as_float(_first(location, "latitude", "lat")),
        courier_longitude=_as_float(_first(location, "longitude", "lng", "lon")),
        raw=data,
        status_detail=status_detail,
        progress=progress if type(progress) is int else None,
        progress_segments=progress_segments if type(progress_segments) is int else None,
        stops_before_delivery=stops,
    )
