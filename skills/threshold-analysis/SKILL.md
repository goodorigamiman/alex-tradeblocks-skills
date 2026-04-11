---
name: threshold-analysis
description: >
  Generic threshold analysis for any trade or market field with interactive chart. Sweeps a parameter
  (SLR, VIX, premium, gap, duration, etc.) to find optimal entry/exit filter using correct per-trade
  ROR methodology. Invoke as: /threshold-analysis [field]. Examples: /threshold-analysis SLR,
  /threshold-analysis VIX, /threshold-analysis premium, /threshold-analysis gap.
compatibility: Requires TradeBlocks MCP server with trade data loaded.
metadata:
  author: alex-tradeblocks
  version: "1.0"
---

# Threshold Analysis

Sweep any numeric field across thresholds to find optimal entry filters, normalized to Return on Risk (ROM). Produces an interactive HTML chart and a Current vs Recommended comparison table.

## Supported Fields

The skill accepts a field argument. Map the user's input to the correct data source:

### Trade-Level Fields (from `trades.trade_data` or computed from legs)

| User Input | Internal Field | Source | Notes |
|------------|---------------|--------|-------|
| `SLR`, `slr`, `short long ratio` | `openingShortLongRatio` | Derived from legs | `sum(STO prices) / sum(BTO prices)` — requires 4-leg STO/BTO structure |
| `premium` | `premium` | `trades.trade_data.premium` | Net premium collected (negative = debit) |
| `duration`, `hours` | `durationHours` | Computed | `(date_closed - date_opened)` in hours |
| `gap` | `gap` | `trades.trade_data` via `get_field_statistics` | SPX gap on trade open day |
| `movement` | `movement` | `trades.trade_data` via `get_field_statistics` | Underlying movement during trade |
| `contracts` | `num_contracts` | `trades.trade_data.num_contracts` | Position size |
| `margin` | `margin_req` | `trades.trade_data.margin_req` | Margin per trade |

### Market Context Fields (from `market.daily` or `market._context_derived`, joined by trade date)

| User Input | Internal Field | Source Table | Join Column | Lag Required |
|------------|---------------|-------------|-------------|--------------|
| `VIX`, `vix` | `close` | `market.daily` WHERE ticker='VIX' | `date = date_opened` | No (same-day open known) |
| `VIX open` | `open` | `market.daily` WHERE ticker='VIX' | `date = date_opened` | No |
| `RSI`, `rsi` | `RSI_14` | `market.daily` WHERE ticker='SPX' | `date = date_opened` | Yes (prior day) |
| `RV5`, `realized vol` | `Realized_Vol_5D` | `market.daily` WHERE ticker='SPX' | `date = date_opened` | Yes (prior day) |
| `RV20` | `Realized_Vol_20D` | `market.daily` WHERE ticker='SPX' | `date = date_opened` | Yes (prior day) |
| `ATR` | `ATR_Pct` | `market.daily` WHERE ticker='SPX' | `date = date_opened` | Yes (prior day) |
| `VIX IVR`, `ivr` | `ivr` | `market.daily` WHERE ticker='VIX' | `date = date_opened` | Yes (prior day) |
| `VIX IVP`, `ivp` | `ivp` | `market.daily` WHERE ticker='VIX' | `date = date_opened` | Yes (prior day) |
| `gap pct`, `gap%` | `Gap_Pct` | `market.daily` WHERE ticker='SPX' | `date = date_opened` | No (same-day) |
| `EMA21`, `price vs ema` | `Price_vs_EMA21_Pct` | `market.daily` WHERE ticker='SPX' | `date = date_opened` | Yes (prior day) |
| `SMA50`, `price vs sma` | `Price_vs_SMA50_Pct` | `market.daily` WHERE ticker='SPX' | `date = date_opened` | Yes (prior day) |

**Lag rules:** Close-derived fields (RSI, RV, ATR, IVR, IVP, EMA, SMA) use the **prior trading day** value to prevent lookahead bias. Open-known fields (VIX open, Gap_Pct) use same-day values.

If the user's input doesn't match any known field, ask: "Which field do you mean? Here are the available options: [list from tables above]."

## Prerequisites

- TradeBlocks MCP server running
- At least one block with trade data loaded
- For market context fields: market data must be imported (check with `run_sql` — if no rows match, suggest `/tradeblocks:market-data`)
- Strategy profile recommended (for current filter settings)

## Process

### Step 1: Parse Argument and Select Target

1. **Parse the field argument** from the user's invocation (e.g., `/threshold-analysis VIX` -> field = VIX close).
2. Use `list_blocks` to show available blocks if not already established.
3. Ask which block and optionally which strategy to analyze.
4. If a profile exists, load it with `get_strategy_profile` to find the **current threshold** for this field (search `entryFilters` for a matching field name). If no current setting exists, note "No current filter" — the chart will omit the "Current" reference line.

### Step 2: Check Data Sufficiency

Run ALL checks before proceeding. The checks depend on the field source.

**Universal checks:**

```sql
-- Check 1: Trade count
SELECT COUNT(*)::INT as trades FROM trades.trade_data WHERE block_id = '{blockId}'
```
**Minimum: 50 trades.** Report and stop if insufficient.

```sql
-- Check 2: Margin data (required for ROM)
SELECT COUNT(CASE WHEN margin_req > 0 THEN 1 END)::INT as has_margin,
       COUNT(*)::INT as total
FROM trades.trade_data WHERE block_id = '{blockId}'
```
**All trades must have margin > 0.** Report and stop if missing.

**Field-specific checks:**

**For trade-level fields** (premium, duration, gap, movement, contracts, margin):
```sql
-- Check 3a: Field has values and sufficient spread
SELECT COUNT(*)::INT as non_null,
       ROUND(MIN({field}), 4) as min_val,
       ROUND(MAX({field}), 4) as max_val,
       ROUND(STDDEV({field}), 4) as stddev
FROM trades.trade_data WHERE block_id = '{blockId}' AND {field} IS NOT NULL
```
Use `get_field_statistics` for the field to get distribution. **Minimum: 90% non-null, stddev > 0.**

**For SLR (derived from legs):**
```sql
-- Check 3b: Legs are parseable
SELECT COUNT(*)::INT as total,
       COUNT(CASE WHEN legs LIKE '%STO%' AND legs LIKE '%BTO%' THEN 1 END)::INT as parseable
FROM trades.trade_data WHERE block_id = '{blockId}'
```
**All trades must be parseable.** Also check SLR spread >= 0.10.

**For market context fields:**
```sql
-- Check 3c: Market data exists for trade dates
SELECT COUNT(*)::INT as trades_with_data
FROM trades.trade_data t
JOIN market.daily m ON m.ticker = '{ticker}' AND CAST(m.date AS DATE) = CAST(t.date_opened AS DATE)
WHERE t.block_id = '{blockId}'
```
**Minimum: 90% of trades must have matching market data.** If < 90%, report: "Only {n}% of trades have {field} data. Run `/tradeblocks:market-data` to import missing data."

**Pre-screen correlation:**

Run `find_predictive_fields` with `targetField: "rom"` and check if the field appears with |correlation| >= 0.05. If correlation < 0.05, warn: "Correlation between {field} and ROM is only {r} — threshold analysis may not produce useful differentiation. Proceed anyway?"

If any check fails, **stop and report** the specific issue. Do not proceed.

### Step 3: Build the Analysis Query

Construct the SQL to compute per-trade ROM at each threshold. The query structure depends on the field source.

**CRITICAL: ROM must be computed per-trade FIRST, then averaged.** `rom_pct = pl / margin_req * 100` for each trade. Then `AVG(rom_pct)` within each threshold group.

**Determine filter direction:**
- Most fields use `>=` (higher = filter IN): SLR, premium, VIX IVR, duration
- Some fields use `<=` (lower = filter IN): VIX level, RSI, gap (for negative gaps)
- When ambiguous, check the correlation sign from `find_predictive_fields`. Positive correlation = `>=` filter. Negative correlation = `<=` filter.
- Present both directions in the chart (gt and lt dots) regardless — let the data show which side is better.

**For trade-level fields** (direct column):
```sql
WITH base AS (
  SELECT
    pl, margin_req, num_contracts,
    pl / NULLIF(margin_req, 0) * 100 as rom_pct,
    pl / num_contracts as pl_per_lot,
    pl > 0 as is_win,
    {field_expression} as field_val
  FROM trades.trade_data
  WHERE block_id = '{blockId}'
)
SELECT
  ROUND(AVG(CASE WHEN field_val >= {t} THEN rom_pct END), 2) as gt_rom,
  ROUND(AVG(CASE WHEN field_val < {t} THEN rom_pct END), 2) as lt_rom,
  ROUND(SUM(CASE WHEN field_val >= {t} THEN rom_pct END), 2) as gt_net_ror,
  ROUND(SUM(CASE WHEN field_val < {t} THEN rom_pct END), 2) as lt_net_ror,
  ROUND(SUM(CASE WHEN field_val >= {t} AND rom_pct > 0 THEN rom_pct ELSE 0 END) /
    NULLIF(ABS(SUM(CASE WHEN field_val >= {t} AND rom_pct < 0 THEN rom_pct ELSE 0 END)), 0), 2) as gt_pf,
  ROUND(SUM(CASE WHEN field_val < {t} AND rom_pct > 0 THEN rom_pct ELSE 0 END) /
    NULLIF(ABS(SUM(CASE WHEN field_val < {t} AND rom_pct < 0 THEN rom_pct ELSE 0 END)), 0), 2) as lt_pf,
  ROUND(AVG(CASE WHEN field_val >= {t} THEN pl_per_lot END), 2) as gt_pl_lot,
  COUNT(CASE WHEN field_val >= {t} THEN 1 END)::INT as gt_count,
  COUNT(CASE WHEN field_val < {t} THEN 1 END)::INT as lt_count,
  ...
FROM base
```

**For SLR (derived):**
Use the regex pattern from the SLR skill:
```sql
(CAST(regexp_extract(legs, 'P STO ([0-9.]+)', 1) AS DOUBLE) +
 CAST(regexp_extract(legs, 'C STO ([0-9.]+)', 1) AS DOUBLE)) / NULLIF(
 CAST(regexp_extract(legs, 'P BTO ([0-9.]+)', 1) AS DOUBLE) +
 CAST(regexp_extract(legs, 'C BTO ([0-9.]+)', 1) AS DOUBLE), 0) as field_val
```

**For market context fields (joined):**
```sql
WITH base AS (
  SELECT
    t.pl, t.margin_req, t.num_contracts,
    t.pl / NULLIF(t.margin_req, 0) * 100 as rom_pct,
    t.pl / t.num_contracts as pl_per_lot,
    t.pl > 0 as is_win,
    m.{column} as field_val
  FROM trades.trade_data t
  JOIN market.daily m
    ON m.ticker = '{ticker}'
    AND CAST(m.date AS DATE) = {join_expression}
  WHERE t.block_id = '{blockId}'
)
```

Where `{join_expression}` is:
- Same-day: `CAST(t.date_opened AS DATE)`
- Prior-day (lagged): `(SELECT MAX(CAST(m2.date AS DATE)) FROM market.daily m2 WHERE m2.ticker = '{ticker}' AND CAST(m2.date AS DATE) < CAST(t.date_opened AS DATE))`

**Generate thresholds:** Use `get_field_statistics` percentiles (p5, p10, p25, p50, p75, p90, p95) as anchor points, then fill in at regular intervals to get ~30-40 threshold points across the range.

Run the threshold sweep in a single SQL query with conditional aggregation for all thresholds.

**Also collect baseline metrics** (all trades, no filter):
```sql
SELECT
  ROUND(AVG(rom_pct), 2) as baseline_rom,
  ROUND(SUM(rom_pct), 2) as baseline_net_ror,
  ROUND(SUM(CASE WHEN rom_pct > 0 THEN rom_pct ELSE 0 END) /
    NULLIF(ABS(SUM(CASE WHEN rom_pct < 0 THEN rom_pct ELSE 0 END)), 0), 2) as baseline_pf,
  ROUND(AVG(pl_per_lot), 2) as baseline_pl_lot,
  ROUND(SUM(CASE WHEN is_win THEN 1 ELSE 0 END)::FLOAT / COUNT(*) * 100, 1) as baseline_wr,
  COUNT(*)::INT as total_trades
FROM base
```

**Metric definitions:**
- **Avg ROR %**: Average of individual trade ROM values in the group
- **Net ROR %**: Simple sum of all individual trade ROM values in the group — shows total cumulative return on risk
- **Profit Factor**: `SUM(positive ROMs) / ABS(SUM(negative ROMs))` — computed on ROM basis, not raw P/L

### Step 4: Identify Zones and Recommendation

Same logic as the SLR skill but field-agnostic:

| Zone | Criteria | Interpretation |
|------|----------|----------------|
| **No benefit** | ROM within 1pp of baseline AND gradient flat | Filtering here doesn't help |
| **Sweet spot** | ROM rising smoothly, trades >= 25% of total, smooth gradient | Robust zone |
| **High selectivity** | ROM high but trades < 25% of total | Too few trades to be reliable |
| **Overfitting** | < 30 trades in the filtered group | Not actionable |

**Recommendation logic:**
1. Find the threshold where ROM is >= 2pp above baseline (in the favorable direction)
2. Verify smooth gradient at +/- one step
3. Verify >= 30 trades in the filtered group
4. If no threshold qualifies, report: "No clear {field} filter improvement found."

### Step 5: Generate Interactive Chart

Save HTML to: `{block_folder}/{field_slug}_threshold_analysis.html`

Where `field_slug` is the field name in snake_case (e.g., `vix_close`, `opening_slr`, `premium`).

**Chart specification** (same as SLR skill but with dynamic labels):

- **Title:** `{Field Name} Threshold Analysis`
- **Subtitle:** `{block_name} | {n} trades | Metric: Avg ROM (%) | Baseline ROM: {baseline}%`
- **X-axis title:** `{Field Display Name}` (e.g., "VIX Close", "Opening S/L Ratio", "Premium ($)")
- **X-axis range:** min to max of field data with 5% padding
- **Left Y-axis:** "% Included in Analysis" (-10 to 110)
- **Right Y-axis:** "Avg ROM (%)" — range auto-scaled to data with padding
- **Scatter dots:**
  - Orange (#e67e22): Avg ROM for trades on the **favorable side** of threshold (label: "High {Field}" or "Low {Field}" based on correlation direction)
  - Purple (#9b59b6): Avg ROM for trades on the **unfavorable side**
- **Lines:** % Trades Included and % P/L Included, building left to right (0% to 100%)
- **Annotations:**
  - 0% ROM horizontal line (solid white, 0.3 opacity)
  - Baseline ROM horizontal dashed line with label
  - Current filter value vertical dashed line (red) — from profile, if exists
  - Recommended threshold vertical dashed line (green) — if one was found
  - Thin Data box where trades < 30
- **Comparison table** below chart:
  - Columns: {Field} Filter, Avg ROR %, Net ROR %, Profit Factor, Avg 1-Lot P/L, Win Rate, Trades Retained
  - Net ROR % = simple sum of individual trade ROM values in the filtered group
  - Profit Factor = SUM(positive ROMs) / ABS(SUM(negative ROMs)) — computed on ROM basis, not raw P/L
  - Rows: Current (red tag), Recommended (green tag), Delta
  - Method note: "ROM = per-trade P/L / margin, then averaged across trades."

### Step 6: Present Results

Display chart location and markdown summary:

**Tradeoff table:**

| {Field} Threshold | Trades | % Kept | Win Rate | WR Delta | Avg ROM | ROM Delta | Net ROR | Profit Factor | Gradient |
|-------------------|--------|--------|----------|----------|---------|-----------|---------|---------------|----------|
| Baseline (all) | {n} | 100% | {wr}% | — | {rom}% | — | {net}% | {pf} | — |
| {t1} | | | | | | | | | Smooth |
| **{recommended}** | | | | | | | | | |
| {t2} | | | | | | | | | |

**Key findings:**
- Correlation direction and strength
- Where the favorable/unfavorable ROM dots diverge
- Whether gradient is smooth or cliff
- Tradeoff: ROM gained vs trades lost

### Step 7: Optional — Generate Blackout Dates

If the user wants dates to exclude in OO:

```sql
SELECT strftime(CAST(date_opened AS DATE), '%Y-%m-%d') as trade_date
FROM {base_query}
WHERE field_val {unfavorable_operator} {recommended_threshold}
ORDER BY trade_date
```

Output as comma-separated ISO dates.

## Examples

### `/threshold-analysis SLR`
- Field: Opening S/L Ratio (derived from legs)
- X-axis: "Opening S/L Ratio" (0.30 – 0.80 typical)
- Direction: higher = better (positive correlation with ROM)
- Current: from profile `min_short_long_ratio`

### `/threshold-analysis VIX`
- Field: VIX close (from market.daily)
- X-axis: "VIX Close" (10 – 40 typical)
- Direction: check correlation — often negative (lower VIX = better for short-DTE DCs)
- Current: from profile `VIX_Close` entry filter if exists

### `/threshold-analysis premium`
- Field: Net premium collected
- X-axis: "Premium ($)" (negative values = debit strategies)
- Direction: check correlation — varies by structure
- Note: Premium is negative in the trade data (debit). Display as absolute value or clarify sign convention.

### `/threshold-analysis gap`
- Field: SPX gap on trade open day
- X-axis: "Gap (points)"
- Direction: typically negative correlation (down gaps = better for DCs)
- Source: `gap` column in trade data, or `Gap_Pct` from market.daily

## Related Skills


- `/tradeblocks:dc-analysis` — Uses threshold analysis as part of its workflow
- `/tradeblocks:optimize` — Broader parameter exploration
- `/tradeblocks:health-check` — Overall strategy health
- `/tradeblocks:market-data` — Import market data if context fields are missing

## What NOT to Do

- **Don't estimate ROM from average raw P&L.** Always compute `pl/margin_req` per trade first, then average. This is the single most important rule.
- Don't recommend thresholds with fewer than 30 trades in the filtered group
- Don't recommend where adjacent thresholds show a cliff (curve fitting)
- Don't ignore that cut trades may be profitable — always show the tradeoff
- Don't forget to check correlation direction before labeling "high" vs "low" as favorable
- Don't use same-day close-derived fields without lagging — that's lookahead bias
- Don't proceed without data sufficiency checks — missing market data silently drops trades from the analysis

## Notes

- The chart HTML uses Chart.js 4.x + annotation plugin from CDN
- For market context fields, the underlying ticker defaults to SPX. If the block trades a different underlying, adjust the join accordingly.
- Fields with bimodal distributions (e.g., gap: clustered around 0 with tails) may need non-uniform threshold spacing. Use percentile-based thresholds instead of linear intervals.
- This skill supersedes `/slr-threshold-analysis` for SLR analysis. The SLR skill remains available for backwards compatibility.
