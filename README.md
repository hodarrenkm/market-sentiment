# Market Sentiment & Breadth Dashboard

Automated US market sentiment dashboard. A GitHub Actions workflow runs every weekday morning
Singapore time (08:00 SGT / 00:00 UTC), computes a 7-component fear/greed composite plus S&P 500
breadth indicators, and publishes a static HTML dashboard via GitHub Pages.

No paid data, no API keys required.

## Live dashboard

Enable GitHub Pages on your repo: **Settings → Pages → Source: Deploy from a branch →
Branch: `main`, folder: `/docs`**.

The dashboard URL will be `https://<your-username>.github.io/<repo-name>/`.

---

## Setup

```bash
git clone https://github.com/<you>/market-sentiment.git
cd market-sentiment
pip install -r requirements.txt

# Run the full pipeline locally (backfills ~1 year of history on first run)
python -m src.pipeline
```

Open `docs/index.html` in a browser to verify the dashboard.

---

## Running the tests

```bash
pytest tests/ -v
```

---

## How it works

### Data sources

| # | Indicator | Source |
|---|-----------|--------|
| 1 | Market Momentum | `^GSPC` via yfinance — S&P 500 close vs 125-day MA |
| 2 | Volatility | `^VIX` via yfinance — VIX vs 50-day MA, inverted |
| 3 | Safe Haven Demand | SPY vs IEF via yfinance — 20-day total return differential |
| 4 | Junk Bond Demand | FRED `BAMLH0A0HYM2` — HY OAS, inverted |
| 5 | Put/Call Ratio | CBOE CDN — equity P/C ratio, inverted. **Null-safe**: if unavailable, the composite renormalizes over the remaining 6 components |
| 6 | New Highs / New Lows | Computed from S&P 500 constituent panel (proxy — see note below) |
| 7 | Stock Breadth | McClellan oscillator over same panel |
| — | CNN Fear & Greed | Stored as benchmark only — never a hard dependency |

### Scoring

Each sub-indicator is scored as the percentile rank of today's value within a
trailing 252-trading-day window (expanding window if fewer than 252 days are
available; minimum 60). Higher = more greedy. VIX, HY spread, and P/C ratio
are inverted before ranking.

Composite = equal-weighted mean of all available sub-scores.

**Bands:** 0–25 Extreme Fear · 25–45 Fear · 45–55 Neutral · 55–75 Greed · 75–100 Extreme Greed

---

## S&P 500 breadth — proxy caveat

True exchange-wide new-highs/new-lows and advance/decline data require a paid
data feed. This dashboard computes breadth over the **S&P 500 universe** (~503
members) as a documented proxy. All breadth indicators are labeled "S&P 500
breadth" in the UI to reflect this.

**Upgrade seam:** `src/fetch.py → get_breadth_series()` is the single function
to replace with a Barchart feed (`$MAHN`, `$MALN`, `$MAAD`, `$MADC`). The return
schema (DataFrame with columns `nh`, `nl`, `advances`, `declines` indexed by date)
must remain unchanged; no other file needs to change.

---

## Changing the schedule

Edit `.github/workflows/refresh.yml`:

```yaml
on:
  schedule:
    - cron: "0 0 * * 2-6"   # UTC — adjust as needed
```

Current schedule fires at 00:00 UTC Tuesday–Saturday, corresponding to 08:00 SGT
after each US trading day (Mon–Fri closes). Note: GitHub Actions cron can fire up
to ~15 minutes late during busy periods.

---

## Troubleshooting

- **Dashboard shows stale-source badge:** one data source returned data older than
  3 business days. The composite is still computed from the remaining live sources.
- **Put/Call card is greyed out:** CBOE CDN endpoints returned an error.
  The composite renormalizes over the remaining 6 sub-indicators automatically.
- **First run is slow:** the breadth computation downloads 1 year of OHLC for all
  ~503 S&P 500 members in a single batched yfinance call (~60–120 s).
