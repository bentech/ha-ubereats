"""Test arrival timestamp conversion without a Home Assistant runtime."""

from datetime import UTC, datetime, timedelta, timezone
from runpy import run_path

import pytest

parse_eta = run_path("custom_components/uber_eats/eta.py")["parse_eta"]


@pytest.mark.parametrize(
    ("value", "now", "zone", "earliest", "latest"),
    [
        (
            "5:11 - 5:29 PM",
            "2026-11-22T16:56:00Z",
            UTC,
            "2026-11-22T17:11:00Z",
            "2026-11-22T17:29:00Z",
        ),
        (
            "17:11–17:29",
            "2026-07-01T15:56:00Z",
            timezone(timedelta(hours=1)),
            "2026-07-01T16:11:00Z",
            "2026-07-01T16:29:00Z",
        ),
        (
            "11:55 - 12:10 PM",
            "2026-11-22T11:50:00Z",
            UTC,
            "2026-11-22T11:55:00Z",
            "2026-11-22T12:10:00Z",
        ),
        (
            "11:55 - 12:10 AM",
            "2026-11-22T23:50:00Z",
            UTC,
            "2026-11-22T23:55:00Z",
            "2026-11-23T00:10:00Z",
        ),
        (
            "11:55 PM - 12:10 AM",
            "2026-11-23T00:03:00Z",
            UTC,
            "2026-11-22T23:55:00Z",
            "2026-11-23T00:10:00Z",
        ),
        (
            "00:10",
            "2026-11-22T23:58:00Z",
            UTC,
            "2026-11-23T00:10:00Z",
            "2026-11-23T00:10:00Z",
        ),
        (
            "00:10",
            "2026-11-23T00:20:00Z",
            UTC,
            "2026-11-23T00:10:00Z",
            "2026-11-23T00:10:00Z",
        ),
        (
            "2026-07-01T17:48:00+01:00",
            "2026-07-01T16:30:00Z",
            UTC,
            "2026-07-01T16:48:00Z",
            "2026-07-01T16:48:00Z",
        ),
    ],
)
def test_parse_eta_window(value, now, zone, earliest, latest):
    assert parse_eta(value, datetime.fromisoformat(now), zone) == (
        datetime.fromisoformat(earliest),
        datetime.fromisoformat(latest),
    )


@pytest.mark.parametrize("value", ["Arriving now", "2026-11-22", "25:00", "12:75 PM"])
def test_unrecognized_eta_stays_unknown(value):
    assert parse_eta(value, datetime(2026, 11, 22, tzinfo=UTC), UTC) == (None, None)
