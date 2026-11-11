# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-11-11

First version: the Base and HP/HC options of the EDF regulated tariffs (TRVE).
Tempo comes with 0.2.0.

### Added
- Configuration of a contract: tariff option, subscribed power among those in force
  in the CRE grid, and off-peak hours for HP/HC (strictly validated, stored in a
  canonical form, editable in the options). Several contracts can be added.
- Sensors: current price, current tariff period, yearly subscription, price of each
  period and, for HP/HC, next price change. All prices include taxes.
- Tariff grids downloaded once a day from the CRE open data on data.gouv.fr, read by
  column name, with the row in force chosen by its validity dates; dates, decimals
  and encodings are parsed tolerantly and invalid grids are rejected.
- Exact updates at each change of tariff period and at midnight, in French time
  (Europe/Paris) whatever the system time zone, including on daylight saving time
  days; no polling.
- The last known prices are kept for up to 7 days when the grid cannot be
  downloaded, then become unavailable rather than possibly wrong.
- Specification (`docs/cahier-des-charges.md`, in French), README in French and
  English, GPL-3.0 license, guidelines for AI-assisted development (`CLAUDE.md`).
- Continuous integration (ruff, strict mypy, tests with coverage, hassfest, HACS
  Action) and automated releases.

[Unreleased]: https://github.com/iWils/ha-trve-edf/compare/0.1.0...HEAD
[0.1.0]: https://github.com/iWils/ha-trve-edf/releases/tag/0.1.0
