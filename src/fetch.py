"""
All data-source fetchers. Each function retries 3× with exponential backoff;
on final failure it logs and returns None (or raises for callers that treat
the data as mandatory). The pipeline treats every source as optional except
GSPC/VIX/SPY/IEF, which are essential.

Note: the equity put/call ratio sub-indicator has been permanently removed.
CBOE CDN endpoints returned 403 and no reliable free alternative exists
without an API key. The composite renormalizes over the remaining 6 components.

Seam for exchange breadth: replace get_breadth_series() body with a
Barchart feed ($MAHN / $MALN / $MAAD etc.) — the return schema
(DataFrame with columns nh, nl, advances, declines indexed by date) is stable.
"""
import io
import logging
import random
import time
import warnings
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
import yfinance as yf

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent
DATA_DIR = _ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

_SP500_CACHE = DATA_DIR / "sp500_universe.csv"
_UNIVERSE_TTL_DAYS = 7

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


# ── Retry helper ──────────────────────────────────────────────────────────────

def _retry(fn, retries: int = 3, backoff: float = 2.0, max_delay: float = 30.0):
    last_exc: Exception = RuntimeError("no attempts made")
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                delay = min(backoff ** attempt + random.uniform(0, 1), max_delay)
                logger.warning(
                    "Attempt %d/%d failed (%s); retrying in %.1fs",
                    attempt + 1, retries, exc, delay,
                )
                time.sleep(delay)
    raise last_exc


def _make_yf_session() -> requests.Session:
    """requests.Session with a browser User-Agent to reduce yfinance rate-limiting."""
    s = requests.Session()
    s.headers.update(_BROWSER_HEADERS)
    return s


# ── yfinance price data ───────────────────────────────────────────────────────

def get_yfinance_prices(tickers: list, period: str = "3y") -> pd.DataFrame:
    """
    Adjusted Close prices for the given tickers.
    Returns a DataFrame indexed by date (tz-naive), one column per ticker.

    Core index tickers (^GSPC, ^VIX, SPY, IEF) are fetched here separately
    from the large constituent batch in get_breadth_series.
    """
    def _fetch():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            raw = yf.download(
                tickers,
                period=period,
                group_by="column",
                auto_adjust=True,
                threads=False,
                progress=False,
                session=_make_yf_session(),
            )
        if raw is None or raw.empty:
            raise ValueError(f"yfinance returned empty data for {tickers}")

        # Normalise to a flat DataFrame with ticker-name columns.
        # yfinance group_by="column": level-0 = metric, level-1 = ticker.
        # Older builds may swap the levels — handle both.
        if isinstance(raw.columns, pd.MultiIndex):
            lvl0 = raw.columns.get_level_values(0).unique().tolist()
            lvl1 = raw.columns.get_level_values(1).unique().tolist()
            if "Close" in lvl0:
                closes = raw["Close"]
            elif "Close" in lvl1:
                closes = raw.xs("Close", axis=1, level=1)
            else:
                raise ValueError(f"Cannot locate 'Close' in columns: {raw.columns.tolist()[:10]}")
            if isinstance(closes, pd.Series):
                closes = closes.to_frame(name=tickers[0])
        else:
            if "Close" in raw.columns:
                closes = raw[["Close"]].rename(columns={"Close": tickers[0]})
            else:
                closes = raw

        closes.index = pd.to_datetime(closes.index)
        if closes.index.tz is not None:
            closes.index = closes.index.tz_convert(None)
        return closes.dropna(how="all")

    return _retry(_fetch, retries=5, backoff=3.0, max_delay=30.0)




# ── S&P 500 universe ──────────────────────────────────────────────────────────

def get_sp500_universe() -> pd.DataFrame:
    """
    Returns a DataFrame with columns [Symbol, Security] for all S&P 500 members.
    Results are cached in data/sp500_universe.csv and refreshed weekly.
    """
    if _SP500_CACHE.exists():
        cached = pd.read_csv(_SP500_CACHE)
        cached_date = pd.to_datetime(cached["cached_at"].iloc[0], errors="coerce")
        age = (pd.Timestamp.now() - cached_date).days
        if age < _UNIVERSE_TTL_DAYS:
            logger.info("Using cached S&P 500 universe (%d tickers, %d days old)", len(cached), age)
            return cached

    def _fetch():
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        resp = requests.get(url, headers=_BROWSER_HEADERS, timeout=30)
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text), header=0, flavor="lxml")
        df = tables[0][["Symbol", "Security"]].copy()
        # Normalise tickers for yfinance (BRK.B → BRK-B)
        df["Symbol"] = df["Symbol"].str.replace(".", "-", regex=False)
        df["cached_at"] = pd.Timestamp.now().strftime("%Y-%m-%d")
        return df

    fresh = _retry(_fetch)

    if _SP500_CACHE.exists():
        old = pd.read_csv(_SP500_CACHE)
        added = sorted(set(fresh["Symbol"]) - set(old["Symbol"]))
        removed = sorted(set(old["Symbol"]) - set(fresh["Symbol"]))
        if added:
            logger.info("S&P 500 additions: %s", added)
        if removed:
            logger.info("S&P 500 removals: %s", removed)

    fresh.to_csv(_SP500_CACHE, index=False)
    logger.info("S&P 500 universe refreshed: %d constituents", len(fresh))
    return fresh


# ── Batched yfinance close downloader ────────────────────────────────────────

def _download_closes_batched(
    tickers: list,
    period: str = "1y",
    batch_size: int = 25,
) -> pd.DataFrame:
    """
    Download Close prices in batches of ~batch_size tickers with a 2-5 s
    random pause between batches to avoid GitHub-runner rate-limiting.
    Each batch retries up to 5× with exponential backoff capped at 30 s.
    """
    batches = [tickers[i:i + batch_size] for i in range(0, len(tickers), batch_size)]
    all_closes: list = []

    for idx, batch in enumerate(batches):
        logger.info(
            "Downloading batch %d/%d (%d tickers)...",
            idx + 1, len(batches), len(batch),
        )

        def _fetch_batch(b=batch):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                raw = yf.download(
                    b,
                    period=period,
                    group_by="column",
                    auto_adjust=True,
                    threads=False,
                    progress=False,
                    session=_make_yf_session(),
                )
            if raw is None or raw.empty:
                raise ValueError(f"Empty response for batch starting {b[:3]}")
            return raw

        panel = _retry(_fetch_batch, retries=5, backoff=3.0, max_delay=30.0)

        if isinstance(panel.columns, pd.MultiIndex):
            lvl0 = panel.columns.get_level_values(0).unique().tolist()
            lvl1 = panel.columns.get_level_values(1).unique().tolist()
            if "Close" in lvl0:
                closes = panel["Close"]
            elif "Close" in lvl1:
                closes = panel.xs("Close", axis=1, level=1)
            else:
                raise ValueError(f"Cannot locate 'Close' in batch {idx + 1} columns")
            if isinstance(closes, pd.Series):
                closes = closes.to_frame(name=batch[0])
        else:
            if "Close" in panel.columns:
                closes = panel[["Close"]].rename(columns={"Close": batch[0]})
            else:
                closes = panel

        all_closes.append(closes)

        if idx < len(batches) - 1:
            delay = random.uniform(2.0, 5.0)
            logger.debug("Batch %d done; pausing %.1fs", idx + 1, delay)
            time.sleep(delay)

    if not all_closes:
        raise ValueError("No batches returned Close data")

    combined = pd.concat(all_closes, axis=1)
    return combined.loc[:, ~combined.columns.duplicated()]


# ── S&P 500 breadth (seam) ────────────────────────────────────────────────────

def get_breadth_series() -> pd.DataFrame:
    """
    Compute daily NH/NL and advances/declines over the S&P 500 universe.

    Seam: to replace with Barchart ($MAHN/$MALN/$MAAD/$MADC), swap this
    function body while keeping the return schema:
        DataFrame indexed by date with integer columns: nh, nl, advances, declines

    Labeled "S&P 500 breadth" throughout the UI — not NYSE — to accurately
    reflect the proxy nature of this computation.
    """
    universe = get_sp500_universe()
    tickers = universe["Symbol"].tolist()
    logger.info(
        "Downloading 1y closes for %d S&P 500 constituents in batches of 25...",
        len(tickers),
    )

    closes = _download_closes_batched(tickers, period="1y", batch_size=25)

    closes.index = pd.to_datetime(closes.index)
    if closes.index.tz is not None:
        closes.index = closes.index.tz_localize(None)

    # Drop tickers with <70% coverage (delistings, late additions)
    min_obs = int(len(closes) * 0.70)
    closes = closes.dropna(axis=1, thresh=min_obs)
    logger.info("Breadth panel: %d tickers × %d days after coverage filter", closes.shape[1], len(closes))

    # Vectorised computation (no Python-level loops over rows)
    daily_chg = closes.diff()
    advances = (daily_chg > 0).sum(axis=1).astype(int)
    declines = (daily_chg < 0).sum(axis=1).astype(int)

    rolling_max = closes.rolling(252, min_periods=1).max()
    rolling_min = closes.rolling(252, min_periods=1).min()
    nh_ser = (closes >= rolling_max).sum(axis=1).astype(int)
    nl_ser = (closes <= rolling_min).sum(axis=1).astype(int)

    # Day 0 has no prior close — zero advances/declines there
    advances.iloc[0] = 0
    declines.iloc[0] = 0

    df = pd.DataFrame({
        "nh": nh_ser,
        "nl": nl_ser,
        "advances": advances,
        "declines": declines,
    })
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


# ── CNN Fear & Greed (benchmark only) ────────────────────────────────────────

def get_cnn_fear_greed() -> Optional[float]:
    """
    Fetch CNN's current Fear & Greed composite score.
    Returns float in [0, 100] or None — never a hard dependency.
    """
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    try:
        resp = requests.get(url, timeout=15, headers=_BROWSER_HEADERS)
        resp.raise_for_status()
        data = resp.json()
        score = float(data["fear_and_greed"]["score"])
        logger.info("CNN Fear & Greed score: %.1f", score)
        return score
    except Exception as exc:
        logger.warning("CNN Fear & Greed unavailable: %s", exc)
        return None


# ── Staleness check ───────────────────────────────────────────────────────────

def is_stale(series, name: str, max_bdays: int = 3) -> bool:
    """Return True if the most recent data point is older than max_bdays business days."""
    if series is None:
        return True
    try:
        last = pd.to_datetime(series.index[-1] if hasattr(series, "index") else series.name)
        today = pd.Timestamp.now().normalize()
        lag = len(pd.bdate_range(start=last + pd.Timedelta(days=1), end=today))
        if lag > max_bdays:
            logger.warning("Source '%s' is stale: last datapoint %s (%d bdays ago)", name, last.date(), lag)
            return True
    except Exception:
        pass
    return False
