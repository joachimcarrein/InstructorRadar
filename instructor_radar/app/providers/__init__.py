"""Planner providers. One module per planner; the add-on option `provider` selects one from the registry.

Adding a provider = adding a module with a class implementing `Provider` and registering it in `_REGISTRY`.

Rules for every provider:
- Hold the planner session as briefly as possible: the caller does login -> fetch -> logout in one go, without
  keep-alive or session reuse between runs (planners limit simultaneous sessions per user).
- Drop student personal data (phone, address, e-mail, birthdate, national number, ...) inside the provider: only the
  fields of `app.models` may leave it.
- Never log lesson or student details; counts only.
- Only call read-only endpoints.
"""

from __future__ import annotations

import datetime as dt
import importlib
from dataclasses import dataclass, field
from typing import Protocol

import aiohttp

from ..models import Lesson, StudentInfo


class ProviderError(Exception):
    """Base class. `message` is shown in the log and the app's status banner and must hold no personal data."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class LoginFailed(ProviderError):
    """Credentials, 2FA or account state refused. Never retried before the next scheduled run (avoid account lock)."""


class CaptchaRequired(ProviderError):
    """The planner asks for a captcha: automated login is impossible until a person logs in in a browser."""


class UnexpectedResponse(ProviderError):
    """HTML where JSON was expected, unknown status, changed page layout, ..."""


class NotLoggedIn(UnexpectedResponse):
    """The planner answered 'not logged in' in the middle of a run (session ended or taken over)."""


class PlannerBusy(ProviderError):
    """All sessions of the account are in use. Not an error of the add-on: keep the old data and try again later."""


@dataclass(frozen=True)
class FetchSettings:
    include_student_name: bool = False
    include_student_age: bool = False


@dataclass
class PlannerSession:
    """State of one run. Created fresh for every run and discarded afterwards."""

    http: aiohttp.ClientSession
    base_url: str
    settings: FetchSettings = field(default_factory=FetchSettings)
    # Provider-private state for this run only (e.g. opaque student key -> planner id). Never persisted.
    private: dict = field(default_factory=dict)
    request_count: int = 0


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str = field(repr=False)
    auth_mode: str = "none"  # none | totp | manual
    totp_secret: str = field(default="", repr=False)


class Provider(Protocol):
    name: str

    async def login(self, session: PlannerSession, credentials: Credentials) -> None: ...

    async def fetch_events(self, session: PlannerSession, start: dt.date, end: dt.date) -> list[Lesson]: ...

    async def fetch_student(self, session: PlannerSession, student_key: str, today: dt.date) -> StudentInfo: ...

    async def logout(self, session: PlannerSession) -> None: ...


# option value -> "module:Class" (module relative to this package)
_REGISTRY: dict[str, str] = {
    "biqsdrive": "biqsdrive:BiqsDriveProvider",
    "demo": "demo:DemoProvider",  # synthetic data for development, CI and screenshots (--demo); not an add-on option
}


def available() -> list[str]:
    return sorted(_REGISTRY)


def get_provider(name: str) -> Provider:
    try:
        target = _REGISTRY[name]
    except KeyError:
        raise ValueError(f"Unknown provider '{name}'. Available: {', '.join(available())}") from None
    module_name, class_name = target.split(":")
    module = importlib.import_module(f"{__name__}.{module_name}")
    return getattr(module, class_name)()
