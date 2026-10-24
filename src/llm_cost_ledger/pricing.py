"""Pricing table lookups.

Prices change. The bundled default table (``data/default_pricing.yaml``) is a
snapshot taken when this tool was published and WILL go stale -- always
check your provider's current pricing page and override with your own
config file (``--pricing``) for anything that matters. This module never
calls out to the network to "refresh" prices; that would violate the
offline guarantee this tool makes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
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
        try:
            data = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            raise PricingError(f"pricing config is not valid YAML: {exc}") from exc
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
        cache_read = _optional_rate(name, "cache_read_per_million", fields)
        cache_write = _optional_rate(name, "cache_write_per_million", fields)
        for label, rate in (
            ("input_per_million", input_price),
            ("output_per_million", output_price),
        ):
            _check_rate(name, label, rate)
        return ModelPrice(
            input_per_million=input_price,
            output_per_million=output_price,
            cache_read_per_million=cache_read,
            cache_write_per_million=cache_write,
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
        """Cost in USD, computed exactly in decimal and returned as the nearest float."""
        return float(self.exact_cost_of(record))

    def exact_cost_of(self, record: UsageRecord) -> Decimal:
        """Cost in USD as an exact decimal (tokens x rate / 1,000,000)."""
        price = self.get(record.model)
        # An explicit 0.0 cache rate means "free", so test for None rather
        # than truthiness; only a missing rate falls back to the input rate.
        cache_read_rate = (
            price.cache_read_per_million
            if price.cache_read_per_million is not None
            else price.input_per_million
        )
        cache_write_rate = (
            price.cache_write_per_million
            if price.cache_write_per_million is not None
            else price.input_per_million
        )
        total = (
            record.input_tokens * _dec(price.input_per_million)
            + record.output_tokens * _dec(price.output_per_million)
            + record.cache_read_tokens * _dec(cache_read_rate)
            + record.cache_write_tokens * _dec(cache_write_rate)
        )
        return total / _MILLION


_MILLION = Decimal(1_000_000)


def _dec(rate: float) -> Decimal:
    """The decimal a rate was written as: 0.15 means 0.15, not 0.1499999..."""
    return Decimal(repr(rate))


def _check_rate(model: str, label: str, rate: float) -> None:
    if not math.isfinite(rate) or rate < 0:
        raise PricingError(f"pricing entry for {model!r}: {label} must be a finite number >= 0")


def _optional_rate(model: str, label: str, fields: dict[str, Any]) -> float | None:
    raw = fields.get(label)
    if raw is None:
        return None
    try:
        rate = float(raw)
    except (TypeError, ValueError) as exc:
        raise PricingError(f"pricing entry for {model!r} has a non-numeric {label}") from exc
    _check_rate(model, label, rate)
    return rate
