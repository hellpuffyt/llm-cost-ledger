# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
