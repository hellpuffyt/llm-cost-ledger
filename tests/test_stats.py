import pytest

from llm_cost_ledger.stats import StatsError, t_distribution_two_sided_p_value, welch_t_test


@pytest.mark.parametrize(
    "t_stat,df,expected_p",
    [
        (2.228, 10, 0.05),
        (3.169, 10, 0.01),
        (1.812, 10, 0.10),
        (12.706, 1, 0.05),
        (2.086, 20, 0.05),
        (2.042, 30, 0.05),
        (2.571, 5, 0.05),
    ],
)
def test_t_distribution_matches_standard_table_values(
    t_stat: float, df: float, expected_p: float
) -> None:
    p = t_distribution_two_sided_p_value(t_stat, df)
    assert p == pytest.approx(expected_p, abs=0.002)


def test_t_distribution_zero_statistic_gives_p_one() -> None:
    assert t_distribution_two_sided_p_value(0.0, 10) == pytest.approx(1.0)


def test_t_distribution_is_symmetric_in_t() -> None:
    p_pos = t_distribution_two_sided_p_value(2.5, 15)
    p_neg = t_distribution_two_sided_p_value(-2.5, 15)
    assert p_pos == pytest.approx(p_neg)


def test_t_distribution_large_t_gives_small_p() -> None:
    p = t_distribution_two_sided_p_value(50.0, 20)
    assert p < 0.0001


def test_t_distribution_rejects_nonpositive_df() -> None:
    with pytest.raises(StatsError):
        t_distribution_two_sided_p_value(1.0, 0)


def test_welch_requires_at_least_two_observations_each() -> None:
    with pytest.raises(StatsError):
        welch_t_test([1.0], [1.0, 2.0])
    with pytest.raises(StatsError):
        welch_t_test([1.0, 2.0], [1.0])


def test_welch_detects_clear_mean_shift() -> None:
    baseline = [1.0, 1.02, 0.98, 1.01, 0.99, 1.0]
    current = [2.0, 2.02, 1.98, 2.01, 1.99, 2.0]
    result = welch_t_test(baseline, current)
    assert result.p_value < 0.001
    assert result.current_mean > result.baseline_mean


def test_welch_does_not_flag_identical_samples() -> None:
    baseline = [1.0, 1.1, 0.9, 1.05, 0.95]
    result = welch_t_test(baseline, list(baseline))
    assert result.p_value == pytest.approx(1.0, abs=1e-6)


def test_welch_high_variance_noise_gives_high_p_value() -> None:
    # Same underlying distribution sampled twice - small differences in
    # sample mean should NOT look significant when variance is high.
    baseline = [10.0, 40.0, 15.0, 35.0, 20.0, 30.0]
    current = [12.0, 38.0, 18.0, 33.0, 22.0, 28.0]
    result = welch_t_test(baseline, current)
    assert result.p_value > 0.5


def test_welch_constant_equal_samples_gives_p_one() -> None:
    result = welch_t_test([5.0, 5.0, 5.0], [5.0, 5.0, 5.0])
    assert result.p_value == 1.0
    assert result.t_statistic == 0.0


def test_welch_constant_different_samples_gives_p_zero() -> None:
    result = welch_t_test([5.0, 5.0, 5.0], [9.0, 9.0, 9.0])
    assert result.p_value == 0.0
    assert result.current_mean == 9.0


def test_welch_result_reports_sample_sizes() -> None:
    result = welch_t_test([1.0, 2.0, 3.0], [4.0, 5.0])
    assert result.baseline_n == 3
    assert result.current_n == 2
