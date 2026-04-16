---
name: alex-create-datelist
description: >
  Generate a filtered datelist from entry filter data for use in Option Omega.
  User specifies a field + threshold or custom criteria. Output is an OO-compatible ISO datelist
  with descriptive label, ready to copy-paste. Reads from shared entry_filter_data.csv when available.
  Usage as whitelist or blackout is contextual — the label provides the necessary info.
compatibility: Requires TradeBlocks MCP server with trade data loaded.
metadata:
  author: alex-tradeblocks
  version: "1.0"
---

# Create Datelist

Generate a copy-paste-ready datelist of trade dates that meet a specified filter condition. Output format matches Option Omega's ISO CSV import format. Whether the list is used as a whitelist or blackout is contextual — the descriptive label provides the necessary info.

**Shared data with Pareto, Parallel Coords, and Threshold Analysis skills.** When the shared `entry_filter_data.csv` exists, dates are filtered directly from it — no SQL needed for any field in the CSV. If the CSV doesn't exist, the skill builds it via the shared Phase 1 pipeline or falls back to direct SQL for fields not in the CSV schema.

## Output Format

The skill outputs a labeled datelist directly in the conversation (not to a file) so the user can copy it.

**Format rules:**
1. Every date is ISO format: `YYYY-MM-DD`
2. Every date has a comma before AND after (including first and last): `,2026-01-03,`
3. Dates are separated by a space: `,2026-01-03, ,2026-01-10, ,2026-01-17,`
4. A descriptive label precedes the datelist on its own line
5. Label format: `{description} gen {YYYYMMDD}, {date_type}.`

**Example output:**

```
Prediction Model 1 >= 0% gen 20260412, start dates.
,2022-05-20, ,2022-06-03, ,2022-06-10, ,2022-07-01, ,2022-07-08, ,2022-07-15, ,2022-07-22, ,2022-08-05, ,2022-08-12, ,2022-08-19,
```

**No line breaks in the datelist.** The entire date sequence must be a single continuous line after the label. This ensures clean copy-paste into OO without stray newlines.

**Date type in label:**
- `start dates` — dates the trade was opened (default, most common)
- `end dates` — dates the trade was closed (if user specifies exit-based filtering)

## Supported Criteria

The user specifies what to filter. Common patterns:

| User Says | Field | Operator | Source |
|-----------|-------|----------|--------|
| `prediction model 1 >= 0` | `Prediction_Model_1` | `>=` | CSV |
| `VIX < 25` | `VIX_Close` | `<` | CSV |
| `SLR >= 0.45` | `SLR` | `>=` | CSV |
| `ROM > 0` (wins only) | `rom_pct` | `>` | CSV |
| `premium > -150` | `premium_per_contract` | `>` | CSV |
| `RSI between 30 and 70` | `RSI_14` | `>= AND <=` | CSV |
| `term structure = contango` | `Term_Structure_State` | `== 1` | CSV |
| `month not in [6, 7, 8]` | `Month` | `not in` | CSV |

**Compound criteria:** The user can combine multiple conditions with AND:
- `prediction model 1 >= 5 and VIX < 30`
- `SLR >= 0.4 and RSI > 30`

Parse each condition independently, apply all as AND (intersection).

**Field name resolution:** Match user input to CSV column names using the same mapping as the threshold analysis skill. If ambiguous, ask.

## File Dependencies

### entry_filter_groups CSV

Same resolution order as other skills:
1. User specifies a file at invocation
2. `_shared/entry_filter_groups.csv` (no `.default`)
3. `_shared/entry_filter_groups.default.csv`

### Shared Phase 1 SQL (used only when building CSV from scratch)

- `_shared/phase1_sufficiency_checks.default.sql`
- `_shared/phase1_entry_filter_data.default.sql`

### entry_filter_data.csv (Phase 1 output)

One row per trade, columns: `date_opened`, `pl_per_contract`, `margin_per_contract`, `rom_pct`, plus all filter columns. Shared across all entry filter skills.

## Prerequisites

- TradeBlocks MCP server running
- At least one block with trade data loaded
- `entry_filter_data.csv` should exist (run any entry filter skill first to build it)

## Process

### Step 1: Parse Criteria

1. **Parse the user's filter specification** into one or more conditions:
   - Each condition: `{field} {operator} {value}`
   - Supported operators: `>`, `>=`, `<`, `<=`, `==`, `!=`, `between X and Y`, `in [...]`, `not in [...]`
2. **Map field names** to CSV Column names using the threshold analysis field mapping.
3. If the user doesn't specify a field, ask: "Which field and threshold? Examples: `prediction model 1 >= 0`, `VIX < 25`, `SLR >= 0.45`"

### Step 2: Select Target Block

1. Use `list_blocks` to show available blocks if not already established.
2. Confirm which block to analyze.

### Step 3: Load Data

**CSV-first (preferred):**

1. Check if `{block_folder}/alex-tradeblocks-ref/entry_filter_data.csv` exists.
2. **If it exists:** Read it. Verify the required field column(s) exist. Report: "Using cached filter data ({n} trades)."
3. **If CSV does not exist and all fields are in the CSV schema:** Build it via shared Phase 1:
   - Run sufficiency checks from `phase1_sufficiency_checks.default.sql`
   - Run the data CTE from `phase1_entry_filter_data.default.sql`
   - Write results to `{block_folder}/alex-tradeblocks-ref/entry_filter_data.csv`

**SQL fallback (fields not in CSV):**

For fields only available via direct SQL (duration, movement, raw gap points), query trades directly:
```sql
SELECT date_opened, {field_expression} as field_val
FROM trades.trade_data
WHERE block_id = '{blockId}'
```

### Step 4: Apply Filter and Extract Dates

1. Apply all conditions to the data (AND logic for compound criteria).
2. Extract `date_opened` for all matching rows.
3. Convert to ISO date format: `YYYY-MM-DD`.
4. Sort chronologically.
5. Deduplicate (shouldn't be needed, but safety check).

### Step 5: Build Label

Construct the descriptive label:

```
{filter_description} gen {today_YYYYMMDD}, start dates.
```

Where `{filter_description}` summarizes the criteria in human-readable form:
- Single condition: `Prediction Model 1 >= 0%`
- Compound: `Prediction Model 1 >= 5% AND VIX < 30`
- ROM-based: `Winning Trades (ROM > 0%)`

`{today_YYYYMMDD}` is today's date in YYYYMMDD format (no hyphens).

### Step 6: Output Datelist

Present the datelist directly in the conversation in a code block:

```
{label}
,{date1}, ,{date2}, ,{date3}, ,{date4}, ,{date5}, ,{date6}, ...
```

The datelist is a **single continuous line** — no line breaks within the date sequence.

**Also report summary metrics:**
- Total trades in dataset
- Trades matching filter: {n} ({pct}%)
- Date range: {first_date} to {last_date}
- If `rom_pct` is available: Avg ROM of included trades, Win Rate, Net ROR

### Step 7: Offer Inverse

After outputting the datelist, offer: "Want the inverse? ({m} dates that did NOT meet the criteria)"

If yes, repeat Step 6 with the excluded dates and an appropriate label describing the inverted criteria.

## Customization

- **Change date type:** "Use close dates instead of open dates" → extract `date_closed` instead
- **Change line width:** "Put 5 dates per line" → adjust wrapping
- **Save to file:** "Save to a file" → write to `{block_folder}/alex-tradeblocks-ref/{slug}_datelist.txt`
- **Multiple blocks:** "Run on all DC blocks" → loop over blocks, generate one datelist per block

## What NOT to Do

- **Don't output to a file by default** — output in the conversation for easy copy-paste.
- **Don't forget the comma before AND after each date** — OO requires this format.
- **Don't include dates where the field value is NULL** — NULL means data was missing, not that the condition failed.
- **Don't hardcode field mappings** — use the entry_filter_groups CSV and threshold analysis field mapping.
- **Don't mix open and close dates** — default is open (start) dates. Only use close dates if the user explicitly asks.
- **Don't skip the summary metrics** — the user needs to verify the filter is producing the expected number of dates.

## Related Skills

- `dev-threshold-analysis` — Find optimal threshold before generating datelist
- `dev-entry-filter-pareto` — Compare all filters to pick the best one
- `dev-entry-filter-parallel-coords` — Visual multi-filter exploration

## Notes

- The datelist format matches Option Omega's date import: comma-wrapped ISO dates. Usage as whitelist or blackout is determined by context — the label describes the criteria so the user knows how to apply it.
- When generating from a prediction model column, note that the model was trained in-sample. Flag this in the label (e.g., "in-sample" or "gen {date}").
- Compound filters apply as AND (intersection). OR logic is not supported — if the user needs OR, generate two separate datelists.
