"""Settings edited inside the app (Settings page), not in the add-on options.

- SharedSettings: for everyone (/data/settings.json): what to fetch, when, and which student data to show.
- NotifyPrefs: per Home Assistant user (stored in users.json): devices and which notifications.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .config import ConfigError, parse_fetch_times

DEFAULT_FETCH_TIMES = (dt.time(6, 0), dt.time(22, 0))
NOTIFY_SERVICE = re.compile(r"^notify\.[a-z0-9_]+$")


def _bool(value) -> bool:
    return str(value).lower() in ("1", "true", "on", "yes")


def _int(value, low: int, high: int, name: str) -> int:
    try:
        number = int(str(value).strip())
    except ValueError:
        raise ConfigError(f"{name}: not a number") from None
    if not low <= number <= high:
        raise ConfigError(f"{name}: must be between {low} and {high}")
    return number


def _time(value, name: str) -> dt.time:
    m = re.match(r"^([01]\d|2[0-3]):([0-5]\d)$", str(value).strip())
    if not m:
        raise ConfigError(f"{name}: not a time like 06:30")
    return dt.time(int(m.group(1)), int(m.group(2)))


@dataclass(frozen=True)
class SharedSettings:
    days_ahead: int = 14
    fetch_times: tuple[dt.time, ...] = DEFAULT_FETCH_TIMES
    include_student_name: bool = False
    include_student_age: bool = False

    def to_dict(self) -> dict:
        return {
            "days_ahead": self.days_ahead,
            "fetch_times": [t.strftime("%H:%M") for t in self.fetch_times],
            "include_student_name": self.include_student_name,
            "include_student_age": self.include_student_age,
        }

    @classmethod
    def from_dict(cls, d: dict) -> SharedSettings:
        """Lenient: anything invalid falls back to its default (a broken file must not stop the add-on)."""
        default = cls()
        try:
            days = _int(d.get("days_ahead", default.days_ahead), 1, 60, "days_ahead")
        except ConfigError:
            days = default.days_ahead
        try:
            times = parse_fetch_times(d.get("fetch_times") or [])
        except ConfigError:
            times = default.fetch_times
        return cls(days, times, bool(d.get("include_student_name", False)), bool(d.get("include_student_age", False)))

    @classmethod
    def from_form(cls, form) -> SharedSettings:
        """Strict: from the Settings page. Raises ConfigError with a message for the user."""
        times = [x for x in re.split(r"[\s,;]+", str(form.get("fetch_times", ""))) if x]
        return cls(
            days_ahead=_int(form.get("days_ahead", ""), 1, 60, "days_ahead"),
            fetch_times=parse_fetch_times(times),
            include_student_name=_bool(form.get("include_student_name")),
            include_student_age=_bool(form.get("include_student_age")),
        )


class SettingsStore:
    def __init__(self, path: Path):
        self.path = path

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> SharedSettings:
        try:
            return SharedSettings.from_dict(json.loads(self.path.read_text(encoding="utf-8")))
        except (FileNotFoundError, json.JSONDecodeError, AttributeError):
            return SharedSettings()

    def save(self, settings: SharedSettings) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings.to_dict(), indent=1), encoding="utf-8")
        os.replace(tmp, self.path)


def from_legacy_options(raw: dict) -> SharedSettings:
    """Version 2026.11.0 had these as add-on options; carry them over once."""
    return SharedSettings.from_dict({k: raw[k] for k in SharedSettings().to_dict() if k in raw})


@dataclass(frozen=True)
class NotifyPrefs:
    devices: tuple[str, ...] | None = None  # None = never saved (the phones are suggested)
    changes: bool = True
    changes_days: int = 2
    reminder: bool = False
    reminder_minutes: int = 30
    summary: bool = False
    summary_time: dt.time = dt.time(6, 30)

    @property
    def active(self) -> bool:
        return bool(self.devices) and (self.changes or self.reminder or self.summary)

    def to_dict(self) -> dict:
        return {
            "devices": list(self.devices) if self.devices is not None else None,
            "changes": self.changes,
            "changes_days": self.changes_days,
            "reminder": self.reminder,
            "reminder_minutes": self.reminder_minutes,
            "summary": self.summary,
            "summary_time": self.summary_time.strftime("%H:%M"),
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> NotifyPrefs:
        if not isinstance(d, dict):
            return cls()
        default = cls()
        devices = d.get("devices")
        try:
            summary_time = _time(d.get("summary_time", "06:30"), "summary_time")
        except ConfigError:
            summary_time = default.summary_time
        return cls(
            devices=tuple(x for x in devices if NOTIFY_SERVICE.match(str(x))) if isinstance(devices, list) else None,
            changes=bool(d.get("changes", default.changes)),
            changes_days=int(d.get("changes_days", default.changes_days)) if str(d.get("changes_days", "")).isdigit()
            else default.changes_days,
            reminder=bool(d.get("reminder", default.reminder)),
            reminder_minutes=int(d.get("reminder_minutes", default.reminder_minutes))
            if str(d.get("reminder_minutes", "")).isdigit() else default.reminder_minutes,
            summary=bool(d.get("summary", default.summary)),
            summary_time=summary_time,
        )

    @classmethod
    def from_form(cls, form, devices: list[str]) -> NotifyPrefs:
        chosen = tuple(sorted({d for d in devices if NOTIFY_SERVICE.match(d)}))
        return cls(
            devices=chosen,
            changes=_bool(form.get("changes")),
            changes_days=_int(form.get("changes_days", "2"), 1, 14, "changes_days"),
            reminder=_bool(form.get("reminder")),
            reminder_minutes=_int(form.get("reminder_minutes", "30"), 5, 240, "reminder_minutes"),
            summary=_bool(form.get("summary")),
            summary_time=_time(form.get("summary_time", "06:30"), "summary_time"),
        )
