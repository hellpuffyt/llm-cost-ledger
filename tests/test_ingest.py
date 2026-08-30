import json
from datetime import date

import pytest

from llm_cost_ledger.ingest import (
    IngestError,
    merge,
    parse_anthropic_export,
    parse_export,
    parse_openai_export,
)

OPENAI_JSON = json.dumps(
    {
        "data": [
            {
                "start_time": "2026-06-01",
                "model": "gpt-4o-mini",
                "n_requests": 10,
                "n_context_tokens_total": 1000,
                "n_generated_tokens_total": 200,
                "project_id": "proj_a",
                "api_key_id": "key_1",
            }
        ]
    }
)

OPENAI_CSV = (
    "start_time,model,n_requests,n_context_tokens_total,n_generated_tokens_total,project_id\n"
    "2026-06-01,gpt-4o,5,2000,400,proj_b\n"
)

ANTHROPIC_CSV = (
    "date,workspace_id,model,input_tokens,output_tokens,"
    "cache_creation_input_tokens,cache_read_input_tokens,request_count\n"
    "2026-06-01,ws_1,claude-3-5-sonnet-20241022,3000,600,100,50,20\n"
)

ANTHROPIC_JSON = json.dumps(
    [
        {
            "date": "2026-06-02",
            "workspace_id": "ws_2",
            "model": "claude-3-5-haiku-20241022",
            "input_tokens": 500,
            "output_tokens": 100,
            "request_count": 3,
        }
    ]
)


def test_parse_openai_json() -> None:
    records = parse_openai_export(OPENAI_JSON)
    assert len(records) == 1
    r = records[0]
    assert r.provider == "openai"
    assert r.model == "gpt-4o-mini"
    assert r.record_date == date(2026, 6, 1)
    assert r.input_tokens == 1000
    assert r.output_tokens == 200
    assert r.request_count == 10
    assert r.raw_project_id == "proj_a"
    assert r.raw_api_key_id == "key_1"


def test_parse_openai_csv() -> None:
    records = parse_openai_export(OPENAI_CSV)
    assert len(records) == 1
    r = records[0]
    assert r.model == "gpt-4o"
    assert r.raw_project_id == "proj_b"
    assert r.request_count == 5


def test_parse_openai_missing_request_count_defaults_to_one() -> None:
    raw = json.dumps(
        {
            "data": [
                {
                    "start_time": "2026-06-01",
                    "model": "gpt-4o",
                    "n_context_tokens_total": 100,
                    "n_generated_tokens_total": 50,
                }
            ]
        }
    )
    records = parse_openai_export(raw)
    assert records[0].request_count == 1


def test_parse_openai_missing_model_raises() -> None:
    raw = json.dumps({"data": [{"start_time": "2026-06-01", "n_requests": 1}]})
    with pytest.raises(IngestError, match="row 0"):
        parse_openai_export(raw)


def test_parse_anthropic_csv() -> None:
    records = parse_anthropic_export(ANTHROPIC_CSV)
    assert len(records) == 1
    r = records[0]
    assert r.provider == "anthropic"
    assert r.model == "claude-3-5-sonnet-20241022"
    assert r.input_tokens == 3000
    assert r.output_tokens == 600
    assert r.cache_write_tokens == 100
    assert r.cache_read_tokens == 50
    assert r.request_count == 20
    assert r.raw_project_id == "ws_1"


def test_parse_anthropic_json() -> None:
    records = parse_anthropic_export(ANTHROPIC_JSON)
    assert len(records) == 1
    r = records[0]
    assert r.record_date == date(2026, 6, 2)
    assert r.model == "claude-3-5-haiku-20241022"
    assert r.request_count == 3


def test_parse_anthropic_missing_date_raises() -> None:
    raw = json.dumps([{"model": "claude-3-5-haiku-20241022", "input_tokens": 1}])
    with pytest.raises(IngestError, match="row 0"):
        parse_anthropic_export(raw)


def test_parse_export_dispatches_by_provider() -> None:
    records = parse_export("openai", OPENAI_JSON)
    assert records[0].provider == "openai"
    records2 = parse_export("anthropic", ANTHROPIC_CSV)
    assert records2[0].provider == "anthropic"


def test_parse_export_unknown_provider_raises() -> None:
    with pytest.raises(IngestError, match="unknown provider"):
        parse_export("cohere", "{}")


def test_malformed_json_raises_ingest_or_value_error() -> None:
    with pytest.raises(Exception):  # noqa: B017 - json.JSONDecodeError subclasses ValueError
        parse_openai_export("{not valid json")


def test_non_numeric_token_count_raises() -> None:
    raw = json.dumps(
        {
            "data": [
                {
                    "start_time": "2026-06-01",
                    "model": "gpt-4o",
                    "n_context_tokens_total": "not-a-number",
                }
            ]
        }
    )
    with pytest.raises(IngestError):
        parse_openai_export(raw)


def test_merge_flattens_multiple_groups() -> None:
    a = parse_openai_export(OPENAI_JSON)
    b = parse_anthropic_export(ANTHROPIC_CSV)
    merged = merge(a, b)
    assert len(merged) == 2
    assert {r.provider for r in merged} == {"openai", "anthropic"}


def test_unix_timestamp_date_parsing() -> None:
    raw = json.dumps(
        {
            "data": [
                {
                    "start_time": 1717200000,  # 2024-06-01 in unix time
                    "model": "gpt-4o",
                    "n_context_tokens_total": 10,
                    "n_generated_tokens_total": 5,
                }
            ]
        }
    )
    records = parse_openai_export(raw)
    assert records[0].record_date.year == 2024
