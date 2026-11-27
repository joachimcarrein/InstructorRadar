# Changelog

## Unreleased

- **Settings inside the app.** *For everyone*: days ahead, fetch times, show student names and ages (these were add-on
  options). *My notifications*, per Home Assistant user like in MedStock: the devices (Companion app phones
  suggested), schedule changes (days ahead), a **reminder before each lesson** and a **morning summary**, plus a test
  notification. The YAML examples for these are no longer needed.
- The add-on configuration now holds only the planner login and the log level. The old values are carried over when
  the Supervisor still provides them; check **Settings** once after updating. A former `notify_service` is not carried
  over: pick your devices in **Settings › My notifications**.
- Documentation: the internal calendar port (8100) is explained in its own section.

- Lesson details: the student's number of lessons (in lesson units, "11-12" = 2) and driving hours, both as
  driven + planned; exams and cancelled lessons do not count. Hours appear after the student's next history refresh
  (the first fetch of a day).
- Lesson details: all the student's lessons including future ones, with the opened lesson marked.
- Week view on a computer: the lesson number or "Exam" is shown on the same line as the time.
- iPhone: no more focus ring around the close button when the lesson details open.

## 2026.11.0

- First version. Reads a driving instructor's schedule from the school's biqsDRIVE planner at quiet times (default
  06:00 and 22:00), in one short session with an explicit logout.
- Weekly schedule in the sidebar: lesson number or exam, manual or automatic, optional student name and age, badges
  for a first lesson, a student who is new to you and a changed lesson; on a phone a list per day.
- Lesson details with the student's lessons so far (date, instructor, cancel reason).
- Changes page and a notification for changes to lessons in the next days (`notify_changes_days`), through a notify
  service or a persistent notification.
- Calendar feed for the Remote Calendar integration (internal port 8100, not mapped to the host).
- Login problems, captchas and unexpected planner answers raise a persistent notification and are not retried
  before the next fetch time; when all planner sessions are in use the old schedule is kept and one retry follows.
- English, Dutch (with Belgian words) and French; language per Home Assistant user.
