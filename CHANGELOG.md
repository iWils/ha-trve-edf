# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Specification of the integration (`docs/cahier-des-charges.md`, in French), validated.
- README in French and English.
- GPL-3.0 license.
- Guidelines for AI-assisted development (`CLAUDE.md`).
- Scaffold of the `trve_edf` integration: manifest, setup and unload of an entry,
  config flow announcing that configuration is not available yet, French and
  English translations, brand icon.
- Continuous integration: ruff, strict mypy, tests with coverage (90 % minimum),
  hassfest and HACS validation.
- Automated releases: once `main` holds a manifest version with a dated changelog
  section and no tag, the tests run, then the tag and the GitHub release are created
  with the changelog notes and the `trve_edf.zip` archive.
