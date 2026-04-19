---
name: alex-entry-filter-heatmap
description: "Entry-filter retention heatmap for a block. Discovery Map (global, sorted by 80r% delta, includes Min/Max/Combo) + By Filter Group table (per-Entry-Group Min/Max/Combo restatement, cells color-only) + Binary & Categorical breakdown (clickable, In/Out side-by-side). Every data cell is click-to-capture \u2014 continuous threshold/combo expressions and binary/categorical In (==) / Out (!=) expressions all feed one selections panel, persisted in localStorage, copy-to-clipboard feeds alex-create-datelist. Reads THREE block-local CSVs and only these three: entry_filter_groups.*.csv (labels & organization), entry_filter_threshold_results.csv (continuous sweep data + block baselines), entry_filter_categorical_results.csv (binary + categorical In/Out stats). Does NOT read entry_filter_data.csv \u2014 every number it shows is pre-computed by alex-entry-filter-threshold-sweep. Defaults: AvgROR metric, max_avg variant, Report Heatmap column for filter inclusion. All three overridable via\
  \ --sweep-metric, --sweep-variant, --heatmap-col."
compatibility: Requires Python 3 standard library only. No MCP, no DuckDB, no network, no numpy.
metadata:
  author: alex-tradeblocks
  version: 5.0.1
---

# Entry Filter Heatmap

All-filter retention overview. Three sections:
1. **Discovery Map** — compact global grid. Every (continuous filter × Min/Max/Combo direction × retention target) becomes a cell, colored by Avg ROM delta vs baseline, sorted left-to-right by 80r% delta (best-lift filters first). Combo lives here so high-retention combo bands surface alongside the best single-direction setups without needing a separate view.
2. **By Filter Group** — per-Entry-Group compact restatement at the filter level. Min/Max/Combo rows per continuous filter, grouped by Entry Group. Cells are color-only — threshold, avg, and delta are in the tooltip and captured on click. Use this when you already know which group holds the filter you want and want to compare Min vs Max vs Combo side-by-side within a single filter. Min/Max cells cross-highlight with Discovery; Combo highlights in both sections.
3. **Binary & Categorical Breakdown** — per-value stats for non-continuous filters (Day_of_Week, Gap_Filled, Vol_Regime, Is_Opex, holidays, etc.). Two side-by-side clickable blocks per category: **In Group (==)** for `col == value`; **Out Group (!=)** for the complement `col != value`. Each side shows three columns: `Avg ROM` (subset mean), `+avg pts` (avg-ROM delta vs baseline in pp), `+net ROM` (share-of-edge bump = `pct_baseline - pct_trades`, positive = subset carries disproportionately more Net ROR than its share of trades). Tooltip adds the absolute Net ROM value (both raw sum and as % of baseline), trade count, and WR. Click "In" to capture `{col} == {val}` (or `{col} >= 4` for the 4+ aggregated bucket). Click "Out" to capture `{col} != {val}` (or `{col} < 4` for the 4+ inverse).

**Every data cell is click-to-capture** — Discovery cells, By-Filter-Group cells, and Binary/Categorical ROM cells all feed the same floating selections panel, persist to localStorage, and can be copied to clipboard. Mutual highlight (orange outline) ties Discovery ↔ By Filter Group for continuous Min/Max selections; Combo selections highlight only in Discovery; binary/categorical selections highlight only in the breakdown table.

## Architecture

Single CLI driver owned by this skill. No shared modules at runtime. No MCP, no DuckDB.

```
{skill_dir}/
├── SKILL.md
└── gen_heatmap.py   ← the driver
```

(`{skill_dir}` = this skill's base directory, announced when the skill is loaded.)

The driver:
1. Resolves the block folder and ref folder from `BLOCK_ID`.
2. Locates both sweep CSVs (exit 8 if either is missing).
3. Locates exactly one `entry_filter_groups.*.csv` in the block ref folder (or uses `--groups-csv`).
4. Scopes filters: rows where `--heatmap-col` (default `Report Heatmap`) is `TRUE`, optionally AND-combined with `--filter-by`.
5. Reads block baselines (total_trades, Avg ROR, Avg PCR, WR, PF) from the continuous sweep CSV's metadata columns.
6. Reads per-filter retention curves from the continuous sweep CSV and per-category In/Out stats from the categorical sweep CSV.
7. Renders a static HTML file to the block folder.

The skill never reads `entry_filter_data.csv`. Every number it shows is pre-computed by `alex-entry-filter-threshold-sweep`, which is the sole consumer of the raw trade data.

## File Dependencies

| File | Role | Produced by |
|---|---|---|
| `{block}/alex-tradeblocks-ref/entry_filter_groups.*.csv` | Filter registry — labels, Short Names, Entry Groups, Filter Type, `Report Heatmap` column | `alex-entry-filter-build-data` |
| `{block}/alex-tradeblocks-ref/entry_filter_threshold_results.csv` | Continuous sweep results — retention curves + block baselines | `alex-entry-filter-threshold-sweep` |
| `{block}/alex-tradeblocks-ref/entry_filter_categorical_results.csv` | Binary + categorical per-category In/Out stats | `alex-entry-filter-threshold-sweep` |

Those three files are the **only** runtime inputs. `entry_filter_data.csv` is not read and may even be deleted after the sweep runs (the sweep CSVs carry every derived value the heatmap needs).

**If any are missing, the skill exits with a specific code:**
- Exit 3 — groups CSV missing. Run `/alex-entry-filter-build-data BLOCK_ID`.
- Exit 8 — a sweep CSV is missing. Run `/alex-entry-filter-threshold-sweep BLOCK_ID`.

This skill **never builds data or recomputes any metric.** It reads and renders.

## Defaults at a glance

| Choice | Default | Override flag |
|---|---|---|
| Primary metric | `AvgROR` | `--sweep-metric {AvgROR,AvgPCR}` |
| Selection variant | `max_avg` | `--sweep-variant {tightest,max_avg}` |
| Filter inclusion column | `Report Heatmap` | `--heatmap-col <column name>` |
| Filter pool narrowing | (none) | `--filter-by "COLUMN=VALUE"` |
| Groups CSV variant | (auto-detected block-local) | `--groups-csv PATH` |

CLI flags set the **initial** dropdown position in the rendered report. The user can then switch metric and variant interactively in the browser without re-running the skill.

## Interactive dropdowns in the rendered HTML

Above the Discovery Map:

- **Metric:** `AvgROR` / `AvgPCR` — which metric's avg is rendered in cell tooltips and colors.
- **Variant:** `tightest` / `max_avg` — which selection rule's results are shown. `tightest` = most-selective qualifying threshold at each retention target; `max_avg` = threshold maximizing the chosen metric at each retention target. See `alex-entry-filter-threshold-sweep/README.md` for background.

Both dropdowns update **Discovery Map + Retention Detail** live on change. Binary & Categorical Breakdown is not recomputed (it's always relative to the AvgROR baseline and not driven by the sweep CSV).

The subtitle's `Sweep:` tag echoes the current selection (e.g., `metric=AvgPCR · variant=tightest`) so anyone looking at the report can tell which slice is displayed.

### What's stable across toggles (by design)

- **Color scale.** Anchored at the union of 80r% deltas across all 4 (metric × variant) combinations — cells don't flash wildly on toggle.
- **Column sort.** Fixed by the CLI-selected default's 80r% delta ranking — columns stay in place so you can scan one filter's behavior across the four combinations without hunting.
- **Retention target grid.** All 5% increments from the sweep CSV's data-driven ceiling down to R_5, applied to both tables. Filters that don't have data at the higher targets render as blank cells.

To re-sort by a different variant's 80r% ranking, re-run the skill with `--sweep-variant <other>` on the CLI — that resets the fixed sort order.

## Click-to-capture selections

Click any cell in the **Discovery Map** or **Retention Detail** to add its threshold expression to the floating **Selected Filters** panel (bottom-right corner). Click the same cell again to remove it.

Selected cells get an orange outline so you can see what's picked. Selections are keyed by `(metric, variant, filter, direction, retention_target)` — meaning the same cell under different toggle settings captures as a separate selection. Toggling variant/metric only highlights cells that match the current view; previously-captured selections from other views stay in the panel, just without a visible outline.

### Panel buttons

- **Copy expressions** — plain-text list of filter expressions, one per line. Paste into `/alex-create-datelist` or any OO-style filter builder.
- **Copy with context** — expressions + inline comments noting retention target, metric, direction, variant, and delta. Useful for documenting your picks.
- **Clear** — wipes all selections (with a confirmation prompt).
- **Header bar** (title row) — click to collapse/expand the panel.

### Persistence

Selections are saved to `localStorage` under the key `heatmap-selections`, so they survive page reloads. Clear them via the button, or browser devtools if you're scripting.

### Example workflow

1. Run `/alex-entry-filter-heatmap BLOCK` with the default view (AvgROR × max_avg × Report Heatmap).
2. Scan the Discovery Map for promising cells (strong green at moderate retention targets).
3. Click each promising cell — the panel fills up with expressions like `SLR ∈ [0.465, 0.649]`, `VIX_Close <= 29.43`, `ATR_Pct >= 1.517`.
4. Toggle to variant=tightest to see alternate thresholds for the same retention targets; click any additional cells of interest.
5. Click **Copy expressions** — the plaintext list is on your clipboard.
6. Feed the list to `/alex-create-datelist BLOCK` (or any downstream filter-evaluation tool) to turn the expressions into a dated trade-selection list.

Clicks on Binary/Categorical Breakdown cells are not captured (those don't have threshold expressions in the same form).

## Prerequisites

- `alex-entry-filter-build-data` has been run against the block at least once.
- `alex-entry-filter-threshold-sweep` has been run against the block **since the most recent build-data run** (the sweep CSV must reflect current data).
- The block-local groups CSV has a `Report Heatmap` column. If it doesn't (old block copy predating that refactor), either edit it to add the column, delete the block copy and re-run build-data to re-copy the updated shared default, or pass `--heatmap-col "Report V1"` as a one-off backward-compat path.

## CLI

```bash
python3 "{skill_dir}/gen_heatmap.py" \
    BLOCK_ID \
    [--tb-root PATH] \
    [--groups-csv PATH] \
    [--heatmap-col NAME] \
    [--filter-by "COLUMN=VALUE"] \
    [--list]
```

**Positional**
- `BLOCK_ID` — required; block folder name under the TB root.

**Flags**
- `--tb-root PATH` — override the hardcoded TB Data root.
- `--groups-csv PATH` — explicit groups CSV path. Enables variant selection (`.V1`, `.calendar`, etc.) without editing the block-local copy.
- `--heatmap-col NAME` — column in the groups CSV to use for filter inclusion. **Default: `Report Heatmap`**. Rows where this column equals `TRUE` (case-insensitive) are included. Override to match a different curation: `--heatmap-col "Report V1"` mirrors the pre-refactor behavior.
- `--sweep-metric {AvgROR,AvgPCR}` — which metric rows to read from the sweep CSV. Default `AvgROR` (matches pre-refactor heatmap output exactly). Pass `AvgPCR` to render the heatmap in premium-capture terms instead.
- `--sweep-variant {tightest,max_avg}` — which variant of sweep rows to read. **Default `max_avg`** — at each retention target, pick the threshold maximizing the chosen metric. This is the "best achievable edge at this retention budget" reading, and it gives the best-performing filter settings even when the retention curve is non-monotonic. Pass `tightest` to use the older "most-selective qualifying threshold" selection — useful when you want to see the shape of the retention curve itself rather than the best-case optimum.
- `--filter-by "COLUMN=VALUE"` — additional scoping, AND-combined with the `--heatmap-col` filter. E.g., `--filter-by "Entry Group=A: Volatility"` renders only volatility filters within the heatmap-tagged set.
- `--list` — print filters in scope grouped by Entry Group and exit without generating HTML.

## Exit codes

| Code | Meaning | Invoker action |
|---|---|---|
| 0 | HTML written (or `--list` completed) | `open` the file |
| 1 | Generic error (unreadable CSV, malformed registry, etc.) | Fix and retry |
| 3 | No `entry_filter_groups.*.csv` in block ref folder | Run `/alex-entry-filter-build-data BLOCK_ID` first |
| 4 | Multiple groups CSV variants, none chosen | Ask which variant, then retry with `--groups-csv` |
| 5 | `--heatmap-col` column doesn't exist in the groups CSV | Tell user to add the column or pass a different `--heatmap-col` (suggest `--heatmap-col "Report V1"` as backward-compat) |
| 6 | `--filter-by` column missing, or scoping produced zero filters | Surface available columns and filter set; ask user to narrow differently |
| 8 | Either sweep CSV missing (`entry_filter_threshold_results.csv` or `entry_filter_categorical_results.csv`) | Run `/alex-entry-filter-threshold-sweep BLOCK_ID` |

## Output

`{block}/entry filter heatmap.html` (spaces, lowercase — matches the threshold-analysis file-naming convention).

In-HTML title (`<title>` and `<h1>`): **`Entry Filter Heatmap`** (Title Case).

## Labeling (mandated)

Rendered in the Discovery Map column headers and the Retention Detail left column:
- **Primary label:** `Short Name` (tight — keeps the grid readable with 20+ filters across).
- **Subscript:** `CSV Column` in small monospace font — so the user can copy-paste into SQL/pandas without looking up the registry.
- **Hover tooltip:** full `Filter` text + CSV Column + Index — click-through style at-a-glance.

At the top of the report, a collapsible **Filter Reference** legend (`<details>`) lists every in-scope filter with Index · Filter · Short Name · CSV Column · Entry Group · Filter Type — one-stop lookup for the user.

## Chart rendering preferences (mandated)

- **Section order:** metrics row → Filter Reference (collapsed by default) → Discovery Map → Retention Detail → Binary & Categorical Breakdown.
- **Coloring:** green → red gradient keyed to `delta_pp` (filter avg ROM minus baseline). Scale anchored at 80r% deltas so the sort and color stay consistent across views.
- **Sort order (Discovery Map):** columns sorted left-to-right by 80r% delta descending — best-lift filters appear first.
- **Minimum trade floor:** a filter threshold is recorded only when survivors ≥ `MIN_TRADES` (10) AND ≥ `MIN_TRADE_PCT%` (10%) of total trades. This matches the Retention Detail tooltip convention.
- **Null-column skip:** any filter column with > 10% nulls is skipped with a message to stdout. Reported in the final-line summary.
- **Title matches filename convention:** browser tab + `<h1>` both read "Entry Filter Heatmap" (Title Case); file on disk is lowercase with spaces (`entry filter heatmap.html`) for tidy sorting.

## Process (for Claude when invoked)

1. **Confirm the target block.** If not already known, call `list_blocks` or ask.
2. **Invoke the driver:**
   ```bash
   python3 "{skill_dir}/gen_heatmap.py" "<BLOCK>"
   ```
3. **Handle non-zero exit codes per the table above.**
4. **On exit 0:** surface the output path to the user and offer to `open` it.

## Related skills

- `alex-entry-filter-build-data` — upstream. Creates the two CSVs this skill reads.
- `alex-entry-filter-threshold-analysis` — single-filter deep dive (Chart.js interactive). Use when the heatmap surfaces an interesting filter and you want to drill in.
- `alex-create-datelist` — generate OO datelists once a filter decision is made.

## What NOT to do

- Don't auto-build missing data. If either CSV is missing, surface the error and offer `/alex-entry-filter-build-data`.
- Don't read from `_shared/` at runtime. This skill is strictly block-local.
- Don't hardcode the filter set. All filter inclusion goes through `--heatmap-col` (default `Report Heatmap`) on the block-local groups CSV.
- Don't write block-specific wrapper scripts. The CLI is the single entry point.
- Don't display long `Filter` names in the heatmap grid — they crowd the layout. Short Name is primary; full Filter name lives in tooltips and the Filter Reference section.
