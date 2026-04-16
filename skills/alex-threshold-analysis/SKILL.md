---
name: alex-threshold-analysis
description: >
  Generic threshold analysis for any trade or market field with interactive chart. Sweeps a parameter
  continuously across both >= and <= directions, generates retention references at standard levels,
  an efficiency frontier chart, and OO filter translation. Examples: /dev-threshold-analysis SLR, VIX O/N, premium.
compatibility: Requires TradeBlocks MCP server with trade data loaded.
metadata:
  author: alex-tradeblocks
  version: "3.0.1"
---

# Threshold Analysis

Sweep any numeric field across all unique values to analyze entry filter potential. Produces an interactive HTML with:
1. **Threshold chart** -- both-direction Avg ROM curves + CDF lines
2. **Retention reference table** -- >= / <= / combo sections at 99/95/90/80/70/60/50r% with OO filter translation
3. **Efficiency frontier** -- Avg ROM vs % ROR retained for all three filter approaches
4. **Scatter plot** -- individual trade ROM vs field value with best-fit line

No single recommendation is made. The chart presents retention references at standard levels and lets the user decide the tradeoff.

## Architecture

The chart logic lives in a **shared Python module** that any block can import:

```
gen_threshold_analysis.py    # shared generator (720+ lines)
```

Block-specific scripts are **thin wrappers** that pass a config dict. No chart code is duplicated.

## File Dependencies (3 files)

The skill needs exactly 3 files. No SQL queries, no MCP calls for data at runtime.

### 1. entry_filter_data.csv (trade data)

Location: `{block_folder}/alex-tradeblocks-ref/entry_filter_data.csv`

One row per trade. Required columns: `rom_pct`, `pl_per_contract`, plus the target field column. Shared with Pareto and Heatmap skills -- building any of those first creates this cache. If missing, build via the shared Phase 1 pipeline (see Pareto skill for SQL).

### 2. entry_filter_groups.csv (field metadata)

Resolution order:
1. `_shared/entry_filter_groups.csv` (user-customized)
2. `_shared/entry_filter_groups.default.csv` (default)

Provides `Filter`, `Short Name`, `Group`, `Direction`, and `Type` per field. Used for field lookup and display names.

### 3. Shared generator module

Location: `gen_threshold_analysis.py` (skill-local)

Called by block-specific wrapper scripts. Contains all chart logic, HTML template, percentile computation, and Chart.js rendering.

## Supported Fields

Map user input to CSV column:

| User Input | CSV Column | Notes |
|---|---|---|
| `SLR`, `slr` | `SLR` | Short-to-long premium ratio |
| `VIX`, `vix` | `VIX_Close` | Prior day VIX close |
| `VIX open` | `VIX_Open` | Same-day VIX open |
| `VIX O/N`, `vix gap` | `VIX_Gap_Pct` | Overnight VIX move (%) -- continuous, positive = up |
| `VIX spike` | `VIX_Spike_Pct` | Prior day VIX spike |
| `RSI`, `rsi` | `RSI_14` | Prior day SPX RSI-14 |
| `RV5`, `realized vol` | `Realized_Vol_5D` | 5-day realized volatility |
| `RV20` | `Realized_Vol_20D` | 20-day realized volatility |
| `ATR`, `atr%` | `ATR_Pct` | ATR as % of price |
| `VIX IVR`, `ivr` | `VIX_IVR` | IV Rank |
| `VIX IVP`, `ivp` | `VIX_IVP` | IV Percentile |
| `gap%` | `Gap_Pct` | Same-day SPX gap % |
| `prev return` | `Prev_Return_Pct` | Prior day return |
| `EMA21`, `price vs ema` | `Price_vs_EMA21_Pct` | Price vs EMA21 |
| `SMA50`, `price vs sma` | `Price_vs_SMA50_Pct` | Price vs SMA50 |
| `return 5d` | `Return_5D` | 5-day return |
| `VIX9D ratio` | `VIX9D_VIX_Ratio` | VIX9D/VIX open ratio |
| `premium` | `premium_per_contract` | Net credit per contract |
| `margin` | `margin_per_contract` | Margin per contract |
| `credit` | `premium_per_contract` | Alias for premium |

If user input doesn't match, list available fields and ask.

## Process

### Step 1: Parse Argument and Load Data

1. Parse field argument (e.g., `/alex-threshold-analysis VIX O/N` -> field = `VIX_Gap_Pct`).
2. Determine block from context or ask.
3. Check for `{block_folder}/alex-tradeblocks-ref/entry_filter_data.csv`.
   - **If exists:** Read directly. Report "Using cached filter data ({n} trades)."
   - **If missing:** Build via shared Phase 1 pipeline (see Pareto skill), then read.
4. Extract arrays: `field_val[]`, `rom_pct[]`, `pl_per_contract[]`. Drop rows where field is null/empty.

### Step 2: Compute Baseline and Correlation

From the loaded arrays:

- **Baseline Avg ROM:** `mean(rom_pct)`
- **Baseline Net ROR:** `sum(rom_pct)`
- **Win Rate:** `count(rom_pct > 0) / total * 100`
- **Profit Factor:** `sum(positive roms) / abs(sum(negative roms))`
- **Avg 1-Lot P/L:** `mean(pl_per_contract)`
- **Correlation:** Pearson `r` between field_val and rom_pct
- **Best fit:** least-squares `y = mx + b`, R^2

**CRITICAL: ROM is already per-trade in the CSV.** Just average the `rom_pct` values within each group. Never re-derive from aggregate P/L.

### Step 3: Generate Block Wrapper and Run

Create a thin wrapper script at `{block_folder}/gen_{field_slug}_threshold.py` that imports the shared module:

```python
#!/usr/bin/env python3
"""Threshold analysis for {FIELD_LABEL} in {BLOCK_NAME}."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '_shared'))
from gen_threshold_analysis import generate

generate({
    'block_folder': os.path.dirname(os.path.abspath(__file__)),
    'block_name':   '{BLOCK_NAME}',
    'field_col':    '{FIELD_COL}',
    'field_label':  '{FIELD_LABEL}',
    'field_slug':   '{field_slug}',
    'oo_translate':  '{oo_type}',     # 'simple' | 'vix_on'
    'show_zero_x':   {show_zero},     # True for fields spanning +/-
    'subtitle_note': '{note}',
})
```

Then run:
```bash
cd "{block_folder}"
python3 gen_{field_slug}_threshold.py
```

Output: `{block_folder}/entry_filter_threshold_{field_slug}.html`

### Config Reference

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `block_folder` | str | yes | Absolute path to block directory |
| `block_name` | str | yes | Display name for subtitle |
| `field_col` | str | yes | CSV column name |
| `field_label` | str | yes | Full display label (e.g., "VIX O/N Move (%)") |
| `field_slug` | str | yes | Filename slug (e.g., "vix_on", "slr") |
| `oo_translate` | str | no | OO translation mode: `'simple'` (default) or `'vix_on'` |
| `show_zero_x` | bool | no | Show vertical 0-line for fields spanning +/-. Default `False` |
| `subtitle_note` | str | no | Custom subtitle suffix. Default auto-generated |

#### OO Translation Modes

- **`simple`**: `Min {Field} = X` / `Max {Field} = X`. Use for SLR, VIX, RSI, premium, etc.
- **`vix_on`**: Splits by sign: `Min O/N Move Up = X` / `Max O/N Move Down = X`. Use for VIX O/N only.

### Step 4: Client-Side Threshold Computation (JavaScript in HTML)

All threshold metrics are computed client-side at every unique field value for full resolution. The raw data is embedded as JSON.

#### 4a. Threshold Data

For each unique value `t` in the field (minimum 1 trade on each side):

```
gtRows = trades where field_val >= t
ltRows = trades where field_val <= t
```

Compute for each direction:
- `gtRom` / `ltRom`: avg ROM of the group
- `gtNet` / `ltNet`: sum ROM of the group
- `gtN` / `ltN`: trade count
- `gtWr` / `ltWr`: win rate
- `gtPf` / `ltPf`: profit factor (capped at 99)
- `gtRetained` / `ltRetained`: `groupNet / baselineNet * 100` (% of baseline Net ROR retained)

CDF lines (always 0% -> 100% left to right):
- `pctTrades`: `count(field_val < t) / N * 100`
- `pctNetRor`: `sum(rom where field_val < t) / baselineNet * 100`

Trades at exactly `t` appear in BOTH >= and <= groups (intentional -- boundary trades are the marginal case).

#### 4b. Retention References

Standard levels: `[99, 95, 90, 80, 70, 60, 50]` r%

**>= direction:** For each target, find the **highest** threshold where `gtRetained >= target` and `gtN >= 10`. Fallback: if no threshold qualifies, use min value (= all trades = baseline).

**<= direction:** For each target, find the **lowest** threshold where `ltRetained >= target` and `ltN >= 10`. Fallback: if no threshold qualifies, use max value (= all trades = baseline).

**Combo [min, max]:** O(N^2) search over all `[lo, hi]` pairs from threshData. For each retention target, find the range that maximizes Avg ROM while `retained >= target` and `n >= 10`. Fallback: full range (= baseline).

Every retention level always has a row -- fallback ensures no gaps.

#### 4c. Non-Monotonic Detection

When you tighten a filter, you expect to steadily lose ROR. A **non-monotonic** result means the ROR dipped below the target on the path from baseline to this threshold, then bounced back -- typically because a large losing trade got excluded, canceling out a large winner that was also excluded. The threshold only hits the retention target due to coincidental cancellation, not systematic edge.

**Detection:**
- **>= refs:** Flag if any threshold `t' < ref.t` (wider filter) has `gtRetained < target`
- **<= refs:** Flag if any threshold `t' > ref.t` (wider filter) has `ltRetained < target`
- **Combo refs:** Flag if any wider range `[lo', hi']` (where `lo' <= ref.lo` and `hi' >= ref.hi`, not identical) has `retained < target`

Display: warning icon with hover tooltip explaining the issue. Always show the value -- just flag it.

**ELI5 footnote** below the table (orange): "As you tighten a filter, you expect to steadily lose ROR. A non-monotonic result means the ROR dipped below the target on the way to this threshold, then bounced back because a big loser got excluded. The reported threshold only hits the retention target because large winning and losing trades above/below it happen to cancel out -- not because of a systematic edge. Treat with caution."

### Step 5: HTML Chart Specification

Dark theme (#1a1a2e background), Chart.js 4.x + annotation plugin from CDN.

**Layout order (top to bottom):**

1. **Title + subtitle** (block name, trade count, baseline ROM, correlation, sweep description)
2. **Metrics cards** (Total Trades, Baseline Avg ROM, Baseline Net ROR, Win Rate, Profit Factor, Correlation)
3. **Threshold chart** (tall, 500px)
4. **Retention References table**
5. **Method note + non-monotonic ELI5**
6. **Efficiency Frontier chart** (tall, 500px)
7. **Scatter plot** (shorter, 350px)

#### Threshold Chart

- **Type:** Scatter with `showLine: true`
- **Datasets:**
  - Orange (#e67e22): `>= threshold (Avg ROM %)` -- yAxisID: `yRom`
  - Purple (#9b59b6): `<= threshold (Avg ROM %)` -- yAxisID: `yRom`
  - Blue (0.6 opacity, dashed): `% Trades (CDF)` -- yAxisID: `yPct`, pointRadius: 0
  - Green (0.5 opacity, dashed): `% Net ROR (CDF)` -- yAxisID: `yPct`, pointRadius: 0
- **Left Y-axis** (`yRom`): "Avg ROM (%)" -- auto-scaled with padding
- **Right Y-axis** (`yPct`): "% of Total" -- range -5 to 110
- **X-axis:** Field label, linear scale
- **Annotations:**
  - Baseline ROM horizontal dashed line with label
  - 0% ROM horizontal line (white, 0.15 opacity)
  - 0 x-axis vertical dashed line (for fields spanning positive/negative, controlled by `show_zero_x`)
  - >= retention reference lines: **dashed [6,3]**, colored by retention level, span from **baseline ROM up to chart top**
  - <= retention reference lines: **dotted [2,2]**, colored by retention level, span from **chart bottom up to baseline ROM**
  - Thin data boxes: shaded regions where `< 30 trades` in either direction, with label

#### Retention References Table

- **Columns:** Threshold | ROR Retention | Avg ROM % | ROM Delta | Trades | % Trades | Win Rate | PF | Avg 1-Lot P/L | OO Filter
- **Sections:**
  1. **Baseline** row (blue BASE tag)
  2. **>= direction** (orange header) -- dashed reference lines
  3. **<= direction** (purple header) -- dotted reference lines
  4. **Combo** (teal header) -- best [min, max] range
- **Rows per section:** 99r%, 95r%, 90r%, 80r%, 70r%, 60r%, 50r% -- all always present (fallback to baseline)
- **Styling:** Retention level color tags, green/red delta coloring, warning non-monotonic flags with hover tooltip

#### Efficiency Frontier Chart

- **Type:** Scatter with `showLine: true`
- **X-axis:** "% Total ROR Retained" -- **reversed** (100% on left), range 0-105
- **Y-axis:** "Avg ROM (%)" -- auto-scaled
- **Datasets:**
  - Orange: `>= (Min threshold)` -- pointRadius 2
  - Purple: `<= (Max threshold)` -- pointRadius 2
  - Teal (#1abc9c): `Combo [min, max]` -- de-duplicated to distinct (x,y) points, pointRadius 4

#### Scatter Plot

- **Height:** 350px (shorter than other charts)
- **Dots:** Blue for winners, red for losers, radius 4.5
- **Best-fit line:** Orange, dashed, with equation + R^2 annotation
- **Annotations:** Retention reference lines (lighter opacity)

### Step 6: Run and Open

1. Execute: `python3 gen_{field_slug}_threshold.py`
2. Open: `open entry_filter_threshold_{field_slug}.html`
3. Report: baseline stats, correlation, and that the chart is open

No markdown summary table or recommendation. The HTML is the deliverable.

## What NOT to Do

- **Don't duplicate chart code.** Always import from `gen_threshold_analysis.py` (skill-local). Block scripts are thin wrappers only.
- **Don't estimate ROM from aggregate P/L.** `rom_pct` is already per-trade in the CSV. Just average it.
- **Don't make a single recommendation.** Present retention references and let the user decide.
- **Don't use SQL at runtime.** Everything comes from the CSV. The only SQL would be building the CSV if it doesn't exist.
- **Don't skip retention levels.** Always report all 7 levels per section. Fallback to baseline if nothing qualifies.
- **Don't hide non-monotonic results.** Show the value, flag it with warning icon.
- **Don't use `< 5` trade cutoff for threshData.** Use `< 1` so lines extend to the full data range. Thin data boxes visually warn about sparse zones.
- **Don't use same-day close-derived fields without lagging** -- that's lookahead bias. Lags are baked into the CSV.
- **Don't open DuckDB connections from the script.** The script only reads CSV.

## Files

| File | Location | Purpose |
|------|----------|---------|
| `gen_threshold_analysis.py` | skill-local | Shared chart generator module |
| `gen_{slug}_threshold.py` | `{block_folder}/` | Block-specific thin wrapper |
| `entry_filter_data.csv` | `{block_folder}/alex-tradeblocks-ref/` | Trade data input |
| `entry_filter_threshold_{slug}.html` | `{block_folder}/` | Output chart |
| `entry_filter_groups.default.csv` | skill-local | Field metadata |

## Related Skills

- `alex-entry-filter-pareto` -- Pareto chart of all filters (shares entry_filter_data.csv)
- `alex-entry-filter-heatmap` -- Retention heatmap with discovery map (shares entry_filter_data.csv + groups CSV)
- `alex-entry-filter-parallel-coords` -- Parallel coordinate plot (shares entry_filter_data.csv)

## Notes

- Chart HTML uses Chart.js 4.x + annotation plugin from CDN. No other dependencies.
- The entry_filter_data.csv is shared across all dev-entry-filter-* skills. Building any skill first creates the cache for all.
- When reading from CSV, all lag rules and per-contract normalizations are already applied.
- For fields spanning positive and negative (VIX O/N, Gap %, returns), set `show_zero_x: True`.
- The OO translation function is field-specific. VIX O/N uses `'vix_on'` mode. All others use `'simple'`.
- Combo O(N^2) search can be slow for very large threshData arrays. The `>= 10 trades` filter on survivors keeps it manageable for typical blocks (50-300 trades).
- The shared module requires `numpy` for correlation and polyfit. All other computation is in client-side JS.
