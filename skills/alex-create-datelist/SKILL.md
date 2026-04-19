---
name: alex-create-datelist
description: 'Generate a filtered datelist from entry filter data for use in Option Omega. User specifies a field + threshold or custom criteria. Output is an OO-compatible ISO datelist with descriptive label, ready to copy-paste. Reads from shared entry_filter_data.csv when available. Usage as whitelist or blackout is contextual — the label provides the necessary info.

  '
compatibility: Requires TradeBlocks MCP server with trade data loaded.
metadata:
  author: alex-tradeblocks
  version: 1.5.0
---

# Create Datelist

Generate a copy-paste-ready datelist of trade dates that meet a specified filter condition. Output format matches Option Omega's ISO CSV import format. Whether the list is used as a whitelist or blackout is contextual — the descriptive label provides the necessary info.

**Shared data with Pareto, Parallel Coords, and Threshold Analysis skills.** When the shared `entry_filter_data.csv` exists, dates are filtered directly from it — no SQL needed for any field in the CSV. If the CSV doesn't exist, the skill builds it via the shared Phase 1 pipeline or falls back to direct SQL for fields not in the CSV schema.

## Output Format

The skill outputs TWO separate code blocks, each independently copy-pasteable:

1. **Specific Dates (whitelist)** — AND-combined intersection. ONE label + ONE dates row containing only dates where ALL filters clear. The label concatenates every filter expression with ` + ` so the provenance stays with the copy-paste.
2. **Blackout Dates (blacklist)** — PER-FILTER. Each filter gets its own label + dates row listing the dates that did NOT meet that single condition. Dates may repeat across filter blocks — that's fine for blackout use because OO will de-dupe when applied.

**Why two blocks:** In OO, whitelist ("specific dates") is an AND constraint — the trade must be on a listed date to run, so passing per-filter lists would be wrong. Blackout ("skip these dates") is an OR constraint — any filter can independently veto, so per-filter rows let the user delete whole filter-rows to drop them without rebuilding the intersection.

**Datelist type is part of every label** (`specific dates:` or `blackout dates:`) so when the user pastes just a fragment into OO, it still self-describes.

**Layout rules:**
1. Every date is ISO format: `YYYY-MM-DD`
2. Every date has a comma before AND after (including first and last): `,2026-01-03,`
3. Dates are separated by a space: `,2026-01-03, ,2026-01-10, ,2026-01-17,`
4. Each entry: label on one line (ending with `.`), dates on the next line (single continuous line, no wrapping).
5. Within the blackout block, filters are separated by a blank line.
6. Label format (both blocks end with `gen {YYYYMMDD}.` — no trailing `start dates` suffix on either):
   - Specific: `specific dates: {f1} + {f2} + {f3} gen {YYYYMMDD}.`
   - Blackout: `blackout dates: {filter_expression} gen {YYYYMMDD}.`
7. No blank line between a label and its dates. A single blank line separates filters within the blackout block.

**Example output (two separate code blocks):**

Specific Dates (intersection, one row):

````
```
specific dates: VIX_IVP <= 92.032 + VIX9D_VIX_Ratio >= 0.807 + margin_per_contract <= 234 + Gap_Pct <= 0.269 gen 20260413.
,2022-05-16, ,2022-06-13, ,2022-06-27, …
```
````

Blackout Dates (one row per filter, repeats allowed):

````
```
blackout dates: VIX_IVP <= 92.032 gen 20260416.
,2022-10-17, ,2024-04-22, …

blackout dates: VIX9D_VIX_Ratio >= 0.807 gen 20260416.
,2022-05-30, ,2022-06-20, …

blackout dates: margin_per_contract <= 234 gen 20260416.
,2022-06-20, ,2022-07-04, …

blackout dates: Gap_Pct <= 0.269 gen 20260416.
,2022-05-23, ,2022-06-06, …
```
````

**Single-filter case:** Specific block still has one row (just one filter in the label — no `+`). Blackout block also has one row. Two blocks total even with one filter, so the user always sees the whitelist/blacklist pair.

**No line breaks inside a row's dates.** Each dates sequence must be a single continuous line.

**Date type:** The skill uses `date_opened` (trade open date) by default — this is what OO's Specific Dates / Blackout Dates slots expect. Labels do NOT carry an explicit `start dates` / `end dates` suffix; trade-open is implied. If a user explicitly requests close-date filtering, extract `date_closed` instead and note this in the conversation (but the label format stays the same).

**Blackout inversion rule:** For each filter, a blackout date is any `date_opened` from the data where the filter condition evaluated FALSE (i.e., trade was ACTIVE that day but failed the criterion). NULL values are excluded from blackout — NULL means data was missing, not that the filter failed.

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

### Step 4: Compute Both Datelists

**Specific Dates (whitelist, AND-intersection):**
1. Apply ALL filter conditions jointly to every trade (AND).
2. Extract `date_opened` for matching rows.
3. Convert to ISO, sort, dedupe.

**Blackout Dates (per-filter, inverse):**
For **each** filter independently:
1. Identify trades where the filter condition is non-null AND evaluates FALSE.
2. Extract `date_opened` for those rows.
3. Convert to ISO, sort, dedupe.
4. Record per-filter metrics (blackout count, and for the POSITIVE side: trades retained, net ROR retained vs baseline, avg ROR).

### Step 5: Build Labels

**`gen` date = the LAST `date_opened` in `entry_filter_data.csv`**, formatted `YYYYMMDD` (no hyphens). This is NOT today's date — it's the coverage date of the underlying data, so when the user pastes a datelist into OO months later they can see exactly how fresh the source trades were.

**Specific block** — one label, with ALL filter expressions joined by ` + `:
```
specific dates: {f1} + {f2} + {f3} gen {data_max_YYYYMMDD}.
```

**Blackout block** — one label per filter:
```
blackout dates: {filter_expression} gen {data_max_YYYYMMDD}.
```

The `{filter_expression}` values are verbatim as the user wrote them (e.g., `VIX_IVP <= 92.032`) so provenance stays with the copy-paste.

### Step 6: Output — Fixed Order

**The output must always appear in this exact order (no exceptions):**

1. Skill version line: `alex-create-datelist v{version} · gen {data_max_YYYYMMDD} (last date_opened in entry_filter_data.csv)`
2. Summary table (baseline row + per-filter rows + AND-intersection row, columns as specified below)
3. Code Block 1 — **Specific Dates** (whitelist, single label + single dates line, label ends with `gen YYYYMMDD.`)
4. Code Block 2 — **Blackout Dates** (one label + dates line per filter, blank line between filters, each label ends with `gen YYYYMMDD.`)

**Block 1 — Specific Dates (whitelist):**

```
specific dates: {f1} + {f2} + ... gen YYYYMMDD.
,{date1}, ,{date2}, ...
```

**Block 2 — Blackout Dates (one row per filter).** Label immediately followed by its dates line (no blank between them). A single blank line separates one filter from the next:

```
blackout dates: {f1} gen YYYYMMDD.
,{date1}, ,{date2}, ...

blackout dates: {f2} gen YYYYMMDD.
,{date1}, ,{date2}, ...

blackout dates: {f3} gen YYYYMMDD.
,{date1}, ,{date2}, ...
```

Dates may repeat across blackout rows — that's expected (each filter blacks out independently).

**Report a summary table immediately BEFORE the code blocks.** Format and order are fixed:

**Line immediately above the table** — skill version marker (so copied output self-identifies):

```
alex-create-datelist v{version_from_frontmatter} · gen {data_max_YYYYMMDD} (last date_opened in entry_filter_data.csv)
```

**Columns — in this exact order:**

| # | Column | Contents | Formatting |
|---|---|---|---|
| 1 | `Filter` | Filter expression verbatim (or `All Trades (baseline)` / `All AND (specific dates)`) | First and last rows **bold** |
| 2 | `Keep` | Count of trades passing the filter | Integer, right-aligned |
| 3 | `Blackout` | Count of trades where the filter was non-null and failed | Integer, right-aligned |
| 4 | `Net ROR` | Sum of `rom_pct` over the keep subset, as % of baseline Net ROR (baseline = 100.0%) | `XX.X%`, right-aligned |
| 5 | `Avg ROR` | Mean `rom_pct` across keep | `XX.XX%`, right-aligned |
| 6 | `Avg ROR +pts` | `Avg ROR(row) − Avg ROR(baseline)` | `+X.XX pp` / `-X.XX pp`; baseline row = `—` |
| 7 | `WR` | Win rate of keep | `XX.X%`, right-aligned |
| 8 | `WR +pts` | `WR(row) − WR(baseline)` | `+X.XX pp` / `-X.XX pp`; baseline row = `—` |

**Row order — fixed:**

1. **`All Trades (baseline)`** — the anchor row. Keep = total trades, Blackout = 0, Net ROR = 100.0%, both `+pts` columns = `—`.
2. One row per user-supplied filter, in the order the user listed them.
3. **`All AND (specific dates)`** — the intersection row matching the Specific Dates code block.

Template (values are placeholders):

| Filter | Keep | Blackout | Net ROR | Avg ROR | Avg ROR +pts | WR | WR +pts |
|---|---:|---:|---:|---:|---:|---:|---:|
| **All Trades (baseline)** | Nₜ | 0 | 100.0% | B.BB% | — | W.W% | — |
| {f1} | N₁ | K₁ | R₁% | A₁% | ±ΔA₁ pp | W₁% | ±ΔW₁ pp |
| {f2} | N₂ | K₂ | R₂% | A₂% | ±ΔA₂ pp | W₂% | ±ΔW₂ pp |
| … | … | … | … | … | … | … | … |
| **All AND (specific dates)** | N∩ | B∪ | R∩% | A∩% | ±ΔA∩ pp | W∩% | ±ΔW∩ pp |

The first row anchors the comparison so every other row is read as "what this filter does relative to doing nothing." Individual rows describe each filter's keep effect in isolation. The last row describes the specific-dates whitelist (what actually runs).

### Step 7: Offer Inverse

Offer: "Want the inverse of any individual filter (swap blackout ↔ keep)?"

## Customization

- **Change date type:** "Use close dates instead of open dates" → extract `date_closed` instead
- **Change line width:** "Put 5 dates per line" → adjust wrapping
- **Multiple blocks:** "Run on all DC blocks" → loop over blocks, generate one datelist per block

## What NOT to Do

- **Don't conflate specific and blackout.** Specific dates MUST be the AND-intersection (trade runs only if the date is listed); blackout dates MUST be per-filter (any filter's blackout independently vetoes). Mixing these breaks OO's semantics.
- **Don't AND-combine blackouts.** Each filter gets its own blackout row. Overlapping dates are expected and correct.
- **Don't drop the type tag (`specific dates:` / `blackout dates:`)** — it travels with the copy-paste and tells the user which OO slot the fragment belongs in.
- **Don't output a single merged code block.** Specific and blackout go in SEPARATE code blocks so each can be copied independently.
- **Don't include blackout dates where the field value is NULL** — NULL means data was missing, not that the condition failed.
- **Don't save output to a file — ever.** The two code blocks (specific + blackout) are the deliverable. The user copies them straight into OO; writing `.txt` files into the block folder just creates orphaned artifacts that drift out of sync with the latest filter thinking. In-conversation only. If the user explicitly asks for a file anyway, push back once (remind them the skill is copy-paste-first) before writing.
- **Don't forget the comma before AND after each date** — OO requires this format.
- **Don't hardcode field mappings** — use the entry_filter_groups CSV and threshold analysis field mapping.
- **Don't mix open and close dates** — default is open (start) dates. Only use close dates if the user explicitly asks.
- **Don't skip the per-filter summary metrics** — the user needs to verify each filter is producing the expected number of dates.

## Related Skills

- `alex-entry-filter-threshold-analysis` — Find optimal threshold before generating datelist
- `alex-entry-filter-heatmap` — Click-to-capture builds the filter expressions this skill consumes

## Notes

- The datelist format matches Option Omega's date import: comma-wrapped ISO dates. Usage as whitelist or blackout is determined by context — the label describes the criteria so the user knows how to apply it.
- When generating from a prediction model column, note that the model was trained in-sample. Flag this in the label (e.g., "in-sample" or "gen {date}").
- **Two-block output model.** Specific dates (whitelist, AND-intersection) and blackout dates (per-filter, OR-veto) are always emitted as separate code blocks. The user copies whichever block matches the OO slot they're populating. Dropping a single filter from the blackout side is a line delete; dropping one from the specific side requires regenerating the intersection, which the user can do by re-invoking the skill without that filter.
