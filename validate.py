"""Standalone sanity-check for indicators.py — run as: python validate.py"""
import sys
print("Python", sys.version)

import numpy as np
import pandas as pd
print("pandas", pd.__version__, "numpy", np.__version__)

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from src.indicators import (
    pct_rank_series, mcclellan_oscillator, mcclellan_summation,
    cumulative_ad_line, composite_score, score_vix, score_junk, band_label,
)

# Test 1: pct_rank all-same → 50
s = pd.Series([5.0] * 100)
r = pct_rank_series(s, window=50, min_periods=10)
assert r.dropna().between(49, 51).all(), f"pct_rank all-same failed: {r.dropna().iloc[-1]}"
print("PASS: pct_rank all-same → 50")

# Test 2: pct_rank ascending → last is near 100
s = pd.Series(list(range(1, 101)), dtype=float)
r = pct_rank_series(s, window=100, min_periods=60)
assert r.dropna().iloc[-1] > 95, f"pct_rank max failed: {r.dropna().iloc[-1]}"
print("PASS: pct_rank max → >95")

# Test 3: McClellan hand-computed
adv = pd.Series([60., 55., 65., 70., 50.])
dec = pd.Series([40., 45., 35., 30., 50.])
net = [20., 10., 30., 40., 0.]
alpha19, alpha39 = 2/20, 2/40
e19 = [net[0]]; [e19.append(alpha19*v + (1-alpha19)*e19[-1]) for v in net[1:]]
e39 = [net[0]]; [e39.append(alpha39*v + (1-alpha39)*e39[-1]) for v in net[1:]]
expected = e19[-1] - e39[-1]
osc = mcclellan_oscillator(adv, dec)
assert abs(osc.iloc[-1] - expected) < 1e-9, f"McClellan failed: {osc.iloc[-1]} vs {expected}"
print("PASS: McClellan oscillator hand-computed")

# Test 4: composite renormalization
scores = {"a": pd.Series([80.]*100), "b": pd.Series([40.]*100), "c": pd.Series([np.nan]*100)}
result = composite_score(scores)
assert np.allclose(result, 60.0, atol=0.01), f"composite renorm failed: {result.iloc[-1]}"
print("PASS: composite renormalization (NaN excluded)")

# Test 5: inversion — low VIX → high score
vix = pd.Series([30.]*60 + [12.])
r = score_vix(vix)
assert r.dropna().iloc[-1] > 80, f"VIX inversion failed: {r.dropna().iloc[-1]}"
print("PASS: VIX inversion (low VIX → greed)")

# Test 6: band labels
assert band_label(10) == "Extreme Fear"
assert band_label(35) == "Fear"
assert band_label(50) == "Neutral"
assert band_label(65) == "Greed"
assert band_label(90) == "Extreme Greed"
print("PASS: band labels")

print("\nAll validation checks PASSED.")
