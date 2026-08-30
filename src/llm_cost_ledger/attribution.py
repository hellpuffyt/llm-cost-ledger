"""Attribute usage records to a project/feature via a mapping-rule file.

Provider usage exports carry the provider's own identifiers (an OpenAI
project_id, an Anthropic workspace_id, sometimes an api_key_id) but not
your organisation's notion of "project" or "feature". A mapping rule file
(YAML) bridges the two:

    rules:
      - match:
          provider: openai
          raw_project_id: "proj_marketing*"
        tags:
          project: marketing
          feature: ad-copy-generator
      - match:
          provider: anthropic
          model: "claude-3-5-haiku*"
        tags:
          project: support
          feature: ticket-triage

Rules are evaluated in order; the first rule whose ``match`` clauses all
match (glob-style, case-insensitive) wins. A record that matches no rule
falls back to ``project=<raw_project_id or "unattributed">`` and
``feature="unattributed"`` so nothing is silently dropped from reports.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from llm_cost_ledger.models import AttributedRecord, UsageRecord
from llm_cost_ledger.pricing import PricingTable

UNATTRIBUTED_FEATURE = "unattributed"


class AttributionError(ValueError):
    """Raised for malformed mapping-rule configuration."""


_MATCHABLE_FIELDS = ("provider", "model", "raw_project_id", "raw_api_key_id")


@dataclass(frozen=True)
class MappingRule:
    match: dict[str, str]
    project: str
    feature: str

    def matches(self, record: UsageRecord) -> bool:
        for field_name, pattern in self.match.items():
            value = getattr(record, field_name, None) or ""
            if not fnmatch.fnmatch(str(value).lower(), pattern.lower()):
                return False
        return True


class AttributionRules:
    def __init__(self, rules: list[MappingRule]) -> None:
        self._rules = rules

    @classmethod
    def empty(cls) -> AttributionRules:
        return cls([])

    @classmethod
    def from_file(cls, path: str | Path) -> AttributionRules:
        return cls.from_yaml_text(Path(path).read_text(encoding="utf-8"))

    @classmethod
    def from_yaml_text(cls, text: str) -> AttributionRules:
        data = yaml.safe_load(text) or {}
        if not isinstance(data, dict) or "rules" not in data:
            raise AttributionError("mapping file must be a mapping with a top-level 'rules' key")
        raw_rules = data["rules"]
        if not isinstance(raw_rules, list):
            raise AttributionError("'rules' must be a list")
        rules: list[MappingRule] = []
        for i, raw_rule in enumerate(raw_rules):
            rules.append(cls._parse_rule(i, raw_rule))
        return cls(rules)

    @staticmethod
    def _parse_rule(index: int, raw_rule: Any) -> MappingRule:
        if not isinstance(raw_rule, dict):
            raise AttributionError(f"rule {index} must be a mapping")
        match = raw_rule.get("match")
        tags = raw_rule.get("tags")
        if not isinstance(match, dict) or not match:
            raise AttributionError(f"rule {index} must have a non-empty 'match' mapping")
        for key in match:
            if key not in _MATCHABLE_FIELDS:
                raise AttributionError(
                    f"rule {index} match field {key!r} is not one of {_MATCHABLE_FIELDS}"
                )
        if not isinstance(tags, dict) or "project" not in tags:
            raise AttributionError(f"rule {index} must have tags.project")
        return MappingRule(
            match={k: str(v) for k, v in match.items()},
            project=str(tags["project"]),
            feature=str(tags.get("feature", UNATTRIBUTED_FEATURE)),
        )

    def attribute(self, record: UsageRecord) -> tuple[str, str]:
        """Return (project, feature) for a record."""
        for rule in self._rules:
            if rule.matches(record):
                return rule.project, rule.feature
        fallback_project = record.raw_project_id or "unattributed"
        return fallback_project, UNATTRIBUTED_FEATURE


def attribute_and_price(
    records: list[UsageRecord],
    pricing: PricingTable,
    rules: AttributionRules,
) -> list[AttributedRecord]:
    attributed: list[AttributedRecord] = []
    for record in records:
        project, feature = rules.attribute(record)
        cost = pricing.cost_of(record)
        attributed.append(
            AttributedRecord(usage=record, project=project, feature=feature, cost_usd=cost)
        )
    return attributed
