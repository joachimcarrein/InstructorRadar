"""When to fetch: fixed local times of day, one retry when the planner was busy, and 'fetch now' requests."""

from __future__ import annotations

import datetime as dt

BUSY_RETRY = dt.timedelta(minutes=15)
MANUAL_MIN_INTERVAL = dt.timedelta(minutes=2)


def next_run(now: dt.datetime, times: tuple[dt.time, ...]) -> dt.datetime:
    """The first configured time strictly after `now` (same tzinfo as `now`)."""
    if not times:
        raise ValueError("no fetch times")
    for day_offset in (0, 1):
        day = now.date() + dt.timedelta(days=day_offset)
        for t in sorted(times):
            candidate = dt.datetime.combine(day, t, tzinfo=now.tzinfo)
            if candidate > now:
                return candidate
    raise AssertionError("unreachable")


def manual_allowed(last_attempt: dt.datetime | None, now: dt.datetime) -> bool:
    """Protect the planner's session slots: at most one manual fetch per MANUAL_MIN_INTERVAL."""
    return last_attempt is None or now - last_attempt >= MANUAL_MIN_INTERVAL


def is_fetch_command(line: str) -> bool:
    """hassio.addon_stdin input: 'fetch', '"fetch"' or {"action": "fetch"}."""
    text = line.strip().strip('"').strip().lower()
    if text in ("fetch", "fetch_now", "fetch now"):
        return True
    return text.replace(" ", "") in ('{"action":"fetch"}', "{'action':'fetch'}", '{"action":"fetch_now"}')
