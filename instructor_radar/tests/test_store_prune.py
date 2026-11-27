import datetime as dt

from app.diff import Change
from app.models import HistoryEntry, Kind, Lesson, Status, StudentInfo, Transmission
from app.store import State, Store, StudentRecord, apply_privacy, prune

from .conftest import NOW


def _l(id_, day, key="s1"):
    return Lesson(id_, dt.datetime(2030, 1, day, 9), dt.datetime(2030, 1, day, 11), Kind.LESSON, "B",
                  Transmission.MANUAL, "1-2", "Centrum", Status.PLANNED, key)


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


def test_prune_keeps_the_student_of_a_removed_lesson():
    state = State(
        lessons={"mon": _l("mon", 7)},
        students={k: StudentRecord(StudentInfo(k, name="X"), dt.date(2030, 1, 7)) for k in ("s1", "gone")},
        changes=[Change("removed", _l("r", 8, "gone"), None, NOW)],
    )
    prune(state, dt.date(2030, 1, 9))
    assert set(state.students) == {"s1", "gone"}  # 'Removed: ... – X' can still say who


def test_apply_privacy_strips_names_and_ages():
    record = StudentRecord(StudentInfo("s1", age=18, name="Name"), dt.date(2030, 1, 7), with_name=True, with_age=True)
    state = State(lessons={"a": _l("a", 7)}, students={"s1": record})
    apply_privacy(state, keep_name=True, keep_age=False)
    assert state.students["s1"].info.name == "Name" and state.students["s1"].info.age is None
    assert record.with_name and not record.with_age
    apply_privacy(state, keep_name=False, keep_age=False)
    assert state.students["s1"].info.name is None and not record.with_name


def test_names_on_old_lessons_move_to_the_student_record():
    # State written by 2026.11.4: name and age on every lesson, the record without a name.
    old = State(lessons={"a": _l("a", 7)}, students={"s1": StudentRecord(StudentInfo("s1", age=18), dt.date(2030, 1, 7))})
    d = old.to_dict()
    d["lessons"][0].update(student_name="Old Name", student_age=18)
    for v in d["students"].values():
        del v["name"], v["with_name"], v["with_age"]
    loaded = State.from_dict(d)
    assert loaded.students["s1"].info.name == "Old Name" and loaded.students["s1"].with_name
    assert not loaded.students["s1"].with_age  # fetched again once when ages are on
    assert "student_name" not in loaded.lessons["a"].to_dict()


def test_roundtrip(tmp_path):
    store = Store(tmp_path / "state.json")
    history = [HistoryEntry(dt.date(2029, 12, 1), "09:00", "X", True, Kind.LESSON, "1-2", Status.CANCELLED, "Ziek")]
    state = State(lessons={"a": _l("a", 7)},
                  students={"s1": StudentRecord(StudentInfo("s1", 18, history, "Name"), dt.date(2030, 1, 7), True)},
                  changes=[Change("changed", _l("a", 7), _l("a", 8), NOW, ("start",))],
                  window_end=dt.date(2030, 1, 21))
    store.save(state)
    loaded = store.load()
    assert loaded.lessons == state.lessons
    assert loaded.students["s1"].info == state.students["s1"].info and loaded.students["s1"].with_name
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


def test_familiarity_counts_earlier_planned_lessons():
    def h(day, start, mine=True, status=Status.PLANNED):
        return HistoryEntry(dt.date(2026, 12, day), start, "", mine, Kind.LESSON, "", status)

    # Lesson 1-2 still planned on Friday 18/12, lesson 3-4 on Saturday 19/12: not a first lesson.
    planned = StudentInfo("k", history=[h(18, "15:45"), h(19, "08:00")])
    assert planned.familiarity(dt.datetime(2026, 12, 18, 15, 45)) == "first"
    assert planned.familiarity(dt.datetime(2026, 12, 19, 8, 0)) == ""
    # Same day, earlier lesson with a colleague: new to me, not first.
    colleague = StudentInfo("k", history=[h(18, "09:00", mine=False), h(18, "13:30")])
    assert colleague.familiarity(dt.datetime(2026, 12, 18, 13, 30)) == "new"
    # An earlier planned lesson that was cancelled does not count.
    cancelled = StudentInfo("k", history=[h(18, "09:00", status=Status.CANCELLED), h(19, "08:00")])
    assert cancelled.familiarity(dt.datetime(2026, 12, 19, 8, 0)) == "first"


def test_practice_minutes():
    def h(status, start="09:00", end="11:00", kind=Kind.LESSON):
        return HistoryEntry(dt.date(2029, 12, 1), start, "X", True, kind, "", status, end=end)

    info = StudentInfo("k", history=[h(Status.DONE), h(Status.DONE, "14:30", "15:20"), h(Status.CANCELLED),
                                     h(Status.PLANNED), h(Status.DONE, kind=Kind.EXAM), h(Status.DONE, end="")])
    assert info.practice_minutes() == (170, 120)
    assert h(Status.DONE, "10:00", "09:00").minutes == 0


def test_lesson_counts_in_units():
    def h(status, seq, kind=Kind.LESSON):
        return HistoryEntry(dt.date(2029, 12, 1), "09:00", "X", True, kind, seq, status)

    info = StudentInfo("k", history=[h(Status.DONE, "1-2"), h(Status.DONE, "3"), h(Status.CANCELLED, "4-5"),
                                     h(Status.PLANNED, "4-5"), h(Status.DONE, "", Kind.EXAM), h(Status.DONE, "")])
    assert info.lesson_counts() == (4, 2)
    assert h(Status.DONE, "12-11").units == 1
