# US Earnings Calendar Datelist — Trading-Day-Indexed Feature Table

File: `entry_filter_dates_earnings.default.csv`

## Scope

Trading-day-indexed feature table covering one row per **trading day** from 2022-01-03 through 2026-12-18 (1,251 rows × 37 columns). Each row carries the source's pre-existing earnings features (per-index reporting percentage, per-stock days-to/from-earnings) plus 24 new threshold-proximity columns describing how that trading day relates to high-concentration earnings days at >5%, >10%, and >20% reporting thresholds for both SPY and QQQ.

This file is **anchor-agnostic** — consumed by the entry-filter build pipeline via a left-join on `date_opened`. The builder handles anchor prefixing (`Open_*`, `ShortExp_*`, etc.); this file does not.

## Source

`daily_earnings_feature_table.csv`, built locally by the feature-engineering pipeline at `Build Earnings Data/feature engineering/output/`. The pipeline aggregates earnings calendar data (release dates, index-membership weighting) into a daily table where each row carries the percentage of the SPY and QQQ indices reporting that day, plus per-stock days-to/from-earnings counters for AAPL, AMZN, MSFT, NVDA, and TSLA.

**Provenance**: data sourced from upstream earnings calendars + index-membership weights computed in the build pipeline. Refresh cadence is manual — re-run the feature-engineering pipeline against fresh earnings data, then copy the output CSV into `_shared/entry_filter_dates_earnings.default.csv` and rebuild this datelist (re-running the threshold-proximity transform).

## Build process

A one-shot Python transform added 24 threshold-proximity columns to the source table. The transform:

1. Read source CSV (already trading-day-indexed, no row-structure changes).
2. Built 6 category date sets — one per `(index, threshold)` pair — by filtering trading days where `<index>_pct_due_0d > <threshold>`:
   - `spy_above_5pct`, `spy_above_10pct`, `spy_above_20pct`
   - `qqq_above_5pct`, `qqq_above_10pct`, `qqq_above_20pct`
3. For each trading day in the file, computed `days_to`, `days_from`, `weeks_to`, `weeks_from` against each category — 6 categories × 4 directions/units = 24 new columns.
4. Appended new columns to the source structure, preserving all 13 source columns unchanged.
5. Wrote atomically (`.tmp` + `os.replace`) with LF line endings and no BOM.

## Why this shape

**Trading-day indexed (not weekday or calendar-day indexed).** The source is already trading-day indexed because earnings releases align with trading sessions — companies don't report on weekends or market holidays. Joins to `entry_filter_data.date_opened` work cleanly since `date_opened` is always a trading day.

The row-indexing differs from the other datelist files:

| File | Row indexing | Rows/year (~) |
|---|---|---:|
| Holidays | Weekday (Mon–Fri, includes closures) | ~261 |
| OPEX | Calendar-day (all 7 days) | 365 |
| Earnings | Trading-day (excludes weekends + closures) | ~250 |
| Econ calendar | Event-indexed (~9.5 events per trading day) | ~2,500 |

For consumers joining on `date_opened`, all three calendar-style files (holidays, OPEX, earnings) match equivalently — closure-day or weekend rows in the other files just don't get matched.

## Source data semantics

**Units quirk (important):** the `spy_pct_due_0d` and `qqq_pct_due_0d` columns are in **percent units** (5.0 = 5%), NOT decimal form (0.05 = 5%). Threshold logic in the build script uses `> 5`, `> 10`, `> 20` (not `> 0.05`). Documented here because the column-name `_pct_` could be read either way; verified by inspecting the data range (max ~26% for SPY, ~45% for QQQ — only sensible under percent-unit interpretation).

**Per-stock columns use to/from convention already.** `aapl_days_to_earnings`, `aapl_days_from_earnings`, etc. — these match the snake_case to/from convention we use throughout the datelist files. They're also nullable: NULL appears in `_to_` columns when no future earnings date is in the source, and in `_from_` columns at the start of the file before any earnings date has occurred.

**Source covers 5 stocks**: AAPL, AMZN, MSFT, NVDA, TSLA. These are the largest names by index weight in QQQ and major weights in SPY — meaningful per-stock coverage for the entry filter use case but not exhaustive. Adding more stocks would require regenerating the source pipeline upstream.

## Column reference

In file order:

| # | Column | Type | Definition |
|---|---|---|---|
| 1 | `date` | ISO date | Trading day; PK. |
| 2 | `spy_pct_due_0d` | continuous | Percentage of SPY index reporting earnings on this day (units = percent, e.g. `5.0` = 5%). |
| 3 | `qqq_pct_due_0d` | continuous | Percentage of QQQ index reporting earnings on this day. |
| 4 | `aapl_days_to_earnings` | continuous, nullable | Calendar days until next AAPL earnings release. |
| 5 | `aapl_days_from_earnings` | continuous, nullable | Calendar days since previous AAPL earnings release. |
| 6 | `amzn_days_to_earnings` | continuous, nullable | Same for AMZN. |
| 7 | `amzn_days_from_earnings` | continuous, nullable | Same. |
| 8 | `msft_days_to_earnings` | continuous, nullable | Same for MSFT. |
| 9 | `msft_days_from_earnings` | continuous, nullable | Same. |
| 10 | `nvda_days_to_earnings` | continuous, nullable | Same for NVDA. |
| 11 | `nvda_days_from_earnings` | continuous, nullable | Same. |
| 12 | `tsla_days_to_earnings` | continuous, nullable | Same for TSLA. |
| 13 | `tsla_days_from_earnings` | continuous, nullable | Same. |
| 14–17 | `earnings_*_to/from_spy_above_5pct` | continuous, nullable | Days/weeks proximity to nearest day where `spy_pct_due_0d > 5`. |
| 18–21 | `earnings_*_to/from_spy_above_10pct` | continuous, nullable | Same for `> 10`. |
| 22–25 | `earnings_*_to/from_spy_above_20pct` | continuous, nullable | Same for `> 20`. |
| 26–29 | `earnings_*_to/from_qqq_above_5pct` | continuous, nullable | Same for QQQ at `> 5`. |
| 30–33 | `earnings_*_to/from_qqq_above_10pct` | continuous, nullable | Same for QQQ at `> 10`. |
| 34–37 | `earnings_*_to/from_qqq_above_20pct` | continuous, nullable | Same for QQQ at `> 20`. |

### Feature list for entry filter data build

All columns below are eligible features for the entry filter builder. Names follow the canonical to/from snake_case convention used across all four datelist files. The `_pct_due_0d` columns are values (continuous), the `_days_to/from_earnings` columns are pre-existing per-stock proximity, and the `earnings_*_to/from_*` columns are the new threshold proximity built under the convention.

**Per-day values (1 column each):**
```
spy_pct_due_0d                          continuous (percent units, 0–~26)
qqq_pct_due_0d                          continuous (percent units, 0–~45)
```

**Per-stock proximity (10 columns total, 2 per stock):**
```
aapl_days_to_earnings                   aapl_days_from_earnings
amzn_days_to_earnings                   amzn_days_from_earnings
msft_days_to_earnings                   msft_days_from_earnings
nvda_days_to_earnings                   nvda_days_from_earnings
tsla_days_to_earnings                   tsla_days_from_earnings
```

**Threshold-proximity (24 columns total, 4 per category × 6 categories):**
```
earnings_days_to_spy_above_5pct          earnings_days_to_qqq_above_5pct
earnings_days_from_spy_above_5pct        earnings_days_from_qqq_above_5pct
earnings_weeks_to_spy_above_5pct         earnings_weeks_to_qqq_above_5pct
earnings_weeks_from_spy_above_5pct       earnings_weeks_from_qqq_above_5pct
earnings_days_to_spy_above_10pct         earnings_days_to_qqq_above_10pct
earnings_days_from_spy_above_10pct       earnings_days_from_qqq_above_10pct
earnings_weeks_to_spy_above_10pct        earnings_weeks_to_qqq_above_10pct
earnings_weeks_from_spy_above_10pct      earnings_weeks_from_qqq_above_10pct
earnings_days_to_spy_above_20pct         earnings_days_to_qqq_above_20pct
earnings_days_from_spy_above_20pct       earnings_days_from_qqq_above_20pct
earnings_weeks_to_spy_above_20pct        earnings_weeks_to_qqq_above_20pct
earnings_weeks_from_spy_above_20pct      earnings_weeks_from_qqq_above_20pct
```

Total feature columns available to the entry filter builder: **36** (excluding `date` which is the join key).

## Semantics

Identical to the holidays + econ_calendar + OPEX datelists (see `entry_filter_dates_holidays_notes.md` for canonical worked examples of the same-week-zero rule):

**Days (calendar-day distance):**
- `days_to=0` and `days_from=0` on the day of an event of the matching category.
- `days_to=1` on the day before; `days_from=1` on the day after.
- Counts calendar days, not trading days.
- Null when no event of that category exists in the source on the matching side.

**Weeks (ISO-week bucket with same-week-zero rule):**
- ISO week is Mon–Sun.
- If the date's ISO week contains *any* event of the matching category → both `weeks_to` and `weeks_from` = 0.
- Otherwise: integer ISO-week distance to the next/prev event's week.

**Threshold operator:** strict `>` (matches the user's "more than X%" wording). For this dataset `>` and `>=` give identical results since no exactly-on-threshold values exist (no day reports exactly 5.0%, 10.0%, or 20.0% of the index). The convention matters for future data refreshes.

**Naming convention:**
- snake_case throughout for new columns.
- All new threshold-proximity columns prefixed `earnings_*` to match the dataset stem (parallel to `holidays_*`, `econ_calendar_*`, `opex_*`).
- Source columns (`spy_pct_due_0d`, `aapl_days_to_earnings`, etc.) retain the source's original snake_case naming as legacy — they predate the convention and already use to/from style, so no rename was needed.

## Coverage gaps and forward-extension policy

| Range | Affected columns | Reason |
|---|---|---|
| 2022-01-03 to ~2022-04 (per-threshold warmup) | `earnings_*_from_*above_*pct` NULL | No past threshold breach in source until the first one occurs (e.g. first SPY >20% day in source = 2023-02-02). Prior trading days have nothing to anchor `_from_` against. |
| 2026-12-XX onward (last few weeks of source) | `earnings_*_to_*above_*pct` NULL where no future breach exists | Source ends 2026-12-18; the highest-threshold breach (>20%) is rarer so its `_to_` column nulls out earliest. |

Source covers 2022-01-03 → 2026-12-18 (note: ends earlier than the other three datelist files which run to 2026-12-31). The 13-day gap from 2026-12-19 to 2026-12-31 is not padded — joining to `entry_filter_data` on `date_opened` for trades opened in that window will return NULL for all earnings features.

**Forward-extension policy** (shared across all four datelist files): when source data is extended past the current end date, rebuild this file with the new endpoint. **Do not pre-extend the file forward** — extending past the source range would silently produce all-NULL `*_to_*` rows that downstream threshold-sweep skills would have to special-case. Better to keep the file bounded to source data and have the consumer handle out-of-range trades explicitly (skip or treat as missing).

## Philosophy decisions

These are the design choices made during build that aren't obvious from the data:

1. **Trading-day indexed (not weekday or calendar).** Source is already trading-day indexed because earnings releases align with trading sessions. Preserved the source's row structure rather than padding with weekend/closure rows.

2. **Strict `>` threshold operator.** Matches the user's "more than X%" wording. Identical to `>=` for this dataset (no exactly-on-threshold values), but the convention matters for future refreshes.

3. **Three threshold buckets (>5%, >10%, >20%).** Sparsity progression is in the useful-feature range — 8.1% / 3.8% / 0.7% of trading days for SPY at the three thresholds. The 20% bucket is rare enough (9 days over 5 years) that proximity to it is a meaningful market regime feature.

4. **SPY and QQQ separately, no aggregate "either index" feature.** SPY is broad-market-weighted, QQQ is tech-heavy. Treating them as independent dimensions lets the model pick whichever signal correlates with the strategy. An aggregate "either-above-N%" feature can be added later if useful (deferred — see Open design questions).

5. **`earnings_*` prefix for new columns**, matching the dataset stem (parallel to `holidays_*`, `econ_calendar_*`, `opex_*`).

6. **All 13 source columns preserved unchanged.** Their snake_case naming already matches the to/from convention (`<ticker>_days_to_earnings`); no rename needed. Per-day percentage values (`spy_pct_due_0d`, `qqq_pct_due_0d`) stay in their source units (percent, not decimal).

7. **Same-week-zero rule for weeks** (consistent with the other three datelist files). Treats "any threshold breach in the current ISO week" as `weeks_to=0` AND `weeks_from=0`, regardless of pre/post within the week.

8. **0 = day-of for days**, both directions. A trading day where `spy_pct_due_0d > 20` reads `earnings_days_to_spy_above_20pct=0` AND `earnings_days_from_spy_above_20pct=0`.

9. **No forward extension past source data** (shared across all four datelist files). See "Coverage gaps and forward-extension policy" above.

10. **Per-stock columns kept as-is.** AAPL/AMZN/MSFT/NVDA/TSLA proximity is already in the right shape for the entry filter builder. Did not extend with weeks_to/from for these — only days_to/from is in the source, and adding ISO-week proximity per stock can be done later if useful (deferred).

## Statistics

| Metric | Value |
|---|---:|
| Trading days in file | 1,251 |
| Earliest / latest date | 2022-01-03 / 2026-12-18 |
| Total columns | 37 |
| Source columns preserved | 13 |
| New `earnings_*` proximity columns | 24 |
| `spy_above_5pct` reference dates | 101 (8.1% of trading days) |
| `spy_above_10pct` reference dates | 47 (3.8%) |
| `spy_above_20pct` reference dates | 9 (0.7%) |
| `qqq_above_5pct` reference dates | 86 (6.9%) |
| `qqq_above_10pct` reference dates | 62 (5.0%) |
| `qqq_above_20pct` reference dates | 25 (2.0%) |
| SPY range (any reporting) | 0% to 26.17% |
| QQQ range (any reporting) | 0% to 44.58% |
| Days with any SPY reporting | 901 (72.0%) |
| Days with any QQQ reporting | 593 (47.4%) |

**Top SPY reporting days in source** (heaviest earnings clusters):

| Date | SPY % | QQQ % |
|---|---:|---:|
| 2026-04-29 | 26.17% | 40.80% |
| 2023-02-02 | 23.15% | 44.58% |
| 2025-10-29 | 22.69% | 34.68% |
| 2024-04-25 | 22.35% | 36.82% |
| 2023-10-24 | 21.97% | 34.43% |

These are mega-cap earnings clusters (typically days where AAPL/AMZN/MSFT/META/GOOG report together).

## Open design questions (deferred)

1. **Add intermediate or higher thresholds.** E.g. `>7.5%`, `>15%`, `>25%`. Could give finer regime resolution if the 5/10/20 buckets prove too coarse. Adding new thresholds is mechanical (add to the build script's threshold list).

2. **Add weeks_to/from per-stock earnings.** Currently the per-stock columns only have days_to/from. Adding ISO-week proximity (with same-week-zero rule) for AAPL/AMZN/MSFT/NVDA/TSLA would cost 10 new columns and provide weekly-bucket regime features. Not yet built.

3. **Aggregate "either-index above N%" feature.** E.g. `earnings_days_to_either_above_5pct` = min of SPY and QQQ proximity. Currently the model has to compose this manually from the two separate features. Easy to add but not yet built.

4. **Per-stock thresholds.** Could extend the threshold concept to individual stocks (e.g. `earnings_days_to_aapl_earnings_within_3d_of_fomc`). Cross-feature interactions like this are typically better captured by tree models splitting on the existing features, but worth exploring if specific patterns emerge.

5. **Pre-market vs after-hours timing.** Earnings releases happen pre-market or after-hours (rarely intraday). Source doesn't carry timing. Adding it would let the model distinguish "trade entered before pre-market earnings" vs "trade entered after after-hours earnings." Punted — would require source-pipeline changes.

6. **Expand stock universe.** Source covers 5 mega-caps (AAPL, AMZN, MSFT, NVDA, TSLA). META, GOOG/GOOGL, NFLX, AVGO are also significant index weights and frequent market-movers. Expansion requires source-pipeline changes upstream.

## Regenerating

Source of truth is `Build Earnings Data/feature engineering/output/daily_earnings_feature_table.csv` (managed by the local feature-engineering pipeline — refresh that pipeline first). To rebuild this file:

1. Re-run the feature-engineering pipeline against the latest earnings data.
2. Copy the regenerated `daily_earnings_feature_table.csv` to `Dev-TradeBlocks-Skills/_shared/entry_filter_dates_earnings.default.csv`.
3. Rerun the inline transform — read source, compute threshold-proximity for the 6 categories, atomic-write back.
4. Verify date range advanced and threshold-breach counts are reasonable for the new range.

**Always extend the source first**, then rebuild. Pre-extending the file past source data would silently produce all-NULL `*_to_*` rows beyond the source endpoint.

The build script lives inline in conversation history; a future skill (e.g. `dev-entry-filter-build-datelists`) should wrap it alongside the holidays, econ_calendar, and OPEX builds.

**Excel warning**: opening this CSV in Excel and saving it back can reformat dates from ISO YYYY-MM-DD to M/D/YY and may trim rows. Inspect via text editor or pandas; do not save from Excel.

## File format

- Encoding: UTF-8, no BOM (pure ASCII content).
- Line endings: LF.
- Nullable integer columns serialized as empty cells (Excel reads as blank, pandas as NaN, DuckDB as NULL).
- Excel-clean: opens directly without import-wizard prompts.
