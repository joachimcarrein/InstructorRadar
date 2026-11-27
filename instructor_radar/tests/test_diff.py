import datetime as dt
from dataclasses import replace

from app.diff import diff, to_notify
from app.models import Kind, Lesson, Status, Transmission

from .conftest import NOW


def _l(id_, day, hour=9, **kw):
    base = dict(
        id=id_,
        start=dt.datetime(2030, 1, day, hour),
        end=dt.datetime(2030, 1, day, hour + 2),
        kind=Kind.LESSON,
        licence="B",
        transmission=Transmission.MANUAL,
        sequence="1-2",
        location="Centrum",
        status=Status.PLANNED,
        student_key="s1",
    )
    return Lesson(**{**base, **kw})


def test_added_changed_removed():
    old = {x.id: x for x in [_l("a", 7), _l("b", 8), _l("c", 9), _l("far", 30)]}
    new = [_l("a", 7), _l("b", 8, hour=13), _l("d", 10)]
    changes = diff(old, new, dt.date(2030, 1, 7), dt.date(2030, 1, 21), NOW)
    kinds = {(c.type, c.lesson.id) for c in changes}
    assert kinds == {("changed", "b"), ("removed", "c"), ("added", "d")}  # 'far' is outside the window
    changed = next(c for c in changes if c.type == "changed")
    assert changed.fields == ("start", "end") and changed.before.start.hour == 9


def test_name_change_is_not_a_schedule_change():
    old = {"a": _l("a", 7)}
    new = [replace(_l("a", 7), student_name="Someone", student_age=18)]
    assert diff(old, new, dt.date(2030, 1, 7), dt.date(2030, 1, 21), NOW) == []


def test_to_notify_window():
    changes = diff({}, [_l("today", 7), _l("tomorrow", 8), _l("later", 10)], dt.date(2030, 1, 7),
                   dt.date(2030, 1, 21), NOW)
    now = NOW.replace(tzinfo=None)
    assert {c.lesson.id for c in to_notify(changes, now.date(), 2, now)} == {"today", "tomorrow"}
    assert {c.lesson.id for c in to_notify(changes, now.date(), 1, now)} == {"today"}
    assert to_notify(changes, now.date(), 0, now) == []


def test_moved_into_window_notifies():
    old = {"a": _l("a", 15)}
    new = [_l("a", 8)]
    changes = diff(old, new, dt.date(2030, 1, 7), dt.date(2030, 1, 21), NOW)
    now = NOW.replace(tzinfo=None)
    assert len(to_notify(changes, now.date(), 2, now)) == 1


async def test_change_detected_between_runs_and_notified(make_radar):
    radar, planner = await make_radar()
    await radar.run()
    assert radar.state.changes == []  # first run is the baseline
    assert not [c for c in radar.ha.calls if c[0] in ("notify", "persistent_notification")]

    planner.events = [e for e in planner.events if e.get("id") != "9001"]  # today's lesson cancelled
    planner.events[0]["start"] = "2030-01-08 14:00:00"  # tomorrow's lesson moved
    radar.test_clock["now"] = NOW + dt.timedelta(hours=1)
    run = await radar.run()
    assert run.changes == 2
    types = sorted(c.type for c in radar.state.changes)
    assert types == ["changed", "removed"]
    notes = [c for c in radar.ha.calls if c[0] == "persistent_notification" and c[3] == "instructor_radar_changes"]
    assert len(notes) == 1 and "Geannuleerd" in notes[0][2]


async def test_notify_service_used_when_set(make_radar):
    radar, planner = await make_radar(notify_service="mobile_app_phone")
    await radar.run()
    planner.events[0]["location"] = "02"
    radar.test_clock["now"] = NOW + dt.timedelta(hours=1)
    await radar.run()
    assert [c for c in radar.ha.calls if c[0] == "notify" and c[1] == "mobile_app_phone"]
