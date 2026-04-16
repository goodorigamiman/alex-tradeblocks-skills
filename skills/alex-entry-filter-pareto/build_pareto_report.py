#!/usr/bin/env python3
"""
Shared entry filter Pareto report generator.
Block-specific scripts import this and call generate() with a config dict.

Usage from a block-specific wrapper:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '_shared'))
    from build_pareto_report import generate

    generate({
        'block_folder': '/path/to/block',
        'block_name':   '20250926 - SPX DC 5-7 22.5-15d oF',
    })
"""

import csv
import json
import math
import os


SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
GROUPS_CSV_DEFAULT = os.path.join(SKILLS_DIR, "entry_filter_groups.default.csv")


# ── Helpers ──────────────────────────────────────────────────────────────────

def compute_metrics(subset):
    """Compute Avg ROR, Net ROR, PF, WR, count from a list of trades"""
    roms = [t['rom_pct'] for t in subset if t['rom_pct'] is not None]
    if not roms:
        return None
    n = len(roms)
    avg_ror = sum(roms) / n
    net_ror = sum(roms)
    pos = sum(r for r in roms if r > 0)
    neg = abs(sum(r for r in roms if r < 0))
    pf = pos / neg if neg > 0 else float('inf')
    wins = sum(1 for r in roms if r > 0)
    wr = wins / n * 100
    return {'avg_ror': avg_ror, 'net_ror': net_ror, 'pf': pf, 'wr': wr, 'n': n}


def pearson_r(xs, ys):
    """Compute Pearson correlation between two lists"""
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 10:
        return None
    n = len(pairs)
    sx = sum(x for x, _ in pairs)
    sy = sum(y for _, y in pairs)
    sxx = sum(x*x for x, _ in pairs)
    syy = sum(y*y for _, y in pairs)
    sxy = sum(x*y for x, y in pairs)
    denom = math.sqrt((n*sxx - sx*sx) * (n*syy - sy*sy))
    if denom == 0:
        return 0.0
    return (n*sxy - sx*sy) / denom


def get_filter_values(trades, csv_col):
    """Get (value, trade) pairs for a filter column"""
    pairs = []
    for t in trades:
        raw = t.get(csv_col, '')
        if raw is None:
            continue
        raw = str(raw).strip()
        if raw == '' or raw.lower() == 'null':
            continue
        try:
            pairs.append((float(raw), t))
        except ValueError:
            continue
    return pairs


def sweep_continuous(trades, csv_col, baseline_avg, min_trades=30):
    """Full resolution threshold sweep. Returns best recommendation."""
    pairs = get_filter_values(trades, csv_col)
    if len(pairs) < min_trades:
        return None

    values = sorted(set(v for v, _ in pairs))
    if len(values) < 3:
        return None

    best = None
    best_avg = baseline_avg

    for thresh in values:
        # Try >= threshold
        above = [t for v, t in pairs if v >= thresh]
        if len(above) >= min_trades:
            m = compute_metrics(above)
            if m and m['avg_ror'] > best_avg:
                best = {'dir': '>=', 'thresh': thresh, 'metrics': m}
                best_avg = m['avg_ror']

        # Try < threshold
        below = [t for v, t in pairs if v < thresh]
        if len(below) >= min_trades:
            m = compute_metrics(below)
            if m and m['avg_ror'] > best_avg:
                best = {'dir': '<', 'thresh': thresh, 'metrics': m}
                best_avg = m['avg_ror']

    # Also try <= threshold
    for thresh in values:
        leq = [t for v, t in pairs if v <= thresh]
        if len(leq) >= min_trades:
            m = compute_metrics(leq)
            if m and m['avg_ror'] > best_avg:
                best = {'dir': '<=', 'thresh': thresh, 'metrics': m}
                best_avg = m['avg_ror']

    return best


def compare_binary(trades, csv_col):
    """Compare TRUE(1) vs FALSE(0) groups"""
    pairs = get_filter_values(trades, csv_col)
    if not pairs:
        return None
    group1 = [t for v, t in pairs if v == 1]
    group0 = [t for v, t in pairs if v == 0]
    m1 = compute_metrics(group1) if group1 else None
    m0 = compute_metrics(group0) if group0 else None
    return {'true': m1, 'false': m0}


def compare_categorical(trades, csv_col):
    """Compare each category"""
    pairs = get_filter_values(trades, csv_col)
    if not pairs:
        return None

    # Weeks_to/from_Holiday: cap at 0-3, aggregate 4+
    if csv_col in ('Weeks_to_Holiday', 'Weeks_from_Holiday'):
        capped = []
        for v, t in pairs:
            try:
                iv = int(v)
            except (ValueError, TypeError):
                continue
            bucket = iv if iv <= 3 else 4
            capped.append((bucket, t))
        pairs = capped

    categories = sorted(set(v for v, _ in pairs))
    results = {}
    for cat in categories:
        label = f"{cat}+" if cat == 4 and csv_col in ('Weeks_to_Holiday', 'Weeks_from_Holiday') else str(cat)
        subset = [t for v, t in pairs if v == cat]
        m = compute_metrics(subset)
        if m:
            results[label] = m
    return results


LABEL_MAP = {
    'VIX level threshold': 'VIX Close',
    'VIX overnight gap': 'VIX Gap',
    'VIX9D-to-VIX ratio': 'VIX9D/VIX',
    'VIX IV Rank': 'VIX IVR',
    'VIX IV Percentile': 'VIX IVP',
    'VIX spike magnitude': 'VIX Spike',
    'RSI momentum filter': 'RSI 14',
    'Price vs simple moving average': 'SMA50 %',
    'Prior day return': 'Prev Return',
    'ATR as % of price': 'ATR %',
    'Underlying gap or move from open': 'Gap %',
    'Margin per contract': 'Margin/K',
    '5-day realized volatility': 'RV5',
    'Net credit per contract': 'Prem/K',
    'Short-to-long premium ratio': 'SLR',
    '5-day trailing return': 'Ret 5D',
    'Price vs exponential moving average': 'EMA21',
}

GROUP_SORT_ORDER = {
    'A: Volatility Level': 0, 'B: Relative Volatility': 1, 'C: Momentum / Trend': 2,
    'D: Daily Price Action': 3, 'E: Calendar': 4, 'F: Term Structure': 5,
    'G: VIX Event': 6, 'H: Premium & Structure': 7,
}

GROUP_ORDER = [
    'A: Volatility Level',
    'B: Relative Volatility',
    'C: Momentum / Trend',
    'D: Daily Price Action',
    'E: Calendar',
    'F: Term Structure',
    'G: VIX Event',
    'H: Premium & Structure',
]

GROUP_COLORS = {
    'A: Volatility Level': '#e67e22',
    'B: Relative Volatility': '#9b59b6',
    'C: Momentum / Trend': '#2ecc71',
    'D: Daily Price Action': '#3498db',
    'E: Calendar': '#1abc9c',
    'F: Term Structure': '#e74c3c',
    'G: VIX Event': '#f39c12',
    'H: Premium & Structure': '#95a5a6',
}

GROUP_SHORT = {
    'A: Volatility Level': 'A: Vol Level',
    'B: Relative Volatility': 'B: Rel Vol',
    'C: Momentum / Trend': 'C: Momentum',
    'D: Daily Price Action': 'D: Price Action',
    'E: Calendar': 'E: Calendar',
    'F: Term Structure': 'F: Term Str',
    'G: VIX Event': 'G: VIX Event',
    'H: Premium & Structure': 'H: Premium',
}

CAT_LABELS = {
    'Term_Structure_State': {-1: 'Backwardation', 0: 'Flat', 1: 'Contango'},
    'Day_of_Week': {1: 'Mon', 2: 'Tue', 3: 'Wed', 4: 'Thu', 5: 'Fri'},
    'Month': {1:'Jan',2:'Feb',3:'Mar',4:'Apr',5:'May',6:'Jun',7:'Jul',8:'Aug',9:'Sep',10:'Oct',11:'Nov',12:'Dec'},
}


def fmt_num(v, decimals=1):
    if v is None: return '--'
    if abs(v) >= 1000:
        return f"{v:,.{decimals}f}"
    return f"{v:.{decimals}f}"


def fmt_pct(v, decimals=1):
    if v is None: return '--'
    return f"{v:.{decimals}f}%"


def group_color(group_letter):
    colors = {
        'A': '#e67e22', 'B': '#9b59b6', 'C': '#2ecc71', 'D': '#3498db',
        'E': '#1abc9c', 'F': '#e74c3c', 'G': '#f39c12', 'H': '#95a5a6',
    }
    return colors.get(group_letter, '#888888')


def hex_to_rgb(color):
    """Convert #RRGGBB or #RGB to 'R,G,B' string."""
    h = color.lstrip('#')
    if len(h) == 3:
        h = h[0]*2 + h[1]*2 + h[2]*2
    return ",".join(str(int(h[i:i+2], 16)) for i in (0, 2, 4))


# ── Main generate function ──────────────────────────────────────────────────

def generate(config):
    """
    Generate filter_pareto.html for the given block.

    Config keys:
        block_folder  (str): Absolute path to the block folder
        block_name    (str): Display name for subtitle
        groups_csv    (str, optional): Override path to entry_filter_groups CSV
    """
    block_folder = config['block_folder']
    block_name = config['block_name']
    groups_csv = config.get('groups_csv', GROUPS_CSV_DEFAULT)

    data_csv = os.path.join(block_folder, "alex-tradeblocks-ref", "entry_filter_data.csv")
    out_html = os.path.join(block_folder, "filter_pareto.html")

    # ── Load data ──
    with open(data_csv) as f:
        reader = csv.DictReader(f)
        trades = [r for r in reader]

    for t in trades:
        t['rom_pct'] = float(t['rom_pct']) if t['rom_pct'] else None
        t['pl_per_contract'] = float(t['pl_per_contract']) if t.get('pl_per_contract') else None
        t['margin_per_contract'] = float(t['margin_per_contract']) if t.get('margin_per_contract') else None

    with open(groups_csv) as f:
        reader = csv.DictReader(f)
        groups = [r for r in reader]

    report_filters = [g for g in groups if g['Report V1'] == 'TRUE' and g['CSV Column'].strip()]

    # ── Baseline ──
    baseline = compute_metrics(trades)
    print(f"Baseline: {baseline['n']} trades, Avg ROR {baseline['avg_ror']:.2f}%, Net ROR {baseline['net_ror']:.2f}%, PF {baseline['pf']:.2f}, WR {baseline['wr']:.1f}%")

    # ── Compute correlation with ROM for each filter ──
    rom_values = [t['rom_pct'] for t in trades]

    # ── Process all Report V1 filters ──
    continuous_results = []
    binary_results = []
    categorical_results = []

    for filt in report_filters:
        csv_col = filt['CSV Column'].strip()
        ftype = filt['Filter Type'].strip()
        entry_group = filt['Entry Group'].strip()
        label = filt['Filter'].strip()

        filter_vals = []
        for t in trades:
            raw = t.get(csv_col, '')
            if raw is None:
                filter_vals.append(None)
                continue
            raw = str(raw).strip()
            try:
                filter_vals.append(float(raw) if raw and raw.lower() != 'null' else None)
            except ValueError:
                filter_vals.append(None)

        corr = pearson_r(filter_vals, rom_values)

        if ftype == 'continuous':
            result = sweep_continuous(trades, csv_col, baseline['avg_ror'])
            if result:
                result['csv_col'] = csv_col
                result['label'] = label
                result['entry_group'] = entry_group
                result['corr'] = corr
                result['index'] = int(filt['Index'])
                continuous_results.append(result)
            else:
                continuous_results.append({
                    'csv_col': csv_col, 'label': label, 'entry_group': entry_group,
                    'corr': corr, 'index': int(filt['Index']),
                    'dir': '--', 'thresh': None,
                    'metrics': baseline
                })

        elif ftype == 'binary':
            result = compare_binary(trades, csv_col)
            if result:
                result['csv_col'] = csv_col
                result['label'] = label
                result['entry_group'] = entry_group
                result['corr'] = corr
                result['index'] = int(filt['Index'])
                binary_results.append(result)

        elif ftype == 'categorical':
            result = compare_categorical(trades, csv_col)
            if result:
                categorical_results.append({
                    'csv_col': csv_col, 'label': label, 'entry_group': entry_group,
                    'corr': corr, 'index': int(filt['Index']),
                    'categories': result
                })

    continuous_results.sort(key=lambda x: (GROUP_SORT_ORDER.get(x['entry_group'], 99), x['index']))

    print(f"\nContinuous filters with recommendations: {len([r for r in continuous_results if r['thresh'] is not None])}")
    print(f"Binary filters: {len(binary_results)}")
    print(f"Categorical filters: {len(categorical_results)}")

    for r in continuous_results:
        m = r['metrics']
        if r['thresh'] is not None:
            corr_str = f", corr={r['corr']:.3f}" if r['corr'] else ""
            print(f"  {r['label']}: {r['dir']} {r['thresh']:.2f} -> Avg {m['avg_ror']:.2f}%, {m['n']} trades{corr_str}")

    # ── Build all detail rows (organized by Entry Group) ──
    all_detail_rows = []

    for r in continuous_results:
        m = r['metrics']
        if r['thresh'] is not None:
            thresh_str = f"{r['dir']} {r['thresh']:.2f}" if abs(r['thresh']) < 1000 else f"{r['dir']} {r['thresh']:,.0f}"
        else:
            thresh_str = '--'
        all_detail_rows.append({
            'label': r['label'],
            'csv_col': r['csv_col'],
            'entry_group': r['entry_group'],
            'type': 'continuous',
            'threshold': thresh_str,
            'avg_ror': m['avg_ror'],
            'net_ror': m['net_ror'],
            'pf': m['pf'],
            'wr': m['wr'],
            'n': m['n'],
            'corr': r['corr'],
            'index': r['index'],
        })

    for r in binary_results:
        mt = r.get('true')
        mf = r.get('false')
        if mt and mf:
            if mt['avg_ror'] >= mf['avg_ror']:
                best_m, best_label = mt, '= TRUE (1)'
            else:
                best_m, best_label = mf, '= FALSE (0)'
        elif mt:
            best_m, best_label = mt, '= TRUE (1)'
        else:
            best_m, best_label = mf, '= FALSE (0)'

        all_detail_rows.append({
            'label': r['label'],
            'csv_col': r['csv_col'],
            'entry_group': r['entry_group'],
            'type': 'binary',
            'threshold': best_label,
            'avg_ror': best_m['avg_ror'],
            'net_ror': best_m['net_ror'],
            'pf': best_m['pf'],
            'wr': best_m['wr'],
            'n': best_m['n'],
            'corr': r['corr'],
            'index': r['index'],
            'detail_true': mt,
            'detail_false': mf,
        })

    for r in categorical_results:
        cats = r['categories']
        if not cats:
            continue
        total_in_cats = sum(c['n'] for c in cats.values())
        single_cat = len(cats) == 1 or any(c['n'] == total_in_cats for c in cats.values())

        if single_cat:
            only_cat = max(cats.items(), key=lambda x: x[1]['n'])
            all_detail_rows.append({
                'label': r['label'],
                'csv_col': r['csv_col'],
                'entry_group': r['entry_group'],
                'type': 'categorical',
                'threshold': f'All = {only_cat[0]}',
                'avg_ror': only_cat[1]['avg_ror'],
                'net_ror': only_cat[1]['net_ror'],
                'pf': only_cat[1]['pf'],
                'wr': only_cat[1]['wr'],
                'n': only_cat[1]['n'],
                'corr': r['corr'],
                'index': r['index'],
                'uninformative': True,
                'categories': cats,
            })
        else:
            best_cat = max(cats.items(), key=lambda x: x[1]['avg_ror'])
            cat_label_map = CAT_LABELS.get(r['csv_col'], {})
            try:
                cat_key = int(float(best_cat[0]))
            except (ValueError, TypeError):
                cat_key = best_cat[0]
            cat_name = cat_label_map.get(cat_key, str(best_cat[0]))

            all_detail_rows.append({
                'label': r['label'],
                'csv_col': r['csv_col'],
                'entry_group': r['entry_group'],
                'type': 'categorical',
                'threshold': f'Best: {cat_name} ({best_cat[0]})',
                'avg_ror': best_cat[1]['avg_ror'],
                'net_ror': best_cat[1]['net_ror'],
                'pf': best_cat[1]['pf'],
                'wr': best_cat[1]['wr'],
                'n': best_cat[1]['n'],
                'corr': r['corr'],
                'index': r['index'],
                'categories': cats,
            })

    # ── Build chart data (continuous only, with recommendations) ──
    chart_filters = [r for r in continuous_results if r['thresh'] is not None]
    chart_labels = ['Baseline'] + [LABEL_MAP.get(r['label'], r['label']) for r in chart_filters]
    chart_avg_ror = [round(baseline['avg_ror'], 2)] + [round(r['metrics']['avg_ror'], 2) for r in chart_filters]
    chart_net_ror_raw = [round(baseline['net_ror'], 1)] + [round(r['metrics']['net_ror'], 1) for r in chart_filters]
    chart_net_ror_pct = [100.0] + [round(r['metrics']['net_ror'] / baseline['net_ror'] * 100, 1) for r in chart_filters]
    chart_trades = [baseline['n']] + [r['metrics']['n'] for r in chart_filters]
    chart_pct_kept = [100.0] + [round(r['metrics']['n'] / baseline['n'] * 100, 1) for r in chart_filters]
    chart_thresh = ['--'] + [f"{r['dir']} {r['thresh']:.2f}" if abs(r['thresh']) < 1000 else f"{r['dir']} {r['thresh']:,.0f}" for r in chart_filters]

    max_avg = max(chart_avg_ror) + 5
    y_avg_max = math.ceil(max_avg / 5) * 5

    chart_group_labels = ['--'] + [r['entry_group'] for r in chart_filters]
    chart_groups_for_js = json.dumps(chart_group_labels)

    group_spans = {}
    for i, r in enumerate(chart_filters):
        g = r['entry_group']
        idx = i + 1
        if g not in group_spans:
            group_spans[g] = [idx, idx]
        else:
            group_spans[g][1] = idx

    # Build annotation JS objects for group bands + labels
    group_annotations_js = ""
    for g, (first, last) in group_spans.items():
        color = GROUP_COLORS.get(g, '#888')
        short = GROUP_SHORT.get(g, g)
        band_id = g[0].lower() + 'Band'
        label_id = g[0].lower() + 'Label'
        rgb = hex_to_rgb(color)
        group_annotations_js += f"""
          {band_id}: {{
            type: 'box',
            xMin: {first} - 0.5, xMax: {last} + 0.5,
            yMin: 0, yMax: {y_avg_max},
            yScaleID: 'yAvg',
            backgroundColor: 'rgba({rgb}, 0.06)',
            borderColor: 'rgba({rgb}, 0.25)',
            borderWidth: 1,
            borderRadius: 4,
          }},
          {label_id}: {{
            type: 'label',
            xValue: {(first + last) / 2},
            yValue: {y_avg_max - 1.5},
            yScaleID: 'yAvg',
            content: '{short}',
            color: '{color}',
            font: {{ size: 10, weight: '700' }},
            backgroundColor: 'rgba(22, 33, 62, 0.85)',
            padding: {{ top: 2, bottom: 2, left: 5, right: 5 }},
            borderRadius: 3,
          }},"""

    # ── Organize detail rows by Entry Group ──
    grouped_rows = {}
    for g in GROUP_ORDER:
        grouped_rows[g] = []

    for row in all_detail_rows:
        g = row['entry_group']
        if g in grouped_rows:
            grouped_rows[g].append(row)

    for g in grouped_rows:
        grouped_rows[g].sort(key=lambda x: x['avg_ror'], reverse=True)

    # ── Identify recommended filters ──
    recommended = set()
    for r in continuous_results:
        if r['thresh'] is not None and r['metrics']['avg_ror'] >= baseline['avg_ror'] + 2.0 and r['metrics']['n'] >= 30:
            recommended.add(r['csv_col'])

    for row in all_detail_rows:
        if row['type'] in ('binary', 'categorical') and not row.get('uninformative'):
            if row['avg_ror'] >= baseline['avg_ror'] + 2.0 and row['n'] >= 30:
                recommended.add(row['csv_col'])

    # ── Find redundant recommended pairs ──
    rec_by_group = {}
    for row in all_detail_rows:
        if row['csv_col'] in recommended:
            g = row['entry_group']
            rec_by_group.setdefault(g, []).append(row['label'])

    redundant_notes = []
    for g, labels in rec_by_group.items():
        if len(labels) > 1:
            redundant_notes.append(f"{g}: {', '.join(labels)} are in the same correlation cluster -- pick one representative")

    # ── Best overall recommendation ──
    best_tradeoff = None
    for r in continuous_results:
        if r['thresh'] is not None and r['metrics']['n'] >= 30:
            net_pct = r['metrics']['net_ror'] / baseline['net_ror'] * 100
            if net_pct >= 70 and (best_tradeoff is None or r['metrics']['avg_ror'] > best_tradeoff['metrics']['avg_ror']):
                best_tradeoff = r

    # ── Build detail table HTML ──
    detail_html = ""
    for g in GROUP_ORDER:
        rows = grouped_rows[g]
        if not rows:
            continue

        letter = g[0]
        color = group_color(letter)
        rgb = hex_to_rgb(color)
        detail_html += f'      <tr class="group-header"><td colspan="10" style="background:rgba({rgb},0.12); color:{color}; font-weight:700; font-size:12px; padding:10px 14px; letter-spacing:0.5px;">{g}</td></tr>\n'

        for row in rows:
            is_rec = row['csv_col'] in recommended
            delta_pp = row['avg_ror'] - baseline['avg_ror']
            net_delta = row['net_ror'] - baseline['net_ror']
            pct_kept = row['n'] / baseline['n'] * 100

            label_short = LABEL_MAP.get(row['label'], row['label'])
            tags = ''
            if is_rec:
                tags += ' <span class="tag tag-strong">Rec</span>'
            if row.get('uninformative'):
                tags += ' <span class="tag tag-weak">N/A</span>'
            if row['type'] == 'binary':
                tags += ' <span class="tag tag-moderate">Binary</span>'
            elif row['type'] == 'categorical':
                tags += ' <span class="tag tag-moderate">Cat</span>'

            thresh_display = row['threshold']

            avg_cls = 'positive' if delta_pp >= 2 else ('highlight' if delta_pp > 0 else 'negative')
            delta_cls = 'positive' if delta_pp >= 2 else ('neutral' if abs(delta_pp) < 0.5 else 'negative')
            net_cls = 'positive' if row['net_ror'] >= baseline['net_ror'] * 0.8 else 'negative'
            net_d_cls = 'positive' if net_delta >= 0 else ('neutral' if net_delta > -baseline['net_ror'] * 0.2 else 'negative')
            wr_cls = 'positive' if row['wr'] > baseline['wr'] + 2 else ('neutral' if row['wr'] >= baseline['wr'] - 2 else 'negative')
            kept_cls = 'positive' if pct_kept >= 70 else ('neutral' if pct_kept >= 40 else 'negative')
            corr_str = f"{row['corr']:+.3f}" if row['corr'] is not None else '--'
            corr_cls = 'positive' if row['corr'] and abs(row['corr']) >= 0.1 else 'neutral'

            detail_html += f'      <tr>\n'
            detail_html += f'        <td>{label_short}{tags}<span class="threshold">{thresh_display}</span></td>\n'
            detail_html += f'        <td class="{avg_cls}">{fmt_pct(row["avg_ror"])}</td>\n'
            detail_html += f'        <td class="{delta_cls}">{delta_pp:+.1f}pp</td>\n'
            detail_html += f'        <td class="{net_cls}">{fmt_num(row["net_ror"])}%</td>\n'
            detail_html += f'        <td class="{net_d_cls}">{net_delta:+,.0f}</td>\n'
            detail_html += f'        <td class="highlight">{fmt_num(row["pf"], 2)}</td>\n'
            detail_html += f'        <td class="{wr_cls}">{fmt_pct(row["wr"])}</td>\n'
            detail_html += f'        <td>{row["n"]}</td>\n'
            detail_html += f'        <td class="{kept_cls}">{pct_kept:.0f}%</td>\n'
            detail_html += f'        <td class="{corr_cls}">{corr_str}</td>\n'
            detail_html += f'      </tr>\n'

    # ── Build verdict ──
    verdict_lines = []
    if best_tradeoff:
        bt_label = LABEL_MAP.get(best_tradeoff['label'], best_tradeoff['label'])
        bt_m = best_tradeoff['metrics']
        bt_net_pct = bt_m['net_ror'] / baseline['net_ror'] * 100
        verdict_lines.append(f"<strong>Best tradeoff filter: {bt_label} {best_tradeoff['dir']} {best_tradeoff['thresh']:.2f}</strong> -- "
                            f"+{bt_m['avg_ror'] - baseline['avg_ror']:.1f}pp Avg ROR ({bt_m['avg_ror']:.1f}%) while retaining "
                            f"{bt_net_pct:.0f}% of Net ROR and {bt_m['n']}/{baseline['n']} trades ({bt_m['n']/baseline['n']*100:.0f}%).")

    rec_count = len(recommended)
    verdict_lines.append(f"<br><br><strong>{rec_count} filters</strong> improve Avg ROR by >=2pp with >=30 trades.")

    if redundant_notes:
        verdict_lines.append("<br><br><strong>Redundancy warnings:</strong><br>" + "<br>".join(f"&bull; {n}" for n in redundant_notes))

    for row in all_detail_rows:
        if row['type'] == 'binary' and row['csv_col'] in recommended:
            label_short = LABEL_MAP.get(row['label'], row['label'])
            verdict_lines.append(f"<br><br><strong>{label_short}:</strong> {row['threshold']} -> {row['avg_ror']:.1f}% Avg ROR ({row['n']} trades).")

    for row in all_detail_rows:
        if row['type'] == 'categorical' and not row.get('uninformative') and row['csv_col'] in recommended:
            label_short = LABEL_MAP.get(row['label'], row['label'])
            verdict_lines.append(f"<br><br><strong>{label_short}:</strong> {row['threshold']} -> {row['avg_ror']:.1f}% Avg ROR ({row['n']} trades).")

    for row in all_detail_rows:
        if row.get('uninformative') and row['csv_col'] == 'Day_of_Week':
            verdict_lines.append(f"<br><br><em>Day of Week: all {baseline['n']} trades on Friday (Day 5) -- uninformative for this strategy.</em>")

    verdict_html = "\n".join(verdict_lines)

    # ── Assemble HTML ──
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Entry Filter Pareto -- {block_name}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.1.0/dist/chartjs-plugin-annotation.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #1a1a2e; color: #e0e0e0; font-family: 'Inter', -apple-system, sans-serif; padding: 24px; max-width: 1500px; margin: 0 auto; }}
  .header {{ margin-bottom: 20px; }}
  .header h1 {{ font-size: 18px; color: #fff; font-weight: 600; }}
  .header .subtitle {{ font-size: 13px; color: #888; margin-top: 4px; }}
  .chart-container {{ background: #16213e; border-radius: 12px; padding: 24px; }}
  .legend-bar {{ display: flex; gap: 24px; justify-content: center; margin-bottom: 16px; flex-wrap: wrap; }}
  .legend-item {{ display: flex; align-items: center; gap: 6px; font-size: 12px; color: #aaa; }}
  .legend-swatch {{ width: 14px; height: 14px; border-radius: 3px; }}
  .legend-line {{ width: 20px; height: 3px; border-radius: 2px; }}
  canvas {{ max-height: 500px; }}

  .detail-section {{ margin-top: 24px; }}
  .detail-section h2 {{ font-size: 14px; color: #aaa; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 12px; }}
  .detail-table {{ width: 100%; border-collapse: collapse; background: #16213e; border-radius: 12px; overflow: hidden; }}
  .detail-table thead th {{ background: #0f3460; padding: 12px 14px; text-align: center; font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; border-bottom: 2px solid #1a1a2e; }}
  .detail-table thead th:first-child {{ text-align: left; }}
  .detail-table tbody td {{ padding: 10px 14px; text-align: center; font-size: 13px; font-weight: 600; border-bottom: 1px solid rgba(255,255,255,0.05); }}
  .detail-table tbody td:first-child {{ text-align: left; font-size: 12px; font-weight: 500; }}
  .detail-table tbody tr.baseline td {{ color: #888; }}
  .detail-table tbody tr.baseline td:first-child {{ color: #f39c12; }}
  .detail-table tbody tr.group-header td {{ border-bottom: 1px solid rgba(255,255,255,0.08); }}
  .detail-table tbody tr td:first-child .threshold {{ display: block; font-size: 11px; color: #666; margin-top: 2px; }}
  .detail-table tbody tr td.positive {{ color: #2ecc71; }}
  .detail-table tbody tr td.negative {{ color: #e74c3c; }}
  .detail-table tbody tr td.neutral {{ color: #888; }}
  .detail-table tbody tr td.highlight {{ color: #fff; }}
  .tag {{ display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 700; margin-left: 4px; vertical-align: middle; }}
  .tag-strong {{ background: rgba(46, 204, 113, 0.15); color: #2ecc71; }}
  .tag-moderate {{ background: rgba(52, 152, 219, 0.15); color: #3498db; }}
  .tag-weak {{ background: rgba(231, 76, 60, 0.15); color: #e74c3c; }}
  .tag-best {{ background: rgba(243, 156, 18, 0.15); color: #f39c12; }}
  .method-note {{ font-size: 11px; color: #555; margin-top: 8px; text-align: right; }}
  .verdict {{ margin-top: 20px; background: #0f3460; border-radius: 8px; padding: 16px; font-size: 13px; line-height: 1.6; }}
  .verdict strong {{ color: #f39c12; }}
  .verdict em {{ color: #888; }}
</style>
</head>
<body>

<div class="header">
  <h1>Entry Filter Pareto -- Avg ROR vs Net ROR</h1>
  <div class="subtitle">{block_name} &nbsp;|&nbsp; {baseline['n']} trades &nbsp;|&nbsp; Baseline: {baseline['avg_ror']:.1f}% Avg ROR, {baseline['net_ror']:,.0f}% Net ROR, PF {baseline['pf']:.2f}, WR {baseline['wr']:.1f}% &nbsp;|&nbsp; {len(report_filters)} Report V1 filters &nbsp;|&nbsp; v2.0</div>
</div>

<div class="chart-container">
  <div class="legend-bar">
    <div class="legend-item"><div class="legend-swatch" style="background:#e67e22;"></div> Avg ROR % (per-trade, then averaged)</div>
    <div class="legend-item"><div class="legend-swatch" style="background:#3498db;"></div> % of Baseline Net ROR (retained cumulative return)</div>
    <div class="legend-item"><div class="legend-line" style="background:rgba(255,255,255,0.3);border-top:2px dashed rgba(255,255,255,0.3);height:0;"></div> Baseline Avg ROR ({baseline['avg_ror']:.1f}%)</div>
  </div>
  <canvas id="paretoChart"></canvas>
</div>

<div class="detail-section">
  <h2>Filter Comparison Detail -- Organized by Entry Group</h2>
  <table class="detail-table">
    <thead>
      <tr>
        <th style="min-width:180px;">Filter</th>
        <th>Avg ROR %</th>
        <th>vs Base</th>
        <th>Net ROR %</th>
        <th>vs Base</th>
        <th>Profit Factor</th>
        <th>Win Rate</th>
        <th>Trades</th>
        <th>% Kept</th>
        <th>Corr w/ ROM</th>
      </tr>
    </thead>
    <tbody>
      <tr class="baseline">
        <td>Baseline (no filter) <span class="tag tag-best">Reference</span></td>
        <td>{baseline['avg_ror']:.1f}%</td>
        <td class="neutral">--</td>
        <td>{baseline['net_ror']:,.0f}%</td>
        <td class="neutral">--</td>
        <td>{baseline['pf']:.2f}</td>
        <td>{baseline['wr']:.1f}%</td>
        <td>{baseline['n']}</td>
        <td>100%</td>
        <td class="neutral">--</td>
      </tr>
{detail_html}    </tbody>
  </table>
  <div class="method-note">ROM = per-trade P/L / margin, then averaged. Net ROR = simple sum of individual trade ROMs. Profit Factor = SUM(+ROMs) / |SUM(-ROMs)|. Prior-day lag on close-derived fields to prevent lookahead. Rec = >=2pp above baseline with >=30 trades.</div>
</div>

<div class="verdict">
{verdict_html}
</div>

<script>
const labels = {json.dumps(chart_labels)};
const avgROR = {json.dumps(chart_avg_ror)};
const netRORraw = {json.dumps(chart_net_ror_raw)};
const netROR = {json.dumps(chart_net_ror_pct)};
const trades_arr = {json.dumps(chart_trades)};
const pctKept = {json.dumps(chart_pct_kept)};
const thresholds = {json.dumps(chart_thresh)};
const groupLabels = {chart_groups_for_js};
const baselineAvg = {baseline['avg_ror']:.2f};

const ctx = document.getElementById('paretoChart').getContext('2d');

new Chart(ctx, {{
  type: 'bar',
  data: {{
    labels: labels,
    datasets: [
      {{
        label: 'Avg ROR %',
        data: avgROR,
        backgroundColor: avgROR.map((v, i) => i === 0 ? 'rgba(243, 156, 18, 0.5)' : 'rgba(230, 126, 34, 0.7)'),
        borderColor: avgROR.map((v, i) => i === 0 ? '#f39c12' : '#e67e22'),
        borderWidth: 1,
        yAxisID: 'yAvg',
        order: 2,
        borderRadius: 4,
        barPercentage: 0.8,
        categoryPercentage: 0.75,
      }},
      {{
        label: 'Net ROR %',
        data: netROR,
        backgroundColor: netROR.map((v, i) => i === 0 ? 'rgba(52, 152, 219, 0.4)' : 'rgba(52, 152, 219, 0.7)'),
        borderColor: '#3498db',
        borderWidth: 1,
        yAxisID: 'yNet',
        order: 1,
        borderRadius: 4,
        barPercentage: 0.8,
        categoryPercentage: 0.75,
      }}
    ]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: true,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{
        backgroundColor: '#1a1a2e',
        borderColor: '#444',
        borderWidth: 1,
        titleColor: '#fff',
        bodyColor: '#ccc',
        padding: 12,
        callbacks: {{
          afterBody: function(items) {{
            const idx = items[0].dataIndex;
            return [
              '',
              'Group: ' + groupLabels[idx],
              'Threshold: ' + thresholds[idx],
              'Trades: ' + trades_arr[idx] + ' (' + pctKept[idx].toFixed(1) + '% kept)',
              'Avg ROR delta: ' + (avgROR[idx] - baselineAvg >= 0 ? '+' : '') + (avgROR[idx] - baselineAvg).toFixed(1) + 'pp',
              'Net ROR retained: ' + netROR[idx].toFixed(1) + '% of baseline (' + netRORraw[idx].toLocaleString() + '%)',
            ];
          }}
        }}
      }},
      annotation: {{
        annotations: {{
          baselineAvg: {{
            type: 'line',
            yMin: baselineAvg, yMax: baselineAvg,
            yScaleID: 'yAvg',
            borderColor: 'rgba(255, 255, 255, 0.35)',
            borderWidth: 2,
            borderDash: [6, 4],
            label: {{
              display: true,
              content: 'Baseline Avg ROR ' + baselineAvg.toFixed(1) + '%',
              position: 'start',
              color: '#999',
              font: {{ size: 10 }},
              backgroundColor: 'rgba(26, 26, 46, 0.8)',
              padding: 4
            }}
          }},{group_annotations_js}
        }}
      }}
    }},
    scales: {{
      x: {{
        ticks: {{
          color: '#aaa',
          font: {{ size: 10, weight: '600' }},
          maxRotation: 45,
          minRotation: 45,
        }},
        grid: {{ display: false }},
      }},
      yAvg: {{
        type: 'linear',
        position: 'left',
        title: {{ display: true, text: 'Avg ROR %', color: '#e67e22', font: {{ size: 12, weight: '600' }} }},
        min: 0,
        max: {y_avg_max},
        ticks: {{ color: '#e67e22', callback: v => v + '%', stepSize: 5 }},
        grid: {{ color: 'rgba(255,255,255,0.04)' }},
      }},
      yNet: {{
        type: 'linear',
        position: 'right',
        title: {{ display: true, text: '% of Baseline Net ROR', color: '#3498db', font: {{ size: 12, weight: '600' }} }},
        min: 0,
        max: 110,
        ticks: {{ color: '#3498db', callback: v => v + '%', stepSize: 20 }},
        grid: {{ display: false }},
      }},
    }},
  }}
}});
</script>

</body>
</html>
"""

    with open(out_html, 'w') as f:
        f.write(html)

    print(f"\nWritten to {out_html}")
    print(f"  Chart: {len(chart_filters)} continuous filters + baseline = {len(chart_labels)} bars")
    print(f"  Table: {len(all_detail_rows)} detail rows across {sum(1 for g in GROUP_ORDER if grouped_rows[g])} entry groups")
    print(f"  Recommended: {len(recommended)} filters (>=2pp, >=30 trades)")
    return out_html


# Allow direct execution for testing
if __name__ == "__main__":
    print("This module is meant to be imported. Use a block-specific wrapper script.")
    print("Example wrapper:")
    print('    from build_pareto_report import generate')
    print('    generate({"block_folder": "/path/to/block", "block_name": "My Block"})')
