#!/usr/bin/env python3
"""
dev-entry-filter-threshold-sweep — CLI driver.

Pre-computes sweep results for every continuous AND categorical entry filter
on a block, producing two sibling CSVs that downstream skills (heatmap, pareto,
etc.) consume instead of recomputing on every run.

    python3 gen_sweep.py BLOCK_ID \\
        [--tb-root PATH] \\
        [--groups-csv PATH] \\
        [--filter-by "COLUMN=VALUE"] \\
        [--step PCT]            (default 5)

Inputs (both block-local):
    {block}/alex-tradeblocks-ref/entry_filter_data.csv
    {block}/alex-tradeblocks-ref/entry_filter_groups.*.csv

Outputs (both block-local, written every run):
    entry_filter_threshold_results.csv    — continuous filters
    entry_filter_categorical_results.csv  — categorical filters

Continuous schema: one row per (csv_column, direction, variant, metric).
    - direction ∈ {"low threshold" (>=), "high threshold" (<=), "combo" ([lo,hi])}
    - variant   ∈ {"tightest", "max_avg"}
    - metric    ∈ {"AvgROR", "AvgPCR", "ThresholdROR", "ThresholdPCR"}
    - columns: metadata + R_<T> cells for each retention target T

Categorical schema: one row per (csv_column, category_value, metric).
    - metric ∈ {"AvgROR", "AvgPCR"}
    - columns: csv_column, category_value, category_label, metric,
               baseline_avg, total_trades,
               in_sample_trades, in_sample, out_sample_trades, out_sample
    - in_sample  = mean metric over trades where col == category_value
    - out_sample = mean metric over non-null trades where col != category_value
    - Ordered by Index in the groups CSV; Weeks_to/from_Holiday aggregates
      values >= 4 into a ">=4" bucket.

Retention target ceiling is data-driven per block — any combo retaining above
baseline extends the column set automatically.

See SKILL.md for exit codes and full workflow.
"""

from __future__ import annotations

import argparse
import csv
import math
import pathlib
import sys
from typing import Optional, Tuple, List, Dict


TB_ROOT_DEFAULT = "/Users/alexanderhardt/Library/CloudStorage/OneDrive-AIACOTechnology/Documents - AIACO Trading Development/Pipeline Data/TradeBlocks Data"

EXIT_OK = 0
EXIT_MISSING_DATA_CSV = 2
EXIT_MISSING_GROUPS_CSV = 3
EXIT_MULTIPLE_GROUPS_CSV = 4
EXIT_FILTER_BY_ERROR = 6

REQUIRED_GROUPS_COLS = {"Index", "Filter", "Short Name", "CSV Column", "Entry Group", "Filter Type"}
MIN_TRADES = 10
MIN_TRADE_PCT = 10.0   # % of total
MAX_NULL_FRAC = 0.10   # skip filters with >10% nulls

DIRECTIONS = ["low threshold", "high threshold", "combo"]
VARIANTS = ["tightest", "max_avg"]
# Each (filter, direction, variant) emits FOUR metric rows: the avg metric and
# the threshold chosen per metric. For tightest variant ThresholdROR == ThresholdPCR
# (the same tightest threshold underlies both avg cells); for max_avg variant
# they can differ (ROR- and PCR-optimal thresholds are chosen independently).
METRICS = ["AvgROR", "AvgPCR", "ThresholdROR", "ThresholdPCR"]


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
            f"Run /alex-entry-filter-build-data BLOCK_ID first."
        )
    return p


def resolve_groups_csv(
    ref_folder: pathlib.Path,
    explicit: Optional[pathlib.Path] = None,
) -> Tuple[pathlib.Path, str]:
    if explicit is not None:
        if not explicit.is_file():
            raise RuntimeError(f"--groups-csv file not found: {explicit}")
        return explicit.resolve(), "explicit"
    matches = sorted(ref_folder.glob("entry_filter_groups.*.csv"))
    if len(matches) == 0:
        raise FileNotFoundError(
            f"No entry_filter_groups.*.csv in {ref_folder}.\n"
            f"Run /alex-entry-filter-build-data BLOCK_ID first."
        )
    if len(matches) > 1:
        names = ", ".join(m.name for m in matches)
        raise RuntimeError(
            f"Multiple filter-groups files in block ref folder: {names}.\n"
            f"Pass --groups-csv PATH to pick one."
        )
    return matches[0], "block-local"


# ── Groups CSV ───────────────────────────────────────────────────────────────

def load_groups(path: pathlib.Path) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        if not reader.fieldnames:
            raise RuntimeError(f"groups CSV has no header: {path}")
        missing = REQUIRED_GROUPS_COLS - set(reader.fieldnames)
        if missing:
            raise RuntimeError(
                f"groups CSV missing required columns: {sorted(missing)}. Path: {path}"
            )
    for r in rows:
        for col in REQUIRED_GROUPS_COLS:
            if r.get(col) is not None:
                r[col] = r[col].strip()
    return rows


def apply_filter_by(groups: List[Dict], expr: Optional[str]) -> List[Dict]:
    if not expr:
        return groups
    if "=" not in expr:
        raise RuntimeError(f"--filter-by must be COLUMN=VALUE (got: {expr!r})")
    col, _, val = expr.partition("=")
    col = col.strip(); val = val.strip()
    if not groups:
        return groups
    if col not in groups[0]:
        available = sorted(groups[0].keys())
        raise RuntimeError(
            f"--filter-by column {col!r} not in groups CSV. Available: {available}"
        )
    val_lower = val.lower()
    return [r for r in groups if (r.get(col) or "").strip().lower() == val_lower]


# ── Data CSV ─────────────────────────────────────────────────────────────────

def load_data(path: pathlib.Path) -> Tuple[List[Dict], List[str]]:
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        header = list(reader.fieldnames or [])
    return rows, header


def parse_float(v: Optional[str]) -> Optional[float]:
    if v is None:
        return None
    s = v.strip()
    if not s or s.lower() in ("null", "none", "nan"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ── Sweep algorithm ──────────────────────────────────────────────────────────

def build_filter_arrays(
    trades: List[Dict],
    col: str,
) -> Tuple[List[float], List[float], List[float], int]:
    """
    Return (vals, roms, pcrs, null_count) for trades with non-null filter value.
    rom_pct and pcr_pct are required columns in entry_filter_data.csv.
    """
    vals: List[float] = []
    roms: List[float] = []
    pcrs: List[float] = []
    nulls = 0
    for t in trades:
        v = parse_float(t.get(col))
        r = parse_float(t.get("rom_pct"))
        p = parse_float(t.get("pcr_pct"))
        if v is None or r is None:
            nulls += 1
            continue
        vals.append(v)
        roms.append(r)
        pcrs.append(p if p is not None else 0.0)
    return vals, roms, pcrs, nulls


def _fmt_threshold(t_val) -> str:
    """Render a threshold for the CSV. Combo threshold is (lo, hi) → 'lo|hi'."""
    if t_val is None:
        return ""
    if isinstance(t_val, tuple):
        lo, hi = t_val
        return f"{lo:.6f}|{hi:.6f}"
    return f"{t_val:.6f}"


def sweep_one_direction(
    vals: List[float],
    roms: List[float],
    pcrs: List[float],
    baseline_net: float,
    total_trades: int,
    targets: List[int],
    direction: str,
) -> Tuple[Dict[int, Dict[str, Dict]], float]:
    """
    For each retention target T, compute THREE candidate selections:
      - tightest:  most-selective qualifying threshold (smallest survivor count;
                   equivalently, highest t for 'low threshold', lowest t for
                   'high threshold', smallest-n pair for 'combo')
      - max_ror:   qualifying threshold with the highest avg ROR of survivors
      - max_pcr:   qualifying threshold with the highest avg PCR of survivors

    Returns:
      { T: {
          "tightest": {"t": threshold, "avg_ror": float, "avg_pcr": float, "n": int},
          "max_ror":  {"t": threshold, "avg_ror": float, "avg_pcr": float, "n": int},
          "max_pcr":  {"t": threshold, "avg_ror": float, "avg_pcr": float, "n": int},
        } or {} if no candidate qualifies at T }

    "threshold" is a float for low/high direction, (lo, hi) tuple for combo.
    Uses MIN_TRADES and MIN_TRADE_PCT guards on survivor count.
    """
    n = len(vals)
    if n == 0 or baseline_net == 0:
        return {T: {} for T in targets}, 0.0
    min_n = max(MIN_TRADES, int(math.ceil(total_trades * MIN_TRADE_PCT / 100.0)))

    # Index sort ascending by value — prefix-sum trick for O(1) range stats.
    order = sorted(range(n), key=lambda i: vals[i])
    sorted_vals = [vals[i] for i in order]
    sorted_roms = [roms[i] for i in order]
    sorted_pcrs = [pcrs[i] for i in order]
    prefix_rom = [0.0] * (n + 1)
    prefix_pcr = [0.0] * (n + 1)
    for i in range(n):
        prefix_rom[i + 1] = prefix_rom[i] + sorted_roms[i]
        prefix_pcr[i + 1] = prefix_pcr[i] + sorted_pcrs[i]

    # Unique value groups.
    unique_vals: List[float] = []
    left_of: List[int] = []
    right_of: List[int] = []
    i = 0
    while i < n:
        v = sorted_vals[i]
        j = i
        while j < n and sorted_vals[j] == v:
            j += 1
        unique_vals.append(v)
        left_of.append(i)
        right_of.append(j)
        i = j
    m = len(unique_vals)

    def slice_stats(lo_idx: int, hi_idx: int) -> Tuple[int, float, float, float]:
        cnt = hi_idx - lo_idx
        rom_s = prefix_rom[hi_idx] - prefix_rom[lo_idx]
        pcr_s = prefix_pcr[hi_idx] - prefix_pcr[lo_idx]
        return cnt, rom_s, pcr_s, (rom_s / baseline_net * 100 if baseline_net else 0.0)

    # Build the candidate list for this direction. Each candidate:
    #   (threshold_value, count, avg_ror, avg_pcr, retention)
    candidates: List[Tuple] = []

    if direction == "low threshold":
        # survivors = val >= unique_vals[k]; as k increases, survivors shrink.
        for k in range(m):
            lo_idx = left_of[k]
            cnt, rom_s, pcr_s, ret = slice_stats(lo_idx, n)
            if cnt < min_n:
                continue
            candidates.append((unique_vals[k], cnt, rom_s / cnt, pcr_s / cnt, ret))
    elif direction == "high threshold":
        # survivors = val <= unique_vals[k]; as k decreases, survivors shrink.
        for k in range(m):
            hi_idx = right_of[k]
            cnt, rom_s, pcr_s, ret = slice_stats(0, hi_idx)
            if cnt < min_n:
                continue
            candidates.append((unique_vals[k], cnt, rom_s / cnt, pcr_s / cnt, ret))
    elif direction == "combo":
        for i_lo in range(m):
            lo_idx = left_of[i_lo]
            lo_val = unique_vals[i_lo]
            for i_hi in range(i_lo, m):
                hi_idx = right_of[i_hi]
                hi_val = unique_vals[i_hi]
                cnt, rom_s, pcr_s, ret = slice_stats(lo_idx, hi_idx)
                if cnt < min_n:
                    continue
                candidates.append(((lo_val, hi_val), cnt, rom_s / cnt, pcr_s / cnt, ret))
    else:
        raise ValueError(f"unknown direction: {direction}")

    # Peak retention observed across all qualifying candidates (regardless of T).
    # Useful as a row-level context column so downstream reports can see the
    # filter/direction's ceiling without scanning the R_* cells.
    max_net_ror_observed = max((c[4] for c in candidates), default=0.0)

    # For each target T, pick three candidates among qualifiers (retained >= T):
    #   tightest  = smallest n     (ties broken by direction-specific preference)
    #   max_ror   = max avg_ror
    #   max_pcr   = max avg_pcr
    results: Dict[int, Dict[str, Dict]] = {}
    for T in targets:
        qualifying = [c for c in candidates if c[4] >= T]
        if not qualifying:
            results[T] = {}
            continue
        # Tightest = smallest n. Tie-break: for low threshold prefer highest t
        # (most restrictive filter); for high threshold prefer lowest t;
        # for combo prefer largest lo (just for determinism).
        def tight_key(c):
            t, cnt, _, _, _ = c
            if direction == "low threshold":
                return (cnt, -t)           # small n, then high t
            if direction == "high threshold":
                return (cnt, t)            # small n, then low t
            # combo: small n, then tight range (hi - lo small), then lo desc
            lo, hi = t
            return (cnt, hi - lo, -lo)
        tightest = min(qualifying, key=tight_key)
        max_ror  = max(qualifying, key=lambda c: c[2])
        max_pcr  = max(qualifying, key=lambda c: c[3])

        def pack(c) -> Dict:
            t, cnt, avg_ror, avg_pcr, _ret = c
            return {"t": t, "avg_ror": avg_ror, "avg_pcr": avg_pcr, "n": cnt}

        results[T] = {
            "tightest": pack(tightest),
            "max_ror":  pack(max_ror),
            "max_pcr":  pack(max_pcr),
        }
    return results, max_net_ror_observed


def compute_max_achieved_retention(
    filter_data: Dict[str, Tuple[List[float], List[float], List[float]]],
    baseline_net: float,
    total_trades: int,
) -> float:
    """Scan all filters/directions/combos to find the highest retention any subset achieves."""
    if baseline_net == 0:
        return 100.0
    min_n = max(MIN_TRADES, int(math.ceil(total_trades * MIN_TRADE_PCT / 100.0)))
    max_ret = 100.0
    for col, (vals, roms, _pcrs) in filter_data.items():
        n = len(vals)
        if n < min_n:
            continue
        order = sorted(range(n), key=lambda i: vals[i])
        sorted_vals = [vals[i] for i in order]
        sorted_roms = [roms[i] for i in order]
        prefix_rom = [0.0] * (n + 1)
        for i in range(n):
            prefix_rom[i + 1] = prefix_rom[i] + sorted_roms[i]
        # For combo scan — check every (lo_idx, hi_idx) pair
        unique_vals = []; left_of = []; right_of = []
        i = 0
        while i < n:
            v = sorted_vals[i]; j = i
            while j < n and sorted_vals[j] == v:
                j += 1
            unique_vals.append(v); left_of.append(i); right_of.append(j)
            i = j
        m = len(unique_vals)
        for i_lo in range(m):
            lo_idx = left_of[i_lo]
            for i_hi in range(i_lo, m):
                hi_idx = right_of[i_hi]
                cnt = hi_idx - lo_idx
                if cnt < min_n:
                    continue
                rom_s = prefix_rom[hi_idx] - prefix_rom[lo_idx]
                ret = rom_s / baseline_net * 100
                if ret > max_ret:
                    max_ret = ret
    return max_ret


def build_target_list(max_ret: float, step: int) -> List[int]:
    """
    Return retention targets from ceiling down to 0 in step-% increments.
    Ceiling = ceil(max_ret / step) * step, floored at 105%. This gives ONE
    extra blank column above the highest achieved retention (e.g., max=111% →
    ceiling=115, so R_115 appears as a blank marker of "range complete").
    If max_ret lands exactly on a step boundary, the top column has data — no
    extra headroom added.
    """
    ceiling = max(105, int(math.ceil(max_ret / step) * step))
    targets = list(range(ceiling, -1, -step))
    if targets[-1] != 0:
        targets.append(0)
    return targets


# ── CSV writing ──────────────────────────────────────────────────────────────

def write_sweep_csv(
    out_path: pathlib.Path,
    rows: List[Dict],
    targets: List[int],
) -> None:
    # Lean schema. Downstream reports join csv_column back to entry_filter_groups
    # for display names and other metadata; this file stores no redundant names.
    # baseline_wr and baseline_pf are block-wide constants repeated across every
    # row so downstream consumers can surface block baselines without needing
    # a second data source.
    meta_cols = [
        "csv_column", "direction", "variant", "metric",
        "baseline_avg", "baseline_wr", "baseline_pf",
        "total_trades", "max_net_ror",
    ]
    target_cols = [f"R_{T}" for T in targets]
    fieldnames = meta_cols + target_cols
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        f.write("\ufeff")
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


# ── Categorical sweep ────────────────────────────────────────────────────────
# Labels for display-only (category_label column). Functional joins use raw
# category_value (the literal CSV value), so downstream skills don't need to
# know the label map.
CAT_LABELS = {
    "Day_of_Week": {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri"},
    "Month": {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
              7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"},
    "Term_Structure_State": {-1: "Backwardation", 0: "Flat", 1: "Contango"},
}
# Columns where values >= 4 aggregate into a single ">=4" bucket (matches the
# heatmap's "4+" display — values that far from/to a holiday are noise).
AGG_4PLUS_COLS = ("Weeks_to_Holiday", "Weeks_from_Holiday")


def _label_for(col: str, cat: str) -> str:
    if cat == ">=4":
        return "4+"
    lbl_map = CAT_LABELS.get(col, {})
    try:
        return lbl_map.get(int(float(cat)), cat)
    except (ValueError, TypeError):
        return cat


def _sort_key_for(cat: str):
    if cat == ">=4":
        return (1, 4.5)       # sorts after 0/1/2/3
    try:
        return (0, float(cat))
    except (ValueError, TypeError):
        return (2, cat)


def sweep_categorical_filter(
    trades: List[Dict],
    col: str,
    baseline_avg_ror: float,
    baseline_avg_pcr: float,
    baseline_net_ror: float,
    total_trades: int,
) -> List[Dict]:
    """
    Return rows for one categorical (or binary) filter — one row per
    (category, metric). Values >= 4 aggregate into ">=4" for
    Weeks_to_Holiday / Weeks_from_Holiday. Rows ordered by natural category
    sort (numeric asc; "4+" last).
    """
    # Bucket roms and pcrs + win-count per category value. Exclude nulls
    # (NULL means data missing, not a valid category).
    buckets: Dict[str, Tuple[List[float], List[float]]] = {}
    for t in trades:
        raw = (t.get(col) or "").strip()
        if not raw or raw.lower() in ("null", "none", "nan"):
            continue
        r = parse_float(t.get("rom_pct"))
        p = parse_float(t.get("pcr_pct"))
        if r is None:
            continue
        # Aggregate >= 4 bucket if applicable.
        cat_key = raw
        if col in AGG_4PLUS_COLS:
            try:
                iv = int(float(raw))
                cat_key = str(iv) if iv <= 3 else ">=4"
            except (ValueError, TypeError):
                pass
        roms, pcrs = buckets.setdefault(cat_key, ([], []))
        roms.append(r)
        pcrs.append(p if p is not None else 0.0)

    if not buckets:
        return []

    def mean(xs: List[float]) -> Optional[float]:
        return (sum(xs) / len(xs)) if xs else None

    def wr(xs: List[float]) -> Optional[float]:
        return (sum(1 for x in xs if x > 0) / len(xs) * 100) if xs else None

    rows: List[Dict] = []
    for cat in sorted(buckets.keys(), key=_sort_key_for):
        in_roms, in_pcrs = buckets[cat]
        out_roms = [r for k, (rs, _) in buckets.items() if k != cat for r in rs]
        out_pcrs = [p for k, (_, ps) in buckets.items() if k != cat for p in ps]
        label = _label_for(col, cat)
        in_wr = wr(in_roms)
        out_wr = wr(out_roms)
        for metric, in_val, out_val, baseline in (
            ("AvgROR", mean(in_roms), mean(out_roms), baseline_avg_ror),
            ("AvgPCR", mean(in_pcrs), mean(out_pcrs), baseline_avg_pcr),
        ):
            rows.append({
                "csv_column":        col,
                "category_value":    cat,
                "category_label":    label,
                "metric":            metric,
                "baseline_avg":      f"{baseline:.6f}",
                "total_trades":      str(total_trades),
                "in_sample_trades":  str(len(in_roms)),
                "in_sample":         (f"{in_val:.6f}" if in_val is not None else ""),
                "in_sample_wr":      (f"{in_wr:.4f}" if in_wr is not None else ""),
                "out_sample_trades": str(len(out_roms)),
                "out_sample":        (f"{out_val:.6f}" if out_val is not None else ""),
                "out_sample_wr":     (f"{out_wr:.4f}" if out_wr is not None else ""),
            })
    return rows


def write_categorical_csv(out_path: pathlib.Path, rows: List[Dict]) -> None:
    fieldnames = [
        "csv_column", "category_value", "category_label", "metric",
        "baseline_avg", "total_trades",
        "in_sample_trades", "in_sample", "in_sample_wr",
        "out_sample_trades", "out_sample", "out_sample_wr",
    ]
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        f.write("\ufeff")
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Pre-compute threshold sweep results for every continuous entry filter.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("block_id", help="Block folder name under TB root")
    ap.add_argument("--tb-root", default=TB_ROOT_DEFAULT, help="TradeBlocks Data root")
    ap.add_argument("--groups-csv", default=None,
                    help="Explicit entry_filter_groups CSV path (abs or relative to TB root)")
    ap.add_argument("--filter-by", default=None, metavar="COL=VAL",
                    help="Scope filters to rows where COL equals VAL (case-insensitive)")
    ap.add_argument("--step", type=int, default=5,
                    help="Retention target step in percentage points")
    args = ap.parse_args()

    if args.step <= 0 or args.step > 100:
        print(f"ERROR: --step must be in (0, 100], got {args.step}", file=sys.stderr)
        return 1

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
        data_path = resolve_data_csv(ref_folder)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return EXIT_MISSING_DATA_CSV

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
    try:
        display_data = data_path.relative_to(tb_root)
    except ValueError:
        display_data = data_path

    print(f"Data CSV:   {display_data}  [block-local]")
    print(f"Groups CSV: {display_groups}  [{source}]")

    try:
        groups = load_groups(groups_path)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    try:
        scoped = apply_filter_by(groups, args.filter_by)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return EXIT_FILTER_BY_ERROR

    # Apply the `Entry Filter` scope column — rows tagged FALSE are present in
    # the shared groups registry for data-collection purposes (e.g. VIX_at_Close
    # is useful context but NOT a valid entry signal due to lookahead) but must
    # not pollute the sweep results. Missing/blank values default to TRUE so
    # older groups CSVs without this column keep the pre-change behavior.
    def _is_entry_filter(r: Dict) -> bool:
        v = (r.get("Entry Filter") or "").strip().upper()
        return v != "FALSE"  # default TRUE when blank/missing

    non_entry_excluded = [r for r in scoped if not _is_entry_filter(r)]
    scoped = [r for r in scoped if _is_entry_filter(r)]
    if non_entry_excluded:
        names = ", ".join(r.get("CSV Column","?") for r in non_entry_excluded)
        print(f"Excluded from sweep (Entry Filter = FALSE): {len(non_entry_excluded)} "
              f"filter(s) — {names}")

    # Filter to continuous rows with non-blank CSV Column.
    continuous = [
        r for r in scoped
        if (r.get("Filter Type") or "").strip().lower() == "continuous"
        and (r.get("CSV Column") or "").strip()
    ]
    print(f"Continuous filters in groups: {len(continuous)} (of {len(scoped)} in scope)")

    # Load trade data.
    trades, data_header = load_data(data_path)
    total_trades = len(trades)
    if total_trades == 0:
        print("ERROR: entry_filter_data.csv has no rows.", file=sys.stderr)
        return 1

    # Baselines (net ROR is the retention denominator for both metric runs).
    roms_all = [parse_float(t.get("rom_pct")) for t in trades]
    pcrs_all = [parse_float(t.get("pcr_pct")) for t in trades]
    if any(r is None for r in roms_all):
        print("ERROR: entry_filter_data.csv has null rom_pct values.", file=sys.stderr)
        return 1
    roms_all_nn = [r for r in roms_all if r is not None]
    pcrs_all_nn = [p for p in pcrs_all if p is not None]
    baseline_net_ror = sum(roms_all_nn)
    baseline_avg_ror = baseline_net_ror / len(roms_all_nn)
    baseline_avg_pcr = sum(pcrs_all_nn) / len(pcrs_all_nn) if pcrs_all_nn else 0.0
    baseline_wr = sum(1 for r in roms_all_nn if r > 0) / len(roms_all_nn) * 100
    _gp = sum(r for r in roms_all_nn if r > 0)
    _gl = abs(sum(r for r in roms_all_nn if r < 0))
    baseline_pf = _gp / _gl if _gl > 0 else float("inf")

    # Build per-filter arrays, skipping filters whose column is missing or has >10% nulls.
    filter_data: Dict[str, Tuple[List[float], List[float], List[float]]] = {}
    skipped_missing: List[str] = []
    skipped_null: List[str] = []
    for f in continuous:
        col = (f.get("CSV Column") or "").strip()
        if col not in data_header:
            skipped_missing.append(col)
            continue
        vals, roms, pcrs, nulls = build_filter_arrays(trades, col)
        if nulls > total_trades * MAX_NULL_FRAC:
            skipped_null.append(col)
            continue
        filter_data[col] = (vals, roms, pcrs)

    if not filter_data:
        print("ERROR: no continuous filters passed the null threshold.", file=sys.stderr)
        return 1

    # Determine retention target list from data.
    max_ret = compute_max_achieved_retention(filter_data, baseline_net_ror, total_trades)
    targets = build_target_list(max_ret, args.step)
    print(f"Max retention achieved: {max_ret:.1f}%")
    print(f"Retention targets: R_{targets[0]} → R_{targets[-1]} (step {args.step}) = {len(targets)} targets")

    # Map csv_column → groups row (for metadata).
    meta_by_col: Dict[str, Dict] = {}
    for f in continuous:
        col = (f.get("CSV Column") or "").strip()
        if col and col not in meta_by_col:
            meta_by_col[col] = f

    # Run the sweep. Each filter × direction generates 3 candidates per target
    # (tightest, max_ror, max_pcr) — rendered into 2 variants × 4 metrics = 8
    # rows. Total rows = filters × 3 directions × 8 = 24 rows per filter.
    print(f"\nSweeping {len(filter_data)} filters × {len(DIRECTIONS)} directions × {len(VARIANTS)} variants × {len(METRICS)} metrics × {len(targets)} targets...")
    rows_out: List[Dict] = []
    for col, (vals, roms, pcrs) in filter_data.items():
        for direction in DIRECTIONS:
            per_target, max_net_ror = sweep_one_direction(
                vals, roms, pcrs,
                baseline_net=baseline_net_ror,
                total_trades=total_trades,
                targets=targets,
                direction=direction,
            )
            # Emit the 8 rows for this (filter, direction): 2 variants × 4 metrics.
            # baseline_avg depends on metric (ROR vs PCR); threshold rows carry
            # an empty baseline_avg (they report filter values, not metric averages).
            for variant in VARIANTS:
                # Which candidate does this variant read?
                cand_for_variant = "tightest" if variant == "tightest" else "max_ror"
                # max_avg variant splits: AvgROR/ThresholdROR use max_ror, AvgPCR/ThresholdPCR use max_pcr.
                for metric in METRICS:
                    if variant == "tightest":
                        cand_key = "tightest"
                    else:
                        cand_key = "max_ror" if metric in ("AvgROR", "ThresholdROR") else "max_pcr"

                    baseline_for_metric = (
                        baseline_avg_ror if metric == "AvgROR"
                        else baseline_avg_pcr if metric == "AvgPCR"
                        else ""   # threshold rows: no baseline
                    )
                    row = {
                        "csv_column":   col,
                        "direction":    direction,
                        "variant":      variant,
                        "metric":       metric,
                        "baseline_avg": (f"{baseline_for_metric:.6f}" if isinstance(baseline_for_metric, float) else ""),
                        "baseline_wr":  f"{baseline_wr:.4f}",
                        "baseline_pf":  (f"{baseline_pf:.4f}" if baseline_pf != float("inf") else "inf"),
                        "total_trades": str(total_trades),
                        "max_net_ror":  f"{max_net_ror:.2f}",
                    }
                    for T in targets:
                        entry = per_target.get(T, {}).get(cand_key)
                        if entry is None:
                            row[f"R_{T}"] = ""
                            continue
                        if metric == "AvgROR":
                            row[f"R_{T}"] = f"{entry['avg_ror']:.6f}"
                        elif metric == "AvgPCR":
                            row[f"R_{T}"] = f"{entry['avg_pcr']:.6f}"
                        else:   # ThresholdROR or ThresholdPCR
                            row[f"R_{T}"] = _fmt_threshold(entry["t"])
                    rows_out.append(row)

    # Write continuous sweep.
    out_path = ref_folder / "entry_filter_threshold_results.csv"
    write_sweep_csv(out_path, rows_out, targets)

    try:
        out_rel = out_path.relative_to(tb_root)
    except ValueError:
        out_rel = out_path

    # ── Categorical sweep ────────────────────────────────────────────────────
    # Scope: every groups row whose Filter Type == "categorical" and CSV Column
    # is present in the data. Ordered by Index (groups CSV order preserved).
    # Sibling CSV — separate file because the schema differs (category rows,
    # not direction/variant/target cells).
    def _idx_key(row: Dict) -> Tuple[int, str]:
        try:
            return (0, int(float(row.get("Index") or 0)))
        except (ValueError, TypeError):
            return (1, (row.get("Index") or ""))
    # Include both binary and categorical — binary is a degenerate categorical
    # (K=2), but the heatmap consumes both through the same codepath so keeping
    # them together in the sweep CSV means the heatmap needs only this file.
    categorical = sorted(
        [
            r for r in scoped
            if (r.get("Filter Type") or "").strip().lower() in ("categorical", "binary")
            and (r.get("CSV Column") or "").strip()
        ],
        key=_idx_key,
    )

    cat_rows: List[Dict] = []
    cat_skipped_missing: List[str] = []
    cat_cols_processed: List[str] = []
    for f in categorical:
        col = (f.get("CSV Column") or "").strip()
        if col not in data_header:
            cat_skipped_missing.append(col)
            continue
        filter_rows = sweep_categorical_filter(
            trades, col,
            baseline_avg_ror=baseline_avg_ror,
            baseline_avg_pcr=baseline_avg_pcr,
            baseline_net_ror=baseline_net_ror,
            total_trades=total_trades,
        )
        if filter_rows:
            cat_rows.extend(filter_rows)
            cat_cols_processed.append(col)

    cat_out_path = ref_folder / "entry_filter_categorical_results.csv"
    write_categorical_csv(cat_out_path, cat_rows)
    try:
        cat_out_rel = cat_out_path.relative_to(tb_root)
    except ValueError:
        cat_out_rel = cat_out_path

    print("\nSweep complete.")
    print("\nSources")
    print(f"  Block:                   {args.block_id}")
    print(f"  Data CSV:                {display_data}  [block-local]")
    print(f"  Groups CSV:              {display_groups}  [{source}]")
    print(f"  Continuous output CSV:   {out_rel}  [block-local]")
    print(f"  Categorical output CSV:  {cat_out_rel}  [block-local]")

    print("\nScope")
    print(f"  Continuous filters in scope:    {len(filter_data)}")
    if skipped_null:
        print(f"  Skipped (>10% nulls):           {', '.join(skipped_null)}")
    if skipped_missing:
        print(f"  Skipped (column not in data):   {', '.join(skipped_missing)}")
    print(f"  Categorical filters in scope:   {len(cat_cols_processed)} ({', '.join(cat_cols_processed) if cat_cols_processed else '—'})")
    if cat_skipped_missing:
        print(f"  Categorical skipped (not in data): {', '.join(cat_skipped_missing)}")

    print("\nDimensions")
    print(f"  Continuous rows written:        {len(rows_out)}   ({len(filter_data)} × {len(DIRECTIONS)} directions × {len(VARIANTS)} variants × {len(METRICS)} metrics)")
    print(f"  Retention target columns:       R_{targets[0]} … R_{targets[-1]}   ({len(targets)} targets, step={args.step})")
    print(f"  Max retention achieved:         {max_ret:.1f}%")
    print(f"  Categorical rows written:       {len(cat_rows)}   ({len(cat_cols_processed)} filters × categories × 2 metrics)")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
