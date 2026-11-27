# Contributing to Instructor Radar

Thanks for helping! Instructor Radar logs in to a driving school planner with someone's own account and handles data
about students, so a few rules are stricter than usual.

## Ground rules

- **No real data.** Never put real student, instructor or school names, phone numbers, planner addresses or
  screenshots of a real schedule in code, tests, fixtures, issues or logs. Use made-up data (see `tests/fixtures/`)
  or the demo mode (`--demo`).
- **No credentials anywhere** except the add-on options: not in code, tests, fixtures, logs or commits.
- **Logs contain counts only** at every level: no lesson details, no names, no tokens.
- **Be gentle with the planner.** Planners limit simultaneous sessions per account: one short session per run
  (login, sequential reads, logout in `finally`), no keep-alive, no session reuse, no retry after a refused login.
- **Read-only.** A provider only calls endpoints on its allowlist, and only ones that read.
- **No external calls** except the planner and the Supervisor. No telemetry.
- **English** for code, comments, commits and docs.

## Development

Requires Python 3.13.

```sh
cd instructor_radar
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check . && .venv/bin/pytest
.venv/bin/python -m app --demo
```

Open <http://localhost:8099/>. In development the app uses a fake Home Assistant, the user `dev` and data under
`.devdata/` (or `$INSTRUCTOR_RADAR_DATA_DIR`). Ingress URLs: every link is relative to the `base` template variable
(the `X-Ingress-Path` prefix); never write a literal `/...` URL in templates or JavaScript.

- **UI texts:** add every key to `app/locales/en.json` and to each language file (`nl.json`, `fr.json`, ...). A test
  fails when a language misses a key or a placeholder (`{name}`).
- **A new language:** copy `nl.json` to `<code>.json` and translate it. It is found at start-up and offered in the
  language menu.
- **Regional variants:** `nl-BE.json` holds only the words that differ in Belgium (e.g. *Manueel*); every other text
  falls back to `nl.json`, then English. A regional file needs its language file and may only contain keys English
  has; the tests check both.
- **A new planner:** add `app/providers/<name>.py` implementing `Provider` (`login`, `fetch_events`,
  `fetch_student`, `logout`), register it in `app/providers/__init__.py`, add it to `provider` in `config.yaml`, and
  test it against a fake server with synthetic fixtures (see `tests/conftest.py`). Drop all personal data inside the
  provider. Unverified behaviour goes into small functions marked `TODO(verify)`.

## Pull requests

1. Fork, create a branch, make the change with tests.
2. Add a line under `## Unreleased` in `instructor_radar/CHANGELOG.md` for every user-visible change. Do **not** change
   the version: that happens at release time.
3. Open a pull request. CI runs lint and tests, the Docker build and a smoke test under the AppArmor profile. The
   maintainer reviews every pull request before it is merged.

## Releases (maintainer)

**Actions › Release › Run workflow** (or `gh workflow run release.yaml`). Versions follow the date like Home
Assistant: `YEAR.MONTH.N`; the workflow picks the next number itself. It bumps the version, turns `## Unreleased`
into the release notes, tests, builds and signs the images, checks that they can be pulled, and only then updates
`main` and creates the tag and GitHub release. Home Assistant offers the update as soon as `main` has the new version.
