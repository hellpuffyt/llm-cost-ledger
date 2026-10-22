"""Parsers that turn provider usage exports into UsageRecord objects.

Two shapes are supported out of the box:

* ``openai`` -- a JSON export shaped like OpenAI's usage/aggregation API:
  ``{"data": [{"start_time": <unix ts>, "n_requests": int,
  "n_context_tokens_total": int, "n_generated_tokens_total": int,
  "model": str, "project_id": str, "api_key_id": str}, ...]}``
  A flat CSV with equivalent column names is also accepted.

* ``anthropic`` -- a CSV export shaped like Anthropic's usage/cost report:
  ``date,workspace_id,model,input_tokens,output_tokens,
  cache_creation_input_tokens,cache_read_input_tokens,request_count``
  A JSON list-of-objects with the same field names is also accepted.

Real provider export formats change over time; both parsers accept a small,
documented set of column/field name aliases so minor schema drift does not
break ingestion outright. Anything genuinely unrecognised raises
IngestError rather than silently dropping data.
"""

from __future__ import annotations

import csv
import io
import json
import math
from collections.abc import Iterable
from datetime import date, datetime, timezone
from typing import Any

from llm_cost_ledger.models import UsageRecord


class IngestError(ValueError):
    """Raised when a usage export cannot be parsed or is missing fields."""


def _to_int(value: Any, field_name: str) -> int:
    """A non-negative whole-number count. ``12.0`` is accepted; ``12.7``,
    ``inf``, ``nan`` and negatives are rejected rather than truncated."""
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        raise IngestError(f"expected an integer for {field_name!r}, got {value!r}")
    if isinstance(value, int):
        number = value
    else:
        text = str(value).strip()
        try:
            number = int(text)
        except ValueError:
            try:
                as_float = float(text)
            except ValueError as exc:
                raise IngestError(f"expected an integer for {field_name!r}, got {value!r}") from exc
            if not math.isfinite(as_float) or not as_float.is_integer():
                raise IngestError(
                    f"expected a whole number for {field_name!r}, got {value!r}"
                ) from None
            number = int(as_float)
    if number < 0:
        raise IngestError(f"{field_name!r} must not be negative, got {value!r}")
    return number


def _first(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def _parse_date(value: Any, field_name: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value), tz=timezone.utc).date()
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return datetime.fromtimestamp(float(text), tz=timezone.utc).date()
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y/%m/%d"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
    raise IngestError(f"could not parse a date from {field_name}={value!r}")


def _load_rows(raw: str) -> list[dict[str, Any]]:
    """Load a JSON (dict-with-data-list, or list) or CSV payload into rows."""
    stripped = raw.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise IngestError(f"invalid JSON: {exc}") from exc
        if isinstance(parsed, dict):
            for key in ("data", "records", "usage", "items"):
                if key in parsed and isinstance(parsed[key], list):
                    return _require_objects(parsed[key])
            raise IngestError("JSON object payload must contain a data/records/usage/items list")
        if isinstance(parsed, list):
            return _require_objects(parsed)
        raise IngestError("JSON payload must be an object or a list")
    try:
        reader = csv.DictReader(io.StringIO(raw))
        return [dict(row) for row in reader]
    except csv.Error as exc:
        raise IngestError(f"invalid CSV: {exc}") from exc


def _require_objects(items: list[Any]) -> list[dict[str, Any]]:
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise IngestError(f"row {i} must be a JSON object, got {type(item).__name__}")
    return list(items)


def parse_openai_export(raw: str) -> list[UsageRecord]:
    """Parse an OpenAI-style usage export (JSON or CSV) into UsageRecords."""
    rows = _load_rows(raw)
    records: list[UsageRecord] = []
    for i, row in enumerate(rows):
        try:
            ts = _first(row, "start_time", "date", "aggregation_timestamp", "timestamp")
            model = _first(row, "model", "snapshot_id")
            if ts is None or model is None:
                raise IngestError("row is missing a date/timestamp or model field")
            record_date = _parse_date(ts, "start_time/date")
            input_tokens = _to_int(
                _first(row, "n_context_tokens_total", "input_tokens", "prompt_tokens"),
                "n_context_tokens_total",
            )
            output_tokens = _to_int(
                _first(row, "n_generated_tokens_total", "output_tokens", "completion_tokens"),
                "n_generated_tokens_total",
            )
            request_count = _to_int(
                _first(row, "n_requests", "request_count", "requests"), "n_requests"
            )
            if request_count == 0 and (input_tokens or output_tokens):
                request_count = 1
            project_id = _first(row, "project_id", "project")
            api_key_id = _first(row, "api_key_id", "api_key")
            records.append(
                UsageRecord(
                    record_date=record_date,
                    provider="openai",
                    model=str(model),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    request_count=request_count,
                    raw_project_id=str(project_id) if project_id else None,
                    raw_api_key_id=str(api_key_id) if api_key_id else None,
                )
            )
        except (IngestError, ValueError) as exc:
            raise IngestError(f"openai export row {i}: {exc}") from exc
    return records


def parse_anthropic_export(raw: str) -> list[UsageRecord]:
    """Parse an Anthropic-style usage export (CSV or JSON) into UsageRecords."""
    rows = _load_rows(raw)
    records: list[UsageRecord] = []
    for i, row in enumerate(rows):
        try:
            ts = _first(row, "date", "start_time", "usage_date")
            model = _first(row, "model")
            if ts is None or model is None:
                raise IngestError("row is missing a date or model field")
            record_date = _parse_date(ts, "date")
            input_tokens = _to_int(_first(row, "input_tokens"), "input_tokens")
            output_tokens = _to_int(_first(row, "output_tokens"), "output_tokens")
            cache_write = _to_int(
                _first(row, "cache_creation_input_tokens", "cache_write_tokens"),
                "cache_creation_input_tokens",
            )
            cache_read = _to_int(
                _first(row, "cache_read_input_tokens", "cache_read_tokens"),
                "cache_read_input_tokens",
            )
            request_count = _to_int(
                _first(row, "request_count", "n_requests", "requests"), "request_count"
            )
            if request_count == 0 and (input_tokens or output_tokens):
                request_count = 1
            workspace_id = _first(row, "workspace_id", "workspace")
            records.append(
                UsageRecord(
                    record_date=record_date,
                    provider="anthropic",
                    model=str(model),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_write_tokens=cache_write,
                    cache_read_tokens=cache_read,
                    request_count=request_count,
                    raw_project_id=str(workspace_id) if workspace_id else None,
                )
            )
        except (IngestError, ValueError) as exc:
            raise IngestError(f"anthropic export row {i}: {exc}") from exc
    return records


PARSERS = {
    "openai": parse_openai_export,
    "anthropic": parse_anthropic_export,
}


def parse_export(provider: str, raw: str) -> list[UsageRecord]:
    try:
        parser = PARSERS[provider]
    except KeyError as exc:
        raise IngestError(
            f"unknown provider {provider!r}; supported providers are {sorted(PARSERS)}"
        ) from exc
    return parser(raw)


def merge(*record_groups: Iterable[UsageRecord]) -> list[UsageRecord]:
    """Flatten several groups of records (e.g. from different files) into one."""
    merged: list[UsageRecord] = []
    for group in record_groups:
        merged.extend(group)
    return merged
