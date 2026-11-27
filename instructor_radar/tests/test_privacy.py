"""Student personal data (phone, address, birthdate, national number, ...) never reaches the store, ICS, UI or logs."""

import logging

from aiohttp.test_utils import TestClient, TestServer

from app.web.server import calendar_app, ui_app

from .conftest import NAMES, SECRETS


def _unfold(ics: str) -> str:
    return ics.replace("\r\n ", "")


def _ics(radar) -> str:
    return _unfold(radar.calendar("nl"))


async def _everything(radar, caplog) -> str:
    """All outputs of the add-on concatenated: state file, ICS, every UI page and the logs."""
    parts = [radar.store.path.read_text(encoding="utf-8"), _ics(radar)]
    async with TestClient(TestServer(ui_app(radar, addon_mode=False))) as client:
        for path in ["/", "/changes", "/status"] + [f"/lesson/{i}" for i in radar.state.lessons]:
            resp = await client.get(path)
            assert resp.status == 200, path
            parts.append(await resp.text())
    async with TestClient(TestServer(calendar_app(radar, addon_mode=False))) as client:
        parts.append(_unfold(await (await client.get("/calendar.ics")).text()))
    parts.append(caplog.text)
    return "\n".join(parts)


async def test_names_off_nothing_personal_anywhere(make_radar, caplog):
    caplog.set_level(logging.DEBUG)
    radar, _ = await make_radar()
    run = await radar.run()
    assert run.status == "ok" and run.lessons == 3
    everything = await _everything(radar, caplog)
    for secret in SECRETS + NAMES:
        assert secret not in everything, secret
    assert all(r.info.name is None and r.info.age is None for r in radar.state.students.values())


async def test_names_on_shows_name_and_age_but_still_no_contact_data(make_radar, caplog):
    caplog.set_level(logging.DEBUG)
    radar, _ = await make_radar(include_student_name=True, include_student_age=True)
    await radar.run()
    everything = await _everything(radar, caplog)
    for secret in SECRETS:
        assert secret not in everything, secret
    assert "Testleerling Een" in _ics(radar)
    # Born 15/03/2012, lesson on 07/01/2030 -> 17.
    assert "Testleerling Een (17)" in _ics(radar)
    # Logs hold counts, never names.
    assert "Testleerling" not in caplog.text


async def test_switching_names_off_purges_stored_names(make_radar, tmp_path):
    radar, _ = await make_radar(include_student_name=True, include_student_age=True)
    await radar.run()
    assert "Testleerling" in radar.store.path.read_text(encoding="utf-8")

    from app.settings import SharedSettings

    radar.update_settings(SharedSettings(include_student_name=False, include_student_age=False))
    text = radar.store.path.read_text(encoding="utf-8")
    assert "Testleerling" not in text
    assert '"age": 17' not in text


async def test_login_token_never_logged(make_radar, caplog):
    caplog.set_level(logging.DEBUG)
    radar, _ = await make_radar()
    await radar.run()
    assert "Basic" not in caplog.text and "ZmFrZTp0b2tlbg" not in caplog.text
    assert "fake-password" not in caplog.text
