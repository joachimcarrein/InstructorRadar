"""iCalendar (RFC 5545) output for the Home Assistant Remote Calendar integration."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable
from zoneinfo import ZoneInfo

from .i18n import Translator
from .models import Lesson, Status
from .present import kind_label, licence_label, summary


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")


def _fold(line: str) -> str:
    """Fold lines longer than 75 octets (continuation lines start with a space)."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, current, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        limit = 75 if not parts else 74
        if size + n > limit:
            parts.append(current)
            current, size = "", 0
        current += ch
        size += n
    parts.append(current)
    return "\r\n ".join(parts)


def _utc(value: dt.datetime, tz: ZoneInfo) -> str:
    return value.replace(tzinfo=tz).astimezone(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def build_calendar(
    lessons: Iterable[Lesson],
    t: Translator,
    tz: ZoneInfo,
    now: dt.datetime,
    name: str,
    who: Callable[[Lesson], str] = lambda lesson: "",
) -> str:
    stamp = now.astimezone(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Instructor Radar//EN",
        "CALSCALE:GREGORIAN",
        f"X-WR-CALNAME:{_escape(name)}",
    ]
    for lesson in sorted(lessons, key=lambda x: x.start):
        description = [kind_label(lesson, t), licence_label(lesson, t)]
        lines += [
            "BEGIN:VEVENT",
            f"UID:{_escape(lesson.id)}@instructor-radar",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{_utc(lesson.start, tz)}",
            f"DTEND:{_utc(lesson.end, tz)}",
            f"SUMMARY:{_escape(summary(lesson, t, who(lesson)))}",
            f"LOCATION:{_escape(lesson.location)}",
            f"DESCRIPTION:{_escape(' · '.join(d for d in description if d))}",
            f"STATUS:{'CANCELLED' if lesson.status == Status.CANCELLED else 'CONFIRMED'}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
