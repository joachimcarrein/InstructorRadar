"""One fetch run: login -> lessons -> (student histories) -> logout -> diff -> store -> notify.

The planner limits simultaneous sessions per account, so a run holds its session as briefly as possible: requests
are sequential, there is a hard time limit, and logout always happens (also after an error).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from collections.abc import Callable
from dataclasses import replace
from zoneinfo import ZoneInfo

import aiohttp

from .config import Options
from .diff import Change, diff, to_notify
from .ha import ERROR_NOTIFICATION_ID, HomeAssistant
from .i18n import Translator
from .ics import build_calendar
from .models import Lesson
from .present import one_line, when
from .providers import (
    Credentials,
    FetchSettings,
    NotLoggedIn,
    PlannerBusy,
    PlannerSession,
    Provider,
    ProviderError,
)
from .scheduler import BUSY_RETRY, manual_allowed
from .store import RunInfo, State, Store, StudentRecord, apply_privacy, prune, week_start
from .users import UserSettings

log = logging.getLogger(__name__)

RUN_TIMEOUT = 60  # seconds for the whole planner conversation (logout excluded)
REQUEST_TIMEOUT = 20
LOGOUT_TIMEOUT = 10
MAX_STUDENTS_PER_RUN = 40
MAX_NOTIFY_LINES = 10
CHANGES_NOTIFICATION_ID = "instructor_radar_changes"
USER_AGENT = "Mozilla/5.0 (compatible; InstructorRadar; +https://github.com/joachimcarrein/InstructorRadar)"


class Radar:
    def __init__(
        self,
        options: Options,
        store: Store,
        ha: HomeAssistant,
        provider: Provider,
        tz: ZoneInfo,
        clock: Callable[[], dt.datetime] | None = None,
        users: UserSettings | None = None,
    ):
        self.options = options
        self.store = store
        self.ha = ha
        self.provider = provider
        self.tz = tz
        self.users = users
        self._clock = clock or (lambda: dt.datetime.now(tz))
        self._lock = asyncio.Lock()
        self.last_attempt: dt.datetime | None = None
        self.retry_at: dt.datetime | None = None
        self._lang: str | None = None
        self.state: State = apply_privacy(
            prune(store.load(), self.now().date()), options.include_student_name, options.include_student_age
        )

    def now(self) -> dt.datetime:
        return self._clock()

    @property
    def running(self) -> bool:
        return self._lock.locked()

    async def language(self) -> str:
        """Notification language: what the most recent visitor of the UI sees, else Home Assistant's language."""
        if self.users and (seen := self.users.notification_language()):
            return seen
        if self._lang is None:
            self._lang = await self.ha.language()
        return self._lang

    # ------------------------------------------------------------------ manual trigger

    def manual_request(self) -> str:
        """'started' | 'running' | 'too_soon'. The caller starts `run('manual')` when 'started'."""
        if self.running:
            return "running"
        if not manual_allowed(self.last_attempt, self.now()):
            return "too_soon"
        return "started"

    # ------------------------------------------------------------------ the run

    async def run(self, reason: str = "scheduled") -> RunInfo:
        async with self._lock:
            return await self._run(reason)

    async def _run(self, reason: str) -> RunInfo:
        now = self.now()
        self.last_attempt = now
        today = now.date()
        window_start, window_end = week_start(today), today + dt.timedelta(days=self.options.days_ahead)
        previous = self.state.run
        started = time.monotonic()
        session = PlannerSession(
            http=aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                headers={"User-Agent": USER_AGENT},
                cookie_jar=aiohttp.CookieJar(),
            ),
            base_url=self.options.base_url,
            settings=FetchSettings(self.options.include_student_name, self.options.include_student_age),
        )
        credentials = Credentials(
            self.options.username, self.options.password, self.options.auth_mode, self.options.totp_secret
        )
        changes: list[Change] = []
        refreshed = 0
        try:
            login_attempted = False
            try:
                async with asyncio.timeout(RUN_TIMEOUT):
                    login_attempted = True
                    await self.provider.login(session, credentials)
                    lessons = await self.provider.fetch_events(session, window_start, window_end)
                    changes = diff(self.state.lessons, lessons, window_start, window_end, now)
                    students, refreshed = await self._refresh_students(session, lessons, changes, today)
            finally:
                if login_attempted:
                    await self._logout(session)
                await session.http.close()
        except PlannerBusy as exc:
            return await self._finish_busy(exc, now, reason, previous)
        except ProviderError as exc:
            return await self._finish_error(exc.message, now, notify=exc.notify)
        except TimeoutError:
            return await self._finish_error("The planner did not answer in time; trying again at the next fetch time.", now)
        except aiohttp.ClientError as exc:
            return await self._finish_error(f"Could not reach the planner ({type(exc).__name__}).", now)
        except Exception:  # noqa: BLE001 - keep the add-on running; details without personal data
            log.exception("Unexpected error during the fetch")
            return await self._finish_error("Unexpected error during the fetch; see the add-on log.", now)

        lessons = [self._with_age(lesson, students) for lesson in lessons]
        first_run = previous.last_success is None
        self._apply(lessons, students, changes if not first_run else [], window_start, window_end, today)
        self.retry_at = None
        self.state.run = RunInfo(
            at=now, status="ok", message="", lessons=len(lessons), changes=len(changes), last_success=now
        )
        self.store.save(self.state)
        log.info(
            "Fetch (%s) ok: %d lessons, %d changes, %d students refreshed, %d requests in %.1fs",
            reason,
            len(lessons),
            0 if first_run else len(changes),
            refreshed,
            session.request_count,
            time.monotonic() - started,
        )
        if previous.status == "error":
            await self.ha.dismiss_notification(ERROR_NOTIFICATION_ID)
        if not first_run:
            await self._notify_changes(changes, now)
        return self.state.run

    async def _logout(self, session: PlannerSession) -> None:
        try:
            async with asyncio.timeout(LOGOUT_TIMEOUT):
                await self.provider.logout(session)
        except Exception as exc:  # noqa: BLE001 - logout is best effort, never fatal
            log.warning("Logout failed (%s); the planner ends the session after its idle timeout", type(exc).__name__)

    async def _refresh_students(
        self, session: PlannerSession, lessons: list[Lesson], changes: list[Change], today: dt.date
    ) -> tuple[dict[str, StudentRecord], int]:
        """Fetch history (and age) for students that are new, changed, or not refreshed today."""
        students = {k: v for k, v in self.state.students.items()}
        keys = sorted({lesson.student_key for lesson in lessons if lesson.student_key})
        changed = {c.lesson.student_key for c in changes}
        todo = [k for k in keys if k not in students or students[k].refreshed < today or k in changed]
        refreshed = 0
        for key in todo[:MAX_STUDENTS_PER_RUN]:
            try:
                info = await self.provider.fetch_student(session, key, today)
            except NotLoggedIn:
                raise
            except ProviderError as exc:
                # One odd student page must not cost the whole schedule.
                log.warning("Student details skipped: %s", type(exc).__name__)
                continue
            students[key] = StudentRecord(info=info, refreshed=today)
            refreshed += 1
        return students, refreshed

    def _with_age(self, lesson: Lesson, students: dict[str, StudentRecord]) -> Lesson:
        if not self.options.include_student_age or lesson.student_key not in students:
            return lesson
        return replace(lesson, student_age=students[lesson.student_key].info.age)

    def _apply(
        self,
        lessons: list[Lesson],
        students: dict[str, StudentRecord],
        changes: list[Change],
        window_start: dt.date,
        window_end: dt.date,
        today: dt.date,
    ) -> None:
        kept = {k: v for k, v in self.state.lessons.items() if not window_start <= v.start.date() <= window_end}
        kept.update({lesson.id: lesson for lesson in lessons})
        self.state.lessons = kept
        self.state.students = students
        self.state.changes = self.state.changes + changes
        self.state.window_end = window_end
        prune(self.state, today)

    async def _finish_busy(self, exc: PlannerBusy, now: dt.datetime, reason: str, previous: RunInfo) -> RunInfo:
        log.warning("Planner busy: all sessions of the account are in use; keeping the previous schedule")
        self.retry_at = now + BUSY_RETRY if reason != "retry" else None
        self.state.run = replace(previous, at=now, status="busy", message=exc.message)
        self.store.save(self.state)
        return self.state.run

    async def _finish_error(self, message: str, now: dt.datetime, notify: bool = True) -> RunInfo:
        log.error("Fetch failed: %s", message)
        self.retry_at = None  # no retry before the next scheduled time (avoid locking the account)
        self.state.run = replace(self.state.run, at=now, status="error", message=message)
        self.store.save(self.state)
        if notify:
            t = Translator(await self.language())
            await self.ha.persistent_notification(t("error_title"), message, ERROR_NOTIFICATION_ID)
        return self.state.run

    async def _notify_changes(self, changes: list[Change], now: dt.datetime) -> None:
        relevant = to_notify(changes, now.date(), self.options.notify_changes_days, now.replace(tzinfo=None))
        if not relevant:
            return
        t = Translator(await self.language())
        lines = []
        for c in relevant[:MAX_NOTIFY_LINES]:
            if c.type == "added":
                lines.append(t("notify_added", lesson=one_line(c.lesson, t)))
            elif c.type == "removed":
                lines.append(t("notify_removed", lesson=one_line(c.lesson, t)))
            else:
                lines.append(t("notify_changed", lesson=one_line(c.lesson, t), before=when(c.before, t)))
        if len(relevant) > MAX_NOTIFY_LINES:
            lines.append("…")
        message = "\n".join(lines)
        if self.options.notify_service:
            await self.ha.notify(self.options.notify_service, t("notify_title"), message)
        else:
            await self.ha.persistent_notification(t("notify_title"), message, CHANGES_NOTIFICATION_ID)
        log.info("Change notification sent (%d changes)", len(relevant))

    # ------------------------------------------------------------------ outputs

    def calendar(self, lang: str) -> str:
        return build_calendar(self.state.lessons.values(), Translator(lang), self.tz, self.now(), "Instructor Radar")
