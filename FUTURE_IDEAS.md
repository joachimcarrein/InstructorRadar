# Future ideas

Not planned yet; open an issue to discuss one.

- **Phone agenda subscription.** Adding the calendar to the phone's own agenda app needs an address the phone can
  reach without logging in to Home Assistant (ingress needs a login, the internal port 8100 is not reachable from
  outside). Options: an optional mapped port with a secret token in the URL (exposed through a VPN or reverse proxy),
  or per-lesson "add to agenda" downloads (a one-off copy that does not follow later changes).
- **Home Assistant entities and actions** (for automations and dashboards, beyond the web UI and notifications).
  - *How*: an add-on cannot register entities by itself. Options, best first:
    1. **MQTT discovery** (needs the Mosquitto add-on): real entities with a unique id (editable, in areas, history),
       grouped under one *Instructor Radar* device, plus `button` entities for actions. Retained, so they survive an
       HA restart. Most add-ons do it this way.
    2. A small **custom integration** (HACS) that reads the add-on's API: also a native `calendar` entity and
       proper actions (`instructor_radar.fetch`), but a second thing to install and maintain.
    3. `POST /api/states/...` with the Supervisor token: no extra install, but no unique id (not editable in the
       UI) and gone after an HA restart until the next push. Fine for a first try only.
  - *Sensors* (names/ages only when that option is on, like everywhere else):
    - **Next lesson** (timestamp) with attributes kind, sequence, licence/gear, location, student; drives
      "leave in 15 min" or car pre-heating automations.
    - **First lesson today / tomorrow** (timestamp): for the alarm clock or a morning routine.
    - **Lesson in progress** (binary): phone to do-not-disturb during a lesson, back to normal afterwards.
    - **Lessons today / this week** (count) and **driving hours planned this week** (dashboard).
    - **Next exam** (timestamp, student, attempt) and **last exam result**.
    - **Changes since last seen** (count) with the latest change as attributes; resets when the Changes page is
      opened.
    - **Planner status** (ok / busy / error) with last successful fetch (timestamp), and a **problem** binary
      sensor for an alert automation (replaces the persistent notification for those who prefer that).
  - *Actions* (buttons with MQTT, actions with an integration):
    - **Fetch now**: same rate limit as the UI button; replaces `hassio.addon_stdin` with `fetch` (stdin stays as a
      fallback, it needs no MQTT).
    - **Send morning summary now** / **send test notification**.
    - **Mark changes as seen** (clears the *Changed* badges).
- **`auth_mode: manual`**: enter a 2FA code in the UI when a fetch needs one.
- **More planners** as provider modules.
- Verify on the real planner and remove the `TODO(verify)` markers in `providers/biqsdrive.py` (session-limit
  behaviour, `?e=` codes, `statusConfirmed`, history `event_status` codes).
