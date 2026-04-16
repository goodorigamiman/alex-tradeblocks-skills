#!/usr/bin/env python3
"""
Shared parallel coordinate plot generator.
Block-specific scripts import this and call generate() with a config dict.

Usage from a block-specific wrapper:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'Alex-TradeBlocks-Skills'))
    from build_parallel_coords import generate

    generate({
        'block_folder': os.path.dirname(os.path.abspath(__file__)),
        'block_name':   '20250926 - SPX DC 5-7 22.5-15d oF',
    })
"""

import csv
import json
import math
import os


SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
GROUPS_CSV_DEFAULT = os.path.join(SKILLS_DIR, "entry_filter_groups.default.csv")

# ── Short labels ──────────────────────────────────────────────────────────────
SHORT_LABELS = {
    "VIX_Close": "VIX Close",
    "ATR_Pct": "ATR %",
    "Realized_Vol_5D": "RV 5D",
    "VIX_IVR": "VIX IVR",
    "VIX_IVP": "VIX IVP",
    "RSI_14": "RSI 14",
    "Price_vs_SMA50_Pct": "SMA50 %",
    "Return_5D": "Ret 5D",
    "Gap_Pct": "Gap %",
    "Prev_Return_Pct": "Prev Ret",
    "Gap_Filled": "Gap Fill",
    "Month": "Month",
    "Is_Opex": "OpEx",
    "VIX9D_VIX_Ratio": "VIX9D/VIX",
    "Term_Structure_State": "Term Str",
    "VIX_Gap_Pct": "VIX Gap",
    "VIX_Spike_Pct": "VIX Spike",
    "SLR": "SLR",
    "premium_per_contract": "Prem/K",
    "margin_per_contract": "Margin/K",
    "rom_pct": "RoR %",
}

# ── Group short names for headers ─────────────────────────────────────────────
GROUP_SHORT = {
    "A: Volatility Level": "A: VOL LEVEL",
    "B: Relative Volatility": "B: REL VOL",
    "C: Momentum / Trend": "C: MOMENTUM",
    "D: Daily Price Action": "D: PRICE ACTION",
    "E: Calendar": "E: CALENDAR",
    "F: Term Structure": "F: TERM STR",
    "G: VIX Event": "G: VIX EVENT",
    "H: Premium & Structure": "H: PREMIUM",
    "OUTCOME": "OUTCOME",
}

GROUP_COLORS_MAP = {
    "A: Volatility Level": "#e67e22",
    "B: Relative Volatility": "#9b59b6",
    "C: Momentum / Trend": "#2ecc71",
    "D: Daily Price Action": "#3498db",
    "E: Calendar": "#1abc9c",
    "F: Term Structure": "#e74c3c",
    "G: VIX Event": "#f39c12",
    "H: Premium & Structure": "#95a5a6",
    "OUTCOME": "#dd4466",
}

GROUP_ORDER = [
    "A: Volatility Level",
    "B: Relative Volatility",
    "C: Momentum / Trend",
    "D: Daily Price Action",
    "E: Calendar",
    "F: Term Structure",
    "G: VIX Event",
    "H: Premium & Structure",
]


def read_csv_file(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def safe_float(v):
    if v is None or v == "":
        return None
    try:
        return round(float(v), 4)
    except (ValueError, TypeError):
        return None


def nice_ticks(lo, hi, n=7):
    """Generate ~n nice ticks between lo and hi."""
    rng = hi - lo
    if rng <= 0:
        return [lo]
    raw_step = rng / n
    mag = 10 ** math.floor(math.log10(raw_step))
    residual = raw_step / mag
    if residual <= 1.5:
        step = 1 * mag
    elif residual <= 3:
        step = 2 * mag
    elif residual <= 7:
        step = 5 * mag
    else:
        step = 10 * mag
    start = math.ceil(lo / step) * step
    ticks = []
    v = start
    while v <= hi + step * 0.01:
        ticks.append(round(v, 10))
        v += step
    return ticks


def generate(config):
    """
    Generate filter_parallel_coords.html for the given block.

    Config keys:
        block_folder  (str): Absolute path to the block folder
        block_name    (str): Display name for title/subtitle
        groups_csv    (str, optional): Override path to entry_filter_groups CSV
    """
    block_folder = config['block_folder']
    block_name = config['block_name']
    groups_csv = config.get('groups_csv', GROUPS_CSV_DEFAULT)

    data_csv = os.path.join(block_folder, "alex-tradeblocks-ref", "entry_filter_data.csv")
    out_html = os.path.join(block_folder, "filter_parallel_coords.html")

    # ── Load filter groups ────────────────────────────────────────────────────
    groups_rows = read_csv_file(groups_csv)

    # ── Load trade data first to check for uninformative axes ────────────────
    trades = read_csv_file(data_csv)
    N = len(trades)

    # Build ordered axis list from groups CSV
    axes_spec = []
    skipped_axes = []
    for r in groups_rows:
        report_v1 = r.get("Report V1", "").strip().upper()
        csv_col = r.get("CSV Column", "").strip()
        if report_v1 != "TRUE" or not csv_col:
            continue

        # Dynamic uninformative axis detection: skip if all trades have same value
        vals = set()
        for t in trades:
            v = t.get(csv_col, "").strip()
            if v and v.lower() not in ("null", "none", ""):
                vals.add(v)
        if len(vals) <= 1:
            label = r.get("Filter", csv_col).strip()
            only_val = next(iter(vals)) if vals else "N/A"
            skipped_axes.append(f"{label} (all = {only_val})")
            continue

        axes_spec.append({
            "csv_col": csv_col,
            "group": r.get("Entry Group", "").strip(),
            "index": int(r.get("Index", 999)),
            "filter_type": r.get("Filter Type", "continuous").strip(),
        })

    # Sort by group order then index
    group_rank = {g: i for i, g in enumerate(GROUP_ORDER)}
    axes_spec.sort(key=lambda a: (group_rank.get(a["group"], 99), a["index"]))

    # Append rom_pct as final OUTCOME axis
    axes_spec.append({
        "csv_col": "rom_pct",
        "group": "OUTCOME",
        "index": 999,
        "filter_type": "continuous",
    })

    # Extract columns needed
    axis_keys = [a["csv_col"] for a in axes_spec]

    # Build columnar data
    D = {}
    for key in axis_keys:
        vals = []
        for row in trades:
            vals.append(safe_float(row.get(key, "")))
        D[key] = vals

    # Extract year from date_opened for color-by-year
    years = []
    months_from_date = []
    for row in trades:
        d = row.get("date_opened", "")
        try:
            years.append(int(d[:4]))
            months_from_date.append(int(d[5:7]))
        except (ValueError, IndexError):
            years.append(None)
            months_from_date.append(None)
    D["_year"] = years
    D["_month_date"] = months_from_date

    # ── Build DIMS config ─────────────────────────────────────────────────────
    dims_js = []
    for a in axes_spec:
        key = a["csv_col"]
        ft = a["filter_type"]
        label = SHORT_LABELS.get(key, key)
        group = a["group"]
        group_short = GROUP_SHORT.get(group, group.upper())
        color = GROUP_COLORS_MAP.get(group, "#888888")
        vals = [v for v in D[key] if v is not None]

        if ft == "binary":
            dim = {
                "key": key, "label": label, "group": group_short, "color": color,
                "domain": [-0.2, 1.2],
                "ticks": [0, 1],
                "fmtType": "binary",
            }
        elif ft == "categorical" and key == "Term_Structure_State":
            dim = {
                "key": key, "label": label, "group": group_short, "color": color,
                "domain": [-1.4, 1.4],
                "ticks": [-1, 0, 1],
                "fmtType": "ts",
            }
        elif key == "Month":
            dim = {
                "key": key, "label": label, "group": group_short, "color": color,
                "domain": [0.5, 12.5],
                "ticks": list(range(1, 13)),
                "fmtType": "month",
            }
        elif key == "rom_pct":
            vmin = min(vals) if vals else -30
            vmax = max(vals) if vals else 60
            pad = max((vmax - vmin) * 0.05, 2)
            lo_d = round(vmin - pad, 2)
            hi_d = round(vmax + pad, 2)
            ticks = nice_ticks(lo_d, hi_d, 8)
            dim = {
                "key": key, "label": label, "group": group_short, "color": color,
                "domain": [lo_d, hi_d],
                "ticks": ticks,
                "fmtType": "ror",
            }
        else:
            # continuous
            if not vals:
                vmin, vmax = 0, 1
            else:
                vmin, vmax = min(vals), max(vals)
            pad = (vmax - vmin) * 0.05 if vmax > vmin else 0.5
            lo_d = round(vmin - pad, 4)
            hi_d = round(vmax + pad, 4)
            ticks = nice_ticks(lo_d, hi_d, 7)
            dim = {
                "key": key, "label": label, "group": group_short, "color": color,
                "domain": [lo_d, hi_d],
                "ticks": ticks,
                "fmtType": "num",
            }
        dims_js.append(dim)

    # Compute LO / HI for RoR color scale
    ror_vals = [v for v in D["rom_pct"] if v is not None]
    LO = round(min(ror_vals), 2) if ror_vals else -30
    HI = round(max(ror_vals), 2) if ror_vals else 60

    # ── Serialize data for JS ─────────────────────────────────────────────────
    data_json = json.dumps(D, separators=(",", ":"))
    dims_json = json.dumps(dims_js, separators=(",", ":"))

    # ── Build HTML ────────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Entry Filter Parallel Coordinates -- {block_name}</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#0f1117; color:#e8ecff; font-family:'Segoe UI',Helvetica,Arial,sans-serif; overflow-x:auto; }}
#title-bar {{ text-align:center; padding:14px 0 4px; }}
#title-bar h1 {{ font-size:18px; font-weight:700; color:#e8ecff; letter-spacing:0.5px; }}
#title-bar .sub {{ font-size:12px; color:#8899bb; margin-top:2px; }}
#controls {{ display:flex; align-items:center; justify-content:center; gap:24px; padding:6px 0 8px; }}
#controls label {{ color:#8899bb; font-size:12px; }}
#controls select, #controls input[type=range] {{ background:#1a1d28; border:1px solid #334; color:#e8ecff; border-radius:4px; padding:2px 6px; font-size:12px; }}
#controls button {{ background:#1a1d28; border:1px solid #445; color:#8899bb; border-radius:4px; padding:3px 12px; font-size:12px; cursor:pointer; }}
#controls button:hover {{ color:#e8ecff; border-color:#667; }}
#chart-wrap {{ position:relative; width:1800px; margin:0 auto; }}
#cvs, #pc {{ position:absolute; top:0; left:0; }}
#pc {{ pointer-events:none; }}
#pc .axis-g {{ pointer-events:all; }}
#stats-bar {{ width:1800px; margin:0 auto; background:#12151f; border-top:1px solid #222; padding:8px 24px; display:flex; gap:28px; align-items:center; justify-content:center; font-family:'Courier New',monospace; font-size:13px; }}
#stats-bar .sl {{ color:#8899bb; }}
#stats-bar .sv {{ color:#e8ecff; font-weight:600; }}
#filter-table-wrap {{ width:1800px; margin:0 auto; padding:12px 24px 20px; display:none; }}
#filter-table-wrap h3 {{ font-size:12px; color:#8899bb; font-weight:600; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:8px; }}
#filter-table {{ width:100%; border-collapse:collapse; background:#12151f; border-radius:8px; overflow:hidden; }}
#filter-table thead th {{ background:#161b28; padding:8px 12px; text-align:center; font-size:10px; color:#6677aa; text-transform:uppercase; letter-spacing:0.5px; font-weight:600; border-bottom:1px solid #222; }}
#filter-table thead th:first-child {{ text-align:left; }}
#filter-table tbody td {{ padding:7px 12px; text-align:center; font-size:12px; color:#e8ecff; font-weight:500; border-bottom:1px solid rgba(255,255,255,0.04); font-family:'Courier New',monospace; }}
#filter-table tbody td:first-child {{ text-align:left; font-family:'Segoe UI',sans-serif; }}
#filter-table tbody td.grp {{ color:#8899bb; font-size:11px; }}
#filter-table tbody td.pos {{ color:#2ecc71; }}
#filter-table tbody td.neg {{ color:#e74c3c; }}
#filter-table tfoot td {{ padding:8px 12px; font-size:12px; font-weight:700; border-top:2px solid #334; font-family:'Courier New',monospace; }}
#filter-table tfoot td:first-child {{ font-family:'Segoe UI',sans-serif; color:#f39c12; }}
</style>
</head>
<body>

<div id="title-bar">
  <h1>Entry Filter Parallel Coordinates &mdash; {block_name}</h1>
  <div class="sub"><span id="tradeCount">{N}</span> trades</div>
</div>

<div id="controls">
  <label>Opacity <input type="range" id="opSlider" min="5" max="100" value="30" style="width:120px;vertical-align:middle;"></label>
  <label>Color by
    <select id="colorBy">
      <option value="ror" selected>RoR</option>
      <option value="year">Year</option>
      <option value="month">Month</option>
      <option value="ts">Term Structure</option>
    </select>
  </label>
  <button id="resetBtn">Reset All</button>
</div>

<div id="chart-wrap" style="height:700px;">
  <canvas id="cvs" width="1800" height="700"></canvas>
  <svg id="pc" width="1800" height="700"></svg>
</div>

<div id="stats-bar">
  <span><span class="sl">N: </span><span class="sv" id="sN">{N}</span></span>
  <span><span class="sl">% of Total: </span><span class="sv" id="sPct">100.0%</span></span>
  <span><span class="sl">Avg RoR: </span><span class="sv" id="sRor">--</span></span>
  <span><span class="sl">Win Rate: </span><span class="sv" id="sWr">--</span></span>
  <span><span class="sl">Profit Factor: </span><span class="sv" id="sPf">--</span></span>
  <span><span class="sl">Net RoR Retained: </span><span class="sv" id="sNet">100.0%</span></span>
</div>

<div id="filter-table-wrap">
  <h3>Active Brush Filters</h3>
  <table id="filter-table">
    <thead>
      <tr>
        <th style="min-width:120px;">Filter</th>
        <th>Group</th>
        <th>Range</th>
        <th>Avg RoR %</th>
        <th>vs Baseline</th>
        <th>Win Rate</th>
        <th>Profit Factor</th>
        <th>% Net RoR</th>
        <th>Trades</th>
        <th>% Kept</th>
      </tr>
    </thead>
    <tbody id="filter-table-body"></tbody>
    <tfoot id="filter-table-foot"></tfoot>
  </table>
</div>

<script>
// ── Data ─────────────────────────────────────────────────────────────────────
const D = {data_json};
const DIMS = {dims_json};
const TOTAL = {N};
const LO = {LO};
const HI = {HI};

// ── Transpose to rows ────────────────────────────────────────────────────────
const rows = [];
for (let i = 0; i < TOTAL; i++) {{
  const r = {{}};
  for (const k of Object.keys(D)) r[k] = D[k][i];
  rows.push(r);
}}

// ── Layout ───────────────────────────────────────────────────────────────────
const W = 1800, H = 700;
const M = {{ top: 90, bottom: 30, left: 48, right: 80 }};

// ── Scales ───────────────────────────────────────────────────────────────────
const xScale = d3.scalePoint()
  .domain(DIMS.map(d => d.key))
  .range([M.left, W - M.right]);

const yScales = {{}};
DIMS.forEach(d => {{
  yScales[d.key] = d3.scaleLinear()
    .domain(d.domain)
    .range([H - M.bottom, M.top]);
}});

// ── Formatters ───────────────────────────────────────────────────────────────
const MONTH_NAMES = ['','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
function fmtTick(dim, v) {{
  switch(dim.fmtType) {{
    case 'binary': return v === 0 ? 'No' : v === 1 ? 'Yes' : '';
    case 'ts': return ({{'-1':'Back','0':'Flat','1':'Cont'}})[String(Math.round(v))] || '';
    case 'month': return MONTH_NAMES[Math.round(v)] || '';
    case 'ror': return (v >= 0 ? '+' : '') + v.toFixed(1) + '%';
    default: return Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2);
  }}
}}

// ── Color scales ─────────────────────────────────────────────────────────────
function rorColor(v) {{
  if (v == null) return 'rgb(80,80,105)';
  const t = Math.max(0, Math.min(1, (v - LO) / (HI - LO)));
  if (t < 0.45) {{
    const s = t / 0.45;
    return `rgb(${{Math.round(190-60*s)}}, ${{Math.round(45+20*s)}}, ${{Math.round(45+20*s)}})`;
  }} else if (t < 0.55) {{
    return 'rgb(80,80,105)';
  }} else {{
    const s = (t - 0.55) / 0.45;
    return `rgb(${{Math.round(40+30*s)}}, ${{Math.round(160+80*s)}}, ${{Math.round(100+30*s)}})`;
  }}
}}
const YEAR_COLORS = {{2022:'#8855ee',2023:'#33aaee',2024:'#33dd99',2025:'#ddcc33',2026:'#ff7733'}};
function yearColor(v) {{ return YEAR_COLORS[v] || '#888'; }}
function monthColor(v) {{ return `hsl(${{(v-1)/11*240}}, 60%, 55%)`; }}
const TS_COLORS = {{'-1':'#ee5533','0':'#8899aa','1':'#33aaee'}};
function tsColor(v) {{ return TS_COLORS[String(Math.round(v))] || '#888'; }}

function getColor(row) {{
  const mode = document.getElementById('colorBy').value;
  switch(mode) {{
    case 'year': return yearColor(row._year);
    case 'month': return monthColor(row._month_date);
    case 'ts': return tsColor(row.Term_Structure_State);
    default: return rorColor(row.rom_pct);
  }}
}}

// ── Brush state ──────────────────────────────────────────────────────────────
const brushState = {{}};
DIMS.forEach(d => brushState[d.key] = null);

function isSelected(row) {{
  for (const key of Object.keys(brushState)) {{
    const b = brushState[key];
    if (b === null) continue;
    const v = row[key];
    if (v == null) return false;
    if (v < b[0] || v > b[1]) return false;
  }}
  return true;
}}

// ── Canvas drawing ───────────────────────────────────────────────────────────
const cvs = document.getElementById('cvs');
const ctx = cvs.getContext('2d');

function drawLines() {{
  ctx.clearRect(0, 0, W, H);
  const op = parseInt(document.getElementById('opSlider').value) / 100;
  const hasBrush = Object.values(brushState).some(v => v !== null);

  if (hasBrush) {{
    ctx.globalAlpha = 0.04;
    ctx.lineWidth = 0.8;
    for (const row of rows) {{
      if (!isSelected(row)) drawLine(row);
    }}
    ctx.globalAlpha = op;
    ctx.lineWidth = 1.2;
    for (const row of rows) {{
      if (isSelected(row)) drawLine(row);
    }}
  }} else {{
    ctx.globalAlpha = op;
    ctx.lineWidth = 1;
    for (const row of rows) drawLine(row);
  }}
  ctx.globalAlpha = 1;
}}

function drawLine(row) {{
  ctx.strokeStyle = getColor(row);
  ctx.beginPath();
  let started = false;
  for (const dim of DIMS) {{
    const v = row[dim.key];
    if (v == null) {{ started = false; continue; }}
    const x = xScale(dim.key);
    const y = yScales[dim.key](v);
    if (!started) {{ ctx.moveTo(x, y); started = true; }}
    else ctx.lineTo(x, y);
  }}
  ctx.stroke();
}}

// ── SVG axes & labels ────────────────────────────────────────────────────────
const svg = d3.select('#pc');

// Group headers
const groups = [];
let curGroup = null;
DIMS.forEach((d, i) => {{
  if (d.group !== (curGroup && curGroup.name)) {{
    curGroup = {{ name: d.group, color: d.color, startX: xScale(d.key), endX: xScale(d.key), startIdx: i }};
    groups.push(curGroup);
  }} else {{
    curGroup.endX = xScale(d.key);
  }}
}});

groups.forEach(g => {{
  const cx = (g.startX + g.endX) / 2;
  svg.append('text')
    .attr('x', cx).attr('y', M.top - 28)
    .attr('text-anchor', 'middle')
    .attr('fill', g.color)
    .attr('font-size', '10.5px')
    .attr('font-weight', '700')
    .attr('letter-spacing', '1px')
    .text(g.name);
  svg.append('line')
    .attr('x1', g.startX - 10).attr('x2', g.endX + 10)
    .attr('y1', M.top - 22).attr('y2', M.top - 22)
    .attr('stroke', g.color).attr('stroke-width', 2).attr('opacity', 0.6);
}});

// Axis lines, labels, ticks
DIMS.forEach((dim, di) => {{
  const x = xScale(dim.key);
  const g = svg.append('g').attr('class', 'axis-g').attr('data-key', dim.key);

  // Axis line
  g.append('line')
    .attr('x1', x).attr('x2', x)
    .attr('y1', M.top).attr('y2', H - M.bottom)
    .attr('stroke', '#334').attr('stroke-width', 1);

  // Label
  g.append('text')
    .attr('x', x).attr('y', M.top - 6)
    .attr('text-anchor', 'middle')
    .attr('fill', '#e8ecff')
    .attr('font-size', '12.5px')
    .attr('font-weight', '700')
    .text(dim.label);

  // Ticks - alternate sides
  const side = di % 2 === 0 ? -1 : 1;
  dim.ticks.forEach(tv => {{
    const y = yScales[dim.key](tv);
    if (y < M.top - 2 || y > H - M.bottom + 2) return;
    g.append('line')
      .attr('x1', x - 3).attr('x2', x + 3)
      .attr('y1', y).attr('y2', y)
      .attr('stroke', '#445').attr('stroke-width', 1);
    g.append('text')
      .attr('x', x + side * 8)
      .attr('y', y + 3)
      .attr('text-anchor', side < 0 ? 'end' : 'start')
      .attr('fill', '#6677aa')
      .attr('font-size', '9px')
      .text(fmtTick(dim, tv));
  }});

  // Brush interaction
  const brushWidth = 28;
  const brushG = g.append('g').attr('class', 'brush-g');

  const hitArea = g.append('rect')
    .attr('x', x - brushWidth/2).attr('y', M.top)
    .attr('width', brushWidth).attr('height', H - M.top - M.bottom)
    .attr('fill', 'transparent')
    .attr('cursor', 'crosshair');

  let brushRect = null;
  let brushing = false;
  let brushStartY = 0;

  hitArea.on('mousedown', function(event) {{
    event.preventDefault();
    brushing = true;
    brushStartY = event.offsetY;
    brushG.selectAll('rect').remove();
    brushRect = brushG.append('rect')
      .attr('x', x - brushWidth/2 + 2)
      .attr('width', brushWidth - 4)
      .attr('rx', 3)
      .attr('fill', dim.color)
      .attr('fill-opacity', 0.2)
      .attr('stroke', dim.color)
      .attr('stroke-opacity', 0.6)
      .attr('stroke-width', 1);

    function onMove(e) {{
      if (!brushing) return;
      const curY = e.offsetY;
      const y1 = Math.max(M.top, Math.min(brushStartY, curY));
      const y2 = Math.min(H - M.bottom, Math.max(brushStartY, curY));
      brushRect.attr('y', y1).attr('height', y2 - y1);
    }}

    function onUp(e) {{
      if (!brushing) return;
      brushing = false;
      const curY = e.offsetY;
      const y1 = Math.max(M.top, Math.min(brushStartY, curY));
      const y2 = Math.min(H - M.bottom, Math.max(brushStartY, curY));
      if (y2 - y1 < 3) {{
        brushG.selectAll('rect').remove();
        brushState[dim.key] = null;
      }} else {{
        const scale = yScales[dim.key];
        const dataHi = scale.invert(y1);
        const dataLo = scale.invert(y2);
        brushState[dim.key] = [dataLo, dataHi];
      }}
      drawLines();
      updateStats();
      updateBoxPlot();
      updateFilterTable();
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    }}

    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }});

  hitArea.on('dblclick', function() {{
    brushG.selectAll('rect').remove();
    brushState[dim.key] = null;
    drawLines();
    updateStats();
    updateBoxPlot();
    updateFilterTable();
  }});
}});

// ── Stats ────────────────────────────────────────────────────────────────────
function updateStats() {{
  const hasBrush = Object.values(brushState).some(v => v !== null);
  const subset = hasBrush ? rows.filter(isSelected) : rows;
  const n = subset.length;
  const rs = subset.map(r => r.rom_pct).filter(v => v != null);
  const ws = rs.filter(r => r > 0);
  const ls = rs.filter(r => r < 0);
  const avg = rs.length ? rs.reduce((a,b) => a+b, 0) / rs.length : 0;
  const wr = rs.length ? ws.length / rs.length * 100 : 0;
  const grossW = ws.length ? ws.reduce((a,b) => a+b, 0) : 0;
  const grossL = ls.length ? Math.abs(ls.reduce((a,b) => a+b, 0)) : 0;
  const pf = grossL > 0 ? grossW / grossL : 999;
  const pct = n / TOTAL * 100;

  const netRor = rs.reduce((a,b) => a+b, 0);
  const netPct = baselineNetRor !== 0 ? (netRor / baselineNetRor * 100) : 0;

  document.getElementById('sN').textContent = n.toLocaleString();
  document.getElementById('sPct').textContent = pct.toFixed(1) + '%';
  document.getElementById('sRor').textContent = (avg >= 0 ? '+' : '') + avg.toFixed(2) + '%';
  document.getElementById('sWr').textContent = wr.toFixed(1) + '%';
  document.getElementById('sPf').textContent = pf > 99 ? '>99' : pf.toFixed(2);
  document.getElementById('sNet').textContent = netPct.toFixed(1) + '%';
}}

// ── Baseline metrics ─────────────────────────────────────────────────────
const baselineRors = rows.map(r => r.rom_pct).filter(v => v != null).sort((a,b) => a-b);
const baselineAvg = baselineRors.reduce((a,b) => a+b, 0) / baselineRors.length;
const baselineNetRor = baselineRors.reduce((a,b) => a+b, 0);

// ── Box plot on RoR axis ────────────────────────────────────────────────
const rorKey = 'rom_pct';
const rorX = xScale(rorKey);
const rorScale = yScales[rorKey];
const bpOffsetAll = 22;
const bpOffsetSel = 44;
const bpWidth = 12;

function quartiles(arr) {{
  const s = arr.slice().sort((a,b) => a-b);
  const n = s.length;
  if (n === 0) return null;
  const q1 = s[Math.floor(n * 0.25)];
  const med = s[Math.floor(n * 0.5)];
  const q3 = s[Math.floor(n * 0.75)];
  const iqr = q3 - q1;
  const wLo = Math.max(s[0], q1 - 1.5 * iqr);
  const wHi = Math.min(s[n-1], q3 + 1.5 * iqr);
  return {{ q1, med, q3, wLo, wHi, min: s[0], max: s[n-1] }};
}}

// Full dataset box plot
const bpAll = svg.append('g').attr('class','bp-all');
const fullQ = quartiles(baselineRors);
if (fullQ) {{
  const cx = rorX + bpOffsetAll;
  bpAll.append('line')
    .attr('x1', cx).attr('x2', cx)
    .attr('y1', rorScale(fullQ.wHi)).attr('y2', rorScale(fullQ.wLo))
    .attr('stroke', '#556').attr('stroke-width', 1);
  [fullQ.wLo, fullQ.wHi].forEach(v => {{
    bpAll.append('line')
      .attr('x1', cx - 4).attr('x2', cx + 4)
      .attr('y1', rorScale(v)).attr('y2', rorScale(v))
      .attr('stroke', '#556').attr('stroke-width', 1);
  }});
  bpAll.append('rect')
    .attr('x', cx - bpWidth/2).attr('width', bpWidth)
    .attr('y', rorScale(fullQ.q3)).attr('height', rorScale(fullQ.q1) - rorScale(fullQ.q3))
    .attr('fill', 'rgba(80,80,105,0.25)')
    .attr('stroke', '#556').attr('stroke-width', 1)
    .attr('rx', 2);
  bpAll.append('line')
    .attr('x1', cx - bpWidth/2).attr('x2', cx + bpWidth/2)
    .attr('y1', rorScale(fullQ.med)).attr('y2', rorScale(fullQ.med))
    .attr('stroke', '#8899bb').attr('stroke-width', 1.5);
}}

// Filtered subset box plot
const bpSel = svg.append('g').attr('class','bp-sel');

function updateBoxPlot() {{
  bpSel.selectAll('*').remove();
  const hasBrush = Object.values(brushState).some(v => v !== null);
  if (!hasBrush) return;

  const subset = rows.filter(isSelected).map(r => r.rom_pct).filter(v => v != null);
  if (subset.length < 4) return;

  const q = quartiles(subset);
  if (!q) return;

  const cx = rorX + bpOffsetSel;
  bpSel.append('line')
    .attr('x1', cx).attr('x2', cx)
    .attr('y1', rorScale(q.wHi)).attr('y2', rorScale(q.wLo))
    .attr('stroke', '#dd4466').attr('stroke-width', 1.5);
  [q.wLo, q.wHi].forEach(v => {{
    bpSel.append('line')
      .attr('x1', cx - 5).attr('x2', cx + 5)
      .attr('y1', rorScale(v)).attr('y2', rorScale(v))
      .attr('stroke', '#dd4466').attr('stroke-width', 1.5);
  }});
  bpSel.append('rect')
    .attr('x', cx - bpWidth/2).attr('width', bpWidth)
    .attr('y', rorScale(q.q3)).attr('height', Math.max(1, rorScale(q.q1) - rorScale(q.q3)))
    .attr('fill', 'rgba(221,68,102,0.25)')
    .attr('stroke', '#dd4466').attr('stroke-width', 1.5)
    .attr('rx', 2);
  bpSel.append('line')
    .attr('x1', cx - bpWidth/2).attr('x2', cx + bpWidth/2)
    .attr('y1', rorScale(q.med)).attr('y2', rorScale(q.med))
    .attr('stroke', '#ff6688').attr('stroke-width', 2);
  const mean = subset.reduce((a,b) => a+b, 0) / subset.length;
  bpSel.append('circle')
    .attr('cx', cx).attr('cy', rorScale(mean)).attr('r', 3)
    .attr('fill', '#ff6688').attr('stroke', '#0f1117').attr('stroke-width', 1);
}}

// ── Filter table update ─────────────────────────────────────────────────
const dimLookup = {{}};
DIMS.forEach(d => dimLookup[d.key] = {{ label: d.label, group: d.group, fmtType: d.fmtType }});

function fmtRange(key, lo, hi) {{
  const d = dimLookup[key];
  if (!d) return lo.toFixed(2) + ' - ' + hi.toFixed(2);
  if (d.fmtType === 'binary') return (lo <= 0.5 && hi >= 0.5) ? 'Both' : (hi < 0.5 ? 'No' : 'Yes');
  if (d.fmtType === 'ts') {{
    const ts = {{'1':'Cont','0':'Flat','-1':'Back'}};
    const lo_r = Math.round(lo), hi_r = Math.round(hi);
    if (lo_r === hi_r) return ts[String(lo_r)] || lo_r;
    return (ts[String(lo_r)] || lo_r) + ' - ' + (ts[String(hi_r)] || hi_r);
  }}
  if (d.fmtType === 'month') {{
    const mn = ['','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return mn[Math.max(1,Math.round(lo))] + ' - ' + mn[Math.min(12,Math.round(hi))];
  }}
  if (d.fmtType === 'ror') return lo.toFixed(1) + '% - ' + hi.toFixed(1) + '%';
  if (Math.abs(lo) >= 100 || Math.abs(hi) >= 100) return lo.toFixed(0) + ' - ' + hi.toFixed(0);
  return lo.toFixed(2) + ' - ' + hi.toFixed(2);
}}

function updateFilterTable() {{
  const wrap = document.getElementById('filter-table-wrap');
  const tbody = document.getElementById('filter-table-body');
  const tfoot = document.getElementById('filter-table-foot');
  const activeKeys = Object.keys(brushState).filter(k => brushState[k] !== null);

  if (activeKeys.length === 0) {{
    wrap.style.display = 'none';
    return;
  }}
  wrap.style.display = 'block';

  const combined = rows.filter(isSelected);
  const cRors = combined.map(r => r.rom_pct).filter(v => v != null);
  const cAvg = cRors.length ? cRors.reduce((a,b) => a+b, 0) / cRors.length : 0;
  const cWs = cRors.filter(r => r > 0);
  const cLs = cRors.filter(r => r < 0);
  const cWr = cRors.length ? cWs.length / cRors.length * 100 : 0;
  const cGrossW = cWs.length ? cWs.reduce((a,b) => a+b, 0) : 0;
  const cGrossL = cLs.length ? Math.abs(cLs.reduce((a,b) => a+b, 0)) : 0;
  const cPf = cGrossL > 0 ? cGrossW / cGrossL : 999;

  let html = '';
  for (const key of activeKeys) {{
    const [lo, hi] = brushState[key];
    const d = dimLookup[key] || {{ label: key, group: '--', fmtType: 'num' }};

    const solo = rows.filter(r => {{
      const v = r[key];
      return v != null && v >= lo && v <= hi;
    }});
    const sRors = solo.map(r => r.rom_pct).filter(v => v != null);
    const sAvg = sRors.length ? sRors.reduce((a,b) => a+b, 0) / sRors.length : 0;
    const sWs = sRors.filter(r => r > 0);
    const sLs = sRors.filter(r => r < 0);
    const sWr = sRors.length ? sWs.length / sRors.length * 100 : 0;
    const sGW = sWs.length ? sWs.reduce((a,b) => a+b, 0) : 0;
    const sGL = sLs.length ? Math.abs(sLs.reduce((a,b) => a+b, 0)) : 0;
    const sPf = sGL > 0 ? sGW / sGL : 999;
    const delta = sAvg - baselineAvg;
    const deltaCls = delta >= 2 ? 'pos' : (delta <= -2 ? 'neg' : '');
    const pctKept = (sRors.length / TOTAL * 100).toFixed(1);
    const sNetRor = sRors.reduce((a,b) => a+b, 0);
    const sNetPct = baselineNetRor !== 0 ? (sNetRor / baselineNetRor * 100).toFixed(1) : '--';
    const sNetCls = sNetRor >= baselineNetRor * 0.8 ? 'pos' : (sNetRor < baselineNetRor * 0.5 ? 'neg' : '');

    html += '<tr>';
    html += '<td>' + d.label + '</td>';
    html += '<td class="grp">' + d.group + '</td>';
    html += '<td>' + fmtRange(key, lo, hi) + '</td>';
    html += '<td>' + sAvg.toFixed(2) + '%</td>';
    html += '<td class="' + deltaCls + '">' + (delta >= 0 ? '+' : '') + delta.toFixed(1) + 'pp</td>';
    html += '<td>' + sWr.toFixed(1) + '%</td>';
    html += '<td>' + (sPf > 99 ? '>99' : sPf.toFixed(2)) + '</td>';
    html += '<td class="' + sNetCls + '">' + sNetPct + '%</td>';
    html += '<td>' + sRors.length + '</td>';
    html += '<td>' + pctKept + '%</td>';
    html += '</tr>';
  }}
  tbody.innerHTML = html;

  const cDelta = cAvg - baselineAvg;
  const cDeltaCls = cDelta >= 2 ? 'pos' : (cDelta <= -2 ? 'neg' : '');
  const cPctKept = (cRors.length / TOTAL * 100).toFixed(1);
  const cNetRor = cRors.reduce((a,b) => a+b, 0);
  const cNetPct = baselineNetRor !== 0 ? (cNetRor / baselineNetRor * 100).toFixed(1) : '--';
  const cNetCls = cNetRor >= baselineNetRor * 0.8 ? 'pos' : (cNetRor < baselineNetRor * 0.5 ? 'neg' : '');
  let foot = '<tr>';
  foot += '<td>Combined (' + activeKeys.length + ' filters)</td>';
  foot += '<td style="text-align:center"></td>';
  foot += '<td style="text-align:center"></td>';
  foot += '<td style="text-align:center;color:#e8ecff">' + cAvg.toFixed(2) + '%</td>';
  foot += '<td style="text-align:center" class="' + cDeltaCls + '">' + (cDelta >= 0 ? '+' : '') + cDelta.toFixed(1) + 'pp</td>';
  foot += '<td style="text-align:center;color:#e8ecff">' + cWr.toFixed(1) + '%</td>';
  foot += '<td style="text-align:center;color:#e8ecff">' + (cPf > 99 ? '>99' : cPf.toFixed(2)) + '</td>';
  foot += '<td style="text-align:center" class="' + cNetCls + '">' + cNetPct + '%</td>';
  foot += '<td style="text-align:center;color:#e8ecff">' + cRors.length + '</td>';
  foot += '<td style="text-align:center;color:#e8ecff">' + cPctKept + '%</td>';
  foot += '</tr>';
  tfoot.innerHTML = foot;
}}

// ── Controls ─────────────────────────────────────────────────────────────────
document.getElementById('opSlider').addEventListener('input', () => {{ drawLines(); }});
document.getElementById('colorBy').addEventListener('change', () => {{ drawLines(); }});
document.getElementById('resetBtn').addEventListener('click', () => {{
  DIMS.forEach(d => brushState[d.key] = null);
  svg.selectAll('.brush-g rect').remove();
  drawLines();
  updateStats();
  updateBoxPlot();
  updateFilterTable();
}});

// ── Init ─────────────────────────────────────────────────────────────────────
drawLines();
updateStats();
</script>
</body>
</html>"""

    with open(out_html, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Written: {out_html}")
    print(f"  {N} trades, {len(dims_js)} axes, RoR range [{LO}, {HI}]")
    if skipped_axes:
        print(f"  Skipped uninformative axes: {', '.join(skipped_axes)}")
    return out_html


# Allow direct execution for testing
if __name__ == "__main__":
    print("This module is meant to be imported. Use a block-specific wrapper script.")
    print("Example wrapper:")
    print('    from build_parallel_coords import generate')
    print('    generate({"block_folder": "/path/to/block", "block_name": "My Block"})')
