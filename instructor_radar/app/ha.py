"""Home Assistant through the Supervisor API (homeassistant_api: true)."""

from __future__ import annotations

import logging
import os
from typing import Protocol

import aiohttp

log = logging.getLogger(__name__)

ERROR_NOTIFICATION_ID = "instructor_radar_error"


class HomeAssistant(Protocol):
    async def language(self) -> str: ...

    async def persistent_notification(self, title: str, message: str, notification_id: str) -> None: ...

    async def dismiss_notification(self, notification_id: str) -> None: ...

    async def notify(self, service: str, title: str, message: str) -> None: ...


class SupervisorHomeAssistant:
    def __init__(self, token: str, base: str = "http://supervisor/core/api"):
        self._token = token
        self._base = base

    async def _call(self, domain: str, service: str, data: dict) -> None:
        url = f"{self._base}/services/{domain}/{service}"
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as http:
                async with http.post(url, json=data, headers=headers) as resp:
                    if resp.status >= 400:
                        log.warning("Home Assistant service %s.%s answered HTTP %d", domain, service, resp.status)
        except (aiohttp.ClientError, TimeoutError) as exc:
            log.warning("Home Assistant service %s.%s failed: %s", domain, service, type(exc).__name__)

    async def language(self) -> str:
        """Home Assistant's configured language (for notification texts); 'en' when unknown."""
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as http:
                async with http.get(f"{self._base}/config", headers={"Authorization": f"Bearer {self._token}"}) as r:
                    if r.status == 200:
                        return str((await r.json()).get("language") or "en")
        except (aiohttp.ClientError, TimeoutError, ValueError):
            pass
        return "en"

    async def persistent_notification(self, title: str, message: str, notification_id: str) -> None:
        await self._call(
            "persistent_notification", "create", {"title": title, "message": message, "notification_id": notification_id}
        )

    async def dismiss_notification(self, notification_id: str) -> None:
        await self._call("persistent_notification", "dismiss", {"notification_id": notification_id})

    async def notify(self, service: str, title: str, message: str) -> None:
        await self._call("notify", service, {"title": title, "message": message})


class FakeHomeAssistant:
    """Development / tests: records calls instead of sending them."""

    def __init__(self, lang: str = "nl"):
        self.calls: list[tuple] = []
        self.lang = lang

    async def language(self) -> str:
        return self.lang

    async def persistent_notification(self, title: str, message: str, notification_id: str) -> None:
        self.calls.append(("persistent_notification", title, message, notification_id))

    async def dismiss_notification(self, notification_id: str) -> None:
        self.calls.append(("dismiss", notification_id))

    async def notify(self, service: str, title: str, message: str) -> None:
        self.calls.append(("notify", service, title, message))


def from_environment() -> HomeAssistant:
    token = os.environ.get("SUPERVISOR_TOKEN")
    return SupervisorHomeAssistant(token) if token else FakeHomeAssistant()
