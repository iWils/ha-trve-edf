"""Tests of the automated release tooling.

The Release workflow publishes the manifest version once CHANGELOG.md has its
dated section, using that section as release notes.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "release_notes.py"
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")

CHANGELOG = """# Changelog

## [Unreleased]

## [1.1.0] - 2027-02-01

### Fixed
- Something.

## [1.0.0] - 2027-01-01

[Unreleased]: https://example.org/compare/1.1.0...HEAD
"""


def load_script() -> ModuleType:
    """Import the release notes script as a module."""
    spec = importlib.util.spec_from_file_location("release_notes", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manifest_version() -> str:
    """Return the version of the integration manifest."""
    manifest = ROOT / "custom_components" / "trve_edf" / "manifest.json"
    version: str = json.loads(manifest.read_text(encoding="utf-8"))["version"]
    return version


def run_script(version: str) -> subprocess.CompletedProcess[str]:
    """Run the release notes script on the real changelog."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), version],
        capture_output=True,
        text=True,
        check=False,
    )


async def test_manifest_version_is_semver() -> None:
    """The manifest version follows SemVer."""
    assert SEMVER.match(manifest_version())


async def test_manifest_version_is_releasable_or_pending() -> None:
    """The manifest version is either ready (valid notes) or not dated yet."""
    result = run_script(manifest_version())

    assert result.returncode in (0, 1), result.stderr
    if result.returncode == 0:
        assert result.stdout.startswith("### ")


async def test_notes_of_a_dated_section() -> None:
    """The notes stop before the next section."""
    notes = load_script().release_notes("1.1.0", CHANGELOG)

    assert notes == "### Fixed\n- Something."


async def test_missing_section() -> None:
    """A version without dated section is not ready."""
    script = load_script()

    with pytest.raises(script.MissingSectionError):
        script.release_notes("2.0.0", CHANGELOG)


async def test_empty_section() -> None:
    """A dated section without content is an error."""
    script = load_script()

    with pytest.raises(script.EmptySectionError):
        script.release_notes("1.0.0", CHANGELOG)


async def test_exit_code_of_a_missing_section() -> None:
    """The command line exits with 1 when the version has no section."""
    result = run_script("0.0.0")

    assert result.returncode == 1
    assert "0.0.0" in result.stderr
