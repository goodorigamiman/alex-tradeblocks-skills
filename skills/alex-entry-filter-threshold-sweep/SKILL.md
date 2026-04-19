---
name: alex-entry-filter-threshold-sweep
description: 'Pre-computes sweep results for every continuous AND categorical entry filter on a block. Writes TWO sibling CSVs next to entry_filter_data.csv: entry_filter_threshold_results.csv (continuous — wide retention-target grid with tightest/max_avg variants across AvgROR/AvgPCR × low/high/combo direction) and entry_filter_categorical_results.csv (categorical — one row per category × metric, columns in_sample and out_sample for inclusion vs exclusion impact). Downstream skills (heatmap, pareto, future consumers) read these CSVs instead of recomputing. Reads only two block-local CSVs; never builds data itself. Defers upstream to dev-entry-filter-build-data.

  '
compatibility: Python 3 standard library only. No MCP, no DuckDB, no numpy.
metadata:
  author: alex-tradeblocks
  version: 1.2.0
---

# Entry Filter Threshold Sweep

**Run this before the heatmap, pareto, or any report that needs pre-computed retention curves.** Writes one CSV per block that captures, for every continuous filter, the average ROR (or average PCR) of surviving trades at the tightest threshold achieving retention ≥ T% of baseline Net ROR — across the full range of T from 0% up to the maximum observed.

## Architecture

```
Dev-TradeBlocks-Skills/alex-entry-filter-threshold-sweep/
├── SKILL.md
└── gen_sweep.py   ← the driver
```

Single CLI driver. No shared modules at runtime. No MCP, no DuckDB, no network. Monolithic Python.

## File Dependencies

| File | Role |
|---|---|
| `{block}/alex-tradeblocks-ref/entry_filter_data.csv` | Trade-level data |
| `{block}/alex-tradeblocks-ref/entry_filter_groups.*.csv` | Filter registry (for CSV Column, Short Name, Entry Group, Filter Type metadata) |

If either is missing, exit with the appropriate non-zero code and tell the user to run `/alex-entry-filter-build-data BLOCK_ID` first.

## Output

Every run writes TWO sibling CSVs under `{block}/alex-tradeblocks-ref/`:

| File | Contents |
|---|---|
| `entry_filter_threshold_results.csv` | Continuous filters — wide retention-target grid |
| `entry_filter_categorical_results.csv` | Categorical filters — one row per category × metric with in/out-sample columns |

---

### Continuous output: `entry_filter_threshold_results.csv`

### Schema (wide CSV)

**Metadata columns (always present, 7 cols):**

| Column | Description |
|---|---|
| `csv_column` | Joins back to `entry_filter_data.csv` and to `entry_filter_groups` (via `CSV Column`). Downstream reports look up display names, entry group, filter type, etc. from the groups CSV — this file stores no redundant metadata. |
| `direction` | `low threshold` (>=), `high threshold` (<=), or `combo` ([lo, hi]) |
| `variant` | `tightest` — most-selective qualifying threshold (smallest survivor count). For low/high this is the highest/lowest qualifying t; for combo it's the smallest-n qualifying pair.<br>`max_avg` — threshold chosen to maximize the row's metric. Selections for AvgROR and AvgPCR can differ under this variant. |
| `metric` | One of:<br>• `AvgROR` — cell = avg ROR of survivors at the selected threshold<br>• `AvgPCR` — cell = avg PCR of survivors at the selected threshold<br>• `ThresholdROR` — cell = the threshold used for AvgROR selection (numeric for low/high, `"lo\|hi"` for combo)<br>• `ThresholdPCR` — cell = the threshold used for AvgPCR selection |
| `baseline_avg` | Baseline of the chosen metric across all trades. Blank for Threshold rows. |
| `total_trades` | Total trade count in the block |
| `max_net_ror` | **Max net ROR retention observed** for this (filter × direction) across any qualifying threshold/pair — not bounded by the target bucket grid. Same value repeats across all 8 rows of a (filter × direction). Positioned immediately before the `R_*` target columns. |

**Retention target columns (dynamic per block, step 5% by default):**

- Named `R_<T>` where T is the retention target in whole percentage points.
- Range: ceiling down to 0 in `--step` increments. Ceiling is `max(105, round_up(max_observed_retention / step) * step)` — so blocks where a combo beats baseline get columns above `R_100` automatically; blocks where nothing exceeds 100% cap at `R_105`. The top column is typically blank (one blank above the highest achieved retention, signaling "range complete"); if a block's max retention lands exactly on a step boundary, the top column has data and there's no headroom blank.
- **Cell value** = mean of the metric (ROR or PCR) across survivors at the best threshold that achieves retention ≥ T%. Blank when no threshold meets the target.

### Row inventory

Every (filter × direction) combination emits 8 rows: **2 variants × 4 metrics**. For a block with N in-scope continuous filters: **N × 3 directions × 2 variants × 4 metrics = 24N rows**.

For the Lambo block: 34 in-scope filters → 816 rows × 31 cols (with max retention 111% → 24 target columns R_115 down to R_0).

### Semantic notes

- **Min/Max rows are consistent across metrics.** The threshold selection depends only on the retention criterion (net ROR), not on the reported metric. So `AvgROR/low threshold/R_T` and `AvgPCR/low threshold/R_T` use the same underlying subset — only the averaged series differs.
- **Combo rows diverge across metrics.** The `(lo, hi)` pair selected for `AvgROR/combo/R_T` maximizes survivor avg ROR; for `AvgPCR/combo/R_T` it maximizes survivor avg PCR. These can be substantially different pairs when ROR and PCR rank trades differently.

---

### Categorical output: `entry_filter_categorical_results.csv`

One row per `(csv_column, category_value, metric)`. Row order follows the `Index` column in `entry_filter_groups.*.csv` (so grouped reports can render filters in registry order without a secondary sort). Within each filter, categories are sorted numerically (with `">=4"` last for the aggregated bucket).

| Column | Description |
|---|---|
| `csv_column` | Join key back to `entry_filter_data.csv` and `entry_filter_groups` (via `CSV Column`). |
| `category_value` | Raw CSV value (e.g. `"1"`, `"6"`). For `Weeks_to_Holiday` / `Weeks_from_Holiday`, values `>= 4` collapse into a single row with `category_value = ">=4"`. |
| `category_label` | Display-friendly label (`Mon`, `Jan`, `Backwardation`, `4+`…). Purely informational — downstream joins use `category_value`. |
| `metric` | `AvgROR` or `AvgPCR` — one row per metric for each category. |
| `baseline_avg` | Baseline of the chosen metric across all trades (same value across all rows for a metric). |
| `total_trades` | Total trade count in the block. |
| `in_sample_trades` | Count of trades where `col == category_value` (for `>=4`, trades where col ≥ 4). |
| `in_sample` | Mean of `metric` over the in-sample subset. |
| `out_sample_trades` | Count of non-null trades where `col != category_value`. |
| `out_sample` | Mean of `metric` over the out-sample subset. Blank when the complement is empty (e.g. Monday-only strategy → Day_of_Week has no Out group). |

**Label map** (display-only): `Day_of_Week {1..5 → Mon..Fri}`, `Month {1..12 → Jan..Dec}`, `Term_Structure_State {-1 → Backwardation, 0 → Flat, 1 → Contango}`. Other columns (`Vol_Regime`, `Weeks_*`, `Days_*`) pass through raw; `Weeks_to_Holiday` and `Weeks_from_Holiday` aggregate `>= 4` into a single `">=4"` row labelled `"4+"`.

**Row count:** for each categorical filter with K categories, the CSV contributes `K × 2` rows (one per metric). The Lambo block has 8 categorical filters with 104 total category buckets → **208 rows**.

**In/Out semantics:** both sides exclude NULLs — a trade missing the column value is dropped from both in_sample and out_sample (consistent with heatmap rules). For binary-ish categoricals the Out row for category A is identical to the In row for category B (they cover the complementary trade sets), which is intentional redundancy so each row can be consumed independently.

**Binary filters ARE included** — treated as degenerate 2-category categoricals. Each binary filter emits rows for value `0` and value `1` (2 × 2 metrics = 4 rows per binary filter). The `In` row for one value and the `Out` row for the other value cover identical trade subsets (redundant by definition), but having both keeps downstream renderers uniform — the heatmap consumes one file for all non-continuous filters.

## Prerequisites

- `alex-entry-filter-build-data` has been run against the block at least once.
- Python 3 standard library only.

## CLI

```bash
python3 "Dev-TradeBlocks-Skills/alex-entry-filter-threshold-sweep/gen_sweep.py" \
    BLOCK_ID \
    [--tb-root PATH] \
    [--groups-csv PATH] \
    [--filter-by "COLUMN=VALUE"] \
    [--step PCT]
```

**Positional**
- `BLOCK_ID` — required; block folder name.

**Flags**
- `--tb-root PATH` — override the hardcoded TB Data root.
- `--groups-csv PATH` — explicit groups CSV path (absolute or relative to TB root).
- `--filter-by "COLUMN=VALUE"` — narrow the filter scope (case-insensitive). Default: all continuous filters with ≤10% nulls. Useful for experimenting with a subset.
- `--step PCT` — retention target step in percentage points. Default: 5.

## Exit codes

| Code | Meaning | Invoker action |
|---|---|---|
| 0 | CSV written successfully | Proceed to downstream skills |
| 1 | Generic error (unreadable CSV, malformed registry, etc.) | Fix and retry |
| 2 | `entry_filter_data.csv` missing | Run `/alex-entry-filter-build-data BLOCK_ID` |
| 3 | No `entry_filter_groups.*.csv` in block ref folder | Run `/alex-entry-filter-build-data BLOCK_ID` |
| 4 | Multiple groups CSV variants, none chosen | Ask user which variant, pass `--groups-csv` |
| 6 | `--filter-by` column missing | Surface available columns, ask user to retry |

## Filter scope

**Continuous sweep** — rows where:
1. `Filter Type` is `continuous`.
2. `CSV Column` is non-blank and exists in `entry_filter_data.csv`.
3. The data column has ≤ 10% nulls.

**Categorical sweep** — rows where:
1. `Filter Type` is `categorical` OR `binary`.
2. `CSV Column` is non-blank and exists in `entry_filter_data.csv`.

(No null-threshold gate on categorical — NULLs are simply excluded from both in_sample and out_sample subsets. Binary filters are written as 2-category rows so downstream renderers can consume one file for all non-continuous filters.)

`--filter-by` narrows further if supplied. Downstream skills subset by their own flags (`--heatmap-col "Report Heatmap"`, etc.) from the resulting rows.

## Algorithm

For each in-scope continuous filter `col`:
1. Build `(filter_value, rom_pct, pcr_pct)` for every trade with non-null `col`.
2. Sort by filter value; build prefix sums for O(1) range aggregates.
3. For each `metric ∈ {AvgROR, AvgPCR}` and each `direction ∈ {low threshold, high threshold, combo}`:
   - **Low threshold:** scan unique values ascending; find the highest `t` such that survivors `val >= t` retain ≥ T% net ROR (for each target T). Record the survivor mean of the metric.
   - **High threshold:** scan descending; find the lowest `t` such that survivors `val <= t` retain ≥ T%.
   - **Combo:** scan every `(lo, hi)` pair; among those whose survivors retain ≥ T%, pick the one maximizing survivor mean metric.
4. Apply guards: survivors must have count ≥ `MIN_TRADES` (10) AND ≥ `MIN_TRADE_PCT%` (10%) of total trades. Otherwise the cell is blank.

Retention is always computed from **net ROR** (the denominator) regardless of which metric is reported — this is what the user specified. The metric choice only affects what's averaged across survivors and, for combo, what's optimized.

## Process (for Claude when invoked)

1. **Confirm the target block.**
2. **Invoke the driver:**
   ```bash
   python3 "Dev-TradeBlocks-Skills/alex-entry-filter-threshold-sweep/gen_sweep.py" "<BLOCK>"
   ```
3. **Handle non-zero exit codes** per the table above.
4. **On exit 0:** report the CSV path and summary (rows written, targets, max retention). Suggest the heatmap or pareto as the next step.

## Related skills

- `alex-entry-filter-build-data` — upstream. Creates the two input CSVs.
- `alex-entry-filter-heatmap` — downstream. Consumes the sweep CSV instead of recomputing.
- `alex-entry-filter-threshold-analysis` — single-filter interactive drill-down. Computes its own sweep client-side (intentional — enables the interactive Chart.js zoom without a round-trip).

## What NOT to do

- Don't auto-build missing data. Defer to `alex-entry-filter-build-data`.
- Don't read from `_shared/` at runtime. Block-local only.
- Don't persist the threshold value in the CSV. The user chose "one column per target" — only the avg metric is stored. Downstream skills that need the threshold value can re-derive it from the data CSV by re-running a single-filter scan (cheap for one filter).
