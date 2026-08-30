"""Command-line interface for llm-cost-ledger.

Exit codes (documented for CI use):
  0 -- success, no gate breached
  1 -- usage error (bad arguments, unparsable input, bad config)
  2 -- `report --max-cost-per-request` gate breached
  3 -- `drift` found one or more statistically meaningful regressions
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from llm_cost_ledger.attribution import AttributionError, AttributionRules, attribute_and_price
from llm_cost_ledger.drift import DriftResult, detect_drift
from llm_cost_ledger.ingest import IngestError, merge, parse_export
from llm_cost_ledger.models import AttributedRecord, UsageRecord
from llm_cost_ledger.pricing import PricingError, PricingTable
from llm_cost_ledger.report import aggregate, filter_by_date, render

_INPUT_HELP = (
    "Usage export to ingest, formatted as PROVIDER=PATH, e.g. "
    "openai=exports/openai.json or anthropic=exports/anthropic.csv. "
    "Repeat this flag to combine multiple files/providers. "
    "Supported providers: openai, anthropic."
)


class CliError(Exception):
    """Raised for user-facing errors; caught in main() and reported cleanly."""


def _parse_input_spec(spec: str) -> tuple[str, str]:
    if "=" not in spec:
        raise CliError(f"--input value {spec!r} must look like PROVIDER=PATH")
    provider, _, path = spec.partition("=")
    provider = provider.strip().lower()
    path = path.strip()
    if not provider or not path:
        raise CliError(f"--input value {spec!r} must look like PROVIDER=PATH")
    return provider, path


def _load_records(input_specs: list[str]) -> list[UsageRecord]:
    groups: list[list[UsageRecord]] = []
    for spec in input_specs:
        provider, path_str = _parse_input_spec(spec)
        path = Path(path_str)
        if not path.exists():
            raise CliError(f"input file not found: {path}")
        try:
            raw = path.read_text(encoding="utf-8")
            groups.append(parse_export(provider, raw))
        except IngestError as exc:
            raise CliError(f"failed to parse {path} as {provider!r}: {exc}") from exc
    return merge(*groups)


def _load_pricing(pricing_path: str | None) -> PricingTable:
    try:
        if pricing_path is None:
            return PricingTable.load_default()
        return PricingTable.from_file(pricing_path)
    except (PricingError, OSError) as exc:
        raise CliError(f"failed to load pricing config: {exc}") from exc


def _load_rules(mapping_path: str | None) -> AttributionRules:
    if mapping_path is None:
        return AttributionRules.empty()
    try:
        return AttributionRules.from_file(mapping_path)
    except (AttributionError, OSError) as exc:
        raise CliError(f"failed to load mapping config: {exc}") from exc


def _parse_date_arg(value: str | None, flag: str) -> date | None:
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise CliError(f"{flag} must be YYYY-MM-DD, got {value!r}") from exc


def _parse_group_by(value: str, valid: tuple[str, ...]) -> tuple[str, ...]:
    dims = tuple(d.strip() for d in value.split(",") if d.strip())
    if not dims:
        raise CliError("--group-by must name at least one dimension")
    for dim in dims:
        if dim not in valid:
            raise CliError(f"--group-by dimension {dim!r} must be one of {valid}")
    return dims


def _build_attributed(args: argparse.Namespace) -> list[AttributedRecord]:
    records = _load_records(args.input)
    pricing = _load_pricing(args.pricing)
    rules = _load_rules(args.mapping)
    return attribute_and_price(records, pricing, rules)


def _write_output(text: str, output_path: str | None) -> None:
    if output_path is None:
        print(text)
    else:
        Path(output_path).write_text(text + "\n", encoding="utf-8")


def cmd_ingest(args: argparse.Namespace) -> int:
    records = _load_records(args.input)
    payload = [
        {
            "date": r.record_date.isoformat(),
            "provider": r.provider,
            "model": r.model,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "cache_read_tokens": r.cache_read_tokens,
            "cache_write_tokens": r.cache_write_tokens,
            "request_count": r.request_count,
            "raw_project_id": r.raw_project_id,
            "raw_api_key_id": r.raw_api_key_id,
        }
        for r in records
    ]
    _write_output(json.dumps(payload, indent=2), args.output)
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    group_by = _parse_group_by(args.group_by, ("project", "feature", "model", "provider", "day"))
    start = _parse_date_arg(args.start_date, "--start-date")
    end = _parse_date_arg(args.end_date, "--end-date")

    attributed = _build_attributed(args)
    attributed = filter_by_date(attributed, start, end)
    rows = aggregate(attributed, group_by)
    _write_output(render(rows, group_by, args.format), args.output)

    if args.max_cost_per_request is not None:
        breaches = [row for row in rows if row.cost_per_request > args.max_cost_per_request]
        if breaches:
            names = ", ".join("/".join(row.dimensions.values()) for row in breaches[:5])
            print(
                f"GATE FAILED: {len(breaches)} group(s) exceed "
                f"--max-cost-per-request={args.max_cost_per_request}: {names}",
                file=sys.stderr,
            )
            return 2
    return 0


def _drift_result_to_dict(result: DriftResult) -> dict[str, object]:
    d = asdict(result)
    d["group_key"] = list(result.group_key)
    return d


def cmd_drift(args: argparse.Namespace) -> int:
    group_by = _parse_group_by(args.group_by, ("project", "feature", "model", "provider"))

    baseline_start = _parse_date_arg(args.baseline_start, "--baseline-start")
    baseline_end = _parse_date_arg(args.baseline_end, "--baseline-end")
    current_start = _parse_date_arg(args.current_start, "--current-start")
    current_end = _parse_date_arg(args.current_end, "--current-end")

    if None in (baseline_start, baseline_end, current_start, current_end):
        raise CliError(
            "drift requires --baseline-start --baseline-end --current-start --current-end"
        )

    attributed = _build_attributed(args)
    baseline = filter_by_date(attributed, baseline_start, baseline_end)
    current = filter_by_date(attributed, current_start, current_end)

    results = detect_drift(
        baseline,
        current,
        group_by=group_by,
        alpha=args.alpha,
        min_relative_increase=args.min_relative_increase,
        min_days=args.min_days,
    )

    if args.format == "json":
        text = json.dumps([_drift_result_to_dict(r) for r in results], indent=2)
    elif args.format == "csv":
        import csv
        import io

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                *group_by,
                "baseline_mean_cost_per_request",
                "current_mean_cost_per_request",
                "relative_change",
                "p_value",
                "baseline_days",
                "current_days",
                "is_regression",
                "insufficient_data",
                "note",
            ]
        )
        for r in results:
            writer.writerow(
                [
                    *r.group_key,
                    f"{r.baseline_mean_cost_per_request:.8f}",
                    f"{r.current_mean_cost_per_request:.8f}",
                    f"{r.relative_change:.4f}",
                    "" if r.p_value is None else f"{r.p_value:.6f}",
                    r.baseline_days,
                    r.current_days,
                    r.is_regression,
                    r.insufficient_data,
                    r.note,
                ]
            )
        text = buf.getvalue()
    else:
        lines = [
            "  ".join(
                [
                    *group_by,
                    "baseline$/req",
                    "current$/req",
                    "change",
                    "p",
                    "days(b/c)",
                    "status",
                ]
            )
        ]
        for r in results:
            status = "insufficient-data" if r.insufficient_data else (
                "REGRESSION" if r.is_regression else "ok"
            )
            change_str = "n/a" if r.relative_change == float("inf") else f"{r.relative_change:+.1%}"
            p_str = "n/a" if r.p_value is None else f"{r.p_value:.4f}"
            lines.append(
                "  ".join(
                    [
                        *r.group_key,
                        f"{r.baseline_mean_cost_per_request:.6f}",
                        f"{r.current_mean_cost_per_request:.6f}",
                        change_str,
                        p_str,
                        f"{r.baseline_days}/{r.current_days}",
                        status,
                    ]
                )
            )
        text = "\n".join(lines)

    _write_output(text, args.output)

    regressions = [r for r in results if r.is_regression]
    if regressions:
        print(f"{len(regressions)} regression(s) detected", file=sys.stderr)
        return 3
    return 0


def _add_common_input_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input", action="append", required=True, help=_INPUT_HELP)
    parser.add_argument(
        "--output", default=None, help="Write output to this path instead of stdout."
    )


def _add_pricing_mapping_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--pricing",
        default=None,
        help="Path to a YAML pricing config. Merged over the bundled defaults.",
    )
    parser.add_argument(
        "--mapping",
        default=None,
        help="Path to a YAML attribution mapping-rule file.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llm-cost-ledger",
        description=(
            "Attribute LLM API spend per project, model and prompt from provider usage "
            "exports, with drift alerts on cost per request."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_ingest = subparsers.add_parser(
        "ingest", help="Parse provider exports into normalised JSON (debugging aid)."
    )
    _add_common_input_args(p_ingest)
    p_ingest.set_defaults(func=cmd_ingest)

    p_report = subparsers.add_parser(
        "report", help="Ingest, attribute, price and aggregate usage into a spend report."
    )
    _add_common_input_args(p_report)
    _add_pricing_mapping_args(p_report)
    p_report.add_argument(
        "--group-by",
        default="project,feature,model",
        help="Comma-separated dimensions: project,feature,model,provider,day.",
    )
    p_report.add_argument("--format", choices=["table", "json", "csv"], default="table")
    p_report.add_argument("--start-date", default=None, help="Filter records >= YYYY-MM-DD.")
    p_report.add_argument("--end-date", default=None, help="Filter records <= YYYY-MM-DD.")
    p_report.add_argument(
        "--max-cost-per-request",
        type=float,
        default=None,
        help="CI gate: exit 2 if any reported group exceeds this cost per request (USD).",
    )
    p_report.set_defaults(func=cmd_report)

    p_drift = subparsers.add_parser(
        "drift", help="Compare cost-per-request between two periods and flag regressions."
    )
    _add_common_input_args(p_drift)
    _add_pricing_mapping_args(p_drift)
    p_drift.add_argument("--baseline-start", required=True, help="YYYY-MM-DD, inclusive.")
    p_drift.add_argument("--baseline-end", required=True, help="YYYY-MM-DD, inclusive.")
    p_drift.add_argument("--current-start", required=True, help="YYYY-MM-DD, inclusive.")
    p_drift.add_argument("--current-end", required=True, help="YYYY-MM-DD, inclusive.")
    p_drift.add_argument(
        "--group-by",
        default="project,feature,model",
        help="Comma-separated dimensions: project,feature,model,provider.",
    )
    p_drift.add_argument("--format", choices=["table", "json", "csv"], default="table")
    p_drift.add_argument(
        "--alpha", type=float, default=0.05, help="Significance level for Welch's t-test."
    )
    p_drift.add_argument(
        "--min-relative-increase",
        type=float,
        default=0.10,
        help="Minimum fractional increase in mean cost/request to ever flag (default 0.10 = 10%%).",
    )
    p_drift.add_argument(
        "--min-days",
        type=int,
        default=3,
        help="Minimum distinct daily data points required in each period to test significance.",
    )
    p_drift.set_defaults(func=cmd_drift)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
