"""
Generate docs/index.html from the history DataFrame.
All data is embedded as a JSON blob — no runtime API calls.
"""
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from src.indicators import band_color, band_label

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent
DOCS_DIR = _ROOT / "docs"
DOCS_DIR.mkdir(exist_ok=True)
OUTPUT = DOCS_DIR / "index.html"

_SUB_LABELS = {
    "momentum":   "Market Momentum",
    "vix":        "Volatility (VIX)",
    "safe_haven": "Safe Haven Demand",
    "junk":       "Junk Bond Demand",
    "nh_nl":      "New Highs / New Lows",
    "breadth":    "Stock Breadth (McClellan)",
}

_RAW_COL = {
    "momentum":   ("gspc_close", "S&P 500 close", ".0f"),
    "vix":        ("vix_close",  "VIX",           ".1f"),
    "safe_haven": ("spy_close",  "SPY price",     ".2f"),
    "junk":       ("hy_oas",     "HY OAS",        ".2f"),
    "nh_nl":      (None,         "",              ""),
    "breadth":    ("mclellan_osc", "McClellan",   ".1f"),
}


def _safe_float(v) -> float | None:
    """Convert to Python float, returning None for NaN/inf."""
    try:
        f = float(v)
        if np.isfinite(f):
            return round(f, 4)
        return None
    except (TypeError, ValueError):
        return None


def _series_to_list(s: pd.Series, decimals: int = 2) -> list:
    return [_safe_float(v) for v in s]


def build(history: pd.DataFrame, stale_sources: list | None = None) -> None:
    stale_sources = stale_sources or []
    if history.empty:
        logger.error("No history data — cannot render dashboard")
        return

    # Work with the last 504 rows for charts (≈2 years), full history for scores
    chart_df = history.tail(504).copy()
    latest = history.iloc[-1]
    latest_date = history.index[-1]

    composite_val = _safe_float(latest.get("composite"))
    if composite_val is None:
        composite_val = 50.0

    # Weekly change: composite 5 rows ago
    composite_prev = None
    if len(history) >= 6:
        composite_prev = _safe_float(history["composite"].iloc[-6])
    weekly_change = None
    if composite_val is not None and composite_prev is not None:
        weekly_change = round(composite_val - composite_prev, 1)

    # Sub-indicator cards
    cards = []
    for key, label in _SUB_LABELS.items():
        score_col = f"score_{key}"
        score_val = _safe_float(latest.get(score_col))

        raw_info = _RAW_COL.get(key, (None, "", ""))
        raw_col, raw_label, raw_fmt = raw_info
        raw_val = None
        raw_str = ""
        if raw_col and raw_col in latest.index:
            raw_val = _safe_float(latest[raw_col])
            if raw_val is not None and raw_fmt:
                raw_str = f"{raw_label} {raw_val:{raw_fmt}}"

        # NH/NL special case
        if key == "nh_nl":
            nh = _safe_float(latest.get("nh"))
            nl = _safe_float(latest.get("nl"))
            if nh is not None and nl is not None:
                raw_str = f"{int(nh)} highs / {int(nl)} lows"

        cards.append({
            "key":    key,
            "label":  label,
            "score":  score_val,
            "raw":    raw_str,
            "color":  band_color(score_val) if score_val is not None else "#888",
            "null":   score_val is None,
        })

    # Time-series chart data
    dates_list = [d.strftime("%Y-%m-%d") for d in chart_df.index]

    def _col(name):
        if name in chart_df.columns:
            return _series_to_list(chart_df[name])
        return [None] * len(chart_df)

    chart_data = {
        "dates":        dates_list,
        "composite":    _col("composite"),
        "cnn":          _col("cnn_score"),
        "nh_nl_bar":    _col("nh") if "nh" in chart_df else [None]*len(chart_df),
        "nl_bar":       _col("nl") if "nl" in chart_df else [None]*len(chart_df),
        "ad_line":      _col("ad_line"),
        "mclellan":     _col("mclellan_osc"),
    }
    # nh−nl net bar
    if "nh" in chart_df.columns and "nl" in chart_df.columns:
        chart_data["nh_nl_net"] = _series_to_list(chart_df["nh"] - chart_df["nl"])
    else:
        chart_data["nh_nl_net"] = [None] * len(chart_df)

    payload = {
        "date":          latest_date.strftime("%Y-%m-%d"),
        "composite":     composite_val,
        "band":          band_label(composite_val),
        "band_color":    band_color(composite_val),
        "weekly_change": weekly_change,
        "cards":         cards,
        "chart":         chart_data,
        "stale":         stale_sources,
        "history_rows":  len(history),
    }

    html = _render_html(payload)
    OUTPUT.write_text(html, encoding="utf-8")
    logger.info("Dashboard written → %s", OUTPUT)


# ── HTML template ─────────────────────────────────────────────────────────────

def _render_html(p: dict) -> str:
    data_json = json.dumps(p, separators=(",", ":"))
    band = p["band"]
    color = p["band_color"]
    score = p["composite"]
    date_str = p["date"]
    change_str = ""
    if p["weekly_change"] is not None:
        sign = "+" if p["weekly_change"] >= 0 else ""
        change_str = f"{sign}{p['weekly_change']:.1f} vs 1 week ago"

    cards_html = ""
    for c in p["cards"]:
        null_cls = " null-card" if c["null"] else ""
        score_display = f"{c['score']:.0f}" if c["score"] is not None else "—"
        raw_display = c["raw"] or ""
        bar_pct = c["score"] if c["score"] is not None else 0
        cards_html += f"""
        <div class="card{null_cls}">
          <div class="card-label">{c['label']}</div>
          <div class="card-score" style="color:{c['color']}">{score_display}<span class="card-denom">/100</span></div>
          <div class="bar-track"><div class="bar-fill" style="width:{bar_pct:.0f}%;background:{c['color']}"></div></div>
          <div class="card-raw">{raw_display}</div>
        </div>"""

    stale_html = ""
    for s in p["stale"]:
        stale_html += f'<span class="stale-badge">⚠ {s} stale</span>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Market Sentiment Dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"
        integrity="sha512-ZwR1/gSZM3ai6vCdI+LVF1zSq/5HznD3oD+sCoJrzXJ+yKen9RtQ1/IHpHMcNcIGVHjbrBORdEBjP7t07X3tA=="
        crossorigin="anonymous" referrerpolicy="no-referrer"></script>
<style>
:root {{
  --bg: #0f1117; --surface: #1a1d27; --border: #2a2d3e;
  --text: #e2e8f0; --muted: #8892a4;
  --fear: #e63946; --greed: #2a9d8f;
}}
@media (prefers-color-scheme: light) {{
  :root {{
    --bg: #f8fafc; --surface: #fff; --border: #e2e8f0;
    --text: #0f172a; --muted: #64748b;
  }}
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: var(--bg); color: var(--text); font-family: system-ui, sans-serif; padding: 1rem; }}
h1 {{ text-align: center; font-size: 1.4rem; color: var(--muted); margin-bottom: 1.5rem; font-weight: 400; }}

/* Gauge */
.gauge-wrap {{ display: flex; flex-direction: column; align-items: center; margin-bottom: 2rem; }}
.gauge-canvas {{ max-width: 360px; width: 100%; }}
.gauge-score {{ font-size: 3rem; font-weight: 700; color: {color}; margin-top: -2.5rem; }}
.gauge-band  {{ font-size: 1.2rem; color: {color}; font-weight: 600; margin-top: 0.25rem; }}
.gauge-change {{ font-size: 0.85rem; color: var(--muted); margin-top: 0.25rem; }}

/* Cards */
.cards-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 0.75rem;
  margin-bottom: 2rem;
}}
.card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 0.85rem; }}
.card.null-card {{ opacity: 0.45; }}
.card-label {{ font-size: 0.7rem; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; margin-bottom: 0.4rem; }}
.card-score {{ font-size: 1.8rem; font-weight: 700; line-height: 1; }}
.card-denom {{ font-size: 0.85rem; font-weight: 400; color: var(--muted); }}
.bar-track {{ height: 5px; background: var(--border); border-radius: 3px; margin: 0.5rem 0; }}
.bar-fill  {{ height: 100%; border-radius: 3px; transition: width .4s; }}
.card-raw  {{ font-size: 0.72rem; color: var(--muted); }}

/* Tabs */
.tabs {{ display: flex; gap: 0.4rem; margin-bottom: 0.75rem; flex-wrap: wrap; }}
.tab-btn {{
  padding: 0.35rem 0.8rem; border-radius: 6px; border: 1px solid var(--border);
  background: var(--surface); color: var(--muted); cursor: pointer; font-size: 0.8rem;
}}
.tab-btn.active {{ background: var(--border); color: var(--text); }}
.chart-panel {{ display: none; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 1rem; }}
.chart-panel.active {{ display: block; }}

/* Footer */
footer {{
  margin-top: 1.5rem; font-size: 0.72rem; color: var(--muted);
  text-align: center; border-top: 1px solid var(--border); padding-top: 0.75rem;
  display: flex; flex-wrap: wrap; justify-content: center; gap: 0.5rem;
}}
.stale-badge {{
  background: #7c3f00; color: #ffb347; padding: 0.15rem 0.5rem;
  border-radius: 4px; font-size: 0.7rem;
}}
</style>
</head>
<body>
<h1>US Market Sentiment &amp; Breadth</h1>

<div class="gauge-wrap">
  <canvas id="gaugeChart" class="gauge-canvas" height="200"></canvas>
  <div class="gauge-score">{score:.0f}</div>
  <div class="gauge-band">{band}</div>
  <div class="gauge-change">{change_str}</div>
</div>

<div class="cards-grid">{cards_html}</div>

<div class="tabs">
  <button class="tab-btn active" onclick="showTab('composite')">Composite History</button>
  <button class="tab-btn" onclick="showTab('nhNl')">NH−NL</button>
  <button class="tab-btn" onclick="showTab('adLine')">Cumulative A/D</button>
  <button class="tab-btn" onclick="showTab('mclellan')">McClellan Osc.</button>
</div>
<div id="tab-composite" class="chart-panel active"><canvas id="compositeChart"></canvas></div>
<div id="tab-nhNl"      class="chart-panel"><canvas id="nhNlChart"></canvas></div>
<div id="tab-adLine"    class="chart-panel"><canvas id="adLineChart"></canvas></div>
<div id="tab-mclellan"  class="chart-panel"><canvas id="mclellanChart"></canvas></div>

<footer>
  <span>Data as of {date_str} US close</span>
  <span>S&amp;P 500 universe breadth (proxy — not NYSE)</span>
  {stale_html}
</footer>

<script>
const DATA = {data_json};
const DATES = DATA.chart.dates;

function showTab(id) {{
  document.querySelectorAll('.chart-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + id).classList.add('active');
  event.target.classList.add('active');
}}

const isDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
const gridColor = isDark ? 'rgba(255,255,255,0.07)' : 'rgba(0,0,0,0.07)';
const textColor = isDark ? '#8892a4' : '#64748b';

Chart.defaults.color = textColor;
Chart.defaults.borderColor = gridColor;

// ── Gauge (semicircle doughnut) ──
const gaugeCtx = document.getElementById('gaugeChart').getContext('2d');
const score = DATA.composite;
const BANDS = [25,20,10,20,25]; // extreme-fear, fear, neutral, greed, extreme-greed widths
const BAND_COLORS = ['#e63946','#f4a261','#e9c46a','#2a9d8f','#264653'];
const needle = score / 100; // 0–1

new Chart(gaugeCtx, {{
  type: 'doughnut',
  data: {{
    datasets: [{{
      data: BANDS,                 // 5 equal-weight bands, sum=100
      backgroundColor: BAND_COLORS,
      borderWidth: 0,
    }}]
  }},
  options: {{
    responsive: true,
    cutout: '70%',
    circumference: 180,          // render only top semicircle
    rotation: -90,               // start from 9-o'clock (left = extreme fear)
    plugins: {{ legend: {{ display: false }}, tooltip: {{ enabled: false }} }},
    animation: false,
  }},
  plugins: [{{
    id: 'needle',
    afterDraw(chart) {{
      const {{ ctx }} = chart;
      const meta = chart.getDatasetMeta(0);
      if (!meta.data || meta.data.length === 0) return;
      const arc = meta.data[0];
      const cx = arc.x;
      const cy = arc.y;
      const r  = (arc.outerRadius + arc.innerRadius) / 2;
      // angle: π (left) → 3π/2 (top) → 2π (right) as needle goes 0→1
      const angle = Math.PI + needle * Math.PI;
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(cx + r * Math.cos(angle), cy + r * Math.sin(angle));
      ctx.strokeStyle = isDark ? '#e2e8f0' : '#0f172a';
      ctx.lineWidth = 2.5;
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(cx, cy, 6, 0, 2 * Math.PI);
      ctx.fillStyle = isDark ? '#e2e8f0' : '#0f172a';
      ctx.fill();
      ctx.restore();
    }}
  }}]
}});

function mkLine(canvasId, datasets, yLabel) {{
  const ctx = document.getElementById(canvasId).getContext('2d');
  new Chart(ctx, {{
    type: 'line',
    data: {{ labels: DATES, datasets }},
    options: {{
      responsive: true,
      animation: false,
      parsing: false,
      spanGaps: true,
      plugins: {{ legend: {{ position: 'top', labels: {{ boxWidth: 12 }} }} }},
      scales: {{
        x: {{
          type: 'category',
          ticks: {{ maxTicksLimit: 8, maxRotation: 0 }},
        }},
        y: {{ title: {{ display: !!yLabel, text: yLabel }} }},
      }},
    }},
  }});
}}

function mkBar(canvasId, datasets, yLabel) {{
  const ctx = document.getElementById(canvasId).getContext('2d');
  new Chart(ctx, {{
    type: 'bar',
    data: {{ labels: DATES, datasets }},
    options: {{
      responsive: true,
      animation: false,
      plugins: {{ legend: {{ position: 'top', labels: {{ boxWidth: 12 }} }} }},
      scales: {{
        x: {{ ticks: {{ maxTicksLimit: 8, maxRotation: 0 }} }},
        y: {{ title: {{ display: !!yLabel, text: yLabel }} }},
      }},
    }},
  }});
}}

// Composite history
const hasCnn = DATA.chart.cnn && DATA.chart.cnn.some(v => v !== null);
const compositeDS = [{{
  label: 'Our Composite',
  data: DATA.chart.composite,
  borderColor: '#7c3aed',
  backgroundColor: 'rgba(124,58,237,0.1)',
  borderWidth: 2,
  pointRadius: 0,
  fill: true,
}}];
if (hasCnn) compositeDS.push({{
  label: 'CNN Fear & Greed',
  data: DATA.chart.cnn,
  borderColor: '#f97316',
  borderWidth: 1.5,
  pointRadius: 0,
  borderDash: [4, 4],
}});
mkLine('compositeChart', compositeDS, 'Score (0–100)');

// NH−NL bars (color by positive/negative)
const nhNlColors = (DATA.chart.nh_nl_net || []).map(v => (v !== null && v >= 0) ? '#2a9d8f' : '#e63946');
mkBar('nhNlChart', [{{
  label: 'New Highs − New Lows (S&P 500 proxy)',
  data: DATA.chart.nh_nl_net,
  backgroundColor: nhNlColors,
  borderWidth: 0,
}}], 'Net NH−NL');

// Cumulative A/D line
mkLine('adLineChart', [{{
  label: 'Cumulative A/D Line (S&P 500 proxy)',
  data: DATA.chart.ad_line,
  borderColor: '#3b82f6',
  borderWidth: 2,
  pointRadius: 0,
}}], 'Cumulative');

// McClellan oscillator
const oscColors = (DATA.chart.mclellan || []).map(v => (v !== null && v >= 0) ? '#2a9d8f' : '#e63946');
mkBar('mclellanChart', [{{
  label: 'McClellan Oscillator (S&P 500 proxy)',
  data: DATA.chart.mclellan,
  backgroundColor: oscColors,
  borderWidth: 0,
}}], 'Oscillator');
</script>
</body>
</html>"""
