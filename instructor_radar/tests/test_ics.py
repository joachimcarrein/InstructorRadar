import datetime as dt

from app.i18n import Translator
from app.ics import _fold, build_calendar
from app.models import Kind, Lesson, Status, Transmission

from .conftest import NOW, TZ


def _lesson(**kw):
    base = dict(
        id="1",
        start=dt.datetime(2030, 7, 1, 9, 0),
        end=dt.datetime(2030, 7, 1, 11, 0),
        kind=Kind.LESSON,
        licence="B",
        transmission=Transmission.MANUAL,
        sequence="7-8",
        location="Centrum",
        status=Status.PLANNED,
        student_key="k",
    )
    return Lesson(**{**base, **kw})


def test_calendar_structure_and_summary():
    ics = build_calendar([_lesson()], Translator("nl-BE"), TZ, NOW, "Instructor Radar")
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert "SUMMARY:Les 7-8 – B manueel – Centrum\r\n" in ics
    # 09:00 Brussels in summer = 07:00 UTC
    assert "DTSTART:20300701T070000Z" in ics and "DTEND:20300701T090000Z" in ics
    assert "UID:1@instructor-radar" in ics
    assert "X-WR-CALNAME:Instructor Radar" in ics


def test_exam_and_automatic_and_name():
    lesson = _lesson(kind=Kind.EXAM, transmission=Transmission.AUTOMATIC, sequence="", student_name="Sam Fictief",
                     student_age=18)
    ics = build_calendar([lesson], Translator("en"), TZ, NOW, "X")
    assert "SUMMARY:Exam – B automatic – Centrum – Sam Fictief (18)" in ics


def test_escaping():
    ics = build_calendar([_lesson(location="A, B; C\\D")], Translator("en"), TZ, NOW, "X")
    assert "LOCATION:A\\, B\\; C\\\\D" in ics


def test_folding_keeps_lines_short_and_utf8_intact():
    line = "SUMMARY:" + "é" * 100
    folded = _fold(line)
    for part in folded.split("\r\n"):
        assert len(part.encode("utf-8")) <= 75
    assert folded.replace("\r\n ", "") == line


def test_empty_calendar_is_valid():
    ics = build_calendar([], Translator("en"), TZ, NOW, "X")
    assert "BEGIN:VEVENT" not in ics and "END:VCALENDAR" in ics
