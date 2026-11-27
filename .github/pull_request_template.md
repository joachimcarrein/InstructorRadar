## What and why

<!-- What does this change, and why? Link the issue if there is one. -->

## Checklist

- [ ] Tests added or updated; `pytest` and `ruff check .` pass in `instructor_radar/`
- [ ] User-visible change: a line under `## Unreleased` in `instructor_radar/CHANGELOG.md` (and `DOCS.md` when needed)
- [ ] New UI text in every `app/locales/<lang>.json` (English and each translation)
- [ ] No real data (student or instructor names, phone numbers, schools) in code, tests, fixtures, screenshots or logs
- [ ] Planner provider: only read-only endpoints, one short session per run, logout always
