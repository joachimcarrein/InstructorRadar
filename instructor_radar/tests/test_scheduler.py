import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from app.config import ConfigError, parse_fetch_times, parse_options
from app.scheduler import BUSY_RETRY, is_fetch_command, manual_allowed, next_run

TZ = ZoneInfo("Europe/Brussels")


def test_parse_fetch_times_sorts_and_dedupes():
    assert parse_fetch_times(["22:00", "06:00", "06:00"]) == (dt.time(6), dt.time(22))


@pytest.mark.parametrize("bad", ["6:00", "24:00", "12:60", "noon", "", "06:00:00"])
def test_parse_fetch_times_rejects(bad):
    with pytest.raises(ConfigError):
        parse_fetch_times([bad])


def test_parse_fetch_times_needs_one():
    with pytest.raises(ConfigError):
        parse_fetch_times([])


def test_next_run_later_today():
    now = dt.datetime(2030, 1, 7, 12, 0, tzinfo=TZ)
    assert next_run(now, (dt.time(6), dt.time(22))) == dt.datetime(2030, 1, 7, 22, 0, tzinfo=TZ)


def test_next_run_tomorrow():
    now = dt.datetime(2030, 1, 7, 22, 30, tzinfo=TZ)
    assert next_run(now, (dt.time(6), dt.time(22))) == dt.datetime(2030, 1, 8, 6, 0, tzinfo=TZ)


def test_next_run_exactly_now_is_next_slot():
    now = dt.datetime(2030, 1, 7, 6, 0, tzinfo=TZ)
    assert next_run(now, (dt.time(6), dt.time(22))) == dt.datetime(2030, 1, 7, 22, 0, tzinfo=TZ)


def test_manual_rate_limit():
    now = dt.datetime(2030, 1, 7, 12, 0, tzinfo=TZ)
    assert manual_allowed(None, now)
    assert not manual_allowed(now - dt.timedelta(seconds=30), now)
    assert manual_allowed(now - dt.timedelta(minutes=5), now)
    assert BUSY_RETRY == dt.timedelta(minutes=15)


@pytest.mark.parametrize("line", ["fetch", "fetch\n", '"fetch"', '{"action": "fetch"}', "FETCH_NOW"])
def test_stdin_fetch_commands(line):
    assert is_fetch_command(line)


@pytest.mark.parametrize("line", ["", "restart", '{"action": "delete"}'])
def test_stdin_other_input(line):
    assert not is_fetch_command(line)


def _raw(**kw):
    base = {"base_url": "https://school.example.invalid", "username": "u", "password": "p"}
    return {**base, **kw}


def test_options_defaults():
    o = parse_options(_raw())
    assert o.fetch_times == (dt.time(6), dt.time(22))
    assert o.days_ahead == 14 and o.notify_changes_days == 2
    assert not o.include_student_name and not o.include_student_age


def test_options_strip_notify_prefix():
    assert parse_options(_raw(notify_service="notify.mobile_app_phone")).notify_service == "mobile_app_phone"


@pytest.mark.parametrize(
    "bad",
    [
        {"base_url": "http://school.example.invalid"},
        {"auth_mode": "sms"},
        {"auth_mode": "totp"},
        {"days_ahead": 0},
        {"notify_changes_days": 30},
        {"notify_service": "notify.Bad Name"},
        {"password": ""},
    ],
)
def test_options_rejected(bad):
    with pytest.raises(ConfigError):
        parse_options(_raw(**bad))


def test_password_not_in_repr():
    o = parse_options(_raw(password="hunter2-secret", auth_mode="totp", totp_secret="JBSWY3DPEHPK3PXP"))
    assert "hunter2-secret" not in repr(o) and "JBSWY3DPEHPK3PXP" not in repr(o)
