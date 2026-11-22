"""Convert delivery estimates into timestamp sensor values."""

import re
from datetime import UTC, datetime, timedelta, tzinfo

_CLOCK = r"(\d{1,2}):(\d{2})(?:\s*([ap]m))?"
_WINDOW = re.compile(rf"{_CLOCK}(?:\s*[-–—]\s*{_CLOCK})?", re.IGNORECASE)


def _clock_minutes(hour: str, minute: str, period: str | None) -> int:
    hours, minutes = int(hour), int(minute)
    if minutes > 59 or (not 1 <= hours <= 12 if period else hours > 23):
        raise ValueError("Invalid ETA clock time")
    if period:
        hours = hours % 12 + (12 if period.lower() == "pm" else 0)
    return hours * 60 + minutes


def _local_instants(wall_time: datetime, timezone: tzinfo) -> set[datetime]:
    """Find real UTC instants for the local clock time, including DST overlaps."""
    instants = {
        wall_time.replace(tzinfo=timezone, fold=fold).astimezone(UTC) for fold in (0, 1)
    }
    return {
        instant
        for instant in instants
        if instant.astimezone(timezone).replace(tzinfo=None) == wall_time
    }


def parse_eta(
    value: str, now: datetime, timezone: tzinfo
) -> tuple[datetime | None, datetime | None]:
    """Return the closest plausible arrival window in UTC."""
    value = value.strip()
    if "T" in value or " " in value:
        try:
            instant = datetime.fromisoformat(value)
        except ValueError:
            pass
        else:
            if instant.tzinfo is None:
                choices = _local_instants(instant, timezone)
                instant = min(choices, key=lambda item: abs(item - now), default=None)
            else:
                instant = instant.astimezone(UTC)
            return instant, instant

    if not (match := _WINDOW.fullmatch(value)):
        return None, None
    start_hour, start_minute, start_period, end_hour, end_minute, end_period = (
        match.groups()
    )
    try:
        start = _clock_minutes(start_hour, start_minute, start_period or end_period)
        end = (
            _clock_minutes(end_hour, end_minute, end_period or start_period)
            if end_hour is not None
            else start
        )
    except ValueError:
        return None, None

    if end < start:
        if end_period and not start_period:
            start -= 12 * 60
        else:
            end += (12 if start_period and not end_period else 24) * 60

    midnight = now.astimezone(timezone).replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=None
    )
    windows = []
    for day in (-1, 0, 1):
        local_start = midnight + timedelta(days=day, minutes=start)
        local_end = midnight + timedelta(days=day, minutes=end)
        starts = _local_instants(local_start, timezone)
        if start == end:
            windows.extend((instant, instant) for instant in starts)
            continue
        ends = _local_instants(local_end, timezone)
        windows.extend(
            (earliest, latest)
            for earliest in starts
            for latest in ends
            if latest >= earliest
        )

    return min(
        windows,
        key=lambda window: (
            max(window[0] - now, now - window[1], timedelta()),
            window[1] - window[0],
            abs(window[0] - now),
        ),
        default=(None, None),
    )
