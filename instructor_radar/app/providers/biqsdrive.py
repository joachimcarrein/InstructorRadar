"""biqsDRIVE planner (PHP web app, session-cookie auth, no public API).

Unofficial: based on what the web app itself does in a browser. Behaviour that could not be verified safely is
isolated in small functions marked `TODO(verify)`, so it is easy to adjust after testing against the real site.

Verified on 2026-11-27 (v1.106-015):
- GET / sets PHPSESSID and shows the login form. Hidden field `b` is filled by page JavaScript with client
  properties ({screen_resolution, languages, timezone}); we send our own.
- POST /login.php (b, credential, password, 2fa, login) answers HTTP 200 HTML. Success = a script that opens
  drive_calendar.php. The body contains `//maxusers:N //noofusers:N` (simultaneous sessions of the account).
  An empty 2fa is accepted when 2FA is off.
- GET /logout.php -> 302 /. Afterwards data endpoints answer HTTP 403 JSON.
- POST /events.php (start, end) -> JSON list of the instructor's own appointments (plus student phone/address
  fields, and the phone inside `title`: all dropped here).
- POST php/crud_calendar.php?action=get_location -> [{Code, Name, ...}].
- POST php/crud_customer.php?action=edit_customer {customer_index} -> the student record (read; the name is the
  web app's). Only `birthdate` (-> age) and `UniqueId` are taken; the record also holds national number, ID card,
  address, ... which never leave `_student_extract`.
- POST php/crud_customer.php?action=get_customer_events {customer_index, UniqueId} -> the student's lessons with
  every instructor (date, start, instructorId, instructorName, lessonSequence, timesheetcode, event_status,
  cancel_reason, isFutureAppointment). Rows are not uniform.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
from typing import Any

from ..models import HistoryEntry, Kind, Lesson, Status, StudentInfo, Transmission
from . import (
    CaptchaRequired,
    Credentials,
    LoginFailed,
    NotLoggedIn,
    PlannerBusy,
    PlannerSession,
    UnexpectedResponse,
)

log = logging.getLogger(__name__)

# Read-only endpoints this provider may call. Everything else (update_*, delete_*, assign_*, anonymise..., ...) is
# refused before a request is made, so a bug can never change data in the planner.
P_LOGIN_PAGE = "/"
P_LOGIN = "/login.php"
P_LOGOUT = "/logout.php"
P_EVENTS = "/events.php"
P_LOCATIONS = "/php/crud_calendar.php?action=get_location"
P_DELETE_REASONS = "/php/crud_calendar.php?action=get_deleteReasons"
P_STUDENT = "/php/crud_customer.php?action=edit_customer"
P_STUDENT_EVENTS = "/php/crud_customer.php?action=get_customer_events"
ALLOWED = {
    ("GET", P_LOGIN_PAGE),
    ("POST", P_LOGIN),
    ("GET", P_LOGOUT),
    ("POST", P_EVENTS),
    ("POST", P_LOCATIONS),
    ("GET", P_DELETE_REASONS),
    ("POST", P_STUDENT),
    ("POST", P_STUDENT_EVENTS),
}

EXAM_CODES = {"EXAM", "EXAM_TIME", "LESSON_EXAM"}
LESSON_CODES = {"LESSON"}


class BiqsDriveProvider:
    name = "biqsdrive"

    # ---------------------------------------------------------------- session

    async def login(self, session: PlannerSession, credentials: Credentials) -> None:
        status, _, page = await _request(session, "GET", P_LOGIN_PAGE)
        if status != 200:
            raise UnexpectedResponse(f"The planner's login page answered HTTP {status}.")
        if _has_captcha(page):
            raise CaptchaRequired(_CAPTCHA_MSG)
        if not _is_login_page(page):
            raise UnexpectedResponse("The planner's login page looks different than expected (no login form).")

        form = {
            "b": _client_properties(),
            "credential": credentials.username,
            "password": credentials.password,
            "2fa": _second_factor(credentials),
            "login": "",
        }
        status, location, body = await _request(session, "POST", P_LOGIN, form=form)
        seats = _check_login_response(status, location, body)
        if seats:
            session.private["seats"] = seats
            log.debug("Planner sessions at login: %d of %d in use", seats[1], seats[0])

    async def logout(self, session: PlannerSession) -> None:
        status, _, _ = await _request(session, "GET", P_LOGOUT)
        if status not in (200, 302, 303):
            log.warning("Logout answered HTTP %d", status)

    # ---------------------------------------------------------------- data

    async def fetch_events(self, session: PlannerSession, start: dt.date, end: dt.date) -> list[Lesson]:
        locations = await self._locations(session)
        # FullCalendar semantics: `end` is exclusive.
        form = {"start": start.isoformat(), "end": (end + dt.timedelta(days=1)).isoformat()}
        data = _parse_json(*await _request(session, "POST", P_EVENTS, form=form))
        if not isinstance(data, list):
            raise UnexpectedResponse("The planner sent lessons in an unknown format.")

        session.private["instructor_ids"] = {str(e.get("instructorId")) for e in data if isinstance(e, dict)}
        students: dict[str, str] = session.private.setdefault("students", {})
        lessons: list[Lesson] = []
        seen: dict[str, int] = {}
        for raw in data:
            if not isinstance(raw, dict) or not _is_appointment(raw):
                continue
            lesson = _to_lesson(raw, locations, session, students)
            if lesson is None:
                continue
            # Ids are expected to be unique; keep both if not.
            n = seen.get(lesson.id, 0)
            seen[lesson.id] = n + 1
            if n:
                lesson = Lesson.from_dict({**lesson.to_dict(), "id": f"{lesson.id}#{n}"})
            lessons.append(lesson)
        return lessons

    async def fetch_student(self, session: PlannerSession, student_key: str, today: dt.date) -> StudentInfo:
        planner_id = session.private.get("students", {}).get(student_key)
        if planner_id is None:
            raise UnexpectedResponse("Unknown student (fetch_events must run first).")

        record = _parse_json(*await _request(session, "POST", P_STUDENT, json_body={"customer_index": planner_id}))
        birthdate, unique_id = _student_extract(record)
        del record  # holds personal data; nothing else is used
        age = _age(birthdate, today) if session.settings.include_student_age else None

        rows = _parse_json(
            *await _request(
                session,
                "POST",
                P_STUDENT_EVENTS,
                json_body={"customer_index": planner_id, "UniqueId": unique_id},
            )
        )
        own = session.private.get("instructor_ids", set())
        reasons = await self._delete_reasons(session) if _needs_reason_lookup(rows) else {}
        history = sorted(
            (h for h in (_to_history(r, own, reasons) for r in _rows(rows)) if h is not None),
            key=lambda h: (h.date, h.start),
        )
        return StudentInfo(key=student_key, age=age, history=history)

    async def _locations(self, session: PlannerSession) -> dict[str, str]:
        if "locations" not in session.private:
            data = _parse_json(*await _request(session, "POST", P_LOCATIONS, form={}))
            session.private["locations"] = {
                str(x.get("Code")): str(x.get("Name") or x.get("Code"))
                for x in (data if isinstance(data, list) else [])
                if isinstance(x, dict)
            }
        return session.private["locations"]

    async def _delete_reasons(self, session: PlannerSession) -> dict[str, str]:
        if "delete_reasons" not in session.private:
            data = _parse_json(*await _request(session, "GET", P_DELETE_REASONS))
            session.private["delete_reasons"] = {
                str(x.get("id")): str(x.get("description") or "")
                for x in (data if isinstance(data, list) else [])
                if isinstance(x, dict)
            }
        return session.private["delete_reasons"]


# -------------------------------------------------------------------- HTTP


async def _request(
    session: PlannerSession,
    method: str,
    path: str,
    form: dict | None = None,
    json_body: dict | None = None,
) -> tuple[int, str | None, str]:
    """One request, no redirects followed. Returns (status, Location header, body text)."""
    if (method, path) not in ALLOWED:
        raise AssertionError(f"Endpoint not on the read-only allowlist: {method} {path}")
    session.request_count += 1
    kwargs: dict[str, Any] = {"allow_redirects": False}
    if form is not None:
        kwargs["data"] = form
    if json_body is not None:
        kwargs["json"] = json_body
    async with session.http.request(method, session.base_url + path, **kwargs) as resp:
        text = await resp.text(errors="replace")
        return resp.status, resp.headers.get("Location"), text


def _parse_json(status: int, location: str | None, text: str) -> Any:
    if status == 403 or (status in (301, 302, 303) and _error_code(location) is not None):
        raise NotLoggedIn("The planner ended the session in the middle of a fetch (logged in elsewhere?).")
    if status != 200:
        raise UnexpectedResponse(f"The planner answered HTTP {status} where data was expected.")
    stripped = text.lstrip()
    if stripped.startswith("<"):
        raise UnexpectedResponse("The planner sent a web page instead of data (HTML instead of JSON).")
    try:
        return json.loads(stripped) if stripped else []
    except json.JSONDecodeError:
        raise UnexpectedResponse("The planner sent data that is not valid JSON.") from None


def _error_code(location: str | None) -> str | None:
    m = re.search(r"[?&]e=(\w+)", location or "")
    return m.group(1) if m else None


# -------------------------------------------------------------------- login details


_CAPTCHA_MSG = (
    "The planner asks for a captcha. Log in once in a browser; Instructor Radar tries again at the next fetch time."
)


def _client_properties() -> str:
    # The page fills hidden field `b` with these browser properties. Fixed values, nothing about the host.
    return json.dumps(
        {"screen_resolution": "1920x1080", "languages": ["nl-BE", "nl", "en"], "timezone": "Europe/Brussels"},
        separators=(",", ":"),
    )


def _second_factor(credentials: Credentials) -> str:
    if credentials.auth_mode == "none":
        return ""  # verified: an empty 2fa is accepted when 2FA is off
    if credentials.auth_mode == "totp":
        import pyotp

        class _Totp(pyotp.TOTP):
            # pyotp >= 2.10 refuses secrets under 112 bits; many sites still issue 80-bit (16 character) keys.
            min_secret_length_bits = 80

        secret = credentials.totp_secret.replace(" ", "").upper().rstrip("=")
        try:
            return _Totp(secret + "=" * (-len(secret) % 8)).now()
        except Exception:  # noqa: BLE001 - never echo the secret
            raise LoginFailed("The TOTP secret is not valid (expected the base32 key of the authenticator).") from None
    raise LoginFailed("auth_mode 'manual' is not implemented yet. Use 'none' or 'totp'.")


def _is_login_page(html: str) -> bool:
    return 'name="credential"' in html and 'name="password"' in html and "login.php" in html


def _has_captcha(html: str) -> bool:
    # The page always loads Google's reCAPTCHA script but showed no widget when verified. A widget = g-recaptcha div.
    return 'class="g-recaptcha' in html or "data-sitekey=" in html


def _parse_seats(html: str) -> tuple[int, int] | None:
    """(maxusers, noofusers) from the login response comments, if present."""
    m_max = re.search(r"//\s*maxusers:\s*(\d+)", html)
    m_used = re.search(r"//\s*noofusers:\s*(\d+)", html)
    if not (m_max and m_used):
        return None
    return int(m_max.group(1)), int(m_used.group(1))


def _login_succeeded(html: str) -> bool:
    # Verified: success = a script that opens drive_calendar.php, without the login form.
    return "drive_calendar.php" in html and not _is_login_page(html)


def _check_login_response(status: int, location: str | None, body: str) -> tuple[int, int] | None:
    """Raise when the login did not succeed. Returns the session seats (max, used) when the planner reports them."""
    if status in (301, 302, 303):
        code = _error_code(location)
        # TODO(verify): which ?e=<code> values exist; ?e=14 was seen for "not logged in / failed".
        raise LoginFailed(
            "The planner refused the login"
            + (f" (code {code})" if code else "")
            + ". Check username, password and 2FA in the add-on configuration."
        )
    if status != 200:
        raise UnexpectedResponse(f"The planner's login answered HTTP {status}.")
    seats = _parse_seats(body)
    if _login_succeeded(body):
        if seats and seats[1] >= seats[0]:
            # TODO(verify): when all sessions are in use, does the planner refuse us or end the oldest session?
            # Logged so the behaviour can be learned from the log (counts only).
            log.warning("All %d planner sessions were already in use at login", seats[0])
        return seats
    if _has_captcha(body):
        raise CaptchaRequired(_CAPTCHA_MSG)
    if seats and seats[1] >= seats[0]:
        # TODO(verify): exact page shown when the session limit refuses a login.
        raise PlannerBusy(f"All {seats[0]} planner sessions of this account are in use.")
    raise LoginFailed("The planner refused the login. Check username, password and 2FA in the add-on configuration.")


# -------------------------------------------------------------------- mapping (privacy filter)


def _is_appointment(raw: dict) -> bool:
    return raw.get("rendering") not in ("background", "inverse-background") and bool(raw.get("start"))


def _parse_dt(value: Any) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(value).replace("T", " ")[:19])
    except ValueError:
        return None


def _student_key(base_url: str, planner_id: str) -> str:
    return hashlib.sha256(f"{base_url}|{planner_id}".encode()).hexdigest()[:16]


def _kind(timesheet_code: Any, licence_id: Any) -> Kind:
    code = str(timesheet_code or "").upper()
    # TODO(verify): LESSON_EXAM seems to be the lesson/drive to the exam; shown as an exam for now.
    if code in EXAM_CODES or str(licence_id or "").upper().startswith("EX-"):
        return Kind.EXAM
    if code in LESSON_CODES:
        return Kind.LESSON
    return Kind.OTHER


def _licence(licence_id: Any) -> tuple[str, Transmission]:
    """'B' / 'B-AUTO' / 'EX-B' / 'EX-B-AUTO' -> ('B', manual|automatic)."""
    code = str(licence_id or "").upper()
    if code.startswith("EX-"):
        code = code[3:]
    auto = code.endswith("-AUTO")
    if auto:
        code = code[: -len("-AUTO")]
    if not code:
        return "", Transmission.UNKNOWN
    return code, Transmission.AUTOMATIC if auto else Transmission.MANUAL


def _sequence(value: Any) -> str:
    """'Les: 11 - 12' -> '11-12', 'Les: 23' -> '23'."""
    numbers = re.findall(r"\d+", str(value or ""))
    return "-".join(numbers[:2])


def _status(raw: dict) -> Status:
    # TODO(verify): only statusConfirmed "0" seen so far; "1" assumed to mean confirmed.
    return Status.CONFIRMED if str(raw.get("statusConfirmed")) == "1" else Status.PLANNED


def _to_lesson(raw: dict, locations: dict[str, str], session: PlannerSession, students: dict[str, str]) -> Lesson | None:
    start, end = _parse_dt(raw.get("start")), _parse_dt(raw.get("end"))
    if start is None or end is None:
        return None
    planner_student = str(raw.get("studentId") or "")
    key = ""
    if planner_student and planner_student != "ex_slot":
        key = _student_key(session.base_url, planner_student)
        students[key] = planner_student
    licence, transmission = _licence(raw.get("driverlicenceId"))
    location_code = str(raw.get("location") or "")
    settings = session.settings
    name = str(raw.get("studentName") or "").strip() or None
    # Only whitelisted fields are copied. studentPhone, studentPrivatePhone, studentAddress, studentCity, title,
    # originalTitle (contains the phone), description, ... are never read.
    return Lesson(
        id=str(raw.get("id") or raw.get("UniqueId") or f"{start:%Y%m%d%H%M}"),
        start=start,
        end=end,
        kind=_kind(raw.get("timesheetCode"), raw.get("driverlicenceId")),
        licence=licence,
        transmission=transmission,
        sequence=_sequence(raw.get("lessonSequence")),
        location=locations.get(location_code, location_code),
        status=_status(raw),
        student_key=key,
        student_name=name if settings.include_student_name and key else None,
    )


def _student_extract(record: Any) -> tuple[str, Any]:
    """From the full student record keep only (birthdate, UniqueId)."""
    if isinstance(record, list):
        record = record[-1] if record else {}
    if not isinstance(record, dict):
        raise UnexpectedResponse("The planner sent student data in an unknown format.")
    return str(record.get("birthdate") or ""), record.get("UniqueId")


def _age(birthdate: str, today: dt.date) -> int | None:
    """Birthdate as ddmmyyyy (verified), also accepts dd/mm/yyyy and yyyy-mm-dd."""
    digits = re.sub(r"\D", "", birthdate)
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}", birthdate):
            born = dt.date.fromisoformat(birthdate[:10])
        elif len(digits) == 8:
            born = dt.date(int(digits[4:]), int(digits[2:4]), int(digits[:2]))
        else:
            return None
    except ValueError:
        return None
    age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    return age if 0 < age < 120 else None


def _rows(data: Any) -> list[dict]:
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):  # tolerate {"key": [rows]}
        for value in data.values():
            if isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
    return []


def _needs_reason_lookup(data: Any) -> bool:
    # TODO(verify): cancel_reason may be text or an id of get_deleteReasons; look it up only when it is numeric.
    return any(str(r.get("cancel_reason") or "").isdigit() for r in _rows(data))


def _to_history(row: dict, own_instructor_ids: set[str], reasons: dict[str, str]) -> HistoryEntry | None:
    try:
        date = dt.datetime.strptime(str(row.get("date") or ""), "%d/%m/%Y").date()
    except ValueError:
        parsed = _parse_dt(row.get("orderdate"))
        if parsed is None:
            return None
        date = parsed.date()
    reason = str(row.get("cancel_reason") or "").strip()
    reason = reasons.get(reason, reason)
    # TODO(verify): meaning of event_status codes; cancellation is detected from cancel_reason for now.
    if reason:
        status = Status.CANCELLED
    elif str(row.get("isFutureAppointment")) == "1":
        status = Status.PLANNED
    else:
        status = Status.DONE
    kind = Kind.OTHER if row.get("theory_id") else _kind(row.get("timesheetcode"), row.get("driverlicenceId"))
    return HistoryEntry(
        date=date,
        start=str(row.get("start") or "")[:5],
        instructor=str(row.get("instructorName") or "").strip(),
        mine=str(row.get("instructorId")) in own_instructor_ids,
        kind=kind,
        sequence=_sequence(row.get("lessonSequence")),
        status=status,
        cancel_reason=reason,
    )
