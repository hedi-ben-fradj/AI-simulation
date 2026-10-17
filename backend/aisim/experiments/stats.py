"""Small statistics helpers (no SciPy dependency).

Welch's t-test uses the Student-t CDF computed from the regularised incomplete
beta function (continued-fraction evaluation, as in Numerical Recipes).
"""

from __future__ import annotations

import math
from statistics import mean, stdev

# Two-sided 95% t critical values by degrees of freedom.
_T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
        11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093,
        20: 2.086, 25: 2.060, 30: 2.042, 40: 2.021, 60: 2.000, 120: 1.980}


def t_critical(df: float) -> float:
    if df <= 0:
        return float("nan")
    keys = sorted(_T95)
    for k in keys:
        if df <= k:
            return _T95[k]
    return 1.96


def describe(values: list[float]) -> dict[str, float | int | None]:
    vals = [v for v in values if v is not None and not math.isnan(v)]
    n = len(vals)
    if n == 0:
        return {"n": 0, "mean": None, "sd": None, "ci95": None, "min": None, "max": None}
    m = mean(vals)
    sd = stdev(vals) if n > 1 else 0.0
    ci = t_critical(n - 1) * sd / math.sqrt(n) if n > 1 else None
    return {"n": n, "mean": round(m, 6), "sd": round(sd, 6), "ci95": None if ci is None else round(ci, 6),
            "min": round(min(vals), 6), "max": round(max(vals), 6)}


def _betacf(a: float, b: float, x: float) -> float:
    max_iter, eps, fpmin = 200, 3e-14, 1e-300
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > fpmin else fpmin)
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > fpmin else fpmin)
        c = 1 + aa / c
        c = c if abs(c) > fpmin else fpmin
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > fpmin else fpmin)
        c = 1 + aa / c
        c = c if abs(c) > fpmin else fpmin
        de = d * c
        h *= de
        if abs(de - 1) < eps:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    front = math.exp(lbeta)
    if x < (a + 1) / (a + b + 2):
        return front * _betacf(a, b, x) / a
    return 1 - front * _betacf(b, a, 1 - x) / b


def t_two_sided_p(t: float, df: float) -> float:
    if df <= 0 or math.isnan(t):
        return float("nan")
    return betainc(df / 2, 0.5, df / (df + t * t))


def welch(a: list[float], b: list[float]) -> dict[str, float | None]:
    """Welch's unequal-variance t-test of mean(b) - mean(a)."""
    a = [v for v in a if v is not None]
    b = [v for v in b if v is not None]
    if len(a) < 2 or len(b) < 2:
        return {"diff": (mean(b) - mean(a)) if a and b else None, "t": None, "df": None, "p": None}
    ma, mb = mean(a), mean(b)
    va, vb = stdev(a) ** 2 / len(a), stdev(b) ** 2 / len(b)
    se = math.sqrt(va + vb)
    if se == 0:
        return {"diff": round(mb - ma, 6), "t": None, "df": None, "p": None if mb == ma else 0.0}
    t = (mb - ma) / se
    df = (va + vb) ** 2 / ((va ** 2) / (len(a) - 1) + (vb ** 2) / (len(b) - 1))
    return {"diff": round(mb - ma, 6), "t": round(t, 4), "df": round(df, 2), "p": round(t_two_sided_p(t, df), 6)}
