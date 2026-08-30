from datetime import date

import pytest

from llm_cost_ledger.models import UsageRecord
from llm_cost_ledger.pricing import PricingError, PricingTable


def make_record(model: str, input_tokens: int, output_tokens: int, **kw: object) -> UsageRecord:
    return UsageRecord(
        record_date=date(2026, 1, 1),
        provider="openai",
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        request_count=1,
        **kw,  # type: ignore[arg-type]
    )


def test_load_default_table_has_known_models() -> None:
    table = PricingTable.load_default()
    assert "gpt-4o-mini" in table.known_models()
    assert "claude-3-5-sonnet-20241022" in table.known_models()


def test_cost_of_simple_record() -> None:
    table = PricingTable.load_default()
    record = make_record("gpt-4o-mini", 1_000_000, 1_000_000)
    price = table.get("gpt-4o-mini")
    expected = price.input_per_million + price.output_per_million
    assert table.cost_of(record) == pytest.approx(expected)


def test_cost_of_zero_tokens_is_zero() -> None:
    table = PricingTable.load_default()
    record = make_record("gpt-4o-mini", 0, 0)
    assert table.cost_of(record) == 0.0


def test_unknown_model_raises() -> None:
    table = PricingTable.load_default()
    record = make_record("totally-made-up-model", 100, 100)
    with pytest.raises(PricingError, match="no price entry"):
        table.cost_of(record)


def test_from_yaml_text_parses_minimal_table() -> None:
    text = """
models:
  test-model:
    input_per_million: 1.0
    output_per_million: 2.0
"""
    table = PricingTable.from_yaml_text(text)
    record = make_record("test-model", 1_000_000, 1_000_000)
    assert table.cost_of(record) == pytest.approx(3.0)


def test_from_yaml_text_missing_models_key_raises() -> None:
    with pytest.raises(PricingError, match="models"):
        PricingTable.from_yaml_text("foo: bar")


def test_from_yaml_text_missing_required_field_raises() -> None:
    text = """
models:
  broken:
    input_per_million: 1.0
"""
    with pytest.raises(PricingError, match="missing required field"):
        PricingTable.from_yaml_text(text)


def test_from_yaml_text_non_numeric_price_raises() -> None:
    text = """
models:
  broken:
    input_per_million: "cheap"
    output_per_million: 1.0
"""
    with pytest.raises(PricingError, match="non-numeric"):
        PricingTable.from_yaml_text(text)


def test_from_file_merges_with_default(tmp_path: object) -> None:
    import pathlib

    path = pathlib.Path(str(tmp_path)) / "override.yaml"
    path.write_text(
        "models:\n  gpt-4o-mini:\n    input_per_million: 9.0\n    output_per_million: 9.0\n",
        encoding="utf-8",
    )
    table = PricingTable.from_file(path)
    # Overridden model uses the new price...
    record = make_record("gpt-4o-mini", 1_000_000, 0)
    assert table.cost_of(record) == pytest.approx(9.0)
    # ...but other default models are still present.
    assert "gpt-4o" in table.known_models()


def test_from_file_without_merge_only_has_override_models(tmp_path: object) -> None:
    import pathlib

    path = pathlib.Path(str(tmp_path)) / "override.yaml"
    path.write_text(
        "models:\n  only-model:\n    input_per_million: 1.0\n    output_per_million: 1.0\n",
        encoding="utf-8",
    )
    table = PricingTable.from_file(path, merge_with_default=False)
    assert table.known_models() == ["only-model"]


def test_cache_tokens_use_cache_rate_when_present() -> None:
    text = """
models:
  cached-model:
    input_per_million: 10.0
    output_per_million: 20.0
    cache_read_per_million: 1.0
    cache_write_per_million: 5.0
"""
    table = PricingTable.from_yaml_text(text)
    record = make_record(
        "cached-model", 0, 0, cache_read_tokens=1_000_000, cache_write_tokens=1_000_000
    )
    assert table.cost_of(record) == pytest.approx(6.0)


def test_cache_tokens_fall_back_to_input_rate_when_absent() -> None:
    text = """
models:
  no-cache-rate:
    input_per_million: 4.0
    output_per_million: 20.0
"""
    table = PricingTable.from_yaml_text(text)
    record = make_record("no-cache-rate", 0, 0, cache_read_tokens=1_000_000)
    assert table.cost_of(record) == pytest.approx(4.0)
