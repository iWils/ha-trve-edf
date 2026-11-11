"""Tests of the consistency of the translation files."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

INTEGRATION = Path(__file__).resolve().parents[1] / "custom_components" / "trve_edf"
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def load(name: str) -> dict[str, Any]:
    """Load a translation file of the integration."""
    data: dict[str, Any] = json.loads((INTEGRATION / name).read_text(encoding="utf-8"))
    return data


def flatten(data: dict[str, Any], prefix: str = "") -> dict[str, str]:
    """Return the translated strings by key path."""
    strings: dict[str, str] = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            strings.update(flatten(value, path))
        else:
            strings[path] = value
    return strings


async def test_strings_json_is_the_english_translation() -> None:
    """strings.json and translations/en.json are identical."""
    assert load("strings.json") == load("translations/en.json")


async def test_french_and_english_have_the_same_keys_and_placeholders() -> None:
    """Every English string has a French translation with the same placeholders."""
    english = flatten(load("translations/en.json"))
    french = flatten(load("translations/fr.json"))

    assert french.keys() == english.keys()
    for path, text in english.items():
        assert set(PLACEHOLDER.findall(french[path])) == set(
            PLACEHOLDER.findall(text)
        ), path
