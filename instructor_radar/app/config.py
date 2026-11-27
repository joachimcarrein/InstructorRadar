"""Add-on options (/data/options.json, written by the Supervisor from config.yaml)."""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
AUTH_MODES = ("none", "totp", "manual")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Options:
    provider: str = "biqsdrive"
    base_url: str = ""
    username: str = ""
    password: str = field(default="", repr=False)
    auth_mode: str = "none"
    totp_secret: str = field(default="", repr=False)
    days_ahead: int = 14
    fetch_times: tuple[dt.time, ...] = (dt.time(6, 0), dt.time(22, 0))
    include_student_name: bool = False
    include_student_age: bool = False
    notify_changes_days: int = 2
    notify_service: str = ""
    log_level: str = "info"


def parse_fetch_times(values: list[str] | tuple[str, ...]) -> tuple[dt.time, ...]:
    """'HH:MM' strings -> sorted, de-duplicated times. Raises ConfigError on anything else."""
    times = set()
    for raw in values:
        m = TIME_RE.match(str(raw).strip())
        if not m:
            raise ConfigError(f"fetch_times: '{raw}' is not a time like 06:00")
        times.add(dt.time(int(m.group(1)), int(m.group(2))))
    if not times:
        raise ConfigError("fetch_times: at least one time is required")
    return tuple(sorted(times))


def parse_options(raw: dict) -> Options:
    base_url = str(raw.get("base_url", "")).strip().rstrip("/")
    if not re.match(r"^https://[A-Za-z0-9.-]+(:\d+)?(/.*)?$", base_url):
        raise ConfigError("base_url must be the https address of your driving school's planner")
    auth_mode = str(raw.get("auth_mode", "none"))
    if auth_mode not in AUTH_MODES:
        raise ConfigError(f"auth_mode must be one of {', '.join(AUTH_MODES)}")
    if auth_mode == "totp" and not str(raw.get("totp_secret", "")).strip():
        raise ConfigError("auth_mode totp needs totp_secret")
    if not str(raw.get("username", "")).strip() or not str(raw.get("password", "")):
        raise ConfigError("username and password are required")
    days = int(raw.get("days_ahead", 14))
    notify_days = int(raw.get("notify_changes_days", 2))
    if not 1 <= days <= 60:
        raise ConfigError("days_ahead must be between 1 and 60")
    if not 0 <= notify_days <= 14:
        raise ConfigError("notify_changes_days must be between 0 and 14")
    service = str(raw.get("notify_service", "") or "").strip()
    if service.startswith("notify."):
        service = service[len("notify."):]
    if service and not re.match(r"^[a-z0-9_]+$", service):
        raise ConfigError("notify_service must look like notify.mobile_app_my_phone")
    return Options(
        provider=str(raw.get("provider", "biqsdrive")),
        base_url=base_url,
        username=str(raw["username"]).strip(),
        password=str(raw["password"]),
        auth_mode=auth_mode,
        totp_secret=str(raw.get("totp_secret", "") or "").replace(" ", ""),
        days_ahead=days,
        fetch_times=parse_fetch_times(raw.get("fetch_times") or ["06:00", "22:00"]),
        include_student_name=bool(raw.get("include_student_name", False)),
        include_student_age=bool(raw.get("include_student_age", False)),
        notify_changes_days=notify_days,
        notify_service=service,
        log_level=str(raw.get("log_level", "info") or "info"),
    )


def load_options(path: Path) -> Options:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"{path} not found") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON") from exc
    return parse_options(raw)
