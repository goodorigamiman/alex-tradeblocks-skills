# Alex-TradeBlocks-Skills — Supporting Files

Reference data and dependencies used by alex-tradeblocks skills at runtime. These files are provisioned to your TradeBlocks Data working directory on first skill run.

---

## Folder Organization

```
Alex-TradeBlocks-Skills/
  README.md                                  This file
  entry_filter_groups.default.csv            Entry filter taxonomy and metadata
  entry_filter_correlations.default.csv      Pairwise correlation matrix for market fields
```

### Naming Convention

| Pattern | Meaning |
|---------|---------|
| `*.default.csv` | Shipped defaults — maintained by the plugin author |
| `*.csv` (no `.default`) | User override — your customization, never overwritten |

Skills resolve files in this order:
1. File specified at invocation → use that
2. User version (no `.default` suffix) → use that
3. Local `.default` copy → use that
4. Nothing found → copy from plugin cache, then use

To refresh defaults after a plugin update: delete or rename the local `.default.csv` file. The next skill run will re-provision from the updated cache.

---

## File Documentation

### `entry_filter_groups.default.csv`

**Purpose:** Unified reference table of all available entry filters across Option Omega (native) and TradeBlocks (MCP), with group classifications and redundancy annotations.

**Columns:**

| Column | Description |
|--------|-------------|
| Section | Organizational category (Market Conditions — VIX, Underlying, Calendar; Premium & Structure) |
| Index | Row number (1–38) |
| Filter | Human-readable filter name |
| OO Filter | `TRUE` if available as a native Option Omega entry filter |
| OO Parameters | Parameter format in OO (e.g., min/max threshold) |
| OO Notes | OO-specific implementation notes |
| TB Filter | `TRUE` if available as a TradeBlocks MCP field |
| TB Field | Exact DuckDB column name(s) used in SQL queries |
| TB Table | Source table in market.duckdb (e.g., `market.daily (VIX)`, `market._context_derived`) |
| TB Notes | Lookahead rules, lag requirements, computation notes |
| Entry Group | Correlation cluster letter (A–H) from the correlation analysis |
| Implication | Redundancy and independence notes for filter selection |

**Entry Groups:**

| Group | Name | Count | Key Representative | Description |
|-------|------|-------|--------------------|-------------|
| A | Volatility Level | 13 | VIX_Close or ATR_Pct | VIX level, ATR, RV5/20, Vol_Regime, Intraday_Range, VIX9D/3M close. All r > 0.77 with VIX_Close. Picking one captures the full cluster. |
| B | Relative Volatility | 2 | VIX_IVR | VIX_IVR and VIX_IVP (r = 0.84 with each other). Adds ranking dimension beyond raw VIX level (~0.53–0.65 with Group A). |
| C | Momentum / Trend | 8 | RSI_14 | RSI, SMA50, EMA21, Ret5D/20D, Consecutive_Days, Close_In_Range, MACD. SMA50 and EMA21 near-redundant (r = 0.89). |
| D | Daily Price Action | 7 | Gap_Pct | Gap, ORB breakout/non-breakout, Prev_Return, Intra_Return, Gap_Filled, Prior_Range_vs_ATR. Mostly independent of each other. |
| E | Calendar | 3 | Day_of_Week | Day_of_Week, Month, Is_Opex. Independent of all market fields (r < 0.03). |
| F | Term Structure | 2 | Term_Structure_State | VIX term structure and VIX9D/VIX ratio. Weak negative with VIX level (r = -0.39); independent signal. |
| G | VIX Event | 2 | VIX_Spike_Pct | VIX_Spike_Pct and VIX_Gap_Pct. Low correlation with VIX level (r ~0.21); captures transient dislocations. |
| H | Premium & Structure | 3 | SLR | Short-to-long ratio, net credit, margin. Trade-specific, not market-condition-based. Excluded from market correlation analysis. |

**Scope & Limitations:**
- Covers 13 OO native filters, 37 TB filters, 12 shared, 1 OO-only (MACD), 25 TB-only.
- Group classifications are based on SPX market data correlations since 2006. Other underlyings (QQQ, IWM, etc.) may show different correlation structure.
- Premium & Structure filters (Group H) were excluded from the correlation analysis because they are trade-specific, not market-condition fields.
- Entry groups assume the standard TradeBlocks market data schema. Custom-derived fields added by users are not classified.

**How to Recreate:**
1. Run `describe_database` to discover all available market fields
2. Query OO documentation (`docs.optionomega.com/llms-full.txt`) for native entry filters
3. Map OO filters to TB fields by matching semantics (e.g., OO "VIX Filter" → TB `VIX_Close`)
4. Run pairwise `corr()` queries across all market fields from `market.daily` and `market._context_derived` (SPX + VIX + VIX9D + VIX3M) since 2006
5. Cluster fields with r > 0.77 into groups; assign letters A–H
6. Write implication notes based on redundancy (r > 0.87 = near-redundant, flag for single-representative selection)

---

### `entry_filter_correlations.default.csv`

**Purpose:** Full pairwise correlation matrix across all market fields available in TradeBlocks, used to identify redundancy and independence between potential entry filters.

**Columns:**

| Column | Description |
|--------|-------------|
| field_a | First field in the pair |
| field_b | Second field in the pair |
| r | Pearson correlation coefficient (rounded to 3 decimal places) |
| group_a | Entry group assignment for field_a (e.g., "A: Volatility Level") |
| group_b | Entry group assignment for field_b |
| same_group | `TRUE` if both fields belong to the same entry group |
| implication | Plain-language note on what the correlation means for filter selection |

**Methodology:**
- Data source: `market.daily` (SPX, VIX, VIX9D, VIX3M) and `market._context_derived`, all trading days since 2006-01-01
- 73 pairwise correlations covering all non-premium market fields
- Integer/boolean fields (`Vol_Regime`, `Term_Structure_State`, `Day_of_Week`, `Month`, `Is_Opex`) cast to DOUBLE for `corr()` computation
- VIX tenor fields (VIX9D, VIX3M) joined via `market.daily` on matching ticker
- Derived fields (`Vol_Regime`, `Term_Structure_State`, `VIX_Spike_Pct`) from `market._context_derived`

**Key Findings:**
- 38 candidate entry filters collapse to ~8 independent signal types
- Within Group A (Volatility Level), most pairs exceed r = 0.87 — a single representative (VIX_Close or ATR_Pct) captures the cluster
- VIX_IVR and VIX_IVP (Group B) are r = 0.84 with each other but only ~0.53–0.65 with VIX level, justifying a separate group
- SMA50 and EMA21 (Group C) are r = 0.89 — near-redundant; pick one
- Calendar fields (Group E) show r < 0.03 with all market fields — fully independent structural effects
- Gap_Filled is the most independent binary field (r < 0.03 with everything)

**Scope & Limitations:**
- Correlations are computed on the full SPX dataset since 2006. Subsetting to specific regimes or time periods may yield different structure.
- Pearson correlation captures linear relationships only. Non-linear dependencies (e.g., VIX level may matter more at extremes) are not reflected.
- Premium & Structure fields are excluded — they are trade-specific and cannot be correlated against market fields without a block context.
- The matrix covers 73 selected pairs, not all possible N*(N-1)/2 combinations. Pairs were chosen based on within-group and cross-group relevance.

**How to Recreate:**
1. Build a CTE joining `market.daily` (SPX) with VIX, VIX9D, VIX3M via ticker joins, plus `market._context_derived`
2. Cast integer/boolean fields to DOUBLE (DuckDB `corr()` requires numeric input; BigInt serialization fails without cast)
3. Run `ROUND(corr(field_a, field_b), 3)` for each pair using UNION ALL queries (avoids BigInt serialization issues with wide single-row results)
4. Filter to date >= '2006-01-01' for consistent history
5. Assign groups and implications based on clustering thresholds (r > 0.77 = same cluster, r > 0.87 = near-redundant)

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-04-12 | Initial release: entry_filter_groups.default.csv (38 filters, 8 groups) and entry_filter_correlations.default.csv (73 pairs) |
