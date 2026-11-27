"""Internal model. Deliberately minimal: no phone, address, e-mail, birthdate or other student personal data.

The student's name and age live only in the student record (StudentInfo), never on a lesson: a lesson refers to its
student by an opaque key, so there is one place to update and one place to strip when an option is switched off.

Providers build these objects and drop everything else before returning, so nothing beyond these fields can reach
the store, the ICS, the web UI or the logs.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum


class Kind(StrEnum):
    LESSON = "lesson"
    EXAM = "exam"
    OTHER = "other"


class Transmission(StrEnum):
    MANUAL = "manual"
    AUTOMATIC = "automatic"
    UNKNOWN = "unknown"


class Status(StrEnum):
    PLANNED = "planned"
    CONFIRMED = "confirmed"
    DONE = "done"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Lesson:
    """One appointment in the instructor's own schedule. Times are naive local time (the planner's time zone)."""

    id: str
    start: dt.datetime
    end: dt.datetime
    kind: Kind
    licence: str  # e.g. "B"
    transmission: Transmission
    sequence: str  # e.g. "11-12", "23", or "" when not numbered
    location: str  # human-readable location name (or code when unknown)
    status: Status
    student_key: str  # opaque key (hash), never the planner's own id
    title: str = ""  # only for appointments without a student (e.g. 'Beschikbaar voor rijlessen')

    # Fields compared to detect a change.
    COMPARED = ("start", "end", "kind", "licence", "transmission", "sequence", "location", "status", "student_key")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["start"] = self.start.isoformat(timespec="minutes")
        d["end"] = self.end.isoformat(timespec="minutes")
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Lesson:
        return cls(
            id=str(d["id"]),
            start=dt.datetime.fromisoformat(d["start"]),
            end=dt.datetime.fromisoformat(d["end"]),
            kind=Kind(d.get("kind", Kind.OTHER)),
            licence=str(d.get("licence", "")),
            transmission=Transmission(d.get("transmission", Transmission.UNKNOWN)),
            sequence=str(d.get("sequence", "")),
            location=str(d.get("location", "")),
            status=Status(d.get("status", Status.PLANNED)),
            student_key=str(d.get("student_key", "")),
            title=str(d.get("title", "")),
        )


@dataclass(frozen=True)
class HistoryEntry:
    """One past or planned lesson of a student (with any instructor)."""

    date: dt.date
    start: str  # "HH:MM" or ""
    instructor: str  # instructor's display name as the planner shows it
    mine: bool  # True when it was (or is) with the instructor whose account is used
    kind: Kind
    sequence: str
    status: Status
    cancel_reason: str = ""
    end: str = ""  # "HH:MM" or ""
    result: str = ""  # exams only: "passed" | "failed" | "" (unknown / not taken yet)
    event_id: str = ""  # the planner's id of the appointment; equals Lesson.id of the same appointment

    @property
    def minutes(self) -> int:
        """Duration in minutes (0 when start or end is unknown)."""
        try:
            sh, sm = (int(x) for x in self.start.split(":")[:2])
            eh, em = (int(x) for x in self.end.split(":")[:2])
        except ValueError:
            return 0
        return max(0, (eh * 60 + em) - (sh * 60 + sm))

    @property
    def units(self) -> int:
        """Lesson units of this entry: '11-12' = 2, '23' = 1, unnumbered = 1."""
        numbers = [int(x) for x in self.sequence.split("-") if x.isdigit()]
        if len(numbers) == 2 and 0 <= numbers[1] - numbers[0] < 8:
            return numbers[1] - numbers[0] + 1
        return 1

    def to_dict(self) -> dict:
        d = asdict(self)
        d["date"] = self.date.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> HistoryEntry:
        return cls(
            date=dt.date.fromisoformat(d["date"]),
            start=str(d.get("start", "")),
            instructor=str(d.get("instructor", "")),
            mine=bool(d.get("mine", False)),
            kind=Kind(d.get("kind", Kind.OTHER)),
            sequence=str(d.get("sequence", "")),
            status=Status(d.get("status", Status.DONE)),
            cancel_reason=str(d.get("cancel_reason", "")),
            end=str(d.get("end", "")),
            result=str(d.get("result", "")),
            event_id=str(d.get("event_id", "")),
        )


@dataclass(frozen=True)
class StudentInfo:
    key: str
    age: int | None = None  # only when include_student_age is on
    history: list[HistoryEntry] = field(default_factory=list)
    name: str | None = None  # only when include_student_name is on

    def label(self, show_name: bool, show_age: bool) -> str:
        """'Name (18)', 'Name' or '' (an age alone says nothing)."""
        if not (show_name and self.name):
            return ""
        return f"{self.name} ({self.age})" if show_age and self.age is not None else self.name

    def without_personal(self, keep_name: bool, keep_age: bool) -> StudentInfo:
        return replace(self, name=self.name if keep_name else None, age=self.age if keep_age else None)

    def _practice(self, measure) -> tuple[int, int]:
        driven = planned = 0
        for h in self.history:
            if h.kind != Kind.LESSON:
                continue
            if h.status == Status.DONE:
                driven += measure(h)
            elif h.status in (Status.PLANNED, Status.CONFIRMED):
                planned += measure(h)
        return driven, planned

    def practice_minutes(self) -> tuple[int, int]:
        """(driven, planned) minutes of practical lessons; exams, theory and cancelled lessons do not count."""
        return self._practice(lambda h: h.minutes)

    def lesson_counts(self) -> tuple[int, int]:
        """(driven, planned) number of practical lessons, counted in lesson units ('11-12' = 2)."""
        return self._practice(lambda h: h.units)

    def familiarity(self, before: dt.datetime | dt.date) -> str:
        """'first' = no earlier lesson at all, 'new' = earlier lessons but never with me, '' = I had them before.

        Earlier = before this lesson (date and start time), driven or still planned: lesson 3-4 the day after a
        planned lesson 1-2 is not a first lesson. Cancelled lessons and exams do not count.
        """
        if isinstance(before, dt.datetime):
            limit = (before.date(), f"{before:%H:%M}")
            earlier = [h for h in self.history if (h.date, h.start) < limit]
        else:
            earlier = [h for h in self.history if h.date < before]
        counted = (Status.DONE, Status.PLANNED, Status.CONFIRMED)
        past = [h for h in earlier if h.status in counted and h.kind == Kind.LESSON]
        if not past:
            return "first"
        if not any(h.mine for h in past):
            return "new"
        return ""
