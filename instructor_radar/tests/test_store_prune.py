import datetime as dt

from app.diff import Change
from app.models import HistoryEntry, Kind, Lesson, Status, StudentInfo, Transmission
from app.store import State, Store, StudentRecord, apply_privacy, prune

from .conftest import NOW


def _l(id_, day, key="s1"):
    return Lesson(id_, dt.datetime(2030, 1, day, 9), dt.datetime(2030, 1, day, 11), Kind.LESSON, "B",
                  Transmission.MANUAL, "1-2", "Centrum", Status.PLANNED, key, "Name", 18)


def test_prune_keeps_current_week_only():
    state = State(
        lessons={x.id: x for x in [_l("old", 3, "gone"), _l("mon", 7), _l("next", 15)]},
        students={k: StudentRecord(StudentInfo(k), dt.date(2030, 1, 7)) for k in ("s1", "gone")},
        changes=[Change("added", _l("x", 3), None, NOW - dt.timedelta(days=5)), Change("added", _l("y", 8), None, NOW)],
    )
    prune(state, dt.date(2030, 1, 9))  # Wednesday -> keep from Monday the 7th
    assert set(state.lessons) == {"mon", "next"}
    assert set(state.students) == {"s1"}
    assert [c.lesson.id for c in state.changes] == ["y"]


def test_apply_privacy_strips_names_and_ages():
    state = State(lessons={"a": _l("a", 7)},
                  students={"s1": StudentRecord(StudentInfo("s1", age=18), dt.date(2030, 1, 7))})
    apply_privacy(state, keep_name=False, keep_age=False)
    assert state.lessons["a"].student_name is None and state.lessons["a"].student_age is None
    assert state.students["s1"].info.age is None


def test_roundtrip(tmp_path):
    store = Store(tmp_path / "state.json")
    history = [HistoryEntry(dt.date(2029, 12, 1), "09:00", "X", True, Kind.LESSON, "1-2", Status.CANCELLED, "Ziek")]
    state = State(lessons={"a": _l("a", 7)},
                  students={"s1": StudentRecord(StudentInfo("s1", 18, history), dt.date(2030, 1, 7))},
                  changes=[Change("changed", _l("a", 7), _l("a", 8), NOW, ("start",))],
                  window_end=dt.date(2030, 1, 21))
    store.save(state)
    loaded = store.load()
    assert loaded.lessons == state.lessons
    assert loaded.students["s1"].info.history == history
    assert loaded.changes[0].before.start.day == 8
    assert loaded.window_end == dt.date(2030, 1, 21)


def test_corrupt_file_starts_empty(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json", encoding="utf-8")
    assert Store(path).load().lessons == {}


def test_familiarity():
    def h(day, mine, status=Status.DONE, kind=Kind.LESSON):
        return HistoryEntry(dt.date(2029, 12, day), "", "", mine, kind, "", status)

    lesson_day = dt.date(2030, 1, 7)
    assert StudentInfo("k", history=[]).familiarity(lesson_day) == "first"
    assert StudentInfo("k", history=[h(1, False, Status.CANCELLED)]).familiarity(lesson_day) == "first"
    assert StudentInfo("k", history=[h(1, False)]).familiarity(lesson_day) == "new"
    assert StudentInfo("k", history=[h(1, False), h(2, True)]).familiarity(lesson_day) == ""
    assert StudentInfo("k", history=[h(1, True, Status.CANCELLED), h(2, False)]).familiarity(lesson_day) == "new"


def test_practice_minutes():
    def h(status, start="09:00", end="11:00", kind=Kind.LESSON):
        return HistoryEntry(dt.date(2029, 12, 1), start, "X", True, kind, "", status, end=end)

    info = StudentInfo("k", history=[h(Status.DONE), h(Status.DONE, "14:30", "15:20"), h(Status.CANCELLED),
                                     h(Status.PLANNED), h(Status.DONE, kind=Kind.EXAM), h(Status.DONE, end="")])
    assert info.practice_minutes() == (170, 120)
    assert h(Status.DONE, "10:00", "09:00").minutes == 0
