"""Print the CHANGELOG.md section of a version, used as GitHub release notes.

Usage: python3 .github/scripts/release_notes.py VERSION

Exit codes:
    0  the notes are printed
    1  the version has no dated section yet: it is not ready to be released
    2  wrong usage
    3  the dated section of the version is empty
"""

from __future__ import annotations

from pathlib import Path
import re
import sys

CHANGELOG = Path(__file__).resolve().parents[2] / "CHANGELOG.md"


class MissingSectionError(LookupError):
    """The version has no dated section."""


class EmptySectionError(LookupError):
    """The dated section of the version has no content."""


def release_notes(version: str, changelog: str) -> str:
    """Return the body of the "## [version] - YYYY-MM-DD" section."""
    pattern = re.compile(
        rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}\n"
        r"(?P<body>.*?)"
        r"(?=^## \[|^\[[^\]]+\]: |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(changelog)
    if match is None:
        raise MissingSectionError(
            f"CHANGELOG.md has no '## [{version}] - YYYY-MM-DD' section"
        )
    body = match.group("body").strip()
    if not body:
        raise EmptySectionError(f"The CHANGELOG.md section of {version} is empty")
    return body


def main(argv: list[str]) -> int:
    """Run the command line interface."""
    if len(argv) != 2:
        print(f"Usage: {argv[0]} VERSION", file=sys.stderr)
        return 2
    try:
        print(release_notes(argv[1], CHANGELOG.read_text(encoding="utf-8")))
    except MissingSectionError as err:
        print(err, file=sys.stderr)
        return 1
    except EmptySectionError as err:
        print(err, file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
