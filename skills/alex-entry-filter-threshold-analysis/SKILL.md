---
name: alex-entry-filter-threshold-analysis
description: >
  Threshold analysis for a single entry filter on a block. Sweeps the filter
  across its unique values, computes retention references (99% through 50% of baseline
  Net ROR), and renders an interactive HTML chart with efficiency frontier, scatter,
  and OO filter translation. Reads only two block-local CSVs: entry_filter_data.csv
  and entry_filter_groups.*.csv. Never builds data — defers to alex-entry-filter-build-data.
  Filter labeling, ordering, and filter list all come from the groups CSV so the user
  can customize per-block by editing their local copy.
compatibility: Requires Python 3 with numpy. No MCP. No DuckDB. No network.
metadata:
  author: alex-tradeblocks
  version: "5.0.1"
---

# Entry Filter Threshold Analysis

Single-filter deep-dive. Renders an interactive HTML chart showing how ROM, Net ROR, and Win Rate evolve as a threshold sweeps across the filter's observed range, with efficiency-frontier markers at standard retention levels (99% → 50% of baseline Net ROR) and an OO-friendly filter-string translator. One filter per run. Zero external dependencies beyond the two block-local CSVs.

## Architecture

Single CLI driver owned by this skill. No shared modules. No wrappers. No MCP.

```
{skill_dir}/
├── SKILL.md
└── gen_threshold_analysis.py   ← the driver
```

(`{skill_dir}` = this skill's base directory, announced when the skill is loaded.)

The driver:
1. Resolves the block folder and ref folder from `BLOCK_ID`.
2. Locates `entry_filter_data.csv` (errors if missing).
3. Locates exactly one `entry_filter_groups.*.csv` in the block ref folder (or uses `--groups-csv`).
4. Resolves the user's FILTER argument against the groups CSV via a 5-step ladder.
5. Extracts baseline stats and calls the existing Chart.js HTML template (unchanged).
6. Writes the report to the block folder.

## File Dependencies

| File | Role |
|---|---|
| `{block}/alex-tradeblocks-ref/entry_filter_data.csv` | Trade-level data |
| `{block}/alex-tradeblocks-ref/entry_filter_groups.*.csv` | Filter registry (labels, short names, indices, entry groups) |

**If either is missing, run `/alex-entry-filter-build-data BLOCK_ID` first.** This skill never builds data.

## Prerequisites

- `alex-entry-filter-build-data` has been run against the block at least once (creates both CSVs).
- Python 3 with `numpy`.

## CLI

```bash
python3 "{skill_dir}/gen_threshold_analysis.py" \
    BLOCK_ID [FILTER] \
    [--tb-root PATH] \
    [--groups-csv PATH] \
    [--filter-by "COLUMN=VALUE"] \
    [--list]
```

**Positional args**
- `BLOCK_ID` — required. Block folder name under the TB root.
- `FILTER` — optional. If omitted and `--list` not passed, the skill exits with code 5 and prints the available filter list so you can pick one.

**Flags**
- `--tb-root PATH` — override the TB Data root (default is hardcoded).
- `--groups-csv PATH` — explicit groups CSV (absolute or relative to TB root). Lets the user select a non-default variant (e.g., `entry_filter_groups.V2.csv`, `entry_filter_groups.calendar.csv`).
- `--filter-by "COLUMN=VALUE"` — narrow the active filter pool to rows where `COLUMN == VALUE` (case-insensitive string comparison). Works for `--list` and for single-filter resolution. Example: `--filter-by "Calendar Report=TRUE"`, `--filter-by "Entry Group=A: Volatility"`.
- `--list` — print available filters grouped by Entry Group and exit. Honors `--filter-by`.

## Filter resolution ladder

The `FILTER` argument is resolved against the groups CSV in this order — first step with matches wins:

1. Exact case-sensitive match on `CSV Column`
2. Exact integer match on `Index`
3. Exact case-insensitive match on `Short Name`
4. Exact case-insensitive match on `Filter`
5. Case-insensitive substring contains across `Filter` + `Short Name` + `CSV Column`

Zero matches or multiple fuzzy matches → exit 6 with candidates listed.

## Output

`{block}/entry filter threshold analysis [<Short Name>].html`

The filename uses the **Short Name** column value (sanitized — `/` becomes ` over `, other unsafe chars replaced). The full `Filter` column value still appears inside the HTML title, subtitle, and chart labels. This keeps block-folder filenames compact while preserving rich labels in the report.

## Exit codes

| Code | Meaning | Invoker action |
|---|---|---|
| 0 | HTML written (or `--list` completed) | `open` the file |
| 1 | Generic error (unreadable CSV, malformed registry, etc.) | Fix and retry |
| 2 | `entry_filter_data.csv` missing | Offer `/alex-entry-filter-build-data BLOCK_ID` |
| 3 | No `entry_filter_groups.*.csv` in block ref folder | Same — run build-data first |
| 4 | Multiple groups CSV variants present, none chosen | Ask which variant, then retry with `--groups-csv` |
| 5 | `FILTER` not provided | Show the filter list to the user and ask which one |
| 6 | `FILTER` unresolvable, ambiguous, or filtered out by `--filter-by` | Surface candidates; ask user to narrow |
| 7 | Resolved filter has empty `Short Name` | Ask user to populate the column in the groups CSV |

## Process (for Claude when invoked)

1. **Confirm the target block.** If not already known, call `list_blocks` or ask.
2. **Invoke the driver** with the user-specified filter (if given). Run from TB root:
   ```bash
   python3 "{skill_dir}/gen_threshold_analysis.py" "<BLOCK>" "<FILTER>"
   ```
3. **Handle non-zero exit codes** per the table above.
4. **On exit 0:** surface the output path to the user and offer to `open` it.

## Groups CSV columns used

- **`CSV Column`** — maps to the actual column in `entry_filter_data.csv` that gets analyzed.
- **`Index`** — ordering for listings; also a resolution target.
- **`Short Name`** — concise label for the output filename and for space-constrained rendering.
- **`Filter`** — full display name, used in HTML title/subtitle/chart labels.
- **`Entry Group`** — category bucket, used to group the filter list.

The user may add new columns (e.g., `Calendar Report`) and use `--filter-by "Calendar Report=TRUE"` to scope runs. The skill doesn't interpret custom columns — it just uses them for the `--filter-by` predicate.

## Auto-detection

- **Vertical 0-line on X-axis:** the driver checks the field's min/max on load. If the values span negative-to-positive, the 0-line renders automatically. No per-field config needed.
- **OO translator style:** `vix_on` for `VIX_Gap_Pct` (signed overnight move); `simple` for everything else. Hardcoded at the mapping layer; can be promoted to a groups CSV column later if needed.

## Chart rendering preferences (mandated)

These rules must stay true in the HTML output. They're enforced in the driver today; if the chart template is edited, preserve them.

- **Section order.** The report presents sections in this exact order, top-to-bottom:
  1. Title (`<h1>`) and subtitle
  2. Metric cards (6-card row: trades, baseline ROM/NetROR/WR/PF, correlation)
  3. **Scatter chart** — `Trade ROM vs <Filter>` (raw per-trade view, shown first so the user sees the underlying data before any derivations)
  4. **Threshold Sweep chart** — Avg ROM by `>= threshold` and `<= threshold` directions, plus CDFs for `% Trades` and `% Net ROR`
  5. **Efficiency Frontier chart** — retention vs Avg ROM curve
  6. **Retention References table** — numeric summary with OO filter translations
- **No sample-size shading on the threshold chart.** Earlier versions shaded regions where fewer than 30 trades survived (`thinBoxGt` / `thinBoxLt` box annotations). These are removed. Trade count is already surfaced in the tooltip and the retention reference table; shading adds visual noise without new information.
- **No minimum-sample floor. Report everything.** Earlier versions filtered out thresholds where fewer than 10 trades survived. That's gone — the threshold sweep, retention references, and efficiency frontier now include every single unique threshold, down to the single-trade extremes. Thin data shows up as visible variability on the charts (whipsawing curves at the tails, noisy retention values) — better to see that directly than have it silently hidden.
- **Frontier sweep is full range.** The efficiency frontier scans retention targets from **500% down to 0%** in 1pp steps (the upper ceiling is a generous guard — any target above the data's achievable max just produces no point and costs nothing). This exposes the full Pareto curve including the extreme-cherry-pick end (where a tight combo drops losers and pushes Net ROR above baseline) and the near-empty-set tail at 0%.
- **Thin-data warning icon.** Any retention-reference row with fewer than 30 surviving trades renders a ⚠ icon in the Trades column. The icon has a hover-tooltip explaining the risk ("Thin sample: N trades. Avg ROM is noisy — interpret with caution."). Data is still reported — the icon just flags variance risk. Threshold: `THIN_N = 30` in the JS.

### Interactive X-axis controls (consistent across all three charts)

Each chart exposes a **pair** of number inputs (Low and High) rendered directly above it. Every input change triggers both an X-axis update and a Y-axis auto-refit on that chart. Implementation uses a shared `wireXControls(lowId, highId, onChange)` helper so all three charts follow the same pattern.

**Scatter + Threshold share one pair of inputs** (`#sharedXLow`, `#sharedXHigh`). The two charts visualize the same filter-value domain and must stay in sync — a threshold reference line drawn on one must line up with its underlying trade dots on the other. Adjusting either input updates both chart X axes and recomputes each chart's Y bounds independently (scatter Y from per-trade ROM; threshold yRom from gtRom/ltRom; threshold yPct stays fixed at [-5, 110] because it's a CDF).

**Efficiency Frontier has its own pair** (`#effXLow`, `#effXHigh`). Different X domain (retention %), so it gets independent controls.

**Defaults (set by JS from actual chart-init bounds — single source of truth, not duplicated in HTML value attributes):**
- Scatter/threshold X Low = `min(filter_values)` (the data min)
- Scatter/threshold X High = `max(filter_values)` (the data max)
- EF X High = `max(105%, data_max + 5)` (the data-driven ceiling) — listed first to match the axis direction (X is `reverse: true`, high on the left)
- EF X Low = **20** (cuts off the noisy near-empty-set tail; chart still scans full range when the user widens it)

**Y axis behavior is uniform** across all three charts. Each chart has its own bounds function (`scatterYBounds`, `threshYBounds`, `effYBounds`) that share a common `yBoundsFormula(ys)` producing `{ min: min(0, min(visibleY)) - 2, max: max(visibleY) + 2 }`. Zero is always included as a floor so the baseline reference is visible. When the X window narrows, the Y axis auto-zooms — so the chart never wastes vertical space on off-screen extremes. Update is `chart.update('none')` (no animation, instant redraw).
- **Title uses Title Case.** The `<title>` and `<h1>` both read `Entry Filter Threshold Analysis - <Short Name>` (e.g., `Entry Filter Threshold Analysis - SLR`). The underlying filename on disk still uses the lowercase-plus-brackets form (`entry filter threshold analysis [SLR].html`) for tidy sorting, but the in-report display is capitalized for readability.

## What NOT to do

- Don't auto-build missing data. If either CSV is missing, surface the error and offer `/alex-entry-filter-build-data`.
- Don't estimate ROM from aggregated P/L and aggregated margin. The driver computes baseline ROM correctly (per-trade ROM, averaged); don't replace with a simpler aggregation that double-normalizes.
- Don't hard-code field-name lookups. All resolution goes through the block-local groups CSV.
- Don't write block-specific wrapper scripts. The CLI is the single entry point.
- Don't touch the plugin's `_shared/` folder at runtime. This skill is strictly block-local.

## Related skills

- `alex-entry-filter-build-data` — upstream. Creates the two CSVs this skill reads.
- `alex-entry-filter-heatmap` — all-filter retention view. Complements this skill's single-filter deep dive.
- `alex-create-datelist` — generate OO-compatible datelists once a threshold decision is made.

## Changelog

- **5.0.0-dev** — Pre-compute all aggregates in Python, eliminating the O(u² × n) client-side combo sweep that hung the browser on large blocks (u ≈ 4,000, n ≈ 4,300). Browser now does only render work. Server-side math uses sorted-prefix sums (see `_compute_aggregates` in `gen_threshold_analysis.py`) and takes ~5-10s at u ≈ 2,000 pairs-worth of aggregation. Output: identical retention-reference numbers, chart layouts, and OO filter strings as 4.0.3. Efficiency-frontier combo curve is now a Pareto front (strict dominance) rather than a 501-step target sweep — same visual result, fewer redundant points. HTML size grows from ~150 KB to ~1.5 MB for large-n blocks because aggregated state is serialized inline; small-n blocks barely change.
- **4.0.3-dev** — Previous client-side recomputation approach. Worked for filtered blocks (n ≤ 500) but hung on No-Filters blocks due to O(u² × n) JS loops.
