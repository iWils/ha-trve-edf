# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-11-11

The Tempo option.

### Added
- Tempo contracts: subscribed power among those in force in the CRE Tempo grid; the
  off-peak hours are fixed nationally (22:00-06:00), nothing to enter.
- Tempo sensors: the 6 prices (blue, white, red, in peak and off-peak hours), the
  color of the current Tempo day (06:00 to 06:00) and the colors of yesterday, today
  and tomorrow ("unknown" until published). The current price, current period and
  next price change also cover Tempo.
- Tempo colors from Jour Tempo (RTE data redistributed as open data), with a
  fallback source. Only missing colors are asked for: yesterday, today and, from
  10:30 the day before, tomorrow, every 15 minutes while one is missing. Known
  colors are saved, shared by all the Tempo contracts and never asked again.

### Changed
- The current price of a Tempo contract is unavailable while the color of the current
  Tempo day is unknown, rather than possibly wrong.
- Prices of a tariff row are keyed by price (one per period, and per color for
  Tempo); grids saved by 0.1.0 are still read.

## [0.1.0] - 2026-11-11

First version: the Base and HP/HC options of the EDF regulated tariffs (TRVE).
Tempo comes with 0.2.0.

### Added
- Configuration of a contract: tariff option, subscribed power among those in force
  in the CRE grid, and off-peak hours for HP/HC (strictly validated, stored in a
  canonical form, editable in the options). A failed download shows an error that
  can be retried. Several contracts can be added.
- Sensors: current price, current tariff period, yearly subscription, price of each
  period and, for HP/HC, next price change (period switch, or new tariff row at
  midnight). All prices include taxes.
- Tariff grids downloaded once a day from the CRE open data on data.gouv.fr, read by
  column name, with the row in force chosen by its validity dates; dates, decimals
  and encodings are parsed tolerantly. A grid with an invalid row that can still
  apply is rejected; invalid rows that ended before the download day are skipped
  and logged.
- Exact updates at each change of tariff period and at midnight, in French time
  (Europe/Paris) whatever the system time zone, including on daylight saving time
  days; no polling.
- The grid is saved and shared by the contracts of the same option: reused without
  download for a day, and still used after a restart while the CRE cannot be
  reached, up to 7 days after its download. Prices then become unavailable rather
  than possibly wrong, as they do when the grid holds conflicting rows for the same
  power and day.
- Specification (`docs/cahier-des-charges.md`, in French), README in French and
  English, GPL-3.0 license, guidelines for AI-assisted development (`CLAUDE.md`).
- Continuous integration (ruff, strict mypy, tests with coverage, hassfest, HACS
  Action) and automated releases.

[Unreleased]: https://github.com/iWils/ha-trve-edf/compare/0.2.0...HEAD
[0.2.0]: https://github.com/iWils/ha-trve-edf/compare/0.1.0...0.2.0
[0.1.0]: https://github.com/iWils/ha-trve-edf/releases/tag/0.1.0
