"""Unit tests for indicators.py — pure function coverage."""
import numpy as np
import pandas as pd
import pytest

from src.indicators import (
    band_label,
    composite_score,
    cumulative_ad_line,
    mcclellan_oscillator,
    mcclellan_summation,
    pct_rank_series,
    score_breadth,
    score_junk,
    score_put_call,
    score_safe_haven,
    score_vix,
)


# ── pct_rank_series ───────────────────────────────────────────────────────────

class TestPctRankSeries:
    def test_all_same_values_gives_50(self):
        s = pd.Series([5.0] * 100)
        result = pct_rank_series(s, window=50, min_periods=10)
        assert result.dropna().between(49.0, 51.0).all()

    def test_max_value_scores_near_100(self):
        # Ascending series: the last value is the maximum
        s = pd.Series(list(range(1, 101)), dtype=float)
        result = pct_rank_series(s, window=100, min_periods=60)
        assert result.dropna().iloc[-1] > 95.0

    def test_min_value_scores_near_0(self):
        # Descending series: the last value is the minimum
        s = pd.Series(list(range(100, 0, -1)), dtype=float)
        result = pct_rank_series(s, window=100, min_periods=60)
        assert result.dropna().iloc[-1] < 5.0

    def test_min_periods_enforced(self):
        # Only 3 observations, min_periods=60 → all NaN
        s = pd.Series([1.0, 2.0, 3.0])
        result = pct_rank_series(s, window=252, min_periods=60)
        assert result.isna().all()

    def test_result_bounded_0_to_100(self):
        rng = np.random.default_rng(42)
        s = pd.Series(rng.standard_normal(300))
        result = pct_rank_series(s, window=100, min_periods=60)
        valid = result.dropna()
        assert valid.ge(0.0).all() and valid.le(100.0).all()

    def test_window_respects_rolling_size(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = pct_rank_series(s, window=3, min_periods=3)
        # First two should be NaN (window not full)
        assert result.iloc[0] is np.nan or pd.isna(result.iloc[0])
        assert result.iloc[1] is np.nan or pd.isna(result.iloc[1])
        # Third: [1,2,3] → 3 is the max of the 3-value window → 100%
        assert np.isclose(result.iloc[2], 100.0)


# ── Inversion checks ──────────────────────────────────────────────────────────

class TestInversion:
    def test_score_vix_low_vix_gives_high_score(self):
        # Need enough values: MA min_periods=25 + pct_rank min_periods=60 requires 84+ rows.
        # VIX at 30 for 89 days then drops to 12 → far below 50-day MA → greed.
        vix = pd.Series([30.0] * 89 + [12.0])
        result = score_vix(vix)
        assert result.dropna().iloc[-1] > 80.0

    def test_score_vix_high_vix_gives_low_score(self):
        # VIX at 15 for 89 days then spikes to 40 → far above 50-day MA → fear.
        vix = pd.Series([15.0] * 89 + [40.0])
        result = score_vix(vix)
        assert result.dropna().iloc[-1] < 20.0

    def test_score_junk_tight_spread_gives_high_score(self):
        # HY OAS at multi-year low → 100 − low_rank = high → greed
        hy = pd.Series([5.0] * 60 + [1.0])
        result = score_junk(hy)
        assert result.dropna().iloc[-1] > 80.0

    def test_score_junk_wide_spread_gives_low_score(self):
        hy = pd.Series([2.0] * 60 + [8.0])
        result = score_junk(hy)
        assert result.dropna().iloc[-1] < 20.0

    def test_score_put_call_low_ratio_gives_high_score(self):
        pc = pd.Series([1.2] * 60 + [0.4])
        result = score_put_call(pc)
        assert result.dropna().iloc[-1] > 80.0

    def test_score_safe_haven_spy_leads_gives_high_score(self):
        # SPY flat for 130 days then surges to 200 — last 20-day SPY return is
        # exceptional vs a long history of ~0% returns → should score > 70.
        idx = pd.date_range("2022-01-01", periods=150, freq="B")
        spy_vals = [100.0] * 130 + [200.0] * 20
        spy = pd.Series(spy_vals, index=idx)
        ief = pd.Series(np.full(150, 100.0), index=idx)
        result = score_safe_haven(spy, ief)
        assert result.dropna().iloc[-1] > 70.0


# ── Composite score / null handling ──────────────────────────────────────────

class TestCompositeScore:
    def test_renormalizes_when_column_all_null(self):
        # mean of [80, 40] = 60; 'c' is NaN and should be excluded
        scores = {
            "a": pd.Series(np.full(100, 80.0)),
            "b": pd.Series(np.full(100, 40.0)),
            "c": pd.Series(np.full(100, np.nan)),
        }
        result = composite_score(scores)
        assert np.allclose(result, 60.0, atol=0.01)

    def test_all_null_row_is_nan(self):
        scores = {
            "a": pd.Series([np.nan, 50.0]),
            "b": pd.Series([np.nan, 60.0]),
        }
        result = composite_score(scores)
        assert pd.isna(result.iloc[0])
        assert np.isclose(result.iloc[1], 55.0)

    def test_six_components_renormalize_correctly(self):
        # 5 components at 80 and 1 null → composite should still be 80
        scores = {f"s{i}": pd.Series([80.0]) for i in range(5)}
        scores["null_one"] = pd.Series([np.nan])
        result = composite_score(scores)
        assert np.isclose(result.iloc[0], 80.0)

    def test_single_component(self):
        scores = {"only": pd.Series([42.0, 58.0])}
        result = composite_score(scores)
        assert np.allclose(result.values, [42.0, 58.0])


# ── McClellan oscillator — hand-computed fixture ──────────────────────────────

class TestMcClellan:
    # net advances: [20, 10, 30, 40, 0]
    ADV = pd.Series([60.0, 55.0, 65.0, 70.0, 50.0])
    DEC = pd.Series([40.0, 45.0, 35.0, 30.0, 50.0])

    def _hand_compute_ema(self, net_values, span):
        alpha = 2 / (span + 1)
        ema = [net_values[0]]
        for v in net_values[1:]:
            ema.append(alpha * v + (1 - alpha) * ema[-1])
        return ema

    def test_oscillator_last_value_matches_hand_computation(self):
        net = [20.0, 10.0, 30.0, 40.0, 0.0]
        e19 = self._hand_compute_ema(net, 19)
        e39 = self._hand_compute_ema(net, 39)
        expected = e19[-1] - e39[-1]

        osc = mcclellan_oscillator(self.ADV, self.DEC)
        assert np.isclose(osc.iloc[-1], expected, rtol=1e-6)

    def test_oscillator_all_values_match(self):
        net = [20.0, 10.0, 30.0, 40.0, 0.0]
        e19 = self._hand_compute_ema(net, 19)
        e39 = self._hand_compute_ema(net, 39)
        expected = [a - b for a, b in zip(e19, e39)]

        osc = mcclellan_oscillator(self.ADV, self.DEC)
        assert np.allclose(osc.values, expected, rtol=1e-6)

    def test_summation_equals_cumsum_of_oscillator(self):
        osc = mcclellan_oscillator(self.ADV, self.DEC)
        summation = mcclellan_summation(osc)
        assert np.isclose(summation.iloc[-1], osc.sum(), rtol=1e-6)

    def test_cumulative_ad_line(self):
        adv = pd.Series([100.0, 120.0, 90.0])
        dec = pd.Series([80.0, 70.0, 100.0])
        ad = cumulative_ad_line(adv, dec)
        # net: [20, 50, -10], cumsum: [20, 70, 60]
        assert np.allclose(ad.values, [20.0, 70.0, 60.0])

    def test_net_advances_flat_gives_zero_oscillator_at_convergence(self):
        # Constant net advances: EMAs converge to the same value → oscillator → 0
        net_val = 100.0
        adv = pd.Series([net_val + 50] * 200)
        dec = pd.Series([50.0] * 200)
        osc = mcclellan_oscillator(adv, dec)
        # After ~200 days the EMAs have converged
        assert abs(osc.iloc[-1]) < 0.01 * net_val


# ── Band labels ───────────────────────────────────────────────────────────────

class TestBandLabel:
    def test_extreme_fear(self):
        assert band_label(10) == "Extreme Fear"

    def test_fear(self):
        assert band_label(35) == "Fear"

    def test_neutral(self):
        assert band_label(50) == "Neutral"

    def test_greed(self):
        assert band_label(65) == "Greed"

    def test_extreme_greed(self):
        assert band_label(90) == "Extreme Greed"

    def test_boundaries(self):
        assert band_label(25) == "Fear"     # 25 is not extreme fear
        assert band_label(45) == "Neutral"  # 45 is not fear
        assert band_label(55) == "Greed"    # 55 is not neutral
        assert band_label(75) == "Extreme Greed"
