"""
Pipeline orchestrator: fetch → compute → append → render.

Run with:  python -m src.pipeline

Behavior:
- Idempotent: re-running on the same day overwrites that day's row.
- One bad source never fails the run; degraded data is logged + flagged.
- If history is already up-to-date, exit 0 with a log line.
"""
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from src import fetch, indicators, render

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent
HISTORY_PATH = _ROOT / "data" / "history.csv"
HISTORY_PATH.parent.mkdir(exist_ok=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _last_us_trading_day() -> pd.Timestamp:
    """Most recent weekday on or before today (US calendar proxy)."""
    today = pd.Timestamp.now().normalize()
    offset = max(0, today.weekday() - 4)  # 5=Sat→1, 6=Sun→2
    return today - pd.Timedelta(days=offset)


def _safe_fetch(fn, name: str):
    """Run fn(); on any exception log and return None instead of raising."""
    try:
        result = fn()
        logger.info("Fetched %s OK", name)
        return result
    except Exception as exc:
        logger.error("FAILED to fetch %s: %s — continuing with null", name, exc)
        return None


def _align(series, index: pd.DatetimeIndex, name: str):
    """Reindex series to the master trading calendar, forward-fill gaps."""
    if series is None:
        return None
    try:
        aligned = series.reindex(index, method="ffill")
        return aligned
    except Exception as exc:
        logger.warning("Could not align %s: %s", name, exc)
        return None


def _load_history() -> pd.DataFrame:
    if HISTORY_PATH.exists():
        df = pd.read_csv(HISTORY_PATH, index_col="date", parse_dates=True)
        df.index = pd.to_datetime(df.index)
        if df.index.tz is not None:
            df.index = df.index.tz_convert(None)
        return df
    return pd.DataFrame()


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run() -> None:
    target = _last_us_trading_day()
    logger.info("Target trading day: %s", target.date())

    # ── Skip guard ─────────────────────────────────────────────────────────────
    existing = _load_history()
    if not existing.empty:
        latest = existing.index.max()
        if latest >= target:
            logger.info(
                "History already current through %s (target %s) — exiting.",
                latest.date(), target.date(),
            )
            sys.exit(0)

    # ── Fetch ──────────────────────────────────────────────────────────────────
    prices = _safe_fetch(
        lambda: fetch.get_yfinance_prices(["^GSPC", "^VIX", "SPY", "IEF"], period="3y"),
        "yfinance ^GSPC/^VIX/SPY/IEF",
    )
    if prices is None or prices.empty:
        logger.critical("Cannot proceed without price data — aborting")
        sys.exit(1)

    hy_series = _safe_fetch(lambda: fetch.get_fred_series("BAMLH0A0HYM2"), "FRED BAMLH0A0HYM2")
    pc_series = _safe_fetch(fetch.get_cboe_put_call, "CBOE put/call")
    breadth_df = _safe_fetch(fetch.get_breadth_series, "S&P 500 breadth panel")
    cnn_score = _safe_fetch(fetch.get_cnn_fear_greed, "CNN Fear & Greed")

    # ── Master calendar: S&P 500 trading days ─────────────────────────────────
    gspc_col = "^GSPC" if "^GSPC" in prices.columns else prices.columns[0]
    dates = prices.dropna(subset=[gspc_col]).index
    dates = dates[dates <= target]

    gspc = prices[gspc_col].reindex(dates)
    vix = prices["^VIX"].reindex(dates) if "^VIX" in prices.columns else None
    spy = prices["SPY"].reindex(dates) if "SPY" in prices.columns else None
    ief = prices["IEF"].reindex(dates) if "IEF" in prices.columns else None

    hy_aligned = _align(hy_series, dates, "HY OAS")
    pc_aligned = _align(pc_series, dates, "put/call") if pc_series is not None else None
    breadth_aligned = (
        breadth_df.reindex(dates, method="ffill")
        if breadth_df is not None else None
    )

    # ── Compute sub-indicator scores ──────────────────────────────────────────
    score_map: dict = {}

    score_map["momentum"] = indicators.score_momentum(gspc)

    if vix is not None:
        score_map["vix"] = indicators.score_vix(vix)
    else:
        logger.warning("VIX unavailable — sub-indicator null")

    if spy is not None and ief is not None:
        score_map["safe_haven"] = indicators.score_safe_haven(spy, ief)
    else:
        logger.warning("SPY/IEF unavailable — safe-haven sub-indicator null")

    if hy_aligned is not None:
        score_map["junk"] = indicators.score_junk(hy_aligned)
    else:
        logger.warning("HY OAS unavailable — junk-bond sub-indicator null")

    if pc_aligned is not None:
        score_map["put_call"] = indicators.score_put_call(pc_aligned)
    else:
        logger.info("P/C ratio null — composite renormalized over remaining components")

    mclellan_osc = None
    if breadth_aligned is not None:
        nh = breadth_aligned["nh"].astype(float)
        nl = breadth_aligned["nl"].astype(float)
        adv = breadth_aligned["advances"].astype(float)
        dec = breadth_aligned["declines"].astype(float)
        mclellan_osc = indicators.mcclellan_oscillator(adv, dec)
        score_map["nh_nl"] = indicators.score_highs_lows(nh, nl)
        score_map["breadth"] = indicators.score_breadth(mclellan_osc)
    else:
        logger.warning("Breadth panel unavailable — NH/NL and breadth sub-indicators null")

    composite = indicators.composite_score(score_map)

    # ── Staleness flags ────────────────────────────────────────────────────────
    stale_sources = []
    if fetch.is_stale(hy_series, "FRED HY OAS"):
        stale_sources.append("HY OAS")
    if fetch.is_stale(pc_series, "CBOE P/C"):
        stale_sources.append("CBOE P/C")
    if fetch.is_stale(prices, "yfinance"):
        stale_sources.append("prices")

    # ── Assemble new-history DataFrame (full recompute over fetched window) ───
    new_rows = pd.DataFrame(index=dates)
    new_rows.index.name = "date"

    new_rows["gspc_close"] = gspc
    if vix is not None:
        new_rows["vix_close"] = vix
    if spy is not None:
        new_rows["spy_close"] = spy
    if ief is not None:
        new_rows["ief_close"] = ief
    if hy_aligned is not None:
        new_rows["hy_oas"] = hy_aligned
    if pc_aligned is not None:
        new_rows["pc_ratio"] = pc_aligned

    if breadth_aligned is not None:
        new_rows["nh"] = breadth_aligned["nh"]
        new_rows["nl"] = breadth_aligned["nl"]
        new_rows["advances"] = breadth_aligned["advances"]
        new_rows["declines"] = breadth_aligned["declines"]
        new_rows["mclellan_osc"] = mclellan_osc
        new_rows["mclellan_sum"] = indicators.mcclellan_summation(mclellan_osc)
        new_rows["ad_line"] = indicators.cumulative_ad_line(adv, dec)

    for key, s in score_map.items():
        new_rows[f"score_{key}"] = s

    new_rows["composite"] = composite

    # Store the CNN score only on the target date (it's a single point)
    if cnn_score is not None:
        if target in new_rows.index:
            new_rows.loc[target, "cnn_score"] = float(cnn_score)

    # ── Merge with existing history (new data wins on overlapping dates) ──────
    if not existing.empty:
        combined = pd.concat([existing, new_rows])
        combined = combined[~combined.index.duplicated(keep="last")]
        history = combined.sort_index()
    else:
        history = new_rows.sort_index()

    # ── Write history ──────────────────────────────────────────────────────────
    history.to_csv(HISTORY_PATH)
    n_rows = len(history)
    logger.info("History saved: %d rows → %s", n_rows, HISTORY_PATH)

    if n_rows < 60:
        logger.warning("Only %d history rows — percentile scores may be unreliable", n_rows)

    # ── Render dashboard ───────────────────────────────────────────────────────
    render.build(history, stale_sources=stale_sources)
    logger.info("Pipeline complete for %s.", target.date())


if __name__ == "__main__":
    run()
