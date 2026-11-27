"""Notifications to the devices each Home Assistant user chose in Settings › My notifications.

- Changes: after a fetch, about lessons from today up to the user's number of days.
- Reminder: N minutes before each lesson.
- Morning summary: today's lessons at the user's time.
Reminders and summaries are sent at most 30 minutes late (e.g. after a restart), never later, and only once.
Nothing is sent to anyone who did not choose devices and switch a notification on themselves.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from .diff import Change, to_notify
from .i18n import Translator
from .models import Lesson, Status
from .present import kind_label, licence_label, one_line, summary, when

if TYPE_CHECKING:
    from .sync import Radar

log = logging.getLogger(__name__)

LATE = dt.timedelta(minutes=30)
MAX_LINES = 10

Who = Callable[[Lesson], str]  # the student label of a lesson ('' when names are off)


class Notifier:
    def __init__(self, radar: Radar):
        self.radar = radar

    def _recipients(self):
        return self.radar.users.recipients() if self.radar.users else []

    async def _lang(self, user_id: str | None) -> str:
        if user_id and self.radar.users and (lang := self.radar.users.effective_language(user_id)):
            return lang
        return await self.radar.language()

    async def _send(self, devices, title: str, message: str) -> int:
        sent = 0
        for device in devices:
            await self.radar.ha.notify(device.removeprefix("notify."), title, message)
            sent += 1
        return sent

    # ---------------------------------------------------------------- changes

    async def changes(self, changes: list[Change], now: dt.datetime) -> None:
        """Only to users who switched it on themselves; nobody set up = nothing is sent (the Changes page shows them)."""
        naive = now.replace(tzinfo=None)
        for user_id, prefs in [(u, p) for u, p in self._recipients() if p.changes]:
            relevant = to_notify(changes, naive.date(), prefs.changes_days, naive)
            if not relevant:
                continue
            t = Translator(await self._lang(user_id))
            await self._send(prefs.devices, t("notify_title"), _changes_message(relevant, t, self.radar.who))
            log.info("Change notification sent (%d changes, %d devices)", len(relevant), len(prefs.devices))

    # ---------------------------------------------------------------- reminders and summary

    async def tick(self, now: dt.datetime) -> None:
        """Called every ~30 seconds."""
        users = self.radar.users
        if users is None:
            return
        naive = now.replace(tzinfo=None)
        today = naive.date()
        lessons = [x for x in self.radar.state.lessons.values() if x.status != Status.CANCELLED]
        for user_id, prefs in users.recipients():
            if prefs.reminder:
                for lesson in lessons:
                    at = lesson.start - dt.timedelta(minutes=prefs.reminder_minutes)
                    key = f"r|{lesson.id}|{lesson.start:%Y%m%d%H%M}|{prefs.reminder_minutes}"
                    if at <= naive < min(at + LATE, lesson.start) and not users.was_sent(user_id, key):
                        users.mark_sent(user_id, key, today)
                        t = Translator(await self._lang(user_id))
                        await self._send(prefs.devices, *_reminder(lesson, prefs.reminder_minutes, t, self.radar.who))
                        log.info("Lesson reminder sent (%d devices)", len(prefs.devices))
            if prefs.summary:
                at = dt.datetime.combine(today, prefs.summary_time)
                key = f"s|{today.isoformat()}"
                if at <= naive < at + LATE and not users.was_sent(user_id, key):
                    users.mark_sent(user_id, key, today)
                    todays = sorted((x for x in lessons if x.start.date() == today), key=lambda x: x.start)
                    if todays:
                        t = Translator(await self._lang(user_id))
                        await self._send(prefs.devices, *_summary(todays, t, self.radar.who))
                        log.info("Morning summary sent (%d lessons, %d devices)", len(todays), len(prefs.devices))

    async def test(self, user_id: str) -> int:
        prefs = self.radar.users.notify(user_id) if self.radar.users else None
        if not prefs or not prefs.devices:
            return 0
        t = Translator(await self._lang(user_id))
        return await self._send(prefs.devices, t("test_title"), t("test_message"))


def notification_samples(t: Translator, settings) -> tuple[tuple[str, str], tuple[str, str]]:
    """(reminder, summary) as (title, message) with made-up lessons, written by the same code as the real ones."""
    from .models import Kind, Transmission

    today = dt.date.today()
    from .models import StudentInfo

    students: dict[str, StudentInfo] = {}

    def lesson(hour, minute, hours, kind, gear, seq, name, years):
        start = dt.datetime.combine(today, dt.time(hour, minute))
        key = f"sample-{hour}"
        students[key] = StudentInfo(key, age=years, name=name)
        return Lesson(
            id=key, start=start, end=start + dt.timedelta(hours=hours), kind=kind, licence="B",
            transmission=gear, sequence=seq, location="Centrum", status=Status.PLANNED, student_key=key,
        )

    def who(x: Lesson) -> str:
        return students[x.student_key].label(settings.include_student_name, settings.include_student_age)

    day = [
        lesson(8, 0, 2, Kind.LESSON, Transmission.MANUAL, "11-12", "Alex Voorbeeld", 18),
        lesson(10, 30, 2, Kind.LESSON, Transmission.AUTOMATIC, "3-4", "Sam Testmans", 17),
        lesson(14, 50, 1, Kind.EXAM, Transmission.AUTOMATIC, "", "Robin Fictief", 24),
    ]
    return _reminder(day[0], 30, t, who), _summary(day, t, who)


def _changes_message(relevant: list[Change], t: Translator, who: Who) -> str:
    lines = []
    for c in relevant[:MAX_LINES]:
        line = one_line(c.lesson, t, who(c.lesson))
        if c.type == "added":
            lines.append(t("notify_added", lesson=line))
        elif c.type == "removed":
            lines.append(t("notify_removed", lesson=line))
        else:
            lines.append(t("notify_changed", lesson=line, before=when(c.before, t)))
    if len(relevant) > MAX_LINES:
        lines.append("…")
    return "\n".join(lines)


def _reminder(lesson: Lesson, minutes: int, t: Translator, who: Who) -> tuple[str, str]:
    title = t("reminder_title", minutes=minutes, label=kind_label(lesson, t))
    parts = [f"{lesson.start:%H:%M}–{lesson.end:%H:%M}", licence_label(lesson, t), lesson.location, who(lesson)]
    return title, " · ".join(p for p in parts if p)


def _summary(lessons: list[Lesson], t: Translator, who: Who) -> tuple[str, str]:
    title = t("summary_title", count=len(lessons))
    return title, "\n".join(f"{x.start:%H:%M} {summary(x, t, who(x))}" for x in lessons)
