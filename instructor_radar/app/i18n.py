"""UI and notification texts, one JSON file per language in app/locales/.

- en.json is the reference: every key lives there.
- <lang>.json (nl, fr, ...) is a full translation: the same keys and placeholders as English.
- <lang>-<REGION>.json (nl-BE, ...) holds only the words that differ in that region; every other text falls back to
  <lang>.json, then to English. A regional file needs its language file.
Adding a language = adding a file: it is found at start-up and offered in the language menu.
"""

from __future__ import annotations

import json
from pathlib import Path

LOCALES = Path(__file__).parent / "locales"


def _load() -> dict[str, dict[str, str]]:
    texts = {}
    for path in sorted(LOCALES.glob("*.json")):
        texts[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return texts


TEXTS: dict[str, dict[str, str]] = _load()
LANGUAGES = sorted(code for code in TEXTS if "-" not in code)  # full languages (menu)


def _canonical(code: str) -> str:
    """'nl-be' / 'nl_BE' -> 'nl-BE'."""
    parts = code.replace("_", "-").split("-")
    return parts[0].lower() + ("-" + parts[1].upper() if len(parts) > 1 and parts[1] else "")


def normalize(lang: str | None) -> str:
    """The most specific available locale for a code: 'nl-BE' -> 'nl-BE', 'nl-NL' -> 'nl', 'de' -> 'en'."""
    code = _canonical((lang or "en").strip())
    if code in TEXTS:
        return code
    base = code.split("-")[0]
    return base if base in TEXTS else "en"


def pick_language(accept_language: str | None) -> str:
    """First supported language of an Accept-Language header (in the order the browser lists them)."""
    for part in (accept_language or "").split(","):
        code = part.split(";")[0].strip()
        if not code or code == "*":
            continue
        found = normalize(code)
        if found != "en" or code.lower().startswith("en"):
            return found
    return "en"


class Translator:
    def __init__(self, lang: str | None):
        self.lang = normalize(lang)
        chain = [self.lang]
        if "-" in self.lang:
            chain.append(self.lang.split("-")[0])
        if "en" not in chain:
            chain.append("en")
        self._chain = [TEXTS[c] for c in chain if c in TEXTS]
        self.html_lang = self.lang
        self.weekdays = self("weekdays").split(",")

    def __call__(self, key: str, **kwargs) -> str:
        text = next((t[key] for t in self._chain if key in t), key)
        return text.format(**kwargs) if kwargs else text


def language_names() -> list[tuple[str, str]]:
    """(code, own name) of every full language, for the language menu."""
    return [(code, TEXTS[code].get("language_name", code)) for code in LANGUAGES]
