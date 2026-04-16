#!/usr/bin/env python3
"""
Shared entry filter retention heatmap generator.
Block-specific scripts import this and call generate() with a config dict.

Usage from a block-specific wrapper:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'Alex-TradeBlocks-Skills'))
    from gen_heatmap import generate

    generate({
        'block_folder': '/path/to/block',
        'block_name':   '20250926 - SPX DC 5-7 22.5-15d oF',
    })
"""

import csv
import os


SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
GROUPS_CSV_DEFAULT = os.path.join(SKILLS_DIR, "entry_filter_groups.default.csv")

TARGETS = [90, 80, 70, 60, 50, 40, 30, 20, 10]
MIN_TRADES = 10
MIN_TRADE_PCT = 10.0  # % of total


# ── Retention computation ────────────────────────────────────────────────────

def compute_retention_min(vals_roms, baseline_ror, total_trades, targets):
    """Min direction (>= threshold). vals_roms = list of (val, rom)."""
    unique_vals = sorted(set(v for v, _ in vals_roms))
    results = {}
    for target in targets:
        best = None
        for t in unique_vals:
            survivors = [(v, r) for v, r in vals_roms if v >= t]
            if len(survivors) < MIN_TRADES or len(survivors) < total_trades * MIN_TRADE_PCT / 100:
                continue
            ret = sum(r for _, r in survivors) / baseline_ror * 100 if baseline_ror != 0 else 0
            avg_rom = sum(r for _, r in survivors) / len(survivors)
            if ret >= target:
                best = {
                    "threshold": t, "trades": len(survivors),
                    "avg_rom": avg_rom, "retention": ret,
                    "delta_pp": avg_rom - (baseline_ror / total_trades)
                }
        results[target] = best
    return results


def compute_retention_max(vals_roms, baseline_ror, total_trades, targets):
    """Max direction (<= threshold)."""
    unique_vals = sorted(set(v for v, _ in vals_roms), reverse=True)
    results = {}
    for target in targets:
        best = None
        for t in unique_vals:
            survivors = [(v, r) for v, r in vals_roms if v <= t]
            if len(survivors) < MIN_TRADES or len(survivors) < total_trades * MIN_TRADE_PCT / 100:
                continue
            ret = sum(r for _, r in survivors) / baseline_ror * 100 if baseline_ror != 0 else 0
            avg_rom = sum(r for _, r in survivors) / len(survivors)
            if ret >= target:
                best = {
                    "threshold": t, "trades": len(survivors),
                    "avg_rom": avg_rom, "retention": ret,
                    "delta_pp": avg_rom - (baseline_ror / total_trades)
                }
        results[target] = best
    return results


def compute_retention_combo(vals_roms, baseline_ror, total_trades, targets):
    """Combo: find best [min, max] range maximizing Avg ROM while meeting retention target."""
    unique_vals = sorted(set(v for v, _ in vals_roms))
    results = {}
    for target in targets:
        best = None
        best_avg = -999
        for i, lo in enumerate(unique_vals):
            for hi in reversed(unique_vals[i:]):
                survivors = [(v, r) for v, r in vals_roms if lo <= v <= hi]
                if len(survivors) < MIN_TRADES or len(survivors) < total_trades * MIN_TRADE_PCT / 100:
                    continue
                ret = sum(r for _, r in survivors) / baseline_ror * 100 if baseline_ror != 0 else 0
                avg_rom = sum(r for _, r in survivors) / len(survivors)
                if ret >= target and avg_rom > best_avg:
                    best_avg = avg_rom
                    best = {
                        "lo": lo, "hi": hi, "trades": len(survivors),
                        "avg_rom": avg_rom, "retention": ret,
                        "delta_pp": avg_rom - (baseline_ror / total_trades)
                    }
        results[target] = best
    return results


# ── Format helpers ───────────────────────────────────────────────────────────

def fmt_threshold(val, col):
    if col == "SLR":
        return f"{val:.4f}"
    elif col in ("VIX9D_VIX_Ratio",):
        return f"{val:.2f}"
    elif abs(val) < 1:
        return f"{val:.2f}"
    elif abs(val) >= 100:
        return f"{val:.0f}"
    else:
        return f"{val:.2f}"


def fmt_pp(delta):
    if delta >= 0:
        return f"+{delta:.1f}pp"
    return f"{delta:.1f}pp"


def delta_to_color(delta_pp, max_pos_delta, max_neg_delta):
    """Color based on delta pp vs baseline. Scale anchored at 80r% range."""
    if delta_pp >= 0:
        intensity = min(delta_pp / max_pos_delta, 1.0) if max_pos_delta > 0 else 0
        alpha = 0.08 + intensity * 0.47
        return f"rgba(46,204,113,{alpha:.2f})"
    else:
        intensity = min(abs(delta_pp) / abs(max_neg_delta), 1.0) if max_neg_delta < 0 else 0
        alpha = 0.08 + intensity * 0.47
        return f"rgba(231,76,60,{alpha:.2f})"


# ── Main generate function ──────────────────────────────────────────────────

def generate(config):
    """
    Generate entry_filter_heatmap.html for the given block.

    Config keys:
        block_folder  (str): Absolute path to the block folder
        block_name    (str): Display name for subtitle (e.g. '20250926 - SPX DC 5-7 22.5-15d oF')
        groups_csv    (str, optional): Override path to entry_filter_groups CSV
    """
    block_folder = config['block_folder']
    block_name = config['block_name']
    groups_csv = config.get('groups_csv', GROUPS_CSV_DEFAULT)

    data_csv = os.path.join(block_folder, "alex-tradeblocks-ref", "entry_filter_data.csv")
    out_html = os.path.join(block_folder, "entry_filter_heatmap.html")

    # ── Load data ────────────────────────────────────────────────────────────
    with open(data_csv, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        trades = list(reader)

    with open(groups_csv, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        groups_raw = list(reader)

    # Parse trade data
    for t in trades:
        t["rom_pct"] = float(t["rom_pct"])
        t["pl_per_contract"] = float(t["pl_per_contract"])

    total_trades = len(trades)
    baseline_net_ror = sum(t["rom_pct"] for t in trades)
    baseline_avg_rom = baseline_net_ror / total_trades
    baseline_wr = sum(1 for t in trades if t["rom_pct"] > 0) / total_trades * 100

    # Profit factor
    gross_profit = sum(t["rom_pct"] for t in trades if t["rom_pct"] > 0)
    gross_loss = abs(sum(t["rom_pct"] for t in trades if t["rom_pct"] < 0))
    baseline_pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # ── Filter groups ────────────────────────────────────────────────────────
    report_filters = []
    for g in groups_raw:
        rv1 = g.get("Report V1", "").strip()
        csv_col = g.get("CSV Column", "").strip()
        if rv1 and rv1.upper() != "FALSE" and csv_col:
            report_filters.append(g)

    # Classify
    continuous_filters = []
    binary_filters = []
    categorical_filters = []

    seen_cols = {}
    for f in report_filters:
        ft = f.get("Filter Type", "").strip().lower()
        col = f["CSV Column"].strip()
        idx = int(f["Index"].strip())
        name = f["Filter"].strip()
        short_name = f.get("Short Name", name).strip() or name
        entry_group = f["Entry Group"].strip()

        if ft == "continuous":
            if col not in seen_cols:
                seen_cols[col] = {
                    "index": idx, "name": name, "short_name": short_name, "col": col,
                    "group": entry_group, "type": "continuous"
                }
            elif idx < seen_cols[col]["index"]:
                seen_cols[col]["index"] = idx
                seen_cols[col]["name"] = name
                seen_cols[col]["short_name"] = short_name
        elif ft == "binary":
            if col not in seen_cols:
                seen_cols[col] = {
                    "index": idx, "name": name, "short_name": short_name, "col": col,
                    "group": entry_group, "type": "binary"
                }
        elif ft == "categorical":
            if col not in seen_cols:
                seen_cols[col] = {
                    "index": idx, "name": name, "short_name": short_name, "col": col,
                    "group": entry_group, "type": "categorical"
                }

    for k, v in seen_cols.items():
        if v["type"] == "continuous":
            continuous_filters.append(v)
        elif v["type"] == "binary":
            binary_filters.append(v)
        elif v["type"] == "categorical":
            categorical_filters.append(v)

    continuous_filters.sort(key=lambda x: (x["group"], x["index"]))
    binary_filters.sort(key=lambda x: (x["group"], x["index"]))
    categorical_filters.sort(key=lambda x: (x["group"], x["index"]))

    # ── Compute all filter results ───────────────────────────────────────────
    print("Computing retention thresholds...")

    filter_results = {}
    filter_meta = {}

    for filt in continuous_filters:
        col = filt["col"]
        idx = filt["index"]
        name = filt["name"]
        filter_meta[idx] = filt

        vals_roms = []
        null_count = 0
        for t in trades:
            v = t.get(col, "").strip()
            if v == "" or v.lower() == "null" or v.lower() == "none":
                null_count += 1
                continue
            try:
                vals_roms.append((float(v), t["rom_pct"]))
            except ValueError:
                null_count += 1

        if null_count > len(trades) * 0.1:
            print(f"  Skipping {name} (>{10}% nulls)")
            continue

        print(f"  {idx}: {name} ({len(vals_roms)} values)")

        min_res = compute_retention_min(vals_roms, baseline_net_ror, total_trades, TARGETS)
        max_res = compute_retention_max(vals_roms, baseline_net_ror, total_trades, TARGETS)
        combo_res = compute_retention_combo(vals_roms, baseline_net_ror, total_trades, TARGETS)

        filter_results[(idx, "Min")] = min_res
        filter_results[(idx, "Max")] = max_res
        filter_results[(idx, "Combo")] = combo_res

    # ── Compute binary/categorical summaries ─────────────────────────────────
    binary_results = {}
    for filt in binary_filters:
        col = filt["col"]
        idx = filt["index"]
        filter_meta[idx] = filt
        categories = {}
        for t in trades:
            v = t.get(col, "").strip()
            if v == "" or v.lower() == "null":
                continue
            if v not in categories:
                categories[v] = []
            categories[v].append(t["rom_pct"])
        binary_results[idx] = {}
        for cat, roms in sorted(categories.items()):
            n = len(roms)
            avg_rom = sum(roms) / n
            net_ror = sum(roms)
            pct_baseline = net_ror / baseline_net_ror * 100 if baseline_net_ror != 0 else 0
            wr = sum(1 for r in roms if r > 0) / n * 100
            gp = sum(r for r in roms if r > 0)
            gl = abs(sum(r for r in roms if r < 0))
            pf = gp / gl if gl > 0 else float("inf")
            label = f"Yes ({cat})" if cat == "1" else f"No ({cat})"
            binary_results[idx][label] = {
                "trades": n, "pct_trades": n / total_trades * 100,
                "avg_rom": avg_rom, "delta_pp": avg_rom - baseline_avg_rom,
                "net_ror": net_ror, "pct_baseline": pct_baseline,
                "wr": wr, "pf": pf
            }

    categorical_results = {}
    CAT_LABELS = {
        "Day_of_Week": {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri"},
        "Month": {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
                  7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"},
        "Term_Structure_State": {-1: "Backwardation", 0: "Flat", 1: "Contango"},
        "Vol_Regime": {}
    }

    for filt in categorical_filters:
        col = filt["col"]
        idx = filt["index"]
        filter_meta[idx] = filt
        categories = {}
        for t in trades:
            v = t.get(col, "").strip()
            if v == "" or v.lower() == "null":
                continue
            categories[v] = categories.get(v, [])
            categories[v].append(t["rom_pct"])

        label_map = CAT_LABELS.get(col, {})
        categorical_results[idx] = {}

        sorted_keys = sorted(categories.keys(), key=lambda x: float(x) if x.replace("-", "").replace(".", "").isdigit() else x)

        # Weeks_to/from_Holiday: only show 0-3, aggregate 4+ into one bucket
        if col in ("Weeks_to_Holiday", "Weeks_from_Holiday"):
            capped = {}
            for cat in sorted_keys:
                try:
                    iv = int(float(cat))
                except (ValueError, TypeError):
                    continue
                bucket = str(iv) if iv <= 3 else "4+"
                capped.setdefault(bucket, []).extend(categories[cat])
            categories = capped
            sorted_keys = sorted(categories.keys(), key=lambda x: float(x) if x != "4+" else 4.5)

        for cat in sorted_keys:
            roms = categories[cat]
            n = len(roms)
            avg_rom = sum(roms) / n
            net_ror = sum(roms)
            pct_baseline = net_ror / baseline_net_ror * 100 if baseline_net_ror != 0 else 0
            wr = sum(1 for r in roms if r > 0) / n * 100
            gp = sum(r for r in roms if r > 0)
            gl = abs(sum(r for r in roms if r < 0))
            pf = gp / gl if gl > 0 else float("inf")
            try:
                label = label_map.get(int(float(cat)), cat)
            except (ValueError, TypeError):
                label = cat
            categorical_results[idx][label] = {
                "trades": n, "pct_trades": n / total_trades * 100,
                "avg_rom": avg_rom, "delta_pp": avg_rom - baseline_avg_rom,
                "net_ror": net_ror, "pct_baseline": pct_baseline,
                "wr": wr, "pf": pf
            }

    # ── Color function: vs baseline, anchored at 80r% ───────────────────────
    all_80r_deltas = []
    for key, res in filter_results.items():
        if 80 in res and res[80] is not None:
            all_80r_deltas.append(res[80]["delta_pp"])

    for idx, cats in binary_results.items():
        for label, data in cats.items():
            all_80r_deltas.append(data["delta_pp"])
    for idx, cats in categorical_results.items():
        for label, data in cats.items():
            all_80r_deltas.append(data["delta_pp"])

    max_pos_delta = max((d for d in all_80r_deltas if d > 0), default=1.0)
    max_neg_delta = min((d for d in all_80r_deltas if d < 0), default=-1.0)

    # ── Build Discovery Map data ────────────────────────────────────────────
    disc_columns = []
    for filt in continuous_filters:
        idx = filt["index"]
        for d in ["Min", "Max"]:
            key = (idx, d)
            if key in filter_results:
                disc_columns.append(key)

    def sort_key_80r(col):
        res = filter_results.get(col, {}).get(80)
        if res is None:
            return -999
        return res["delta_pp"]

    disc_columns.sort(key=sort_key_80r, reverse=True)

    dir_symbols = {"Min": "^", "Max": "v", "Combo": "<>"}

    # ── Generate HTML ────────────────────────────────────────────────────────
    print("Generating HTML...")

    html = []
    h = html.append

    h('<!DOCTYPE html>')
    h('<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">')
    h('<title>Entry Filter Retention Heatmap</title>')
    h('<style>')
    h('*{margin:0;padding:0;box-sizing:border-box}')
    h("body{background:#1a1a2e;color:#e0e0e0;font-family:'Segoe UI',system-ui,sans-serif;padding:20px 30px}")
    h('h1{font-size:1.4em;color:#fff;margin-bottom:4px}')
    h('h3{font-size:1.05em;color:#fff;margin:20px 0 8px}')
    h('.subtitle{color:#aaa;font-size:0.85em;margin-bottom:16px}')
    h('.metrics-row{display:flex;gap:14px;margin-bottom:16px;flex-wrap:wrap}')
    h('.metric-card{background:#16213e;border-radius:6px;padding:8px 14px;min-width:110px}')
    h('.metric-card .val{font-size:1.3em;font-weight:700;color:#fff}')
    h('.metric-card .lbl{font-size:0.72em;color:#888;margin-top:2px}')
    h('table{border-collapse:collapse;font-size:0.82em;width:100%;margin-bottom:20px}')
    h('th{background:#0f3460;color:#888;padding:8px 10px;text-transform:uppercase;font-size:0.72em;letter-spacing:0.5px;white-space:nowrap}')
    h('td{padding:7px 10px;text-align:center;border-bottom:1px solid rgba(255,255,255,0.05)}')
    h('.group-hdr td{background:#0f3460;color:#f39c12;font-weight:700;text-align:left;font-size:0.85em;padding:6px 10px}')
    h('.filter-name{text-align:left;font-weight:600;color:#ccc;vertical-align:middle;white-space:nowrap}')
    h('.dir-cell{color:#888;font-size:0.78em;white-space:nowrap}')
    h('.cv{font-size:12px;font-weight:700;color:#fff}')
    h('.cs{font-size:8.5px;color:rgba(255,255,255,0.45);margin-top:1px}')
    h('.na{color:#555;font-style:italic;font-size:0.78em;text-align:left;padding-left:16px}')
    h('.combo-row td{border-top:1px solid rgba(255,255,255,0.08)}')
    h('.dim{color:#444}')
    h('.cat-table th{font-size:0.7em}')
    h('.cat-table td{font-size:0.8em;padding:5px 8px}')
    h('.cat-table .rom-cell{font-weight:700}')
    h('.disc-table{width:100%;margin-bottom:24px}')
    h('.disc-table th{writing-mode:vertical-lr;transform:rotate(180deg);text-align:left;padding:4px 2px;font-size:0.68em;min-width:20px;height:80px;white-space:nowrap;letter-spacing:0.3px}')
    h('.disc-table td{padding:3px;min-width:20px;height:18px;border:1px solid rgba(255,255,255,0.04)}')
    h('.disc-table td.disc-label{text-align:left;font-size:0.78em;color:#aaa;white-space:nowrap;width:auto;padding:3px 8px;font-weight:600}')
    h('</style></head><body>')

    # Title & subtitle
    h('<h1>Entry Filter Retention Heatmap</h1>')
    h(f'<div class="subtitle">{block_name} &nbsp;|&nbsp; {total_trades} trades &nbsp;|&nbsp; '
      f'Baseline Net ROR: {baseline_net_ror:.1f}% &nbsp;|&nbsp; Baseline Avg ROM: {baseline_avg_rom:.2f}% &nbsp;|&nbsp; '
      f'Min 10 trades / 10% of total &nbsp;|&nbsp; Color &amp; sort keyed at 80r%</div>')

    # Metrics row
    h('<div class="metrics-row">')
    h(f'<div class="metric-card"><div class="val">{total_trades}</div><div class="lbl">Total Trades</div></div>')
    h(f'<div class="metric-card"><div class="val">{baseline_net_ror:.1f}%</div><div class="lbl">Baseline Net ROR</div></div>')
    h(f'<div class="metric-card"><div class="val">{baseline_avg_rom:.2f}%</div><div class="lbl">Baseline Avg ROM</div></div>')
    h(f'<div class="metric-card"><div class="val">{baseline_wr:.1f}%</div><div class="lbl">Win Rate</div></div>')
    h(f'<div class="metric-card"><div class="val">{baseline_pf:.2f}</div><div class="lbl">Profit Factor</div></div>')
    h('</div>')

    # ════════════════════════════════════════════════════════════════════════
    # DISCOVERY MAP
    # ════════════════════════════════════════════════════════════════════════
    h('<h3>Discovery Map</h3>')
    h('<table class="disc-table"><thead><tr><th style="writing-mode:horizontal-tb;transform:none;height:auto"></th>')

    for idx, d in disc_columns:
        name = filter_meta[idx]["name"]
        short = filter_meta[idx].get("short_name", str(idx))
        sym = dir_symbols[d]
        h(f'<th title="{name} {d}">{short}{sym}</th>')

    h('</tr></thead><tbody>')

    for target in TARGETS:
        h(f'<tr><td class="disc-label">{target}r%</td>')
        for idx, d in disc_columns:
            res = filter_results.get((idx, d), {}).get(target)
            if res is None:
                h('<td class="dim" style="background:#16213e"></td>')
            else:
                color = delta_to_color(res["delta_pp"], max_pos_delta, max_neg_delta)
                name = filter_meta[idx]["name"]
                col = filter_meta[idx]["col"]
                if d == "Combo":
                    thr_str = f"[{res['lo']:.2f}, {res['hi']:.2f}]"
                else:
                    thr_str = f"{'>='.format() if d=='Min' else '<='}{fmt_threshold(res['threshold'], col)}"
                tip = (f"{name} {d} @ {target}r%\n"
                       f"Threshold: {thr_str}\n"
                       f"{res['trades']} trades | Avg ROM: {res['avg_rom']:.2f}% ({fmt_pp(res['delta_pp'])})\n"
                       f"Retention: {res['retention']:.1f}%")
                h(f'<td style="background:{color}" title="{tip}"></td>')
        h('</tr>')

    h('</tbody></table>')

    # ════════════════════════════════════════════════════════════════════════
    # MAIN HEATMAP TABLE
    # ════════════════════════════════════════════════════════════════════════
    h('<h3>Retention Detail</h3>')
    h('<table><thead><tr>')
    h('<th style="text-align:left">Entry Filter</th>')
    h('<th>Dir</th>')
    for t in TARGETS:
        h(f'<th>{t}r%</th>')
    h('</tr></thead><tbody>')

    current_group = None
    for filt in continuous_filters:
        idx = filt["index"]
        name = filt["name"]
        col = filt["col"]
        group = filt["group"]

        if group != current_group:
            current_group = group
            h(f'<tr class="group-hdr"><td colspan="11">{group}</td></tr>')

        if (idx, "Min") not in filter_results:
            continue

        for row_idx, d in enumerate(["Min", "Max", "Combo"]):
            res_map = filter_results.get((idx, d), {})
            row_class = ' class="combo-row"' if d == "Combo" else ""

            if row_idx == 0:
                h(f'<tr><td class="filter-name" rowspan="3">{name}</td>')
            else:
                h(f'<tr{row_class}>')

            h(f'<td class="dir-cell">{d}</td>')

            for target in TARGETS:
                res = res_map.get(target)
                if res is None:
                    h('<td class="dim">-</td>')
                else:
                    color = delta_to_color(res["delta_pp"], max_pos_delta, max_neg_delta)
                    pp = fmt_pp(res["delta_pp"])

                    if d == "Combo":
                        thr_str = f"[{fmt_threshold(res['lo'], col)},{fmt_threshold(res['hi'], col)}]"
                        sub = f"{thr_str} {res['trades']}t"
                        tip_thr = f"Range: [{fmt_threshold(res['lo'], col)}, {fmt_threshold(res['hi'], col)}]"
                    elif d == "Min":
                        thr_str = f"&gt;={fmt_threshold(res['threshold'], col)}"
                        sub = f"{thr_str} | {res['trades']}t"
                        tip_thr = f"Threshold: >={fmt_threshold(res['threshold'], col)}"
                    else:
                        thr_str = f"&lt;={fmt_threshold(res['threshold'], col)}"
                        sub = f"{thr_str} | {res['trades']}t"
                        tip_thr = f"Threshold: <={fmt_threshold(res['threshold'], col)}"

                    tip = f"{tip_thr} | {res['trades']} trades | Avg ROM: {res['avg_rom']:.2f}% ({pp}) | Retention: {res['retention']:.1f}%"
                    h(f'<td style="background:{color}" title="{tip}"><div class="cv">{pp}</div><div class="cs">{sub}</div></td>')

            h('</tr>')

    # Binary/categorical inline in main table
    for filt in binary_filters:
        idx = filt["index"]
        name = filt["name"]
        group = filt["group"]
        if group != current_group:
            current_group = group
            h(f'<tr class="group-hdr"><td colspan="11">{group}</td></tr>')

        parts = []
        for label, data in binary_results.get(idx, {}).items():
            pp = fmt_pp(data["delta_pp"])
            parts.append(f"{label}: {pp} ({data['trades']}t)")
        summary = " | ".join(parts)
        h(f'<tr><td class="filter-name">{name}</td><td class="dir-cell">--</td>')
        h(f'<td colspan="9" class="na">{summary}</td></tr>')

    for filt in categorical_filters:
        idx = filt["index"]
        name = filt["name"]
        group = filt["group"]
        if group != current_group:
            current_group = group
            h(f'<tr class="group-hdr"><td colspan="11">{group}</td></tr>')

        parts = []
        for label, data in categorical_results.get(idx, {}).items():
            pp = fmt_pp(data["delta_pp"])
            parts.append(f"{label}: {pp} ({data['trades']}t)")
        summary = " | ".join(parts)
        h(f'<tr><td class="filter-name">{name}</td><td class="dir-cell">--</td>')
        h(f'<td colspan="9" class="na">{summary}</td></tr>')

    h('</tbody></table>')

    # ════════════════════════════════════════════════════════════════════════
    # BINARY & CATEGORICAL BREAKDOWN TABLE
    # ════════════════════════════════════════════════════════════════════════
    h('<h3>Binary &amp; Categorical Filter Breakdown</h3>')
    h('<table class="cat-table"><thead><tr>')
    h('<th style="text-align:left">Filter</th><th>Category</th><th>Avg ROM</th><th>vs Baseline</th>')
    h('<th>% Trades</th><th>% Net ROR</th><th>PF</th><th>WR</th>')
    h('</tr></thead><tbody>')

    for idx, cats in binary_results.items():
        name = filter_meta[idx]["name"]
        first = True
        n_cats = len(cats)
        for label, data in cats.items():
            color = delta_to_color(data["delta_pp"], max_pos_delta, max_neg_delta)
            pp = fmt_pp(data["delta_pp"])
            if first:
                h(f'<tr><td class="filter-name" rowspan="{n_cats}">{name}</td>')
                first = False
            else:
                h('<tr>')
            h(f'<td>{label}</td>')
            h(f'<td class="rom-cell" style="background:{color}">{data["avg_rom"]:.2f}%</td>')
            h(f'<td style="background:{color}">{pp}</td>')
            h(f'<td>{data["pct_trades"]:.1f}%</td>')
            h(f'<td>{data["pct_baseline"]:.1f}%</td>')
            pf_str = f'{data["pf"]:.2f}' if data["pf"] != float("inf") else "inf"
            h(f'<td>{pf_str}</td>')
            h(f'<td>{data["wr"]:.1f}%</td>')
            h('</tr>')

    for idx, cats in categorical_results.items():
        name = filter_meta[idx]["name"]
        first = True
        n_cats = len(cats)
        for label, data in cats.items():
            color = delta_to_color(data["delta_pp"], max_pos_delta, max_neg_delta)
            pp = fmt_pp(data["delta_pp"])
            if first:
                h(f'<tr><td class="filter-name" rowspan="{n_cats}">{name}</td>')
                first = False
            else:
                h('<tr>')
            h(f'<td>{label}</td>')
            h(f'<td class="rom-cell" style="background:{color}">{data["avg_rom"]:.2f}%</td>')
            h(f'<td style="background:{color}">{pp}</td>')
            h(f'<td>{data["pct_trades"]:.1f}%</td>')
            h(f'<td>{data["pct_baseline"]:.1f}%</td>')
            pf_str = f'{data["pf"]:.2f}' if data["pf"] != float("inf") else "inf"
            h(f'<td>{pf_str}</td>')
            h(f'<td>{data["wr"]:.1f}%</td>')
            h('</tr>')

    h('</tbody></table>')
    h('</body></html>')

    # Write output
    with open(out_html, "w", encoding="utf-8") as f:
        f.write("\n".join(html))

    print(f"Written to {out_html}")
    print(f"Color scale: green max at +{max_pos_delta:.1f}pp, red max at {max_neg_delta:.1f}pp (from 80r%)")
    return out_html


# Allow direct execution for testing
if __name__ == "__main__":
    print("This module is meant to be imported. Use a block-specific wrapper script.")
    print("Example wrapper:")
    print('    from gen_heatmap import generate')
    print('    generate({"block_folder": "/path/to/block", "block_name": "My Block"})')
