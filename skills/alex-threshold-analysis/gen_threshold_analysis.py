#!/usr/bin/env python3
"""
Shared threshold analysis chart generator.
Block-specific scripts import this and call generate() with a config dict.

Usage from a block-specific wrapper:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '_shared'))
    from gen_threshold_analysis import generate

    generate({
        'block_folder': '/path/to/block',
        'block_name':   '20250926 - SPX DC 5-7 22.5-15d oF',
        'field_col':    'SLR',
        'field_label':  'Short-to-Long Premium Ratio (SLR)',
        'field_slug':   'slr',
        'oo_translate':  'simple',   # 'simple' | 'vix_on' | custom JS function string
        'show_zero_x':   False,       # vertical 0-line for fields spanning +/-
        'subtitle_note': 'Continuous sweep across all unique SLR values',
    })
"""

import csv
import json
import os
import numpy as np


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


def generate(config):
    """Generate threshold analysis HTML from config dict.

    Required keys:
        block_folder, block_name, field_col, field_label, field_slug

    Optional keys:
        oo_translate   (str): 'simple' | 'vix_on' | raw JS function. Default 'simple'
        show_zero_x    (bool): Show vertical 0-line annotation. Default False
        subtitle_note  (str): Suffix text for subtitle. Default auto-generated
    """
    block_folder  = config['block_folder']
    block_name    = config['block_name']
    field_col     = config['field_col']
    field_label   = config['field_label']
    field_slug    = config['field_slug']
    oo_translate  = config.get('oo_translate', 'simple')
    show_zero_x   = config.get('show_zero_x', False)
    subtitle_note = config.get('subtitle_note', f'Continuous sweep across all unique {field_label} values')

    data_csv = os.path.join(block_folder, 'alex-tradeblocks-ref', 'entry_filter_data.csv')
    out_html = os.path.join(block_folder, f'entry_filter_threshold_{field_slug}.html')

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

    print(f"Using cached filter data ({n} trades)")
    print(f"Correlation with ROM: r = {corr:.4f}, R^2 = {r_squared:.4f}")
    print(f"Range: [{vals.min():.4f}, {vals.max():.4f}]")
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

    html = _build_html(
        field_label=field_label,
        field_short=field_short,
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


def _build_html(*, field_label, field_short, block_name, subtitle_note,
                n, baseline_rom, baseline_net, baseline_wr, baseline_pf, baseline_pl,
                corr, slope, intercept, r_squared, raw_json,
                oo_js, zero_x_thresh, zero_x_scatter):

    return f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{field_label} Threshold Analysis</title>
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

<h1>{field_label} Threshold Analysis</h1>
<div class="subtitle">{block_name} &nbsp;|&nbsp; {n} trades &nbsp;|&nbsp; Baseline ROM: {baseline_rom:.2f}% &nbsp;|&nbsp; r = {corr:.4f} &nbsp;|&nbsp; {subtitle_note}</div>

<div class="metrics-row">
<div class="metric-card"><div class="val">{n}</div><div class="lbl">Total Trades</div></div>
<div class="metric-card"><div class="val">{baseline_rom:.2f}%</div><div class="lbl">Baseline Avg ROM</div></div>
<div class="metric-card"><div class="val">{baseline_net:.1f}%</div><div class="lbl">Baseline Net ROR</div></div>
<div class="metric-card"><div class="val">{baseline_wr:.1f}%</div><div class="lbl">Win Rate</div></div>
<div class="metric-card"><div class="val">{baseline_pf:.2f}</div><div class="lbl">Profit Factor</div></div>
<div class="metric-card"><div class="val">{corr:.4f}</div><div class="lbl">Correlation (r)</div></div>
</div>

<div class="chart-wrap"><canvas id="threshChart"></canvas></div>

<h3>Retention References</h3>
<table id="compTable"></table>
<p class="method">ROM = per-trade P/L / margin, then averaged across trades. ROR Retention = % of baseline Net ROR retained after applying filter. OO Filter = Option Omega implementation syntax.</p>
<p class="method" style="color:#f39c12">&#9888; Non-monotonic -- As you tighten a filter, you expect to steadily lose ROR. A non-monotonic result means the ROR dipped below the target on the way to this threshold, then bounced back because a big loser got excluded. The reported threshold only hits the retention target because large winning and losing trades above/below it happen to cancel out -- not because of a systematic edge. Treat with caution.</p>

<h3>Efficiency Frontier</h3>
<div class="chart-wrap"><canvas id="effChart"></canvas></div>

<h3>Trade ROM vs {field_label}</h3>
<div class="chart-wrap-sm"><canvas id="scatterChart"></canvas></div>

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
        if (d.gtRetained >= target && d.gtN >= 10) {{
            if (!best || d.t > best.t) best = d;
        }}
    }}
    gtRefs[target] = best || {{ ...baselineFallback, t: minVal }};
}}

const ltRefs = {{}};
for (const target of retTargets) {{
    let best = null;
    for (const d of threshData) {{
        if (d.ltRetained >= target && d.ltN >= 10) {{
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
            if (survivors.length < 10) continue;
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
    const dipped = threshData.some(d => d.t < ref.t && d.gtRetained < t && d.gtN >= 10);
    if (dipped) gtNonMono[t] = true;
}}
const ltNonMono = {{}};
for (const [target, ref] of Object.entries(ltRefs)) {{
    const t = Number(target);
    const dipped = threshData.some(d => d.t > ref.t && d.ltRetained < t && d.ltN >= 10);
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
            if (survivors.length < 10) continue;
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

const thinGt = threshData.find(d => d.gtN < 30);
if (thinGt) {{
    annotations.thinBoxGt = {{
        type: 'box', xMin: thinGt.t, xMax: threshData[threshData.length-1].t,
        backgroundColor: 'rgba(255,255,255,0.03)', borderColor: 'rgba(255,255,255,0.08)',
        borderWidth: 1, borderDash: [3,3],
        label: {{ display: true, content: '< 30 trades (>=)', position: 'start',
                  backgroundColor: 'transparent', color: 'rgba(255,255,255,0.25)', font: {{size:9}} }}
    }};
}}
const thinLtArr = [...threshData].reverse();
const thinLt = thinLtArr.find(d => d.ltN < 30);
if (thinLt) {{
    annotations.thinBoxLt = {{
        type: 'box', xMin: threshData[0].t, xMax: thinLt.t,
        backgroundColor: 'rgba(255,255,255,0.03)', borderColor: 'rgba(255,255,255,0.08)',
        borderWidth: 1, borderDash: [3,3],
        label: {{ display: true, content: '< 30 trades (<=)', position: 'end',
                  backgroundColor: 'transparent', color: 'rgba(255,255,255,0.25)', font: {{size:9}} }}
    }};
}}

new Chart(threshCtx, {{
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
const xMin = Math.min(...raw.map(r => r[0]));
const xMax = Math.max(...raw.map(r => r[0]));
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

new Chart(scatterCtx, {{
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
            x: {{ type: 'linear', title: {{ display: true, text: FIELD_LABEL, color: '#aaa' }}, ticks: {{ color: '#888' }}, grid: {{ color: 'rgba(255,255,255,0.04)' }} }},
            y: {{ type: 'linear', title: {{ display: true, text: 'Trade ROM (%)', color: '#aaa' }}, ticks: {{ color: '#888' }}, grid: {{ color: 'rgba(255,255,255,0.04)' }} }}
        }}
    }}
}});

// ── Efficiency Frontier ─────────────────────────────────────────────────
const gtCurve = threshData
    .filter(d => d.gtN >= 10)
    .map(d => ({{x: d.gtRetained, y: d.gtRom, t: d.t, n: d.gtN}}))
    .sort((a,b) => b.x - a.x);

const ltCurve = threshData
    .filter(d => d.ltN >= 10)
    .map(d => ({{x: d.ltRetained, y: d.ltRom, t: d.t, n: d.ltN}}))
    .sort((a,b) => b.x - a.x);

const comboCurve = [];
const comboTargetsFine = [];
for (let t = 99; t >= 10; t -= 1) comboTargetsFine.push(t);
for (const target of comboTargetsFine) {{
    let best = null;
    let bestAvg = -999;
    for (let i = 0; i < threshData.length; i++) {{
        for (let j = i; j < threshData.length; j++) {{
            const lo = threshData[i].t;
            const hi = threshData[j].t;
            const survivors = raw.filter(r => r[0] >= lo && r[0] <= hi);
            if (survivors.length < 10) continue;
            const sRoms = survivors.map(r => r[1]);
            const sNet = sRoms.reduce((s,v) => s+v, 0);
            const retained = sNet / baselineNet * 100;
            if (retained < target) continue;
            const sAvg = sNet / survivors.length;
            if (sAvg > bestAvg) {{
                bestAvg = sAvg;
                best = {{ x: retained, y: sAvg, lo, hi, n: survivors.length }};
            }}
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
const allEffY = [...gtCurve.map(d=>d.y), ...ltCurve.map(d=>d.y), ...comboCurveFinal.map(d=>d.y)];
const effYMin = Math.min(0, ...allEffY) - 2;
const effYMax = Math.max(...allEffY) + 2;

new Chart(effCtx, {{
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
                min: 0, max: 105,
                ticks: {{ color: '#888' }}, grid: {{ color: 'rgba(255,255,255,0.04)' }}
            }},
            y: {{
                type: 'linear',
                title: {{ display: true, text: 'Avg ROM (%)', color: '#aaa' }},
                min: effYMin, max: effYMax,
                ticks: {{ color: '#888' }}, grid: {{ color: 'rgba(255,255,255,0.04)' }}
            }}
        }}
    }}
}});

// ── Retention Table ─────────────────────────────────────────────────────
const tbl = document.getElementById('compTable');
const fmt = (v, d=2) => v.toFixed(d);
const cls = v => v >= 0 ? 'delta-pos' : 'delta-neg';
const fmtD = (v, d=2) => (v >= 0 ? '+' : '') + v.toFixed(d);

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
    tb += '<td>' + ref.gtN + '</td><td>' + fmt(ref.gtN/N*100,1) + '%</td>';
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
    tb += '<td>' + ref.ltN + '</td><td>' + fmt(ref.ltN/N*100,1) + '%</td>';
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
    tb += '<td>' + ref.n + '</td><td>' + fmt(ref.n/N*100,1) + '%</td>';
    tb += '<td>' + fmt(ref.wr,1) + '%</td><td>' + fmt(ref.pf) + '</td>';
    tb += '<td>$' + fmt(ref.pl) + '</td>';
    tb += '<td style="font-size:0.75em;color:#ccc">' + loOO + ' + ' + hiOO + '</td></tr>';
}}

tb += '</tbody>';
tbl.innerHTML = th + tb;
</script>
</body></html>'''


if __name__ == '__main__':
    # If run directly, show usage
    print("This is a shared module. Import and call generate() from a block-specific wrapper.")
    print("See SKILL.md for wrapper examples.")
