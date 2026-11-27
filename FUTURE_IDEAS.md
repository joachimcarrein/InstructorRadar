# Future ideas

Not planned yet; open an issue to discuss one.

- **Phone agenda subscription.** Adding the calendar to the phone's own agenda app needs an address the phone can
  reach without logging in to Home Assistant (ingress needs a login, the internal port 8100 is not reachable from
  outside). Options: an optional mapped port with a secret token in the URL (exposed through a VPN or reverse proxy),
  or per-lesson "add to agenda" downloads (a one-off copy that does not follow later changes).
- **`auth_mode: manual`**: enter a 2FA code in the UI when a fetch needs one.
- **More planners** as provider modules.
- Verify on the real planner and remove the `TODO(verify)` markers in `providers/biqsdrive.py` (session-limit
  behaviour, `?e=` codes, `statusConfirmed`, history `event_status` / `cancel_reason` codes, `LESSON_EXAM`).
