---
name: alex-entry-filter-pareto
description: >
  Entry filter Pareto chart comparing all candidate filters side-by-side. Shows Avg ROR vs % of
  baseline Net ROR retained for each filter at its recommended threshold. Use when comparing
  multiple entry filter candidates to find the best risk-adjusted tradeoff.
compatibility: Requires TradeBlocks MCP server with trade data and market data loaded.
metadata:
  author: alex-tradeblocks
  version: "1.0"
---

# Entry Filter Pareto

Compare all candidate entry filters side-by-side in a single Pareto chart. For each filter, sweep thresholds to find the best candidate level, then plot Avg ROR (per-trade quality) vs % of Baseline Net ROR retained (cumulative productivity). Surfaces the core tradeoff: per-trade selectivity vs total return.

## Default Filter Set

The standard set of filters to evaluate. The user may add, remove, or substitute filters.

| Filter | Source | Field | Direction | Lag | Typical Range |
|--------|--------|-------|-----------|-----|---------------|
| SLR | Trade legs (derived) | `sum(STO prices) / sum(BTO prices)` | `>=` (higher = better) | N/A | 0.30 – 0.80 |
| VIX Close | `market.daily` WHERE ticker='VIX' | `close` | `<` (lower = better) | Same-day | 12 – 45 |
| RSI (14) | `market.daily` WHERE ticker='SPX' | `RSI_14` | `<` (lower = better) | Prior day | 25 – 80 |
| VIX IVP | `market.daily` WHERE ticker='VIX' | `ivp` | `<` (lower = better) | Prior day | 0 – 100 |
| RV5 | `market.daily` WHERE ticker='SPX' | `Realized_Vol_5D` | Check corr sign | Prior day | 3 – 40 |
| ATR % | `market.daily` WHERE ticker='SPX' | `ATR_Pct` | Check corr sign | Prior day | 0.7 – 3.0 |
| Price vs EMA21 | `market.daily` WHERE ticker='SPX' | `Price_vs_EMA21_Pct` | `<` (below EMA = better) | Prior day | -8 – 5 |
| 1-Lot Premium | `trades.trade_data` | `premium / num_contracts` | Check corr sign | N/A | -350 – 0 |

**Lag rules:** Close-derived market fields (RSI, RV, ATR, IVP, EMA) use the **prior trading day** value to prevent lookahead bias. Same-day open-known fields (VIX close) use trade-date values. Trade-level fields (SLR, premium) have no lag concern.

## Prerequisites

- TradeBlocks MCP server running
- At least one block with trade data loaded (50+ trades minimum)
- Market data imported for all market context fields (check with SQL join counts)
- All trades must have `margin_req > 0` (required for ROM calculation)

## Process

### Step 1: Select Target Block

1. Use `list_blocks` to show available blocks if not already established.
2. Ask which block to analyze.
3. If a profile exists, load it with `get_strategy_profile` to note any existing entry filters.

### Step 2: Data Sufficiency Checks

Run ALL checks before proceeding.

**Universal checks:**

```sql
-- Check 1: Trade count and margin coverage
SELECT COUNT(*)::INT as trades,
       COUNT(CASE WHEN margin_req > 0 THEN 1 END)::INT as has_margin
FROM trades.trade_data WHERE block_id = '{blockId}'
```
**Minimum: 50 trades, all with margin > 0.**

**Market data coverage:**

```sql
-- Check 2: All market fields have data for trade dates
SELECT
  CAST(SUM(CASE WHEN m_vix.close IS NOT NULL THEN 1.0 ELSE 0.0 END) AS INT) as has_vix,
  CAST(SUM(CASE WHEN m_spx.RSI_14 IS NOT NULL THEN 1.0 ELSE 0.0 END) AS INT) as has_rsi,
  CAST(SUM(CASE WHEN m_vix.ivp IS NOT NULL THEN 1.0 ELSE 0.0 END) AS INT) as has_ivp,
  CAST(SUM(CASE WHEN m_spx.Realized_Vol_5D IS NOT NULL THEN 1.0 ELSE 0.0 END) AS INT) as has_rv5,
  CAST(SUM(CASE WHEN m_spx.ATR_Pct IS NOT NULL THEN 1.0 ELSE 0.0 END) AS INT) as has_atr,
  CAST(SUM(CASE WHEN m_spx.Price_vs_EMA21_Pct IS NOT NULL THEN 1.0 ELSE 0.0 END) AS INT) as has_ema21,
  CAST(COUNT(*) AS INT) as total
FROM trades.trade_data t
LEFT JOIN market.daily m_vix ON m_vix.ticker = 'VIX'
  AND CAST(m_vix.date AS DATE) = CAST(t.date_opened AS DATE)
LEFT JOIN market.daily m_spx ON m_spx.ticker = 'SPX'
  AND CAST(m_spx.date AS DATE) = (
    SELECT MAX(CAST(m2.date AS DATE)) FROM market.daily m2
    WHERE m2.ticker = 'SPX' AND CAST(m2.date AS DATE) < CAST(t.date_opened AS DATE)
  )
WHERE t.block_id = '{blockId}'
```
**Minimum: 90% coverage for each field.** If any field < 90%, exclude it from the analysis and report: "Excluded {field} — only {n}% of trades have data. Run `/tradeblocks:market-data` to import."

**SLR parseability (for 4-leg structures):**

```sql
SELECT COUNT(*)::INT as total,
       COUNT(CASE WHEN legs LIKE '%STO%' AND legs LIKE '%BTO%' THEN 1 END)::INT as parseable
FROM trades.trade_data WHERE block_id = '{blockId}'
```
If not all parseable, exclude SLR from the filter set.

### Step 3: Compute Baseline Metrics

**CRITICAL: ROM must be computed per-trade FIRST, then averaged.** `rom_pct = pl / margin_req * 100` for each trade. Then `AVG(rom_pct)` across all trades.

```sql
WITH base AS (
  SELECT
    CAST(pl / NULLIF(margin_req, 0) * 100 AS DOUBLE) as rom_pct,
    CASE WHEN pl > 0 THEN 1.0 ELSE 0.0 END as is_win
  FROM trades.trade_data
  WHERE block_id = '{blockId}'
)
SELECT
  ROUND(AVG(rom_pct), 2) as baseline_avg_ror,
  ROUND(SUM(rom_pct), 2) as baseline_net_ror,
  ROUND(SUM(CASE WHEN rom_pct > 0 THEN rom_pct ELSE 0.0 END) /
    NULLIF(ABS(SUM(CASE WHEN rom_pct < 0 THEN rom_pct ELSE 0.0 END)), 0), 2) as baseline_pf,
  ROUND(SUM(is_win) / COUNT(*) * 100, 1) as baseline_wr,
  CAST(COUNT(*) AS INT) as total_trades
FROM base
```

Store baseline values — they are the reference for the entire chart.

### Step 4: Determine Filter Direction and Correlation

Run `find_predictive_fields` with `targetField: "rom"` to get correlation for trade-level fields (SLR, premium).

For market context fields, compute correlations via SQL since they require joins:

```sql
-- Correlation for each market field with ROM
WITH base AS (
  SELECT
    CAST(t.pl / NULLIF(t.margin_req, 0) * 100 AS DOUBLE) as rom_pct,
    CAST(m_vix_sd.close AS DOUBLE) as vix_close,
    CAST(m_vix_pd.ivp AS DOUBLE) as vix_ivp,
    CAST(m_spx.RSI_14 AS DOUBLE) as rsi,
    CAST(m_spx.Realized_Vol_5D AS DOUBLE) as rv5,
    CAST(m_spx.ATR_Pct AS DOUBLE) as atr,
    CAST(m_spx.Price_vs_EMA21_Pct AS DOUBLE) as ema21
  FROM trades.trade_data t
  JOIN market.daily m_vix_sd ON m_vix_sd.ticker = 'VIX'
    AND CAST(m_vix_sd.date AS DATE) = CAST(t.date_opened AS DATE)
  JOIN market.daily m_vix_pd ON m_vix_pd.ticker = 'VIX'
    AND CAST(m_vix_pd.date AS DATE) = (
      SELECT MAX(CAST(m2.date AS DATE)) FROM market.daily m2
      WHERE m2.ticker = 'VIX' AND CAST(m2.date AS DATE) < CAST(t.date_opened AS DATE)
    )
  JOIN market.daily m_spx ON m_spx.ticker = 'SPX'
    AND CAST(m_spx.date AS DATE) = (
      SELECT MAX(CAST(m2.date AS DATE)) FROM market.daily m2
      WHERE m2.ticker = 'SPX' AND CAST(m2.date AS DATE) < CAST(t.date_opened AS DATE)
    )
  WHERE t.block_id = '{blockId}'
)
SELECT
  ROUND(CORR(vix_close, rom_pct), 4) as corr_vix,
  ROUND(CORR(vix_ivp, rom_pct), 4) as corr_ivp,
  ROUND(CORR(rsi, rom_pct), 4) as corr_rsi,
  ROUND(CORR(rv5, rom_pct), 4) as corr_rv5,
  ROUND(CORR(atr, rom_pct), 4) as corr_atr,
  ROUND(CORR(ema21, rom_pct), 4) as corr_ema21
FROM base
```

**Direction rules:**
- Positive correlation: `>=` filter (higher values = better ROM). Test above-threshold groups.
- Negative correlation: `<` filter (lower values = better ROM). Test below-threshold groups.
- For fields with default directions in the table above, use those as the primary direction.
- **Always test both directions** in the sweep and pick the one that produces better results.

### Step 5: Sweep Each Filter

For each filter, sweep 5–8 threshold values across the field's range. Use `get_field_statistics` percentiles as anchor points, then add round-number thresholds.

**SQL pattern for trade-level fields:**

```sql
WITH base AS (
  SELECT
    CAST(pl / NULLIF(margin_req, 0) * 100 AS DOUBLE) as rom_pct,
    CASE WHEN pl > 0 THEN 1.0 ELSE 0.0 END as is_win,
    {field_expression} as fv
  FROM trades.trade_data WHERE block_id = '{blockId}'
)
SELECT
  ROUND(AVG(CASE WHEN fv {op} {t} THEN rom_pct END), 2) as avg_ror,
  ROUND(SUM(CASE WHEN fv {op} {t} THEN rom_pct ELSE 0.0 END), 2) as net_ror,
  ROUND(SUM(CASE WHEN fv {op} {t} AND rom_pct > 0 THEN rom_pct ELSE 0.0 END) /
    NULLIF(ABS(SUM(CASE WHEN fv {op} {t} AND rom_pct < 0 THEN rom_pct ELSE 0.0 END)), 0), 2) as pf,
  ROUND(SUM(CASE WHEN fv {op} {t} THEN is_win ELSE 0.0 END) /
    NULLIF(SUM(CASE WHEN fv {op} {t} THEN 1.0 ELSE 0.0 END), 0) * 100, 1) as wr,
  CAST(CAST(SUM(CASE WHEN fv {op} {t} THEN 1.0 ELSE 0.0 END) AS INT) AS INT) as trades
FROM base
```

Where `{op}` is `>=` or `<` depending on direction.

**SQL pattern for market context fields:**

```sql
WITH base AS (
  SELECT
    CAST(t.pl / NULLIF(t.margin_req, 0) * 100 AS DOUBLE) as rom_pct,
    CASE WHEN t.pl > 0 THEN 1.0 ELSE 0.0 END as is_win,
    CAST(m.{column} AS DOUBLE) as fv
  FROM trades.trade_data t
  JOIN market.daily m ON m.ticker = '{ticker}'
    AND CAST(m.date AS DATE) = {join_expression}
  WHERE t.block_id = '{blockId}'
)
-- same aggregation as above
```

Where `{join_expression}` is:
- Same-day: `CAST(t.date_opened AS DATE)`
- Prior-day (lagged): `(SELECT MAX(CAST(m2.date AS DATE)) FROM market.daily m2 WHERE m2.ticker = '{ticker}' AND CAST(m2.date AS DATE) < CAST(t.date_opened AS DATE))`

**SLR field expression:**
```sql
(CAST(regexp_extract(legs, 'P STO ([0-9.]+)', 1) AS DOUBLE) +
 CAST(regexp_extract(legs, 'C STO ([0-9.]+)', 1) AS DOUBLE)) / NULLIF(
 CAST(regexp_extract(legs, 'P BTO ([0-9.]+)', 1) AS DOUBLE) +
 CAST(regexp_extract(legs, 'C BTO ([0-9.]+)', 1) AS DOUBLE), 0)
```

**1-Lot Premium field expression:**
```sql
CAST(premium AS DOUBLE) / num_contracts
```

**DuckDB BigInt workaround:** Always cast COUNT results via `CAST(CAST(SUM(...) AS INT) AS INT)` and use `CASE WHEN ... THEN 1.0 ELSE 0.0 END` instead of boolean casts to avoid BigInt serialization errors.

### Step 6: Select Recommended Threshold Per Filter

For each filter, pick the "best candidate" threshold:

1. **Must have >= 30 trades** in the filtered group
2. **Avg ROR >= 2pp above baseline** (in the favorable direction)
3. **Smooth gradient** at adjacent thresholds (+/- one step) — ROM should not cliff
4. Among candidates meeting all 3 criteria, prefer the one retaining the most trades

If no threshold meets all criteria, still include the filter using the threshold with the highest avg ROR that has >= 30 trades. Note it as "marginal" if avg ROR improvement is < 2pp.

**Collect for each filter at its recommended threshold:**
- `avg_ror`: Average of individual trade ROMs
- `net_ror`: Sum of individual trade ROMs
- `pf`: Profit Factor on ROM basis = SUM(positive ROMs) / ABS(SUM(negative ROMs))
- `wr`: Win rate
- `trades`: Number of trades retained
- `pct_kept`: trades / total * 100
- `pct_net_ror`: net_ror / baseline_net_ror * 100 (% of baseline Net ROR retained)
- `correlation`: From Step 4

### Step 7: Sort by Avg ROR (Pareto Order)

Sort filters descending by avg ROR. The baseline (no filter) is included as the first bar so the user can visually compare all filters against the as-is performance.

The resulting data array:
```
[Baseline, Filter1 (highest avg), Filter2, ..., FilterN (lowest avg)]
```

### Step 8: Generate Interactive Chart

Save HTML to: `{block_folder}/filter_pareto.html`

**Chart specification:**
- **Library:** Chart.js 4.x + chartjs-plugin-annotation
- **Theme:** Dark (#1a1a2e background, #16213e chart container)
- **Chart type:** Grouped bar chart
- **X-axis:** Filter labels (e.g., "Baseline", "RSI < 50", "SLR >= 0.50") — sorted by Avg ROR descending
- **Left Y-axis:** "Avg ROR %" (orange #e67e22) — min 0, max auto-scaled with padding
- **Right Y-axis:** "% of Baseline Net ROR" (blue #3498db) — min 0, max 110
- **Bar datasets:**
  - Orange bars: Avg ROR % for each filter (left Y-axis)
  - Blue bars: % of Baseline Net ROR retained (right Y-axis)
- **Uniform styling:** All bars use the same color/opacity — no filter is highlighted over others
- **Annotations:**
  - Baseline Avg ROR horizontal dashed line with label
- **Tooltips:** Show filter name, avg ROR, trades kept, avg ROR delta, % of baseline Net ROR retained (with raw Net ROR in parentheses)
- **Legend bar above chart:**
  - Orange swatch: "Avg ROR % (per-trade, then averaged)"
  - Blue swatch: "% of Baseline Net ROR (retained cumulative return)"
  - Dashed line: "Baseline Avg ROR ({baseline}%)"

**Detail table below chart:**

| Column | Description |
|--------|-------------|
| Filter | Name + threshold + lag note |
| Avg ROR % | Per-trade ROM averaged |
| vs Base | Delta in pp, green if positive |
| Net ROR % | Raw sum of trade ROMs |
| vs Base | Delta from baseline Net ROR |
| Profit Factor | SUM(+ROMs) / ABS(SUM(-ROMs)) |
| Win Rate | % winning trades |
| Trades | Count retained |
| % Kept | Trades / total |
| Correlation | Pearson r with ROM |

First row is the baseline (amber/gold tag "Reference").

**Method note below table:** "ROM = per-trade P/L / margin, then averaged. Net ROR = simple sum of individual trade ROMs. Profit Factor = SUM(+ROMs) / |SUM(-ROMs)|. Market fields use prior-day close to prevent lookahead bias."

**Verdict section:**
- Which filter has the best risk-adjusted tradeoff (considering both avg ROR gain AND trade retention)
- Rank filters by correlation strength
- Note which filters exceed the 0.10 correlation threshold for meaningful predictive power
- Flag any filters that cut > 50% of trades

### Step 9: Present Results

Display chart location and markdown summary:

**Pareto summary table:**

| Filter | Threshold | Avg ROR | +/- Base | % Net ROR Kept | Trades | Correlation |
|--------|-----------|---------|----------|----------------|--------|-------------|
| Baseline | — | {rom}% | — | 100% | {n} | — |
| {filter1} | {threshold} | | | | | |
| ... | | | | | | |

**Key findings:**
- Which filter(s) achieve the best avg ROR improvement without destroying net ROR
- The fundamental tradeoff: most filters improve per-trade quality by 2–4pp but sacrifice 50–70% of cumulative returns
- Correlation ranking: which fields have genuine predictive power vs noise
- Whether any filter retains > 80% of net ROR (strong candidate for standalone use)
- Whether any pair of filters might combine well (non-overlapping, different correlation sources)

## Customization

The user can customize the filter set:
- **Add filters:** "Also include VIX9D/VIX ratio" — add to the sweep
- **Remove filters:** "Skip ATR and EMA21" — exclude from analysis
- **Change thresholds:** "Use SLR >= 0.45 instead" — override the recommended level
- **Change sort:** "Sort by % net ROR kept instead" — reorder the Pareto

## Related Skills

- `/alex-tradeblocks:alex-threshold-analysis [field]` — Deep dive into a single filter with full threshold sweep chart
- `/tradeblocks:dc-analysis` — Comprehensive DC strategy analysis (includes filter evaluation)
- `/tradeblocks:optimize` — Broader parameter exploration

## What NOT to Do

- **Don't estimate ROM from average raw P&L.** Always compute `pl/margin_req` per trade first, then average. This is the single most important rule.
- Don't recommend a filter solely because it has the highest avg ROR — always show the net ROR tradeoff
- Don't include filters with fewer than 30 trades at the recommended threshold — flag as "thin data"
- Don't use same-day close-derived fields without lagging — that's lookahead bias
- Don't highlight or visually emphasize any single filter over others — let the data speak
- Don't stack filters without testing them individually first — correlated filters (VIX + VIX IVP) may overlap
- Don't proceed without checking market data coverage — missing data silently drops trades from the join
- Don't confuse total premium correlation (driven by contract sizing) with per-lot premium correlation (the actual entry signal)

## Notes

- The chart HTML uses Chart.js 4.x + annotation plugin from CDN
- Net ROR is expressed as % of baseline to make the tradeoff immediately visual: avg ROR bars should go UP from baseline, net ROR bars should stay as CLOSE to 100% as possible
- For strategies without 4-leg STO/BTO structures, SLR will be automatically excluded
- The default filter set covers the most common entry conditions. For exotic filters (e.g., VIX term structure ratio, OPEX proximity), the user can request additions
- Premium should be normalized to per-lot (premium / num_contracts) to remove the contract-size confound
- DuckDB BigInt serialization: avoid `COUNT(...)::INT` in conditional aggregation. Use `CAST(CAST(SUM(CASE WHEN ... THEN 1.0 ELSE 0.0 END) AS INT) AS INT)` pattern instead
