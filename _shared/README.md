# Shared Supporting Files (`_shared/`)

Reference data and SQL templates shared across multiple dev skills. These files are the **source of truth** for shared dependencies — they ship with the plugin (via `_shared/` in the repo, mirroring this dev folder's layout) and are copied to the plugin cache on install.

---

## Folder Organization

```
Dev-TradeBlocks-Skills/
  _shared/
    README.md                                  This file
    entry_filter_groups.default.csv            Entry filter taxonomy and metadata
    entry_filter_correlations.default.csv      Pairwise correlation matrix for market fields
    entry_filter_holidays.default.csv          US options market holidays (2021-2026)
    phase1_entry_filter_data.default.sql       Phase 1 data query (CTE with joins)
    phase1_sufficiency_checks.default.sql      Phase 1 pre-flight checks
```

### Naming Convention

| Pattern | Meaning |
|---------|---------|
| `*.default.csv` / `*.default.sql` | Shipped defaults — maintained by the plugin author |
| `*.csv` / `*.sql` (no `.default`) | User override — your customization, never overwritten |

### How Files Flow

```
_shared/ (dev)  →  repo/_shared/ (GitHub)  →  plugin cache  →  block folder (on first run)
```

1. **Dev:** you edit files here in `_shared/`
2. **Publish:** `dev-github-update` copies `_shared/` contents to `repo/_shared/` during Step 2C
3. **Cache:** users get the files when they install/update the plugin
4. **Block:** on first skill run in a block, if the file doesn't already exist locally, it's copied from the cache

### Resolution Order (at runtime)

When a skill needs a shared file, it resolves in this order:

1. **User specifies a file at invocation** → use that
2. **User override exists** (no `.default` suffix) in `_shared/` → use that
3. **Default copy exists** (`.default` suffix) in `_shared/` → use that
4. **Neither exists** → copy `.default` from plugin cache to `_shared/`, then use it

To refresh defaults after a plugin update: delete or rename the local `.default` file. The next skill run will re-provision from the updated cache.

### Skill-Local Python Modules

Each skill that generates a report has its own `.py` module **inside its skill folder** (not in `_shared/`):

| Module | Skill Folder | Purpose |
|--------|-------------|---------|
| `build_pareto_report.py` | `dev-entry-filter-pareto/` | Pareto chart generator |
| `gen_heatmap.py` | `dev-entry-filter-heatmap/` | Heatmap generator |
| `build_parallel_coords.py` | `dev-entry-filter-parallel-coords/` | Parallel coords chart |
| `gen_threshold_analysis.py` | `dev-threshold-analysis/` | Threshold sweep chart |

These modules use `sys.path.insert` to reference `_shared/` for CSV/SQL imports. They are NOT stored in `_shared/` — they travel with their skill and are copied to the cache alongside the skill's `SKILL.md`.

---

## File Documentation

### `entry_filter_groups.default.csv`

**Purpose:** Unified reference table of all 59 available entry filters across Option Omega (native), TradeBlocks (MCP), and enrichment skills, with group classifications (A-H) and redundancy annotations.

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
| Report V1 | `TRUE` = include in Report V1 presentation (21 of 38 flagged) |
| CSV Column | Exact column name in `entry_filter_data.csv`. Blank = skip (intraday/OO-only). Skills use this to map filter rows to data columns. |
| Filter Type | `continuous` (threshold sweep), `binary` (TRUE/FALSE comparison), or `categorical` (per-category comparison) |
| Computation | Blank = direct DB column reference. Non-blank = computed field (e.g., "VIX9D open / VIX open", "STO legs sum / BTO legs sum from regex") |

**Entry Groups:**

| Group | Name | Count | Key Representative | Description |
|-------|------|-------|--------------------|-------------|
| A | Volatility Level | 14 | VIX_Close or ATR_Pct | VIX level/open/high/low, ATR, RV5/20, Vol_Regime, Intraday_Range, VIX9D/3M close. All r > 0.77 with VIX_Close. |
| B | Relative Volatility | 6 | VIX_IVR | VIX/VIX9D/VIX3M IVR and IVP. Adds ranking dimension beyond raw VIX level (~0.53-0.65 with Group A). |
| C | Momentum / Trend | 14 | RSI_14 | RSI, SMA 5/10/20/50/200 (daily), EMA 5/13/21/50 (min), Ret5D/20D, Close_In_Range, Consecutive_Days, MACD. |
| D | Daily Price Action | 7 | Gap_Pct | Gap, ORB breakout/non-breakout, Prev_Return, Intra_Return, Gap_Filled, Prior_Range_vs_ATR. |
| E | Calendar | 7 | Day_of_Week | DoW, Month, Is_Opex, Holiday proximity (Days/Weeks to/from holiday — continuous). |
| F | Term Structure | 2 | Term_Structure_State | VIX term structure and VIX9D/VIX ratio. Weak negative with VIX level (r = -0.39). |
| G | VIX Event | 2 | VIX_Spike_Pct | VIX_Spike_Pct and VIX_Gap_Pct. Low correlation with VIX level (r ~0.21). |
| H | Premium & Structure | 7 | SLR | SLR, net credit, margin, DC leg premiums. Trade-specific, not market-condition-based. |

**Scope & Limitations:**
- Covers 22 OO native filters, 47 TB filters, 18 shared, 4 OO-only, 29 TB-only. 63 total rows.
- Group classifications are based on SPX market data correlations since 2006. Other underlyings (QQQ, IWM, etc.) may show different correlation structure.
- Premium & Structure filters (Group H) were excluded from the correlation analysis because they are trade-specific, not market-condition fields.
- Entry groups assume the standard TradeBlocks market data schema. Custom-derived fields added by users are not classified.

**How to Recreate:**
1. Run `describe_database` to discover all available market fields
2. Query OO documentation (`docs.optionomega.com/llms-full.txt`) for native entry filters
3. Map OO filters to TB fields by matching semantics (e.g., OO "VIX Filter" -> TB `VIX_Close`)
4. Run pairwise `corr()` queries across all market fields from `market.daily` and `market._context_derived` (SPX + VIX + VIX9D + VIX3M) since 2006
5. Cluster fields with r > 0.77 into groups; assign letters A-H
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
- 59 candidate entry filters collapse to ~8 independent signal types
- Within Group A (Volatility Level), most pairs exceed r = 0.87 -- a single representative (VIX_Close or ATR_Pct) captures the cluster
- VIX_IVR and VIX_IVP (Group B) are r = 0.84 with each other but only ~0.53-0.65 with VIX level, justifying a separate group
- SMA50 and EMA21 (Group C) are r = 0.89 -- near-redundant; pick one
- Calendar fields (Group E) show r < 0.03 with all market fields -- fully independent structural effects
- Gap_Filled is the most independent binary field (r < 0.03 with everything)

**Scope & Limitations:**
- Correlations are computed on the full SPX dataset since 2006. Subsetting to specific regimes or time periods may yield different structure.
- Pearson correlation captures linear relationships only. Non-linear dependencies (e.g., VIX level may matter more at extremes) are not reflected.
- Premium & Structure fields are excluded -- they are trade-specific and cannot be correlated against market fields without a block context.
- The matrix covers 73 selected pairs, not all possible N*(N-1)/2 combinations. Pairs were chosen based on within-group and cross-group relevance.

**How to Recreate:**
1. Build a CTE joining `market.daily` (SPX) with VIX, VIX9D, VIX3M via ticker joins, plus `market._context_derived`
2. Cast integer/boolean fields to DOUBLE (DuckDB `corr()` requires numeric input; BigInt serialization fails without cast)
3. Run `ROUND(corr(field_a, field_b), 3)` for each pair using UNION ALL queries (avoids BigInt serialization issues with wide single-row results)
4. Filter to date >= '2006-01-01' for consistent history
5. Assign groups and implications based on clustering thresholds (r > 0.77 = same cluster, r > 0.87 = near-redundant)

---

### `entry_filter_holidays.default.csv`

**Purpose:** Reference table of US options market holidays for computing trade proximity to holidays. Used by the `dev-entry-filter-enrich-market-holiday` skill to add Days_to_Holiday, Weeks_to_Holiday, Days_from_Holiday, and Weeks_from_Holiday columns to `entry_filter_data.csv`.

**Columns:**

| Column | Description |
|--------|-------------|
| Holiday_Name | Human-readable holiday name (e.g., "Thanksgiving Day") |
| Date | Holiday date in ISO format (YYYY-MM-DD) |
| Type | `closed` (full market closure) or `early_close` (shortened trading hours) |

**Coverage:** 71 holidays from 2021-01-01 through 2026-12-25. Includes all CBOE-recognized US options market holidays and early close days.

**Source:** CBOE US Options Holiday Calendar (https://www.cboe.com/about/hours/us-options/)

**How to Extend:** Create `entry_filter_holidays.csv` (no `.default`) with additional rows for years beyond 2026. The skill resolves user override before the default.

---

### `phase1_entry_filter_data.default.sql`

**Purpose:** Main CTE query that builds the entry filter data CSV. Joins trade data with market data and computes all filter columns.

### `phase1_sufficiency_checks.default.sql`

**Purpose:** Pre-flight checks run before the Phase 1 data query. Validates trade count, market data coverage, and join completeness.

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-04-12 | Initial release: entry_filter_groups.default.csv (38 filters, 8 groups) and entry_filter_correlations.default.csv (73 pairs) |
| 1.1 | 2026-04-14 | Added entry_filter_holidays.default.csv (71 US options market holidays, 2021-2026) |
| 1.2 | 2026-04-14 | Expanded entry_filter_groups to 59 filters (was 38). Restored Entry Groups B/F/G. Added SMA 5/10/20/50/200 (daily), EMA 5/13/21/50 (min), 4 holiday proximity columns (continuous). Fixed phase1 SQL VIX_Gap_Pct reference. Added {ticker} placeholder to phase1 SQL. |
| 1.3 | 2026-04-16 | Migrated from Alex-TradeBlocks-Skills/ to Dev-TradeBlocks-Skills/_shared/. Removed stale .py duplicates (now skill-local). Added SQL template documentation. |
| 1.4 | 2026-04-16 | Repo-side rename: `Alex-TradeBlocks-Skills/` → `_shared/` so the repo mirrors the dev folder. `dev-github-update` bumped to 1.5-dev to handle the rename + stale-destination cleanup. |
