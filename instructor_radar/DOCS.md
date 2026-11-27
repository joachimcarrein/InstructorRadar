# Instructor Radar

Instructor Radar brings a driving instructor's lesson schedule from the driving school's online planner into Home
Assistant: a weekly schedule in the sidebar, a calendar for automations, and a notification when a lesson is added,
moved or cancelled.

> **Unofficial.** Instructor Radar is not affiliated with or endorsed by any planner vendor. It reads the planner the
> way your browser does, with your own account. Planners change without notice; when that happens Instructor Radar
> stops with a clear message instead of guessing.

**Supports:** biqsDRIVE.

## Requirements

- Home Assistant OS or Supervised (apps/add-ons), amd64 or aarch64.
- Your own instructor account on the driving school's planner (the same login you use in the browser).

## Install and update

1. **Settings › Apps › App store › ⋮ › Repositories**, add `https://github.com/joachimcarrein/InstructorRadar`.
2. Install **Instructor Radar** (a prebuilt image is downloaded).
3. Open the **Configuration** tab, fill in your planner login (see *Add-on configuration*) and save.
4. Start it and enable **Show in sidebar**.
5. Open the app and set it up in **Settings** (fetch times, names, notifications).

The very first start fetches once, so the schedule is not empty. After that it only fetches at the fetch times set in **Settings**.

## Important: the planner's session limit

The planner allows only a few simultaneous sessions per account (biqsDRIVE reports 2 for a typical account). Every
fetch logs in, reads what it needs, and **logs out right away** (usually within a few seconds). Still:

- **Fetch outside working hours.** The defaults are 06:00 and 22:00 (**Settings › For everyone**). If you add fetch times during the day, a fetch
  may take a session slot while you or the office are using the planner.
- **When all sessions are in use**, Instructor Radar does not fight for one: it keeps the schedule it already has,
  shows *Planner busy* and tries once more after 15 minutes, then waits for the next fetch time.
- **Fetch now** (the button, or `hassio.addon_stdin`) is limited to once every 2 minutes.
- A **refused login** (wrong password, 2FA, captcha) raises a notification in Home Assistant and is **not retried**
  until the next fetch time, so the account cannot get locked by repeated attempts.

## Add-on configuration

The add-on's **Configuration** tab holds only the planner login. Everything else is set inside the app.

| Option | Default | Meaning |
|---|---|---|
| `provider` | `biqsdrive` | Which planner your school uses. |
| `base_url` | – | **Required.** Your school's planner address, e.g. `https://yourschool.example` (each school has its own). |
| `username`, `password` | – | Your planner login. Stored only in the add-on options. |
| `auth_mode` | `none` | `none` (no 2FA), `totp` (2FA with an authenticator app), `manual` (not implemented yet). |
| `totp_secret` | – | For `totp`: the secret key of the authenticator (the text behind the QR code). |
| `log_level` | `info` | `debug` for troubleshooting (still no lesson details in the log). |

## Settings (in the app)

### For everyone

| Setting | Default | Meaning |
|---|---|---|
| Days ahead to fetch | 14 | The current week (from Monday) is always included. |
| Fetch times | 06:00, 22:00 | Local times, separated by commas. Keep them outside working hours (see above). A change applies right away. |
| Show student names | off | In the schedule, the calendar and notifications. |
| Show student ages | off | Next to the name. |

Switching names or ages **off** removes the stored ones right away; switching them **on** shows them after the next
fetch.

### My notifications

Each Home Assistant user chooses their own, like in MedStock:

- **Devices**: the `notify.*` services of Home Assistant. The phones of the Companion app are listed first and are
  ticked until you save once.
- **Schedule changes** (on by default): new, moved or cancelled lessons from today up to *N* days ahead (default 2 =
  today and tomorrow), noticed at a fetch.
- **Reminder before each lesson** (off by default): *N* minutes before the start (default 30).
- **Morning summary** (off by default): today's lessons at a time of your choice (default 06:30; choose a time after
  a fetch time). Nothing is sent on a day without lessons.
- **Send test notification** sends a test to the devices you saved.

Notifications are written in your language (see *Language*). Reminders and summaries are sent at most 30 minutes late
(for example after a restart), never later, and only once. They use the schedule of the last fetch, so a lesson
cancelled since then is still reminded (see *Changes during the day*).

As long as **nobody** has set up notifications, schedule changes appear as a notification in Home Assistant itself.

## Using it

### Schedule (sidebar)

A week view from Monday, with each lesson as a card:

- time, **Lesson 11-12** or **Exam**, **Manual** / **Automatic** (also by colour; exams have their own colour);
- the student's name (and age) when enabled;
- **First lesson**: the student has had no lessons yet;
- **New to you**: the student has had lessons, but never with you;
- **Changed**: the lesson changed in the last fetch.

Tap a card for the details and the student's **lessons so far**: date, instructor (*you* for your own) and, for a
cancelled lesson, the reason. On a phone the week becomes a list per day that opens at today.

**Changes** lists what changed this week (new, moved, removed), with when it was noticed. Older weeks are removed
automatically: Instructor Radar keeps the current week and what lies ahead, nothing else.

**Language**: the menu at the top, per Home Assistant user (English, Nederlands, Français). *Automatic* follows your browser or app language
(Belgian Dutch gets Belgian words). Your notifications use your language; notifications shown in Home Assistant itself use the language of the
last person who opened the app, or Home Assistant's language before anyone has.

### Calendar entity in Home Assistant (optional)

You do not need this for the schedule or the notifications above. It is for when you want the lessons as a
**calendar entity** in Home Assistant, e.g. on a dashboard calendar card or in your own automations.

**What it is.** Instructor Radar offers the schedule as an iCalendar feed on port **8100**. That port lives only on
Home Assistant's internal network (the network between Home Assistant and its add-ons):

- it is **not** opened on your Home Assistant host, your home network or the internet (the port is not listed in the
  add-on's *Network* settings and cannot be mapped);
- only Home Assistant itself can read it; every other caller is refused;
- it contains the same lessons as the schedule page (student names only when *Show student names* is on);
- it is never written to `/config/www`, because everything under `/local` can be read without logging in.

Because it is internal, you **cannot** subscribe to it from your phone's agenda app (see FUTURE_IDEAS.md in the
repository).

**Set it up:**

1. Find the add-on's hostname on its **Info** tab (e.g. `a0d7b954-instructor-radar`).
2. **Settings › Devices & services › Add integration › Remote Calendar**, name it `Instructor Radar` and use the URL
   `http://<hostname>:8100/calendar.ics`.

You now have `calendar.instructor_radar`, with events titled like `Les 7 – B manueel – Centrum`.

### Fetch now from an automation

Counts against the planner's session limit (see above):

```yaml
action: hassio.addon_stdin
data:
  addon: <the add-on slug from its Info tab, e.g. a0d7b954_instructor_radar>
  input: fetch
```

### Changes during the day

Instructor Radar fetches only at quiet times, so a lesson booked at 10:00 for 14:00 would be missed until the
evening. The planner itself can tell you right away:

1. Ask the driving school to enable **Calendar Notifications** on your instructor record. You then get an e-mail for
   every new or changed lesson.
2. Add the **IMAP** integration in Home Assistant for that mailbox (enable *Event message data → text*).
3. Forward those e-mails as a push notification:

```yaml
alias: "Planner e-mail: lesson changed"
triggers:
  - trigger: event
    event_type: imap_content
    event_data:
      sender: "planner-sender@yourschool.example"   # the sender of the planner's e-mails
actions:
  - action: notify.mobile_app_my_phone
    data:
      title: "{{ trigger.event.data.subject }}"
      message: "{{ trigger.event.data.text[:300] }}"
```

The schedule in Instructor Radar catches up at the next fetch time.

## Privacy

- Only what is needed for the schedule is kept: times, lesson number, licence, manual/automatic, location, status,
  and the student's name and age **only when you enable them**. Phone numbers, addresses, e-mail addresses,
  birthdates and ID numbers are dropped inside the planner module before anything is stored, shown or logged.
- For the student history (and age) the planner's student page is read; only the birthdate (to calculate the age)
  and the lesson list are used, the rest is discarded at once.
- Switching *Show student names* or *Show student ages* off removes the stored names and ages right away.
- The log contains counts only (lessons, changes, requests), never lesson or student details, never your password.
- Nothing is sent anywhere except to your planner and to Home Assistant itself. No telemetry.
- Data lives in the add-on's `/data` folder (part of Home Assistant backups): `state.json` (schedule from this week's
  Monday, history of the students in it, change log), `settings.json` (the settings for everyone) and `users.json`
  (per Home Assistant user: language, notification devices and choices, which reminders were sent).

## Troubleshooting

| You see | What to do |
|---|---|
| *The planner refused the login* | Check username, password and `auth_mode` / `totp_secret`. It tries again at the next fetch time. |
| *The planner asks for a captcha* | Log in once in a browser; then wait for the next fetch time. |
| *Planner busy* | All sessions were in use. Nothing to do; the next fetch will catch up. Consider quieter fetch times. |
| *HTML instead of JSON* / *looks different than expected* | The planner changed. Open an issue (without personal data) with the log. |
| Calendar entity stays empty | Check the hostname and port `8100` in the Remote Calendar URL. |
| No notifications on my phone | **Settings › My notifications**: tick the phone, **Save**, then **Send test notification**. |

## Limitations

- Read-only: Instructor Radar never changes anything in the planner.
- One instructor account per installation.
- Changes between fetch times are only seen at the next fetch (see *Changes during the day*).
- `auth_mode: manual` (entering a 2FA code yourself) is not implemented yet.
