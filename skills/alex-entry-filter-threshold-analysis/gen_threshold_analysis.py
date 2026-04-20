#!/usr/bin/env python3
"""
alex-entry-filter-threshold-analysis — CLI driver.

Generates an interactive threshold-analysis HTML report for a single entry filter
on a block. Reads only two block-local CSVs; never builds data itself.

    python3 gen_threshold_analysis.py BLOCK_ID [FILTER] \\
        [--tb-root PATH] \\
        [--groups-csv PATH] \\
        [--filter-by "COLUMN=VALUE"] \\
        [--list]

Inputs (both block-local):
    {block}/alex-tradeblocks-ref/entry_filter_data.csv
    {block}/alex-tradeblocks-ref/entry_filter_groups.*.csv

Output:
    {block}/entry filter threshold analysis [<Short Name>].html

See SKILL.md for the full workflow and exit-code conventions.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import pathlib
import re
import sys
from typing import Optional, Tuple, List, Dict

import numpy as np


TB_ROOT_DEFAULT = "/Users/alexanderhardt/Library/CloudStorage/OneDrive-AIACOTechnology/Documents - AIACO Trading Development/Pipeline Data/TradeBlocks Data"

# Exit codes — documented in SKILL.md so the invoker can react.
EXIT_OK = 0
EXIT_MISSING_DATA_CSV = 2
EXIT_MISSING_GROUPS_CSV = 3
EXIT_MULTIPLE_GROUPS_CSV = 4
EXIT_NO_FILTER_ARG = 5
EXIT_FILTER_UNRESOLVED = 6
EXIT_SHORT_NAME_EMPTY = 7

REQUIRED_GROUPS_COLS = {"Index", "Filter", "Short Name", "CSV Column", "Entry Group"}


# ── Path resolution ──────────────────────────────────────────────────────────

def resolve_block_folder(tb_root: pathlib.Path, block_id: str) -> pathlib.Path:
    p = tb_root / block_id
    if not p.is_dir():
        raise RuntimeError(f"block folder not found: {p}")
    return p


def resolve_data_csv(ref_folder: pathlib.Path) -> pathlib.Path:
    p = ref_folder / "entry_filter_data.csv"
    if not p.is_file():
        raise FileNotFoundError(
            f"entry_filter_data.csv not found in {ref_folder}.\n"
            f"Run /alex-entry-filter-build-data BLOCK_ID first to build it."
        )
    return p


def resolve_groups_csv(
    ref_folder: pathlib.Path,
    explicit: Optional[pathlib.Path] = None,
) -> Tuple[pathlib.Path, str]:
    """
    Return (path, source_tag).

    Resolution order:
      1. explicit (--groups-csv arg) — must exist.
      2. Single match in block's alex-tradeblocks-ref/entry_filter_groups.*.csv.

    No shared-folder fallback — this skill is strictly block-local. If zero
    matches in the ref folder, the user must first run alex-entry-filter-build-data.
    """
    if explicit is not None:
        if not explicit.is_file():
            raise RuntimeError(f"--groups-csv file not found: {explicit}")
        return explicit.resolve(), "explicit"

    matches = sorted(ref_folder.glob("entry_filter_groups.*.csv"))
    if len(matches) == 0:
        raise FileNotFoundError(
            f"No entry_filter_groups.*.csv in {ref_folder}.\n"
            f"Run /alex-entry-filter-build-data BLOCK_ID first to set up the block ref folder."
        )
    if len(matches) > 1:
        names = ", ".join(m.name for m in matches)
        raise RuntimeError(
            f"Multiple filter-groups files in block ref folder: {names}.\n"
            f"Pass --groups-csv PATH to pick one, or keep only one in the ref folder."
        )
    return matches[0], "block-local"


# ── Groups CSV parsing ───────────────────────────────────────────────────────

def load_groups(path: pathlib.Path) -> List[Dict[str, str]]:
    """Load groups CSV. Validate required columns. Return list of row dicts."""
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        if not reader.fieldnames:
            raise RuntimeError(f"groups CSV has no header: {path}")
        missing = REQUIRED_GROUPS_COLS - set(reader.fieldnames)
        if missing:
            raise RuntimeError(
                f"groups CSV missing required columns: {sorted(missing)}. "
                f"Path: {path}"
            )
    # Normalize whitespace on key columns
    for r in rows:
        for col in REQUIRED_GROUPS_COLS:
            if r.get(col) is not None:
                r[col] = r[col].strip()
    return rows


def list_filters(groups: List[Dict], file=sys.stdout):
    """Print filters grouped by Entry Group, sorted by Index."""
    def _idx(r):
        try:
            return int(r["Index"])
        except (ValueError, TypeError):
            return 10**9
    grouped: Dict[str, List[Dict]] = {}
    for r in groups:
        grouped.setdefault(r.get("Entry Group", "(no group)"), []).append(r)
    print(f"Available filters ({len(groups)}):", file=file)
    for grp in sorted(grouped.keys()):
        print(f"\n  {grp}", file=file)
        for r in sorted(grouped[grp], key=_idx):
            idx = r.get("Index", "?")
            full = r.get("Filter", "")
            short = r.get("Short Name", "")
            col = r.get("CSV Column", "")
            print(f"    {idx:>3} | {full:<32} | {short:<14} | {col}", file=file)


# ── Filter scoping ───────────────────────────────────────────────────────────

def apply_filter_by(groups: List[Dict], expr: Optional[str]) -> List[Dict]:
    """Parse COLUMN=VALUE and narrow groups to matching rows."""
    if not expr:
        return groups
    if "=" not in expr:
        raise RuntimeError(f"--filter-by must be COLUMN=VALUE (got: {expr!r})")
    col, _, val = expr.partition("=")
    col = col.strip()
    val = val.strip()
    if not groups:
        return groups
    if col not in groups[0]:
        available = sorted(groups[0].keys())
        raise RuntimeError(
            f"--filter-by column {col!r} not in groups CSV.\n"
            f"Available columns: {available}"
        )
    val_lower = val.lower()
    narrowed = [r for r in groups if (r.get(col) or "").strip().lower() == val_lower]
    return narrowed


# ── Filter resolution ────────────────────────────────────────────────────────

def resolve_filter(groups: List[Dict], arg: str) -> List[Dict]:
    """
    Return a list of matching rows (0 = unresolved, 1 = unambiguous, >1 = ambiguous).

    Resolution ladder (first ladder step with matches wins):
      1. Exact case-sensitive match on CSV Column
      2. Exact integer match on Index
      3. Exact case-insensitive match on Short Name
      4. Exact case-insensitive match on Filter
      5. Case-insensitive substring contains across Filter + Short Name + CSV Column
    """
    arg = arg.strip()
    # 1. CSV Column (exact, case-sensitive)
    m = [r for r in groups if r.get("CSV Column") == arg]
    if m:
        return m
    # 2. Index (exact int)
    try:
        arg_int = int(arg)
        m = [r for r in groups if (r.get("Index") or "").strip() == str(arg_int)]
        if m:
            return m
    except ValueError:
        pass
    arg_lower = arg.lower()
    # 3. Short Name (exact, case-insensitive)
    m = [r for r in groups if (r.get("Short Name") or "").strip().lower() == arg_lower]
    if m:
        return m
    # 4. Filter (exact, case-insensitive)
    m = [r for r in groups if (r.get("Filter") or "").strip().lower() == arg_lower]
    if m:
        return m
    # 5. Fuzzy substring contains
    m = [
        r for r in groups
        if arg_lower in (r.get("Filter") or "").lower()
        or arg_lower in (r.get("Short Name") or "").lower()
        or arg_lower in (r.get("CSV Column") or "").lower()
    ]
    return m


# ── Filename sanitization ────────────────────────────────────────────────────

_FS_UNSAFE = re.compile(r'[\\<>"|?*]')


def sanitize_short_name_for_filename(name: str) -> str:
    """
    Sanitize Short Name for filesystem use. Slashes read as "over" regardless
    of surrounding spaces (e.g., "VIX O/N" → "VIX O over N", "A / B" → "A over B").
    """
    s = name.strip()
    s = s.replace("/", " over ")
    s = s.replace(":", " -")
    s = _FS_UNSAFE.sub("-", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ── OO Translation JS snippets ──────────────────────────────────────────────

OO_TRANSLATE_SIMPLE = """
function ooFilter(dir, threshold, fieldLabel) {{
    const v = threshold;
    if (dir === '>=') return 'Min ' + fieldLabel + ' = ' + v.toFixed(4);
    else return 'Max ' + fieldLabel + ' = ' + v.toFixed(4);
}}"""

OO_TRANSLATE_VIX_ON = """
function ooFilter(dir, threshold, fieldLabel) {{
    const v = threshold;
    if (dir === '>=') {{
        if (v >= 0) return 'Min O/N Move Up = ' + Math.abs(v).toFixed(2);
        else return 'Max O/N Move Down = ' + Math.abs(v).toFixed(2);
    }} else {{
        if (v >= 0) return 'Max O/N Move Up = ' + Math.abs(v).toFixed(2);
        else return 'Min O/N Move Down = ' + Math.abs(v).toFixed(2);
    }}
}}"""

OO_TRANSLATORS = {
    'simple': OO_TRANSLATE_SIMPLE,
    'vix_on': OO_TRANSLATE_VIX_ON,
}


def _generate(config):
    """Generate threshold analysis HTML from config dict.

    Required keys:
        block_folder, block_name, field_col, field_label, field_slug,
        data_csv, out_html

    Optional keys:
        oo_translate   (str): 'simple' | 'vix_on' | raw JS function. Default 'simple'
        show_zero_x    (bool|None): Force vertical 0-line on/off. None (default)
                                    = auto-detect from data (on if values span 0).
        subtitle_note  (str): Subtitle suffix. Default auto-generated from field_label.
    """
    block_folder  = config['block_folder']
    block_name    = config['block_name']
    field_col     = config['field_col']
    field_label   = config['field_label']
    field_slug    = config['field_slug']
    data_csv      = config['data_csv']
    out_html      = config['out_html']
    oo_translate  = config.get('oo_translate', 'simple')
    show_zero_x   = config.get('show_zero_x', None)  # None = auto-detect
    subtitle_note = config.get('subtitle_note', f'Continuous sweep across all unique {field_label} values')

    # Resolve OO translator JS
    if oo_translate in OO_TRANSLATORS:
        oo_js = OO_TRANSLATORS[oo_translate]
    else:
        oo_js = oo_translate  # assume raw JS string

    # ── Load CSV ─────────────────────────────────────────────────────────────
    with open(data_csv, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        trades = list(reader)

    raw_data = []
    for t in trades:
        v = t.get(field_col, '').strip()
        if v == '' or v.lower() in ('null', 'none'):
            continue
        raw_data.append([
            round(float(v), 4),
            round(float(t['rom_pct']), 4),
            round(float(t['pl_per_contract']), 2)
        ])

    n = len(raw_data)
    if n == 0:
        raise RuntimeError(f"No non-null values for '{field_col}' in {data_csv}")
    vals = np.array([r[0] for r in raw_data])
    roms = np.array([r[1] for r in raw_data])
    pls  = np.array([r[2] for r in raw_data])

    corr = np.corrcoef(vals, roms)[0, 1]
    baseline_rom = roms.mean()
    baseline_net = roms.sum()
    baseline_wr  = (roms > 0).sum() / n * 100
    gp = roms[roms > 0].sum()
    gl = abs(roms[roms < 0].sum())
    baseline_pf = gp / gl if gl > 0 else 99
    baseline_pl = pls.mean()

    slope, intercept = np.polyfit(vals, roms, 1)
    r_squared = corr ** 2

    # Auto-detect show_zero_x if not explicitly set
    if show_zero_x is None:
        show_zero_x = bool(vals.min() < 0 < vals.max())

    print(f"Loaded {n} trades for field '{field_col}'")
    print(f"Correlation with ROM: r = {corr:.4f}, R^2 = {r_squared:.4f}")
    print(f"Range: [{vals.min():.4f}, {vals.max():.4f}]  (0-line: {'ON' if show_zero_x else 'off'})")
    print(f"Baseline: ROM={baseline_rom:.2f}%, Net={baseline_net:.1f}%, WR={baseline_wr:.1f}%, PF={baseline_pf:.2f}")
    print(f"Best fit: y = {slope:.4f}x + {intercept:.4f}")

    raw_json = json.dumps(raw_data)

    # Zero-x annotation JS (injected into annotations object)
    zero_x_thresh = ""
    zero_x_scatter = ""
    if show_zero_x:
        zero_x_thresh = """
    zeroX: {{
        type: 'line', xMin: 0, xMax: 0, xScaleID: 'x',
        borderColor: 'rgba(255,255,255,0.12)', borderWidth: 1, borderDash: [2,2]
    }},"""
        zero_x_scatter = """
    zeroX: {{ type: 'line', xMin: 0, xMax: 0, borderColor: 'rgba(255,255,255,0.12)', borderWidth: 1, borderDash: [2,2] }},"""

    # Short name for table headers
    field_short = field_label.split('(')[0].strip() if '(' in field_label else field_label

    # Title uses Title Case for readability — "Entry Filter Threshold Analysis - <Short Name>".
    # The filename (config['out_html']) still uses lowercase-plus-brackets for tidy on-disk sorting.
    title_short = config.get('title_short') or field_label
    title_text = f"Entry Filter Threshold Analysis - {title_short}"

    html = _build_html(
        field_label=field_label,
        field_short=field_short,
        title_text=title_text,
        block_name=block_name,
        subtitle_note=subtitle_note,
        n=n,
        baseline_rom=baseline_rom,
        baseline_net=baseline_net,
        baseline_wr=baseline_wr,
        baseline_pf=baseline_pf,
        baseline_pl=baseline_pl,
        corr=corr,
        slope=slope,
        intercept=intercept,
        r_squared=r_squared,
        raw_json=raw_json,
        oo_js=oo_js,
        zero_x_thresh=zero_x_thresh,
        zero_x_scatter=zero_x_scatter,
    )

    with open(out_html, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"\nSaved -> {out_html}")
    return out_html


def _build_html(*, field_label, field_short, title_text, block_name, subtitle_note,
                n, baseline_rom, baseline_net, baseline_wr, baseline_pf, baseline_pl,
                corr, slope, intercept, r_squared, raw_json,
                oo_js, zero_x_thresh, zero_x_scatter):

    return f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title_text}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.0.1/dist/chartjs-plugin-annotation.min.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#1a1a2e;color:#e0e0e0;font-family:'Segoe UI',system-ui,sans-serif;padding:20px 30px;max-width:1400px;margin:0 auto}}
h1{{font-size:1.4em;color:#fff;margin-bottom:4px}}
h3{{font-size:1.05em;color:#fff;margin:20px 0 8px}}
.subtitle{{color:#aaa;font-size:0.85em;margin-bottom:16px}}
.metrics-row{{display:flex;gap:14px;margin-bottom:16px;flex-wrap:wrap}}
.metric-card{{background:#16213e;border-radius:6px;padding:8px 14px;min-width:110px}}
.metric-card .val{{font-size:1.3em;font-weight:700;color:#fff}}
.metric-card .lbl{{font-size:0.72em;color:#888;margin-top:2px}}
.chart-wrap{{position:relative;height:500px;margin-bottom:24px}}
.chart-wrap-sm{{position:relative;height:350px;margin-bottom:24px}}
table{{border-collapse:collapse;font-size:0.85em;width:100%;margin-bottom:20px}}
th{{background:#0f3460;color:#888;padding:8px 12px;text-transform:uppercase;font-size:0.72em;letter-spacing:0.5px;text-align:center}}
td{{padding:7px 12px;text-align:center;border-bottom:1px solid rgba(255,255,255,0.05)}}
th:first-child,td:first-child{{text-align:left}}
.tag{{display:inline-block;padding:2px 6px;border-radius:3px;font-size:0.7em;font-weight:600;margin-left:6px;vertical-align:middle}}
.tag-blue{{background:rgba(52,152,219,0.2);color:#3498db}}
.delta-pos{{color:#2ecc71;font-weight:600}}
.delta-neg{{color:#e74c3c;font-weight:600}}
.method{{color:#777;font-size:0.72em;margin-top:8px}}
.group-hdr td{{background:#0f3460;color:#f39c12;font-weight:700;text-align:left;font-size:0.85em;padding:6px 12px}}
</style></head><body>

<h1>{title_text}</h1>
<div class="subtitle">{block_name} &nbsp;|&nbsp; {n} trades &nbsp;|&nbsp; Baseline ROM: {baseline_rom:.2f}% &nbsp;|&nbsp; r = {corr:.4f} &nbsp;|&nbsp; {subtitle_note}</div>

<div class="metrics-row">
<div class="metric-card"><div class="val">{n}</div><div class="lbl">Total Trades</div></div>
<div class="metric-card"><div class="val">{baseline_rom:.2f}%</div><div class="lbl">Baseline Avg ROM</div></div>
<div class="metric-card"><div class="val">{baseline_net:.1f}%</div><div class="lbl">Baseline Net ROR</div></div>
<div class="metric-card"><div class="val">{baseline_wr:.1f}%</div><div class="lbl">Win Rate</div></div>
<div class="metric-card"><div class="val">{baseline_pf:.2f}</div><div class="lbl">Profit Factor</div></div>
<div class="metric-card"><div class="val">{corr:.4f}</div><div class="lbl">Correlation (r)</div></div>
</div>

<h3>Trade ROM vs {field_label}</h3>
<div class="chart-controls" style="display:flex;align-items:center;gap:10px;margin:4px 0 10px;font-size:0.85em;color:#aaa;flex-wrap:wrap">
  <label for="sharedXLow">X Low:</label>
  <input id="sharedXLow" type="number" step="any"
         style="width:90px;background:#16213e;color:#fff;border:1px solid #0f3460;border-radius:4px;padding:4px 6px;font-family:inherit">
  <label for="sharedXHigh">X High:</label>
  <input id="sharedXHigh" type="number" step="any"
         style="width:90px;background:#16213e;color:#fff;border:1px solid #0f3460;border-radius:4px;padding:4px 6px;font-family:inherit">
  <span style="color:#666;font-size:0.9em">&nbsp;— applies to scatter + threshold; Y auto-refits. Defaults: data min / data max.</span>
</div>
<div class="chart-wrap-sm"><canvas id="scatterChart"></canvas></div>

<h3>Threshold Sweep</h3>
<div class="chart-wrap"><canvas id="threshChart"></canvas></div>

<h3>Efficiency Frontier</h3>
<div class="chart-controls" style="display:flex;align-items:center;gap:10px;margin:4px 0 10px;font-size:0.85em;color:#aaa;flex-wrap:wrap">
  <label for="effXHigh">Max retention:</label>
  <input id="effXHigh" type="number" step="5"
         style="width:80px;background:#16213e;color:#fff;border:1px solid #0f3460;border-radius:4px;padding:4px 6px;font-family:inherit">
  <span>%</span>
  <label for="effXLow">Min retention:</label>
  <input id="effXLow" type="number" step="5"
         style="width:80px;background:#16213e;color:#fff;border:1px solid #0f3460;border-radius:4px;padding:4px 6px;font-family:inherit">
  <span>%</span>
  <span style="color:#666;font-size:0.9em">&nbsp;— Y auto-refits. Defaults: max = highest retention observed, min 20%.</span>
</div>
<div class="chart-wrap"><canvas id="effChart"></canvas></div>

<h3>Retention References</h3>
<table id="compTable"></table>
<p class="method">ROM = per-trade P/L / margin, then averaged across trades. ROR Retention = % of baseline Net ROR retained after applying filter. OO Filter = Option Omega implementation syntax.</p>
<p class="method" style="color:#f39c12">&#9888; Non-monotonic -- As you tighten a filter, you expect to steadily lose ROR. A non-monotonic result means the ROR dipped below the target on the way to this threshold, then bounced back because a big loser got excluded. The reported threshold only hits the retention target because large winning and losing trades above/below it happen to cancel out -- not because of a systematic edge. Treat with caution.</p>

<script>
const FIELD_LABEL = '{field_label}';
const FIELD_SHORT = '{field_short}';
const raw = {raw_json};
const N = raw.length;
const baselineRom = {baseline_rom:.4f};
const baselineNet = {baseline_net:.4f};
const baselineWr = {baseline_wr:.4f};
const baselinePf = {baseline_pf:.4f};
const baselinePl = {baseline_pl:.4f};
const slope = {slope:.6f};
const intercept = {intercept:.4f};
const rSquared = {r_squared:.4f};

const allVals = raw.map(r => r[0]).sort((a,b) => a-b);
const uniqueVals = [...new Set(allVals)].sort((a,b) => a-b);

// Compute threshold metrics at every unique value
const threshData = [];
for (const t of uniqueVals) {{
    const gtRows = raw.filter(r => r[0] >= t);
    const ltRows = raw.filter(r => r[0] <= t);
    if (gtRows.length < 1 || ltRows.length < 1) continue;

    const avg = a => a.reduce((s,v) => s+v, 0) / a.length;
    const sum = a => a.reduce((s,v) => s+v, 0);

    const gtRoms = gtRows.map(r => r[1]); const ltRoms = ltRows.map(r => r[1]);
    const gtPls = gtRows.map(r => r[2]); const ltPls = ltRows.map(r => r[2]);

    const gtRom = avg(gtRoms); const ltRom = avg(ltRoms);
    const gtNet = sum(gtRoms); const ltNet = sum(ltRoms);
    const gtWr = gtRoms.filter(v => v > 0).length / gtRows.length * 100;
    const ltWr = ltRoms.filter(v => v > 0).length / ltRows.length * 100;
    const gtGP = sum(gtRoms.filter(v => v > 0)); const gtGL = Math.abs(sum(gtRoms.filter(v => v < 0)));
    const gtPf = gtGL > 0 ? gtGP / gtGL : 99;
    const ltGP = sum(ltRoms.filter(v => v > 0)); const ltGL = Math.abs(sum(ltRoms.filter(v => v < 0)));
    const ltPf = ltGL > 0 ? ltGP / ltGL : 99;

    const pctTrades = raw.filter(r => r[0] < t).length / N * 100;
    const ltNetAll = raw.filter(r => r[0] < t).reduce((s,r) => s + r[1], 0);
    const pctNetRor = ltNetAll / baselineNet * 100;
    const gtRetained = gtNet / baselineNet * 100;
    const ltRetained = ltNet / baselineNet * 100;

    threshData.push({{
        t, gtRom, ltRom, gtNet, ltNet, gtWr, ltWr,
        gtPf: Math.min(gtPf,99), ltPf: Math.min(ltPf,99),
        gtPl: avg(gtPls), ltPl: avg(ltPls),
        gtN: gtRows.length, ltN: ltRows.length,
        pctTrades, pctNetRor, gtRetained, ltRetained,
    }});
}}

// ── Retention references ────────────────────────────────────────────────
const retTargets = [99, 95, 90, 80, 70, 60, 50];
const retColors = {{99:'#3498db', 95:'#2ecc71', 90:'#27ae60', 80:'#f39c12', 70:'#e67e22', 60:'#e74c3c', 50:'#c0392b'}};

const maxVal = uniqueVals[uniqueVals.length - 1];
const minVal = uniqueVals[0];
const baselineFallback = {{
    t: maxVal, gtRom: baselineRom, ltRom: baselineRom, gtNet: baselineNet, ltNet: baselineNet,
    gtWr: baselineWr, ltWr: baselineWr, gtPf: baselinePf, ltPf: baselinePf,
    gtPl: baselinePl, ltPl: baselinePl, gtN: N, ltN: N,
    gtRetained: 100, ltRetained: 100, pctTrades: 100, pctNetRor: 100
}};

const gtRefs = {{}};
for (const target of retTargets) {{
    let best = null;
    for (const d of threshData) {{
        if (d.gtRetained >= target) {{
            if (!best || d.t > best.t) best = d;
        }}
    }}
    gtRefs[target] = best || {{ ...baselineFallback, t: minVal }};
}}

const ltRefs = {{}};
for (const target of retTargets) {{
    let best = null;
    for (const d of threshData) {{
        if (d.ltRetained >= target) {{
            if (!best || d.t < best.t) best = d;
        }}
    }}
    ltRefs[target] = best || baselineFallback;
}}

const comboRefs = {{}};
for (const target of retTargets) {{
    let best = null;
    let bestAvg = -999;
    for (let i = 0; i < threshData.length; i++) {{
        for (let j = i; j < threshData.length; j++) {{
            const lo = threshData[i].t;
            const hi = threshData[j].t;
            const survivors = raw.filter(r => r[0] >= lo && r[0] <= hi);
            if (survivors.length < 1) continue;
            const sRoms = survivors.map(r => r[1]);
            const sPls = survivors.map(r => r[2]);
            const sNet = sRoms.reduce((s,v) => s+v, 0);
            const retained = sNet / baselineNet * 100;
            if (retained < target) continue;
            const sAvg = sNet / survivors.length;
            if (sAvg > bestAvg) {{
                bestAvg = sAvg;
                const sWr = sRoms.filter(v => v > 0).length / survivors.length * 100;
                const sGP = sRoms.filter(v => v > 0).reduce((s,v) => s+v, 0);
                const sGL = Math.abs(sRoms.filter(v => v < 0).reduce((s,v) => s+v, 0));
                const sPf = sGL > 0 ? sGP / sGL : 99;
                const sPlAvg = sPls.reduce((s,v) => s+v, 0) / survivors.length;
                best = {{ lo, hi, n: survivors.length, avg: sAvg, net: sNet, retained, wr: sWr, pf: Math.min(sPf,99), pl: sPlAvg }};
            }}
        }}
    }}
    comboRefs[target] = best || {{ lo: minVal, hi: maxVal, n: N, avg: baselineRom, net: baselineNet, retained: 100, wr: baselineWr, pf: baselinePf, pl: baselinePl }};
}}

// ── Non-monotonic detection ─────────────────────────────────────────────
const gtNonMono = {{}};
for (const [target, ref] of Object.entries(gtRefs)) {{
    const t = Number(target);
    const dipped = threshData.some(d => d.t < ref.t && d.gtRetained < t);
    if (dipped) gtNonMono[t] = true;
}}
const ltNonMono = {{}};
for (const [target, ref] of Object.entries(ltRefs)) {{
    const t = Number(target);
    const dipped = threshData.some(d => d.t > ref.t && d.ltRetained < t);
    if (dipped) ltNonMono[t] = true;
}}
const comboNonMono = {{}};
for (const [target, ref] of Object.entries(comboRefs)) {{
    const t = Number(target);
    let dipped = false;
    for (let i = 0; i < threshData.length; i++) {{
        for (let j = i; j < threshData.length; j++) {{
            const lo = threshData[i].t; const hi = threshData[j].t;
            if (lo > ref.lo || hi < ref.hi) continue;
            if (lo === ref.lo && hi === ref.hi) continue;
            const survivors = raw.filter(r => r[0] >= lo && r[0] <= hi);
            if (survivors.length < 1) continue;
            const sNet = survivors.map(r => r[1]).reduce((s,v) => s+v, 0);
            const retained = sNet / baselineNet * 100;
            if (retained < t) {{ dipped = true; break; }}
        }}
        if (dipped) break;
    }}
    if (dipped) comboNonMono[t] = true;
}}

// ── OO Translation ──────────────────────────────────────────────────────
{oo_js}

// ── Threshold Chart ─────────────────────────────────────────────────────
const threshCtx = document.getElementById('threshChart').getContext('2d');

const romVals = threshData.flatMap(d => [d.gtRom, d.ltRom]);
const romMin = Math.min(0, ...romVals) - 3;
const romMax = Math.max(...romVals) + 3;

const annotations = {{
    baselineRom: {{
        type: 'line', yMin: baselineRom, yMax: baselineRom, yScaleID: 'yRom',
        borderColor: 'rgba(255,255,255,0.4)', borderWidth: 1, borderDash: [4,4],
        label: {{ display: true, content: 'Baseline ' + baselineRom.toFixed(2) + '%',
                  position: 'end', backgroundColor: 'rgba(0,0,0,0.6)', color: '#aaa', font: {{size:10}} }}
    }},
    zeroRom: {{
        type: 'line', yMin: 0, yMax: 0, yScaleID: 'yRom',
        borderColor: 'rgba(255,255,255,0.15)', borderWidth: 1
    }},{zero_x_thresh}
}};

for (const [target, ref] of Object.entries(gtRefs)) {{
    const c = retColors[target] || '#888';
    annotations['gtRet' + target] = {{
        type: 'line', xMin: ref.t, xMax: ref.t, xScaleID: 'x',
        yMin: baselineRom, yMax: romMax, yScaleID: 'yRom',
        borderColor: c + '99', borderWidth: 1.5, borderDash: [6,3],
        label: {{ display: false }}
    }};
}}

for (const [target, ref] of Object.entries(ltRefs)) {{
    const c = retColors[target] || '#888';
    annotations['ltRet' + target] = {{
        type: 'line', xMin: ref.t, xMax: ref.t, xScaleID: 'x',
        yMin: romMin, yMax: baselineRom, yScaleID: 'yRom',
        borderColor: c + '99', borderWidth: 1.5, borderDash: [2,2],
        label: {{ display: false }}
    }};
}}

// Shared X axis bounds — both charts lock to actual data min/max (no padding).
const xMin = Math.min(...raw.map(r => r[0]));
const xMax = Math.max(...raw.map(r => r[0]));

const threshChartObj = new Chart(threshCtx, {{
    type: 'scatter',
    data: {{
        datasets: [
            {{
                label: '>= threshold (Avg ROM %)',
                data: threshData.map(d => ({{x: d.t, y: d.gtRom}})),
                showLine: true, borderColor: '#e67e22', backgroundColor: '#e67e22',
                pointRadius: 3, pointHoverRadius: 5, borderWidth: 2,
                yAxisID: 'yRom', order: 1
            }},
            {{
                label: '<= threshold (Avg ROM %)',
                data: threshData.map(d => ({{x: d.t, y: d.ltRom}})),
                showLine: true, borderColor: '#9b59b6', backgroundColor: '#9b59b6',
                pointRadius: 3, pointHoverRadius: 5, borderWidth: 2,
                yAxisID: 'yRom', order: 2
            }},
            {{
                label: '% Trades (CDF)',
                data: threshData.map(d => ({{x: d.t, y: d.pctTrades}})),
                showLine: true, pointRadius: 0, borderWidth: 1.5,
                borderColor: 'rgba(52,152,219,0.6)', backgroundColor: 'transparent',
                borderDash: [3,2], yAxisID: 'yPct', order: 3
            }},
            {{
                label: '% Net ROR (CDF)',
                data: threshData.map(d => ({{x: d.t, y: d.pctNetRor}})),
                showLine: true, pointRadius: 0, borderWidth: 1.5,
                borderColor: 'rgba(46,204,113,0.5)', backgroundColor: 'transparent',
                borderDash: [3,2], yAxisID: 'yPct', order: 4
            }}
        ]
    }},
    options: {{
        responsive: true, maintainAspectRatio: false,
        interaction: {{ mode: 'nearest', axis: 'x', intersect: false }},
        plugins: {{
            annotation: {{ annotations }},
            tooltip: {{
                callbacks: {{
                    title: ctx => FIELD_LABEL + ': ' + ctx[0].parsed.x.toFixed(2),
                    label: ctx => {{
                        const i = ctx.dataIndex;
                        const ds = ctx.datasetIndex;
                        if (ds === 0) {{
                            const d = threshData[i];
                            return ['>= ' + d.t.toFixed(2) + ': ROM ' + d.gtRom.toFixed(2) + '% (' + d.gtN + 't, WR ' + d.gtWr.toFixed(1) + '%, PF ' + d.gtPf.toFixed(2) + ')'];
                        }} else if (ds === 1) {{
                            const d = threshData[i];
                            return ['<= ' + d.t.toFixed(2) + ': ROM ' + d.ltRom.toFixed(2) + '% (' + d.ltN + 't, WR ' + d.ltWr.toFixed(1) + '%, PF ' + d.ltPf.toFixed(2) + ')'];
                        }}
                        return ctx.dataset.label + ': ' + ctx.parsed.y.toFixed(1) + '%';
                    }}
                }}
            }},
            legend: {{ labels: {{ color: '#aaa', usePointStyle: true, pointStyle: 'circle', padding: 16 }} }}
        }},
        scales: {{
            x: {{
                type: 'linear',
                title: {{ display: true, text: FIELD_LABEL, color: '#aaa' }},
                min: xMin, max: xMax,
                ticks: {{ color: '#888' }}, grid: {{ color: 'rgba(255,255,255,0.04)' }}
            }},
            yRom: {{
                type: 'linear', position: 'left',
                title: {{ display: true, text: 'Avg ROM (%)', color: '#aaa' }},
                min: romMin, max: romMax,
                ticks: {{ color: '#888' }}, grid: {{ color: 'rgba(255,255,255,0.04)' }}
            }},
            yPct: {{
                type: 'linear', position: 'right',
                title: {{ display: true, text: '% of Total', color: '#aaa' }},
                min: -5, max: 110,
                ticks: {{ color: '#888' }}, grid: {{ drawOnChartArea: false }}
            }}
        }}
    }}
}});

// ── Scatter Chart ────────────────────────────────────────────────────────
const scatterCtx = document.getElementById('scatterChart').getContext('2d');
const scatterPts = raw.map(r => ({{x: r[0], y: r[1]}}));
// xMin / xMax are shared with the threshold chart (declared above) — both axes stay aligned.
const fitLine = [
    {{x: xMin, y: slope * xMin + intercept}},
    {{x: xMax, y: slope * xMax + intercept}}
];

const scAnnot = {{
    zeroLine: {{ type: 'line', yMin: 0, yMax: 0, borderColor: 'rgba(255,255,255,0.2)', borderWidth: 1 }},
    fitLabel: {{
        type: 'label', xValue: xMax * 0.75, yValue: slope * xMax * 0.75 + intercept + 5,
        content: 'y = ' + slope.toFixed(3) + 'x + ' + intercept.toFixed(2) + '  R\\u00B2 = ' + rSquared.toFixed(4),
        backgroundColor: 'rgba(0,0,0,0.5)', color: '#e67e22', font: {{ size: 10 }}, padding: 4
    }},{zero_x_scatter}
}};
for (const [target, ref] of Object.entries(gtRefs)) {{
    const c = retColors[target] || '#888';
    scAnnot['gtRet' + target] = {{ type: 'line', xMin: ref.t, xMax: ref.t, borderColor: c + '44', borderWidth: 1, borderDash: [4,3] }};
}}
for (const [target, ref] of Object.entries(ltRefs)) {{
    const c = retColors[target] || '#888';
    scAnnot['ltRet' + target] = {{ type: 'line', xMin: ref.t, xMax: ref.t, borderColor: c + '44', borderWidth: 1, borderDash: [2,2] }};
}}

const scatterChartObj = new Chart(scatterCtx, {{
    type: 'scatter',
    data: {{
        datasets: [
            {{
                label: 'Trade ROM %',
                data: scatterPts,
                backgroundColor: scatterPts.map(p => p.y >= 0 ? 'rgba(52,152,219,0.5)' : 'rgba(231,76,60,0.5)'),
                pointRadius: 4.5, pointHoverRadius: 6, order: 2
            }},
            {{
                label: 'Best Fit',
                data: fitLine,
                showLine: true, pointRadius: 0, borderColor: '#e67e22',
                borderWidth: 2, borderDash: [6,3], order: 1
            }}
        ]
    }},
    options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{
            annotation: {{ annotations: scAnnot }},
            tooltip: {{
                filter: ctx => ctx.datasetIndex === 0,
                callbacks: {{
                    title: ctx => FIELD_LABEL + ': ' + ctx[0].parsed.x.toFixed(2),
                    label: ctx => 'ROM: ' + ctx.parsed.y.toFixed(2) + '%'
                }}
            }},
            legend: {{ display: false }}
        }},
        scales: {{
            x: {{ type: 'linear', title: {{ display: true, text: FIELD_LABEL, color: '#aaa' }}, min: xMin, max: xMax, ticks: {{ color: '#888' }}, grid: {{ color: 'rgba(255,255,255,0.04)' }} }},
            y: {{ type: 'linear', title: {{ display: true, text: 'Trade ROM (%)', color: '#aaa' }}, ticks: {{ color: '#888' }}, grid: {{ color: 'rgba(255,255,255,0.04)' }} }}
        }}
    }}
}});

// ── Efficiency Frontier ─────────────────────────────────────────────────
const gtCurve = threshData
    .map(d => ({{x: d.gtRetained, y: d.gtRom, t: d.t, n: d.gtN}}))
    .sort((a,b) => b.x - a.x);

const ltCurve = threshData
    .map(d => ({{x: d.ltRetained, y: d.ltRom, t: d.t, n: d.ltN}}))
    .sort((a,b) => b.x - a.x);

// Pre-compute ALL (lo, hi) pair stats once. The frontier and the target sweep
// both consume these; avoids an O(targets × pairs × N) nested filter.
const allPairs = [];
{{
    // Sort trades by filter value for O(1) range lookups via binary scanning.
    const sortedTrades = raw.slice().sort((a,b) => a[0] - b[0]);
    const sortedVals = sortedTrades.map(r => r[0]);
    // For each (lo_idx, hi_idx) on the unique-threshold grid, extract survivors
    // and aggregate. threshData is already sorted ascending by `t` (unique vals).
    for (let i = 0; i < threshData.length; i++) {{
        const lo = threshData[i].t;
        // First sorted trade with value >= lo
        let loStart = 0;
        while (loStart < sortedVals.length && sortedVals[loStart] < lo) loStart++;
        for (let j = i; j < threshData.length; j++) {{
            const hi = threshData[j].t;
            // Last sorted trade with value <= hi
            let hiEnd = sortedVals.length;
            while (hiEnd > 0 && sortedVals[hiEnd - 1] > hi) hiEnd--;
            const n = hiEnd - loStart;
            if (n < 1) continue;
            let sNet = 0; let wins = 0; let gp = 0; let gl = 0; let plSum = 0;
            for (let k = loStart; k < hiEnd; k++) {{
                const rom = sortedTrades[k][1];
                sNet += rom;
                plSum += sortedTrades[k][2];
                if (rom > 0) {{ wins++; gp += rom; }} else if (rom < 0) {{ gl -= rom; }}
            }}
            allPairs.push({{
                lo, hi, n,
                net: sNet,
                retained: sNet / baselineNet * 100,
                avg: sNet / n,
                wr: wins / n * 100,
                pf: gl > 0 ? Math.min(gp / gl, 99) : 99,
                pl: plSum / n,
            }});
        }}
    }}
}}

// Combo curve (efficiency frontier target sweep). For each retention target from
// high (above 100 when dropping losers beats baseline) down to 0, find the pair
// with max avg_rom meeting that constraint. 500% ceiling is a generous guard.
const comboCurve = [];
for (let target = 500; target >= 0; target -= 1) {{
    let bestAvg = -999;
    let best = null;
    for (const p of allPairs) {{
        if (p.retained < target) continue;
        if (p.avg > bestAvg) {{
            bestAvg = p.avg;
            best = {{ x: p.retained, y: p.avg, lo: p.lo, hi: p.hi, n: p.n }};
        }}
    }}
    if (best) comboCurve.push(best);
}}
const comboSeen = new Set();
const comboDedupe = [];
for (const p of comboCurve) {{
    const key = p.x.toFixed(2) + '|' + p.y.toFixed(2);
    if (!comboSeen.has(key)) {{ comboSeen.add(key); comboDedupe.push(p); }}
}}
comboDedupe.sort((a,b) => b.x - a.x);
const comboCurveFinal = comboDedupe;

const effCtx = document.getElementById('effChart').getContext('2d');
// X axis upper bound: allow > 100% when dropping losers beats baseline.
// Floor at 105 so small datasets without >100% still render cleanly.
const allEffX = [...gtCurve.map(d=>d.x), ...ltCurve.map(d=>d.x), ...comboCurveFinal.map(d=>d.x)];
const effXMax = Math.max(105, Math.ceil(Math.max(...allEffX) + 5));

// Y axis is dynamic on every chart — bounds are recomputed from whatever points
// fall inside the chart's current X window, so each chart auto-zooms vertically
// when the user adjusts its X-axis controls. All three charts use the same
// formula so behavior is consistent.
function yBoundsFormula(ys) {{
    if (ys.length === 0) return {{ min: -2, max: 2 }};
    return {{
        min: Math.min(0, ...ys) - 2,
        max: Math.max(...ys) + 2,
    }};
}}
// Scatter: Y = per-trade ROM for trades with filter_value inside [xMin, xMax].
function scatterYBounds(xMin, xMax) {{
    const ys = [];
    for (const r of raw) if (r[0] >= xMin && r[0] <= xMax) ys.push(r[1]);
    return yBoundsFormula(ys);
}}
// Threshold: Y = gtRom & ltRom at thresholds inside [xMin, xMax]. yPct stays fixed.
function threshYBounds(xMin, xMax) {{
    const ys = [];
    for (const d of threshData) {{
        if (d.t >= xMin && d.t <= xMax) {{ ys.push(d.gtRom, d.ltRom); }}
    }}
    return yBoundsFormula(ys);
}}
// Efficiency frontier: Y = avg ROM across all three curves inside [xMin, xMax].
function effYBounds(xMin, xMax) {{
    const ys = [];
    const scan = arr => {{
        for (const p of arr) if (p.x >= xMin && p.x <= xMax) ys.push(p.y);
    }};
    scan(gtCurve); scan(ltCurve); scan(comboCurveFinal);
    return yBoundsFormula(ys);
}}

// Default X bounds for the efficiency frontier (user-adjustable via inputs).
// Low defaults to 0 (no losing combos below). High defaults to the data-driven
// ceiling so any above-baseline subset is visible.
const EFF_X_LOW_DEFAULT = 20;
const EFF_X_HIGH_DEFAULT = effXMax;
const initEffY = effYBounds(EFF_X_LOW_DEFAULT, EFF_X_HIGH_DEFAULT);

const effChartObj = new Chart(effCtx, {{
    type: 'scatter',
    data: {{
        datasets: [
            {{
                label: '>= (Min threshold)',
                data: gtCurve,
                showLine: true, borderColor: '#e67e22', backgroundColor: '#e67e22',
                pointRadius: 2, pointHoverRadius: 5, borderWidth: 2, order: 2
            }},
            {{
                label: '<= (Max threshold)',
                data: ltCurve,
                showLine: true, borderColor: '#9b59b6', backgroundColor: '#9b59b6',
                pointRadius: 2, pointHoverRadius: 5, borderWidth: 2, order: 3
            }},
            {{
                label: 'Combo [min, max]',
                data: comboCurveFinal,
                showLine: true, borderColor: '#1abc9c', backgroundColor: '#1abc9c',
                pointRadius: 4, pointHoverRadius: 6, borderWidth: 2.5, order: 1
            }}
        ]
    }},
    options: {{
        responsive: true, maintainAspectRatio: false,
        interaction: {{ mode: 'nearest', intersect: false }},
        plugins: {{
            annotation: {{
                annotations: {{
                    baselineRom: {{
                        type: 'line', yMin: baselineRom, yMax: baselineRom,
                        borderColor: 'rgba(255,255,255,0.3)', borderWidth: 1, borderDash: [4,4],
                        label: {{ display: true, content: 'Baseline ' + baselineRom.toFixed(2) + '%',
                                  position: 'end', backgroundColor: 'rgba(0,0,0,0.5)', color: '#aaa', font: {{size:10}} }}
                    }}
                }}
            }},
            tooltip: {{
                callbacks: {{
                    title: ctx => 'ROR Retained: ' + ctx[0].parsed.x.toFixed(1) + '%',
                    label: ctx => {{
                        const ds = ctx.datasetIndex;
                        const i = ctx.dataIndex;
                        const rom = ctx.parsed.y.toFixed(2);
                        if (ds === 0) {{
                            const d = gtCurve[i];
                            return '>= ' + d.t.toFixed(2) + ' | ROM ' + rom + '% | ' + d.n + 't';
                        }} else if (ds === 1) {{
                            const d = ltCurve[i];
                            return '<= ' + d.t.toFixed(2) + ' | ROM ' + rom + '% | ' + d.n + 't';
                        }} else {{
                            const d = comboCurveFinal[i];
                            return '[' + d.lo.toFixed(2) + ', ' + d.hi.toFixed(2) + '] | ROM ' + rom + '% | ' + d.n + 't';
                        }}
                    }}
                }}
            }},
            legend: {{ labels: {{ color: '#aaa', usePointStyle: true, pointStyle: 'circle', padding: 16 }} }}
        }},
        scales: {{
            x: {{
                type: 'linear', reverse: true,
                title: {{ display: true, text: '% Total ROR Retained', color: '#aaa' }},
                min: EFF_X_LOW_DEFAULT, max: EFF_X_HIGH_DEFAULT,
                ticks: {{ color: '#888' }}, grid: {{ color: 'rgba(255,255,255,0.04)' }}
            }},
            y: {{
                type: 'linear',
                title: {{ display: true, text: 'Avg ROM (%)', color: '#aaa' }},
                min: initEffY.min, max: initEffY.max,
                ticks: {{ color: '#888' }}, grid: {{ color: 'rgba(255,255,255,0.04)' }}
            }}
        }}
    }}
}});

// ── X-axis input wiring (consistent across all three charts) ───────────
// Each chart exposes a Low and High input. On every change, the chart's X bounds
// are updated AND the Y bounds are recomputed from the visible-window data.
// Scatter and threshold share the SAME pair of inputs (they visualize the same
// filter-value domain; sharing lets a threshold reference line up with its
// underlying trade dots). Efficiency frontier has its own pair (different X domain).
function wireXControls(lowId, highId, onChange) {{
    const lo = document.getElementById(lowId);
    const hi = document.getElementById(highId);
    if (!lo || !hi) return;
    const apply = () => {{
        const a = parseFloat(lo.value);
        const b = parseFloat(hi.value);
        if (!Number.isFinite(a) || !Number.isFinite(b)) return;
        onChange(a, b);
    }};
    lo.addEventListener('input', apply);
    hi.addEventListener('input', apply);
}}

// Shared X controls → update BOTH scatter and threshold.
wireXControls('sharedXLow', 'sharedXHigh', (lo, hi) => {{
    scatterChartObj.options.scales.x.min = lo;
    scatterChartObj.options.scales.x.max = hi;
    const sY = scatterYBounds(lo, hi);
    scatterChartObj.options.scales.y.min = sY.min;
    scatterChartObj.options.scales.y.max = sY.max;
    scatterChartObj.update('none');

    threshChartObj.options.scales.x.min = lo;
    threshChartObj.options.scales.x.max = hi;
    const tY = threshYBounds(lo, hi);
    threshChartObj.options.scales.yRom.min = tY.min;
    threshChartObj.options.scales.yRom.max = tY.max;
    threshChartObj.update('none');
}});

// EF X controls → update EF only.
wireXControls('effXLow', 'effXHigh', (lo, hi) => {{
    effChartObj.options.scales.x.min = lo;
    effChartObj.options.scales.x.max = hi;
    const y = effYBounds(lo, hi);
    effChartObj.options.scales.y.min = y.min;
    effChartObj.options.scales.y.max = y.max;
    effChartObj.update('none');
}});

// Populate input values from actual chart-init bounds (single source of truth).
(() => {{
    const setVal = (id, v, decimals = 4) => {{
        const el = document.getElementById(id);
        if (el && Number.isFinite(v)) {{
            // Strip trailing zeros for cleaner display
            el.value = Number.isInteger(v) ? v.toString() : Number(v.toFixed(decimals)).toString();
        }}
    }};
    setVal('sharedXLow',  scatterChartObj.options.scales.x.min);
    setVal('sharedXHigh', scatterChartObj.options.scales.x.max);
    setVal('effXLow',     effChartObj.options.scales.x.min, 1);
    setVal('effXHigh',    effChartObj.options.scales.x.max, 1);
}})();

// ── Retention Table ─────────────────────────────────────────────────────
const tbl = document.getElementById('compTable');
const fmt = (v, d=2) => v.toFixed(d);
const cls = v => v >= 0 ? 'delta-pos' : 'delta-neg';
const fmtD = (v, d=2) => (v >= 0 ? '+' : '') + v.toFixed(d);

// Thin-data warning. Flags any row with fewer than 30 surviving trades.
// Doesn't change behavior — data is still reported — just signals variance risk.
const THIN_N = 30;
const thinFlag = n => n < THIN_N
    ? ' <span title="Thin sample: ' + n + ' trades (< ' + THIN_N + '). Avg ROM is noisy — interpret with caution." style="cursor:help;color:#f39c12">&#9888;</span>'
    : '';

let th = '<thead><tr><th>Threshold</th><th>ROR Retention</th><th>Avg ROM %</th><th>ROM Delta</th><th>Trades</th><th>% Trades</th><th>Win Rate</th><th>PF</th><th>Avg 1-Lot P/L</th><th>OO Filter</th></tr></thead>';
let tb = '<tbody>';

tb += '<tr><td>Baseline (all trades) <span class="tag tag-blue">BASE</span></td>';
tb += '<td>100%</td><td>' + fmt(baselineRom) + '%</td><td>-</td>';
tb += '<td>' + N + '</td><td>100.0%</td>';
tb += '<td>' + fmt(baselineWr,1) + '%</td><td>' + fmt(baselinePf) + '</td>';
tb += '<td>$' + fmt(baselinePl) + '</td><td>-</td></tr>';

tb += '<tr class="group-hdr"><td colspan="10" style="background:#0f3460;color:#e67e22;font-weight:700;text-align:left;font-size:0.85em;padding:6px 12px">&gt;= direction (orange) - higher ' + FIELD_SHORT + ' = filter in &nbsp; <span style="color:#888;font-weight:400;font-size:0.85em">dashed reference lines</span></td></tr>';

const retOrder = [99, 95, 90, 80, 70, 60, 50];
for (const target of retOrder) {{
    const ref = gtRefs[target];
    if (!ref) continue;
    const c = retColors[target];
    const dRom = ref.gtRom - baselineRom;
    const romCls = cls(dRom);
    const nmFlag = gtNonMono[target] ? ' <span title="Non-monotonic: retention dipped below ' + target + '% on the path from baseline to this threshold. Result depends on large trades canceling out." style="cursor:help;color:#f39c12">&#9888;</span>' : '';
    tb += '<tr><td>>= ' + fmt(ref.t) + ' <span class="tag" style="background:' + c + '22;color:' + c + '">' + target + 'r%</span>' + nmFlag + '</td>';
    tb += '<td>' + fmt(ref.gtRetained,1) + '%</td>';
    tb += '<td class="' + romCls + '">' + fmt(ref.gtRom) + '%</td>';
    tb += '<td class="' + romCls + '">' + fmtD(dRom) + 'pp</td>';
    tb += '<td>' + ref.gtN + thinFlag(ref.gtN) + '</td><td>' + fmt(ref.gtN/N*100,1) + '%</td>';
    tb += '<td>' + fmt(ref.gtWr,1) + '%</td><td>' + fmt(ref.gtPf) + '</td>';
    tb += '<td>$' + fmt(ref.gtPl) + '</td>';
    tb += '<td style="font-size:0.8em;color:#ccc">' + ooFilter('>=', ref.t, FIELD_SHORT) + '</td></tr>';
}}

tb += '<tr class="group-hdr"><td colspan="10" style="background:#0f3460;color:#9b59b6;font-weight:700;text-align:left;font-size:0.85em;padding:6px 12px">&lt;= direction (purple) - lower ' + FIELD_SHORT + ' = filter in &nbsp; <span style="color:#888;font-weight:400;font-size:0.85em">dotted reference lines</span></td></tr>';

for (const target of retOrder) {{
    const ref = ltRefs[target];
    if (!ref) continue;
    const c = retColors[target];
    const dRom = ref.ltRom - baselineRom;
    const romCls = cls(dRom);
    const ltNmFlag = ltNonMono[target] ? ' <span title="Non-monotonic: retention dipped below ' + target + '% on the path from baseline to this threshold. Result depends on large trades canceling out." style="cursor:help;color:#f39c12">&#9888;</span>' : '';
    tb += '<tr><td><= ' + fmt(ref.t) + ' <span class="tag" style="background:' + c + '22;color:' + c + '">' + target + 'r%</span>' + ltNmFlag + '</td>';
    tb += '<td>' + fmt(ref.ltRetained,1) + '%</td>';
    tb += '<td class="' + romCls + '">' + fmt(ref.ltRom) + '%</td>';
    tb += '<td class="' + romCls + '">' + fmtD(dRom) + 'pp</td>';
    tb += '<td>' + ref.ltN + thinFlag(ref.ltN) + '</td><td>' + fmt(ref.ltN/N*100,1) + '%</td>';
    tb += '<td>' + fmt(ref.ltWr,1) + '%</td><td>' + fmt(ref.ltPf) + '</td>';
    tb += '<td>$' + fmt(ref.ltPl) + '</td>';
    tb += '<td style="font-size:0.8em;color:#ccc">' + ooFilter('<=', ref.t, FIELD_SHORT) + '</td></tr>';
}}

tb += '<tr class="group-hdr"><td colspan="10" style="background:#0f3460;color:#1abc9c;font-weight:700;text-align:left;font-size:0.85em;padding:6px 12px">Combo (best [min, max] range) - highest Avg ROM meeting retention target</td></tr>';

for (const target of retOrder) {{
    const ref = comboRefs[target];
    if (!ref) continue;
    const c = retColors[target];
    const dRom = ref.avg - baselineRom;
    const romCls = cls(dRom);
    const loOO = ooFilter('>=', ref.lo, FIELD_SHORT);
    const hiOO = ooFilter('<=', ref.hi, FIELD_SHORT);
    const coNmFlag = comboNonMono[target] ? ' <span title="Non-monotonic: a wider range dips below ' + target + '% retention before recovering. Result depends on large trades canceling out." style="cursor:help;color:#f39c12">&#9888;</span>' : '';
    tb += '<tr><td>[' + fmt(ref.lo) + ', ' + fmt(ref.hi) + '] <span class="tag" style="background:' + c + '22;color:' + c + '">' + target + 'r%</span>' + coNmFlag + '</td>';
    tb += '<td>' + fmt(ref.retained,1) + '%</td>';
    tb += '<td class="' + romCls + '">' + fmt(ref.avg) + '%</td>';
    tb += '<td class="' + romCls + '">' + fmtD(dRom) + 'pp</td>';
    tb += '<td>' + ref.n + thinFlag(ref.n) + '</td><td>' + fmt(ref.n/N*100,1) + '%</td>';
    tb += '<td>' + fmt(ref.wr,1) + '%</td><td>' + fmt(ref.pf) + '</td>';
    tb += '<td>$' + fmt(ref.pl) + '</td>';
    tb += '<td style="font-size:0.75em;color:#ccc">' + loOO + ' + ' + hiOO + '</td></tr>';
}}

tb += '</tbody>';
tbl.innerHTML = th + tb;
</script>
</body></html>'''


# ── Main / CLI ───────────────────────────────────────────────────────────────

def derive_field_slug(short_name: str) -> str:
    """Element-ID-safe slug for chart DOM hooks. Lowercased, alnum + dash only."""
    s = sanitize_short_name_for_filename(short_name).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "field"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Threshold analysis for a single entry filter on a block.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("block_id", help="Block folder name under TB root")
    ap.add_argument("filter", nargs="?", default=None,
                    help="Filter identifier (CSV Column, Index, Short Name, Filter, or substring)")
    ap.add_argument("--tb-root", default=TB_ROOT_DEFAULT, help="TradeBlocks Data root")
    ap.add_argument("--groups-csv", default=None,
                    help="Explicit entry_filter_groups CSV path (abs or relative to TB root)")
    ap.add_argument("--filter-by", default=None, metavar="COL=VAL",
                    help='Scope filters to rows where COL equals VAL (case-insensitive)')
    ap.add_argument("--list", action="store_true", dest="list_filters",
                    help="Print available filters (scoped by --filter-by) and exit")
    args = ap.parse_args()

    tb_root = pathlib.Path(args.tb_root).resolve()

    try:
        block_folder = resolve_block_folder(tb_root, args.block_id)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    ref_folder = block_folder / "alex-tradeblocks-ref"

    print(f"Block: {args.block_id}")
    print(f"TB root: {tb_root}")

    # Resolve data CSV (exit 2 on miss)
    try:
        data_csv = resolve_data_csv(ref_folder)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return EXIT_MISSING_DATA_CSV

    # Resolve groups CSV (exit 3 on zero, exit 4 on multiple)
    explicit: Optional[pathlib.Path] = None
    if args.groups_csv:
        candidate = pathlib.Path(args.groups_csv)
        if not candidate.is_absolute():
            candidate = (tb_root / candidate).resolve()
        explicit = candidate

    try:
        groups_path, source = resolve_groups_csv(ref_folder, explicit)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return EXIT_MISSING_GROUPS_CSV
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return EXIT_MULTIPLE_GROUPS_CSV

    try:
        display_groups = groups_path.relative_to(tb_root)
    except ValueError:
        display_groups = groups_path
    try:
        display_data = data_csv.relative_to(tb_root)
    except ValueError:
        display_data = data_csv

    print(f"Data CSV:   {display_data}  [block-local]")
    print(f"Groups CSV: {display_groups}  [{source}]")

    # Load + scope groups
    try:
        groups = load_groups(groups_path)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    try:
        scoped = apply_filter_by(groups, args.filter_by)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return EXIT_FILTER_UNRESOLVED
    if args.filter_by:
        print(f"--filter-by {args.filter_by!r} → {len(scoped)} of {len(groups)} filters match")

    # --list short-circuit
    if args.list_filters:
        list_filters(scoped)
        return EXIT_OK

    # Require FILTER arg (unless --list)
    if not args.filter:
        print()
        print("No FILTER argument provided. Available filters in this block:")
        print()
        list_filters(scoped)
        print()
        print("Pass one of the Index / Short Name / Filter / CSV Column values as the second arg.")
        return EXIT_NO_FILTER_ARG

    # Resolve the filter
    matches = resolve_filter(scoped, args.filter)
    if len(matches) == 0:
        print(f"\nERROR: no filter matches {args.filter!r} in this block's groups CSV.")
        if args.filter_by:
            print(f"(scope: {args.filter_by})")
        print()
        list_filters(scoped, file=sys.stderr)
        return EXIT_FILTER_UNRESOLVED
    if len(matches) > 1:
        print(f"\nERROR: {args.filter!r} is ambiguous — {len(matches)} candidates:", file=sys.stderr)
        for r in matches:
            print(f"  {r.get('Index','?'):>3} | {r.get('Filter','')!s:<32} | {r.get('Short Name','')!s:<14} | {r.get('CSV Column','')}",
                  file=sys.stderr)
        print("\nNarrow the match or pass the exact CSV Column / Index.", file=sys.stderr)
        return EXIT_FILTER_UNRESOLVED

    row = matches[0]
    short_name = (row.get("Short Name") or "").strip()
    if not short_name:
        print(f"\nERROR: resolved filter has empty 'Short Name' column — required for output filename.", file=sys.stderr)
        print(f"  Index={row.get('Index')}, Filter={row.get('Filter')!r}, CSV Column={row.get('CSV Column')!r}",
              file=sys.stderr)
        print("Populate the Short Name column in the groups CSV and retry.", file=sys.stderr)
        return EXIT_SHORT_NAME_EMPTY

    field_col = (row.get("CSV Column") or "").strip()
    full_label = (row.get("Filter") or "").strip() or short_name

    # Build output filename using sanitized Short Name
    fname_short = sanitize_short_name_for_filename(short_name)
    out_html = block_folder / f"entry filter threshold analysis [{fname_short}].html"

    # OO translate mode: preserve existing behavior — vix_on for VIX_Gap_Pct
    oo_translate = "vix_on" if field_col == "VIX_Gap_Pct" else "simple"

    cfg = {
        "block_folder":  str(block_folder),
        "block_name":    args.block_id,
        "field_col":     field_col,
        "field_label":   full_label,
        "field_slug":    derive_field_slug(short_name),
        "title_short":   short_name,  # used in HTML <title> / <h1> suffix, Title Case
        "data_csv":      str(data_csv),
        "out_html":      str(out_html),
        "oo_translate":  oo_translate,
        "show_zero_x":   None,  # auto-detect from data
        "subtitle_note": f"Continuous sweep across all unique {full_label} values",
    }

    print()
    print(f"Resolved filter:")
    print(f"  Index:       {row.get('Index')}")
    print(f"  Filter:      {full_label}")
    print(f"  Short Name:  {short_name}")
    print(f"  CSV Column:  {field_col}")
    print(f"  Entry Group: {row.get('Entry Group','')}")
    print()

    try:
        _generate(cfg)
    except Exception as e:
        print(f"\nERROR: HTML generation failed: {e}", file=sys.stderr)
        return 1

    try:
        out_rel = out_html.relative_to(tb_root)
    except ValueError:
        out_rel = out_html
    print()
    print(f"HTML report written: {out_rel}")
    print(f"  open \"{out_html}\"")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
