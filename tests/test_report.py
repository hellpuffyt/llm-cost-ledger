import csv
import io
import json
from datetime import date

import pytest

from llm_cost_ledger.models import AttributedRecord, UsageRecord
from llm_cost_ledger.report import (
    aggregate,
    filter_by_date,
    render,
    render_csv,
    render_json,
    render_table,
)


def make_attributed(
    day: date, project: str, feature: str, model: str, cost: float, requests: int
) -> AttributedRecord:
    usage = UsageRecord(
        record_date=day,
        provider="openai",
        model=model,
        input_tokens=100,
        output_tokens=50,
        request_count=requests,
    )
    return AttributedRecord(usage=usage, project=project, feature=feature, cost_usd=cost)


@pytest.fixture
def sample_records() -> list[AttributedRecord]:
    return [
        make_attributed(date(2026, 1, 1), "marketing", "ads", "gpt-4o-mini", 1.0, 100),
        make_attributed(date(2026, 1, 2), "marketing", "ads", "gpt-4o-mini", 1.5, 120),
        make_attributed(date(2026, 1, 1), "support", "triage", "gpt-4o", 5.0, 20),
    ]


def test_aggregate_groups_and_sums(sample_records: list[AttributedRecord]) -> None:
    rows = aggregate(sample_records, ("project", "model"))
    by_key = {(r.dimensions["project"], r.dimensions["model"]): r for r in rows}
    marketing = by_key[("marketing", "gpt-4o-mini")]
    assert marketing.total_cost_usd == pytest.approx(2.5)
    assert marketing.total_requests == 220


def test_aggregate_sorted_by_cost_descending(sample_records: list[AttributedRecord]) -> None:
    rows = aggregate(sample_records, ("project",))
    assert rows[0].total_cost_usd >= rows[-1].total_cost_usd


def test_aggregate_unknown_dimension_raises(sample_records: list[AttributedRecord]) -> None:
    with pytest.raises(ValueError, match="unknown dimension"):
        aggregate(sample_records, ("bogus",))


def test_aggregate_by_day(sample_records: list[AttributedRecord]) -> None:
    rows = aggregate(sample_records, ("day",))
    days = {r.dimensions["day"] for r in rows}
    assert days == {"2026-01-01", "2026-01-02"}


def test_cost_per_request_zero_when_no_requests() -> None:
    from llm_cost_ledger.report import ReportRow

    row = ReportRow(
        dimensions={},
        total_cost_usd=1.0,
        total_requests=0,
        total_input_tokens=0,
        total_output_tokens=0,
    )
    assert row.cost_per_request == 0.0


def test_filter_by_date_range(sample_records: list[AttributedRecord]) -> None:
    filtered = filter_by_date(sample_records, date(2026, 1, 2), None)
    assert all(r.record_date >= date(2026, 1, 2) for r in filtered)
    assert len(filtered) == 1


def test_filter_by_date_no_bounds_returns_all(sample_records: list[AttributedRecord]) -> None:
    assert filter_by_date(sample_records, None, None) == sample_records


def test_render_table_contains_totals(sample_records: list[AttributedRecord]) -> None:
    rows = aggregate(sample_records, ("project",))
    text = render_table(rows, ("project",))
    assert "TOTAL" in text
    assert "marketing" in text


def test_render_json_round_trips(sample_records: list[AttributedRecord]) -> None:
    rows = aggregate(sample_records, ("project", "model"))
    text = render_json(rows, ("project", "model"))
    payload = json.loads(text)
    assert isinstance(payload, list)
    assert payload[0]["cost_usd"] > 0


def test_render_csv_has_header_and_rows(sample_records: list[AttributedRecord]) -> None:
    rows = aggregate(sample_records, ("project",))
    text = render_csv(rows, ("project",))
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    assert "project" in header
    assert "cost_usd" in header
    data_rows = list(reader)
    assert len(data_rows) == len(rows)


def test_render_dispatches_on_format(sample_records: list[AttributedRecord]) -> None:
    rows = aggregate(sample_records, ("project",))
    assert "TOTAL" in render(rows, ("project",), "table")
    assert json.loads(render(rows, ("project",), "json"))
    assert "project" in render(rows, ("project",), "csv")


def test_render_unknown_format_raises(sample_records: list[AttributedRecord]) -> None:
    rows = aggregate(sample_records, ("project",))
    with pytest.raises(ValueError, match="unknown format"):
        render(rows, ("project",), "xml")


def test_aggregate_empty_records_returns_empty() -> None:
    assert aggregate([], ("project",)) == []
