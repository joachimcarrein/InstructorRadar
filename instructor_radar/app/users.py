"""Per Home Assistant user settings (/data/users.json): language, notification preferences, what was already sent.

The user comes from the ingress header X-Remote-User-Id (set by the Supervisor). Nothing else about the user is stored.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path

from .i18n import LANGUAGES, normalize
from .settings import NotifyPrefs

USER_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SENT_KEEP_DAYS = 3


class UserSettings:
    def __init__(self, path: Path):
        self.path = path
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._users: dict[str, dict] = data if isinstance(data, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError):
            self._users = {}
        self._last_user: str | None = next(iter(sorted(
            self._users, key=lambda u: self._users[u].get("seen", 0), reverse=True)), None)

    @staticmethod
    def valid(user_id: str | None) -> bool:
        return bool(user_id and USER_ID.match(user_id))

    # ---------------------------------------------------------------- language

    def language(self, user_id: str | None) -> str:
        """The explicit choice ('' = automatic)."""
        return str(self._users.get(user_id or "", {}).get("language", ""))

    def set_language(self, user_id: str, language: str) -> None:
        if language and language not in LANGUAGES:
            raise ValueError("unknown language")
        self._users.setdefault(user_id, {})["language"] = language
        self._save()

    def effective_language(self, user_id: str) -> str | None:
        """Explicit choice, else the language of the user's last visit."""
        user = self._users.get(user_id, {})
        lang = user.get("language") or user.get("last")
        return normalize(lang) if lang else None

    def seen(self, user_id: str, effective: str, counter: int) -> None:
        """Remember the language this user actually sees (for notifications); writes only on change."""
        user = self._users.setdefault(user_id, {})
        changed = user.get("last") != effective or self._last_user != user_id
        user["last"] = effective
        user["seen"] = counter
        self._last_user = user_id
        if changed:
            self._save()

    def notification_language(self) -> str | None:
        """Language of the most recent visitor (explicit choice first), or None when nobody visited yet."""
        return self.effective_language(self._last_user) if self._last_user else None

    # ---------------------------------------------------------------- notifications

    def notify(self, user_id: str) -> NotifyPrefs:
        return NotifyPrefs.from_dict(self._users.get(user_id, {}).get("notify"))

    def set_notify(self, user_id: str, prefs: NotifyPrefs) -> None:
        self._users.setdefault(user_id, {})["notify"] = prefs.to_dict()
        self._save()

    def recipients(self) -> list[tuple[str, NotifyPrefs]]:
        """Users with at least one device and one notification type switched on."""
        result = []
        for user_id in sorted(self._users):
            prefs = self.notify(user_id)
            if prefs.active:
                result.append((user_id, prefs))
        return result

    def was_sent(self, user_id: str, key: str) -> bool:
        return key in self._users.get(user_id, {}).get("sent", {})

    def mark_sent(self, user_id: str, key: str, today: dt.date) -> None:
        sent = self._users.setdefault(user_id, {}).setdefault("sent", {})
        sent[key] = today.isoformat()
        cutoff = (today - dt.timedelta(days=SENT_KEEP_DAYS)).isoformat()
        for k in [k for k, v in sent.items() if v < cutoff]:
            del sent[k]
        self._save()

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._users, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)
