"""Human-readable lesson texts, shared by the web UI, the ICS and notifications."""

from __future__ import annotations

from .i18n import Translator
from .models import Kind, Lesson, Transmission


def kind_label(lesson: Lesson, t: Translator) -> str:
    if lesson.kind == Kind.EXAM:
        return t("exam")
    if lesson.kind == Kind.LESSON:
        return t("lesson", sequence=lesson.sequence) if lesson.sequence else t("lesson_plain")
    return lesson.title or t("other")


def licence_label(lesson: Lesson, t: Translator) -> str:
    gear = t(lesson.transmission.value) if lesson.transmission != Transmission.UNKNOWN else ""
    return " ".join(x for x in (lesson.licence, gear.lower()) if x)


def student_label(lesson: Lesson, t: Translator) -> str:
    if not lesson.student_name:
        return ""
    if lesson.student_age is not None:
        return f"{lesson.student_name} ({lesson.student_age})"
    return lesson.student_name


def summary(lesson: Lesson, t: Translator) -> str:
    """'Les 7 – B manueel – Centrum' (+ ' – Name (18)' when names are enabled)."""
    parts = [kind_label(lesson, t), licence_label(lesson, t), lesson.location, student_label(lesson, t)]
    return " – ".join(p for p in parts if p)


def when(lesson: Lesson, t: Translator) -> str:
    return f"{t.weekdays[lesson.start.weekday()]} {lesson.start:%d/%m %H:%M}–{lesson.end:%H:%M}"


def one_line(lesson: Lesson, t: Translator) -> str:
    return f"{when(lesson, t)} · {summary(lesson, t)}"
