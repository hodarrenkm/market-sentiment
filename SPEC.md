# Build spec: Market sentiment & breadth dashboard (GitHub Actions, daily 8am SGT)

Paste everything below into Claude Code in an empty repo folder.

---

## Objective

Build a fully automated US market sentiment dashboard. A GitHub Actions workflow runs every weekday-after-US-close morning Singapore time, fetches free data sources, computes a 7-component fear/greed composite plus breadth indicators, appends to a versioned history file, regenerates a static HTML dashboard, and publishes it via GitHub Pages. No paid data, no API keys required, no server.

## Repo structure

```
.
├── .github/workflows/refresh.yml
├── src/
│   ├── fetch.py          # all data source fetchers
│   ├── indicators.py     # scoring + breadth math (pure functions, unit-tested)
│   ├── pipeline.py       # orchestrator: fetch -> compute -> append -> render
│   └── render.py         # writes docs/index.html from history + latest scores
├── data/
│   ├── history.csv       # one row per trading day, all raw series + scores
│   └── sp500_universe.csv  # cached constituent list with refresh date
├── docs/
│   └── index.html        # self-contained dashboard (GitHub Pages serves /docs)
├── tests/test_indicators.py
├── requirements.txt
└── README.md
```

## Data sources (all free — verify each endpoint works before building on it)

| # | Indicator | Source | Notes |
|---|-----------|--------|-------|
| 1 | Market momentum | `^GSPC` via yfinance | S&P 500 close vs 125-day MA |
| 2 | Volatility | `^VIX` via yfinance | VIX vs its 50-day MA, inverted |
| 3 | Safe haven demand | `SPY` vs `IEF` via yfinance | 20-day total return differential |
| 4 | Junk bond demand | FRED `BAMLH0A0HYM2` | HY OAS, no key needed: `https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2`, inverted |
| 5 | Put/call ratio | CBOE daily market statistics | Verify the current CSV/JSON endpoint under `cdn.cboe.com`; equities P/C ratio, inverted. If the endpoint is unavailable, mark this sub-indicator `null` and renormalize the composite — do not fail the run |
| 6 | New highs vs new lows | Computed from S&P 500 constituent panel | See breadth section below |
| 7 | Stock price breadth | Computed from same panel | McClellan oscillator on net advances |
| — | CNN Fear & Greed (benchmark only) | `https://production.dataviz.cnn.io/index/fearandgreed/graphdata` | Needs a browser User-Agent header. Store alongside our composite for comparison; never a hard dependency |

## Breadth computation (the important design decision)

True exchange-wide NH/NL and A/D need paid data. Instead, compute breadth over the **S&P 500 universe** as a documented proxy:

1. Scrape current constituents from the Wikipedia "List of S&P 500 companies" table; cache to `data/sp500_universe.csv` and refresh weekly (compare against cache, log additions/deletions).
2. Batch-download 1 year of daily OHLC for all ~503 tickers via `yfinance.download(tickers, period="1y", group_by="ticker", threads=True)` — one batched call, not 503 individual calls.
3. Per day: count members at 52-week closing highs / lows; count advancers / decliners vs prior close.
4. McClellan oscillator = EMA19 − EMA39 of (advancers − decliners). Also store the summation index (cumulative oscillator).
5. Cumulative A/D line = running sum of net advances.

Label everything in the UI as "S&P 500 breadth" — not NYSE. Leave a clearly marked seam in `fetch.py` (`get_breadth_series()`) so a Barchart feed ($MAHN/$MALN etc.) can be swapped in later without touching scoring code.

Historical backfill: because breadth is computed from the price panel, the first run can backfill ~1 year of breadth history retroactively. Do this once and commit it, so percentile ranks have a real distribution from day one.

## Scoring methodology

For each sub-indicator, score = percentile rank of today's value within the trailing 252 trading days (expanding window if <252 available, minimum 60). Orientation: higher = greed. Invert VIX, put/call, and HY spread. Specifically:

- momentum: pct-rank of (close / 125-DMA − 1)
- vix: 100 − pct-rank of (VIX / 50-DMA of VIX)
- safe haven: pct-rank of (SPY 20d return − IEF 20d return)
- junk: 100 − pct-rank of HY OAS level
- put/call: 100 − pct-rank of equity P/C ratio
- highs/lows: pct-rank of (NH − NL) / (NH + NL)
- breadth: pct-rank of McClellan oscillator value

Composite = equal-weighted mean of available sub-scores (renormalize if any are null that day). Bands: 0–25 extreme fear, 25–45 fear, 45–55 neutral, 55–75 greed, 75–100 extreme greed.

All of this lives in `indicators.py` as pure functions over pandas Series — no I/O — with unit tests covering: percentile rank edges, inversion, null-handling renormalization, McClellan EMA values against a hand-computed fixture.

## Pipeline behavior

- Idempotent: re-running on the same day overwrites that day's row, never duplicates.
- Each fetcher: 3 retries with exponential backoff; on final failure, log, set that series `null` for the day, continue.
- Staleness guard: if a source's latest datapoint is older than 3 trading days, flag it `stale` in the output JSON; the dashboard shows a warning badge.
- Skip logic: if the most recent US trading day is already in history (holiday Monday SGT, etc.), exit 0 with a log line — don't error.
- Never let one bad source fail the workflow: the run should always produce a dashboard, even if degraded.

## Dashboard (docs/index.html)

Single self-contained file, Chart.js from cdnjs, data embedded as a JSON blob at build time (no runtime API calls). Layout:

1. Semicircular gauge: composite score + band label + change vs 1 week ago.
2. Grid of 7 sub-indicator cards: score /100, colored progress bar, raw value line (e.g. "VIX 16.4", "184 highs / 92 lows").
3. Tabbed time-series chart: NH−NL daily bars · cumulative A/D line · McClellan oscillator · composite history (with our composite vs CNN's overlaid when available).
4. Footer: "Data as of {date} US close · refreshed {timestamp} SGT · S&P 500 universe breadth" + stale-source badges.

Dark-mode aware via `prefers-color-scheme`. Mobile-usable (the primary viewer checks it on a phone at breakfast).

## GitHub Actions workflow

```yaml
name: refresh-dashboard
on:
  schedule:
    - cron: "0 0 * * 2-6"   # 00:00 UTC = 08:00 SGT, Tue–Sat (captures Mon–Fri US closes)
  workflow_dispatch:          # manual trigger for testing
permissions:
  contents: write
```

Steps: checkout → setup Python 3.11 with pip cache → `pip install -r requirements.txt` → `python -m src.pipeline` → commit `data/` + `docs/` with message `data: refresh YYYY-MM-DD [skip ci]` (only if changed) → push. Add `concurrency: { group: refresh, cancel-in-progress: false }`.

Also note in README: Actions cron can fire up to ~15 min late at busy times; this is fine for our use case.

## Requirements

`yfinance`, `pandas`, `requests`, `lxml` (Wikipedia table), `pytest`. Pin versions.

## Acceptance criteria

1. `pytest` passes.
2. `python -m src.pipeline` run locally produces `data/history.csv` with ≥250 rows of backfilled breadth/score history and a rendered `docs/index.html` that opens correctly in a browser.
3. `workflow_dispatch` run on GitHub succeeds end-to-end and commits.
4. Simulated failure of the CBOE fetch (force an exception) still yields a dashboard with the put/call card greyed out and composite renormalized over 6 components.
5. README documents: setup (enable Pages on main:/docs), the breadth-proxy caveat, the Barchart upgrade seam, and how to change the schedule.

Build it step by step: scaffolding + tests for `indicators.py` first, then fetchers (verify each live endpoint as you go), then pipeline + render, then the workflow. Ask me before adding any paid dependency or API key requirement.
