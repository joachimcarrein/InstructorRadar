"""Persistent state in /data/state.json: the current schedule, student histories and the change log.

Only the current week (from Monday) up to the end of the fetched window is kept; everything older is pruned.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .diff import Change
from .models import HistoryEntry, Lesson, StudentInfo

SCHEMA = 1


@dataclass
class RunInfo:
    at: dt.datetime | None = None
    status: str = "never"  # never | ok | busy | error
    message: str = ""
    lessons: int = 0
    changes: int = 0
    last_success: dt.datetime | None = None

    def to_dict(self) -> dict:
        return {
            "at": self.at.isoformat(timespec="seconds") if self.at else None,
            "status": self.status,
            "message": self.message,
            "lessons": self.lessons,
            "changes": self.changes,
            "last_success": self.last_success.isoformat(timespec="seconds") if self.last_success else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> RunInfo:
        def ts(v):
            return dt.datetime.fromisoformat(v) if v else None

        return cls(
            at=ts(d.get("at")),
            status=d.get("status", "never"),
            message=d.get("message", ""),
            lessons=int(d.get("lessons", 0)),
            changes=int(d.get("changes", 0)),
            last_success=ts(d.get("last_success")),
        )


@dataclass
class StudentRecord:
    info: StudentInfo
    refreshed: dt.date
    # Fetched while names / ages were on. When one is switched on later, records without it are fetched again.
    with_name: bool = False
    with_age: bool = False


@dataclass
class State:
    lessons: dict[str, Lesson] = field(default_factory=dict)
    students: dict[str, StudentRecord] = field(default_factory=dict)
    changes: list[Change] = field(default_factory=list)
    window_end: dt.date | None = None
    run: RunInfo = field(default_factory=RunInfo)

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA,
            "lessons": [lesson.to_dict() for lesson in sorted(self.lessons.values(), key=lambda x: x.start)],
            "students": {
                k: {
                    "name": r.info.name,
                    "age": r.info.age,
                    "refreshed": r.refreshed.isoformat(),
                    "with_name": r.with_name,
                    "with_age": r.with_age,
                    "history": [h.to_dict() for h in r.info.history],
                }
                for k, r in self.students.items()
            },
            "changes": [c.to_dict() for c in self.changes],
            "window_end": self.window_end.isoformat() if self.window_end else None,
            "run": self.run.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> State:
        if d.get("schema") != SCHEMA:
            return cls()
        # Up to 2026.11.4 the name was stored on every lesson: carry it over to the student record once.
        old_names = {x.get("student_key"): x["student_name"] for x in d.get("lessons", []) if x.get("student_name")}
        return cls(
            lessons={x["id"]: Lesson.from_dict(x) for x in d.get("lessons", [])},
            students={
                k: StudentRecord(
                    info=StudentInfo(
                        key=k,
                        age=v.get("age"),
                        history=[HistoryEntry.from_dict(h) for h in v.get("history", [])],
                        name=v.get("name") or old_names.get(k),
                    ),
                    refreshed=dt.date.fromisoformat(v["refreshed"]),
                    with_name=bool(v.get("with_name", k in old_names)),
                    with_age=bool(v.get("with_age", False)),
                )
                for k, v in d.get("students", {}).items()
            },
            changes=[Change.from_dict(c) for c in d.get("changes", [])],
            window_end=dt.date.fromisoformat(d["window_end"]) if d.get("window_end") else None,
            run=RunInfo.from_dict(d.get("run", {})),
        )


def week_start(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())


def prune(state: State, today: dt.date) -> State:
    """Drop lessons and changes from before this week's Monday and students no lesson or change refers to any more.

    A change keeps its student, so a removed lesson still shows who it was for.
    """
    monday = week_start(today)
    state.lessons = {k: v for k, v in state.lessons.items() if v.start.date() >= monday}
    state.changes = [c for c in state.changes if c.detected.date() >= monday]
    used = {lesson.student_key for lesson in state.lessons.values()} | {c.lesson.student_key for c in state.changes}
    state.students = {k: v for k, v in state.students.items() if k in used}
    return state


def apply_privacy(state: State, keep_name: bool, keep_age: bool) -> State:
    """Remove names/ages that were stored while an option was on and is now off (they live in the student records)."""
    for record in state.students.values():
        record.info = record.info.without_personal(keep_name, keep_age)
        record.with_name = record.with_name and keep_name
        record.with_age = record.with_age and keep_age
    return state


class Store:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> State:
        try:
            return State.from_dict(json.loads(self.path.read_text(encoding="utf-8")))
        except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError):
            return State()

    def save(self, state: State) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)
