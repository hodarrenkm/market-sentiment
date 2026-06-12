"""
Pure functions for scoring market indicators and computing breadth metrics.
No I/O — all inputs and outputs are pandas Series/DataFrames.
"""
import numpy as np
import pandas as pd


# ── Percentile rank ───────────────────────────────────────────────────────────

def pct_rank_series(
    series: pd.Series,
    window: int = 252,
    min_periods: int = 60,
) -> pd.Series:
    """
    For each element, compute its percentile rank within the trailing window.
    Returns a Series in [0, 100]. NaN where the window has fewer than min_periods.
    Ties split at the midpoint (weak ranking).
    """
    def _rank_last(arr: np.ndarray) -> float:
        val = arr[-1]
        n = len(arr)
        if n <= 1:
            return 50.0
        below = (arr < val).sum()
        equal = (arr == val).sum()
        # Average 1-indexed rank of tied values, then map to [0, 100].
        # min → 0%, max → 100%, ties → midpoint.
        avg_rank = below + (equal + 1.0) / 2.0
        return float(avg_rank - 1) / float(n - 1) * 100.0

    return series.rolling(window, min_periods=min_periods).apply(_rank_last, raw=True)


# ── Sub-indicator scores (each returns a Series in [0, 100]) ─────────────────

def score_momentum(gspc_closes: pd.Series) -> pd.Series:
    """Pct-rank of (close / 125-day MA − 1). High = greed."""
    ma125 = gspc_closes.rolling(125, min_periods=60).mean()
    ratio = gspc_closes / ma125 - 1
    return pct_rank_series(ratio)


def score_vix(vix_closes: pd.Series) -> pd.Series:
    """100 − pct-rank of (VIX / 50-day MA). Low VIX → high score = greed."""
    ma50 = vix_closes.rolling(50, min_periods=25).mean()
    ratio = vix_closes / ma50
    return 100.0 - pct_rank_series(ratio)


def score_safe_haven(spy_closes: pd.Series, ief_closes: pd.Series) -> pd.Series:
    """Pct-rank of (SPY 20d return − IEF 20d return). SPY outperformance = greed."""
    spy_ret = spy_closes.pct_change(20)
    ief_ret = ief_closes.pct_change(20)
    diff = spy_ret - ief_ret
    return pct_rank_series(diff)


def score_junk_credit(hyg: pd.Series, lqd: pd.Series) -> pd.Series:
    """Pct-rank of HYG 20-day return minus LQD 20-day return.
    HY bonds outperforming IG = tight credit conditions = greed."""
    diff = hyg.pct_change(20) - lqd.pct_change(20)
    return pct_rank_series(diff)



def score_highs_lows(nh: pd.Series, nl: pd.Series) -> pd.Series:
    """Pct-rank of (NH − NL) / (NH + NL). Dominance of new highs = greed."""
    denom = (nh + nl).replace(0, np.nan)
    ratio = (nh - nl) / denom
    return pct_rank_series(ratio)


def score_breadth(mclellan: pd.Series) -> pd.Series:
    """Pct-rank of McClellan oscillator. Positive oscillator = greed."""
    return pct_rank_series(mclellan)


# ── Breadth computations ──────────────────────────────────────────────────────

def mcclellan_oscillator(advances: pd.Series, declines: pd.Series) -> pd.Series:
    """EMA19 − EMA39 of daily net advances (advances − declines)."""
    net = advances - declines
    ema19 = net.ewm(span=19, adjust=False).mean()
    ema39 = net.ewm(span=39, adjust=False).mean()
    return ema19 - ema39


def mcclellan_summation(oscillator: pd.Series) -> pd.Series:
    """Cumulative sum of the McClellan oscillator."""
    return oscillator.cumsum()


def cumulative_ad_line(advances: pd.Series, declines: pd.Series) -> pd.Series:
    """Running sum of net advances."""
    return (advances - declines).cumsum()


# ── Composite score ───────────────────────────────────────────────────────────

def composite_score(score_dict: dict) -> pd.Series:
    """
    Equal-weighted mean of available sub-scores (NaN columns are excluded,
    so the composite automatically renormalizes over however many are live).
    Returns a Series in [0, 100].
    """
    df = pd.DataFrame(score_dict)
    return df.mean(axis=1, skipna=True)


# ── Band labels ───────────────────────────────────────────────────────────────

def band_label(score: float) -> str:
    if score < 25:
        return "Extreme Fear"
    if score < 45:
        return "Fear"
    if score < 55:
        return "Neutral"
    if score < 75:
        return "Greed"
    return "Extreme Greed"


def band_color(score: float) -> str:
    if score < 25:
        return "#e63946"
    if score < 45:
        return "#f4a261"
    if score < 55:
        return "#e9c46a"
    if score < 75:
        return "#2a9d8f"
    return "#264653"
