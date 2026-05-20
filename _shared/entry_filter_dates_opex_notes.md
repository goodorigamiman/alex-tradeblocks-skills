# US Options Expiration Datelist — Calendar-Indexed Feature Table

File: `entry_filter_dates_opex.default.csv`

## Scope

Calendar-indexed feature table covering one row per **calendar day** (including weekends) from 2018-01-01 through 2026-12-31 (3,287 rows × 51 columns). Each row carries the source's pre-existing OPEX flags + 4 source-built proximity columns + 16 new `opex_*` proximity columns added under the `entry_filter_dates_*` convention.

This file is **calendar-indexed including weekends** — different from the holidays datelist (weekday-only) because the source already includes weekend rows with `is_trading_day=False`. Preserved as-is.

## Source

**This file is the source of truth** — there is no separate source file in `_shared/`. 3,287 daily rows covering 2018-01-01 to 2026-12-31, Cboe-validated v2 with SPX AM/PM overlap. The original 35 source columns (binary flags, aggregates, source-built proximity) are preserved at positions 1-35; the 16 derived `opex_*` proximity columns are positions 36-51.

**Provenance**: data is sourced from Cboe Options Calendar PDFs (yearly publications). The earlier version had a companion retired companion notes (now folded into this file) documenting source URLs and validation methodology — that has been retired with the source file. Source URLs and the 65-spot-check validation list are referenced in conversation history if a re-validation is ever needed; for now, trust the curated dataset until Cboe publishes new years.

## Build process

1. Read source CSV (already calendar-indexed, no transformation needed for the row structure).
2. Computed proximity columns for 4 derived/selected categories:
   - `monthly` — from source flag `standard_monthly==1`
   - `triple_witching` — **derived** as `standard_monthly==1 AND month IN {3, 6, 9, 12}` (not a source flag)
   - `quarterly` — from source flag `quarterly==1` (which is *quarter-end last trading day*, not triple witching — see semantics quirk below)
   - `vix_monthly` — from source flag `vix_standard==1`
3. Each category contributes 4 columns: `opex_days_to_X`, `opex_days_from_X`, `opex_weeks_to_X`, `opex_weeks_from_X`.
4. Wrote atomically (`.tmp` + `os.replace`) with LF line endings and no BOM.

All 35 original source columns are preserved unchanged. New columns appended at the end.

## Why this shape

**Calendar-indexed including weekends.** The source already has weekend rows in the schedule because options-related state (e.g. days-since-last-OPEX) is meaningful on weekends too. Preserved the source's row structure rather than filtering — no harm done, and joins on `date_opened` (always a trading day) simply skip weekend rows naturally.

(Compare: the holidays file is weekday-only because its source is purely weekday-event-list; the econ calendar is event-indexed because it has many events per day.)

## Source data semantics

The source's flag-naming has two non-obvious quirks worth knowing before consuming:

1. **`quarterly` flag is quarter-END last trading day, NOT triple witching.** Verified: 36 dates total (4/year × 9 years), all on Mar 28-31 / Jun 28-30 / Sep 30 / Dec 31 — these are quarter-close settlement dates, not 3rd-Friday witching dates. The intersection `quarterly ∩ standard_monthly = 0` (mutually exclusive sets).

2. **`vix_standard` and `standard_monthly` are mutually exclusive.** VIX expires Wednesday before 3rd Friday; equity options expire 3rd Friday. They never co-occur. Triple witching computed as their AND would yield 0 dates (which is why we derive triple witching from `standard_monthly` + month-of-year filter instead).

This is why **triple witching had to be derived**, not pulled from a flag.

## Overlaps with other data sources

This file is **the source of truth** for OPEX features in the entry filter pipeline — we read from this CSV, not from TradeBlocks or other locations. But several CSV columns have semantic overlaps with data also present in other locations. Documenting them here so consumers know when to use what:

### Overlap with TradeBlocks `parquet market.enriched`

**TB has `Is_Opex`** — a binary same-day flag in the per-ticker enriched view. Per the TB tool_tip: *"1 if entry date is on or within 1 day of monthly equity-options expiration (3rd Friday), else 0."*

The four `opex_*_monthly` columns in this file (`opex_days_to_monthly`, `opex_days_from_monthly`, `opex_weeks_to_monthly`, `opex_weeks_from_monthly`) cover the **same conceptual area** at higher granularity. Mapping:

| TB | This file (CSV-sourced) | Granularity difference |
|---|---|---|
| `Is_Opex == 1` | `opex_days_to_monthly <= 1 OR opex_days_from_monthly <= 1` | TB binary "within 1 day"; CSV continuous N days to/from |
| (no equivalent) | `opex_weeks_to_monthly == 0` | "OPEX week" detector (Mon-Sun ISO week containing OPEX) |
| (no equivalent) | `opex_days_from_monthly == 4` | "4 days post-OPEX" — granular post-event filter |

**Decision**: this file is canonical. The entry-filter pipeline pulls `opex_*_monthly` from here, not from `Is_Opex`. The entry-filter groups CSV registers `Is_Opex` as the TB cross-reference (`TB Field = Is_Opex`, `TB Filter = TRUE`) so consumers know an analog exists in TB but should still source from CSV.

### Overlap with Calendar datelist `entry_filter_dates_calendar.default.csv`

**Calendar has end-of-quarter proximity** (`calendar_*_last_trading_day_of_quarter`) — calendar days/weeks to/from the last trading day of each quarter. The dates: Mar 28–31, Jun 28–30, Sep 30, Dec 31 (4/year × 9 years = 36).

The four `opex_*_quarterly` columns in this file are **identical** in date set — both are derived from the same quarter-end-trading-day calculation. The CSV-side `opex_*_quarterly` columns originate from the source's `quarterly` flag (which marks the same dates).

**Decision**: the entry-filter groups CSV uses **Calendar's `calendar_*_last_trading_day_of_quarter`** (Group E), not OPEX's `opex_*_quarterly` (Group J), to avoid duplicate features. The `opex_*_quarterly` columns remain in this file for self-containment (so the OPEX file can be queried independently of Calendar) but are *not* registered as separate features in the entry-filter groups CSV.

### No-overlap features (unique to this file)

- `opex_*_triple_witching` — derived 3rd-Friday-of-Mar/Jun/Sep/Dec dates. Not present in TB or any other datelist file.
- `opex_*_vix_monthly` — Wednesday-before-3rd-Friday VIX expiration dates. Not present in TB or any other datelist file.
- All 35 source columns (binary flags, aggregates, source-built proximity) — not duplicated elsewhere.

## Column reference

**Source columns (1-35) — preserved unchanged.** See companion retired companion notes (now folded into this file) for full descriptions. Categorized:

| Group | Columns |
|---|---|
| Identity | `date`, `day_of_week`, `is_trading_day`, `exchange_holiday` |
| Standard monthly flags | `standard_monthly`, `equity_standard_monthly`, `weekly_equity_friday`, `spx_monthly_am`, `am_settled_index_last_trade` |
| SPX weekly flags (dense) | `spx_weekly_pm`, `spx_weekly_mwf`, `spx_weekly_tuesday`, `spx_weekly_thursday`, `spx_weekly_daily`, `spx_0dte_any` |
| Quarter / EOM flags | `spx_eom_pm`, `eom`, `spx_quarterly_pm`, `quarterly` |
| VIX flags | `vix_standard`, `vix_weekly` |
| Misc flags | `holiday_adjusted`, `spy_0dte_informational`, `qqq_0dte_informational`, `double_spx_expiration_day`, `spx_am_pm_overlap_day`, `all_0dte_complex_day` |
| Aggregates | `has_any_core_expiration`, `total_expirations_equal`, `total_expirations_weighted`, `core_expiration_cluster_5d` |
| Source-built proximity | `days_to_next_standard_monthly`, `days_since_prev_standard_monthly`, `days_to_next_vix_standard`, `days_to_next_spx_am_pm_overlap` |

**New `opex_*` proximity columns (36-51) — added under the convention.** All continuous, nullable; same-week-zero rule for weeks; 0=day-of for days:

| # | Column | Source basis |
|---|---|---|
| 36–39 | `opex_days_to_monthly` / `opex_days_from_monthly` / `opex_weeks_to_monthly` / `opex_weeks_from_monthly` | `standard_monthly==1` |
| 40–43 | `opex_days_to_triple_witching` / `_from_triple_witching` / `_weeks_to/from_triple_witching` | derived: `standard_monthly==1 AND month IN {3,6,9,12}` |
| 44–47 | `opex_days_to_quarterly` / `_from_quarterly` / `_weeks_to/from_quarterly` | `quarterly==1` (quarter-END, NOT witching — see quirks above) |
| 48–51 | `opex_days_to_vix_monthly` / `_from_vix_monthly` / `_weeks_to/from_vix_monthly` | `vix_standard==1` |

## Semantics

Identical to the holidays + econ_calendar datelists (see `entry_filter_dates_holidays_notes.md` for canonical worked examples of the same-week-zero rule):

**Days (calendar-day distance):**
- `days_to=0` and `days_from=0` on the day of an event of the matching category.
- `days_to=1` on the day before; `days_from=1` on the day after.
- Counts calendar days, not trading days.
- Null if no event of that category exists in the source on the matching side.

**Weeks (ISO-week bucket with same-week-zero rule):**
- ISO week is Mon–Sun.
- If the date's ISO week contains *any* event of the matching category → both `weeks_to` and `weeks_from` = 0.
- Otherwise: integer ISO-week distance to the next/prev event's week.

**Naming convention:**
- snake_case throughout for new columns.
- All new proximity columns prefixed `opex_*` to match the dataset stem (parallel to `holidays_*` and `econ_calendar_*`).
- `quarterly` was renamed from initial `quarter_close` to parallel the `monthly` naming pattern. Despite the name, it still references the source's quarter-end last-trading-day flag, NOT triple witching.

## Coverage gaps and forward-extension policy

Within the 2018-01-01 → 2026-12-31 range, each category has a warmup period at the start of the file where `*_from_*` reads NULL because no past event of that type exists yet:

| Category | First occurrence | Warmup days with NULL `*_from_*` |
|---|---|---|
| `monthly` | 2018-01-19 | ~13 |
| `vix_monthly` | 2018-01-17 | ~12 |
| `triple_witching` | 2018-03-16 | ~52 weekdays |
| `quarterly` | 2018-03-29 | ~62 weekdays |

The forward edge (2026-12-XX onward) has corresponding NULL `*_to_*` for the last few weeks of 2026 once we run out of future events in source. Decide null handling at consumer level — threshold sweeps should treat null as missing-value (skip), not as a bucket.

**Forward-extension policy** (shared across all three datelist files): when source data is extended past the current end date, rebuild this file with the new endpoint. **Do not pre-extend the file forward** — extending past the source range would silently treat unknown future dates as having no expirations, contaminating proximity calcs. Better to keep the file bounded to source data and have the consumer handle out-of-range trades explicitly (skip or treat as missing).

## Philosophy decisions

These choices were made during build that aren't obvious from just reading the data:

1. **Calendar-indexed including weekends** (preserved source structure). Holidays file is weekday-only; OPEX file keeps weekends because the source does, and weekend rows do no harm for `date_opened` joins.

2. **Triple witching is derived, not flagged.** The source provides no triple-witching flag. Computed as `standard_monthly==1 AND month IN {3, 6, 9, 12}` — yields exactly 4 dates/year × 9 years = 36 dates, matching the 3rd-Friday-of-Mar/Jun/Sep/Dec definition.

3. **`quarterly` retained as the column name** even though the source's `quarterly` flag marks quarter-END (last trading day), not 3rd Friday. Renamed from initial `quarter_close` to parallel `monthly` and avoid noun-style mixing in the column set. The semantics quirk is documented above and in the companion source-notes file.

4. **All 35 source columns preserved unchanged**, including aliases (`equity_standard_monthly`↔`standard_monthly`, `am_settled_index_last_trade`↔`spx_monthly_am`, `eom`↔`spx_eom_pm`, etc.) and the source's pre-built proximity columns. User opted to accept duplication for now rather than strip aliases or replace the source-built proximity with the new convention.

5. **Skipped dense flags entirely.** `spx_weekly_pm` (76% density), `spx_weekly_mwf` (56%), `spx_weekly_daily` (49%), `spx_0dte_any` (76%), `spy_0dte_informational` / `qqq_0dte_informational` (78%), `all_0dte_complex_day` (74%) — too dense for proximity to be informative (`days_to=0` on most days). Source flags retained for direct boolean use; no proximity columns generated.

6. **`vix_monthly` included even though VIX wasn't explicitly mentioned.** It's calendar-aligned with monthly OPEX (always 1-2 days earlier) and useful for VIX-related strategies. User confirmed inclusion.

7. **`opex_*` prefix convention.** All new columns prefixed to match the dataset stem (parallel to `holidays_*` and `econ_calendar_*`). Source columns retain original casing as legacy.

8. **Same-week-zero rule for weeks** (consistent with holidays + econ_calendar). Treats "any event of that category in the current ISO week" as `weeks_to=0` AND `weeks_from=0`.

9. **0 = day-of for days**, both directions.

10. **No forward extension past source data** (shared across all three datelist files). See "Coverage gaps and forward-extension policy" above.

## Statistics

| Metric | Value |
|---|---:|
| Rows in file | 3,287 |
| Date range | 2018-01-01 → 2026-12-31 |
| Trading days flagged in source | 2,261 |
| Total columns | 51 |
| Source columns preserved | 35 |
| New `opex_*` proximity columns | 16 |
| `monthly` event dates | 108 (12/year) |
| `triple_witching` event dates | 36 (4/year) |
| `quarterly` event dates | 36 (4/year, quarter-end) |
| `vix_monthly` event dates | 108 (12/year) |

## Open design questions (deferred)

1. **Strip source-flag aliases** (`equity_standard_monthly`, `am_settled_index_last_trade`, `eom`, `spx_am_pm_overlap_day`) — duplicates of other columns. User explicitly opted to keep for now.

2. **Replace source-built proximity** (`days_to_next_standard_monthly`, `days_since_prev_standard_monthly`, `days_to_next_vix_standard`, `days_to_next_spx_am_pm_overlap`) with the new `opex_*` convention. Currently they coexist with the new columns (some duplicating, e.g. source's `days_to_next_standard_monthly` ≈ new `opex_days_to_monthly`). Cleanup deferred.

3. **Promote dense flags to span/window features** instead of skipping. E.g. `opex_spx_0dte_any_count_next_5d` could be informative even though pairwise proximity isn't. Not yet built.

4. **Build event-of-day categorical feature** — e.g. `opex_today_event_class` with values like `triple_witching`, `monthly_only`, `quarter_close`, `vix_monthly`, `none` — collapses multiple booleans into one categorical. Not yet built.

## Regenerating

Source of truth is this datelist file (managed/refreshed independently — see its companion notes file retired companion notes (now folded into this file)). To rebuild this file: rerun the inline transform — read source, compute proximity for the 4 categories, atomic-write back. Build script lives inline in conversation history; a future skill (`dev-entry-filter-build-datelists`) should wrap this alongside the holidays and econ_calendar builds.

**Always extend the source first**, then rebuild. Pre-extending the file past source data would silently produce all-NULL `*_to_*` rows beyond the source endpoint.

**Excel warning**: opening this CSV in Excel and saving it back can reformat dates from ISO YYYY-MM-DD to M/D/YY and may trim rows. Inspect via text editor or pandas; do not save from Excel.

## File format

- Encoding: UTF-8, no BOM (pure ASCII content).
- Line endings: LF.
- Nullable integer columns serialized as empty cells (Excel reads as blank, pandas as NaN, DuckDB as NULL).
- Excel-clean: opens directly without import-wizard prompts.
