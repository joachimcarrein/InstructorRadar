"""Add-on options (/data/options.json, written by the Supervisor from config.yaml): the planner login only.

Everything else is set inside the app (see settings.py).
"""

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
    return Options(
        provider=str(raw.get("provider", "biqsdrive")),
        base_url=base_url,
        username=str(raw["username"]).strip(),
        password=str(raw["password"]),
        auth_mode=auth_mode,
        totp_secret=str(raw.get("totp_secret", "") or "").replace(" ", ""),
        log_level=str(raw.get("log_level", "info") or "info"),
    )


def load_raw(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"{path} not found") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} is not an object")
    return raw


def load_options(path: Path) -> Options:
    return parse_options(load_raw(path))
