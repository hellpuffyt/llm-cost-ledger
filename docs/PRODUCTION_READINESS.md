# Production readiness — llm-cost-ledger

Audit date: 2026-10-22. Tested commit: `e5cf0bb` (branch `audit/production-readiness`, based on `main` @ `f25615b`).

## Scope

Offline CLI + library: ingest OpenAI-/Anthropic-style usage exports (CSV/JSON) → price with a
YAML table → attribute to project/feature via glob rules → `report` (table/json/csv, cost gate) and
`drift` (Welch's t-test on daily cost per request). One runtime dependency: PyYAML (`safe_load`).
No network calls anywhere in `src/` (verified by reading every module; no HTTP/socket imports).

## Platforms and prerequisites

CPython 3.10–3.13. Verified on macOS 27 (Apple M5, arm64), CPython 3.12.14. Linux/Windows rely on
the existing CI matrix (not re-run in this audit).

## Clean-clone verification (commit `e5cf0bb`)

```bash
git clone -b audit/production-readiness <local clone> llm-cost-ledger && cd llm-cost-ledger
uv venv --python 3.12 .venv            # README: python -m venv .venv (equivalent)
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m pytest             # 135 passed
.venv/bin/python -m ruff check .       # All checks passed
.venv/bin/python -m mypy src tests     # no issues in 18 files
llm-cost-ledger report ... (README example)   # identical to README output, TOTAL 10.3189
# CI smoke steps from a non-editable install: ingest ok, cost gate exit 2, drift exit 3
```

## Commands and results

| Command | Baseline (`f25615b`) | After (`e5cf0bb`) |
| --- | --- | --- |
| `pytest` | exit 0 — 105 passed, 0 failed, 0 skipped | exit 0 — 135 passed, 0 failed, 0 skipped |
| `ruff check .` | exit 0 | exit 0 |
| `mypy src tests` (strict) | exit 0 | exit 0 |
| `uvx pip-audit` (installed env) | — | no known vulnerabilities |

CI status — default branch: success (`f25615b`, 2026-08-30); audit branch: pending until pushed.

## Arithmetic verification

- **Costs vs hand computation.** Each model total of the README example was computed by hand
  (tokens × USD/1M) and asserted exactly in `test_example_costs_match_hand_computation`:
  gpt-4o 4.72, claude-3-5-sonnet 4.437675, gpt-4o-mini 0.58245, claude-3-5-haiku 0.5788, total 10.318925.
- **Rounding.** Before the fix, float accumulation made the exact 0.58245 print as `0.5824`. Costs are
  now computed with `Decimal` and displayed half-up (`test_table_rounds_exact_halves_up`, `test_format_usd_half_up`).
- **Welch's t-test vs SciPy 1.18.1** (`scipy.stats.ttest_ind(equal_var=False)`), in a separate
  throwaway environment (SciPy is not a dependency): 2,000 random sample pairs (n = 2–40, varied
  variances) → max absolute difference in p-value or relative t-statistic 1.9e-12; edge cases
  n = 2/2, 500/500, 2000/3000, 365/365 and p ≈ 6e-15 agree to ≤ 1.6e-13.

## Security review

- No network I/O, no API keys read, YAML via `safe_load`. Output only to stdout or `--output`.
- Secret scan of full history: no credentials. **History hit (PII, not a secret):** the author's
  email address is in `pyproject.toml` in commits `05863d7` and `f25615b`. Removed from HEAD on this
  branch; history not rewritten (owner decision). No rotation needed.
- `pip-audit`: no known vulnerabilities.
- Workflow permissions: `contents: read`; actions tag-pinned (left as is, not broken).

## Bugs found and fixed (each with a regression test in `tests/test_audit_regressions.py`)

| Severity | Bug | Test |
| --- | --- | --- |
| High (wrong money) | explicit `cache_*_per_million: 0` fell back to the input rate (`rate or input`) | `test_explicit_zero_cache_rate_is_free_not_input_rate` |
| Medium (wrong display) | half-cent ties rounded by float error (0.58245 → 0.5824) | `test_table_rounds_exact_halves_up` |
| Medium (silent bad data) | `12.7` tokens truncated to 12; negative/non-finite prices accepted | `test_bad_token_counts_are_ingest_errors`, `test_negative_or_non_finite_prices_are_rejected` |
| Medium (crash; README promises none) | tracebacks for unknown model, negative/`inf` tokens, bad JSON, non-object JSON rows, bad YAML, non-UTF-8, `--alpha 2` | `test_cli_reports_errors_without_a_traceback[*]`, `test_non_utf8_input_is_a_cli_error`, `test_malformed_json_is_an_ingest_error`, `test_drift_rejects_out_of_range_alpha` |
| Low (invalid output) | `drift --format json` emitted `Infinity` | `test_drift_json_is_strict_json_when_a_group_is_new` |
| Low (stat validity) | overlapping baseline/current periods accepted | `test_drift_rejects_overlapping_periods` |
| Low (docs) | drift table was not aligned as the README shows | `test_drift_table_columns_are_aligned` |

## Known limitations

- The bundled pricing table is a snapshot and not verified against current provider prices.
- Real provider export schemas were not tested (only the documented shapes and fixtures; no real exports or accounts were used).
- A row with tokens and no request count is counted as one request (documented).
- `drift` uses daily granularity; fewer than `--min-days` days per period → "insufficient data".

## Acceptance checklist

| # | Item | Expected | Command / test | Result |
| --- | --- | --- | --- | --- |
| 1 | No network / no keys | no HTTP/socket code | source review | PASS |
| 2 | Costs equal hand computation | exact per-model totals | `test_example_costs_match_hand_computation` | PASS |
| 3 | Half-up display rounding | 0.58245 → 0.5825 | `test_table_rounds_exact_halves_up` | PASS |
| 4 | Cache-rate semantics | 0 = free, missing = input rate | 2 pricing tests | PASS |
| 5 | Welch p-values correct | match SciPy | comparison above | PASS (≤ 2e-12) |
| 6 | Drift flags the known regression | exit 3 on `drift_usage.csv` | CI smoke / clean clone | PASS |
| 7 | Cost gate | exit 2 | CI smoke / clean clone | PASS |
| 8 | Bad input → message, not traceback | exit 1 `error:` | parametrized CLI test | PASS |
| 9 | Clean clone | install + tests + README example | section above | PASS |

## Classification proposal

**Production-Ready for Its Documented Scope** (proposal for the lead), with the caveat that real
provider exports and current prices were not available to test.
