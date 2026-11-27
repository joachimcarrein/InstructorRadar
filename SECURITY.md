# Security policy

Instructor Radar handles a planner login and lesson data about students. Please report security problems
**privately**: [open a private security advisory](https://github.com/joachimcarrein/InstructorRadar/security/advisories/new)
(Security › Report a vulnerability). Do not open a public issue.

Please include the Instructor Radar version, what an attacker could do, and how to reproduce it (with made-up data).
You will get a reply within a week. Fixes are released as a new version; the advisory is published once the update
is available.

Only the latest version is supported.

## What Instructor Radar relies on

- The UI is reachable only through Home Assistant ingress: it answers only the Supervisor (172.30.32.2).
  Everybody who can log in to Home Assistant can see the schedule, by design.
- The calendar feed (port 8100) is not mapped to the host and answers only Home Assistant's internal network.
- The planner login and 2FA secret live only in the add-on options (password fields). They are never logged.
- Planner providers call an allowlist of read-only endpoints; write actions are refused before a request is made.
- Student contact data is dropped inside the provider; tests check that it never reaches storage, UI, calendar or logs.
- Its own AppArmor profile: it can only write to its data folder and `/tmp`.
- Signed images built by GitHub Actions from this repository.
