"""Tests for the Uber Eats response parser and HTTP client."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

# Keep parser tests runnable outside a complete Home Assistant installation.
# Production uses Home Assistant's aiohttp dependency; these exception stubs are
# sufficient because transport behavior is exercised with the fakes below.
aiohttp = ModuleType("aiohttp")
aiohttp.ClientError = type("ClientError", (Exception,), {})
aiohttp.ClientResponseError = type("ClientResponseError", (aiohttp.ClientError,), {})
aiohttp.ClientSession = object
sys.modules.setdefault("aiohttp", aiohttp)

spec = importlib.util.spec_from_file_location(
    "uber_eats_api", Path("custom_components/uber_eats/api.py")
)
assert spec is not None and spec.loader is not None
api_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = api_module
spec.loader.exec_module(api_module)

UberEatsApi = api_module.UberEatsApi
UberEatsAuthError = api_module.UberEatsAuthError
UberEatsApiError = api_module.UberEatsApiError
_find_order = api_module._find_order
_normalize_order = api_module._normalize_order

FIXTURES = Path(__file__).parent / "fixtures"
ORDER_UUID = "00000000-0000-4000-8000-000000000001"


def load_fixture(name: str) -> dict:
    """Load a synthetic order fixture."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("fixture", "status", "restaurant", "courier", "latitude", "longitude"),
    [
        ("preparing.json", "preparing", "Example Kitchen", None, None, None),
        ("on_the_way.json", "en_route", "Example Kitchen", "Sam", 51.5, -0.1),
    ],
)
def test_captured_response_shapes_are_normalized(
    fixture: str,
    status: str,
    restaurant: str,
    courier: str | None,
    latitude: float | None,
    longitude: float | None,
) -> None:
    """Order stages produce stable values for Home Assistant."""
    payload = load_fixture(fixture)
    data = _find_order(payload, ORDER_UUID)

    assert data is not None
    order = _normalize_order(data, ORDER_UUID)
    assert order.status == status
    assert order.restaurant == restaurant
    assert order.courier_name == courier
    assert order.courier_latitude == latitude
    assert order.courier_longitude == longitude


def test_find_order_selects_configured_order() -> None:
    """An unrelated order is never selected when the UUID is present."""
    payload = load_fixture("preparing.json")
    payload["data"]["orders"].insert(0, {"orderUuid": "other", "status": "delivered"})

    result = _find_order(payload, ORDER_UUID)

    assert result is not None
    assert result["orderUuid"] == ORDER_UUID


def test_find_order_returns_none_without_an_order() -> None:
    """Metadata dictionaries are not mistaken for orders."""
    assert _find_order({"data": {"status": {"code": 200}}}, ORDER_UUID) is None


@pytest.mark.parametrize(
    (
        "filename",
        "status",
        "detail",
        "eta",
        "progress",
        "courier",
        "coordinates",
        "stops",
    ),
    [
        (
            "tracking_en_route.json",
            "en_route",
            "Heading your way...",
            "6:48 PM",
            3,
            "Sam",
            (51.5, -0.1),
            None,
        ),
        (
            "tracking_between_stops.json",
            "stop_before_delivery",
            "Heading your way...",
            "6:49 PM",
            3,
            None,
            (None, None),
            1,
        ),
        (
            "tracking_arriving.json",
            "arriving",
            "Almost here!",
            "6:51 PM",
            4,
            "Sam",
            (None, None),
            None,
        ),
    ],
)
def test_web_tracking_responses(
    filename, status, detail, eta, progress, courier, coordinates, stops
):
    data = _find_order(load_fixture(filename), ORDER_UUID)
    assert data is not None
    order = _normalize_order(data, ORDER_UUID)

    assert order.status == status
    assert order.status_detail == detail
    assert order.restaurant == "Example Kitchen"
    assert order.eta == eta
    assert order.courier_name == courier
    assert (order.courier_latitude, order.courier_longitude) == coordinates
    assert order.progress == progress
    assert order.progress_segments == 5
    assert order.stops_before_delivery == stops


def test_different_active_order_is_never_used_as_a_fallback():
    payload = {
        "data": {"orders": [{"uuid": "another-order", "orderStatus": "PREPARING"}]}
    }
    assert _find_order(payload, ORDER_UUID) is None


@pytest.mark.parametrize(
    ("timeline", "expected", "stops"),
    [
        (
            "Your order is on the move! Sam has one stop along the way.",
            "stop_before_delivery",
            1,
        ),
        ("Sam has 2 stops along the way.", "stop_before_delivery", 2),
        ({"text": "Sam has two stops along the way."}, "stop_before_delivery", 2),
        ("Your order is on the move!", "en_route", None),
    ],
)
def test_intermediate_stops_are_reported_from_the_tracking_card(
    timeline, expected, stops
):
    active = {
        "uuid": ORDER_UUID,
        "orderInfo": {"orderPhase": "ACTIVE"},
        "feedCards": [
            {
                "status": {
                    "titleSummary": {"summary": {"text": "Heading your way..."}},
                    "timelineSummary": timeline,
                },
            }
        ],
    }
    order = _normalize_order(active, ORDER_UUID)
    assert order.status == expected
    assert order.stops_before_delivery == stops
    assert order.status_detail == "Heading your way..."


def test_web_status_card_takes_precedence_over_overview():
    active = {
        "uuid": ORDER_UUID,
        "orderInfo": {"orderPhase": "ACTIVE"},
        "activeOrderStatus": {
            "title": "5:08 - 5:29 PM",
            "subtitle": "Estimated arrival",
            "currentProgress": 1,
            "titleSummary": {"summary": {"text": "Picking up your order..."}},
        },
        "feedCards": [
            {"status": {"titleSummary": {"summary": {"text": "Preparing your order…"}}}}
        ],
    }
    order = _normalize_order(active, ORDER_UUID)
    assert order.status == "preparing"
    assert order.status_detail == "Preparing your order…"
    assert order.eta == "5:08 - 5:29 PM"
    assert order.progress == 1


class FakeResponse:
    """Minimal aiohttp response context manager."""

    def __init__(self, status: int, payload: dict) -> None:
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    async def json(self, **_kwargs):
        return self._payload


class FakeSession:
    """Record the outgoing request and return a configured response."""

    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.request: dict | None = None

    def post(self, url, **kwargs):
        self.request = {"url": url, **kwargs}
        return self.response


def test_api_sends_minimal_required_request() -> None:
    """The client derives request data rather than persisting captured headers."""
    session = FakeSession(FakeResponse(200, load_fixture("preparing.json")))
    api = UberEatsApi(
        session,
        cookie="sid=redacted",
        order_uuid=ORDER_UUID,
        timezone="Europe/London",
        locale="GB",
    )

    order = asyncio.run(api.async_get_order())

    assert order.status == "preparing"
    assert session.request["params"] == {"localeCode": "gb"}
    assert session.request["json"]["orderUuid"] == ORDER_UUID
    assert session.request["headers"]["Cookie"] == "sid=redacted"
    assert "Content-Length" not in session.request["headers"]
    assert not any(
        key.startswith("x-uber-device") for key in session.request["headers"]
    )


@pytest.mark.parametrize("status", [401, 403])
def test_api_reports_expired_session(status: int) -> None:
    """Authentication failures have a specific exception type."""
    api = UberEatsApi(
        FakeSession(FakeResponse(status, {})),
        cookie="expired",
        order_uuid=ORDER_UUID,
        timezone="Europe/London",
        locale="gb",
    )

    with pytest.raises(UberEatsAuthError, match="rejected"):
        asyncio.run(api.async_get_order())


def test_api_rejects_response_without_order() -> None:
    """A successful but unusable response does not publish stale-looking data."""
    api = UberEatsApi(
        FakeSession(FakeResponse(200, {"data": {"orders": []}})),
        cookie="sid=redacted",
        order_uuid=ORDER_UUID,
        timezone="Europe/London",
        locale="gb",
    )

    with pytest.raises(UberEatsApiError, match="not present"):
        asyncio.run(api.async_get_order())


def test_api_distinguishes_successful_empty_response_from_error():
    payload = {"status": "success", "data": {"orders": []}}
    api = UberEatsApi(
        FakeSession(FakeResponse(200, payload)),
        cookie="sid=redacted",
        order_uuid=ORDER_UUID,
        timezone="Europe/London",
        locale="gb",
    )
    with pytest.raises(api_module.UberEatsOrderNotActive):
        asyncio.run(api.async_get_order())


def test_account_request_tracks_an_active_order_without_input_id():
    payload = load_fixture("preparing.json")
    payload["status"] = "success"
    payload["data"]["orders"].insert(
        0, {"uuid": "another-order", "status": "preparing"}
    )
    session = FakeSession(FakeResponse(200, payload))
    api = UberEatsApi(
        session,
        cookie="sid=redacted",
        timezone="Europe/London",
        locale="gb",
    )

    assert asyncio.run(api.async_get_order()).uuid == "another-order"
    assert asyncio.run(api.async_get_order(ORDER_UUID)).uuid == ORDER_UUID
    payload["data"]["orders"].pop()
    assert asyncio.run(api.async_get_order(ORDER_UUID)).uuid == "another-order"
    assert session.request["json"]["orderUuid"] is None
    assert session.request["headers"]["Referer"] == "https://www.ubereats.com/gb/orders"
