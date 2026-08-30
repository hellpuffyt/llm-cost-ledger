"""Aggregate attributed records into report rows, and render them."""

from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from llm_cost_ledger.models import AttributedRecord

VALID_DIMENSIONS = ("project", "feature", "model", "provider", "day")


@dataclass(frozen=True)
class ReportRow:
    dimensions: dict[str, str]
    total_cost_usd: float
    total_requests: int
    total_input_tokens: int
    total_output_tokens: int

    @property
    def cost_per_request(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_cost_usd / self.total_requests


def _dim_value(record: AttributedRecord, dim: str) -> str:
    if dim == "project":
        return record.project
    if dim == "feature":
        return record.feature
    if dim == "model":
        return record.model
    if dim == "provider":
        return record.provider
    if dim == "day":
        return record.record_date.isoformat()
    raise ValueError(f"unknown dimension {dim!r}; expected one of {VALID_DIMENSIONS}")


def aggregate(records: list[AttributedRecord], group_by: tuple[str, ...]) -> list[ReportRow]:
    for dim in group_by:
        if dim not in VALID_DIMENSIONS:
            raise ValueError(f"unknown dimension {dim!r}; expected one of {VALID_DIMENSIONS}")

    buckets: dict[tuple[str, ...], list[AttributedRecord]] = defaultdict(list)
    for record in records:
        key = tuple(_dim_value(record, dim) for dim in group_by)
        buckets[key].append(record)

    rows: list[ReportRow] = []
    for key, group_records in buckets.items():
        rows.append(
            ReportRow(
                dimensions=dict(zip(group_by, key, strict=True)),
                total_cost_usd=sum(r.cost_usd for r in group_records),
                total_requests=sum(r.request_count for r in group_records),
                total_input_tokens=sum(r.usage.input_tokens for r in group_records),
                total_output_tokens=sum(r.usage.output_tokens for r in group_records),
            )
        )
    rows.sort(key=lambda r: r.total_cost_usd, reverse=True)
    return rows


def filter_by_date(
    records: list[AttributedRecord], start: date | None, end: date | None
) -> list[AttributedRecord]:
    result = records
    if start is not None:
        result = [r for r in result if r.record_date >= start]
    if end is not None:
        result = [r for r in result if r.record_date <= end]
    return result


def render_table(rows: list[ReportRow], group_by: tuple[str, ...]) -> str:
    headers = [*group_by, "requests", "input_tok", "output_tok", "cost_usd", "cost/req"]
    data_lines = [
        [
            *[row.dimensions[dim] for dim in group_by],
            str(row.total_requests),
            str(row.total_input_tokens),
            str(row.total_output_tokens),
            f"{row.total_cost_usd:.4f}",
            f"{row.cost_per_request:.6f}",
        ]
        for row in rows
    ]
    widths = [
        max(len(headers[i]), *(len(line[i]) for line in data_lines))
        if data_lines
        else len(headers[i])
        for i in range(len(headers))
    ]
    lines = []
    lines.append("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    lines.append("  ".join("-" * widths[i] for i in range(len(headers))))
    for line in data_lines:
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(line)))
    total_cost = sum(row.total_cost_usd for row in rows)
    total_requests = sum(row.total_requests for row in rows)
    lines.append("")
    lines.append(f"TOTAL: {total_cost:.4f} USD across {total_requests} requests")
    return "\n".join(lines)


def render_json(rows: list[ReportRow], group_by: tuple[str, ...]) -> str:
    payload = [
        {
            **row.dimensions,
            "requests": row.total_requests,
            "input_tokens": row.total_input_tokens,
            "output_tokens": row.total_output_tokens,
            "cost_usd": round(row.total_cost_usd, 6),
            "cost_per_request": round(row.cost_per_request, 8),
        }
        for row in rows
    ]
    return json.dumps(payload, indent=2)


def render_csv(rows: list[ReportRow], group_by: tuple[str, ...]) -> str:
    buffer = io.StringIO()
    fieldnames = [
        *group_by,
        "requests",
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "cost_per_request",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                **row.dimensions,
                "requests": row.total_requests,
                "input_tokens": row.total_input_tokens,
                "output_tokens": row.total_output_tokens,
                "cost_usd": f"{row.total_cost_usd:.6f}",
                "cost_per_request": f"{row.cost_per_request:.8f}",
            }
        )
    return buffer.getvalue()


def render(rows: list[ReportRow], group_by: tuple[str, ...], fmt: str) -> str:
    if fmt == "table":
        return render_table(rows, group_by)
    if fmt == "json":
        return render_json(rows, group_by)
    if fmt == "csv":
        return render_csv(rows, group_by)
    raise ValueError(f"unknown format {fmt!r}; expected table, json, or csv")
