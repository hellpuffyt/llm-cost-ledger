"""Small self-contained statistics helpers (no numpy/scipy dependency).

Implements Welch's t-test (unequal variance two-sample t-test) including a
proper Student's t two-sided p-value via the regularised incomplete beta
function, following the standard continued-fraction algorithm (as in
Numerical Recipes). This avoids a heavy scipy dependency while still giving
correct p-values rather than a rough normal approximation.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass


class StatsError(ValueError):
    """Raised when a statistical computation is given invalid input."""


def _betacf(
    a: float, b: float, x: float, max_iterations: int = 200, epsilon: float = 3e-11
) -> float:
    """Continued fraction for the incomplete beta function (used by betai)."""
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, max_iterations + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < epsilon:
            break
    return h


def _regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta function I_x(a, b), for x in [0, 1]."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_beta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(log_beta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def t_distribution_two_sided_p_value(t_stat: float, degrees_of_freedom: float) -> float:
    """Two-sided p-value for Student's t distribution.

    Uses p = I_x(df/2, 1/2) with x = df / (df + t^2), the standard closed
    form for the two-tailed tail probability of the t distribution.
    """
    if degrees_of_freedom <= 0:
        raise StatsError("degrees_of_freedom must be positive")
    x = degrees_of_freedom / (degrees_of_freedom + t_stat * t_stat)
    return _regularized_incomplete_beta(degrees_of_freedom / 2.0, 0.5, x)


@dataclass(frozen=True)
class WelchTTestResult:
    baseline_mean: float
    current_mean: float
    baseline_n: int
    current_n: int
    t_statistic: float
    degrees_of_freedom: float
    p_value: float


def welch_t_test(baseline: list[float], current: list[float]) -> WelchTTestResult:
    """Welch's two-sample t-test (does not assume equal variances).

    Requires at least 2 observations in each sample so a variance can be
    estimated. Raises StatsError otherwise -- callers should treat "not
    enough data" as "cannot claim significance", never as "no difference".
    """
    if len(baseline) < 2 or len(current) < 2:
        raise StatsError("each sample needs at least 2 observations for Welch's t-test")

    mean_b = statistics.mean(baseline)
    mean_c = statistics.mean(current)
    var_b = statistics.variance(baseline)
    var_c = statistics.variance(current)
    n_b = len(baseline)
    n_c = len(current)

    se_b = var_b / n_b
    se_c = var_c / n_c
    standard_error = math.sqrt(se_b + se_c)

    if standard_error == 0.0:
        # Both samples are perfectly constant. If the means differ at all
        # that is a certain difference; if they're equal there is none.
        t_stat = 0.0 if mean_b == mean_c else math.inf
        p_value = 1.0 if mean_b == mean_c else 0.0
        df = n_b + n_c - 2.0
        return WelchTTestResult(mean_b, mean_c, n_b, n_c, t_stat, df, p_value)

    t_stat = (mean_c - mean_b) / standard_error
    numerator = (se_b + se_c) ** 2
    denominator = (se_b**2) / (n_b - 1) + (se_c**2) / (n_c - 1)
    df = numerator / denominator if denominator > 0 else float(n_b + n_c - 2)
    p_value = t_distribution_two_sided_p_value(t_stat, df)

    return WelchTTestResult(
        baseline_mean=mean_b,
        current_mean=mean_c,
        baseline_n=n_b,
        current_n=n_c,
        t_statistic=t_stat,
        degrees_of_freedom=df,
        p_value=p_value,
    )
