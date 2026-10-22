# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed

- An explicit `0` cache-read/cache-write rate was treated as "missing" and
  charged at the input rate (1M free cache-read tokens cost $3.00 on Sonnet).
- Costs are now computed exactly in decimal and displayed rounded half-up;
  float accumulation printed the exact 0.58245 as `0.5824` in the README example.
- Unknown models, negative/infinite/fractional token counts, malformed JSON,
  non-object JSON rows, invalid YAML, non-UTF-8 files and an out-of-range
  `--alpha` crashed with a traceback; each is now `error: ...` with exit code 1.
- Negative or non-finite prices are rejected.
- `drift --format json` wrote the non-standard token `Infinity` for groups with
  no baseline spend; it now writes `null`.
- `drift` table columns are aligned as shown in the README.
- `drift` refuses overlapping baseline/current periods.

### Changed

- README: rounding/cost semantics documented, cross-platform test commands,
  example output corrected. Removed the author email from `pyproject.toml`.

### Added

- `SECURITY.md`, `.editorconfig`, `docs/PRODUCTION_READINESS.md`.

## [0.1.0] - 2026-08-30

### Added

- Initial release.
- OpenAI-style and Anthropic-style usage export ingestion (CSV and JSON),
  normalised into a single internal `UsageRecord` shape.
- User-overridable pricing table (`--pricing`), merged over a bundled
  default table, with optional cache-read/cache-write rates.
- Attribution to project/feature tags via a glob-based mapping-rule file
  (`--mapping`), with a safe unattributed fallback.
- `report` subcommand: aggregate spend by project/feature/model/provider/day,
  output as table/json/csv, with a `--max-cost-per-request` CI gate.
- `drift` subcommand: compare daily cost-per-request between a baseline and
  a current period per group, using Welch's t-test (self-contained
  implementation, no scipy dependency) plus a minimum relative-increase
  threshold to avoid flagging statistically-significant-but-trivial noise.
- `ingest` subcommand for inspecting normalised records directly.
