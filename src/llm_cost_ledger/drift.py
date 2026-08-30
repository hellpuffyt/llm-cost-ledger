"""Drift detection: did cost-per-request regress between two periods?

Any two averages differ by *some* amount just from noise. Flagging every
change would drown out real regressions in false positives. A group is
reported as a regression only if ALL of the following hold:

1. Both periods have at least ``min_days`` distinct daily data points
   (so a variance estimate exists and isn't from a single lucky/unlucky day).
2. The relative increase in mean cost-per-request is at least
   ``min_relative_increase`` (a tiny statistically "significant" wobble is
   still not worth paging anyone about).
3. Welch's t-test on the two samples of daily cost-per-request rejects the
   null hypothesis (no difference) at the ``alpha`` significance level.

Decreases are never flagged as regressions (that is good news), but are
still reported for visibility.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from llm_cost_ledger.models import AttributedRecord
from llm_cost_ledger.stats import StatsError, welch_t_test

GroupKey = tuple[str, ...]


@dataclass(frozen=True)
class DriftResult:
    group_key: GroupKey
    baseline_mean_cost_per_request: float
    current_mean_cost_per_request: float
    relative_change: float
    p_value: float | None
    baseline_days: int
    current_days: int
    is_regression: bool
    insufficient_data: bool
    note: str = ""


def _group_key(record: AttributedRecord, dims: tuple[str, ...]) -> GroupKey:
    values = []
    for dim in dims:
        if dim == "project":
            values.append(record.project)
        elif dim == "feature":
            values.append(record.feature)
        elif dim == "model":
            values.append(record.model)
        elif dim == "provider":
            values.append(record.provider)
        else:
            raise ValueError(f"unknown group-by dimension {dim!r}")
    return tuple(values)


def _daily_cost_per_request(
    records: list[AttributedRecord], dims: tuple[str, ...]
) -> dict[GroupKey, dict[date, list[AttributedRecord]]]:
    grouped: dict[GroupKey, dict[date, list[AttributedRecord]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for record in records:
        key = _group_key(record, dims)
        grouped[key][record.record_date].append(record)
    return grouped


def _daily_series(day_buckets: dict[date, list[AttributedRecord]]) -> list[float]:
    series = []
    for day_records in day_buckets.values():
        total_cost = sum(r.cost_usd for r in day_records)
        total_requests = sum(r.request_count for r in day_records)
        if total_requests > 0:
            series.append(total_cost / total_requests)
    return series


def detect_drift(
    baseline_records: list[AttributedRecord],
    current_records: list[AttributedRecord],
    *,
    group_by: tuple[str, ...] = ("project", "feature", "model"),
    alpha: float = 0.05,
    min_relative_increase: float = 0.10,
    min_days: int = 3,
) -> list[DriftResult]:
    """Compare cost-per-request between two disjoint record sets, per group.

    ``baseline_records`` and ``current_records`` should already be filtered
    to their respective date ranges by the caller.
    """
    if alpha <= 0 or alpha >= 1:
        raise ValueError("alpha must be between 0 and 1 exclusive")
    if min_days < 2:
        raise ValueError("min_days must be at least 2 (Welch's t-test needs a variance)")

    baseline_grouped = _daily_cost_per_request(baseline_records, group_by)
    current_grouped = _daily_cost_per_request(current_records, group_by)

    all_keys = sorted(set(baseline_grouped) | set(current_grouped))
    results: list[DriftResult] = []

    for key in all_keys:
        baseline_days = baseline_grouped.get(key, {})
        current_days = current_grouped.get(key, {})
        baseline_series = _daily_series(baseline_days)
        current_series = _daily_series(current_days)

        if len(baseline_series) < min_days or len(current_series) < min_days:
            note = (
                f"only {len(baseline_series)} baseline / {len(current_series)} current "
                f"daily data points; need at least {min_days} each to test significance"
            )
            baseline_mean = sum(baseline_series) / len(baseline_series) if baseline_series else 0.0
            current_mean = sum(current_series) / len(current_series) if current_series else 0.0
            rel_change = _relative_change(baseline_mean, current_mean)
            results.append(
                DriftResult(
                    group_key=key,
                    baseline_mean_cost_per_request=baseline_mean,
                    current_mean_cost_per_request=current_mean,
                    relative_change=rel_change,
                    p_value=None,
                    baseline_days=len(baseline_series),
                    current_days=len(current_series),
                    is_regression=False,
                    insufficient_data=True,
                    note=note,
                )
            )
            continue

        try:
            test = welch_t_test(baseline_series, current_series)
        except StatsError as exc:  # pragma: no cover - guarded by min_days >= 2 above
            raise AssertionError("unreachable: min_days enforces sample size") from exc

        rel_change = _relative_change(test.baseline_mean, test.current_mean)
        is_regression = (
            rel_change >= min_relative_increase
            and test.p_value < alpha
            and test.current_mean > test.baseline_mean
        )
        results.append(
            DriftResult(
                group_key=key,
                baseline_mean_cost_per_request=test.baseline_mean,
                current_mean_cost_per_request=test.current_mean,
                relative_change=rel_change,
                p_value=test.p_value,
                baseline_days=len(baseline_series),
                current_days=len(current_series),
                is_regression=is_regression,
                insufficient_data=False,
            )
        )

    return results


def _relative_change(baseline: float, current: float) -> float:
    if baseline == 0:
        return float("inf") if current > 0 else 0.0
    return (current - baseline) / baseline
