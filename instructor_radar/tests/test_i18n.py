"""Language files follow the MedStock rules: full languages complete, regional files only the words that differ."""

import re

import pytest

from app.i18n import LANGUAGES, TEXTS, Translator, language_names, normalize, pick_language


def _placeholders(text):
    return set(re.findall(r"{(\w+)}", text))


def test_english_is_the_reference_and_languages_are_found():
    assert "en" in TEXTS and {"nl", "fr"} <= set(LANGUAGES)
    assert "nl-BE" in LANGUAGES  # regional variants can be chosen too
    names = dict(language_names())
    assert names["nl"] == "Nederlands" and names["nl-BE"] == "Nederlands (België)"
    assert all(names[code] != code for code in LANGUAGES)  # every file has its own name


@pytest.mark.parametrize("lang", [code for code in TEXTS if "-" not in code])
def test_full_language_has_every_key_and_placeholder(lang):
    english = TEXTS["en"]
    assert set(TEXTS[lang]) == set(english)
    for key, text in TEXTS[lang].items():
        assert _placeholders(text) == _placeholders(english[key]), key
    assert len(TEXTS[lang]["weekdays"].split(",")) == 7


@pytest.mark.parametrize("region", [code for code in TEXTS if "-" in code])
def test_regional_file_only_overrides(region):
    base = region.split("-")[0]
    assert base in TEXTS, f"{region} needs {base}.json"
    assert set(TEXTS[region]) <= set(TEXTS["en"])
    for key, text in TEXTS[region].items():
        assert text != TEXTS[base][key], f"{region}:{key} is the same as {base}; remove it"
        assert _placeholders(text) == _placeholders(TEXTS["en"][key])


def test_fallback_chain():
    assert Translator("nl-BE")("manual") == "Manueel"
    assert Translator("nl-BE")("schedule") == "Planning"  # from nl.json
    assert Translator("nl-NL")("manual") == "Handgeschakeld"
    assert Translator("de")("schedule") == "Schedule"


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("nl-BE,nl;q=0.9,en;q=0.8", "nl-BE"),
        ("nl-NL", "nl"),
        ("de-DE,fr;q=0.8", "fr"),
        ("en-US,nl;q=0.5", "en"),
        ("", "en"),
        ("*", "en"),
    ],
)
def test_pick_language(header, expected):
    assert pick_language(header) == expected


def test_normalize():
    assert normalize("nl_be") == "nl-BE"
    assert normalize(None) == "en"
