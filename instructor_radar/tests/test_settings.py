"""In-app settings (shared + per user) and the notifications they drive."""

import datetime as dt

import pytest
from aiohttp.test_utils import TestClient, TestServer
from multidict import MultiDict

from app.config import ConfigError
from app.settings import NotifyPrefs, SettingsStore, SharedSettings, from_legacy_options
from app.web.server import ui_app

from .conftest import NOW

AJAX = {"X-Requested-With": "fetch"}


# ------------------------------------------------------------------ shared settings


def test_shared_from_form():
    s = SharedSettings.from_form({"days_ahead": "21", "fetch_times": "22:00, 06:00;12:30", "include_student_name": "on"})
    assert s.days_ahead == 21
    assert s.fetch_times == (dt.time(6), dt.time(12, 30), dt.time(22))
    assert s.include_student_name and not s.include_student_age


@pytest.mark.parametrize("form", [{"days_ahead": "0", "fetch_times": "06:00"}, {"days_ahead": "x", "fetch_times": "06:00"},
                                  {"days_ahead": "14", "fetch_times": "6h"}, {"days_ahead": "14", "fetch_times": ""}])
def test_shared_from_form_rejects(form):
    with pytest.raises(ConfigError):
        SharedSettings.from_form(form)


def test_shared_store_roundtrip_and_broken_file(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    assert not store.exists() and store.load() == SharedSettings()
    store.save(SharedSettings(days_ahead=7, include_student_age=True))
    assert store.load() == SharedSettings(days_ahead=7, include_student_age=True)
    (tmp_path / "settings.json").write_text('{"days_ahead": 999, "fetch_times": ["bad"]}', encoding="utf-8")
    assert store.load() == SharedSettings()  # invalid values fall back to the defaults


def test_legacy_options_carried_over():
    raw = {"base_url": "https://x.invalid", "days_ahead": 10, "fetch_times": ["05:30"], "include_student_name": True,
           "notify_service": "notify.x"}
    assert from_legacy_options(raw) == SharedSettings(10, (dt.time(5, 30),), True, False)
    assert from_legacy_options({"base_url": "https://x.invalid"}) == SharedSettings()


# ------------------------------------------------------------------ per-user preferences


def test_notify_prefs_from_form_and_roundtrip():
    form = {"changes": "on", "changes_days": "3", "reminder": "on", "reminder_minutes": "45", "summary_time": "07:15"}
    prefs = NotifyPrefs.from_form(form, ["notify.mobile_app_b", "notify.mobile_app_a", "evil; drop"])
    assert prefs.devices == ("notify.mobile_app_a", "notify.mobile_app_b")
    assert prefs.changes and prefs.reminder and not prefs.summary
    assert prefs.reminder_minutes == 45 and prefs.summary_time == dt.time(7, 15)
    assert NotifyPrefs.from_dict(prefs.to_dict()) == prefs
    assert NotifyPrefs.from_dict(None).devices is None  # never saved


@pytest.mark.parametrize("bad", [{"changes_days": "0"}, {"reminder_minutes": "1"}, {"summary_time": "25:00"}])
def test_notify_prefs_rejects(bad):
    form = {"changes_days": "2", "reminder_minutes": "30", "summary_time": "06:30", **bad}
    with pytest.raises(ConfigError):
        NotifyPrefs.from_form(form, [])


# ------------------------------------------------------------------ reminders and summary


def _notifies(radar):
    return [c for c in radar.ha.calls if c[0] == "notify"]


async def test_reminder_once_and_never_too_late(make_radar):
    radar, _ = await make_radar()
    await radar.run()  # lessons: Mon 07/01 09:00, Tue 13:00, Thu 10:00
    radar.users.set_notify("u1", NotifyPrefs(devices=("notify.mobile_app_a",), changes=False, reminder=True,
                                             reminder_minutes=30))
    await radar.notifier.tick(NOW.replace(hour=8, minute=29))
    assert _notifies(radar) == []
    await radar.notifier.tick(NOW.replace(hour=8, minute=30))
    await radar.notifier.tick(NOW.replace(hour=8, minute=31))  # not twice
    sent = _notifies(radar)
    assert len(sent) == 1 and sent[0][1] == "mobile_app_a" and "30" in sent[0][2] and "09:00–11:00" in sent[0][3]
    # Tuesday 13:00 lesson: the add-on was down at 12:30 and comes back at 12:59 -> still sent;
    # Thursday 10:00: back only at 10:05 (after the start) -> skipped.
    await radar.notifier.tick(dt.datetime(2030, 1, 8, 12, 59, tzinfo=NOW.tzinfo))
    await radar.notifier.tick(dt.datetime(2030, 1, 10, 10, 5, tzinfo=NOW.tzinfo))
    assert len(_notifies(radar)) == 2


async def test_morning_summary(make_radar):
    radar, _ = await make_radar(include_student_name=True)
    await radar.run()
    radar.users.set_notify("u1", NotifyPrefs(devices=("notify.mobile_app_a",), changes=False, summary=True,
                                             summary_time=dt.time(6, 30)))
    radar.users.set_language("u1", "nl")
    await radar.notifier.tick(NOW.replace(hour=6, minute=45))
    await radar.notifier.tick(NOW.replace(hour=6, minute=50))
    sent = _notifies(radar)
    assert len(sent) == 1
    assert sent[0][2] == "Vandaag: 1 les(sen)" and sent[0][3].startswith("09:00 Les 11-12")
    assert "Testleerling Een" in sent[0][3]
    # Wednesday has no lessons: nothing is sent.
    await radar.notifier.tick(dt.datetime(2030, 1, 9, 6, 31, tzinfo=NOW.tzinfo))
    assert len(_notifies(radar)) == 1


async def test_summary_not_sent_when_too_late(make_radar):
    radar, _ = await make_radar()
    await radar.run()
    radar.users.set_notify("u1", NotifyPrefs(devices=("notify.mobile_app_a",), summary=True))
    await radar.notifier.tick(NOW.replace(hour=7, minute=1))  # 06:30 + 31 min
    assert _notifies(radar) == []


async def test_test_notification(make_radar):
    radar, _ = await make_radar()
    assert await radar.notifier.test("u1") == 0
    radar.users.set_notify("u1", NotifyPrefs(devices=("notify.mobile_app_a", "notify.mobile_app_b")))
    assert await radar.notifier.test("u1") == 2


# ------------------------------------------------------------------ Settings page


async def test_settings_page_and_saving(make_radar):
    radar, _ = await make_radar()
    async with TestClient(TestServer(ui_app(radar, addon_mode=False))) as client:
        html = await (await client.get("/settings", headers={"Accept-Language": "en"})).text()
        assert "For everyone" in html and "My notifications" in html
        # Nothing ticked by default: HA lists every user's phones.
        assert 'value="notify.mobile_app_dev_phone">' in html and 'value="notify.mobile_app_dev_tablet">' in html
        assert " checked> notify." not in html

        assert (await client.post("/settings/shared", data={"days_ahead": "7"})).status == 400  # no AJAX header
        resp = await client.post("/settings/shared", headers=AJAX,
                                 data={"days_ahead": "7", "fetch_times": "05:00, 23:00", "include_student_age": "on"})
        assert resp.status == 200 and (await resp.json())["ok"]
        assert radar.settings == SharedSettings(7, (dt.time(5), dt.time(23)), False, True)
        resp = await client.post("/settings/shared", headers=AJAX, data={"days_ahead": "7", "fetch_times": "nope"})
        assert resp.status == 400

        form = MultiDict([("devices", "notify.mobile_app_dev_phone"), ("devices", "notify.mobile_app_dev_tablet"),
                          ("changes", "on"), ("changes_days", "3"), ("reminder_minutes", "30"),
                          ("summary", "on"), ("summary_time", "06:45")])
        resp = await client.post("/settings/notify", headers=AJAX, data=form)
        assert resp.status == 200
        prefs = radar.users.notify("dev")
        assert prefs.devices == ("notify.mobile_app_dev_phone", "notify.mobile_app_dev_tablet")
        assert prefs.changes_days == 3 and prefs.summary and not prefs.reminder

        data = await (await client.post("/settings/test", headers=AJAX)).json()
        assert data["ok"] and "2" in data["message"]


async def test_settings_saved_in_addon_mode_need_a_user(make_radar):
    radar, _ = await make_radar()
    app = ui_app(radar, addon_mode=False)
    async with TestClient(TestServer(app)) as client:
        resp = await client.post("/settings/notify", headers={**AJAX, "X-Remote-User-Id": "bad id!"}, data={})
        assert resp.status == 403


async def test_status_bar_follows_new_fetch_times(make_radar):
    radar, _ = await make_radar()
    radar.update_settings(SharedSettings(fetch_times=(dt.time(7, 45),)))
    async with TestClient(TestServer(ui_app(radar, addon_mode=False))) as client:
        data = await (await client.get("/status", headers={"Accept-Language": "en"})).json()
    assert "07:45" in data["next"]
    assert NOW.hour == 7  # 07:45 is later today


async def test_settings_page_shows_samples(make_radar):
    radar, _ = await make_radar(include_student_name=True, include_student_age=True)
    async with TestClient(TestServer(ui_app(radar, addon_mode=False))) as client:
        html = await (await client.get("/settings", headers={"Accept-Language": "nl-BE"})).text()
    assert "Voorbeeld" in html
    assert "Over 30 min: Les 11-12" in html  # reminder sample
    assert "Vandaag: 3 les(sen)" in html and "14:50 Examen – B automaat – Centrum – Robin Fictief (24)" in html
