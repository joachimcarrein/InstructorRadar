"""HTTP: the ingress UI (port 8099) and the internal calendar feed (port 8100, not mapped to the host)."""

from __future__ import annotations

import asyncio
import datetime as dt
import ipaddress
import logging
import time
from pathlib import Path

import jinja2
from aiohttp import web

from .. import __version__
from ..config import ConfigError
from ..i18n import Translator, language_names, pick_language
from ..models import HistoryEntry, Kind, Lesson, StudentInfo
from ..notifier import notification_samples
from ..present import kind_label, licence_label
from ..scheduler import next_run
from ..settings import NotifyPrefs, SharedSettings
from ..store import week_start
from ..sync import Radar
from ..users import UserSettings

log = logging.getLogger(__name__)

HERE = Path(__file__).parent
SUPERVISOR = ipaddress.ip_address("172.30.32.2")
HASSIO_NETWORK = ipaddress.ip_network("172.30.32.0/23")
RADAR = web.AppKey("radar", Radar)
ADDON_MODE = web.AppKey("addon_mode", bool)
TASKS = web.AppKey("tasks", set)
DAY_START_HOUR, DAY_END_HOUR = 7, 21
RECENT_CHANGE = dt.timedelta(hours=36)

_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(HERE / "templates"),
    autoescape=jinja2.select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _remote_ip(request: web.Request):
    try:
        return ipaddress.ip_address((request.remote or "").split("%")[0])
    except ValueError:
        return None


def _gate(allowed) -> web.middleware:
    @web.middleware
    async def gate(request: web.Request, handler):
        ip = _remote_ip(request)
        if request.app[ADDON_MODE]:
            ok = ip is not None and (allowed(ip) or (ip.is_loopback and request.path == "/healthz"))
            if not ok:
                raise web.HTTPForbidden()
        return await handler(request)

    return gate


@web.middleware
async def security_headers(request: web.Request, handler):
    response = await handler(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; frame-ancestors 'self'",
    )
    return response


def _user_id(request: web.Request) -> str | None:
    """The Home Assistant user (ingress header). In development there is one user, 'dev'."""
    user = request.headers.get("X-Remote-User-Id") or (None if request.app[ADDON_MODE] else "dev")
    return user if UserSettings.valid(user) else None


def _ctx(request: web.Request) -> dict:
    radar = request.app[RADAR]
    user = _user_id(request)
    chosen = radar.users.language(user) if radar.users and user else ""
    t = Translator(chosen or pick_language(request.headers.get("Accept-Language")))
    if radar.users and user and request.method == "GET":
        radar.users.seen(user, t.lang, int(time.time()))
    prefix = request.headers.get("X-Ingress-Path", "").rstrip("/")
    if ".." in prefix or (prefix and not prefix.startswith("/")):
        prefix = ""
    return {
        "t": t,
        "base": prefix + "/",
        "radar": radar,
        "version": __version__,
        "languages": language_names(),
        "chosen_language": chosen,
        "can_choose_language": bool(radar.users and user),
    }


def _render(name: str, **ctx) -> web.Response:
    return web.Response(text=_env.get_template(name).render(**ctx), content_type="text/html", charset="utf-8")


# ---------------------------------------------------------------------- view helpers


def _hours(minutes: int) -> str:
    return f"{minutes // 60}:{minutes % 60:02d}"


def _familiarity(info: StudentInfo | None, lesson: Lesson) -> str:
    if info is None or lesson.kind != Kind.LESSON:
        return ""
    return info.familiarity(lesson.start)


def _is_this_lesson(h: HistoryEntry, lesson: Lesson, this_start: str) -> bool:
    """By the planner's id (the exam and its drive back share one); by date and time for rows without one."""
    if h.event_id:
        return h.event_id == lesson.id.split("#")[0]
    return h.date == lesson.start.date() and (h.start == this_start or h.start < this_start < h.end)


def _recently_changed(radar: Radar) -> set[str]:
    cutoff = radar.now() - RECENT_CHANGE
    return {c.lesson.id for c in radar.state.changes if c.type != "removed" and c.detected >= cutoff}


def _card(lesson: Lesson, radar: Radar, t: Translator, changed: set[str]) -> dict:
    familiarity = _familiarity(radar.student(lesson), lesson)
    start_h = lesson.start.hour + lesson.start.minute / 60
    end_h = max(start_h + 0.25, (lesson.end - lesson.start).total_seconds() / 3600 + start_h)
    span = DAY_END_HOUR - DAY_START_HOUR
    top = max(0.0, (start_h - DAY_START_HOUR) / span * 100)
    height = max(3.0, (min(end_h, DAY_END_HOUR) - max(start_h, DAY_START_HOUR)) / span * 100)
    return {
        "lesson": lesson,
        "time": f"{lesson.start:%H:%M}–{lesson.end:%H:%M}",
        "label": kind_label(lesson, t),
        "gear": lesson.transmission.value,
        "gear_label": t(lesson.transmission.value),
        "student": radar.who(lesson),
        "familiarity": familiarity,
        "changed": lesson.id in changed,
        "top": f"{top:.2f}",
        "height": f"{height:.2f}",
        "exam": lesson.kind == Kind.EXAM,
        "other": lesson.kind == Kind.OTHER,
    }


def _status(radar: Radar, t: Translator) -> dict:
    run = radar.state.run
    nxt = radar.retry_at or next_run(radar.now(), radar.settings.fetch_times)
    return {
        "code": run.status,
        "label": t(f"status_{run.status}"),
        "message": run.message,
        "last": t("last_fetch", when=f"{run.last_success:%d/%m %H:%M}") if run.last_success else t("never_fetched"),
        "next": t("next_fetch", when=f"{t.weekdays[nxt.weekday()]} {nxt:%H:%M}"),
        "running": radar.running,
    }


# ---------------------------------------------------------------------- handlers


async def week(request: web.Request) -> web.Response:
    c = _ctx(request)
    radar, t = c["radar"], c["t"]
    today = radar.now().date()
    try:
        monday = week_start(dt.date.fromisoformat(request.query.get("week", "")))
    except ValueError:
        monday = week_start(today)
    first, last = week_start(today), week_start(radar.state.window_end or today)
    monday = min(max(monday, first), last)
    changed = _recently_changed(radar)
    days = []
    for i in range(7):
        day = monday + dt.timedelta(days=i)
        lessons = sorted((x for x in radar.state.lessons.values() if x.start.date() == day), key=lambda x: x.start)
        days.append(
            {
                "date": day,
                "name": t.weekdays[i],
                "today": day == today,
                "cards": [_card(x, radar, t, changed) for x in lessons],
            }
        )
    hide_weekend = not any(d["cards"] for d in days[5:])
    return _render(
        "week.html",
        **c,
        days=days[:5] if hide_weekend else days,
        week_number=monday.isocalendar().week,
        monday=monday,
        prev=(monday - dt.timedelta(days=7)).isoformat() if monday > first else None,
        next=(monday + dt.timedelta(days=7)).isoformat() if monday < last else None,
        is_current=monday == first,
        hours=list(range(DAY_START_HOUR, DAY_END_HOUR + 1)),
        status=_status(radar, t),
        page="week",
    )


async def lesson_detail(request: web.Request) -> web.Response:
    c = _ctx(request)
    radar, t = c["radar"], c["t"]
    lesson = radar.state.lessons.get(request.match_info["id"])
    if lesson is None:
        raise web.HTTPNotFound()
    info = radar.student(lesson)
    history, practice, lesson_total = None, "", ""
    if info is not None:
        this_start = f"{lesson.start:%H:%M}"
        history = [
            {"entry": h, "current": _is_this_lesson(h, lesson, this_start)}
            for h in sorted(info.history, key=lambda h: (h.date, h.start), reverse=True)
        ]
        done, coming = info.lesson_counts()
        if done or coming:
            lesson_total = t("practice_detail", total=done + coming, driven=done, planned=coming)
        driven, planned = info.practice_minutes()
        if driven or planned:
            practice = t("practice_detail", total=_hours(driven + planned), driven=_hours(driven), planned=_hours(planned))
    return _render(
        "lesson.html",
        **c,
        lesson=lesson,
        card=_card(lesson, radar, t, _recently_changed(radar)),
        licence=licence_label(lesson, t),
        history=history,
        practice=practice,
        lesson_total=lesson_total,
        weekday=t.weekdays[lesson.start.weekday()],
    )


async def changes(request: web.Request) -> web.Response:
    c = _ctx(request)
    radar, t = c["radar"], c["t"]
    items = []
    for ch in sorted(radar.state.changes, key=lambda x: x.detected, reverse=True):
        items.append(
            {
                "change": ch,
                "type_label": t(ch.type),
                "when": f"{t.weekdays[ch.lesson.start.weekday()]} {ch.lesson.start:%d/%m %H:%M}–{ch.lesson.end:%H:%M}",
                "label": kind_label(ch.lesson, t),
                "licence": licence_label(ch.lesson, t),
                "student": radar.who(ch.lesson),
                "before": (
                    f"{t.weekdays[ch.before.start.weekday()]} {ch.before.start:%d/%m %H:%M}–{ch.before.end:%H:%M}"
                    f" · {ch.before.location}"
                )
                if ch.before
                else "",
                "detected": f"{t.weekdays[ch.detected.weekday()]} {ch.detected:%d/%m %H:%M}",
            }
        )
    return _render("changes.html", **c, items=items, status=_status(radar, t), page="changes")


async def fetch_now(request: web.Request) -> web.Response:
    if request.headers.get("X-Requested-With") != "fetch":
        raise web.HTTPBadRequest()
    radar = request.app[RADAR]
    t = _ctx(request)["t"]
    result = radar.manual_request()
    if result == "started":
        task = asyncio.create_task(radar.run("manual"))
        request.app[TASKS].add(task)
        task.add_done_callback(request.app[TASKS].discard)
    messages = {"started": t("fetch_started"), "running": t("fetch_running"), "too_soon": t("fetch_too_soon")}
    return web.json_response({"result": result, "message": messages[result]})


async def settings_page(request: web.Request) -> web.Response:
    c = _ctx(request)
    radar, t = c["radar"], c["t"]
    user = _user_id(request)
    prefs = radar.users.notify(user) if radar.users and user else NotifyPrefs()
    services = await radar.ha.notify_services()
    # Nothing is ticked until the user chooses: Home Assistant lists every user's phones, and a careless Save must
    # not subscribe them all.
    selected = set(prefs.devices or ())
    sample_reminder, sample_summary = notification_samples(t, radar.settings)
    return _render(
        "settings.html",
        sample_reminder=sample_reminder,
        sample_summary=sample_summary,
        **c,
        shared=radar.settings,
        fetch_times=", ".join(x.strftime("%H:%M") for x in radar.settings.fetch_times),
        prefs=prefs,
        services=services,
        selected=selected,
        can_notify=bool(radar.users and user),
        status=_status(radar, t),
        page="settings",
    )


def _ajax(request: web.Request) -> None:
    if request.headers.get("X-Requested-With") != "fetch":
        raise web.HTTPBadRequest()


async def save_shared(request: web.Request) -> web.Response:
    _ajax(request)
    t = _ctx(request)["t"]
    form = await request.post()
    try:
        settings = SharedSettings.from_form(form)
    except ConfigError as exc:
        return web.json_response({"ok": False, "message": t("invalid_value", detail=str(exc))}, status=400)
    request.app[RADAR].update_settings(settings)
    log.info("Shared settings saved")
    return web.json_response({"ok": True, "message": t("saved")})


async def save_notify(request: web.Request) -> web.Response:
    _ajax(request)
    radar, user = request.app[RADAR], _user_id(request)
    if radar.users is None or user is None:
        raise web.HTTPForbidden()
    t = _ctx(request)["t"]
    form = await request.post()
    try:
        prefs = NotifyPrefs.from_form(form, [str(x) for x in form.getall("devices", [])])
    except ConfigError as exc:
        return web.json_response({"ok": False, "message": t("invalid_value", detail=str(exc))}, status=400)
    radar.users.set_notify(user, prefs)
    log.info("Notification settings saved (%d devices)", len(prefs.devices or ()))
    return web.json_response({"ok": True, "message": t("saved")})


async def send_test(request: web.Request) -> web.Response:
    _ajax(request)
    radar, user = request.app[RADAR], _user_id(request)
    if radar.users is None or user is None:
        raise web.HTTPForbidden()
    t = _ctx(request)["t"]
    count = await radar.notifier.test(user)
    return web.json_response({"ok": count > 0, "message": t("test_sent", count=count) if count else t("test_none")})


async def set_language(request: web.Request) -> web.Response:
    if request.headers.get("X-Requested-With") != "fetch":
        raise web.HTTPBadRequest()
    radar, user = request.app[RADAR], _user_id(request)
    if radar.users is None or user is None:
        raise web.HTTPForbidden()
    data = await request.post()
    try:
        radar.users.set_language(user, str(data.get("language", "")))
    except ValueError:
        raise web.HTTPBadRequest() from None
    return web.json_response({"ok": True})


async def status(request: web.Request) -> web.Response:
    c = _ctx(request)
    return web.json_response(_status(c["radar"], c["t"]))


async def healthz(request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def calendar(request: web.Request) -> web.Response:
    radar = request.app[RADAR]
    body = radar.calendar(await radar.language())
    return web.Response(
        text=body,
        content_type="text/calendar",
        charset="utf-8",
        headers={"Cache-Control": "no-store", "Content-Disposition": 'inline; filename="instructor-radar.ics"'},
    )


# ---------------------------------------------------------------------- apps


def ui_app(radar: Radar, addon_mode: bool) -> web.Application:
    app = web.Application(middlewares=[_gate(lambda ip: ip == SUPERVISOR), security_headers])
    app[RADAR] = radar
    app[ADDON_MODE] = addon_mode
    app[TASKS] = set()
    app.router.add_get("/", week)
    app.router.add_get("/lesson/{id}", lesson_detail)
    app.router.add_get("/changes", changes)
    app.router.add_post("/fetch", fetch_now)
    app.router.add_post("/language", set_language)
    app.router.add_get("/settings", settings_page)
    app.router.add_post("/settings/shared", save_shared)
    app.router.add_post("/settings/notify", save_notify)
    app.router.add_post("/settings/test", send_test)
    app.router.add_get("/status", status)
    app.router.add_get("/healthz", healthz)
    app.router.add_static("/static/", HERE / "static", append_version=True)
    return app


def calendar_app(radar: Radar, addon_mode: bool) -> web.Application:
    # Home Assistant Core reaches add-ons over the internal hassio network; nothing else may read the feed.
    app = web.Application(middlewares=[_gate(lambda ip: ip in HASSIO_NETWORK or ip.is_loopback)])
    app[RADAR] = radar
    app[ADDON_MODE] = addon_mode
    app.router.add_get("/calendar.ics", calendar)
    app.router.add_get("/healthz", healthz)
    return app
