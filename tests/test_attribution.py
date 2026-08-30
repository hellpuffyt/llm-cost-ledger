from datetime import date

import pytest

from llm_cost_ledger.attribution import (
    AttributionError,
    AttributionRules,
    attribute_and_price,
)
from llm_cost_ledger.models import UsageRecord
from llm_cost_ledger.pricing import PricingTable


def make_record(**overrides: object) -> UsageRecord:
    defaults: dict[str, object] = {
        "record_date": date(2026, 1, 1),
        "provider": "openai",
        "model": "gpt-4o-mini",
        "input_tokens": 1000,
        "output_tokens": 200,
        "request_count": 1,
        "raw_project_id": "proj_marketing",
    }
    defaults.update(overrides)
    return UsageRecord(**defaults)  # type: ignore[arg-type]


RULES_YAML = """
rules:
  - match:
      provider: openai
      raw_project_id: "proj_marketing"
    tags:
      project: marketing
      feature: ad-copy

  - match:
      model: "claude-3-5-haiku*"
    tags:
      project: engineering
"""


def test_empty_rules_fall_back_to_raw_project_id() -> None:
    rules = AttributionRules.empty()
    project, feature = rules.attribute(make_record())
    assert project == "proj_marketing"
    assert feature == "unattributed"


def test_empty_rules_fall_back_when_no_raw_project_id() -> None:
    rules = AttributionRules.empty()
    project, feature = rules.attribute(make_record(raw_project_id=None))
    assert project == "unattributed"
    assert feature == "unattributed"


def test_rule_matches_exact_field() -> None:
    rules = AttributionRules.from_yaml_text(RULES_YAML)
    project, feature = rules.attribute(make_record())
    assert project == "marketing"
    assert feature == "ad-copy"


def test_rule_matches_glob_pattern() -> None:
    rules = AttributionRules.from_yaml_text(RULES_YAML)
    record = make_record(model="claude-3-5-haiku-20241022", raw_project_id="ws_x")
    project, feature = rules.attribute(record)
    assert project == "engineering"
    assert feature == "unattributed"  # tags.feature omitted -> falls back


def test_rule_matching_is_case_insensitive() -> None:
    rules = AttributionRules.from_yaml_text(RULES_YAML)
    record = make_record(raw_project_id="PROJ_MARKETING")
    project, _feature = rules.attribute(record)
    assert project == "marketing"


def test_first_matching_rule_wins() -> None:
    text = """
rules:
  - match:
      provider: openai
    tags:
      project: first
  - match:
      provider: openai
    tags:
      project: second
"""
    rules = AttributionRules.from_yaml_text(text)
    project, _ = rules.attribute(make_record())
    assert project == "first"


def test_unmatched_record_falls_back() -> None:
    rules = AttributionRules.from_yaml_text(RULES_YAML)
    record = make_record(provider="anthropic", model="claude-3-opus", raw_project_id="ws_other")
    project, feature = rules.attribute(record)
    assert project == "ws_other"
    assert feature == "unattributed"


def test_missing_rules_key_raises() -> None:
    with pytest.raises(AttributionError, match="rules"):
        AttributionRules.from_yaml_text("foo: bar")


def test_rule_without_match_raises() -> None:
    with pytest.raises(AttributionError, match="match"):
        AttributionRules.from_yaml_text("rules:\n  - tags:\n      project: x\n")


def test_rule_without_project_tag_raises() -> None:
    text = "rules:\n  - match:\n      provider: openai\n    tags:\n      feature: x\n"
    with pytest.raises(AttributionError, match="tags.project"):
        AttributionRules.from_yaml_text(text)


def test_rule_with_invalid_match_field_raises() -> None:
    text = "rules:\n  - match:\n      not_a_field: x\n    tags:\n      project: y\n"
    with pytest.raises(AttributionError, match="not_a_field"):
        AttributionRules.from_yaml_text(text)


def test_attribute_and_price_produces_cost() -> None:
    pricing = PricingTable.load_default()
    rules = AttributionRules.from_yaml_text(RULES_YAML)
    records = [make_record(input_tokens=1_000_000, output_tokens=1_000_000)]
    attributed = attribute_and_price(records, pricing, rules)
    assert len(attributed) == 1
    assert attributed[0].project == "marketing"
    assert attributed[0].cost_usd > 0
