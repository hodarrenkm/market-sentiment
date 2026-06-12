"""
Generate docs/index.html from the history DataFrame.
All data is embedded as a JSON blob — no runtime API calls.
Static HTML renders scores without JavaScript; JS adds the date slider,
gauge needle, and charts as progressive enhancement.
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
    "junk":       "Credit Demand (HYG/LQD)",
    "nh_nl":      "New Highs / New Lows",
    "breadth":    "Stock Breadth (McClellan)",
}

_RAW_COL = {
    "momentum":   ("gspc_close", "S&P 500 close", ".0f"),
    "vix":        ("vix_close",  "VIX",           ".1f"),
    "safe_haven": ("spy_close",  "SPY price",     ".2f"),
    "junk":       ("hyg_close",  "HYG",           ".2f"),
    "nh_nl":      (None,         "",              ""),
    "breadth":    ("mclellan_osc", "McClellan",   ".1f"),
}


def _f(v, decimals: int = 2):
    try:
        f = float(v)
        if np.isfinite(f):
            r = round(f, decimals)
            return int(r) if decimals == 0 else r
        return None
    except (TypeError, ValueError):
        return None


def _col(df: pd.DataFrame, name: str, decimals: int = 2) -> list:
    if name in df.columns:
        return [_f(v, decimals) for v in df[name]]
    return [None] * len(df)


def build(history: pd.DataFrame, stale_sources: list | None = None) -> None:
    stale_sources = stale_sources or []
    if history.empty:
        logger.error("No history data — cannot render dashboard")
        return

    dates = [d.strftime("%Y-%m-%d") for d in history.index]
    n = len(dates)

    scores = {k: _col(history, f"score_{k}", 1) for k in _SUB_LABELS}
    scores["composite"] = _col(history, "composite", 1)
    scores["cnn"]       = _col(history, "cnn_score", 1)

    raws = {
        "gspc_close":   _col(history, "gspc_close",   0),
        "vix_close":    _col(history, "vix_close",    2),
        "spy_close":    _col(history, "spy_close",    2),
        "hyg_close":    _col(history, "hyg_close",    2),
        "nh":           _col(history, "nh",           0),
        "nl":           _col(history, "nl",           0),
        "mclellan_osc": _col(history, "mclellan_osc", 1),
        "ad_line":      _col(history, "ad_line",      0),
    }
    if "nh" in history.columns and "nl" in history.columns:
        raws["nh_nl_net"] = [
            _f(a - b, 0) if a is not None and b is not None else None
            for a, b in zip(raws["nh"], raws["nl"])
        ]
    else:
        raws["nh_nl_net"] = [None] * n

    comp = scores["composite"]
    weekly = [
        round(comp[i] - comp[i - 5], 1)
        if i >= 5 and comp[i] is not None and comp[i - 5] is not None
        else None
        for i in range(n)
    ]

    # ── Static values for initial HTML render ──────────────────────────────────
    latest_idx    = n - 1
    composite_val = comp[latest_idx] or 50.0
    gauge_color   = band_color(composite_val)
    gauge_band    = band_label(composite_val)
    gauge_score   = str(round(composite_val))
    date_str      = dates[latest_idx]
    # Short date format e.g. "11 Jun"
    _months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    _dp = date_str.split("-")
    date_short = f"{int(_dp[2])} {_months[int(_dp[1])-1]}"
    wc = weekly[latest_idx]
    change_str = (("+" if wc >= 0 else "") + f"{wc:.1f} vs 1 week ago") if wc is not None else ""

    # ── Static cards HTML ──────────────────────────────────────────────────────
    cards_html = ""
    for key, label in _SUB_LABELS.items():
        sv = scores[key][latest_idx]
        col = band_color(sv) if sv is not None else "#9ca3af"
        score_disp = str(round(sv)) if sv is not None else "—"
        bar_pct    = sv if sv is not None else 0
        null_cls   = " null-card" if sv is None else ""

        raw_str = ""
        raw_col, raw_label, raw_fmt = _RAW_COL.get(key, (None, "", ""))
        if raw_col and raws.get(raw_col) and raws[raw_col][latest_idx] is not None:
            v = raws[raw_col][latest_idx]
            if raw_fmt == ".0f":
                raw_str = f"{raw_label} {int(v)}"
            elif raw_fmt == ".1f":
                raw_str = f"{raw_label} {float(v):.1f}"
            elif raw_fmt == ".2f":
                raw_str = f"{raw_label} {float(v):.2f}"
        if key == "nh_nl":
            nh = raws["nh"][latest_idx]
            nl = raws["nl"][latest_idx]
            if nh is not None and nl is not None:
                raw_str = f"{int(nh)} highs / {int(nl)} lows"

        cards_html += (
            f'\n  <div class="card{null_cls}" data-key="{key}">'
            f'\n    <div class="card-label">{label}</div>'
            f'\n    <div class="card-score-row">'
            f'<span class="score-val" style="color:{col}">{score_disp}</span>'
            f'</div>'
            f'\n    <div class="bar-track">'
            f'<div class="bar-fill" style="width:{bar_pct:.1f}%;background:{col}"></div></div>'
            f'\n    <div class="card-raw">{raw_str}</div>'
            f'\n  </div>'
        )

    stale_html = "".join(
        f'<span class="stale-badge">⚠ {s} stale</span>' for s in stale_sources
    )

    payload = {
        "dates":  dates,
        "scores": scores,
        "raws":   raws,
        "weekly": weekly,
        "stale":  stale_sources,
        "n":      n,
    }

    html = _HTML_TEMPLATE
    for key, val in {
        "__DATA_JSON__":    json.dumps(payload, separators=(",", ":")),
        "__CARDS_HTML__":   cards_html,
        "__GAUGE_SCORE__":  gauge_score,
        "__GAUGE_BAND__":   gauge_band,
        "__GAUGE_COLOR__":  gauge_color,
        "__GAUGE_CHANGE__": change_str,
        "__DATE_STR__":     date_str,
        "__DATE_SHORT__":   date_short,
        "__STALE_HTML__":   stale_html,
    }.items():
        html = html.replace(key, val)

    OUTPUT.write_text(html, encoding="utf-8")
    logger.info("Dashboard written → %s", OUTPUT)


# ── HTML template ──────────────────────────────────────────────────────────────

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Market Sentiment Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/hammerjs@2.0.8/hammer.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js"></script>
<style>
:root {
  --bg: #f7f8fa;
  --surface: #ffffff;
  --border: #e5e7eb;
  --text: #111827;
  --muted: #6b7280;
  --accent: #6d28d9;
  --tab-active-bg: #111827;
  --tab-active-text: #ffffff;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f1117;
    --surface: #1a1d27;
    --border: #2a2d3e;
    --text: #e2e8f0;
    --muted: #8892a4;
    --accent: #7c3aed;
    --tab-active-bg: #e2e8f0;
    --tab-active-text: #111827;
  }
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg); color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  padding: 1.25rem; max-width: 960px; margin: 0 auto; font-size: 14px;
}

/* ── Hero: gauge + composite info ── */
.hero {
  display: flex; align-items: center; gap: 1.5rem;
  margin-bottom: 1rem;
}
.gauge-wrap { flex-shrink: 0; width: 220px; }
.gauge-canvas { width: 100%; display: block; }
.composite-info { flex: 1; }
.composite-label { font-size: 0.78rem; color: var(--muted); margin-bottom: 0.3rem; letter-spacing: 0.01em; }
.composite-score-row { display: flex; align-items: baseline; gap: 0.15rem; line-height: 1; margin-bottom: 0.2rem; }
.composite-num { font-size: 2.8rem; font-weight: 700; color: var(--text); }
.composite-denom { font-size: 1.1rem; color: var(--muted); font-weight: 400; }
.composite-band { font-size: 0.95rem; font-weight: 600; margin-bottom: 0.2rem; }
.composite-change { font-size: 0.78rem; color: var(--muted); }

/* ── Slider ── */
.slider-row {
  display: flex; align-items: center; gap: 0.6rem;
  margin-bottom: 1.25rem; padding: 0.5rem 0;
  border-top: 1px solid var(--border); border-bottom: 1px solid var(--border);
}
.slider-label { font-size: 0.78rem; color: var(--muted); white-space: nowrap; }
#date-slider { flex: 1; accent-color: var(--accent); cursor: pointer; }
.slider-date { font-size: 0.85rem; font-weight: 600; white-space: nowrap; min-width: 48px; text-align: right; }

/* ── Cards ── */
.cards-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.65rem;
  margin-bottom: 1.5rem;
}
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.85rem 1rem;
  transition: opacity 0.2s;
}
.card.null-card { opacity: 0.45; }
.card-label {
  font-size: 0.7rem; color: var(--muted);
  margin-bottom: 0.35rem; font-weight: 400;
}
.card-score-row { margin-bottom: 0.45rem; line-height: 1; }
.score-val { font-size: 2rem; font-weight: 700; }
.bar-track { height: 3px; background: var(--border); border-radius: 2px; margin-bottom: 0.45rem; }
.bar-fill { height: 100%; border-radius: 2px; transition: width 0.3s, background 0.3s; }
.card-raw { font-size: 0.68rem; color: var(--muted); }

/* ── Chart tabs ── */
.tab-area { margin-bottom: 0.75rem; }
.tab-row { display: flex; gap: 0.35rem; flex-wrap: wrap; align-items: center; margin-bottom: 0.4rem; }
.reset-zoom-btn {
  margin-left: auto; padding: 0.25rem 0.7rem;
  border: 1px solid var(--border); border-radius: 20px;
  background: var(--surface); color: var(--muted);
  cursor: pointer; font-size: 0.72rem; font-family: inherit;
  display: none;
}
.reset-zoom-btn.visible { display: inline-block; }
.tab-btn {
  padding: 0.35rem 0.85rem;
  border: 1px solid var(--border);
  border-radius: 20px;
  background: var(--surface);
  color: var(--muted);
  cursor: pointer;
  font-size: 0.78rem;
  font-family: inherit;
  transition: all 0.15s;
}
.tab-btn:hover { color: var(--text); border-color: #9ca3af; }
.tab-btn.active {
  background: var(--tab-active-bg);
  color: var(--tab-active-text);
  border-color: var(--tab-active-bg);
}
.chart-panel { display: none; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; }
.chart-panel.active { display: block; }

/* ── Footer ── */
footer {
  margin-top: 1.25rem; font-size: 0.68rem; color: var(--muted);
  text-align: center; border-top: 1px solid var(--border); padding-top: 0.6rem;
  display: flex; flex-wrap: wrap; justify-content: center; gap: 0.5rem;
}
.stale-badge { background: #7c3f00; color: #ffb347; padding: 0.1rem 0.4rem; border-radius: 4px; }

@media (max-width: 540px) {
  .hero { flex-direction: column; align-items: flex-start; gap: 0.5rem; }
  .gauge-wrap { width: 200px; }
  .cards-grid { grid-template-columns: repeat(2, 1fr); }
  .composite-num { font-size: 2.2rem; }
}
</style>
</head>
<body>

<div class="hero">
  <div class="gauge-wrap">
    <canvas id="gaugeChart" class="gauge-canvas"></canvas>
  </div>
  <div class="composite-info">
    <div class="composite-label">Composite sentiment</div>
    <div class="composite-score-row">
      <span id="gauge-score" class="composite-num" style="color:__GAUGE_COLOR__">__GAUGE_SCORE__</span>
      <span class="composite-denom">/100</span>
    </div>
    <div id="gauge-band" class="composite-band" style="color:__GAUGE_COLOR__">__GAUGE_BAND__</div>
    <div id="gauge-change" class="composite-change">__GAUGE_CHANGE__</div>
  </div>
</div>

<div class="slider-row" id="slider-section" style="display:none">
  <span class="slider-label">As of</span>
  <input type="range" id="date-slider" min="0" max="1" value="1">
  <span id="as-of-label" class="slider-date">__DATE_SHORT__</span>
</div>

<div class="cards-grid">__CARDS_HTML__
</div>

<div class="tab-area">
  <div class="tab-row">
    <button class="tab-btn active" onclick="showTab('composite',this)">Composite</button>
    <button class="tab-btn" onclick="showTab('momentum',this)">Momentum</button>
    <button class="tab-btn" onclick="showTab('vix',this)">Volatility</button>
    <button class="tab-btn" onclick="showTab('safe_haven',this)">Safe Haven</button>
    <button class="tab-btn" onclick="showTab('junk',this)">Credit</button>
    <button class="tab-btn" onclick="showTab('nh_nl',this)">New Highs−Lows</button>
    <button class="tab-btn" onclick="showTab('ad_line',this)">A/D Line</button>
    <button class="tab-btn" onclick="showTab('mclellan',this)">McClellan</button>
    <button class="reset-zoom-btn" id="reset-zoom-btn" onclick="resetActiveZoom()">Reset zoom</button>
  </div>
</div>
<div id="tab-composite"  class="chart-panel active"><canvas id="compositeChart"></canvas></div>
<div id="tab-momentum"   class="chart-panel"><canvas id="momentumChart"></canvas></div>
<div id="tab-vix"        class="chart-panel"><canvas id="vixChart"></canvas></div>
<div id="tab-safe_haven" class="chart-panel"><canvas id="safeHavenChart"></canvas></div>
<div id="tab-junk"       class="chart-panel"><canvas id="junkChart"></canvas></div>
<div id="tab-nh_nl"      class="chart-panel"><canvas id="nhNlChart"></canvas></div>
<div id="tab-ad_line"    class="chart-panel"><canvas id="adLineChart"></canvas></div>
<div id="tab-mclellan"   class="chart-panel"><canvas id="mclellanChart"></canvas></div>

<footer id="footer-bar">
  <span>S&amp;P 500 breadth: proxy computed from constituents (not NYSE)</span>
  __STALE_HTML__
</footer>

<script>
const D = __DATA_JSON__;
const DATES = D.dates;

// ── Colour helpers ────────────────────────────────────────────────────────────
function bandColor(s) {
  if (s == null) return '#9ca3af';
  if (s < 25)   return '#dc2626';
  if (s < 45)   return '#f97316';
  if (s < 55)   return '#9ca3af';
  if (s < 75)   return '#16a34a';
  return '#15803d';
}
function bandLabel(s) {
  if (s == null) return '—';
  if (s < 25)   return 'Extreme Fear';
  if (s < 45)   return 'Fear';
  if (s < 55)   return 'Neutral';
  if (s < 75)   return 'Greed';
  return 'Extreme Greed';
}
function fmtDate(iso) {
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const p = iso.split('-');
  return parseInt(p[2]) + ' ' + months[parseInt(p[1]) - 1];
}

const isDark = window.matchMedia('(prefers-color-scheme: dark)').matches;

// ── Chart.js global plugins ───────────────────────────────────────────────────
const needlePlugin = {
  id: 'needle',
  afterDraw(chart) {
    if (chart.config.type !== 'doughnut') return;
    const pos = chart._needle != null ? chart._needle : 0.5;
    const { ctx } = chart;
    const meta = chart.getDatasetMeta(0);
    if (!meta.data || !meta.data.length) return;
    const arc = meta.data[0];
    const cx = arc.x, cy = arc.y;
    const rOuter = arc.outerRadius, rInner = arc.innerRadius;
    const angle = Math.PI * (1 + pos);
    const col = isDark ? '#e2e8f0' : '#111827';
    ctx.save();
    // Needle line from center to arc midpoint
    const rMid = (rOuter + rInner) / 2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + rMid * Math.cos(angle), cy + rMid * Math.sin(angle));
    ctx.strokeStyle = col; ctx.lineWidth = 2.5;
    ctx.lineCap = 'round'; ctx.stroke();
    // Center dot
    ctx.beginPath();
    ctx.arc(cx, cy, 5, 0, 2 * Math.PI);
    ctx.fillStyle = col; ctx.fill();
    ctx.restore();
  }
};

const vLinePlugin = {
  id: 'vLine',
  afterDraw(chart) {
    if (chart.config.type === 'doughnut') return;
    const idx = chart._vLineIdx;
    if (idx == null) return;
    const { ctx, chartArea, scales } = chart;
    if (!chartArea || !scales.x) return;
    // Use getPixelForIndex if available, else fall back
    let x;
    try { x = scales.x.getPixelForValue(DATES[idx]); } catch(e) { return; }
    if (isNaN(x) || x < chartArea.left || x > chartArea.right) return;
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(x, chartArea.top);
    ctx.lineTo(x, chartArea.bottom);
    ctx.strokeStyle = isDark ? 'rgba(255,210,40,0.75)' : 'rgba(120,80,0,0.6)';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([5, 3]);
    ctx.stroke();
    ctx.restore();
  }
};

try {
  Chart.defaults.color       = isDark ? '#8892a4' : '#6b7280';
  Chart.defaults.borderColor = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)';
  Chart.register(needlePlugin, vLinePlugin);
} catch(e) { console.warn('Chart.js init failed:', e.message); }

// ── Gauge ─────────────────────────────────────────────────────────────────────
let gaugeChart = null;
try {
  gaugeChart = new Chart(document.getElementById('gaugeChart').getContext('2d'), {
    type: 'doughnut',
    data: {
      datasets: [{
        data: [25, 20, 10, 20, 25],
        backgroundColor: ['#dc2626','#f97316','#d1d5db','#16a34a','#15803d'],
        borderWidth: 0,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: true, aspectRatio: 2,
      cutout: '65%', circumference: 180, rotation: -90, animation: false,
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
    },
  });
  const initScore = parseFloat(document.getElementById('gauge-score').textContent) || 50;
  gaugeChart._needle = initScore / 100;
  gaugeChart.update('none');
} catch(e) { console.warn('Gauge init failed:', e.message); }

// ── Update: gauge + cards + chart v-lines ─────────────────────────────────────
const RAW_FMT = {
  momentum:   i => { const v=D.raws.gspc_close[i];  return v!=null?'S&P 500 close '+v:''; },
  vix:        i => { const v=D.raws.vix_close[i];   return v!=null?'VIX '+Number(v).toFixed(1):''; },
  safe_haven: i => { const v=D.raws.spy_close[i];   return v!=null?'SPY '+Number(v).toFixed(2):''; },
  junk:       i => { const v=D.raws.hyg_close[i];   return v!=null?'HYG '+Number(v).toFixed(2):''; },
  nh_nl:      i => { const nh=D.raws.nh[i],nl=D.raws.nl[i]; return (nh!=null&&nl!=null)?nh+' highs / '+nl+' lows':''; },
  breadth:    i => { const v=D.raws.mclellan_osc[i];return v!=null?'McClellan '+Number(v).toFixed(1):''; },
};

function updateAll(idx) {
  document.getElementById('as-of-label').textContent = fmtDate(DATES[idx]);

  const cs  = D.scores.composite[idx];
  const col = bandColor(cs);

  // Gauge text + needle
  const scoreEl = document.getElementById('gauge-score');
  scoreEl.textContent = cs != null ? Math.round(cs) : '—';
  scoreEl.style.color = col;
  const bandEl = document.getElementById('gauge-band');
  bandEl.textContent = bandLabel(cs); bandEl.style.color = col;
  const wc = D.weekly[idx];
  document.getElementById('gauge-change').textContent =
    wc != null ? (wc >= 0 ? '+' : '') + Number(wc).toFixed(1) + ' vs 1 week ago' : '';
  if (gaugeChart) {
    gaugeChart._needle = (cs != null ? cs : 50) / 100;
    gaugeChart.update('none');
  }

  // Cards
  document.querySelectorAll('.card[data-key]').forEach(card => {
    const key   = card.dataset.key;
    const score = D.scores[key] ? D.scores[key][idx] : null;
    const c     = bandColor(score);
    card.querySelector('.score-val').textContent = score != null ? Math.round(score) : '—';
    card.querySelector('.score-val').style.color = c;
    card.querySelector('.bar-fill').style.width      = (score != null ? score : 0) + '%';
    card.querySelector('.bar-fill').style.background = c;
    card.classList.toggle('null-card', score == null);
    card.querySelector('.card-raw').textContent = RAW_FMT[key] ? RAW_FMT[key](idx) : '';
  });

  // V-line on all rendered charts
  Object.values(activeCharts).forEach(ch => {
    ch._vLineIdx = idx;
    ch.update('none');
  });
}

// ── Slider ────────────────────────────────────────────────────────────────────
const slider = document.getElementById('date-slider');
slider.max   = D.n - 1;
slider.value = D.n - 1;
slider.addEventListener('input', e => updateAll(parseInt(e.target.value)));
document.getElementById('slider-section').style.display = '';

// ── Charts ────────────────────────────────────────────────────────────────────
const activeCharts = {};

const zoomOpts = {
  zoom: { wheel: { enabled: true }, pinch: { enabled: true }, mode: 'xy',
    onZoom: () => document.getElementById('reset-zoom-btn').classList.add('visible') },
  pan: { enabled: true, mode: 'xy',
    onPan: () => document.getElementById('reset-zoom-btn').classList.add('visible') },
};

function mkLine(canvasId, datasets, yLabel) {
  const ctx = document.getElementById(canvasId).getContext('2d');
  const chart = new Chart(ctx, {
    type: 'line',
    data: { labels: DATES, datasets },
    options: {
      responsive: true, animation: false, spanGaps: true,
      plugins: {
        legend: { position: 'top', labels: { boxWidth: 10, font: { size: 11 } } },
        zoom: zoomOpts,
      },
      scales: {
        x: { type: 'category', ticks: { maxTicksLimit: 8, maxRotation: 0, font: { size: 11 } } },
        y: { title: { display: !!yLabel, text: yLabel, font: { size: 11 } }, ticks: { font: { size: 11 } } },
      },
    },
  });
  chart._vLineIdx = D.n - 1;
  return chart;
}

function mkBar(canvasId, datasets, yLabel) {
  const ctx = document.getElementById(canvasId).getContext('2d');
  const chart = new Chart(ctx, {
    type: 'bar',
    data: { labels: DATES, datasets },
    options: {
      responsive: true, animation: false,
      plugins: {
        legend: { position: 'top', labels: { boxWidth: 10, font: { size: 11 } } },
        zoom: zoomOpts,
      },
      scales: {
        x: { ticks: { maxTicksLimit: 8, maxRotation: 0, font: { size: 11 } } },
        y: { title: { display: !!yLabel, text: yLabel, font: { size: 11 } }, ticks: { font: { size: 11 } } },
      },
    },
  });
  return chart;
}

const neutral = {
  label: 'Neutral (50)',
  data: Array(DATES.length).fill(50),
  borderColor: 'rgba(156,163,175,0.5)',
  borderWidth: 1,
  borderDash: [4, 4],
  pointRadius: 0,
  fill: false,
  spanGaps: true,
};

function buildChart(id) {
  if (activeCharts[id]) return;
  try {
    const yScore = 'Score (0–100)';
    switch (id) {
      case 'composite': {
        const ds = [
          { label: 'Composite', data: D.scores.composite,
            borderColor: '#7c3aed', backgroundColor: 'rgba(124,58,237,0.08)',
            borderWidth: 2, pointRadius: 0, fill: true },
        ];
        if (D.scores.cnn && D.scores.cnn.some(v => v !== null))
          ds.push({ label: 'CNN F&G', data: D.scores.cnn,
            borderColor: '#f97316', borderWidth: 1.5, pointRadius: 0,
            borderDash: [4, 4], fill: false });
        ds.push(neutral);
        activeCharts[id] = mkLine('compositeChart', ds, yScore);
        break;
      }
      case 'momentum':
        activeCharts[id] = mkLine('momentumChart', [
          { label: 'Momentum', data: D.scores.momentum,
            borderColor: '#2563eb', backgroundColor: 'rgba(37,99,235,0.07)',
            borderWidth: 2, pointRadius: 0, fill: true },
          neutral,
        ], yScore);
        break;
      case 'vix':
        activeCharts[id] = mkLine('vixChart', [
          { label: 'Volatility (VIX)', data: D.scores.vix,
            borderColor: '#dc2626', backgroundColor: 'rgba(220,38,38,0.07)',
            borderWidth: 2, pointRadius: 0, fill: true },
          neutral,
        ], yScore);
        break;
      case 'safe_haven':
        activeCharts[id] = mkLine('safeHavenChart', [
          { label: 'Safe Haven', data: D.scores.safe_haven,
            borderColor: '#0891b2', backgroundColor: 'rgba(8,145,178,0.07)',
            borderWidth: 2, pointRadius: 0, fill: true },
          neutral,
        ], yScore);
        break;
      case 'junk':
        activeCharts[id] = mkLine('junkChart', [
          { label: 'Credit (HYG/LQD)', data: D.scores.junk,
            borderColor: '#d97706', backgroundColor: 'rgba(217,119,6,0.07)',
            borderWidth: 2, pointRadius: 0, fill: true },
          neutral,
        ], yScore);
        break;
      case 'nh_nl': {
        const colors = (D.raws.nh_nl_net||[]).map(v => v!=null&&v>=0?'#16a34a':'#dc2626');
        activeCharts[id] = mkBar('nhNlChart', [{
          label: 'Net New Highs − Lows',
          data: D.raws.nh_nl_net,
          backgroundColor: colors,
          borderWidth: 0,
        }], 'Net NH−NL');
        break;
      }
      case 'ad_line':
        activeCharts[id] = mkLine('adLineChart', [{
          label: 'Cumulative A/D Line',
          data: D.raws.ad_line,
          borderColor: '#2563eb', borderWidth: 2, pointRadius: 0, fill: false,
        }], 'Cumulative');
        break;
      case 'mclellan': {
        const colors = (D.raws.mclellan_osc||[]).map(v => v!=null&&v>=0?'#16a34a':'#dc2626');
        activeCharts[id] = mkBar('mclellanChart', [{
          label: 'McClellan Oscillator',
          data: D.raws.mclellan_osc,
          backgroundColor: colors,
          borderWidth: 0,
        }], 'Oscillator');
        break;
      }
    }
  } catch(e) {
    console.warn('buildChart(' + id + ') failed:', e.message, e.stack);
  }
}

let activeTabId = 'composite';

function resetActiveZoom() {
  if (activeCharts[activeTabId]) {
    activeCharts[activeTabId].resetZoom();
    document.getElementById('reset-zoom-btn').classList.remove('visible');
  }
}

function showTab(id, btn) {
  document.querySelectorAll('.chart-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + id).classList.add('active');
  btn.classList.add('active');
  activeTabId = id;
  document.getElementById('reset-zoom-btn').classList.remove('visible');
  buildChart(id);
  if (activeCharts[id]) {
    activeCharts[id]._vLineIdx = parseInt(slider.value);
    activeCharts[id].update('none');
  }
}

// Stale badges
if (D.stale && D.stale.length) {
  const footer = document.getElementById('footer-bar');
  D.stale.forEach(s => {
    const span = document.createElement('span');
    span.className = 'stale-badge';
    span.textContent = '⚠ ' + s + ' stale';
    footer.appendChild(span);
  });
}

// Init composite chart
buildChart('composite');
</script>
</body>
</html>"""
