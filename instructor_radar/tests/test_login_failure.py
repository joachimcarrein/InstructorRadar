"""Login failures and odd answers: clean error, persistent notification, logout, no retry before the next slot."""

from app.ha import ERROR_NOTIFICATION_ID


def _notifications(radar):
    return [c for c in radar.ha.calls if c[0] == "persistent_notification" and c[3] == ERROR_NOTIFICATION_ID]


async def test_bad_password_raises_notification_and_does_not_retry(make_radar):
    radar, planner = await make_radar("bad_password")
    run = await radar.run()
    assert run.status == "error"
    assert "refused the login" in run.message
    assert len(_notifications(radar)) == 1
    assert radar.retry_at is None
    assert len(planner.login_forms) == 1  # exactly one attempt
    assert planner.logouts == 1  # logout is still sent (harmless, frees any half-made session)


async def test_login_form_fields(make_radar):
    radar, planner = await make_radar()
    await radar.run()
    form = planner.login_forms[0]
    assert set(form) == {"b", "credential", "password", "2fa", "login"}
    assert form["2fa"] == ""
    assert '"timezone"' in form["b"]


async def test_redirect_with_error_code(make_radar):
    radar, _ = await make_radar("redirect_fail")
    run = await radar.run()
    assert run.status == "error" and "code 14" in run.message
    assert len(_notifications(radar)) == 1


async def test_captcha_is_reported(make_radar):
    radar, planner = await make_radar("captcha")
    run = await radar.run()
    assert run.status == "error" and "captcha" in run.message
    assert planner.login_forms == []  # never posts credentials when a captcha is shown


async def test_html_instead_of_json(make_radar):
    radar, planner = await make_radar("html_events")
    run = await radar.run()
    assert run.status == "error" and "HTML instead of JSON" in run.message
    assert len(_notifications(radar)) == 1
    assert planner.logouts == 1


async def test_session_lost_mid_run(make_radar):
    radar, planner = await make_radar("session_lost")
    run = await radar.run()
    assert run.status == "error" and "ended the session" in run.message


async def test_busy_keeps_schedule_retries_once_and_does_not_notify(make_radar):
    radar, planner = await make_radar()
    assert (await radar.run()).status == "ok"
    lessons_before = dict(radar.state.lessons)

    planner.mode = "busy"
    run = await radar.run()
    assert run.status == "busy"
    assert radar.state.lessons == lessons_before
    assert _notifications(radar) == []
    assert radar.retry_at is not None

    run = await radar.run("retry")
    assert run.status == "busy" and radar.retry_at is None  # only one retry, then the normal schedule


async def test_error_notification_dismissed_after_recovery(make_radar):
    radar, planner = await make_radar("bad_password")
    await radar.run()
    planner.mode = "ok"
    assert (await radar.run()).status == "ok"
    assert ("dismiss", ERROR_NOTIFICATION_ID) in radar.ha.calls


async def test_unreachable_planner(make_radar):
    radar, _ = await make_radar()
    radar.options = radar.options.__class__(**{**radar.options.__dict__, "base_url": "http://127.0.0.1:9"})
    run = await radar.run()
    assert run.status == "error" and "Could not reach" in run.message


async def test_manual_auth_not_implemented(make_radar):
    radar, planner = await make_radar(auth_mode="manual")
    run = await radar.run()
    assert run.status == "error" and "not implemented" in run.message
    assert planner.login_forms == []


async def test_totp_code_is_sent(make_radar):
    radar, planner = await make_radar(auth_mode="totp", totp_secret="JBSWY3DPEHPK3PXP")
    await radar.run()
    code = planner.login_forms[0]["2fa"]
    assert code.isdigit() and len(code) == 6


async def test_run_time_limit_still_logs_out(make_radar, monkeypatch):
    import app.sync

    monkeypatch.setattr(app.sync, "RUN_TIMEOUT", 0.5)
    radar, planner = await make_radar("slow")
    run = await radar.run()
    assert run.status == "error" and "in time" in run.message
    assert planner.logouts == 1
