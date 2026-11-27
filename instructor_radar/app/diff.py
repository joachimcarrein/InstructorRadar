"""Detect added, changed and removed lessons between two fetches."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .models import Lesson


@dataclass(frozen=True)
class Change:
    type: str  # added | changed | removed
    lesson: Lesson  # the new version (or the old one for 'removed')
    before: Lesson | None  # the old version for 'changed'
    detected: dt.datetime
    fields: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "lesson": self.lesson.to_dict(),
            "before": self.before.to_dict() if self.before else None,
            "detected": self.detected.isoformat(timespec="seconds"),
            "fields": list(self.fields),
        }

    @classmethod
    def from_dict(cls, d: dict) -> Change:
        return cls(
            type=d["type"],
            lesson=Lesson.from_dict(d["lesson"]),
            before=Lesson.from_dict(d["before"]) if d.get("before") else None,
            detected=dt.datetime.fromisoformat(d["detected"]),
            fields=tuple(d.get("fields", ())),
        )


def diff(
    old: dict[str, Lesson],
    new: list[Lesson],
    window_start: dt.date,
    window_end: dt.date,
    now: dt.datetime,
    seen_until: dt.date | None = None,
) -> list[Change]:
    """Compare the stored lessons with a fresh fetch of [window_start, window_end].

    Only stored lessons inside the fetched window can be 'removed' (outside it we simply did not look). Likewise,
    a lesson after `seen_until` (the end of the previous fetch window) is not 'added': it may have existed for a long
    time, we only see it now because the window moved on or grew.
    """
    changes: list[Change] = []
    new_by_id = {lesson.id: lesson for lesson in new}
    for lesson in new:
        before = old.get(lesson.id)
        if before is None:
            if seen_until is None or lesson.start.date() <= seen_until:
                changes.append(Change("added", lesson, None, now))
            continue
        fields = tuple(f for f in Lesson.COMPARED if getattr(before, f) != getattr(lesson, f))
        if fields:
            changes.append(Change("changed", lesson, before, now, fields))
    for lesson_id, before in old.items():
        if lesson_id not in new_by_id and window_start <= before.start.date() <= window_end:
            changes.append(Change("removed", before, None, now))
    changes.sort(key=lambda c: c.lesson.start)
    return changes


def to_notify(changes: list[Change], today: dt.date, days: int, now: dt.datetime) -> list[Change]:
    """Changes about lessons from today up to today + days - 1 that have not ended yet (days 0 = none)."""
    if days <= 0:
        return []
    last = today + dt.timedelta(days=days - 1)

    def relevant(c: Change) -> bool:
        lessons = [c.lesson] + ([c.before] if c.before else [])
        return any(today <= x.start.date() <= last and x.end > now for x in lessons)

    return [c for c in changes if relevant(c)]
