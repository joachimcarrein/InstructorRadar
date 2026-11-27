"""Entry point: `python -m app [--demo]`.

Add-on mode (SUPERVISOR_TOKEN present): options from /data/options.json, state in /data, ingress gate on.
Development (no token): options from $INSTRUCTOR_RADAR_DATA_DIR/options.json (or demo defaults with --demo),
fake Home Assistant, no gate.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiohttp import web

from . import __version__
from .config import ConfigError, Options, load_options, load_raw
from .ha import FakeHomeAssistant, from_environment
from .providers import get_provider
from .scheduler import is_fetch_command, next_run
from .settings import SettingsStore, SharedSettings, from_legacy_options
from .store import Store
from .sync import Radar
from .users import UserSettings
from .web.server import calendar_app, ui_app

UI_PORT = 8099
TICK = 30  # seconds
CALENDAR_PORT = 8100
log = logging.getLogger("instructor_radar")

LEVELS = {"trace": logging.DEBUG, "debug": logging.DEBUG, "info": logging.INFO, "warning": logging.WARNING,
          "error": logging.ERROR}


def _timezone() -> ZoneInfo:
    name = os.environ.get("TZ") or "UTC"
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _demo_options() -> Options:
    return Options(provider="demo", base_url="https://demo.invalid", username="demo", password="demo")  # noqa: S106


def _shared_settings(store: SettingsStore, data_dir: Path, demo: bool) -> SharedSettings:
    """Load the in-app settings; on the first start carry over the options of version 2026.11.0."""
    if store.exists():
        return store.load()
    if demo:
        settings = SharedSettings(include_student_name=True, include_student_age=True)
    else:
        try:
            settings = from_legacy_options(load_raw(data_dir / "options.json"))
        except ConfigError:
            settings = SharedSettings()
    store.save(settings)
    return settings


async def _scheduler(radar: Radar) -> None:
    """Every TICK: fetch when a fetch time passed (the times can change in Settings), then reminders/summaries."""
    since = radar.now()
    while True:
        await asyncio.sleep(TICK)
        now = radar.now()
        due = next_run(since, radar.settings.fetch_times) <= now
        retry = radar.retry_at is not None and radar.retry_at <= now
        since = now
        try:
            if due or retry:
                await radar.run("scheduled" if due else "retry")
            await radar.notifier.tick(radar.now())
        except Exception:  # noqa: BLE001 - the loop must survive anything
            log.exception("Scheduler error")


async def _stdin(radar: Radar) -> None:
    """hassio.addon_stdin: any 'fetch' line triggers a fetch (same rate limit as the UI button)."""
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            return  # stdin closed
        if not is_fetch_command(line):
            log.warning("Ignored stdin input (expected 'fetch')")
            continue
        result = radar.manual_request()
        if result == "started":
            await radar.run("stdin")
        else:
            log.info("Fetch via stdin not started: %s", result)


async def main() -> None:
    parser = argparse.ArgumentParser(prog="instructor_radar")
    parser.add_argument("--demo", action="store_true", help="synthetic planner data (development, CI)")
    args = parser.parse_args()

    addon_mode = bool(os.environ.get("SUPERVISOR_TOKEN"))
    data_dir = Path("/data") if addon_mode else Path(os.environ.get("INSTRUCTOR_RADAR_DATA_DIR", ".devdata"))
    data_dir.mkdir(parents=True, exist_ok=True)

    try:
        options = _demo_options() if args.demo else load_options(data_dir / "options.json")
    except ConfigError as exc:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        log.error("Configuration problem: %s", exc)
        raise SystemExit(1) from None

    logging.basicConfig(level=LEVELS.get(options.log_level, logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)  # URLs may carry lesson ids
    tz = _timezone()
    ha = FakeHomeAssistant() if args.demo else from_environment()
    settings_store = SettingsStore(data_dir / "settings.json")
    radar = Radar(options, Store(data_dir / "state.json"), ha, get_provider(options.provider), tz,
                  users=UserSettings(data_dir / "users.json"),
                  settings=_shared_settings(settings_store, data_dir, args.demo))
    radar.settings_store = settings_store
    log.info("Instructor Radar %s, provider %s, time zone %s, fetch times %s", __version__, options.provider, tz.key,
             ", ".join(t.strftime("%H:%M") for t in radar.settings.fetch_times))

    runners = []
    for app, port in ((ui_app(radar, addon_mode), UI_PORT), (calendar_app(radar, addon_mode), CALENDAR_PORT)):
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", port).start()  # noqa: S104 - container; gated by source address
        runners.append(runner)

    tasks = [asyncio.create_task(_scheduler(radar))]
    if not sys.stdin.isatty():
        tasks.append(asyncio.create_task(_stdin(radar)))
    if args.demo or radar.state.run.status == "never":
        # Very first start (or demo): fetch once so the UI is not empty. Never repeated on restarts, so a restart
        # loop cannot hammer the planner's login.
        tasks.append(asyncio.create_task(radar.run("startup")))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):  # Windows development
            pass
    try:
        await stop.wait()
    finally:
        # Let a running fetch finish (and log out) before stopping, so no planner session is left open.
        if radar.running:
            log.info("Waiting for the running fetch to finish")
            try:
                async with asyncio.timeout(20):
                    async with radar._lock:
                        pass
            except TimeoutError:
                log.warning("Stopped during a fetch")
        for task in tasks:
            task.cancel()
        for runner in runners:
            await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
