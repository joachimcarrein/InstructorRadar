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
from .diff import Change, diff
from .ha import ERROR_NOTIFICATION_ID, HomeAssistant
from .i18n import Translator
from .ics import build_calendar
from .models import Lesson, StudentInfo
from .notifier import Notifier
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
from .settings import SharedSettings
from .store import RunInfo, State, Store, StudentRecord, apply_privacy, prune, week_start
from .users import UserSettings

log = logging.getLogger(__name__)

RUN_TIMEOUT = 60  # seconds for the whole planner conversation (logout excluded)
REQUEST_TIMEOUT = 20
LOGOUT_TIMEOUT = 10
MAX_STUDENTS_PER_RUN = 40
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
        settings: SharedSettings | None = None,
    ):
        self.options = options
        self.settings = settings or SharedSettings()
        self.settings_store = None  # set by __main__; the Settings page saves through it
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
            prune(store.load(), self.now().date()), self.settings.include_student_name, self.settings.include_student_age
        )
        self.notifier = Notifier(self)

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
        window_start, window_end = week_start(today), today + dt.timedelta(days=self.settings.days_ahead)
        previous = self.state.run
        started = time.monotonic()
        session = PlannerSession(
            http=aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                headers={"User-Agent": USER_AGENT},
                cookie_jar=aiohttp.CookieJar(),
            ),
            base_url=self.options.base_url,
            settings=FetchSettings(self.settings.include_student_name, self.settings.include_student_age),
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
                    changes = diff(self.state.lessons, lessons, window_start, window_end, now, self.state.window_end)
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
        """Fetch history (name, age) for students that are new, changed, not refreshed today, or fetched without the
        name/age that is switched on now."""
        students = {k: v for k, v in self.state.students.items()}
        keys = sorted({lesson.student_key for lesson in lessons if lesson.student_key})
        changed = {c.lesson.student_key for c in changes}
        want_name, want_age = self.settings.include_student_name, self.settings.include_student_age
        todo = [
            k
            for k in keys
            if k not in students
            or students[k].refreshed < today
            or k in changed
            or (want_name and not students[k].with_name)  # names switched on after this student was fetched
            or (want_age and not students[k].with_age)
        ]
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
            students[key] = StudentRecord(info=info, refreshed=today, with_name=want_name, with_age=want_age)
            refreshed += 1
        return students, refreshed

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
        await self.notifier.changes(changes, now)

    def update_settings(self, settings: SharedSettings) -> None:
        """Apply new shared settings; switching names/ages off removes them from the stored state right away."""
        self.settings = settings
        self.state = apply_privacy(self.state, settings.include_student_name, settings.include_student_age)
        self.store.save(self.state)
        if self.settings_store is not None:
            self.settings_store.save(settings)

    # ------------------------------------------------------------------ outputs

    def calendar(self, lang: str) -> str:
        return build_calendar(
            self.state.lessons.values(), Translator(lang), self.tz, self.now(), "Instructor Radar", self.who
        )

    def student(self, lesson: Lesson) -> StudentInfo | None:
        record = self.state.students.get(lesson.student_key) if lesson.student_key else None
        return record.info if record else None

    def who(self, lesson: Lesson) -> str:
        """The student label of a lesson ('Name (18)'), following the current name/age settings; '' when off."""
        info = self.student(lesson)
        return info.label(self.settings.include_student_name, self.settings.include_student_age) if info else ""
