---
name: alex-entry-filter-pareto
description: >
  Entry filter Pareto chart comparing all candidate filters side-by-side. Shows Avg ROR vs % of
  baseline Net ROR retained for each filter at its recommended threshold. Two-phase workflow:
  Phase 1 builds a reusable data CSV, Phase 2 generates the HTML report. Driven by
  entry_filter_groups.default.csv — no hardcoded filter list.
compatibility: Requires TradeBlocks MCP server with trade data and market data loaded.
metadata:
  author: alex-tradeblocks
  version: "3.0.1"
---

# Entry Filter Pareto

Compare all candidate entry filters side-by-side in a single Pareto chart. For each filter, sweep thresholds to find the best candidate level, then plot Avg ROR (per-trade quality) vs % of Baseline Net ROR retained (cumulative productivity). Surfaces the core tradeoff: per-trade selectivity vs total return.

## Shared Module Architecture (v3.0)

All Pareto report logic lives in the shared module `build_pareto_report.py` (skill-local). Block-specific scripts are thin wrappers that call `generate(config)` with a config dict.

### Wrapper Template

Create `build_pareto_report.py` in the block folder:

```python
#!/usr/bin/env python3
"""Entry filter Pareto report for this block."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '_shared'))
from build_pareto_report import generate

generate({
    'block_folder': os.path.dirname(os.path.abspath(__file__)),
    'block_name':   '20250926 - SPX DC 5-7 22.5-15d oF',
})
```

### Config Reference

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `block_folder` | str | Yes | Absolute path to the block folder |
| `block_name` | str | Yes | Display name for subtitle and title |
| `groups_csv` | str | No | Override path to entry_filter_groups CSV (default: `_shared/entry_filter_groups.default.csv`) |

## Two-Phase Architecture

**Phase 1 (Data):** Query all filter values per trade, compute ROM, write a flat CSV. Cached — only runs if the CSV doesn't exist.

**Phase 2 (Report):** Read the data CSV + entry_filter_groups CSV → sweep thresholds → generate HTML Pareto chart. Always runs. Phase 2 is fully handled by the shared module.

## File Dependencies

### Shared Module

| File | Location | Purpose |
|------|----------|---------|
| `build_pareto_report.py` | skill-local | Shared Pareto report generator module |
| `build_pareto_report.py` | `{block_folder}/` | Thin wrapper script (created per block) |

### entry_filter_groups CSV

Controls which filters exist, how they're classified, and which appear in the report.

**Resolution order:**
1. User specifies a file at invocation → use that
2. User version `_shared/entry_filter_groups.csv` (no `.default`) → use that
3. Default `_shared/entry_filter_groups.default.csv` → use that
4. Neither exists → copy from plugin cache to `_shared/`

**Key columns the skill reads:**

| Column | Phase | Purpose |
|--------|-------|---------|
| TB Filter | 1 | TRUE = include in data query |
| CSV Column | 1 | Column name in entry_filter_data.csv. Blank = skip. |
| TB Table | 1 | Source table — determines query join pattern |
| TB Notes | 1 | Lag rule: "prior day lag" vs "open-known same day" vs "static" |
| Computation | 1 | Blank = direct column. Non-blank = computed field. |
| Report V1 | 2 | TRUE = include in HTML report |
| Filter | 2 | Human-readable label for chart/table |
| Entry Group | 2 | Section grouping in detail table (A through H) |
| Filter Type | 2 | Sweep method: continuous / binary / categorical |

### entry_filter_correlations CSV (optional)

Used in the verdict section for redundancy notes. Same resolution order as above.

## Outputs

- `{block_folder}/alex-tradeblocks-ref/entry_filter_data.csv` — one row per trade, one column per filter
- `{block_folder}/filter_pareto.html` — interactive Pareto chart + detail table

## Prerequisites

- TradeBlocks MCP server running
- At least one block with trade data loaded (50+ trades minimum)
- Market data imported for SPX, VIX, VIX9D, VIX3M (check with SQL join counts)
- All trades must have `margin_req > 0` (required for ROM calculation)
- `_shared/entry_filter_groups.default.csv` must exist

## Process

### Step 1: Select Target Block

1. Use `list_blocks` to show available blocks if not already established.
2. Confirm which block to analyze.
3. If a profile exists, load it with `get_strategy_profile` to note any existing entry filters.

### Step 2: Load Entry Filter Groups

1. Read `entry_filter_groups.csv` using the resolution order above.
2. Parse all rows. Count totals:
   - Total rows: 38
   - TB Filter = TRUE with non-blank CSV Column: ~34 (these become data columns)
   - Report V1 = TRUE: ~21 (these appear in the report)
   - Skipped (blank CSV Column): ~4 (intraday/OO-only)
3. Report to user: "Found {n} queryable filters across {m} source tables. {p} marked for Report V1."

### Step 3: Check Cache

1. Check if `{block_folder}/alex-tradeblocks-ref/entry_filter_data.csv` exists.
2. **If it exists:** Report "Using cached filter data. Delete `alex-tradeblocks-ref/entry_filter_data.csv` and re-run to rebuild." **Skip to Step 7.**
3. **If it does not exist:** Proceed with Phase 1 (Steps 4–6).

### Step 4: Data Sufficiency Checks

Run ALL three checks before building the data query. The SQL lives in a shared file:

**Source:** `_shared/phase1_sufficiency_checks.default.sql`

Read the file, replace `{blockId}` with the target block ID, and execute each tagged query via `run_sql`:

1. **`sufficiency_trades`** — Trade count + margin coverage. Minimum: 50 trades, all with margin > 0.
2. **`sufficiency_market`** — Market data coverage by ticker (7 LEFT JOINs). Minimum: 90% coverage per source. If any source < 90%, exclude its filters and report which ones.
3. **`sufficiency_slr`** — SLR parseability. If not all parseable, set SLR CSV Column to NULL (skip in data query).

### Step 5: Build Data Query

The full CTE query lives in a shared file:

**Source:** `_shared/phase1_entry_filter_data.default.sql`

Read the file, replace `{blockId}` with the target block ID, and execute via `run_sql`.

The query returns one row per trade with all filter columns. Uses LEFT JOINs so trades with missing market data get NULLs rather than being dropped. Structure: `trade_base` CTE → 9 joined CTEs (spx_pd, spx_sd, vix_pd, vix_sd, vix9d_sd, vix9d_pd, vix3m_sd, vix3m_pd, ctx) → final SELECT with ~40 columns.

**Notes:**
- VIX_Gap_Pct: Check if `market.daily` VIX has a `Gap_Pct` column. If yes, use the same-day VIX join to get it directly. If not, compute as `VIX_Open - prior_VIX_Close`. Adjust the COALESCE in the query accordingly.
- The query includes `LIMIT 500` as safety (well above any block's trade count).
- If the query times out due to correlated subqueries, split into 3 queries: (1) trade_base + trade-level, (2) SPX + VIX fields, (3) VIX9D + VIX3M + context. Merge by date_opened.

### Step 6: Write CSV

1. Create `{block_folder}/alex-tradeblocks-ref/` directory if it doesn't exist.
2. Write the query results to `entry_filter_data.csv`.
3. CSV headers must match the `CSV Column` values from entry_filter_groups.csv. Base columns: `date_opened`, `pl`, `margin_req`, `rom_pct`.
4. Report data completeness — for each filter column, count non-null values:

| Status | Criteria |
|--------|----------|
| Complete | 100% non-null |
| Mostly complete | >= 90% non-null |
| Partial | < 90% non-null |
| Unavailable | 0% non-null |

5. Display summary: "{n} of {m} filters have complete data. {p} partial. {q} unavailable."
6. Any filter with < 90% data will be flagged in the report.

---

## Phase 2: Generate Report

### Step 7: Compute Baseline Metrics

Read from `entry_filter_data.csv` (or from query results if just built in Phase 1).

**CRITICAL: ROM must be computed per-trade FIRST, then averaged.** `rom_pct = pl / margin_req * 100` per trade. The CSV already has `rom_pct`.

Compute:
- `baseline_avg_ror` = AVG(rom_pct)
- `baseline_net_ror` = SUM(rom_pct)
- `baseline_pf` = SUM(positive rom_pct) / ABS(SUM(negative rom_pct))
- `baseline_wr` = COUNT(pl > 0) / COUNT(*) * 100
- `total_trades` = COUNT(*)

### Step 8: Determine Report Filters

Read entry_filter_groups.csv. Select rows where:
- `Report V1 = TRUE` (or whichever report column the user specifies)
- `CSV Column` is non-blank
- The CSV Column has >= 90% data completeness (from Step 6)

Classify each selected filter by `Filter Type`:

| Filter Type | Sweep Method | Pareto Chart |
|-------------|-------------|-------------|
| `continuous` | Full resolution: every unique value as threshold | Yes — bar in chart |
| `binary` | Compare TRUE vs FALSE groups | No — detail table only |
| `categorical` | Compare each category; best = recommendation | No — detail table only |

### Step 9: Compute Correlations

For each Report V1 filter, compute Pearson correlation between the filter's CSV Column and `rom_pct` from the data CSV.

```
corr(filter_value, rom_pct) for each filter
```

**Direction rules:**
- Positive correlation → `>=` filter (higher = better ROM)
- Negative correlation → `<` filter (lower = better ROM)
- **Exception for premium_per_contract:** negative correlation means more negative (larger credit) = better. Use `<=` direction.

### Step 10: Sweep Thresholds

**For continuous filters:**

Use full resolution — every unique field value as a threshold point. For each threshold `t`:

With `>=` direction:
- Favorable group: trades where `fv >= t`
- Unfavorable group: trades where `fv <= t` (note: `<=` not `<` — boundary trades appear in BOTH groups)

With `<` direction:
- Favorable group: trades where `fv < t`
- Unfavorable group: trades where `fv >= t`

With `<=` direction (premium):
- Favorable group: trades where `fv <= t` (larger credit = more negative)
- Unfavorable group: trades where `fv >= t`

Compute for the favorable group at each threshold:
- `avg_ror`: AVG(rom_pct)
- `net_ror`: SUM(rom_pct)
- `pf`: SUM(positive rom_pct) / ABS(SUM(negative rom_pct))
- `wr`: win count / total count * 100
- `trades`: count of trades

**For binary filters (Gap_Filled, Is_Opex):**

Compare two groups: TRUE (1) vs FALSE (0). Report both groups' metrics. The "recommended" is whichever group has higher avg_ror with >= 30 trades.

**For categorical filters (Day_of_Week, Month, Term_Structure_State):**

Compare each unique value. Report all categories. The "recommended" is the best category or combination with highest avg_ror and >= 30 trades.

### Step 11: Select Recommended Threshold Per Filter

For each continuous filter, pick the "best candidate" threshold:

1. **Must have >= 30 trades** in the favorable group
2. **Avg ROR >= 2pp above baseline** preferred
3. **Smooth gradient** at adjacent thresholds — ROM should not cliff
4. Among candidates meeting criteria, prefer the one retaining the most trades

If no threshold meets all criteria, use the threshold with the highest avg ROR that has >= 30 trades. Note it as "marginal" if improvement < 2pp.

**Collect for each filter at its recommended threshold:**
- `avg_ror`: Average of individual trade ROMs
- `net_ror`: Sum of individual trade ROMs
- `pf`: Profit Factor on ROM basis
- `wr`: Win rate
- `trades`: Count retained
- `pct_kept`: trades / total * 100
- `pct_net_ror`: net_ror / baseline_net_ror * 100
- `correlation`: From Step 9
- `filter_type`: From entry_filter_groups.csv
- `entry_group`: From entry_filter_groups.csv

### Step 12: Generate Interactive HTML

Save to: `{block_folder}/filter_pareto.html`

**Embed all data in the HTML.** The raw trade data for each Report V1 filter is embedded as JavaScript arrays. This enables full-resolution sweeps client-side with no additional SQL.

**Embedded data format:**
```javascript
const baseline = { avg_ror: X, net_ror: X, pf: X, wr: X, trades: N };
const filters = [
  {
    name: "VIX Close",
    csvColumn: "VIX_Close",
    entryGroup: "A: Volatility Level",
    filterType: "continuous",
    correlation: -0.05,
    direction: "<",
    recommended: { threshold: 25, avg_ror: 16.5, net_ror: 1400, pf: 3.2, wr: 68, trades: 85, pct_kept: 54.1, pct_net_ror: 65 },
    data: [[12.5, 25.3], [14.2, -8.1], ...] // [[filter_value, rom_pct], ...]
  },
  // ... more filters
];
```

**Chart specification:**

- **Library:** Chart.js 4.x + chartjs-plugin-annotation (CDN)
- **Theme:** Dark (#1a1a2e background, #16213e chart container)
- **Chart type:** Grouped bar chart — **continuous filters only** (binary/categorical excluded)
- **X-axis:** Filter labels sorted by Avg ROR descending (e.g., "RSI < 50", "SLR >= 0.50")
  - Rotate labels 45° for readability
  - Abbreviate: use Filter name from CSV + threshold (e.g., "VIX < 25" not "VIX level threshold < 25")
- **Left Y-axis:** "Avg ROR %" (orange #e67e22) — min 0, max auto-scaled with padding
- **Right Y-axis:** "% of Baseline Net ROR" (blue #3498db) — min 0, max 110
- **Bar datasets:**
  - Orange bars: Avg ROR % for each filter (left Y-axis)
  - Blue bars: % of Baseline Net ROR retained (right Y-axis)
- **Uniform styling:** All bars same color/opacity — no filter highlighted over others
- **Annotations:**
  - Baseline Avg ROR horizontal dashed line with label
- **Tooltips:** Show filter name, Entry Group, avg ROR, trades kept (count + %), avg ROR delta (±pp), % of baseline Net ROR (with raw net ROR in parentheses)
- **Legend bar above chart:**
  - Orange swatch: "Avg ROR % (per-trade, then averaged)"
  - Blue swatch: "% of Baseline Net ROR (retained cumulative return)"
  - Dashed line: "Baseline Avg ROR ({baseline}%)"
- **Canvas:** max-width 1400px

**Detail table below chart — organized by Entry Group:**

The table has group header rows separating sections. Within each group, sort by Avg ROR descending.

**Group header rows:** Full-width cells with group name (e.g., "A: Volatility Level") styled with #0f3460 background.

**Data columns:**

| Column | Description |
|--------|-------------|
| Filter | Name + threshold + filter type badge |
| Avg ROR % | Per-trade ROM averaged |
| vs Base | Delta in pp, green if positive, red if negative |
| Net ROR % | Raw sum of trade ROMs |
| % Retained | net_ror / baseline_net_ror * 100 |
| Profit Factor | SUM(+ROMs) / ABS(SUM(-ROMs)) |
| Win Rate | % winning trades |
| Trades | Count retained |
| % Kept | Trades / total |
| Correlation | Pearson r with ROM |

**Row styling:**
- First row: Baseline (amber "Reference" tag)
- Binary/categorical filters: show a badge ("binary" / "categorical") next to the filter name
- Filters with < 2pp improvement: gray "marginal" tag
- Filters cutting > 50% trades: orange "aggressive" tag

**Method note below table:**
"ROM = per-trade P/L / margin, then averaged. Net ROR = simple sum of individual trade ROMs. Profit Factor = SUM(+ROMs) / |SUM(-ROMs)|. Market fields use prior-day close to prevent lookahead bias. Threshold sweep uses full resolution (every unique value). Binary/categorical filters excluded from Pareto chart, shown in detail table only."

**Verdict section:**

- Which continuous filter has the best risk-adjusted tradeoff (avg ROR gain vs trade retention)
- Note same-group redundancy (e.g., "VIX Close and ATR are both Group A — picking both adds little incremental information")
- Rank filters by |correlation| — which have genuine predictive power vs noise (> 0.10 threshold)
- Flag any filters retaining > 80% of net ROR (strong standalone candidates)
- Binary/categorical summary: any standout findings (e.g., "OpEx trades underperform by 3pp")
- Suggestion for next step: run `alex-threshold-analysis` for deep dive on top candidates

### Step 13: Present Results

Display chart location and markdown summary:

**Summary table:**

| Filter | Group | Type | Threshold | Avg ROR | +/- Base | % Net ROR Kept | Trades | Correlation |
|--------|-------|------|-----------|---------|----------|----------------|--------|-------------|
| Baseline | — | — | — | {rom}% | — | 100% | {n} | — |
| {filter1} | A | cont | >= 0.50 | | | | | |
| ... | | | | | | | | |

**Key findings:**
- Which filter(s) achieve the best avg ROR improvement without destroying net ROR
- The fundamental tradeoff: most filters improve per-trade quality by 2–4pp but sacrifice 50–70% of cumulative returns
- Correlation ranking: which fields have genuine predictive power vs noise
- Group redundancy flags from correlation CSV
- Whether any pair of filters might combine well (different Entry Groups, both > 0.10 correlation)

## Customization

- **Change report filters:** Edit `Report V1` column (or add a new Report column) in `entry_filter_groups.csv`
- **Add a filter:** Add a row to `entry_filter_groups.csv` with CSV Column, Filter Type, and TB details. Delete `entry_filter_data.csv` to trigger rebuild.
- **Remove a filter:** Set Report V1 = FALSE. No rebuild needed.
- **Force data rebuild:** Delete `alex-tradeblocks-ref/entry_filter_data.csv`
- **Use a different report column:** "Use Report V2 column instead of Report V1" — the skill reads whichever column is specified
- **Change sort:** "Sort by % net ROR kept instead" — reorder the Pareto

## What NOT to Do

- **Don't estimate ROM from average raw P&L.** Always compute `pl/margin_req` per trade first, then average.
- Don't hardcode filter lists in the skill — everything comes from entry_filter_groups.csv
- Don't recommend a filter solely because it has the highest avg ROR — always show the net ROR tradeoff
- Don't include filters with fewer than 30 trades at the recommended threshold — flag as "thin data"
- Don't use same-day close-derived fields without lagging — that's lookahead bias
- Don't highlight or visually emphasize any single filter over others — let the data speak
- Don't stack filters without testing them individually first — correlated filters may overlap
- Don't proceed without checking market data coverage — missing data silently drops trades from the join
- Don't modify entry_filter_data.csv manually — it's auto-generated
- Don't skip the cache check — it prevents unnecessary re-queries
- Don't confuse total premium correlation (driven by contract sizing) with per-lot premium correlation

## Related Skills

- `alex-threshold-analysis` — Deep dive into a single filter with full threshold sweep chart
- `/tradeblocks:dc-analysis` — Comprehensive DC strategy analysis (includes filter evaluation)
- `/tradeblocks:optimize` — Broader parameter exploration

## Notes

- Chart HTML uses Chart.js 4.x + annotation plugin from CDN
- Net ROR expressed as % of baseline to make the tradeoff immediately visual
- For strategies without 4-leg STO/BTO structures, SLR will be automatically excluded
- DuckDB BigInt serialization: use `CAST(CAST(SUM(CASE WHEN ... THEN 1.0 ELSE 0.0 END) AS INT) AS INT)` pattern
- The data CSV includes ALL TB-available filters (~34 columns), not just Report V1. Changing report flags doesn't require rebuilding the CSV.
- Binary/categorical filters appear in the detail table but not the Pareto chart bars, avoiding apples-to-oranges comparison with threshold-swept continuous filters
