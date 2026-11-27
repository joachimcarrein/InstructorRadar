"""Per Home Assistant user settings (/data/users.json): the chosen language and the language of the last visit.

The user comes from the ingress header X-Remote-User-Id (set by the Supervisor). Nothing else is stored.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .i18n import LANGUAGES, normalize

USER_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


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

    def language(self, user_id: str | None) -> str:
        """The explicit choice ('' = automatic)."""
        return str(self._users.get(user_id or "", {}).get("language", ""))

    def set_language(self, user_id: str, language: str) -> None:
        if language and language not in LANGUAGES:
            raise ValueError("unknown language")
        self._users.setdefault(user_id, {})["language"] = language
        self._save()

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
        if not self._last_user:
            return None
        user = self._users.get(self._last_user, {})
        lang = user.get("language") or user.get("last")
        return normalize(lang) if lang else None

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._users, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)
