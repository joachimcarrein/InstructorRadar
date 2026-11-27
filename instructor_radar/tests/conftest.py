"""Test helpers: a fake biqsDRIVE-like planner (synthetic data only) and a Radar wired to it."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from aiohttp import web

from app.config import Options
from app.ha import FakeHomeAssistant
from app.providers import get_provider
from app.store import Store
from app.sync import Radar

FIXTURES = Path(__file__).parent / "fixtures"
TZ = ZoneInfo("Europe/Brussels")
# Monday 7 January 2030, 07:00: the fixtures' lessons are in this week.
NOW = dt.datetime(2030, 1, 7, 7, 0, tzinfo=TZ)

# Personal data present in the fixtures that must never leave the provider.
SECRETS = [
    "0499 11 22 33", "0499112233", "0477998877", "0477 99 88 77", "Voorbeeldstraat", "Proefweg", "Fictiefstad",
    "Nergensdorp", "15032012", "12.03.15", "000-0000000", "example.invalid", "01|0001|2030", "01|0002|2030",
]
NAMES = ["Testleerling Een", "Testleerling Twee"]

LOGIN_PAGE = """<html><head><script src='https://www.google.com/recaptcha/api.js'></script></head><body>
<form method="post" role="login" action="login.php"><input id="b" type="hidden" name="b">
<input id="username" type="input" name="credential"><input id="password" type="password" name="password">
<input id="2fa" type="input" name="2fa"><button id="btnSubmit" type="submit" name="login">Aanmelden</button></form>
</body></html>"""


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def login_success(used: int = 0, maximum: int = 2) -> str:
    return (
        f"<html><script>// user data\n//maxusers:{maximum}\n//noofusers:{used}\n//isloggedin:0\n"
        "CookieUtil.set('__bdve-uuid', 'Basic ZmFrZTp0b2tlbg==');\nwindow.open('drive_calendar.php','_self');</script></html>"
    )


class FakePlanner:
    """mode: ok | bad_password | redirect_fail | busy | captcha | html_events | session_lost | slow"""

    def __init__(self, mode: str = "ok"):
        self.mode = mode
        self.logged_in = False
        self.calls: list[str] = []
        self.login_forms: list[dict] = []
        self.logouts = 0
        self.events = fixture("events.json")

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", self.handle)
        return app

    async def handle(self, request: web.Request) -> web.StreamResponse:
        path = request.path_qs
        self.calls.append(f"{request.method} {path}")
        if request.method == "GET" and request.path == "/":
            page = LOGIN_PAGE
            if self.mode == "captcha":
                page = page.replace("<form", '<div class="g-recaptcha" data-sitekey="x"></div><form')
            return web.Response(text=page, content_type="text/html")
        if request.path == "/login.php":
            form = dict(await request.post())
            self.login_forms.append(form)
            if self.mode == "bad_password":
                return web.Response(text=LOGIN_PAGE, content_type="text/html")
            if self.mode == "redirect_fail":
                raise web.HTTPFound("/?e=14")
            if self.mode == "busy":
                return web.Response(text=LOGIN_PAGE + "//maxusers:2\n//noofusers:2", content_type="text/html")
            self.logged_in = True
            return web.Response(text=login_success(), content_type="text/html")
        if request.path == "/logout.php":
            self.logouts += 1
            self.logged_in = False
            raise web.HTTPFound("/")
        if not self.logged_in:
            return web.json_response({"id": 403, "message": {"id": 403, "text": "not logged in"}}, status=403)
        if request.path == "/events.php":
            if self.mode == "html_events":
                return web.Response(text="<html>oops</html>", content_type="text/html")
            if self.mode == "session_lost":
                self.logged_in = False
                return web.json_response({"id": 403}, status=403)
            if self.mode == "slow":
                import asyncio

                await asyncio.sleep(5)
            return web.json_response(self.events)
        if path == "/php/crud_calendar.php?action=get_location":
            return web.json_response(fixture("locations.json"))
        if path == "/php/crud_customer.php?action=edit_customer":
            return web.Response(text=json.dumps(fixture("customer.json")), content_type="text/html")
        if path == "/php/crud_customer.php?action=get_customer_events":
            return web.Response(text=json.dumps(fixture("history.json")), content_type="text/html")
        return web.Response(status=404)


@pytest.fixture
def make_radar(aiohttp_server, tmp_path):
    async def factory(mode: str = "ok", **option_overrides):
        planner = FakePlanner(mode)
        server = await aiohttp_server(planner.app())
        options = Options(
            provider="biqsdrive",
            base_url=str(server.make_url("")).rstrip("/"),
            username="fake-user",
            password="fake-password",
            **option_overrides,
        )
        clock = {"now": NOW}
        radar = Radar(options, Store(tmp_path / "state.json"), FakeHomeAssistant(), get_provider("biqsdrive"), TZ,
                      clock=lambda: clock["now"])
        radar.test_clock = clock
        return radar, planner

    return factory
