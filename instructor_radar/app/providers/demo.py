"""Synthetic planner for development, CI smoke tests and screenshots (`--demo`). All names are made up."""

from __future__ import annotations

import datetime as dt

from ..models import HistoryEntry, Kind, Lesson, Status, StudentInfo, Transmission
from . import Credentials, PlannerSession

_STUDENTS = [
    # key, name, age, transmission, lessons already had (with me, with someone else)
    ("demo-a", "Alex Voorbeeld", 18, Transmission.MANUAL, (6, 2)),
    ("demo-b", "Sam Testmans", 17, Transmission.AUTOMATIC, (0, 4)),
    ("demo-c", "Robin Fictief", 24, Transmission.MANUAL, (0, 0)),
    ("demo-d", "Jo Proefnaam", 19, Transmission.AUTOMATIC, (10, 0)),
]
_LOCATIONS = ["Centrum", "Station Noord"]


class DemoProvider:
    name = "demo"

    async def login(self, session: PlannerSession, credentials: Credentials) -> None:
        return None

    async def logout(self, session: PlannerSession) -> None:
        return None

    async def fetch_events(self, session: PlannerSession, start: dt.date, end: dt.date) -> list[Lesson]:
        lessons = []
        day = start
        n = 0
        while day <= end:
            if day.weekday() < 6:
                for slot, hour in enumerate((8, 10, 13, 15)):
                    if (day.toordinal() + slot) % 3 == 0:
                        continue
                    key, name, age, transmission, (mine, other) = _STUDENTS[(day.toordinal() + slot) % len(_STUDENTS)]
                    exam = slot == 3 and day.weekday() == 3
                    seq = mine + other + 1 + 2 * ((day - start).days // 7)
                    lessons.append(
                        Lesson(
                            id=f"demo-{day:%Y%m%d}-{hour}",
                            start=dt.datetime.combine(day, dt.time(hour)),
                            end=dt.datetime.combine(day, dt.time(hour + 2 if not exam else hour + 1)),
                            kind=Kind.EXAM if exam else Kind.LESSON,
                            licence="B",
                            transmission=transmission,
                            sequence="" if exam else f"{seq}-{seq + 1}",
                            location=_LOCATIONS[n % 2],
                            status=Status.PLANNED,
                            student_key=key,
                            student_name=name if session.settings.include_student_name else None,
                        )
                    )
                    n += 1
            day += dt.timedelta(days=1)
        return lessons

    async def fetch_student(self, session: PlannerSession, student_key: str, today: dt.date) -> StudentInfo:
        _, _, age, _, (mine, other) = next(s for s in _STUDENTS if s[0] == student_key)
        history = []
        for i in range(mine + other):
            with_me = i >= other
            history.append(
                HistoryEntry(
                    date=today - dt.timedelta(days=7 * (mine + other - i) + 3),
                    start="09:00",
                    end="11:00",
                    instructor="Jij" if with_me else "Collega Instructeur",
                    mine=with_me,
                    kind=Kind.LESSON,
                    sequence=f"{2 * i + 1}-{2 * i + 2}",
                    status=Status.CANCELLED if i == 1 else Status.DONE,
                    cancel_reason="Ziek" if i == 1 else "",
                )
            )
        history.append(
            HistoryEntry(
                date=today + dt.timedelta(days=9), start="13:00", end="15:00", instructor="Jij", mine=True,
                kind=Kind.LESSON, sequence=f"{2 * (mine + other) + 3}-{2 * (mine + other) + 4}", status=Status.PLANNED,
            )
        )
        return StudentInfo(
            key=student_key, age=age if session.settings.include_student_age else None, history=history
        )
