# US Economic Calendar Datelist — Event-Indexed Feature Table

File: `entry_filter_dates_econ_calendar.default.csv`

## Scope

Event-indexed feature table — one row per scheduled US economic event from 2022-01-03 through 2026-12-31 (12,524 rows × 42 columns). Each row preserves the source event metadata (Id, timestamp, name, impact, wide-flag tags) and adds 32 proximity columns describing how that event's date relates to other category dates in the dataset.

This file is **deliberately event-indexed, not calendar-indexed** — diverging from the holidays and OPEX datelist conventions. Reasons captured in "Why this shape" below.

## Source

**This file is the source of truth** — there is no separate event-list source file in `_shared/`. 12,524 events covering 2022-01-03 to 2026-12-31, 190 distinct event names. The original event-list metadata (Id, Name, Impact, wide-flag tags) is preserved as the file's first 10 columns; the 32 proximity columns are derived from those events.

**Provenance**: data is sourced from the **holiday list Google Sheet pinned in the `test-strats` channel** — an externally-maintained shared sheet aggregating econ calendar releases. Refresh procedure: pull a fresh CSV snapshot from the sheet to a temp location (NOT in `_shared/`), then run the rebuild transform which overwrites this datelist atomically.

Daily event volume: median 9, mean 9.5, max 34. Impact distribution: 51% LOW, 38% MEDIUM, 11% HIGH. Half of weekdays carry ≥1 HIGH-impact event.

## Build process

A one-shot Python transform converted the source event-list into this enriched event-indexed file. The transform:

1. Read source event-list.
2. **Renamed** `Start` → `Start DateTime` to flag that the column carries timestamp + time-of-day data, leaving room for future intraday-resolution features (e.g. `Start TimeMinutes`).
3. **Normalized** the existing `Date` column from M/D/YY → ISO YYYY-MM-DD format.
4. Computed proximity columns for each row's `Date` against 8 category date sets:
   - 5 wide-flag categories: `cpi`, `pmi`, `fomc_minutes`, `fomc`, `jobless` (event treated as positive whenever the wide-flag column is non-null, including the cell value `"x"` in CPI which appears as a tagging variant).
   - 3 impact-tier categories: `high_impact`, `medium_impact`, `low_impact`.
5. Each category contributes 4 columns: `econ_calendar_days_to_X`, `econ_calendar_days_from_X`, `econ_calendar_weeks_to_X`, `econ_calendar_weeks_from_X`.
6. Wrote atomically (`.tmp` + `os.replace`) with LF line endings and no BOM.

Performance: per-date memoization (avg 9.5 events/day × 1,320 distinct dates) reduces work by ~10× vs naive per-row computation.

## Why this shape

The holidays and OPEX datelists are calendar-indexed (one row per weekday) because each calendar day has at most one holiday / OPEX configuration — a clean 1:1 mapping. The econ calendar is fundamentally many-events-per-day (median 9), so collapsing to one row per day discards the per-event metadata (`Name`, `Impact`, `Id`, `Start DateTime`).

Three reasons to preserve event-level rows:

1. **Browsability**: opening the file in Excel reveals the underlying schedule with full event names — useful for spot-checking "what was the HIGH event on this date?" without having to cross-reference the source.
2. **Future intraday features**: `Start DateTime` carries time-of-day data. Future columns (e.g. minute-level distance, pre-market vs post-close indicator) need event-level granularity.
3. **Source-reference traceability**: the `Id` UUID lets us audit any feature value back to the originating source row.

The cost: proximity columns are date-level features attached to event rows, so all events on the same date carry identical proximity values (~9.5× row-level redundancy). For joining to `entry_filter_data` on `date_opened`, the entry filter builder needs to deduplicate to one-row-per-date — typically by selecting the highest-impact event per day, or aggregating across all events.

## Source data semantics

Three quirks/conventions in the source worth knowing before consuming:

1. **`FOMC` wide-flag scope** — the `FOMC` column tags only the press-conference events (19:30 ET), not the broader Fed decision day. On 2022-01-26 (a real FOMC decision date), the source has `Fed Interest Rate Decision` (HIGH, 19:00) and `Fed Monetary Policy Statement` (HIGH, 19:00) on the same day with `FOMC=NaN`, while `FOMC Press Conference` (HIGH, 19:30) carries the `FOMC` tag. So `econ_calendar_days_to_fomc` measures distance to press conferences specifically. For this dataset the press conference always co-occurs with the decision so the result is equivalent — but if a future ingest splits them, the feature would diverge.

2. **CPI tagging inconsistency** — the `CPI` column has cell values `"CPI"` and `"x"`. Both are treated as positive in the proximity calc. Source provider quirk; not corrected.

3. **HIGH-impact events not covered by any wide flag** — 925 events (e.g. NFP, Core PCE, PPI, Retail Sales, GDP Annualized, Powell speeches, Fed Interest Rate Decision). These currently feed only into the `high_impact` aggregate proximity, not into named-category proximity. Promoting them to additional wide flags is a future enhancement (see "Open design questions" below).

## Column reference

In file order:

| # | Column | Type | Definition |
|---|---|---|---|
| 1 | `Id` | string | Source UUID per event (traceability). |
| 2 | `Start DateTime` | timestamp | Event scheduled time, format `M/D/YY HH:MM` (preserved from source). Renamed from `Start`. |
| 3 | `Name` | string | Human-readable event name (190 distinct values). |
| 4 | `Impact` | categorical | `LOW` / `MEDIUM` / `HIGH`. |
| 5 | `Date` | ISO date | Calendar date the event falls on, normalized to YYYY-MM-DD. |
| 6 | `CPI` | flag | Non-null if event is CPI-related. Cell values: `CPI` or `x` (tagging inconsistency, both treated positive). |
| 7 | `PMI` | flag | Non-null if event is PMI-related. Cell value: `PMI`. |
| 8 | `FOMC Min` | flag | Non-null if event is an FOMC minutes release. |
| 9 | `FOMC` | flag | Non-null if event is FOMC-related. **Tags only press conferences, not full decision days** (see Source data semantics). |
| 10 | `Jobless` | flag | Non-null if event is jobless-claims-related (Initial / Continuing). |
| 11–14 | `econ_calendar_*_to/from_cpi` | continuous, nullable | Days/weeks proximity to nearest CPI-tagged date. |
| 15–18 | `econ_calendar_*_to/from_pmi` | continuous, nullable | Same for PMI. |
| 19–22 | `econ_calendar_*_to/from_fomc_minutes` | continuous, nullable | Same for FOMC Minutes releases. |
| 23–26 | `econ_calendar_*_to/from_fomc` | continuous, nullable | Same for FOMC press conferences. |
| 27–30 | `econ_calendar_*_to/from_jobless` | continuous, nullable | Same for jobless claims releases. |
| 31–34 | `econ_calendar_*_to/from_high_impact` | continuous, nullable | Days/weeks to nearest HIGH-impact event date. |
| 35–38 | `econ_calendar_*_to/from_medium_impact` | continuous, nullable | Same for MEDIUM-impact. |
| 39–42 | `econ_calendar_*_to/from_low_impact` | continuous, nullable | Same for LOW-impact. |

## Semantics

Identical to the holidays datelist conventions (see `entry_filter_dates_holidays_notes.md` for canonical worked examples of the same-week-zero rule):

**Days (calendar-day distance):**
- `days_to=0` and `days_from=0` on the day of an event of the matching category.
- `days_to=1` on the day before; `days_from=1` on the day after.
- Counts calendar days, not trading days.
- Null when no event of that category exists in the source on the matching side.

**Weeks (ISO-week bucket with same-week-zero rule):**
- ISO week is Mon–Sun.
- If the event's date falls in an ISO week containing *any* event of the matching category → both `weeks_to` and `weeks_from` = 0.
- Otherwise: integer ISO-week distance to the next/prev event's week.
- **Asymmetry to be aware of**: `weeks_from` can read 0 (same-week rule firing) while `days_from` is NULL (no past event in dataset). This happens when the only matching event in the same ISO week is a future event — the same-week rule satisfies weeks but days_from has nothing to anchor on.

**Naming convention:**
- snake_case throughout for new columns.
- Source columns retain original casing (`Id`, `Start DateTime`, `Name`, `Impact`, `Date`, `CPI`, `PMI`, `FOMC Min`, `FOMC`, `Jobless`) — these predate the convention.
- All new proximity columns prefixed `econ_calendar_*` to match the dataset stem (parallel to `holidays_*` and `opex_*`).

## Coverage gaps and forward-extension policy

**Hard date bounds**: 2022-01-03 → 2026-12-31. The file is bound to the source's natural range — there is no source data outside this range, so backward/forward extension would produce all-NULL rows.

**Within-range first-occurrence warmup**: for each category, events earlier than the first occurrence of that category have NULL `days_from_*` (there is no past event of that type to measure distance to). The `days_to_*` is fine (always populated within range). First occurrences:

| Category | First occurrence | Days with NULL `days_from` |
|---|---|---|
| `pmi`, `jobless`, all impact tiers | 2022-01-03 (first day) | 0 |
| `fomc_minutes` | 2022-01-05 | ~2 |
| `cpi` | ~2022-01-12 | ~10 |
| `fomc` (press conf) | 2022-01-26 | ~25 |

Treat NULLs as missing-value at the consumer level (skip in threshold sweeps).

**Forward-extension policy** (shared across all three datelist files): when source data is extended past the current end date, rebuild this file with the new endpoint. **Do not pre-extend the file forward** — extending past the source range would silently generate all-NULL `days_to_*` rows that downstream threshold-sweep skills would have to special-case. Better to keep the file bounded to source data and have the consumer handle out-of-range trades explicitly (skip or treat as missing).

## Philosophy decisions

These are the design choices we made during build that aren't obvious from the data:

1. **Event-indexed over calendar-indexed.** Preserves event metadata, accepts row-level redundancy in proximity columns, lets the entry-filter builder deduplicate at join time.

2. **Kept all three impact tiers (HIGH/MEDIUM/LOW) for proximity.** Initial recommendation was to drop LOW (51% of events, fires nearly every day → `days_to_low=0` is meaningless). User chose to keep all three for completeness — the entry_filter_groups CSV can toggle off LOW per-block if desired.

3. **Did not extend wide-flag coverage.** 925 HIGH-impact events fall outside the existing 5 wide flags. Promoting NFP, PCE, PPI, Retail Sales, GDP, Fed Decision, Powell speeches to dedicated flags would yield more granular features but expand column count significantly. Punted to future iteration; current behavior subsumes them under the `high_impact` aggregate.

4. **`econ_calendar_*` prefix for new columns**, matching the dataset stem (parallel to `holidays_*` and `opex_*`). Source-column casing inconsistency (`Id`, `Start DateTime`, `FOMC Min`, etc.) accepted as legacy.

5. **Same-week-zero rule for weeks** (consistent with holidays + OPEX). Treats "any event of that category in the current ISO week" as `weeks_to=0` AND `weeks_from=0`, regardless of pre/post within the week.

6. **0 = day-of for days**, both directions. An event row that IS a CPI event reads `days_to_cpi=0` AND `days_from_cpi=0`.

7. **Date format normalized to ISO** (YYYY-MM-DD) in the `Date` column. Original source format (M/D/YY) is brittle for cross-tool consumption (Python pandas, DuckDB, Excel all interpret it differently).

8. **`Id` preserved** as a source-reference column — supports auditing any feature value back to the originating event.

9. **No forward extension past source data** (shared across all three datelist files). See "Coverage gaps and forward-extension policy" above.

## Statistics

| Metric | Value |
|---|---:|
| Total event rows | 12,524 |
| Distinct event dates | 1,320 |
| Distinct event names | 190 |
| Date range | 2022-01-03 → 2026-12-31 |
| HIGH-impact events | 1,408 (11%) |
| MEDIUM-impact events | 4,731 (38%) |
| LOW-impact events | 6,385 (51%) |
| HIGH-impact dates (≥1 HIGH event) | 637 |
| Wide-flag tagged events | CPI 353 · PMI 540 · FOMC 40 · FOMC Min 40 · Jobless 519 |
| Avg events per day | 9.5 |

## Open design questions (deferred)

1. **Promote uncovered HIGH-impact events** (NFP, Core PCE, PPI, Retail Sales, GDP, Fed Decision, Powell speeches) to dedicated wide-flag columns + their proximity columns. Would add ~7 categories × 4 cols = ~28 more proximity columns.

2. **Window-count features** (e.g. `econ_calendar_high_impact_count_next_5d`, `econ_calendar_fomc_in_next_5d`). Often the most informative event feature — captures clustered-event regimes (FOMC + CPI same week) that pairwise proximity features miss. Not yet built.

3. **Build a calendar-indexed rollup file** alongside this event-indexed file. Would be one row per weekday with the same proximity values plus per-day aggregates (`highest_impact_today`, `event_count_today`, `is_high_impact_today` boolean). Joinable directly to `entry_filter_data` on `date_opened` without dedup. Not yet decided whether to maintain both files or have the entry filter builder do the rollup at join time.

4. **Time-of-day features** from `Start DateTime` — pre-market vs post-close, distance from market open/close in minutes. Punted on this iteration.

## Regenerating

Source of truth is **this file**. To rebuild (e.g. after extending source past 2026):

1. Pull a fresh CSV snapshot from the Google Sheet (pinned in `test-strats` channel) to a temp location — do not place it in `_shared/`.
2. Rerun the inline transform pointing at the temp CSV — read source, normalize Date and Start columns, recompute proximity for the 8 categories, atomic-write back to `entry_filter_dates_econ_calendar.default.csv`.
3. Verify date range advanced and warmup pattern is unchanged at the early end of the file.

The build script lives inline in conversation history; a future skill (e.g. `dev-entry-filter-build-datelists`) should wrap it alongside the holidays and OPEX builds.

**Excel warning**: opening this CSV in Excel and saving it back can reformat dates from ISO YYYY-MM-DD to M/D/YY and may trim rows. Inspect via text editor or pandas; do not save from Excel.

## File format

- Encoding: UTF-8, no BOM (source has only ASCII content; `&`, apostrophes, parens preserved).
- Line endings: LF.
- Nullable integer columns serialized as empty cells (Excel reads as blank, pandas as NaN, DuckDB as NULL).
- Excel-clean: opens directly without import-wizard prompts.
