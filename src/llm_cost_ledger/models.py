"""Internal data model that all provider exports are normalised into."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class UsageRecord:
    """A single normalised unit of usage, aggregated over some period.

    Provider exports are usually already aggregated (e.g. "per day per
    model per project"), so a record does not necessarily represent one
    API call -- ``request_count`` says how many calls it represents.
    """

    record_date: date
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    request_count: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    # Identifiers as reported by the provider, used as inputs to attribution
    # mapping rules (e.g. OpenAI project_id, Anthropic workspace_id).
    raw_project_id: str | None = None
    raw_api_key_id: str | None = None
    # Free-form tags carried through from the source record (e.g. a
    # "feature" or "prompt_id" column some exports already include).
    source_tags: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise ValueError("token counts must be non-negative")
        if self.request_count < 0:
            raise ValueError("request_count must be non-negative")
        if self.cache_read_tokens < 0 or self.cache_write_tokens < 0:
            raise ValueError("cache token counts must be non-negative")


@dataclass(frozen=True)
class AttributedRecord:
    """A :class:`UsageRecord` after attribution tags and cost were applied."""

    usage: UsageRecord
    project: str
    feature: str
    cost_usd: float

    @property
    def record_date(self) -> date:
        return self.usage.record_date

    @property
    def model(self) -> str:
        return self.usage.model

    @property
    def provider(self) -> str:
        return self.usage.provider

    @property
    def request_count(self) -> int:
        return self.usage.request_count
