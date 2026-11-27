import datetime as dt

from app.models import Kind, Status, Transmission
from app.providers.biqsdrive import (
    _age,
    _check_login_response,
    _has_captcha,
    _kind,
    _licence,
    _merge_exam_time,
    _parse_seats,
    _sequence,
    _to_history,
)

from .conftest import LOGIN_PAGE, login_success


def test_sequence():
    assert _sequence("Les: 11 - 12") == "11-12"
    assert _sequence("Les: 23") == "23"
    assert _sequence(None) == ""


def test_licence_and_transmission():
    assert _licence("B") == ("B", Transmission.MANUAL)
    assert _licence("B-AUTO") == ("B", Transmission.AUTOMATIC)
    assert _licence("EX-B-AUTO") == ("B", Transmission.AUTOMATIC)
    assert _licence("") == ("", Transmission.UNKNOWN)


def test_kind():
    assert _kind("LESSON", "B") == Kind.LESSON
    assert _kind("EXAM_TIME", "EX-B") == Kind.EXAM
    assert _kind("LESSON_EXAM", "B") == Kind.EXAM
    assert _kind("SOMETHING", "EX-B") == Kind.EXAM
    assert _kind("BLOCK", "") == Kind.OTHER


def test_age():
    assert _age("15032012", dt.date(2030, 3, 14)) == 17
    assert _age("15032012", dt.date(2030, 3, 15)) == 18
    assert _age("15/03/2012", dt.date(2030, 3, 15)) == 18
    assert _age("2012-03-15", dt.date(2030, 3, 15)) == 18
    assert _age("", dt.date(2030, 1, 1)) is None
    assert _age("99999999", dt.date(2030, 1, 1)) is None


def test_seats_and_login_detection():
    assert _parse_seats(login_success(1, 2)) == (2, 1)
    assert _parse_seats(LOGIN_PAGE) is None
    assert _check_login_response(200, None, login_success(0, 2)) == (2, 0)
    assert not _has_captcha(LOGIN_PAGE)  # the reCAPTCHA script alone is not a captcha
    assert _has_captcha('<div class="g-recaptcha" data-sitekey="x">')


def test_history_row_mapping():
    row = {"date": "09/12/2029", "start": "09:00:00", "instructorId": "IY", "instructorName": "Andere Collega",
           "lessonSequence": "Les: 3 - 4", "timesheetcode": "LESSON", "cancel_reason": "Ziek",
           "isFutureAppointment": "0", "appointment_place": "Voorbeeldstraat 1"}
    h = _to_history(row, {"IX"}, {})
    assert h.date == dt.date(2029, 12, 9) and h.start == "09:00"
    assert h.status == Status.CANCELLED and h.cancel_reason == "Ziek" and not h.mine
    assert "Voorbeeldstraat" not in repr(h)


def test_history_reason_lookup_and_mine():
    h = _to_history({"date": "01/12/2029", "instructorId": "IX", "cancel_reason": "3"}, {"IX"}, {"3": "Ziek"})
    assert h.cancel_reason == "Ziek" and h.mine


def test_history_bad_rows_skipped():
    assert _to_history({"date": "bogus"}, set(), {}) is None


def _exam_rows(event_id, date, start, mid, end, passed=None):
    result = {"exam_result_code": "2", "exam_result": "Niet geslaagd", "exam_passed": passed} if passed else {}
    common = {"event_id": event_id, "date": date, "driverlicenceId": "EX-B", "lessonSequence": "ex2",
              "instructorId": "IX", **result}
    return [
        {**common, "start": start, "end": mid, "timesheetcode": "LESSON_EXAM", "isFutureAppointment": "1"},
        # Verified on the live site: the drive back says isFutureAppointment "0" even for a future exam.
        {**common, "start": mid, "end": end, "timesheetcode": "EXAM_TIME", "isFutureAppointment": "0"},
    ]


def test_exam_and_drive_back_are_one_entry():
    rows = [
        {"date": "06/03/2026", "start": "12:45", "end": "13:45", "timesheetcode": "LESSON", "lessonSequence": "Les: 24"},
        *_exam_rows("av_exam_1", "06/03/2026", "14:00", "14:50", "16:00"),
        {"event_id": "av_exam_x", "date": "07/03/2026", "start": "10:00", "end": "11:00", "timesheetcode": "EXAM_TIME"},
    ]
    history = [_to_history(r, {"IX"}, {}) for r in _merge_exam_time(rows)]
    exams = [h for h in history if h.kind == Kind.EXAM]
    assert [(h.start, h.end) for h in exams] == [("14:00", "16:00"), ("10:00", "11:00")]  # orphan drive back kept
    assert exams[0].status == Status.PLANNED and exams[0].sequence == "2"
    assert len(history) == 3


def test_exam_result():
    failed, _ = _exam_rows("e", "06/03/2026", "14:00", "14:50", "16:00", passed="0")
    passed = {**failed, "exam_passed": "1", "exam_result": "Geslaagd"}
    planned, _ = _exam_rows("e", "06/03/2027", "14:00", "14:50", "16:00")
    assert _to_history({**failed, "isFutureAppointment": "0"}, set(), {}).result == "failed"
    assert _to_history({**passed, "isFutureAppointment": "0"}, set(), {}).result == "passed"
    assert _to_history({**planned, "exam_passed": None, "exam_result": None}, set(), {}).result == ""
    lesson = {"date": "06/03/2026", "timesheetcode": "LESSON", "exam_passed": "0", "exam_result": "x"}
    assert _to_history(lesson, set(), {}).result == ""


async def test_full_run_builds_history_and_familiarity(make_radar):
    radar, planner = await make_radar()
    await radar.run()
    lessons = sorted(radar.state.lessons.values(), key=lambda x: x.start)
    assert [x.kind for x in lessons] == [Kind.LESSON, Kind.LESSON, Kind.EXAM]
    assert lessons[0].location == "Centrum" and lessons[1].location == "Station Noord"
    assert lessons[1].transmission == Transmission.AUTOMATIC and lessons[1].status == Status.CONFIRMED
    record = radar.state.students[lessons[0].student_key]
    assert [h.date.isoformat() for h in record.info.history][:3] == ["2029-12-02", "2029-12-09", "2029-12-16"]
    assert record.info.familiarity(lessons[0].start.date()) == ""  # had a lesson with "IX" on 16/12
    # One session: login page, login, locations, events, 2 x (student + history), logout.
    assert planner.calls[0] == "GET /" and planner.calls[-1] == "GET /logout.php"
    assert len(planner.calls) == 9


async def test_second_run_same_day_skips_student_refresh(make_radar):
    radar, planner = await make_radar()
    await radar.run()
    planner.calls.clear()
    radar.test_clock["now"] += dt.timedelta(hours=3)
    await radar.run()
    assert not any("crud_customer" in c for c in planner.calls)


def test_appointment_title_for_entries_without_student():
    from app.providers.biqsdrive import _appointment_title

    assert _appointment_title({"titleShort": "Beschikbaar voor rijlessen", "title": "( Beschikbaar voor rijlessen )\n"}) \
        == "Beschikbaar voor rijlessen"
    assert _appointment_title({"title": " (  )\n \n\n\n"}) == ""
    assert _appointment_title({"title": " ( Vergadering kantoor )\n"}) == "Vergadering kantoor"
    assert _appointment_title({"titleShort": "Bel 0499 11 22 33"}) == "Bel …"


def test_lesson_never_takes_the_title_and_free_time_does():
    from app.i18n import Translator
    from app.present import kind_label
    from app.providers import PlannerSession
    from app.providers.biqsdrive import _to_lesson

    session = PlannerSession(http=None, base_url="https://x.invalid")
    lesson = _to_lesson({"id": "1", "start": "2030-01-07 09:00:00", "end": "2030-01-07 11:00:00", "studentId": "01|1|2030",
                         "timesheetCode": "LESSON", "titleShort": "0499112233", "title": "x|0499112233"}, {}, session, {})
    free = _to_lesson({"id": "2", "start": "2030-01-07 07:30:00", "end": "2030-01-07 08:00:00", "timesheetCode": "FREE_UNREG",
                       "titleShort": "Beschikbaar voor rijlessen"}, {}, session, {})
    assert lesson.title == "" and "0499" not in repr(lesson)
    assert free.kind == Kind.OTHER and kind_label(free, Translator("nl")) == "Beschikbaar voor rijlessen"
