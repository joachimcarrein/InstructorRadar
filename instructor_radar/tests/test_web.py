import re

from aiohttp.test_utils import TestClient, TestServer

from app.web.server import calendar_app, ui_app


async def test_week_page_renders_cards_and_badges(make_radar):
    radar, _ = await make_radar(include_student_name=True)
    await radar.run()
    async with TestClient(TestServer(ui_app(radar, addon_mode=False))) as client:
        resp = await client.get("/", headers={"Accept-Language": "nl-BE,nl;q=0.9", "X-Ingress-Path": "/api/hassio_ingress/abc"})
        html = await resp.text()
    assert resp.status == 200
    assert "Les 11-12" in html and "Examen" in html and "Automaat" in html
    assert "Testleerling Een" in html
    # Every local URL carries the ingress prefix.
    assert 'href="/api/hassio_ingress/abc/static/app.css' in html
    assert not re.search(r'(href|src)="/(?!api/hassio_ingress/abc)', html)
    assert "style=" not in html  # CSP: no inline styles


async def test_lesson_detail_and_404(make_radar):
    radar, _ = await make_radar()
    await radar.run()
    async with TestClient(TestServer(ui_app(radar, addon_mode=False))) as client:
        resp = await client.get("/lesson/9001", headers={"Accept-Language": "en"})
        html = await resp.text()
        assert resp.status == 200
        assert "Lessons" in html and "Andere Collega" in html and "Cancelled: Ziek" in html
        # Future lessons are listed too and the opened lesson is marked; hours from the history:
        # done 02/12 (2:00) + 16/12 (no end = 0:00); planned 07/01 09:00-11:00 is this lesson (2:00).
        assert "this lesson" in html
        # The exam and its drive back are one entry, with the result; exams do not count as driving hours.
        assert html.count("Exam 1") == 1 and "Not passed" in html
        assert "Driving hours" in html and "4:00 (2:00 driven, 2:00 planned)" in html
        # Lessons 1-2 and 3-4 done (3-4 on 09/12 was cancelled, 16/12 counts), 11-12 planned.
        assert "Number of lessons" in html and "6 (4 driven, 2 planned)" in html
        assert (await client.get("/lesson/nope")).status == 404


async def test_fetch_now_needs_header_and_rate_limits(make_radar):
    radar, _ = await make_radar()
    await radar.run()
    async with TestClient(TestServer(ui_app(radar, addon_mode=False))) as client:
        assert (await client.post("/fetch")).status == 400
        data = await (await client.post("/fetch", headers={"X-Requested-With": "fetch"})).json()
        assert data["result"] == "too_soon"  # the run above was "just now"


async def test_gate_blocks_everyone_but_the_supervisor(make_radar):
    radar, _ = await make_radar()
    async with TestClient(TestServer(ui_app(radar, addon_mode=True))) as client:
        assert (await client.get("/")).status == 403
        assert (await client.get("/healthz")).status == 200  # loopback health check
    async with TestClient(TestServer(calendar_app(radar, addon_mode=True))) as client:
        assert (await client.get("/calendar.ics")).status == 200  # loopback is allowed for the feed


async def test_calendar_feed(make_radar):
    radar, _ = await make_radar()
    await radar.run()
    async with TestClient(TestServer(calendar_app(radar, addon_mode=False))) as client:
        resp = await client.get("/calendar.ics")
        body = await resp.text()
    assert resp.content_type == "text/calendar"
    assert body.count("BEGIN:VEVENT") == 3


async def test_language_choice_per_user(make_radar, tmp_path):
    from app.users import UserSettings

    radar, _ = await make_radar()
    radar.users = UserSettings(tmp_path / "users.json")
    async with TestClient(TestServer(ui_app(radar, addon_mode=False))) as client:
        html = await (await client.get("/", headers={"Accept-Language": "fr-BE,fr;q=0.9"})).text()
        assert "Planning" in html and "Récupérer maintenant" in html  # automatic: browser language
        assert radar.users.notification_language() == "fr"
        resp = await client.post("/language", data={"language": "nl"}, headers={"X-Requested-With": "fetch"})
        assert resp.status == 200
        html = await (await client.get("/", headers={"Accept-Language": "fr"})).text()
        assert "Nu ophalen" in html  # explicit choice wins
        assert radar.users.notification_language() == "nl"
        assert (await client.post("/language", data={"language": "xx"}, headers={"X-Requested-With": "fetch"})).status == 400
        assert (await client.post("/language", data={"language": "nl"})).status == 400
    assert await radar.language() == "nl"
