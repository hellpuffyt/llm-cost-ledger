from datetime import date

import pytest

from llm_cost_ledger.models import AttributedRecord, UsageRecord


def make_record(**overrides: object) -> UsageRecord:
    defaults: dict[str, object] = {
        "record_date": date(2026, 1, 1),
        "provider": "openai",
        "model": "gpt-4o-mini",
        "input_tokens": 1000,
        "output_tokens": 500,
        "request_count": 1,
    }
    defaults.update(overrides)
    return UsageRecord(**defaults)  # type: ignore[arg-type]


def test_usage_record_basic_construction() -> None:
    record = make_record()
    assert record.provider == "openai"
    assert record.cache_read_tokens == 0
    assert record.source_tags == {}


def test_negative_input_tokens_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        make_record(input_tokens=-1)


def test_negative_output_tokens_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        make_record(output_tokens=-1)


def test_negative_request_count_rejected() -> None:
    with pytest.raises(ValueError, match="request_count"):
        make_record(request_count=-1)


def test_negative_cache_tokens_rejected() -> None:
    with pytest.raises(ValueError, match="cache token"):
        make_record(cache_read_tokens=-5)
    with pytest.raises(ValueError, match="cache token"):
        make_record(cache_write_tokens=-5)


def test_attributed_record_proxies_usage_fields() -> None:
    usage = make_record(request_count=7)
    attributed = AttributedRecord(usage=usage, project="p", feature="f", cost_usd=1.23)
    assert attributed.record_date == usage.record_date
    assert attributed.model == usage.model
    assert attributed.provider == usage.provider
    assert attributed.request_count == 7
