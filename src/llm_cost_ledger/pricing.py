"""Pricing table lookups.

Prices change. The bundled default table (``data/default_pricing.yaml``) is a
snapshot taken when this tool was published and WILL go stale -- always
check your provider's current pricing page and override with your own
config file (``--pricing``) for anything that matters. This module never
calls out to the network to "refresh" prices; that would violate the
offline guarantee this tool makes.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from llm_cost_ledger.models import UsageRecord


class PricingError(ValueError):
    """Raised for missing or malformed pricing configuration."""


@dataclass(frozen=True)
class ModelPrice:
    input_per_million: float
    output_per_million: float
    # Optional, provider-specific cache token rates. When absent, cache-read
    # tokens are priced at the input rate and cache-write tokens too -- the
    # conservative (non-discounted) assumption.
    cache_read_per_million: float | None = None
    cache_write_per_million: float | None = None


class PricingTable:
    """Maps model name -> :class:`ModelPrice` and prices UsageRecords."""

    def __init__(self, prices: dict[str, ModelPrice]) -> None:
        self._prices = prices

    @classmethod
    def load_default(cls) -> PricingTable:
        raw = resources.files("llm_cost_ledger.data").joinpath("default_pricing.yaml")
        return cls.from_yaml_text(raw.read_text(encoding="utf-8"))

    @classmethod
    def from_file(cls, path: str | Path, *, merge_with_default: bool = True) -> PricingTable:
        text = Path(path).read_text(encoding="utf-8")
        overrides = cls.from_yaml_text(text)
        if not merge_with_default:
            return overrides
        base = cls.load_default()
        merged = dict(base._prices)
        merged.update(overrides._prices)
        return cls(merged)

    @classmethod
    def from_yaml_text(cls, text: str) -> PricingTable:
        data = yaml.safe_load(text) or {}
        if not isinstance(data, dict) or "models" not in data:
            raise PricingError("pricing config must be a mapping with a top-level 'models' key")
        models = data["models"]
        if not isinstance(models, dict):
            raise PricingError("'models' must be a mapping of model name -> price fields")
        prices: dict[str, ModelPrice] = {}
        for name, fields in models.items():
            prices[name] = cls._parse_model_price(name, fields)
        return cls(prices)

    @staticmethod
    def _parse_model_price(name: str, fields: Any) -> ModelPrice:
        if not isinstance(fields, dict):
            raise PricingError(f"pricing entry for {name!r} must be a mapping")
        try:
            input_price = float(fields["input_per_million"])
            output_price = float(fields["output_per_million"])
        except KeyError as exc:
            raise PricingError(
                f"pricing entry for {name!r} is missing required field {exc}"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise PricingError(f"pricing entry for {name!r} has a non-numeric price") from exc
        cache_read = fields.get("cache_read_per_million")
        cache_write = fields.get("cache_write_per_million")
        return ModelPrice(
            input_per_million=input_price,
            output_per_million=output_price,
            cache_read_per_million=float(cache_read) if cache_read is not None else None,
            cache_write_per_million=float(cache_write) if cache_write is not None else None,
        )

    def get(self, model: str) -> ModelPrice:
        try:
            return self._prices[model]
        except KeyError as exc:
            raise PricingError(
                f"no price entry for model {model!r}. Add it to a --pricing config file "
                "(see README Configuration section)."
            ) from exc

    def known_models(self) -> list[str]:
        return sorted(self._prices)

    def cost_of(self, record: UsageRecord) -> float:
        price = self.get(record.model)
        cache_read_rate = price.cache_read_per_million or price.input_per_million
        cache_write_rate = price.cache_write_per_million or price.input_per_million
        cost = (
            record.input_tokens / 1_000_000 * price.input_per_million
            + record.output_tokens / 1_000_000 * price.output_per_million
            + record.cache_read_tokens / 1_000_000 * cache_read_rate
            + record.cache_write_tokens / 1_000_000 * cache_write_rate
        )
        return cost
