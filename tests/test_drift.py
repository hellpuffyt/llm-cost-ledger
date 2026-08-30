from datetime import date, timedelta

import pytest

from llm_cost_ledger.drift import detect_drift
from llm_cost_ledger.models import AttributedRecord, UsageRecord


def make_attributed(
    day: date, cost: float, requests: int, project: str = "p", model: str = "m"
) -> AttributedRecord:
    usage = UsageRecord(
        record_date=day,
        provider="openai",
        model=model,
        input_tokens=1,
        output_tokens=1,
        request_count=requests,
    )
    return AttributedRecord(usage=usage, project=project, feature="f", cost_usd=cost)


def daily_records(
    start: date, days: int, cost_per_request: float, requests_per_day: int, **kw: str
) -> list[AttributedRecord]:
    records = []
    for i in range(days):
        d = start + timedelta(days=i)
        records.append(
            make_attributed(d, cost_per_request * requests_per_day, requests_per_day, **kw)
        )
    return records


def test_stable_cost_is_not_flagged_as_regression() -> None:
    baseline = daily_records(date(2026, 1, 1), 6, cost_per_request=0.01, requests_per_day=100)
    current = daily_records(date(2026, 2, 1), 6, cost_per_request=0.0101, requests_per_day=100)
    results = detect_drift(baseline, current, min_days=3)
    assert len(results) == 1
    assert results[0].is_regression is False


def test_clear_regression_is_flagged() -> None:
    baseline = daily_records(date(2026, 1, 1), 6, cost_per_request=0.01, requests_per_day=100)
    current = daily_records(date(2026, 2, 1), 6, cost_per_request=0.02, requests_per_day=100)
    results = detect_drift(baseline, current, min_days=3)
    assert len(results) == 1
    assert results[0].is_regression is True
    assert results[0].relative_change == pytest.approx(1.0, rel=0.05)


def test_decrease_is_never_flagged_as_regression() -> None:
    baseline = daily_records(date(2026, 1, 1), 6, cost_per_request=0.02, requests_per_day=100)
    current = daily_records(date(2026, 2, 1), 6, cost_per_request=0.01, requests_per_day=100)
    results = detect_drift(baseline, current, min_days=3)
    assert results[0].is_regression is False
    assert results[0].relative_change < 0


def test_small_change_below_min_relative_increase_not_flagged() -> None:
    baseline = daily_records(date(2026, 1, 1), 10, cost_per_request=0.0100, requests_per_day=1000)
    # Only a ~2% bump, deterministic (no noise) so it WOULD be statistically
    # significant, but should still be suppressed by min_relative_increase.
    current = daily_records(date(2026, 2, 1), 10, cost_per_request=0.0102, requests_per_day=1000)
    results = detect_drift(baseline, current, min_days=3, min_relative_increase=0.10)
    assert results[0].is_regression is False


def test_noisy_but_flat_data_not_flagged() -> None:
    baseline_costs = [0.010, 0.014, 0.008, 0.012, 0.009, 0.013]
    current_costs = [0.011, 0.013, 0.009, 0.011, 0.010, 0.012]
    baseline = [
        make_attributed(date(2026, 1, 1) + timedelta(days=i), c * 100, 100)
        for i, c in enumerate(baseline_costs)
    ]
    current = [
        make_attributed(date(2026, 2, 1) + timedelta(days=i), c * 100, 100)
        for i, c in enumerate(current_costs)
    ]
    results = detect_drift(baseline, current, min_days=3)
    assert results[0].is_regression is False


def test_insufficient_data_marked_and_not_flagged() -> None:
    baseline = daily_records(date(2026, 1, 1), 2, cost_per_request=0.01, requests_per_day=100)
    current = daily_records(date(2026, 2, 1), 2, cost_per_request=0.05, requests_per_day=100)
    results = detect_drift(baseline, current, min_days=3)
    assert results[0].insufficient_data is True
    assert results[0].is_regression is False
    assert "need at least" in results[0].note


def test_groups_are_independent() -> None:
    baseline = daily_records(
        date(2026, 1, 1), 6, cost_per_request=0.01, requests_per_day=100, model="gpt-4o"
    ) + daily_records(
        date(2026, 1, 1), 6, cost_per_request=0.01, requests_per_day=100, model="gpt-4o-mini"
    )
    current = daily_records(
        date(2026, 2, 1), 6, cost_per_request=0.03, requests_per_day=100, model="gpt-4o"
    ) + daily_records(
        date(2026, 2, 1), 6, cost_per_request=0.0101, requests_per_day=100, model="gpt-4o-mini"
    )
    results = {r.group_key: r for r in detect_drift(baseline, current, min_days=3)}
    assert results[("p", "f", "gpt-4o")].is_regression is True
    assert results[("p", "f", "gpt-4o-mini")].is_regression is False


def test_group_only_in_current_period_reported_as_insufficient() -> None:
    baseline = daily_records(date(2026, 1, 1), 6, cost_per_request=0.01, requests_per_day=100)
    current_new_group = daily_records(
        date(2026, 2, 1), 6, cost_per_request=0.05, requests_per_day=100, project="new-project"
    )
    results = {r.group_key: r for r in detect_drift(baseline, current_new_group, min_days=3)}
    assert results[("new-project", "f", "m")].insufficient_data is True


def test_alpha_must_be_between_zero_and_one() -> None:
    baseline = daily_records(date(2026, 1, 1), 3, cost_per_request=0.01, requests_per_day=10)
    current = daily_records(date(2026, 2, 1), 3, cost_per_request=0.01, requests_per_day=10)
    with pytest.raises(ValueError, match="alpha"):
        detect_drift(baseline, current, alpha=0)
    with pytest.raises(ValueError, match="alpha"):
        detect_drift(baseline, current, alpha=1.5)


def test_min_days_must_be_at_least_two() -> None:
    baseline = daily_records(date(2026, 1, 1), 3, cost_per_request=0.01, requests_per_day=10)
    current = daily_records(date(2026, 2, 1), 3, cost_per_request=0.01, requests_per_day=10)
    with pytest.raises(ValueError, match="min_days"):
        detect_drift(baseline, current, min_days=1)


def test_group_by_custom_dimensions() -> None:
    baseline = daily_records(date(2026, 1, 1), 6, cost_per_request=0.01, requests_per_day=100)
    current = daily_records(date(2026, 2, 1), 6, cost_per_request=0.03, requests_per_day=100)
    results = detect_drift(baseline, current, group_by=("model",), min_days=3)
    assert results[0].group_key == ("m",)


def test_stricter_alpha_can_suppress_a_borderline_regression() -> None:
    baseline_costs = [0.0100, 0.0103, 0.0098, 0.0102, 0.0099, 0.0101]
    current_costs = [0.0113, 0.0116, 0.0109, 0.0115, 0.0110, 0.0112]
    baseline = [
        make_attributed(date(2026, 1, 1) + timedelta(days=i), c * 100, 100)
        for i, c in enumerate(baseline_costs)
    ]
    current = [
        make_attributed(date(2026, 2, 1) + timedelta(days=i), c * 100, 100)
        for i, c in enumerate(current_costs)
    ]
    loose = detect_drift(baseline, current, min_days=3, alpha=0.20, min_relative_increase=0.01)
    strict = detect_drift(baseline, current, min_days=3, alpha=1e-8, min_relative_increase=0.01)
    assert strict[0].p_value is not None and loose[0].p_value is not None
    assert strict[0].p_value == pytest.approx(loose[0].p_value)
    assert strict[0].is_regression is False
