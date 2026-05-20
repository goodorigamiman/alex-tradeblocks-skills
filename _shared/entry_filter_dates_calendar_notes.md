# US Calendar Datelist — Calendar-Indexed Feature Table (Holidays + Date Primitives + Period Ends)

File: `entry_filter_dates_calendar.default.csv`

## Scope

Calendar-indexed feature table covering one row per **weekday** from 2018-01-01 through 2026-12-31 (2,349 rows × 27 columns). Each row carries:

- **Date primitives** — day-of-week (1–5) and calendar month (1–12) computed directly from the date.
- **Holiday categoricals + booleans** — name and closure type of any holiday occurring on that date, plus per-row boolean flags.
- **Holiday proximity** — calendar days and ISO weeks to/from the next/prior full-closure and early-close events.
- **Period-end proximity** — calendar days and ISO weeks to/from the last trading day of the month, quarter, and year.

This file is **anchor-agnostic** — consumed by the entry-filter build pipeline via a left-join on `date_opened` (or any other anchor date the builder requires). The builder handles anchor prefixing (`Open_*`, `ShortExp_*`, etc.); this file does not.

**File renamed from `entry_filter_dates_holidays.default.csv` to `entry_filter_dates_calendar.default.csv` (and column prefix `holidays_*` → `calendar_*`)** to reflect the broader scope: this is the canonical home for calendar features (date primitives + holidays + period ends), not just holidays.

## Source

**This file is the source of truth** — there is no separate event-list source file in `_shared/`. The 107 underlying NYSE/CBOE holiday events (full-closure `closed` + shortened-session `early_close`, 2018-01-01 to 2026-12-25) are captured inside this datelist via the `calendar_name_today`, `calendar_closure_type_today`, and `calendar_is_*_today` columns — filter rows where these are non-null to reconstruct the event list.

Hand-curated; no external provider, no automated refresh. To extend with new years' holidays: edit this datelist directly (or rebuild via the inline transform from a temp event-list CSV).

## Build process

A one-shot Python transform converted the source event-list into this calendar-indexed feature table. The transform:

1. Determined the dataset endpoint as `Dec 31` of the source's last-event year (currently 2026).
2. Generated all weekdays (Mon–Fri) from 2018-01-01 through that endpoint via `pandas.bdate_range`.
3. Computed the trading-day calendar = weekdays minus full-closure source events.
4. For each weekday, computed:
   - **Date primitives**: `calendar_day_of_week` = `date.weekday() + 1` (1=Mon..5=Fri; weekday-only file so range is 1-5). `calendar_month` = `date.month` (1-12).
   - **Categorical lookups** by date (`calendar_name_today`, `calendar_closure_type_today`).
   - **Calendar-day proximity** to nearest closure / early-close event in either direction.
   - **ISO-week proximity** with the same-week-zero rule (see Semantics below).
   - **Boolean indicators** for day-of events.
   - **Period-end trading-day proximity** — for last trading day of {month, quarter, year}, compute days/weeks to/from with same-week-zero rule. Reference dates derived from the trading-day calendar in step 3 — only includes period-ends within the source's data range.
5. Wrote atomically (`.tmp` + `os.replace`) with LF line endings and no BOM (pure ASCII content).

## Why this shape

**Calendar-indexed (one row per weekday), not event-indexed**: each calendar day has at most one holiday — a clean 1:1 mapping. Calendar-indexed gives the entry filter builder a direct join target on `date_opened` without dedup logic. (Compare: the econ calendar is event-indexed because it has many events per day; OPEX is calendar-indexed including weekends because the source already includes weekend rows.)

**Closure days included as rows**, not filtered out. Earlier versions of this build excluded full-closure days from the trading-day calendar entirely, which made `calendar_is_closure_today` structurally always 0 and left `calendar_name_today` empty on closure days — counterintuitive when the file ostensibly carries holiday metadata. Now closure days are real rows with `is_closure_today=1` and populated categoricals. This also means options expirations that conceptually fall on Good Friday and shift to Thursday have a row to look up. For trading-day-anchored joins (`date_opened`), the closure-day rows are simply unmatched — no harm.

**Saturday/Sunday rows excluded.** Markets aren't open weekends, so weekend rows would be padding. `pandas.bdate_range` semantics handle this naturally. (Compare: OPEX retains weekends because its source schema does.)

## Source data semantics

The source is clean: a single `Type` column distinguishes `closed` (full closure) from `early_close` (shortened session). One quirk worth knowing:

**Weekend-dated source closure** — the source contains one weekend-dated event: `2022-01-02 (Sunday) — New Year's Day Observed`. NYSE didn't actually observe Jan 1 2022 as a market holiday (Jan 1 fell on a Saturday — no observance), so this is arguably bad source data. Sundays are not in the weekday calendar so this date does not appear as a row, but proximity calcs still see it (a trading day next to it will measure distance to the Sunday). Downstream consumers should be aware.

## Column reference

In file order:

| # | Column | Type | Definition |
|---|---|---|---|
| 1 | `date` | ISO date | Weekday (Mon–Fri); PK. Includes both trading days and full-closure holidays. |
| 2 | `calendar_day_of_week` | categorical (1–5) | 1=Mon, 2=Tue, 3=Wed, 4=Thu, 5=Fri. Pure date primitive (no holiday context). |
| 3 | `calendar_month` | categorical (1–12) | Calendar month, 1=Jan, ..., 12=Dec. Pure date primitive. |
| 4 | `calendar_name_today` | categorical | Holiday name on day-of, else null. Populated for both closure days and early-close days. |
| 5 | `calendar_closure_type_today` | categorical | `closed` / `early_close` / null. |
| 6 | `calendar_days_to_closure` | continuous, nullable | Calendar days until next `Type=closed` event. 0 on the day-of. Null when no future closure exists in source range. |
| 7 | `calendar_days_from_closure` | continuous, nullable | Calendar days since previous `Type=closed` event. 0 on the day-of. |
| 8 | `calendar_weeks_to_closure` | continuous, nullable | ISO-week distance to next closure, with same-week-zero rule. |
| 9 | `calendar_weeks_from_closure` | continuous, nullable | ISO-week distance from prior closure, with same-week-zero rule. |
| 10 | `calendar_days_to_early_close` | continuous, nullable | Calendar days until next `Type=early_close` event. 0 on the day-of. |
| 11 | `calendar_days_from_early_close` | continuous, nullable | Calendar days since previous `Type=early_close` event. 0 on the day-of. |
| 12 | `calendar_weeks_to_early_close` | continuous, nullable | ISO-week distance, same-week-zero rule. |
| 13 | `calendar_weeks_from_early_close` | continuous, nullable | ISO-week distance, same-week-zero rule. |
| 14 | `calendar_is_closure_today` | boolean | 1 on the 86 weekday closure days in source range, else 0. |
| 15 | `calendar_is_early_close_today` | boolean | 1 on the 20 early-close days in source range, else 0. |
| 16 | `calendar_days_to_last_trading_day_of_month` | continuous, nullable | Calendar days to the last trading day of the month containing this date (or future month if late in current month). 0 on the day-of. |
| 17 | `calendar_days_from_last_trading_day_of_month` | continuous, nullable | Calendar days from the most recent last-trading-day-of-month. 0 on the day-of. |
| 18 | `calendar_weeks_to_last_trading_day_of_month` | continuous, nullable | ISO-week distance, same-week-zero rule. |
| 19 | `calendar_weeks_from_last_trading_day_of_month` | continuous, nullable | ISO-week distance, same-week-zero rule. |
| 20 | `calendar_days_to_last_trading_day_of_quarter` | continuous, nullable | Same as month, but for end of quarter (Mar/Jun/Sep/Dec). |
| 21 | `calendar_days_from_last_trading_day_of_quarter` | continuous, nullable | Same. |
| 22 | `calendar_weeks_to_last_trading_day_of_quarter` | continuous, nullable | Same. |
| 23 | `calendar_weeks_from_last_trading_day_of_quarter` | continuous, nullable | Same. |
| 24 | `calendar_days_to_last_trading_day_of_year` | continuous, nullable | Same as month, but for end of year. |
| 25 | `calendar_days_from_last_trading_day_of_year` | continuous, nullable | Same. |
| 26 | `calendar_weeks_to_last_trading_day_of_year` | continuous, nullable | Same. |
| 27 | `calendar_weeks_from_last_trading_day_of_year` | continuous, nullable | Same. |

## Semantics

This is the **canonical reference for same-week-zero rule examples** — the other two datelist files (econ_calendar, opex) point here.

**Days (calendar-day distance):**
- `days_to=0` and `days_from=0` on the event day itself.
- `days_to=1` on the day before; `days_from=1` on the day after.
- Counts calendar days, not trading days — gives consistent meaning across weekends and holiday clusters.
- Null if no event of that type exists in the source range on the matching side.

**Weeks (ISO-week bucket with same-week-zero rule):**
- ISO week is Mon–Sun (`date.isocalendar()` semantics).
- If today's ISO week contains *any* event of the matching type → both `weeks_to` and `weeks_from` = 0, regardless of which day of the week the event falls on or whether it has happened yet from today's perspective.
- Otherwise: `weeks_to` = number of ISO-week boundaries until the next event's week; `weeks_from` = number of boundaries since the last event's week.
- Effect: "trade opened in the same week as a closure" is detected by `weeks_to_closure == 0` OR `weeks_from_closure == 0` (equivalent in that week). Day-level features still give pre/post asymmetry.
- Null if no event of that type exists in the source range on the matching side.

**Booleans:**
- `1` on day-of, `0` otherwise. Never null.

**Categoricals:**
- The day's matching value if today is a source event, else null.

### Same-week-zero rule — worked examples

| Trading day | Holiday in same ISO week? | weeks_to_closure | weeks_from_closure | Why |
|---|---|---|---:|---|
| Wed 2018-11-21 | Yes (Thanksgiving Thu) | 0 | 0 | Same-week rule: Thursday closure in same ISO week 2018-W47 |
| Mon 2018-11-26 | No (Thanksgiving was W47, today W48) | 1 | 1 | Bush mourning Wed Dec 5 in W49 (1 ahead); Thanksgiving in W47 (1 behind) |
| Mon 2018-12-24 | Yes (Christmas Tue) | 0 | 0 | Christmas closure in same ISO week 2018-W52 |
| Wed 2018-12-26 | Yes (Christmas Tue, same ISO week) | 0 | 0 | Christmas in same ISO week 2018-W52 |
| Mon 2018-12-31 | Yes (New Year's Tue Jan 1, ISO 2019-W01) | 0 | 0 | Cross-year boundary: Mon Dec 31 is in ISO 2019-W01 |
| Wed 2019-01-02 | Yes (New Year's Tue, same ISO week) | 0 | 0 | Same-week rule applies post-event |

## Coverage gaps and forward-extension policy

| Range | Affected columns | Reason |
|---|---|---|
| 2018-01-01 to 2018-07-02 (~129 weekdays) | `calendar_*_from_early_close` NULL | First `early_close` event in source is 2018-07-03 (Independence Day Early Close). Closure-side columns populated from row 1 because the first `closed` event is 2018-01-01. |
| 2026-12-28 to 2026-12-31 (~4 weekdays) | `calendar_*_to_closure` NULL | Last `closed` event in source is 2026-12-25 (Christmas). The handful of weekdays after Christmas have no future closure to anchor to. The corresponding `*_to_early_close` is NULL further back since the last `early_close` is 2026-11-27. |

Decide null handling at the consumer level — threshold sweeps should treat null as missing-value (skip), not as a valid bucket. The `*_from_closure` column has zero NULLs by design (file starts on the first closure). The last-trading-day proximity columns have zero NULLs in either direction because the LTD reference dates are derived from the file's own date range.

**Forward-extension policy** (shared across all three datelist files): when source data is extended to 2027+, rebuild this file with the new endpoint. **Do not pre-extend the file forward** — it would require treating unknown future dates as trading days, contaminating both the holiday proximity calcs (false NULLs become misleading positives) and the last-trading-day calcs (LTD-of-year for an unsourced year would be wrong). Better to keep the file bounded to source data and have the consumer handle out-of-range trades explicitly (skip or treat as missing).

## Philosophy decisions

These are the design choices we made during build that aren't obvious from the data:

1. **Calendar-indexed (one row per weekday).** Holidays are 1:1 with dates → calendar-indexed gives a direct join target without per-event metadata loss.

2. **Closure days included as rows** (not filtered from the trading-day calendar). Makes `is_closure_today` and the categorical columns meaningful instead of always-empty. Trade-anchored joins simply skip closure rows.

3. **Saturdays/Sundays excluded** as rows. Pandas `bdate_range` semantics — markets aren't open weekends, so weekend rows would be padding.

4. **`calendar_*` prefix for new columns**, matching the dataset stem (parallel to `econ_calendar_*` and `opex_*`).

5. **snake_case throughout.** No source-column casing inconsistency to manage (the file is fully derived from the source event-list; no source columns retained verbatim).

6. **Same-week-zero rule for weeks** (consistent with econ_calendar + OPEX). Treats "any event of that category in the current ISO week" as `weeks_to=0` AND `weeks_from=0`, regardless of pre/post within the week.

7. **0 = day-of for days**, both directions.

8. **Last-trading-day proximity included** (LTD-of-month/quarter/year). Period-end effects are common in options strategies (month-end window dressing, quarter-end rebalancing, year-end tax positioning) and add three useful feature dimensions per anchor.

9. **No forward extension past source data** (shared across all three datelist files). See "Coverage gaps and forward-extension policy" above.

10. **ISO date format (YYYY-MM-DD).** Cross-tool friendly. Excel re-saves can corrupt this — see Regenerating section.

## Statistics

| Metric | Value |
|---|---:|
| Weekdays in file | 2,349 |
| Total columns | 27 |
| Earliest / latest date | 2018-01-01 / 2026-12-31 |
| `calendar_day_of_week` distribution | Mon 470, Tue 470, Wed 470, Thu 470, Fri 469 |
| `calendar_month` distribution | balanced 1-12 (~196 days/month avg) |
| Days where `is_closure_today=1` | 86 |
| Days where `is_early_close_today=1` | 20 |
| Days where `calendar_name_today` is populated (any holiday) | 106 |
| Days with closure in same ISO week (`weeks_to_closure==0` AND `weeks_from_closure==0`) | 435 (~18.5%) |
| Days with NULL `days_from_closure` | 0 |
| Days with NULL `days_to_closure` | ~4 (2026-12-28 to 2026-12-31, after last source event) |
| Days with NULL `days_from_early_close` | ~129 (2018-01-01 to 2018-07-02, before first early-close event) |
| `last_trading_day_of_month` reference dates | 108 (9 yrs × 12 mo) |
| `last_trading_day_of_quarter` reference dates | 36 (9 yrs × 4 q) |
| `last_trading_day_of_year` reference dates | 9 |

**Source coverage** (closure / early-close events per year):

| Year | closed | early_close |
|---|---:|---:|
| 2018 | 10 | 3 |
| 2019 | 9 | 3 |
| 2020 | 9 | 2 |
| 2021 | 9 | 1 |
| 2022 | 9 | 1 |
| 2023 | 10 | 2 |
| 2024 | 10 | 3 |
| 2025 | 11 | 3 |
| 2026 | 10 | 2 |
| **Total** | **87** | **20** |

## Open design questions (deferred)

1. **First-trading-day proximity** (mirror of last-trading-day). E.g. `calendar_days_to_first_trading_day_of_month` for "trade opened N days into the new month." Some strategies are sensitive to month-start effects (FOMC blackout-related volatility around month boundaries, etc.). Not yet built.

2. **Business-day-of-month feature**. E.g. `calendar_business_day_of_month` (1-N counting only trading days within the month). Would let analyses pick up "first 5 trading days of month" patterns directly. Currently a consumer can derive from `calendar_days_from_last_trading_day_of_month` of the prior month, but a direct count is simpler. Not yet built.

3. **Combine with the Sunday-observed quirk fix**. `2022-01-02 (Sun)` is in the source as a closure but NYSE didn't observe — corrupts proximity calcs nearby. Either correct in source (preferred) or filter weekend-dated closures during the build. Not yet decided.

4. **Boolean `calendar_is_observed_market_closure_week`** — true if a federal holiday triggered any market closure that week. Captures "Thanksgiving week" / "Christmas week" effects in a single boolean. Currently the user has to compose `weeks_to_closure==0 OR weeks_from_closure==0` to detect this. Not yet built.

## Regenerating

To rebuild (e.g. after extending holidays past 2026):

1. Stage a temp event-list CSV (columns: `Holiday_Name`, `Date`, `Type`) with the new year's events. Don't put it in `_shared/` — temp location only.
2. Rerun the inline transform pointing at the temp CSV. The transform:
   - Reads the temp event-list and finds the latest event year.
   - Generates weekdays from 2018-01-01 through Dec 31 of that latest year.
   - Derives the trading-day calendar (weekdays minus closures).
   - Computes all derived features (proximity, period-ends, date primitives).
3. Atomic write back to `entry_filter_dates_calendar.default.csv`.

**Always extend the source event-list first.** The file's date range is bound to the source — extending the calendar past the source year would silently treat unknown future dates as trading days, contaminating both the closure proximity calcs and the last-trading-day calcs.

A future skill (e.g. `dev-entry-filter-build-datelists`) should wrap this transform alongside the equivalent builds for the economic calendar and options expirations source files. For now the transform lives inline in conversation history.

**Excel warning**: opening this CSV in Excel and saving it back can reformat dates from ISO YYYY-MM-DD to M/D/YY and may trim rows. Inspect via text editor or pandas; do not save from Excel.

## File format

- Encoding: UTF-8, no BOM (pure ASCII content).
- Line endings: LF.
- Nullable integer columns serialized as empty cells (Excel reads as blank, pandas as NaN, DuckDB as NULL).
- Excel-clean: opens directly without import-wizard prompts.
