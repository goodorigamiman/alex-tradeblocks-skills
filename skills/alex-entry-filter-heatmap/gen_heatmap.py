#!/usr/bin/env python3
"""
alex-entry-filter-heatmap — CLI driver.

Builds the entry-filter retention heatmap for a block. Reads only two block-local
CSVs; never builds data itself.

    python3 gen_heatmap.py BLOCK_ID \\
        [--tb-root PATH] \\
        [--groups-csv PATH] \\
        [--heatmap-col NAME] \\
        [--filter-by "COLUMN=VALUE"] \\
        [--list]

Inputs (both block-local):
    {block}/alex-tradeblocks-ref/entry_filter_data.csv
    {block}/alex-tradeblocks-ref/entry_filter_groups.*.csv

Output:
    {block}/entry filter heatmap.html

Filter selection: every row where the column named by --heatmap-col (default:
"Report Heatmap") is TRUE. Narrow further with --filter-by "COLUMN=VALUE".

See SKILL.md for exit codes and full workflow.
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


TB_ROOT_DEFAULT = "/Users/alexanderhardt/Library/CloudStorage/OneDrive-AIACOTechnology/Documents - AIACO Trading Development/Pipeline Data/TradeBlocks Data"

# Exit codes — match the threshold-analysis skill for consistency.
EXIT_OK = 0
# Exit code 2 (previously EXIT_MISSING_DATA_CSV) is retired — the heatmap no
# longer reads entry_filter_data.csv. The sweep CSVs cover every number the
# report renders. Missing sweep CSVs still exit with EXIT_MISSING_SWEEP_CSV (8).
EXIT_MISSING_GROUPS_CSV = 3
EXIT_MULTIPLE_GROUPS_CSV = 4
EXIT_HEATMAP_COL_MISSING = 5
EXIT_FILTER_BY_ERROR = 6
EXIT_MISSING_SWEEP_CSV = 8

REQUIRED_GROUPS_COLS = {"Index", "Filter", "Short Name", "CSV Column", "Entry Group"}

MIN_TRADES = 10
MIN_TRADE_PCT = 10.0  # % of total
# TARGETS are now inherited from the sweep CSV at load time — we use whatever
# retention columns the sweep produced, in 5% increments from the data-driven
# ceiling (one blank above max_observed) down to R_0.


# ── Path resolution (copy verbatim from gen_threshold_analysis.py) ───────────

def resolve_block_folder(tb_root: pathlib.Path, block_id: str) -> pathlib.Path:
    p = tb_root / block_id
    if not p.is_dir():
        raise RuntimeError(f"block folder not found: {p}")
    return p


def resolve_groups_csv(
    ref_folder: pathlib.Path,
    explicit: Optional[pathlib.Path] = None,
) -> Tuple[pathlib.Path, str]:
    """Return (path, source_tag). Block-local only — no shared fallback at runtime."""
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
    return [r for r in groups if (r.get(col) or "").strip().lower() == val_lower]


def select_heatmap_filters(
    groups: List[Dict],
    col_name: str,
    extra_expr: Optional[str],
) -> List[Dict]:
    """
    Narrow `groups` to rows where `col_name` is TRUE, then AND with --filter-by.
    Raises RuntimeError with a specific exit-5 or exit-6 hint if inputs are bad.
    """
    if not groups:
        return groups
    if col_name not in groups[0]:
        available = [c for c in groups[0].keys() if c.startswith("Report")] or sorted(groups[0].keys())
        raise RuntimeError(
            f"HEATMAP_COL_MISSING: column {col_name!r} not in groups CSV.\n"
            f"Available 'Report' columns: {available}\n"
            f"Either add a {col_name!r} column to the groups CSV, or pass "
            f"--heatmap-col NAME to use a different column (e.g., --heatmap-col \"Report V1\")."
        )
    primary = [r for r in groups if (r.get(col_name) or "").strip().upper() == "TRUE"]
    narrowed = apply_filter_by(primary, extra_expr)
    narrowed.sort(key=lambda r: int(r["Index"]) if (r.get("Index") or "").strip().isdigit() else 10**9)
    return narrowed


# ── Sweep CSV loading (replaces the old compute_retention_* functions) ──────

def resolve_sweep_csv(ref_folder: pathlib.Path) -> pathlib.Path:
    p = ref_folder / "entry_filter_threshold_results.csv"
    if not p.is_file():
        raise FileNotFoundError(
            f"entry_filter_threshold_results.csv not found in {ref_folder}.\n"
            f"Run /alex-entry-filter-threshold-sweep BLOCK_ID first to build it."
        )
    return p


def resolve_cat_sweep_csv(ref_folder: pathlib.Path) -> pathlib.Path:
    p = ref_folder / "entry_filter_categorical_results.csv"
    if not p.is_file():
        raise FileNotFoundError(
            f"entry_filter_categorical_results.csv not found in {ref_folder}.\n"
            f"Run /alex-entry-filter-threshold-sweep BLOCK_ID first to build it."
        )
    return p


def load_block_baselines(path: pathlib.Path) -> Dict[str, float]:
    """
    Read block-wide baselines (total_trades, baseline_avg_ror, baseline_avg_pcr,
    baseline_wr, baseline_pf) from the continuous sweep CSV. These values are
    constants repeated across every row — we take the first AvgROR row and one
    AvgPCR row to pick up both metric baselines.
    """
    with open(path, "r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    total_trades = 0
    base_ror = None
    base_pcr = None
    base_wr = None
    base_pf_str = None
    for r in rows:
        if not total_trades:
            try:
                total_trades = int(r.get("total_trades") or 0)
            except ValueError:
                pass
        if base_wr is None:
            try:
                base_wr = float(r.get("baseline_wr") or 0.0)
            except ValueError:
                pass
        if base_pf_str is None:
            base_pf_str = (r.get("baseline_pf") or "").strip()
        m = (r.get("metric") or "").strip()
        if m == "AvgROR" and base_ror is None:
            try:
                base_ror = float(r.get("baseline_avg") or 0.0)
            except ValueError:
                pass
        if m == "AvgPCR" and base_pcr is None:
            try:
                base_pcr = float(r.get("baseline_avg") or 0.0)
            except ValueError:
                pass
        if total_trades and base_ror is not None and base_pcr is not None and base_wr is not None and base_pf_str is not None:
            break
    try:
        base_pf = float(base_pf_str) if base_pf_str not in ("", "inf") else float("inf")
    except ValueError:
        base_pf = float("inf")
    return {
        "total_trades": total_trades or 0,
        "baseline_avg_ror": base_ror or 0.0,
        "baseline_avg_pcr": base_pcr or 0.0,
        "baseline_wr": base_wr or 0.0,
        "baseline_pf": base_pf,
    }


def load_categorical_sweep(path: pathlib.Path, metric: str = "AvgROR") -> Dict[str, List[Dict]]:
    """
    Return {csv_column: [category_row, ...]} for the requested metric, preserving
    CSV row order (which the sweep writes in Index order + natural category sort).
    Each category_row has numeric in/out stats already parsed.
    """
    out: Dict[str, List[Dict]] = {}
    with open(path, "r", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if (r.get("metric") or "").strip() != metric:
                continue
            col = (r.get("csv_column") or "").strip()
            if not col:
                continue

            def fnum(k):
                v = (r.get(k) or "").strip()
                if not v:
                    return None
                try:
                    return float(v)
                except ValueError:
                    return None

            def fint(k):
                v = (r.get(k) or "").strip()
                if not v:
                    return 0
                try:
                    return int(v)
                except ValueError:
                    return 0

            out.setdefault(col, []).append({
                "category_value": (r.get("category_value") or "").strip(),
                "category_label": (r.get("category_label") or "").strip(),
                "baseline_avg":   fnum("baseline_avg") or 0.0,
                "total_trades":   fint("total_trades"),
                "in_trades":      fint("in_sample_trades"),
                "in_avg":         fnum("in_sample"),
                "in_wr":          fnum("in_sample_wr"),
                "out_trades":     fint("out_sample_trades"),
                "out_avg":        fnum("out_sample"),
                "out_wr":         fnum("out_sample_wr"),
            })
    return out


# Sweep CSV direction → heatmap internal direction label.
_DIR_MAP = {
    "low threshold":  "Min",
    "high threshold": "Max",
    "combo":          "Combo",
}


def load_sweep(
    path: pathlib.Path,
    metric: str = "AvgROR",
    variant: str = "max_avg",
) -> Tuple[Dict, List[int], Dict[str, float]]:
    """
    Load the sweep CSV and pivot into the structure the heatmap renderer expects.

    Pulls both the avg metric rows AND the matching threshold rows (ThresholdROR
    for AvgROR; ThresholdPCR for AvgPCR) so cell tooltips can show the actual
    threshold value that produced the avg.

    Returns:
      filter_results: { (csv_column, direction): { target_int: {"avg": float,
                          "delta_pp": float, "threshold": str} } }
      targets:        sorted list of target ints (descending, as in the CSV header)
      baselines:      { csv_column: baseline_avg (float) }
    """
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])

    target_cols = [c for c in fieldnames if c.startswith("R_")]
    def parse_T(c): return int(c[2:])
    targets_ordered = [parse_T(c) for c in target_cols]

    # Matching threshold metric for the requested avg metric.
    thr_metric = "ThresholdROR" if metric == "AvgROR" else "ThresholdPCR"

    # First pass: collect thresholds keyed by (col, direction, target).
    thresholds: Dict[Tuple[str, str, int], str] = {}
    for row in rows:
        if (row.get("metric") or "").strip() != thr_metric:
            continue
        if (row.get("variant") or "").strip() != variant:
            continue
        col = (row.get("csv_column") or "").strip()
        direction = _DIR_MAP.get((row.get("direction") or "").strip())
        if not col or not direction:
            continue
        for tcol, T in zip(target_cols, targets_ordered):
            cell = (row.get(tcol) or "").strip()
            if cell:
                thresholds[(col, direction, T)] = cell

    # Second pass: avg rows + thresholds joined.
    filter_results: Dict = {}
    baselines: Dict[str, float] = {}
    for row in rows:
        if (row.get("metric") or "").strip() != metric:
            continue
        if (row.get("variant") or "").strip() != variant:
            continue
        col = (row.get("csv_column") or "").strip()
        direction = _DIR_MAP.get((row.get("direction") or "").strip())
        if not col or not direction:
            continue
        try:
            base = float(row.get("baseline_avg") or 0.0)
        except ValueError:
            base = 0.0
        baselines[col] = base

        per_target: Dict[int, Dict] = {}
        for tcol, T in zip(target_cols, targets_ordered):
            cell = (row.get(tcol) or "").strip()
            if not cell:
                continue
            try:
                avg = float(cell)
            except ValueError:
                continue
            per_target[T] = {
                "avg": avg,
                "delta_pp": avg - base,
                "threshold": thresholds.get((col, direction, T), ""),
            }
        filter_results[(col, direction)] = per_target

    return filter_results, sorted(set(targets_ordered), reverse=True), baselines


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


def _fmt_num(s: str) -> str:
    """Format a numeric string for display — 3 decimals, trailing zeros stripped."""
    try:
        n = float(s)
    except (ValueError, TypeError):
        return s
    out = f"{n:.3f}"
    if "." in out:
        out = out.rstrip("0").rstrip(".")
    return out if out else "0"


def fmt_threshold_expr(direction: str, thr: str, csv_col: str) -> str:
    """Render a threshold as a filter expression: 'SLR >= 0.47', 'SLR <= 0.6', 'SLR ∈ [0.3, 0.7]'."""
    if not thr:
        return ""
    if "|" in thr:  # combo
        lo, _, hi = thr.partition("|")
        return f"{csv_col} \u2208 [{_fmt_num(lo)}, {_fmt_num(hi)}]"
    op = ">=" if direction == "Min" else "<="
    return f"{csv_col} {op} {_fmt_num(thr)}"


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


# ── HTML-safe escape ─────────────────────────────────────────────────────────

def esc(s: str) -> str:
    return (str(s).replace("&", "&amp;")
                  .replace("<", "&lt;")
                  .replace(">", "&gt;")
                  .replace('"', "&quot;"))


# ── Main generator (preserved structure, updated labels) ─────────────────────

def _generate(config):
    """Generate entry filter heatmap HTML and return the output path.

    Data sources (all block-local, read-only):
      groups_csv      — filter registry (labels, short names, Entry Group, Filter Type)
      sweep_csv       — continuous threshold sweep results (has block baselines)
      cat_sweep_csv   — categorical/binary per-category in/out-sample stats

    The heatmap never reads entry_filter_data.csv directly — everything it
    needs lives in the sweep CSVs.
    """
    block_folder = config["block_folder"]
    block_name = config["block_name"]
    groups_csv = config["groups_csv"]
    sweep_csv = config["sweep_csv"]                 # continuous sweep
    cat_sweep_csv = config["cat_sweep_csv"]         # categorical + binary sweep
    selected_filters = config["selected_filters"]
    out_html = config["out_html"]
    heatmap_col = config["heatmap_col"]
    sweep_metric = config.get("sweep_metric", "AvgROR")
    sweep_variant = config.get("sweep_variant", "max_avg")

    # ── Block-wide baselines (from the continuous sweep CSV metadata) ─────────
    baselines = load_block_baselines(pathlib.Path(sweep_csv))
    total_trades = baselines["total_trades"]
    baseline_avg_rom = baselines["baseline_avg_ror"]
    baseline_avg_pcr = baselines["baseline_avg_pcr"]
    baseline_wr = baselines["baseline_wr"]
    baseline_pf = baselines["baseline_pf"]
    baseline_net_ror = baseline_avg_rom * total_trades
    if total_trades == 0:
        raise RuntimeError(f"Sweep CSV {sweep_csv} reports total_trades=0; cannot render.")

    # ── Classify selected filters ────────────────────────────────────────────
    continuous_filters, binary_filters, categorical_filters = [], [], []
    seen_cols = {}

    for f in selected_filters:
        ft = f.get("Filter Type", "").strip().lower()
        col = f["CSV Column"].strip()
        if not col:
            continue
        try:
            idx = int(f["Index"].strip())
        except (ValueError, TypeError):
            continue
        name = f["Filter"].strip()
        short_name = (f.get("Short Name") or name).strip() or name
        entry_group = f["Entry Group"].strip()

        entry = {
            "index": idx, "name": name, "short_name": short_name, "col": col,
            "group": entry_group, "type": ft or "continuous",
        }
        if col not in seen_cols or idx < seen_cols[col]["index"]:
            seen_cols[col] = entry

    for v in seen_cols.values():
        if v["type"] == "continuous":
            continuous_filters.append(v)
        elif v["type"] == "binary":
            binary_filters.append(v)
        elif v["type"] == "categorical":
            categorical_filters.append(v)

    continuous_filters.sort(key=lambda x: (x["group"], x["index"]))
    binary_filters.sort(key=lambda x: (x["group"], x["index"]))
    categorical_filters.sort(key=lambda x: (x["group"], x["index"]))

    # ── Load pre-computed sweep results — all 4 (metric × variant) combos ──
    # Computation lives in alex-entry-filter-threshold-sweep. We embed all four
    # combinations in the HTML so the user can toggle metric (AvgROR/AvgPCR)
    # and variant (tightest/max_avg) via dropdowns, without regenerating. The
    # sweep_metric / sweep_variant config values pick which is shown on load.
    METRICS_UI   = ["AvgROR", "AvgPCR"]
    VARIANTS_UI  = ["tightest", "max_avg"]
    print(f"Loading sweep results from {sweep_csv}")
    sweep_data_all: Dict[str, Dict[str, Dict]] = {m: {} for m in METRICS_UI}
    sweep_targets_seen: List[int] = []
    for m in METRICS_UI:
        for v in VARIANTS_UI:
            by_col, targets, _ = load_sweep(
                pathlib.Path(sweep_csv), metric=m, variant=v,
            )
            sweep_data_all[m][v] = by_col
            if not sweep_targets_seen:
                sweep_targets_seen = targets

    # Use the full sweep target grid (5% increments, data-driven ceiling).
    # Drop R_0 — trivially satisfied, no information.
    TARGETS = [t for t in sweep_targets_seen if t > 0]

    # Per-(metric, variant) filter_results keyed by (idx, direction) → {target: cell}
    # 'cell' shape: {"avg_rom": float, "delta_pp": float} or None for blanks.
    filter_results_all: Dict[str, Dict[str, Dict]] = {m: {v: {} for v in VARIANTS_UI} for m in METRICS_UI}
    filter_meta: Dict = {}
    skipped_null: List[str] = []

    def _pack(entry):
        return {
            "avg_rom":  entry["avg"],
            "delta_pp": entry["delta_pp"],
            "threshold": entry.get("threshold", ""),
        }

    for filt in continuous_filters:
        col = filt["col"]; idx = filt["index"]; name = filt["name"]
        filter_meta[idx] = filt
        # Sweep CSV excludes filters with >10% nulls upstream — detect & skip.
        if (col, "Min") not in sweep_data_all["AvgROR"]["max_avg"]:
            skipped_null.append(name)
            continue
        for m in METRICS_UI:
            for v in VARIANTS_UI:
                by_col = sweep_data_all[m][v]
                for dir_label in ("Min", "Max", "Combo"):
                    per_target_sweep = by_col.get((col, dir_label), {})
                    per_target: Dict[int, Optional[Dict]] = {}
                    for T in TARGETS:
                        entry = per_target_sweep.get(T)
                        per_target[T] = _pack(entry) if entry is not None else None
                    filter_results_all[m][v][(idx, dir_label)] = per_target

    # The "active" filter_results used by the Python-side rendering (Retention
    # Detail rows, initial coloring, sort order) is the one picked by the
    # CLI-selected (metric, variant). The JS toggle rewrites cells on the fly;
    # structural layout stays fixed.
    filter_results = filter_results_all[sweep_metric][sweep_variant]
    total_entries = sum(len(v) for m in filter_results_all.values() for v in m.values())
    print(f"  Loaded {total_entries} (filter, direction, metric, variant) entries across {len(continuous_filters)} filters")
    print(f"  Retention targets: R_{TARGETS[0]} … R_{TARGETS[-1]}  ({len(TARGETS)} levels, 5% step)")

    # ── Binary/categorical summaries (loaded from cat_sweep_csv) ─────────────
    # Data precomputed by alex-entry-filter-threshold-sweep. This generator no
    # longer reads entry_filter_data.csv for these — every number below comes
    # from entry_filter_categorical_results.csv joined on csv_column.
    #
    # The breakdown table always displays AvgROR (metric toggle affects only
    # continuous cells); the categorical CSV carries both AvgROR and AvgPCR
    # rows, so we simply request AvgROR here.
    cat_sweep = load_categorical_sweep(pathlib.Path(cat_sweep_csv), metric="AvgROR")

    def _stats_from_csv(n, avg, wr_pct):
        """Rebuild the shape downstream HTML rendering expects."""
        if avg is None or n <= 0:
            return None
        net_ror = avg * n
        pct_trades = n / total_trades * 100 if total_trades else 0.0
        pct_baseline = (net_ror / baseline_net_ror * 100) if baseline_net_ror else 0.0
        net_bump_pp = pct_baseline - pct_trades
        return {
            "trades":       n,
            "pct_trades":   pct_trades,
            "avg_rom":      avg,
            "delta_pp":     avg - baseline_avg_rom,
            "net_ror":      net_ror,
            "pct_baseline": pct_baseline,
            "net_bump_pp":  net_bump_pp,
            "wr":           wr_pct if wr_pct is not None else 0.0,
        }

    binary_results: Dict = {}
    for filt in binary_filters:
        col = filt["col"]; idx = filt["index"]
        filter_meta[idx] = filt
        rows_for_col = cat_sweep.get(col, [])
        if not rows_for_col:
            continue
        binary_results[idx] = {}
        # Binary: wrap category 0/1 as No (0) / Yes (1) to match prior display.
        for entry in rows_for_col:
            cat = entry["category_value"]
            label = f"Yes ({cat})" if cat == "1" else f"No ({cat})"
            in_stats  = _stats_from_csv(entry["in_trades"],  entry["in_avg"],  entry["in_wr"])
            out_stats = _stats_from_csv(entry["out_trades"], entry["out_avg"], entry["out_wr"])
            if in_stats is None:
                continue
            binary_results[idx][label] = {
                **in_stats,
                "raw": cat,
                "out": out_stats,
            }

    categorical_results: Dict = {}
    for filt in categorical_filters:
        col = filt["col"]; idx = filt["index"]
        filter_meta[idx] = filt
        rows_for_col = cat_sweep.get(col, [])
        if not rows_for_col:
            continue
        categorical_results[idx] = {}
        for entry in rows_for_col:
            cat_raw = entry["category_value"]       # e.g. "1", "6", ">=4"
            label   = entry["category_label"]       # e.g. "Mon", "6", "4+"
            in_stats  = _stats_from_csv(entry["in_trades"],  entry["in_avg"],  entry["in_wr"])
            out_stats = _stats_from_csv(entry["out_trades"], entry["out_avg"], entry["out_wr"])
            if in_stats is None:
                continue
            categorical_results[idx][label] = {
                **in_stats,
                "raw": cat_raw,        # ">=4" for aggregated bucket — click-capture reads this
                "out": out_stats,
            }

    # ── Color scale anchored at 80r% deltas — union across all 4 datasets ──
    # Using the union keeps cell colors stable when the user toggles metric/variant
    # in the browser. If we re-anchored per variant, cells would shift color
    # dramatically on toggle; union keeps the scale fixed.
    all_80r_deltas = []
    for m in METRICS_UI:
        for v in VARIANTS_UI:
            for res in filter_results_all[m][v].values():
                if 80 in res and res[80] is not None:
                    all_80r_deltas.append(res[80]["delta_pp"])
    for cats in binary_results.values():
        for data in cats.values():
            all_80r_deltas.append(data["delta_pp"])
            if data.get("out"):
                all_80r_deltas.append(data["out"]["delta_pp"])
    for cats in categorical_results.values():
        for data in cats.values():
            all_80r_deltas.append(data["delta_pp"])
            if data.get("out"):
                all_80r_deltas.append(data["out"]["delta_pp"])
    max_pos_delta = max((d for d in all_80r_deltas if d > 0), default=1.0)
    max_neg_delta = min((d for d in all_80r_deltas if d < 0), default=-1.0)

    # ── Discovery Map column order (sort by 80r% delta desc) ────────────────
    # Includes Min/Max/Combo — Combo columns surface alongside Min/Max via the
    # 80r% sort, so the best setups rise to the top of Discovery regardless of
    # direction. By Filter Group section stays Min/Max only.
    disc_columns = []
    for filt in continuous_filters:
        idx = filt["index"]
        for d in ["Min", "Max", "Combo"]:
            if (idx, d) in filter_results:
                disc_columns.append((idx, d))
    disc_columns.sort(key=lambda c: (filter_results.get(c, {}).get(80) or {"delta_pp": -999})["delta_pp"], reverse=True)

    # Unicode arrows: ^ Min (upper tail), v Max (lower tail), ⇕ Combo (both tails).
    # Raw "<>" breaks HTML parsing (browser sees an empty/unknown tag).
    dir_symbols = {"Min": "^", "Max": "v", "Combo": "\u21d5"}

    # ── HTML ────────────────────────────────────────────────────────────────
    print("Generating HTML...")
    html = []
    h = html.append

    h('<!DOCTYPE html>')
    h('<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">')
    h('<title>Entry Filter Heatmap</title>')
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
    h('.filter-name{text-align:left;vertical-align:middle;white-space:nowrap;cursor:help}')
    h('.filter-name .short{font-weight:700;color:#e0e0e0;font-size:1em}')
    h('.filter-name .colname{display:block;font-family:Menlo,Consolas,monospace;font-size:0.7em;color:#7a8aa8;margin-top:1px}')
    h('.dir-cell{color:#888;font-size:0.78em;white-space:nowrap}')
    h('.na{color:#aaa;font-style:italic;font-size:0.82em;text-align:left;padding-left:16px}')
    h('.dim{color:#444}')
    # By Filter Group cells are color-only (no text) — clicking captures expr.
    h('.bfg-table td[data-det]{min-width:22px;height:18px;padding:3px}')
    # Subtle top border on the Combo row to separate from Max within a filter.
    h('.bfg-table tr.combo-row td{border-top:1px solid rgba(255,255,255,0.08)}')
    h('.cat-table th{font-size:0.7em}')
    h('.cat-table td{font-size:0.8em;padding:5px 8px}')
    h('.cat-table .rom-cell{font-weight:700}')
    # In/Out super-header color coding (subtle tint so columns are distinguishable)
    h('.cat-table th.bc-in{color:#8ad9a0}')
    h('.cat-table th.bc-out{color:#d98a8a}')
    h('.disc-table{width:100%;margin-bottom:24px}')
    h('.disc-table th{writing-mode:vertical-lr;transform:rotate(180deg);text-align:left;padding:4px 2px;font-size:0.68em;min-width:20px;height:80px;white-space:nowrap;letter-spacing:0.3px}')
    h('.disc-table td{padding:3px;min-width:20px;height:18px;border:1px solid rgba(255,255,255,0.04)}')
    h('.disc-table td.disc-label{text-align:left;font-size:0.78em;color:#aaa;white-space:nowrap;width:auto;padding:3px 8px;font-weight:600}')
    h('details{margin:8px 0 18px}')
    h('details summary{cursor:pointer;color:#aaa;font-size:0.88em;padding:6px 0;user-select:none}')
    h('details summary:hover{color:#fff}')
    h('details[open] summary{color:#fff;margin-bottom:6px}')
    h('.ref-table th{text-align:left;padding:6px 10px}')
    h('.ref-table td{text-align:left;padding:4px 10px;font-size:0.82em}')
    h('.ref-table td.mono{font-family:Menlo,Consolas,monospace;color:#7a8aa8}')
    h('.heat-controls{display:flex;align-items:center;gap:10px;margin:4px 0 12px;font-size:0.85em;color:#aaa;flex-wrap:wrap}')
    h('.heat-controls select{background:#16213e;color:#fff;border:1px solid #0f3460;border-radius:4px;padding:4px 8px;font-family:inherit;font-size:0.9em}')
    h('.heat-controls label{color:#888}')
    h('.ctrl-note{color:#666;font-size:0.9em;margin-left:8px}')
    # Click-to-capture UI — cells with data-disc/data-det/data-bc are clickable.
    h('[data-disc],[data-det],[data-bc]{cursor:pointer;transition:outline 0.1s}')
    h('[data-disc]:hover,[data-det]:hover,[data-bc]:hover{outline:1px solid rgba(255,255,255,0.45);outline-offset:-2px}')
    h('.selected{outline:2px solid #f39c12!important;outline-offset:-2px}')
    # Floating selections panel (bottom-right, sticky).
    h('#sel-panel{position:fixed;bottom:20px;right:20px;max-width:420px;min-width:280px;background:#16213e;border:1px solid #0f3460;border-radius:6px;box-shadow:0 4px 16px rgba(0,0,0,0.4);font-size:0.85em;z-index:1000}')
    h('#sel-hdr{display:flex;justify-content:space-between;align-items:center;padding:8px 12px;background:#0f3460;border-radius:6px 6px 0 0;cursor:pointer;user-select:none}')
    h('#sel-hdr .title{color:#f39c12;font-weight:700}')
    h('#sel-hdr .collapse-ind{color:#888}')
    h('#sel-body{max-height:380px;overflow-y:auto;padding:8px 12px}')
    h('#sel-body.collapsed{display:none}')
    h('#sel-body .empty{color:#666;font-style:italic;padding:8px 0}')
    h('.sel-row{display:flex;align-items:flex-start;gap:8px;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.05)}')
    h('.sel-row:last-child{border-bottom:none}')
    h('.sel-body-text{flex:1;min-width:0}')
    h('.sel-expr{font-family:Menlo,Consolas,monospace;color:#e0e0e0;font-size:0.95em;word-break:break-all}')
    h('.sel-ctx{color:#888;font-size:0.8em;margin-top:2px}')
    h('.sel-del{background:transparent;color:#888;border:none;font-size:1.1em;cursor:pointer;padding:0 4px;flex-shrink:0}')
    h('.sel-del:hover{color:#e74c3c}')
    h('#sel-actions{display:flex;gap:8px;padding:8px 12px;background:#1a1a2e;border-top:1px solid rgba(255,255,255,0.05);border-radius:0 0 6px 6px}')
    h('#sel-actions button{flex:1;background:#0f3460;color:#fff;border:1px solid rgba(255,255,255,0.1);border-radius:4px;padding:6px 10px;font-family:inherit;font-size:0.85em;cursor:pointer}')
    h('#sel-actions button:hover{background:#1a4775}')
    h('#sel-actions button:disabled{opacity:0.4;cursor:not-allowed}')
    h('#sel-toast{position:fixed;bottom:20px;right:20px;background:#27ae60;color:#fff;padding:10px 16px;border-radius:4px;font-size:0.85em;z-index:1001;opacity:0;transition:opacity 0.25s;pointer-events:none}')
    h('#sel-toast.show{opacity:1}')
    h('</style></head><body>')

    # Title & subtitle — surface the sweep slice the user is viewing. The
    # <span id="sweep-tag"> is updated by JS when dropdowns change.
    h('<h1>Entry Filter Heatmap</h1>')
    source_tag = esc(f"{heatmap_col}=TRUE")
    init_tag = esc(f"metric={sweep_metric} · variant={sweep_variant}")
    h(f'<div class="subtitle">{esc(block_name)} &nbsp;|&nbsp; {total_trades} trades &nbsp;|&nbsp; '
      f'Baseline Net ROR: {baseline_net_ror:.1f}% &nbsp;|&nbsp; Baseline Avg ROM: {baseline_avg_rom:.2f}% &nbsp;|&nbsp; '
      f'{len(selected_filters)} filters ({source_tag}) &nbsp;|&nbsp; '
      f'Sweep: <span id="sweep-tag">{init_tag}</span> &nbsp;|&nbsp; '
      f'Color &amp; sort keyed at 80r%</div>')

    # Metrics
    h('<div class="metrics-row">')
    h(f'<div class="metric-card"><div class="val">{total_trades}</div><div class="lbl">Total Trades</div></div>')
    h(f'<div class="metric-card"><div class="val">{baseline_net_ror:.1f}%</div><div class="lbl">Baseline Net ROR</div></div>')
    h(f'<div class="metric-card"><div class="val">{baseline_avg_rom:.2f}%</div><div class="lbl">Baseline Avg ROM</div></div>')
    h(f'<div class="metric-card"><div class="val">{baseline_wr:.1f}%</div><div class="lbl">Win Rate</div></div>')
    pf_str = f'{baseline_pf:.2f}' if baseline_pf != float("inf") else "inf"
    h(f'<div class="metric-card"><div class="val">{pf_str}</div><div class="lbl">Profit Factor</div></div>')
    h(f'<div class="metric-card"><div class="val">{len(selected_filters)}</div><div class="lbl">Filters in Scope</div></div>')
    h('</div>')

    # ── Filter Reference (collapsible) ───────────────────────────────────────
    h('<details><summary>&#x25B8; Filter Reference ({} filters) — Index · Filter · Short Name · CSV Column · Entry Group</summary>'.format(len(selected_filters)))
    h('<table class="ref-table"><thead><tr>')
    h('<th>Index</th><th>Filter</th><th>Short Name</th><th>CSV Column</th><th>Entry Group</th><th>Filter Type</th>')
    h('</tr></thead><tbody>')
    for f in selected_filters:
        h('<tr>')
        h(f'<td>{esc(f.get("Index",""))}</td>')
        h(f'<td>{esc(f.get("Filter",""))}</td>')
        h(f'<td><strong>{esc(f.get("Short Name",""))}</strong></td>')
        h(f'<td class="mono">{esc(f.get("CSV Column",""))}</td>')
        h(f'<td>{esc(f.get("Entry Group",""))}</td>')
        h(f'<td>{esc(f.get("Filter Type",""))}</td>')
        h('</tr>')
    h('</tbody></table></details>')

    # ── Discovery Map ────────────────────────────────────────────────────────
    h('<h3>Discovery Map</h3>')
    h('<div class="heat-controls">')
    h('<label for="sel-metric">Metric:</label>')
    h('<select id="sel-metric">')
    for m in METRICS_UI:
        sel = " selected" if m == sweep_metric else ""
        h(f'<option value="{m}"{sel}>{m}</option>')
    h('</select>')
    h('<label for="sel-variant">Variant:</label>')
    h('<select id="sel-variant">')
    for v in VARIANTS_UI:
        sel = " selected" if v == sweep_variant else ""
        h(f'<option value="{v}"{sel}>{v}</option>')
    h('</select>')
    h('<span class="ctrl-note">Applies to Discovery Map + By Filter Group. Color scale &amp; column sort are fixed across toggles for stable visual comparison.</span>')
    h('</div>')
    h('<table class="disc-table"><thead><tr><th style="writing-mode:horizontal-tb;transform:none;height:auto"></th>')
    for idx, d in disc_columns:
        meta = filter_meta[idx]
        short = meta.get("short_name") or str(idx)
        name = meta.get("name", "")
        col = meta.get("col", "")
        sym = dir_symbols[d]
        h(f'<th title="{esc(name)} ({esc(col)}) — {d}">{esc(short)}{sym}</th>')
    h('</tr></thead><tbody>')
    for target in TARGETS:
        h(f'<tr><td class="disc-label">{target}r%</td>')
        for idx, d in disc_columns:
            data_key = f"{idx}|{d}|{target}"
            res = filter_results.get((idx, d), {}).get(target)
            if res is None:
                h(f'<td class="dim" data-disc="{data_key}" style="background:#16213e"></td>')
            else:
                color = delta_to_color(res["delta_pp"], max_pos_delta, max_neg_delta)
                meta = filter_meta[idx]
                name = meta["name"]; col = meta["col"]
                thr_expr = fmt_threshold_expr(d, res.get("threshold", ""), col)
                first_line = thr_expr if thr_expr else f"{name} ({col}) {d} @ {target}r%"
                tip = (f"{first_line}\n"
                       f"{sweep_metric}: {res['avg_rom']:.2f}% ({fmt_pp(res['delta_pp'])})\n"
                       f"Retention target: \u2265{target}%")
                h(f'<td data-disc="{data_key}" style="background:{color}" title="{esc(tip)}"></td>')
        h('</tr>')
    h('</tbody></table>')

    # ── By Filter Group ──────────────────────────────────────────────────────
    # Continuous filters only. Min/Max/Combo rows per filter, grouped by Entry
    # Group. Cells are color-only to match Discovery density; threshold/avg/
    # delta live in the tooltip and get captured into the selections panel on
    # click. Combo appears both here and in the globally-sorted Discovery Map.
    h('<h3>By Filter Group</h3>')
    h('<table class="bfg-table"><thead><tr>')
    h('<th style="text-align:left">Entry Filter</th>')
    h('<th>Dir</th>')
    for t in TARGETS:
        h(f'<th>{t}r%</th>')
    h('</tr></thead><tbody>')

    def label_cell(meta, rowspan=None):
        rs = f' rowspan="{rowspan}"' if rowspan else ''
        tip = f"{meta['name']}  —  CSV: {meta['col']}  —  Index {meta['index']}"
        return (f'<td class="filter-name"{rs} title="{esc(tip)}">'
                f'<span class="short">{esc(meta["short_name"])}</span>'
                f'<span class="colname">{esc(meta["col"])}</span>'
                f'</td>')

    bfg_colspan = 2 + len(TARGETS)
    current_group = None
    for filt in continuous_filters:
        idx = filt["index"]; col = filt["col"]; group = filt["group"]
        if group != current_group:
            current_group = group
            h(f'<tr class="group-hdr"><td colspan="{bfg_colspan}">{esc(group)}</td></tr>')
        if (idx, "Min") not in filter_results:
            continue
        for row_idx, d in enumerate(["Min", "Max", "Combo"]):
            res_map = filter_results.get((idx, d), {})
            row_class = ' class="combo-row"' if d == "Combo" else ""
            if row_idx == 0:
                h(f'<tr>{label_cell(filter_meta[idx], rowspan=3)}')
            else:
                h(f'<tr{row_class}>')
            h(f'<td class="dir-cell">{d}</td>')
            for target in TARGETS:
                data_key = f"{idx}|{d}|{target}"
                res = res_map.get(target)
                if res is None:
                    h(f'<td class="dim" data-det="{data_key}"></td>')
                else:
                    color = delta_to_color(res["delta_pp"], max_pos_delta, max_neg_delta)
                    pp = fmt_pp(res["delta_pp"])
                    avg = res["avg_rom"]
                    thr_expr = fmt_threshold_expr(d, res.get("threshold", ""), col)
                    first_part = thr_expr if thr_expr else f"{d} direction"
                    tip = (f"{first_part} | "
                           f"{sweep_metric}: {avg:.2f}% ({pp}) | "
                           f"Retention target: \u2265{target}%")
                    h(f'<td data-det="{data_key}" style="background:{color}" title="{esc(tip)}"></td>')
            h('</tr>')

    h('</tbody></table>')

    # ── Binary & Categorical Breakdown ──────────────────────────────────────
    # Two clickable cells per row: IN Group (trades where col == value, click
    # captures `col == value`) and OUT Group (trades where col != value, click
    # captures `col != value`). The "Out" side lets the user see what happens
    # when they EXCLUDE that value — often the more actionable question.
    h('<h3>Binary &amp; Categorical Filter Breakdown</h3>')
    h('<table class="cat-table"><thead><tr>')
    h('<th style="text-align:left" rowspan="2">Filter</th>')
    h('<th rowspan="2">Category</th>')
    h('<th colspan="3" class="bc-group bc-in">In Group (==)</th>')
    h('<th colspan="3" class="bc-group bc-out">Out Group (!=)</th>')
    h('</tr><tr>')
    for _ in (0, 1):
        # +avg pts = delta of subset's Avg ROM vs baseline (pp)
        # +net ROM = subset's share-of-edge minus its share-of-trades (pp) —
        # positive means the subset carries disproportionate Net ROR contribution.
        h('<th>Avg ROM</th><th>+avg pts</th><th>+net ROM</th>')
    h('</tr></thead><tbody>')

    def _render_side_cells(bc_attr, stats, color, avg_pp, net_pp, tip):
        """Emit the three cells for one side (In or Out)."""
        if stats is None:
            h('<td class="dim" colspan="3">no trades</td>')
            return
        h(f'<td class="rom-cell" data-bc="{esc(bc_attr)}" style="background:{color}" title="{esc(tip)}">{stats["avg_rom"]:.2f}%</td>')
        h(f'<td style="background:{color}">{avg_pp}</td>')
        h(f'<td style="background:{color}">{net_pp}</td>')

    def _fmt_expr(col, raw, op):
        """Build a display expression. '>=4' raw is the only non-equality case."""
        if raw.startswith(">=") and op == "==":
            return f"{col} >= {raw[2:]}"
        if raw.startswith(">=") and op == "!=":
            return f"{col} < {raw[2:]}"
        return f"{col} {op} {raw}"

    def _bc_tooltip(expr, stats, avg_pp, net_pp):
        # Include absolute Net ROM and its bump alongside Avg ROM details, plus
        # trade count and WR for context on both sides of the comparison.
        return (f"{expr}  |  "
                f"AvgROM {stats['avg_rom']:.2f}% ({avg_pp})  |  "
                f"Net ROM {stats['net_ror']:.1f}% = {stats['pct_baseline']:.1f}% of baseline ({net_pp})  |  "
                f"{stats['trades']} trades ({stats['pct_trades']:.1f}%)  |  "
                f"WR {stats['wr']:.1f}%")

    def render_breakdown(results_dict):
        for idx, cats in results_dict.items():
            meta = filter_meta[idx]
            col = meta.get("col", "")
            first = True
            n_cats = len(cats)
            for label, data in cats.items():
                raw = data.get("raw", "")
                out = data.get("out")
                in_color = delta_to_color(data["delta_pp"], max_pos_delta, max_neg_delta)
                in_avg_pp = fmt_pp(data["delta_pp"])
                in_net_pp = fmt_pp(data["net_bump_pp"])
                out_color = delta_to_color(out["delta_pp"], max_pos_delta, max_neg_delta) if out else "#16213e"
                out_avg_pp = fmt_pp(out["delta_pp"]) if out else ""
                out_net_pp = fmt_pp(out["net_bump_pp"]) if out else ""
                # data-bc payload: idx | col | raw | label | mode (in|out)
                in_attr  = f'{idx}|{col}|{raw}|{label}|in'
                out_attr = f'{idx}|{col}|{raw}|{label}|out'
                in_expr  = _fmt_expr(col, raw, "==")
                out_expr = _fmt_expr(col, raw, "!=")
                in_tip = _bc_tooltip(in_expr, data, in_avg_pp, in_net_pp)
                out_tip = _bc_tooltip(out_expr, out, out_avg_pp, out_net_pp) if out else ""
                if first:
                    h(f'<tr>{label_cell(meta, rowspan=n_cats)}')
                    first = False
                else:
                    h('<tr>')
                h(f'<td>{esc(label)}</td>')
                _render_side_cells(in_attr, data, in_color, in_avg_pp, in_net_pp, in_tip)
                _render_side_cells(out_attr, out, out_color, out_avg_pp, out_net_pp, out_tip)
                h('</tr>')

    render_breakdown(binary_results)
    render_breakdown(categorical_results)

    h('</tbody></table>')

    # ── Click-to-capture panel ───────────────────────────────────────────────
    h('<div id="sel-panel">')
    h('<div id="sel-hdr"><span class="title">Selected Filters (<span id="sel-count">0</span>)</span><span class="collapse-ind" id="sel-collapse-ind">▾</span></div>')
    h('<div id="sel-body"><div class="empty" id="sel-empty">Click any cell in Discovery Map, By Filter Group, or Binary/Categorical Breakdown to add it. Click again to remove.</div><div id="sel-list"></div></div>')
    h('<div id="sel-actions">')
    h('<button id="sel-copy" disabled>Copy expressions</button>')
    h('<button id="sel-copy-csv" disabled>Copy with context</button>')
    h('<button id="sel-clear" disabled>Clear</button>')
    h('</div>')
    h('</div>')
    h('<div id="sel-toast"></div>')

    # ── Interactive toggle JS ─────────────────────────────────────────────────
    # Serialize all 4 (metric × variant) datasets + filter metadata + color
    # scale, then wire the dropdowns to rebuild Discovery Map + Retention Detail
    # cells on change. Binary/Categorical Breakdown is NOT updated (it's always
    # computed vs the AvgROR baseline — documented in SKILL.md).
    def _compact(results_dict):
        """{(idx, dir): {target: cell}} → {"idx|dir": {target: [avg, delta, threshold]}}"""
        out: Dict[str, Dict[int, List]] = {}
        for (idx, dir_lbl), per_tgt in results_dict.items():
            key = f"{idx}|{dir_lbl}"
            inner: Dict[int, List] = {}
            for T, cell in per_tgt.items():
                if cell is not None:
                    inner[T] = [
                        round(cell["avg_rom"], 4),
                        round(cell["delta_pp"], 4),
                        cell.get("threshold", ""),
                    ]
            out[key] = inner
        return out

    sweep_js = {
        m: {v: _compact(filter_results_all[m][v]) for v in VARIANTS_UI}
        for m in METRICS_UI
    }
    meta_js = {
        str(idx): {
            "name":  m.get("name", ""),
            "col":   m.get("col", ""),
            "short": m.get("short_name", ""),
        }
        for idx, m in filter_meta.items()
    }

    h('<script>')
    h(f'const SWEEP = {json.dumps(sweep_js, separators=(",",":"))};')
    h(f'const FILTER_META = {json.dumps(meta_js, separators=(",",":"))};')
    h(f'const COLOR_MAX_POS = {max_pos_delta:.4f};')
    h(f'const COLOR_MAX_NEG = {max_neg_delta:.4f};')
    h('''
function colorFor(delta){
  if (delta >= 0) {
    const a = 0.08 + Math.min(delta / COLOR_MAX_POS, 1.0) * 0.47;
    return 'rgba(46,204,113,' + a.toFixed(2) + ')';
  }
  const a = 0.08 + Math.min(Math.abs(delta) / Math.abs(COLOR_MAX_NEG), 1.0) * 0.47;
  return 'rgba(231,76,60,' + a.toFixed(2) + ')';
}
function fmtPP(d){ return (d >= 0 ? '+' : '') + d.toFixed(1) + 'pp'; }
function fmtNum(s){
  const n = parseFloat(s);
  if (!isFinite(n)) return s;
  let o = n.toFixed(3);
  if (o.indexOf('.') >= 0) {
    o = o.replace(/0+$/, '').replace(/\.$/, '');
    if (!o) o = '0';
  }
  return o;
}
function fmtThresholdExpr(dir, thr, csvCol){
  if (!thr) return '';
  if (thr.indexOf('|') >= 0) {
    const [lo, hi] = thr.split('|');
    return csvCol + ' \u2208 [' + fmtNum(lo) + ', ' + fmtNum(hi) + ']';
  }
  const op = dir === 'Min' ? '>=' : '<=';
  return csvCol + ' ' + op + ' ' + fmtNum(thr);
}

function applySelection(){
  const m = document.getElementById('sel-metric').value;
  const v = document.getElementById('sel-variant').value;
  document.getElementById('sweep-tag').textContent = 'metric=' + m + ' \u00B7 variant=' + v;
  const data = SWEEP[m][v];

  // Discovery Map cells
  document.querySelectorAll('[data-disc]').forEach(cell => {
    const [idx, dir, tgt] = cell.dataset.disc.split('|');
    const row = data[idx + '|' + dir] || {};
    const info = row[tgt];
    if (info) {
      const [avg, delta, thr] = info;
      cell.style.background = colorFor(delta);
      const meta = FILTER_META[idx] || {name:'', col:''};
      const thrExpr = fmtThresholdExpr(dir, thr, meta.col);
      const firstLine = thrExpr || (meta.name + ' (' + meta.col + ') ' + dir + ' @ ' + tgt + 'r%');
      cell.title = firstLine + '\\n' +
                   m + ': ' + avg.toFixed(2) + '% (' + fmtPP(delta) + ')\\n' +
                   'Retention target: \u2265' + tgt + '%';
      cell.classList.remove('dim');
    } else {
      cell.style.background = '#16213e';
      cell.title = '';
      cell.classList.add('dim');
    }
  });

  // By Filter Group cells (color + tooltip only — no inline text to rewrite)
  document.querySelectorAll('[data-det]').forEach(cell => {
    const [idx, dir, tgt] = cell.dataset.det.split('|');
    const row = data[idx + '|' + dir] || {};
    const info = row[tgt];
    if (info) {
      const [avg, delta, thr] = info;
      cell.style.background = colorFor(delta);
      cell.classList.remove('dim');
      const meta = FILTER_META[idx] || {col:''};
      const thrExpr = fmtThresholdExpr(dir, thr, meta.col);
      const firstPart = thrExpr || (dir + ' direction');
      cell.title = firstPart + ' | ' +
                   m + ': ' + avg.toFixed(2) + '% (' + fmtPP(delta) + ') | ' +
                   'Retention target: \u2265' + tgt + '%';
    } else {
      cell.style.background = '';
      cell.classList.add('dim');
      cell.title = '';
    }
  });
}

document.getElementById('sel-metric').addEventListener('change', () => { applySelection(); applySelectedClassToCells(); });
document.getElementById('sel-variant').addEventListener('change', () => { applySelection(); applySelectedClassToCells(); });

// ── Click-to-capture: build a list of filter expressions ──────────────────
const STORAGE_KEY = 'heatmap-selections';
const picks = new Map();  // key → info (continuous or bc kind)

// Continuous selections are keyed by (m, v, idx, dir, tgt) — they change meaning
// as the user toggles metric/variant. Binary/categorical selections don't
// depend on metric or variant (raw value == val is metric-agnostic), so they
// key on (idx, col, raw, mode) and persist across toggles. `mode` distinguishes
// the "In group" click (== val) from the "Out group" click (!= val).
function selKey(info){
  if (info.kind === 'bc') return 'bc|' + info.idx + '|' + info.col + '|' + info.raw + '|' + info.mode;
  return [info.m, info.v, info.idx, info.dir, info.tgt].join('|');
}

function fmtCategoricalExpr(col, raw, mode){
  // mode: 'in' -> ==  (or >= for the "4+" aggregated bucket)
  //       'out' -> != (or < for the "4+" aggregated bucket)
  const isAgg = (typeof raw === 'string' && raw.indexOf('>=') === 0);
  if (isAgg && mode === 'in')  return col + ' >= ' + raw.slice(2);
  if (isAgg && mode === 'out') return col + ' < '  + raw.slice(2);
  return col + ' ' + (mode === 'out' ? '!=' : '==') + ' ' + raw;
}

function extractCellInfo(cell, attr){
  if (attr === 'bc') {
    const raw = cell.dataset.bc;
    if (!raw) return null;
    const parts = raw.split('|');
    if (parts.length < 5) return null;
    const [idx, col, rawVal, label, mode] = parts;
    const meta = FILTER_META[idx] || {col: col, name:'', short:''};
    const expr = fmtCategoricalExpr(col, rawVal, mode);
    return {
      kind: 'bc', idx, col, raw: rawVal, label, mode, expr,
      name: meta.name, short: meta.short,
      // m/v carried for UI context only — not part of selKey for bc rows.
      m: document.getElementById('sel-metric').value,
      v: document.getElementById('sel-variant').value,
    };
  }
  const m = document.getElementById('sel-metric').value;
  const v = document.getElementById('sel-variant').value;
  const raw = cell.dataset[attr];  // e.g. "21|Min|55"
  if (!raw) return null;
  const [idx, dir, tgt] = raw.split('|');
  const row = (SWEEP[m] && SWEEP[m][v]) ? SWEEP[m][v][idx + '|' + dir] : null;
  const info = row ? row[tgt] : null;
  if (!info) return null;
  const [avg, delta, thr] = info;
  const meta = FILTER_META[idx] || {col:'', name:'', short:''};
  const expr = fmtThresholdExpr(dir, thr, meta.col);
  if (!expr) return null;
  return { kind: 'cont', idx, dir, tgt, avg, delta, thr, expr, col: meta.col, name: meta.name, short: meta.short, m, v };
}

function togglePick(cell, attr){
  const info = extractCellInfo(cell, attr);
  if (!info) return;
  const k = selKey(info);
  if (picks.has(k)) {
    picks.delete(k);
  } else {
    picks.set(k, info);
  }
  renderPanel();
  persistPicks();
  applySelectedClassToCells();
}

function renderPanel(){
  const list = document.getElementById('sel-list');
  const empty = document.getElementById('sel-empty');
  const count = document.getElementById('sel-count');
  count.textContent = picks.size;
  list.innerHTML = '';
  empty.style.display = picks.size === 0 ? '' : 'none';
  for (const [k, info] of picks) {
    const row = document.createElement('div');
    row.className = 'sel-row';
    row.innerHTML =
      '<div class="sel-body-text">' +
      '<div class="sel-expr"></div>' +
      '<div class="sel-ctx"></div>' +
      '</div>' +
      '<button class="sel-del" title="Remove">×</button>';
    row.querySelector('.sel-expr').textContent = info.expr;
    if (info.kind === 'bc') {
      row.querySelector('.sel-ctx').textContent =
        info.label + ' · ' + info.col + ' · ' + (info.mode === 'out' ? 'exclude (Out group)' : 'include (In group)');
    } else {
      row.querySelector('.sel-ctx').textContent =
        info.tgt + 'r% · ' + info.m + ' ' + (info.delta >= 0 ? '+' : '') + info.delta.toFixed(1) + 'pp · ' +
        info.dir + ' · ' + info.v;
    }
    row.querySelector('.sel-del').addEventListener('click', (e) => {
      e.stopPropagation();
      picks.delete(k);
      renderPanel();
      persistPicks();
      applySelectedClassToCells();
    });
    list.appendChild(row);
  }
  const has = picks.size > 0;
  document.getElementById('sel-copy').disabled = !has;
  document.getElementById('sel-copy-csv').disabled = !has;
  document.getElementById('sel-clear').disabled = !has;
}

function persistPicks(){
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(Array.from(picks.entries()))); } catch(e) {}
}
function loadPicks(){
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const data = JSON.parse(raw);
    for (const [k, info] of data) picks.set(k, info);
  } catch(e) {}
}

function applySelectedClassToCells(){
  document.querySelectorAll('.selected').forEach(c => c.classList.remove('selected'));
  const m = document.getElementById('sel-metric').value;
  const v = document.getElementById('sel-variant').value;
  for (const info of picks.values()) {
    if (info.kind === 'bc') {
      // Binary/categorical: highlight the one ROM cell whose data-bc matches
      // (idx|col|raw|label|mode). Independent of metric/variant.
      document.querySelectorAll('[data-bc]').forEach(cell => {
        const parts = cell.dataset.bc.split('|');
        if (parts[0] === String(info.idx) && parts[1] === info.col
            && parts[2] === info.raw && parts[4] === info.mode) {
          cell.classList.add('selected');
        }
      });
      continue;
    }
    if (info.m !== m || info.v !== v) continue;  // only highlight cells matching current view
    const sel = info.idx + '|' + info.dir + '|' + info.tgt;
    const d = document.querySelector('[data-disc="' + sel + '"]');
    if (d) d.classList.add('selected');
    const r = document.querySelector('[data-det="' + sel + '"]');
    if (r) r.classList.add('selected');
  }
}

function toast(msg){
  const t = document.getElementById('sel-toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 1400);
}

function copyText(text, msg){
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(() => toast(msg)).catch(() => fallbackCopy(text, msg));
  } else {
    fallbackCopy(text, msg);
  }
}
function fallbackCopy(text, msg){
  const ta = document.createElement('textarea');
  ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
  document.body.appendChild(ta); ta.select();
  try { document.execCommand('copy'); toast(msg); } catch(e) { toast('Copy failed'); }
  document.body.removeChild(ta);
}

document.getElementById('sel-copy').addEventListener('click', () => {
  const lines = Array.from(picks.values()).map(p => p.expr);
  copyText(lines.join('\\n'), 'Copied ' + lines.length + ' expression(s)');
});
document.getElementById('sel-copy-csv').addEventListener('click', () => {
  const lines = Array.from(picks.values()).map(p => {
    if (p.kind === 'bc') {
      return p.expr + '    # ' + p.label + ' · ' + p.col + ' · ' + (p.mode === 'out' ? 'exclude' : 'include');
    }
    return p.expr + '    # ' + p.tgt + 'r% · ' + p.m + ' ' + (p.delta >= 0 ? '+' : '') + p.delta.toFixed(1) + 'pp · ' + p.dir + ' · ' + p.v;
  });
  copyText(lines.join('\\n'), 'Copied with context');
});
document.getElementById('sel-clear').addEventListener('click', () => {
  if (picks.size === 0) return;
  if (!confirm('Clear all ' + picks.size + ' selected filter(s)?')) return;
  picks.clear();
  renderPanel();
  persistPicks();
  applySelectedClassToCells();
});
document.getElementById('sel-hdr').addEventListener('click', () => {
  const body = document.getElementById('sel-body');
  const ind = document.getElementById('sel-collapse-ind');
  body.classList.toggle('collapsed');
  ind.textContent = body.classList.contains('collapsed') ? '▸' : '▾';
});

// Wire click handlers on cells. Delegation via document for simplicity.
document.addEventListener('click', (e) => {
  const cell = e.target.closest('[data-disc],[data-det],[data-bc]');
  if (!cell) return;
  // Don't toggle if the click was on a del button inside the panel
  if (e.target.closest('#sel-panel')) return;
  const attr = cell.dataset.disc !== undefined ? 'disc'
             : cell.dataset.det !== undefined ? 'det'
             : 'bc';
  togglePick(cell, attr);
});

// Initial load
loadPicks();
renderPanel();
applySelectedClassToCells();
''')
    h('</script>')
    h('</body></html>')

    with open(out_html, "w", encoding="utf-8") as f:
        f.write("\n".join(html))

    print(f"Written to {out_html}")
    print(f"Color scale: green max at +{max_pos_delta:.1f}pp, red max at {max_neg_delta:.1f}pp (from 80r%)")
    if skipped_null:
        print(f"Skipped (>10% nulls): {', '.join(skipped_null)}")
    return out_html


# ── Main / CLI ───────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Entry filter retention heatmap for a block.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("block_id", help="Block folder name under TB root")
    ap.add_argument("--tb-root", default=TB_ROOT_DEFAULT, help="TradeBlocks Data root")
    ap.add_argument("--groups-csv", default=None,
                    help="Explicit entry_filter_groups CSV path (abs or relative to TB root)")
    ap.add_argument("--heatmap-col", default="Report Heatmap",
                    help="Column in groups CSV to use for filter inclusion (TRUE rows are included)")
    ap.add_argument("--sweep-metric", default="AvgROR", choices=["AvgROR", "AvgPCR"],
                    help="Which metric rows to read from the sweep CSV")
    ap.add_argument("--sweep-variant", default="max_avg", choices=["tightest", "max_avg"],
                    help="Which variant to read from the sweep CSV. "
                         "max_avg (default) = threshold maximizing the chosen metric at each retention target. "
                         "tightest = most-selective qualifying threshold (smallest survivor count).")
    ap.add_argument("--filter-by", default=None, metavar="COL=VAL",
                    help="Additional scoping predicate, AND-combined with --heatmap-col")
    ap.add_argument("--list", action="store_true", dest="list_filters",
                    help="Print filters in scope and exit without generating HTML")
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

    try:
        sweep_csv = resolve_sweep_csv(ref_folder)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return EXIT_MISSING_SWEEP_CSV

    try:
        cat_sweep_csv = resolve_cat_sweep_csv(ref_folder)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return EXIT_MISSING_SWEEP_CSV

    explicit: Optional[pathlib.Path] = None
    if args.groups_csv:
        cand = pathlib.Path(args.groups_csv)
        if not cand.is_absolute():
            cand = (tb_root / cand).resolve()
        explicit = cand

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

    print(f"Groups CSV: {display_groups}  [{source}]")
    print(f"Heatmap column: {args.heatmap_col}")
    if args.filter_by:
        print(f"Filter-by:  {args.filter_by}")

    try:
        groups = load_groups(groups_path)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    try:
        selected = select_heatmap_filters(groups, args.heatmap_col, args.filter_by)
    except RuntimeError as e:
        msg = str(e)
        if msg.startswith("HEATMAP_COL_MISSING:"):
            print(f"ERROR: {msg.split(':',1)[1].lstrip()}", file=sys.stderr)
            return EXIT_HEATMAP_COL_MISSING
        print(f"ERROR: {msg}", file=sys.stderr)
        return EXIT_FILTER_BY_ERROR

    if not selected:
        print(f"\nERROR: no filters in scope. Check that the {args.heatmap_col!r} column has TRUE values"
              + (f" matching --filter-by {args.filter_by!r}" if args.filter_by else "")
              + ".", file=sys.stderr)
        return EXIT_FILTER_BY_ERROR

    print(f"Filters in scope: {len(selected)} of {len(groups)}")

    if args.list_filters:
        print()
        list_filters(selected)
        return EXIT_OK

    out_html = block_folder / "entry filter heatmap.html"
    try:
        sweep_rel = sweep_csv.relative_to(tb_root)
    except ValueError:
        sweep_rel = sweep_csv
    try:
        cat_sweep_rel = cat_sweep_csv.relative_to(tb_root)
    except ValueError:
        cat_sweep_rel = cat_sweep_csv
    print(f"Sweep CSV (continuous):  {sweep_rel}  [block-local]")
    print(f"Sweep CSV (categorical): {cat_sweep_rel}  [block-local]")
    cfg = {
        "block_folder":     str(block_folder),
        "block_name":       args.block_id,
        "groups_csv":       str(groups_path),
        "sweep_csv":        str(sweep_csv),
        "cat_sweep_csv":    str(cat_sweep_csv),
        "selected_filters": selected,
        "out_html":         str(out_html),
        "heatmap_col":      args.heatmap_col,
        "sweep_metric":     args.sweep_metric,
        "sweep_variant":    args.sweep_variant,
    }

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
