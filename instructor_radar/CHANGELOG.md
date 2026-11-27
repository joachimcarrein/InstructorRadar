# Changelog

## Unreleased

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
