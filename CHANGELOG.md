# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-11-11

Quality.

### Added
- Reconfiguration: change the option, the subscribed power or the off-peak hours of
  a contract without removing it (⋮ menu → Reconfigure); the current values are
  suggested and the sensors of a former option are removed.
- Repair issue when the subscribed power has no tariff in force in the CRE grid,
  cleared when it comes back or when the contract is removed.
- Diagnostics of a contract: grid in use, tariff in force, computed period and
  price, next price change and known Tempo colors, without personal data.
- Icons for every sensor.
- The tests also run on Home Assistant 2025.1, the minimum version.

### Changed
- Invalid off-peak hours show a precise message: no range, bad format, same start
  and end, or overlapping ranges.

## [0.2.0] - 2026-11-11

The Tempo option.

### Added
- Tempo contracts: subscribed power among those in force in the CRE Tempo grid; the
  off-peak hours are fixed nationally (22:00-06:00), nothing to enter.
- Tempo sensors: the 6 prices (blue, white, red, in peak and off-peak hours), the
  color of the current Tempo day (06:00 to 06:00) and the colors of yesterday, today
  and tomorrow. The current price, current period and next price change also cover
  Tempo.
- Accuracy first for Tempo: the current price and the current color are unavailable
  while the color of the current Tempo day is unknown; yesterday's and today's colors
  are unavailable when missing, tomorrow's is "unknown" until published.
- Tempo colors from Jour Tempo (RTE data redistributed as open data), completed by a
  fallback source when it fails or lacks a day. Only missing colors are asked for:
  yesterday, today and, from 10:30 the day before, tomorrow, every 15 minutes while
  one is missing. Known colors are saved, shared by all the Tempo contracts, shown
  at once on startup and never asked again; the setup never waits for the network.

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

[Unreleased]: https://github.com/iWils/ha-trve-edf/compare/0.3.0...HEAD
[0.3.0]: https://github.com/iWils/ha-trve-edf/compare/0.2.0...0.3.0
[0.2.0]: https://github.com/iWils/ha-trve-edf/compare/0.1.0...0.2.0
[0.1.0]: https://github.com/iWils/ha-trve-edf/releases/tag/0.1.0
