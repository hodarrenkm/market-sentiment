"""
Generate docs/index.html from the history DataFrame.
All data is embedded as a JSON blob — no runtime API calls.
Static HTML renders scores without JavaScript; JS adds interactivity.
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

    # Raw value time series (for slider raw-text updates)
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

    # ── Latest-date values for static HTML ────────────────────────────────────
    latest_idx = n - 1
    composite_val = comp[latest_idx] or 50.0
    gauge_color   = band_color(composite_val)
    gauge_band    = band_label(composite_val)
    gauge_score   = str(round(composite_val))
    date_str      = dates[latest_idx]
    wc            = weekly[latest_idx]
    change_str    = (("+" if wc >= 0 else "") + f"{wc:.1f} vs 1 week ago") if wc is not None else ""

    # ── Static cards HTML ──────────────────────────────────────────────────────
    cards_html = ""
    for key, label in _SUB_LABELS.items():
        sv = scores[key][latest_idx]
        col = band_color(sv) if sv is not None else "#888"
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
            f'\n        <div class="card{null_cls}" data-key="{key}">'
            f'\n          <div class="card-label">{label}</div>'
            f'\n          <div class="card-score">'
            f'<span class="score-val" style="color:{col}">{score_disp}</span>'
            f'<span class="card-denom">/100</span></div>'
            f'\n          <div class="bar-track">'
            f'<div class="bar-fill" style="width:{bar_pct:.0f}%;background:{col}"></div></div>'
            f'\n          <div class="card-raw">{raw_str}</div>'
            f'\n        </div>'
        )

    # ── Stale badges HTML ──────────────────────────────────────────────────────
    stale_html = "".join(
        f'<span class="stale-badge">⚠ {s} stale</span>' for s in stale_sources
    )

    # ── JSON payload for interactive slider / charts ───────────────────────────
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
    --bg: #f8fafc; --surface: #fff; --border: #e2e8f0;
    --text: #0f172a; --muted: #64748b; --accent: #6d28d9;
  }
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--text); font-family: system-ui, sans-serif; padding: 1rem; max-width: 1100px; margin: 0 auto; }
h1 { text-align: center; font-size: 1.3rem; color: var(--muted); margin-bottom: 1.5rem; font-weight: 400; }

/* Slider */
.slider-row { display: flex; align-items: center; gap: .75rem; margin-bottom: 1.5rem; flex-wrap: wrap; }
.slider-row label { font-size: .82rem; color: var(--muted); white-space: nowrap; }
.slider-row label span { color: var(--text); font-weight: 600; }
#date-slider { flex: 1; min-width: 140px; accent-color: var(--accent); cursor: pointer; }

/* Gauge */
.gauge-wrap { display: flex; flex-direction: column; align-items: center; margin-bottom: 2rem; }
.gauge-canvas { max-width: 360px; width: 100%; }
.gauge-score { font-size: 3rem; font-weight: 700; margin-top: -2.5rem; }
.gauge-band  { font-size: 1.2rem; font-weight: 600; margin-top: 0.25rem; }
.gauge-change { font-size: 0.85rem; color: var(--muted); margin-top: 0.25rem; }

/* Cards */
.cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 0.75rem;
  margin-bottom: 2rem;
}
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 0.85rem; }
.card.null-card { opacity: 0.45; }
.card-label { font-size: 0.7rem; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; margin-bottom: 0.4rem; }
.card-score { font-size: 1.8rem; font-weight: 700; line-height: 1; }
.card-denom { font-size: 0.85rem; font-weight: 400; color: var(--muted); }
.bar-track { height: 5px; background: var(--border); border-radius: 3px; margin: 0.5rem 0; }
.bar-fill  { height: 100%; border-radius: 3px; transition: width .3s, background .3s; }
.card-raw  { font-size: 0.72rem; color: var(--muted); }

/* Chart tabs */
.tabs { display: flex; gap: 0.4rem; margin-bottom: 0.75rem; flex-wrap: wrap; }
.tab-btn {
  padding: 0.3rem 0.75rem; border-radius: 6px; border: 1px solid var(--border);
  background: var(--surface); color: var(--muted); cursor: pointer; font-size: 0.78rem;
  transition: all .15s;
}
.tab-btn:hover { color: var(--text); }
.tab-btn.active { background: var(--accent); border-color: var(--accent); color: #fff; }
.chart-panel { display: none; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 1rem; }
.chart-panel.active { display: block; }

/* Footer */
footer {
  margin-top: 1.5rem; font-size: 0.72rem; color: var(--muted);
  text-align: center; border-top: 1px solid var(--border); padding-top: 0.75rem;
  display: flex; flex-wrap: wrap; justify-content: center; gap: 0.5rem;
}
.stale-badge { background: #7c3f00; color: #ffb347; padding: 0.15rem 0.5rem; border-radius: 4px; font-size: 0.7rem; }

@media (max-width: 520px) {
  .gauge-canvas { max-width: 240px; }
  .gauge-score { font-size: 2.5rem; }
  .cards-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
</head>
<body>
<h1>US Market Sentiment &amp; Breadth</h1>

<div class="slider-row" id="slider-section" style="display:none">
  <label>As of <span id="as-of-label">__DATE_STR__</span></label>
  <input type="range" id="date-slider" min="0" max="1" value="1">
</div>

<div class="gauge-wrap">
  <canvas id="gaugeChart" class="gauge-canvas" height="200"></canvas>
  <div id="gauge-score" class="gauge-score" style="color:__GAUGE_COLOR__">__GAUGE_SCORE__</div>
  <div id="gauge-band"  class="gauge-band"  style="color:__GAUGE_COLOR__">__GAUGE_BAND__</div>
  <div id="gauge-change" class="gauge-change">__GAUGE_CHANGE__</div>
</div>

<div class="cards-grid">__CARDS_HTML__
</div>

<div class="tabs">
  <button class="tab-btn active" onclick="showTab('composite',this)">Composite</button>
  <button class="tab-btn" onclick="showTab('momentum',this)">Momentum</button>
  <button class="tab-btn" onclick="showTab('vix',this)">Volatility</button>
  <button class="tab-btn" onclick="showTab('safe_haven',this)">Safe Haven</button>
  <button class="tab-btn" onclick="showTab('junk',this)">Credit</button>
  <button class="tab-btn" onclick="showTab('nh_nl',this)">NH−NL</button>
  <button class="tab-btn" onclick="showTab('ad_line',this)">A/D Line</button>
  <button class="tab-btn" onclick="showTab('mclellan',this)">McClellan</button>
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

// ── Helpers ───────────────────────────────────────────────────────────────────
function bandColor(s) {
  if (s == null) return '#888888';
  if (s < 25) return '#e63946';
  if (s < 45) return '#f4a261';
  if (s < 55) return '#e9c46a';
  if (s < 75) return '#2a9d8f';
  return '#264653';
}
function bandLabel(s) {
  if (s == null) return '—';
  if (s < 25) return 'Extreme Fear';
  if (s < 45) return 'Fear';
  if (s < 55) return 'Neutral';
  if (s < 75) return 'Greed';
  return 'Extreme Greed';
}

const isDark = window.matchMedia('(prefers-color-scheme: dark)').matches;

// ── Gauge ─────────────────────────────────────────────────────────────────────
let gaugeChart = null;
try {
  Chart.defaults.color       = isDark ? '#8892a4' : '#64748b';
  Chart.defaults.borderColor = isDark ? 'rgba(255,255,255,0.07)' : 'rgba(0,0,0,0.07)';

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

  gaugeChart = new Chart(document.getElementById('gaugeChart').getContext('2d'), {
    type: 'doughnut',
    data: {
      datasets: [{
        data: [25, 20, 10, 20, 25],
        backgroundColor: ['#e63946','#f4a261','#e9c46a','#2a9d8f','#264653'],
        borderWidth: 0,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: true, aspectRatio: 2,
      cutout: '70%', circumference: 180, rotation: -90, animation: false,
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
    },
    plugins: [needlePlugin],
  });

  // Set initial needle position from static HTML score
  const initScore = parseFloat(document.getElementById('gauge-score').textContent) || 50;
  gaugeChart._needle = initScore / 100;
  gaugeChart.update('none');
} catch(e) {
  console.warn('Gauge init failed:', e.message);
}

// ── Slider ────────────────────────────────────────────────────────────────────
const RAW_FMT = {
  momentum:   i => { const v=D.raws.gspc_close[i];  return v!=null?'S\\u0026P 500 close '+v:''; },
  vix:        i => { const v=D.raws.vix_close[i];   return v!=null?'VIX '+Number(v).toFixed(1):''; },
  safe_haven: i => { const v=D.raws.spy_close[i];   return v!=null?'SPY price '+Number(v).toFixed(2):''; },
  junk:       i => { const v=D.raws.hyg_close[i];   return v!=null?'HYG '+Number(v).toFixed(2):''; },
  nh_nl:      i => { const nh=D.raws.nh[i],nl=D.raws.nl[i]; return (nh!=null&&nl!=null)?nh+' highs / '+nl+' lows':''; },
  breadth:    i => { const v=D.raws.mclellan_osc[i];return v!=null?'McClellan '+Number(v).toFixed(1):''; },
};

function updateAll(idx) {
  document.getElementById('as-of-label').textContent = DATES[idx];

  // Update gauge text + needle
  const cs = D.scores.composite[idx];
  const col = bandColor(cs);
  const scoreEl = document.getElementById('gauge-score');
  scoreEl.textContent = cs != null ? Math.round(cs) : '—';
  scoreEl.style.color = col;
  const bandEl = document.getElementById('gauge-band');
  bandEl.textContent = bandLabel(cs); bandEl.style.color = col;
  const wc = D.weekly[idx];
  document.getElementById('gauge-change').textContent =
    wc != null ? (wc >= 0 ? '+' : '') + wc.toFixed(1) + ' vs 1 week ago' : '';
  if (gaugeChart) {
    gaugeChart._needle = (cs != null ? cs : 50) / 100;
    gaugeChart.update('none');
  }

  // Update cards
  document.querySelectorAll('.card[data-key]').forEach(card => {
    const key = card.dataset.key;
    const score = D.scores[key] ? D.scores[key][idx] : null;
    const c = bandColor(score);
    const sv = card.querySelector('.score-val');
    sv.textContent = score != null ? Math.round(score) : '—';
    sv.style.color = c;
    const bf = card.querySelector('.bar-fill');
    bf.style.width = (score != null ? score : 0) + '%';
    bf.style.background = c;
    card.classList.toggle('null-card', score == null);
    const re = card.querySelector('.card-raw');
    re.textContent = RAW_FMT[key] ? RAW_FMT[key](idx) : '';
  });

  // Redraw active chart vertical line
  Object.keys(activeCharts).forEach(id => {
    const chart = activeCharts[id];
    chart._vLineIdx = idx;
    chart.update('none');
  });
}

const slider = document.getElementById('date-slider');
slider.max   = D.n - 1;
slider.value = D.n - 1;
slider.addEventListener('input', e => updateAll(parseInt(e.target.value)));
document.getElementById('slider-section').style.display = '';

// ── Charts ────────────────────────────────────────────────────────────────────
const activeCharts = {};
let activeTabId = 'composite';

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
    ctx.strokeStyle = isDark ? 'rgba(255,220,50,0.8)' : 'rgba(160,110,0,0.8)';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([5, 3]);
    ctx.stroke();
    ctx.restore();
  }
};

function mkLine(canvasId, datasets, yLabel) {
  const ctx = document.getElementById(canvasId).getContext('2d');
  const chart = new Chart(ctx, {
    type: 'line',
    data: { labels: DATES, datasets },
    options: {
      responsive: true, animation: false, spanGaps: true,
      plugins: { legend: { position: 'top', labels: { boxWidth: 12 } } },
      scales: {
        x: { type: 'category', ticks: { maxTicksLimit: 8, maxRotation: 0 } },
        y: { title: { display: !!yLabel, text: yLabel } },
      },
    },
    plugins: [vLinePlugin],
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
      plugins: { legend: { position: 'top', labels: { boxWidth: 12 } } },
      scales: {
        x: { ticks: { maxTicksLimit: 8, maxRotation: 0 } },
        y: { title: { display: !!yLabel, text: yLabel } },
      },
    },
  });
  return chart;
}

function buildChart(id) {
  if (activeCharts[id]) return;
  try {
    const hasCnn = D.scores.cnn && D.scores.cnn.some(v => v !== null);
    const yScore = 'Score (0–100)';
    const neutral = {
      label: 'Neutral (50)', data: Array(DATES.length).fill(50),
      borderColor: 'rgba(128,128,128,0.3)', borderWidth: 1, borderDash: [4,4],
      pointRadius: 0, fill: false, spanGaps: true,
    };
    switch (id) {
      case 'composite': {
        const ds = [
          { label: 'Our Composite', data: D.scores.composite, borderColor: '#7c3aed',
            backgroundColor: 'rgba(124,58,237,0.1)', borderWidth: 2, pointRadius: 0, fill: true },
        ];
        if (hasCnn) ds.push({ label: 'CNN F&G', data: D.scores.cnn,
          borderColor: '#f97316', borderWidth: 1.5, pointRadius: 0, borderDash: [4,4] });
        ds.push(neutral);
        activeCharts[id] = mkLine('compositeChart', ds, yScore);
        break;
      }
      case 'momentum':
        activeCharts[id] = mkLine('momentumChart', [
          { label: 'Market Momentum', data: D.scores.momentum, borderColor: '#3b82f6',
            backgroundColor: 'rgba(59,130,246,0.07)', borderWidth: 2, pointRadius: 0, fill: true },
          neutral,
        ], yScore);
        break;
      case 'vix':
        activeCharts[id] = mkLine('vixChart', [
          { label: 'Volatility (VIX)', data: D.scores.vix, borderColor: '#e63946',
            backgroundColor: 'rgba(230,57,70,0.07)', borderWidth: 2, pointRadius: 0, fill: true },
          neutral,
        ], yScore);
        break;
      case 'safe_haven':
        activeCharts[id] = mkLine('safeHavenChart', [
          { label: 'Safe Haven Demand', data: D.scores.safe_haven, borderColor: '#06b6d4',
            backgroundColor: 'rgba(6,182,212,0.07)', borderWidth: 2, pointRadius: 0, fill: true },
          neutral,
        ], yScore);
        break;
      case 'junk':
        activeCharts[id] = mkLine('junkChart', [
          { label: 'Credit Demand (HYG/LQD)', data: D.scores.junk, borderColor: '#f59e0b',
            backgroundColor: 'rgba(245,158,11,0.07)', borderWidth: 2, pointRadius: 0, fill: true },
          neutral,
        ], yScore);
        break;
      case 'nh_nl': {
        const colors = (D.raws.nh_nl_net || []).map(v => (v != null && v >= 0) ? '#2a9d8f' : '#e63946');
        activeCharts[id] = mkBar('nhNlChart', [{
          label: 'Net New Highs−Lows (S&P 500 proxy)',
          data: D.raws.nh_nl_net, backgroundColor: colors, borderWidth: 0,
        }], 'Net NH−NL');
        break;
      }
      case 'ad_line':
        activeCharts[id] = mkLine('adLineChart', [{
          label: 'Cumulative A/D Line (S&P 500 proxy)',
          data: D.raws.ad_line, borderColor: '#3b82f6', borderWidth: 2, pointRadius: 0,
        }], 'Cumulative');
        break;
      case 'mclellan': {
        const colors = (D.raws.mclellan_osc || []).map(v => (v != null && v >= 0) ? '#2a9d8f' : '#e63946');
        activeCharts[id] = mkBar('mclellanChart', [{
          label: 'McClellan Oscillator (S&P 500 proxy)',
          data: D.raws.mclellan_osc, backgroundColor: colors, borderWidth: 0,
        }], 'Oscillator');
        break;
      }
    }
  } catch(e) {
    console.warn('buildChart(' + id + ') failed:', e.message);
  }
}

function showTab(id, btn) {
  document.querySelectorAll('.chart-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + id).classList.add('active');
  btn.classList.add('active');
  activeTabId = id;
  buildChart(id);
}

// Build composite chart on load
buildChart('composite');
</script>
</body>
</html>"""
