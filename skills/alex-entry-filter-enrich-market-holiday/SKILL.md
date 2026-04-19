---
name: alex-entry-filter-enrich-market-holiday
description: 'Enrich trade data with market holiday proximity features. Adds 4 columns to entry_filter_data.csv: Days_to_Holiday, Weeks_to_Holiday, Days_from_Holiday, Weeks_from_Holiday. Uses entry_filter_holidays.default.csv as the holiday reference. Both full closures and early close days count as holidays.'
compatibility: Requires TradeBlocks MCP server with trade data loaded.
metadata:
  author: alex-tradeblocks
  version: 1.0.2
---

# Enrich Market Holiday Proximity

Enrich trade data with calendar distance to the nearest market holiday. Options strategies may behave differently near holidays due to shortened trading weeks, reduced liquidity, and theta acceleration. This skill adds 4 columns to the shared `entry_filter_data.csv` so holiday proximity can be analyzed as an entry filter via threshold analysis, pareto, parallel coords, etc.

Both **full market closures** and **early close days** (e.g., day after Thanksgiving, Christmas Eve) count as holidays.

## Enrichment Columns

| Column | Type | Computation |
|--------|------|-------------|
| `Days_to_Holiday` | continuous int | Calendar days from trade date to next holiday date. Always >= 1 (trade can't fall on a closed holiday). |
| `Weeks_to_Holiday` | continuous int | ISO week difference: next holiday's ISO week minus trade's ISO week. 0 = holiday week, 1 = one week before holiday week, etc. Always >= 0. |
| `Days_from_Holiday` | continuous int | Calendar days from most recent past holiday date to trade date. Always >= 1. |
| `Weeks_from_Holiday` | continuous int | ISO week difference: trade's ISO week minus most recent holiday's ISO week. 0 = holiday week, 1 = one week after holiday week, etc. Always >= 0. |

**Week computation uses ISO week numbers** (YYYY-WW), matching the Holiday_Week / Week_Before / Week_After columns in the holiday reference CSV. This means week boundaries align with Monday-Sunday, not trade-date arithmetic.

**Edge case — trade falls on an early close day:** The trade date IS a holiday date. Days_to_Holiday looks forward to the NEXT holiday (skip the current one). Days_from_Holiday = 0 (trade is on the holiday). Weeks_to/from use the same logic.

## File Dependencies

### Holiday Reference CSV

Resolution order:
1. `_shared/entry_filter_holidays.csv` (user override)
2. `_shared/entry_filter_holidays.default.csv` (shipped default)
3. If neither exists → create `entry_filter_holidays.default.csv` with embedded holiday data on first run

**Columns:** `Holiday_Name`, `Date` (ISO), `Type` (closed/early_close)

Coverage: 2021–2026 (71 holidays). User can extend by creating `entry_filter_holidays.csv` with additional rows.

### Shared Phase 1 Data

| File | Location | Purpose |
|------|----------|---------|
| `entry_filter_data.csv` | `{block_folder}/alex-tradeblocks-ref/` | Trade-level data with date_opened column |
| `entry_filter_holidays.default.csv` | skill-local | Holiday reference dates |

If `entry_filter_data.csv` doesn't exist, build it via the shared Phase 1 pipeline (same as other entry filter skills).

## Prerequisites

- TradeBlocks MCP server running
- At least one block with trade data loaded
- `entry_filter_data.csv` should exist (run any entry filter skill first to build it, or this skill will build it)

## Process

### Step 1: Select Target Block

1. Use `list_blocks` to show available blocks if not already established.
2. Confirm which block to enrich.

### Step 2: Load Holiday Reference

1. Check for `_shared/entry_filter_holidays.csv` (user override).
2. If not found, check `_shared/entry_filter_holidays.default.csv`.
3. If neither exists, create `entry_filter_holidays.default.csv` with the embedded holiday data (see Embedded Holiday Data section).
4. Parse CSV into a list of holiday dates, sorted ascending. Compute ISO weeks at runtime from the dates.
5. Report: "Loaded {n} holidays from {source} ({first_year}–{last_year})."

### Step 3: Load Trade Data

1. Check if `{block_folder}/alex-tradeblocks-ref/entry_filter_data.csv` exists.
2. **If it exists:** Read it. Verify `date_opened` column exists. Report: "Using cached filter data ({n} trades)."
3. **If not found:** Build via shared Phase 1 pipeline:
   - Run sufficiency checks from `phase1_sufficiency_checks.default.sql`
   - Run the data CTE from `phase1_entry_filter_data.default.sql`
   - Write results to `{block_folder}/alex-tradeblocks-ref/entry_filter_data.csv`

### Step 4: Compute Holiday Proximity

For each trade row, using its `date_opened`:

1. **Parse trade date** to a date object and compute its ISO year-week (YYYY-WW).

2. **Find next holiday:**
   - Scan holiday list forward from trade date.
   - If trade date equals a holiday date (early close day), skip it and find the next one for Days_to_Holiday.
   - `Days_to_Holiday` = (next_holiday_date - trade_date).days
   - `Weeks_to_Holiday` = ISO week difference between next holiday's week and trade's week.

3. **Find previous holiday:**
   - Scan holiday list backward from trade date.
   - If trade date equals a holiday date (early close day), that IS the previous holiday (Days_from_Holiday = 0).
   - `Days_from_Holiday` = (trade_date - prev_holiday_date).days
   - `Weeks_from_Holiday` = ISO week difference between trade's week and previous holiday's week.

4. **ISO week difference computation:**
   - Parse both YYYY-WW strings to (year, week) tuples.
   - Convert to absolute week number: `year * 52 + week` (approximate but consistent).
   - Difference = `abs(target_week_num - source_week_num)`.
   - **Better method:** Use Python's `datetime.isocalendar()` to get (year, week, weekday), then compute the Monday of each ISO week and take `(monday_a - monday_b).days // 7`.

### Step 5: Write Enriched CSV

1. Add 4 new columns to the existing `entry_filter_data.csv` data.
2. If columns already exist (re-run), overwrite them.
3. Write back to `{block_folder}/alex-tradeblocks-ref/entry_filter_data.csv`.
4. Report: "Added 4 holiday proximity columns to entry_filter_data.csv ({n} trades enriched)."

### Step 6: Summary Statistics

Report a quick summary:
- Distribution of Days_to_Holiday: min, max, median, mean
- Distribution of Weeks_to_Holiday: value counts for 0, 1, 2, 3+
- Trades in holiday week (Weeks_to_Holiday = 0): count and % of total
- Any trades with missing proximity data (date outside holiday CSV range): count and warning

## Embedded Holiday Data

If `entry_filter_holidays.default.csv` doesn't exist, create it with this data on first run. The CSV should contain all US options market holidays from 2021 through 2026 (71 rows). Read the current `entry_filter_holidays.default.csv` in `_shared/` for the canonical data.

## What NOT to Do

- **Don't use trading days** for day counts — use calendar days. Market impact of holidays is felt in calendar time.
- **Don't exclude early close days** — both full closures and early closes affect liquidity and behavior.
- **Don't leave week columns null** — every trade has a next and previous holiday. If a trade is outside the holiday CSV range, warn but still compute from the nearest available holiday.
- **Don't use simple division for weeks** — use ISO week difference, not `days / 7`. Week boundaries matter.
- **Don't modify the shared Phase 1 SQL** — this skill only adds columns to the output CSV, not the SQL query.
- **Don't double-count** — when a holiday pair (e.g., Thanksgiving + Thanksgiving Early Close) falls in the same week, the week proximity is the same. Days proximity should use the nearest date.
- **Don't create derived binary flags** (e.g., Is_Day_Before_Holiday, Is_Week_After_Holiday). Only output the 4 continuous columns. Binary analysis can be done downstream by threshold skills using the continuous values.
- **Don't generate HTML or charts** — this is a data enrichment skill only. It adds columns to the CSV. Visualization is handled by threshold-analysis, pareto, etc.

## Related Skills

- `alex-entry-filter-threshold-analysis` — Sweep Days_to_Holiday or Weeks_to_Holiday to find optimal filter thresholds
- `alex-entry-filter-heatmap` — See holiday-proximity buckets alongside every other filter in the Binary & Categorical Breakdown
- `alex-create-datelist` — Generate OO-compatible datelist excluding/including holiday-adjacent dates

## Notes

- Holiday data covers 2021–2026. Trades before 2021 will use the earliest available holiday; trades after 2026 will use the latest. Both cases generate a warning.
- The holiday CSV is designed to be user-extensible. To add 2027 holidays, create `entry_filter_holidays.csv` (no `.default`) with the additional rows.
- ISO week numbering: Week 1 is the week containing the first Thursday of the year. Most years have 52 weeks; some have 53. The computation handles year boundaries correctly.
