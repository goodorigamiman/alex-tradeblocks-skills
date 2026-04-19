---
name: alex-create-datelist
description: 'Generate a filtered datelist from entry filter data for use in Option Omega. User specifies a field + threshold or custom criteria. Output is an OO-compatible ISO datelist with descriptive label, ready to copy-paste. Reads from shared entry_filter_data.csv when available. Usage as whitelist or blackout is contextual — the label provides the necessary info.

  '
compatibility: Reads `entry_filter_data.csv` directly — no MCP calls from this skill. Requires that upstream `dev-entry-filter-build-data` has already produced the CSV (which itself needs the TradeBlocks MCP server). Pure Python, standard library only.
metadata:
  author: alex-tradeblocks
  version: 1.8.1
---

# Create Datelist

Generate a copy-paste-ready datelist of trade dates that meet a specified filter condition. Output format matches Option Omega's ISO CSV import format. Whether the list is used as a whitelist or blackout is contextual — the descriptive label provides the necessary info.

**Reads the shared `entry_filter_data.csv`** produced by `alex-entry-filter-build-data`. This skill applies filters in Python over the CSV — no SQL, no MCP, no network. If the CSV is missing or stale, surface the error and point the user at `/alex-entry-filter-build-data` to produce a fresh one; do not attempt to build data from inside this skill.

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

| File | Role | Produced by |
|---|---|---|
| `{block}/alex-tradeblocks-ref/entry_filter_data.csv` | Trade-level data — one row per trade with `date_opened`, `rom_pct`, and every filter column. This skill's only data input. | `alex-entry-filter-build-data` |
| `{block}/alex-tradeblocks-ref/entry_filter_groups.*.csv` (optional) | Used only when the user supplies filter expressions by Short Name instead of CSV Column — the skill looks up the matching `CSV Column` here. Block-local preferred; falls back to `_shared/entry_filter_groups.default.csv` if the block copy isn't present. | `alex-entry-filter-build-data` / shared default |

The skill does NOT read SQL templates, market data, or any other shared file. If `entry_filter_data.csv` is missing, it fails fast and defers to `alex-entry-filter-build-data`.

## Prerequisites

- `entry_filter_data.csv` exists in the target block's `alex-tradeblocks-ref/` folder. If missing, run `/alex-entry-filter-build-data BLOCK_ID` to produce it (that skill is what needs MCP + DuckDB; this one does not).
- Python 3 standard library (no extra packages).

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

1. Check if `{block_folder}/alex-tradeblocks-ref/entry_filter_data.csv` exists.
2. **If it exists:** read it. Verify every filter's CSV column is present in the header. Report: "Using filter data ({n} trades, coverage {date_min} → {date_max})."
3. **If it does NOT exist:** stop and surface: *"entry_filter_data.csv is missing for BLOCK_ID. Run `/alex-entry-filter-build-data BLOCK_ID` to produce it, then re-invoke this skill."* Do not attempt to build data from within this skill.
4. **If a requested filter's column is not in the CSV header:** stop and report the missing column. The user needs to add it to the groups CSV and re-run build-data. This skill never falls back to SQL.

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

1. **Skill version line** — `alex-create-datelist v{version} · gen {data_max_YYYYMMDD} (last date_opened in entry_filter_data.csv)`. Self-identifies the output if pasted elsewhere.
2. **Table 1 — Baseline Impact** (each filter vs the full sample)
3. **Table 2 — Marginal Impact** (each filter's contribution to the AND set)
4. **Code block — Specific Dates** (whitelist; single label + single dates line)
5. **Code block — Blackout Dates** (one label + dates line per filter, blank line between filters)

The two tables are the shared canonical layout defined below under **Canonical Tables**. The two code blocks use the label format defined in Step 5. Each section below specifies exactly one of these five outputs; nothing is implied or optional.

---

**Detail — Code block: Specific Dates (whitelist).** Exactly one label line + one dates line, no blank line between them:

```
specific dates: {f1} + {f2} + ... gen YYYYMMDD.
,{date1}, ,{date2}, ...
```

**Detail — Code block: Blackout Dates (per filter).** One label + dates line per filter. Label immediately followed by its dates line (no blank between them). A single blank line separates one filter from the next:

```
blackout dates: {f1} gen YYYYMMDD.
,{date1}, ,{date2}, ...

blackout dates: {f2} gen YYYYMMDD.
,{date1}, ,{date2}, ...

blackout dates: {f3} gen YYYYMMDD.
,{date1}, ,{date2}, ...
```

Dates may repeat across blackout rows — that's expected (each filter blacks out independently).

---

## Canonical Tables (shared with alex-entry-filter-analysis)

Both tables precede the code blocks in the fixed order. Both use the same compressed column set so a reader scans them the same way. The spec here is the shared source of truth for `alex-entry-filter-analysis` as well — update both skills together if this section changes.

**Columns — compressed labels, fixed order. Baseline Impact has 10 columns; Marginal Impact has 11 (adds `N-1` at position 2, shifting everything after it by 1).**

| # (Baseline) | # (Marginal) | Column label | Contents | Formatting |
|---:|---:|---|---|---|
| 1 | 1 | `Filter` | Filter expression verbatim (or the baseline/AND label relevant to the table) | First and last rows **bold** |
| — | 2 | `N-1` | **Marginal only.** Size of the pool the filter operates on — all trades passing the OTHER N−1 filters | Integer; anchor row = `—` |
| 2 | 3 | `Keep` | Count of trades passing the filter (or in the AND set, for Marginal Impact) | Integer, right-aligned |
| 3 | 4 | `Out` | Count of trades non-null on the filter but excluded by it | Integer, right-aligned |
| 4 | 5 | `%` | Baseline: `Keep / Total × 100`; Marginal: `Keep / N-1 × 100` | `XX.X%`, right-aligned |
| 5 | 6 | `Net ROR` | Net ROR of the row's subset as % of baseline Net ROR | `XX.X%`, right-aligned |
| 6 | 7 | `+pts` | Delta of `Net ROR` vs the table's anchor row, in pp | `+X.X pp` / `-X.X pp`; anchor row = `—` |
| 7 | 8 | `Avg ROR` | Mean `rom_pct` across the row's subset | `XX.XX%`, right-aligned |
| 8 | 9 | `+pts` | Delta of `Avg ROR` vs the table's anchor row, in pp | `+X.XX pp` / `-X.XX pp`; anchor row = `—` |
| 9 | 10 | `WR` | Win rate of the row's subset | `XX.X%`, right-aligned |
| 10 | 11 | `+pts` | Delta of `WR` vs the table's anchor row, in pp | `+X.XX pp` / `-X.XX pp`; anchor row = `—` |

The three `+pts` columns are deliberately unqualified in their headers — column order pairs each `+pts` with the metric immediately to its left (Net ROR / Avg ROR / WR). This keeps each table narrow enough to scan at a glance.

**Per-table anchor (what "anchor row" means):**

| Table | Anchor row label | Anchor row values | +pts = ? |
|---|---|---|---|
| Baseline Impact | `All Trades (baseline)` | Keep=total, Out=0, %=100.0%, Net ROR=100.0%, Avg ROR=baseline avg, WR=baseline WR | `(filter row value) − (baseline value)` in absolute pp |
| Marginal Impact | `All N filters (AND set)` | N-1=`—`, Keep=N∩, Out=total−N∩, %=N∩/total, Net ROR=full AND Net %, Avg ROR=full AND avg, WR=full AND WR | `(full AND value) − (N-1 value)` in absolute pp |

All three `+pts` columns in both tables are **absolute pp deltas** — no ratios, no mixed framings. The only difference between tables is which row the delta is measured against.

**Why both `%` and `Net ROR` (plus their bumps):** a filter's quality can't be read from one number alone. `%` shows how selective the filter is (share of sample kept). `Net ROR` shows how much of the baseline's total edge survives — crucial for detecting filters that keep many trades but drop net edge, or filters that trim few trades but preserve nearly all edge. Pairing each metric with its `+pts` bump makes deltas unmistakable; a "free" filter in the Baseline Impact table has `Net ROR +pts > 0` AND `Avg ROR +pts > 0` simultaneously.

---

### Table 1 — Baseline Impact

**Anchor row:** `All Trades (baseline)`. All `+pts` deltas in this table are measured vs baseline.

**Row order (fixed):**

1. **`All Trades (baseline)`** — Keep = total, Out = 0, % = 100.0%, Net ROR = 100.0%, Avg ROR = baseline avg, WR = baseline WR, all `+pts` = `—`.
2. One row per user-supplied filter, in the order the user listed them.
3. **`All AND (specific dates)`** — the intersection row matching the Specific Dates code block.

Template (values are placeholders):

```
Baseline Impact

| Filter | Keep | Out | % | Net ROR | +pts | Avg ROR | +pts | WR | +pts |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **All Trades (baseline)** | Nₜ | 0 | 100.0% | 100.0% | — | B.BB% | — | W.W% | — |
| {f1} | N₁ | K₁ | T₁% | R₁% | ±ΔR₁ | A₁% | ±ΔA₁ | W₁% | ±ΔW₁ |
| … | … | … | … | … | … | … | … | … | … |
| **All AND (specific dates)** | N∩ | B∪ | T∩% | R∩% | ±ΔR∩ | A∩% | ±ΔA∩ | W∩% | ±ΔW∩ |
```

Every filter row reads as "what this filter does relative to doing nothing." The AND row describes the specific-dates whitelist (what actually runs).

---

### Table 2 — Marginal Impact

**Anchor row:** `All N filters (AND set)` — same intersection as the last row of Baseline Impact, shown with absolute/baseline-relative values for reference.

**Filter rows:** each one is labelled `Marginal: {filter expression}`. The `Marginal:` prefix is mandatory — it distinguishes the row from the Baseline Impact table's same-named filter row and signals "this is the filter's contribution to the AND set, NOT the result of dropping it." Each row shows **what that filter does when applied to the subset that already passes the OTHER (N-1) filters** — i.e. its *marginal contribution* to the final AND set.

**Row order (fixed):**

1. **`All N filters (AND set)`** — anchor. Columns show absolute numbers:
   - Keep = N∩, Out = total − N∩, % = N∩ / total × 100
   - Net ROR = N∩'s sum-of-ROM as % of baseline Net ROR
   - Avg ROR = N∩'s mean ROM, WR = N∩'s win rate
   - All three `+pts` columns = `—`
2. One row per filter, in the user-supplied order.

**Marginal Impact uses 11 columns** (one more than Baseline Impact): the extra `N-1` column sits immediately after `Filter` and makes the row's arithmetic self-verifying (`N-1 = Keep + Out`).

**Column semantics for filter rows — ALL main columns show the landing (full AND) value, ALL +pts columns show the absolute pp delta vs the N-1 pool.** This makes every row read the same way: "the N-1 pool had X; adding this filter took us to the landing value Y; the delta Y−X is in the +pts column."

For each filter X, let `S_{N-1}` be the subset of trades that pass the OTHER N−1 filters, and `S_N` = full AND set.

| Column | Filter-row value | What it means |
|---|---|---|
| `N-1` | `|S_{N-1}|` | Size of the pool available to X — the subset of trades that pass every filter EXCEPT X. Exactly equals `Keep + Out`. |
| `Keep` | `|S_N|` (constant across filter rows = N∩) | Landing trade count after X is applied to the N-1 pool. |
| `Out` | `|S_{N-1}| − |S_N|` | How many trades X **additionally excludes** from the N-1 pool. Zero means X removes nothing the other filters didn't already catch (redundant). |
| `%` | `|S_N| / |S_{N-1}| × 100` | X's passthrough rate on the N-1 pool. 100% = redundant; lower = more selective. |
| `Net ROR` | `Net_ROR(S_N) / baseline_Net_ROR × 100` (constant across filter rows = full AND's retention of baseline) | Landing Net ROR as % of baseline. |
| `Net ROR +pts` | `(Net ROR of S_N, as % of baseline) − (Net ROR of S_{N-1}, as % of baseline)` | Absolute pp change in baseline-retention when X is added to the N-1 pool. Negative = X costs retention; positive = X *improves* retention (rare; signals "free" filter). |
| `Avg ROR` | `Avg_ROR(S_N)` (constant = full AND's avg) | Landing per-trade mean ROM. |
| `Avg ROR +pts` | `Avg_ROR(S_N) − Avg_ROR(S_{N-1})` | Absolute pp lift in per-trade edge from adding X. |
| `WR` | `WR(S_N)` (constant = full AND's WR) | Landing win rate. |
| `WR +pts` | `WR(S_N) − WR(S_{N-1})` | Absolute pp lift in WR from adding X. |

**Design pattern:** `Keep`, `Net ROR`, `Avg ROR`, and `WR` are all constant across Marginal filter rows — they're the landing values every row ends at (the full AND). The informative columns that *vary* per filter are `N-1` (size of the pool the filter operates on), `Out` (marginal exclusions), `%` (passthrough rate), and all three `+pts` columns (pre→post deltas). This makes all three `+pts` columns mean the same thing — an absolute pp delta between the N-1 pool's value and the landing value — so they can be read with a single mental model.

For the **anchor row** (All N filters AND set), `N-1` is `—` because the anchor doesn't exclude any filter — it's the full intersection. `Keep`, `Net ROR`, `Avg ROR`, `WR` show the same landing values as the filter rows; all three `+pts` columns show `—` because the anchor has no "before" state.

**Arithmetic check:** every filter row satisfies `N-1 = Keep + Out`. If a reader sees a mismatch, something went wrong in the computation.

**Sign-convention reading:**

- **`Out = 0` and all `+pts = 0`** → X is fully redundant inside this AND set (every trade X would exclude was already excluded by the other filters). Worth keeping in the blackout slot as a safety net against filter-set changes, but doing no incremental work here.
- **`Net ROR +pts > 0`** → X actually *improves* Net ROR retention from the N-1 pool (rare but powerful — X removes net-negative trades the other filters missed).
- **`Avg ROR +pts > 0`** → X concentrates per-trade edge (typical for a working filter).

Template:

```
Marginal Impact — each row shows the filter's effect on the subset that already passes the OTHER filters.

| Filter | N-1 | Keep | Out | % | Net ROR | +pts | Avg ROR | +pts | WR | +pts |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **All N filters (AND set)** | — | N∩ | T−N∩ | T∩% | R∩% | — | A∩% | — | W∩% | — |
| Marginal: {f1} | P₁ | N∩ | O₁ | Q₁% | M₁% | ±ΔM₁ | A∩% | ±ΔA₁ | W∩% | ±ΔW₁ |
| Marginal: {f2} | P₂ | N∩ | O₂ | Q₂% | M₂% | ±ΔM₂ | A∩% | ±ΔA₂ | W∩% | ±ΔW₂ |
| … | … | … | … | … | … | … | … | … | … | … |
```

Notice `Keep`, `Net ROR`, `Avg ROR`, and `WR` are ALL constant across filter rows — they're the landing values every filter row ends at (the full AND set). The informative columns that *vary* per filter are `N-1` (the pool size), `Out` (marginal excludes), `%` (passthrough rate), and all three `+pts` columns (each reporting the absolute pp delta between the N-1 pool's value and the landing value). `N-1 = Keep + Out` is the arithmetic consistency check.

**How to read the two tables together:** Baseline Impact answers "what does each filter do on its own?" Marginal Impact answers "what does each filter contribute to the set we're actually shipping?" A filter can look weak in Baseline Impact but be critical in Marginal Impact (its contribution only visible in combination), and vice versa. Both views are needed before accepting a shortlist.

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

- `alex-entry-filter-analysis` — one-shot orchestrator that runs the full pipeline and typically invokes this skill as its final step (Step 9 of that skill's Process). Use it when you want the recommended filter list built for you; come here directly when you already know the filters you want.
- `alex-entry-filter-threshold-analysis` — single-filter deep dive. Use to find a good threshold for one filter before adding it to a datelist.
- `alex-entry-filter-heatmap` — click-to-capture selections panel produces the exact filter expressions this skill consumes (copy from heatmap → paste here).
- `alex-entry-filter-build-data` — upstream. Produces the `entry_filter_data.csv` this skill reads. Required before this skill can run.

## Notes

- The datelist format matches Option Omega's date import: comma-wrapped ISO dates. Usage as whitelist or blackout is determined by context — the label describes the criteria so the user knows how to apply it.
- When generating from a prediction model column, note that the model was trained in-sample. Flag this in the label (e.g., "in-sample" or "gen {date}").
- **Two-block output model.** Specific dates (whitelist, AND-intersection) and blackout dates (per-filter, OR-veto) are always emitted as separate code blocks. The user copies whichever block matches the OO slot they're populating. Dropping a single filter from the blackout side is a line delete; dropping one from the specific side requires regenerating the intersection, which the user can do by re-invoking the skill without that filter.
