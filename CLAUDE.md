# ha-trve-edf — guidelines for AI-assisted development

Home Assistant custom integration (domain `trve_edf`) exposing the EDF regulated
electricity tariffs (TRVE: Base, HP/HC, Tempo) and the price of the kWh in force,
from official open data (CRE prices, RTE Tempo colors).

## Source of truth

- `docs/cahier-des-charges.md` (French) defines the scope, the business rules and
  the architecture. Read it before designing anything. A change of scope or rules
  starts with a change to that document, validated by the maintainer.
- When the code and the specification disagree, stop and ask.

## Clean-room rule

- Never copy, adapt or paraphrase code from `delphiki/hass-tarif-edf` or
  `iWils/hass-tarif-edf`. This project is a new implementation.
- Public facts are fine: data URLs, CSV column names, tariff rules, API formats.
- Expected behaviors (including the bugs found in the old integration) are written
  as test cases, never as reused code.

## Languages

- Code, comments, docstrings, commit messages, `CHANGELOG.md`: English.
- `README.md` in French and `README.en.md` in English: keep both in sync.
- UI translations: `translations/fr.json` and `translations/en.json`;
  `strings.json` is identical to `en.json`.

## Design rules

- Business rules live in `pricing.py`, with no Home Assistant import, and are fully
  unit-tested.
- Network access only in `api.py`, through Home Assistant's shared aiohttp session,
  always with a timeout. Never keep an invalid response: a grid with an invalid row
  that can still apply is rejected; invalid rows that ended before the download day
  are skipped and logged.
- Accuracy first: when a price cannot be known for sure (unknown Tempo color,
  missing tariff row), the entity is unavailable instead of showing a wrong value.
- All time rules use `Europe/Paris`, whatever the system time zone.
- Current price and period are recomputed at the exact period boundaries, not by
  polling every minute.
- Entities: `has_entity_name`, `translation_key`, unique id `f"{entry_id}_{key}"`,
  declared with entity descriptions.
- Read CSV columns by header name, never by position.

## Workflow

- Every behavior change comes with tests.
- Conventional commits (`feat:`, `fix:`, `docs:`, `ci:`, `refactor:`, `test:`…).
- No AI attribution anywhere: no `Co-Authored-By`, session links or "Generated
  with/by" mentions in commits, pull requests or release notes. Commits are signed
  with the maintainer's GitHub identity
  (`iWils <56263502+iWils@users.noreply.github.com>`).
- Work on a branch and open a pull request to `main`; never push to `main` directly.
- Versions follow SemVer: `0.x` during development, `1.0.0` after validation on a
  real Home Assistant instance.
- A release is published automatically when `main` holds a `manifest.json` version
  without tag: bump `version` and add its dated `## [x.y.z] - YYYY-MM-DD` section to
  `CHANGELOG.md` in the same pull request. A version without dated section is
  simply not released yet.

## Commands

Python 3.13. Install the tools once:

```bash
pip install -r requirements_test.txt -r requirements_lint.txt
```

Run before every push (the CI runs the same checks):

```bash
ruff check .
ruff format --check .
mypy
pytest
```

- `pytest` measures the coverage and fails below 90 %.
- The CI also runs the tests on the oldest supported Home Assistant (2025.1). To do
  the same locally, use a separate virtualenv outside the repository:
  `python3.13 -m venv ../venv-ha2025.1 && ../venv-ha2025.1/bin/pip install -r requirements_test_min.txt`,
  then `../venv-ha2025.1/bin/python -m pytest`.
- `mypy` runs in strict mode on `custom_components`, `tests` and `.github/scripts`.
- Validation of the integration (hassfest, HACS Action) only runs in the CI
  (`.github/workflows/validate.yml`).
