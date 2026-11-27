# Instructor Radar – Home Assistant app

[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fjoachimcarrein%2FInstructorRadar)

Instructor Radar is a Home Assistant app (add-on) for **driving instructors**. It reads your lesson schedule from your
driving school's online planner and brings it into Home Assistant:

- a **weekly schedule** in the sidebar and the Companion app: lesson number or exam, manual or automatic, and
  optionally the student's name and age;
- per lesson the student's **lessons so far** (date, instructor, cancel reason), with a badge for a **first lesson**
  or a student who is **new to you**;
- a **calendar** for automations (reminder before each lesson, a morning summary), via the Remote Calendar integration;
- a **notification** when a lesson today or tomorrow is added, moved or cancelled.

It fetches at quiet times (default 06:00 and 22:00), holds the planner session for a few seconds and logs out right
away, because planners limit the number of simultaneous sessions per account.

**Supports:** biqsDRIVE. Other planners can be added as a provider module.

> **Unofficial; not affiliated with or endorsed by any planner vendor.**

The UI is available in English, Dutch and French.

## Installation

1. Click the badge above, or go to **Settings › Apps › App store › ⋮ › Repositories** and add
   `https://github.com/joachimcarrein/InstructorRadar`.
2. Install **Instructor Radar** (a prebuilt image for amd64 or aarch64 is downloaded).
3. Fill in the configuration (planner address, login), start it and enable **Show in sidebar**.

See [DOCS.md](instructor_radar/DOCS.md) for the full documentation, including the automation examples.

## Development

Requires Python 3.13.

```sh
cd instructor_radar
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
.venv/bin/python -m app --demo      # synthetic data, http://localhost:8099/
```

Without `SUPERVISOR_TOKEN` the app runs in development mode: a fake Home Assistant, no ingress gate, data under
`.devdata/` (or `$INSTRUCTOR_RADAR_DATA_DIR`).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Security problems: see [SECURITY.md](SECURITY.md).

## License

MIT
