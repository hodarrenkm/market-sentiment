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
    """Float, rounded; None for NaN/inf; int for 0 decimals."""
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

    # Score time series (all dates)
    scores = {k: _col(history, f"score_{k}", 1) for k in _SUB_LABELS}
    scores["composite"] = _col(history, "composite", 1)
    scores["cnn"]       = _col(history, "cnn_score", 1)

    # Raw value time series (for slider subtitle updates)
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

    # Weekly delta per date (composite[i] - composite[i-5])
    comp = scores["composite"]
    weekly = [
        round(comp[i] - comp[i - 5], 1)
        if i >= 5 and comp[i] is not None and comp[i - 5] is not None
        else None
        for i in range(n)
    ]

    payload = {
        "dates":  dates,
        "scores": scores,
        "raws":   raws,
        "weekly": weekly,
        "stale":  stale_sources,
        "n":      n,
    }

    html = _HTML_TEMPLATE.replace("__DATA_JSON__", json.dumps(payload, separators=(",", ":")))
    OUTPUT.write_text(html, encoding="utf-8")
    logger.info("Dashboard written → %s", OUTPUT)


# ── HTML template ─────────────────────────────────────────────────────────────

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Market Sentiment Dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"
        integrity="sha512-ZwR1/gSZM3ai6vCdI+LVF1zSq/5HznD3oD+sCoJrzXJ+yKen9RtQ1/IHpHMcNcIGVHjbrBORdEBjP7t07X3tA=="
        crossorigin="anonymous" referrerpolicy="no-referrer"></script>
<style>
:root {
  --bg: #0f1117; --surface: #1a1d27; --border: #2a2d3e;
  --text: #e2e8f0; --muted: #8892a4; --accent: #7c3aed;
}
@media (prefers-color-scheme: light) {
  :root {
    --bg: #f8fafc; --surface: #ffffff; --border: #e2e8f0;
    --text: #0f172a; --muted: #64748b; --accent: #6d28d9;
  }
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg); color: var(--text);
  font-family: system-ui, -apple-system, sans-serif;
  padding: 1rem; max-width: 1100px; margin: 0 auto;
}
h1 {
  text-align: center; font-size: 1.1rem; font-weight: 400;
  color: var(--muted); letter-spacing: .06em; text-transform: uppercase;
  margin-bottom: 1.1rem;
}

/* Slider */
.slider-row {
  display: flex; align-items: center; gap: .75rem;
  margin-bottom: 1.5rem; flex-wrap: wrap;
}
.slider-row label { font-size: .82rem; color: var(--muted); white-space: nowrap; }
.slider-row label span { color: var(--text); font-weight: 600; }
#date-slider { flex: 1; min-width: 140px; accent-color: var(--accent); cursor: pointer; }

/* Main row */
.main-row {
  display: flex; gap: 1.5rem; align-items: flex-start;
  margin-bottom: 2rem; flex-wrap: wrap;
}
.gauge-section {
  display: flex; flex-direction: column; align-items: center;
  min-width: 200px; flex: 0 0 auto;
}
.gauge-canvas { width: 100%; max-width: 280px; }
.gauge-info { text-align: center; margin-top: -1rem; }
#gauge-score { font-size: 3.5rem; font-weight: 700; line-height: 1; }
#gauge-band  { font-size: 1.05rem; font-weight: 600; margin-top: .2rem; }
#gauge-change { font-size: .8rem; color: var(--muted); margin-top: .3rem; min-height: 1.1em; }

/* Cards */
.cards-section { flex: 1; min-width: 0; }
.cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: .65rem;
}
.card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: .75rem;
  box-shadow: 0 1px 3px rgba(0,0,0,.15);
  transition: opacity .2s;
}
.card.null-card { opacity: .4; }
.card-label {
  font-size: .65rem; color: var(--muted);
  text-transform: uppercase; letter-spacing: .05em; margin-bottom: .35rem;
}
.card-score { font-size: 1.85rem; font-weight: 700; line-height: 1; }
.card-denom { font-size: .8rem; font-weight: 400; color: var(--muted); }
.bar-track { height: 5px; background: var(--border); border-radius: 3px; margin: .45rem 0 .3rem; }
.bar-fill  { height: 100%; border-radius: 3px; transition: width .3s, background .3s; }
.card-raw  { font-size: .68rem; color: var(--muted); }

/* Charts */
.chart-section { margin-bottom: 2rem; }
.tab-row { display: flex; gap: .3rem; flex-wrap: wrap; margin-bottom: .65rem; }
.tab-btn {
  padding: .28rem .7rem; border-radius: 6px;
  border: 1px solid var(--border); background: var(--surface);
  color: var(--muted); cursor: pointer; font-size: .76rem;
  transition: all .15s;
}
.tab-btn:hover { color: var(--text); }
.tab-btn.active { background: var(--accent); border-color: var(--accent); color: #fff; }
.chart-panel {
  display: none; background: var(--surface);
  border: 1px solid var(--border); border-radius: 10px; padding: 1rem;
}
.chart-panel.active { display: block; }

/* Footer */
footer {
  margin-top: 1rem; font-size: .68rem; color: var(--muted);
  text-align: center; border-top: 1px solid var(--border); padding-top: .65rem;
  display: flex; flex-wrap: wrap; justify-content: center; gap: .5rem;
}
.stale-badge {
  background: #7c3f00; color: #ffb347;
  padding: .1rem .45rem; border-radius: 4px;
}

@media (max-width: 520px) {
  .gauge-canvas { max-width: 220px; }
  #gauge-score { font-size: 2.8rem; }
  .cards-grid { grid-template-columns: repeat(2, 1fr); }
  .tab-btn { font-size: .7rem; padding: .25rem .55rem; }
}
</style>
</head>
<body>
<h1>US Market Sentiment &amp; Breadth</h1>

<div class="slider-row">
  <label>As of <span id="as-of-label">—</span></label>
  <input type="range" id="date-slider" min="0" max="1" value="1">
</div>

<div class="main-row">
  <div class="gauge-section">
    <canvas id="gaugeChart" class="gauge-canvas"></canvas>
    <div class="gauge-info">
      <div id="gauge-score">—</div>
      <div id="gauge-band">—</div>
      <div id="gauge-change"></div>
    </div>
  </div>
  <div class="cards-section">
    <div class="cards-grid"></div>
  </div>
</div>

<div class="chart-section">
  <div class="tab-row">
    <button class="tab-btn active"  onclick="showTab('composite',this)">Composite</button>
    <button class="tab-btn"         onclick="showTab('momentum',this)">Momentum</button>
    <button class="tab-btn"         onclick="showTab('vix',this)">Volatility</button>
    <button class="tab-btn"         onclick="showTab('safe_haven',this)">Safe Haven</button>
    <button class="tab-btn"         onclick="showTab('junk',this)">Credit</button>
    <button class="tab-btn"         onclick="showTab('nh_nl',this)">NH−NL</button>
    <button class="tab-btn"         onclick="showTab('mclellan',this)">McClellan</button>
    <button class="tab-btn"         onclick="showTab('ad_line',this)">A/D Line</button>
  </div>
  <div id="panel-composite"  class="chart-panel active"><canvas id="chart-composite"></canvas></div>
  <div id="panel-momentum"   class="chart-panel"><canvas id="chart-momentum"></canvas></div>
  <div id="panel-vix"        class="chart-panel"><canvas id="chart-vix"></canvas></div>
  <div id="panel-safe_haven" class="chart-panel"><canvas id="chart-safe_haven"></canvas></div>
  <div id="panel-junk"       class="chart-panel"><canvas id="chart-junk"></canvas></div>
  <div id="panel-nh_nl"      class="chart-panel"><canvas id="chart-nh_nl"></canvas></div>
  <div id="panel-mclellan"   class="chart-panel"><canvas id="chart-mclellan"></canvas></div>
  <div id="panel-ad_line"    class="chart-panel"><canvas id="chart-ad_line"></canvas></div>
</div>

<footer id="footer-bar">
  <span>S&amp;P 500 breadth: proxy computed from constituents (not NYSE)</span>
</footer>

<script>
const D = __DATA_JSON__;

// ── Colour helpers ───────────────────────────────────────────────────────────
function bandColor(s) {
  if (s == null) return '#888888';
  if (s < 25)   return '#e63946';
  if (s < 45)   return '#f4a261';
  if (s < 55)   return '#e9c46a';
  if (s < 75)   return '#2a9d8f';
  return '#264653';
}
function bandLabel(s) {
  if (s == null) return '—';
  if (s < 25)   return 'Extreme Fear';
  if (s < 45)   return 'Fear';
  if (s < 55)   return 'Neutral';
  if (s < 75)   return 'Greed';
  return 'Extreme Greed';
}

const isDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
Chart.defaults.color       = isDark ? '#8892a4' : '#64748b';
Chart.defaults.borderColor = isDark ? 'rgba(255,255,255,0.07)' : 'rgba(0,0,0,0.07)';

// ── Plugins ──────────────────────────────────────────────────────────────────
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
    const r  = (arc.outerRadius + arc.innerRadius) / 2;
    const angle = Math.PI * (1 + pos);
    const col = isDark ? '#e2e8f0' : '#0f172a';
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + r * Math.cos(angle), cy + r * Math.sin(angle));
    ctx.strokeStyle = col; ctx.lineWidth = 2.5; ctx.stroke();
    ctx.beginPath();
    ctx.arc(cx, cy, 6, 0, 2 * Math.PI);
    ctx.fillStyle = col; ctx.fill();
    ctx.restore();
  }
};

const vLinePlugin = {
  id: 'vLine',
  afterDraw(chart) {
    const idx = chart._vLineIdx;
    if (idx == null) return;
    const { ctx, chartArea, scales } = chart;
    if (!chartArea || !scales.x) return;
    const x = scales.x.getPixelForValue(idx);
    if (x < chartArea.left || x > chartArea.right) return;
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(x, chartArea.top);
    ctx.lineTo(x, chartArea.bottom);
    ctx.strokeStyle = isDark ? 'rgba(255,220,50,0.85)' : 'rgba(160,110,0,0.85)';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([5, 3]);
    ctx.stroke();
    ctx.restore();
  }
};

Chart.register(needlePlugin, vLinePlugin);

// ── Gauge ────────────────────────────────────────────────────────────────────
const gaugeChart = new Chart(
  document.getElementById('gaugeChart').getContext('2d'), {
    type: 'doughnut',
    data: {
      datasets: [{
        data: [25, 20, 10, 20, 25],
        backgroundColor: ['#e63946','#f4a261','#e9c46a','#2a9d8f','#264653'],
        borderWidth: 0,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      aspectRatio: 2,
      cutout: '70%',
      circumference: 180,
      rotation: -90,
      animation: false,
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
    },
  }
);
gaugeChart._needle = 0.5;

// ── Cards ────────────────────────────────────────────────────────────────────
const CARD_DEFS = [
  { key: 'momentum',   label: 'Market Momentum' },
  { key: 'vix',        label: 'Volatility (VIX)' },
  { key: 'safe_haven', label: 'Safe Haven Demand' },
  { key: 'junk',       label: 'Credit Demand (HYG/LQD)' },
  { key: 'nh_nl',      label: 'New Highs / New Lows' },
  { key: 'breadth',    label: 'Stock Breadth (McClellan)' },
];
const cardsGrid = document.querySelector('.cards-grid');
CARD_DEFS.forEach(({ key, label }) => {
  const d = document.createElement('div');
  d.className = 'card'; d.dataset.key = key;
  d.innerHTML =
    '<div class="card-label">' + label + '</div>' +
    '<div class="card-score"><span class="score-val">—</span>' +
    '<span class="card-denom">/100</span></div>' +
    '<div class="bar-track"><div class="bar-fill" style="width:0%"></div></div>' +
    '<div class="card-raw"></div>';
  cardsGrid.appendChild(d);
});

// Raw-value text per card
const RAW_FMT = {
  momentum:   i => { const v=D.raws.gspc_close[i]; return v!=null?'S&P 500 close '+v:''; },
  vix:        i => { const v=D.raws.vix_close[i];  return v!=null?'VIX '+v.toFixed(1):''; },
  safe_haven: i => { const v=D.raws.spy_close[i];  return v!=null?'SPY price '+v.toFixed(2):''; },
  junk:       i => { const v=D.raws.hyg_close[i];  return v!=null?'HYG '+v.toFixed(2):''; },
  nh_nl:      i => {
    const nh=D.raws.nh[i], nl=D.raws.nl[i];
    return (nh!=null&&nl!=null)?nh+' highs / '+nl+' lows':'';
  },
  breadth:    i => { const v=D.raws.mclellan_osc[i]; return v!=null?'McClellan '+v.toFixed(1):''; },
};

// ── Update functions ─────────────────────────────────────────────────────────
function updateGauge(idx) {
  const score = D.scores.composite[idx];
  const s = score != null ? score : 50;
  gaugeChart._needle = s / 100;
  gaugeChart.update('none');
  const col = bandColor(score);
  const el = document.getElementById('gauge-score');
  el.textContent = score != null ? Math.round(s) : '—';
  el.style.color = col;
  const bl = document.getElementById('gauge-band');
  bl.textContent = bandLabel(score); bl.style.color = col;
  const wc = D.weekly[idx];
  document.getElementById('gauge-change').textContent =
    wc != null ? (wc >= 0 ? '+' : '') + wc.toFixed(1) + ' vs 1 week ago' : '';
}

function updateCards(idx) {
  CARD_DEFS.forEach(({ key }) => {
    const card = document.querySelector('.card[data-key="' + key + '"]');
    if (!card) return;
    const score = D.scores[key][idx];
    const scoreEl = card.querySelector('.score-val');
    const barEl   = card.querySelector('.bar-fill');
    const rawEl   = card.querySelector('.card-raw');
    if (score != null) {
      const col = bandColor(score);
      scoreEl.textContent = Math.round(score);
      scoreEl.style.color = col;
      barEl.style.width = score + '%';
      barEl.style.background = col;
      card.classList.remove('null-card');
    } else {
      scoreEl.textContent = '—';
      scoreEl.style.color = '#888';
      barEl.style.width = '0%';
      card.classList.add('null-card');
    }
    rawEl.textContent = RAW_FMT[key](idx);
  });
}

function updateVLine(id, idx) {
  const chart = activeCharts[id];
  if (!chart) return;
  chart._vLineIdx = idx;
  chart.update('none');
}

let currentIdx = D.n - 1;
const activeCharts = {};

function updateAll(idx) {
  currentIdx = idx;
  document.getElementById('as-of-label').textContent = D.dates[idx];
  updateGauge(idx);
  updateCards(idx);
  Object.keys(activeCharts).forEach(id => updateVLine(id, idx));
}

// ── Chart builders ────────────────────────────────────────────────────────────
function neutralLine(n) {
  return {
    label: 'Neutral (50)',
    data: Array(n).fill(50),
    borderColor: 'rgba(128,128,128,0.3)',
    borderWidth: 1,
    borderDash: [4, 4],
    pointRadius: 0,
    fill: false,
    spanGaps: true,
  };
}

const LINE_DEFAULTS = { borderWidth: 2, pointRadius: 0, spanGaps: true, tension: 0.1 };
const BAR_DEFAULTS  = { borderWidth: 0 };

function mkLine(ctx, datasets, yOpts) {
  return new Chart(ctx, {
    type: 'line',
    data: { labels: D.dates, datasets: datasets.map(ds => Object.assign({}, LINE_DEFAULTS, ds)) },
    options: {
      responsive: true, animation: false, parsing: false,
      plugins: { legend: { position: 'top', labels: { boxWidth: 10, font: { size: 11 } } } },
      scales: {
        x: { type: 'category', ticks: { maxTicksLimit: 8, maxRotation: 0 } },
        y: Object.assign({ ticks: { font: { size: 11 } } }, yOpts),
      },
    },
  });
}

function mkBar(ctx, datasets, yOpts) {
  return new Chart(ctx, {
    type: 'bar',
    data: { labels: D.dates, datasets: datasets.map(ds => Object.assign({}, BAR_DEFAULTS, ds)) },
    options: {
      responsive: true, animation: false,
      plugins: { legend: { position: 'top', labels: { boxWidth: 10, font: { size: 11 } } } },
      scales: {
        x: { type: 'category', ticks: { maxTicksLimit: 8, maxRotation: 0 } },
        y: Object.assign({ ticks: { font: { size: 11 } } }, yOpts),
      },
    },
  });
}

function buildChart(id) {
  const ctx = document.getElementById('chart-' + id).getContext('2d');
  const n = D.dates.length;
  let chart;
  const yScore = { min: 0, max: 100, title: { display: true, text: 'Score (0–100)' } };

  switch (id) {
    case 'composite': {
      const ds = [
        { label: 'Composite', data: D.scores.composite, borderColor: '#7c3aed',
          backgroundColor: 'rgba(124,58,237,0.08)', fill: true },
        neutralLine(n),
      ];
      if (D.scores.cnn.some(v => v != null))
        ds.splice(1, 0, { label: 'CNN F&G', data: D.scores.cnn,
          borderColor: '#f97316', borderWidth: 1.5, borderDash: [4, 4] });
      chart = mkLine(ctx, ds, yScore);
      break;
    }
    case 'momentum':
      chart = mkLine(ctx, [
        { label: 'Market Momentum', data: D.scores.momentum,
          borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.07)', fill: true },
        neutralLine(n),
      ], yScore);
      break;
    case 'vix':
      chart = mkLine(ctx, [
        { label: 'Volatility (VIX)', data: D.scores.vix,
          borderColor: '#e63946', backgroundColor: 'rgba(230,57,70,0.07)', fill: true },
        neutralLine(n),
      ], yScore);
      break;
    case 'safe_haven':
      chart = mkLine(ctx, [
        { label: 'Safe Haven Demand', data: D.scores.safe_haven,
          borderColor: '#06b6d4', backgroundColor: 'rgba(6,182,212,0.07)', fill: true },
        neutralLine(n),
      ], yScore);
      break;
    case 'junk':
      chart = mkLine(ctx, [
        { label: 'Credit Demand (HYG/LQD)', data: D.scores.junk,
          borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,0.07)', fill: true },
        neutralLine(n),
      ], yScore);
      break;
    case 'nh_nl': {
      const colors = (D.raws.nh_nl_net || []).map(v => (v != null && v >= 0) ? '#2a9d8f' : '#e63946');
      chart = mkBar(ctx, [{
        label: 'Net New Highs−Lows (S&P 500 proxy)',
        data: D.raws.nh_nl_net, backgroundColor: colors,
      }], { title: { display: true, text: 'Net NH−NL' } });
      break;
    }
    case 'mclellan': {
      const colors = (D.raws.mclellan_osc || []).map(v => (v != null && v >= 0) ? '#2a9d8f' : '#e63946');
      chart = mkBar(ctx, [{
        label: 'McClellan Oscillator (S&P 500 proxy)',
        data: D.raws.mclellan_osc, backgroundColor: colors,
      }], { title: { display: true, text: 'Oscillator' } });
      break;
    }
    case 'ad_line':
      chart = mkLine(ctx, [{
        label: 'Cumulative A/D Line (S&P 500 proxy)',
        data: D.raws.ad_line, borderColor: '#3b82f6',
      }], { title: { display: true, text: 'Cumulative' } });
      break;
  }
  chart._vLineIdx = currentIdx;
  activeCharts[id] = chart;
}

// ── Tab switching ─────────────────────────────────────────────────────────────
function showTab(id, btn) {
  document.querySelectorAll('.chart-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('panel-' + id).classList.add('active');
  btn.classList.add('active');
  if (!activeCharts[id]) buildChart(id);
  else updateVLine(id, currentIdx);
}

// ── Slider ────────────────────────────────────────────────────────────────────
const slider = document.getElementById('date-slider');
slider.max   = D.n - 1;
slider.value = D.n - 1;
slider.addEventListener('input', e => updateAll(parseInt(e.target.value, 10)));

// ── Stale badges ──────────────────────────────────────────────────────────────
if (D.stale && D.stale.length) {
  const footer = document.getElementById('footer-bar');
  D.stale.forEach(s => {
    const span = document.createElement('span');
    span.className = 'stale-badge';
    span.textContent = '⚠ ' + s + ' stale';
    footer.appendChild(span);
  });
}

// ── Init ──────────────────────────────────────────────────────────────────────
buildChart('composite');
updateAll(D.n - 1);
</script>
</body>
</html>"""
