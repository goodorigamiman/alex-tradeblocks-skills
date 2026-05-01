---
name: alex-create-datelist
description: >
  Generate a filtered datelist from entry filter data for use in Option Omega.
  User specifies a field + threshold or custom criteria. Output is an OO-compatible ISO datelist
  with descriptive label, ready to copy-paste. Reads from shared entry_filter_data.csv when available.
  Usage as whitelist or blackout is contextual — the label provides the necessary info.
compatibility: Reads `entry_filter_data.csv` directly — no MCP calls from this skill. Requires that upstream `alex-entry-filter-build-data` has already produced the CSV (which itself needs the TradeBlocks MCP server). Pure Python, standard library only.
metadata:
  author: alex-tradeblocks
  version: "1.10.2"
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
| `{block}/alex-tradeblocks-ref/filter_run_log.csv` | **Append-only audit log** — one row per simulation scenario (baseline + filter_set). Written by this skill at the end of every invocation. Read back for recall queries ("what was my highest MAR filter yesterday?"). See Step 8 for schema and lifecycle. | this skill (Step 8) |

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

### Step 4.5: Compute Portfolio Simulation (Table 3)

Simulate the equity curve under OO's sizing model for four scenarios:

1. **Baseline (full history)** — every trade in the block, in chronological order.
2. **Filtered (full history)** — trades where ALL filter conditions pass.
3. **Baseline (last period)** — every trade in the last-period window.
4. **Filtered (last period)** — filtered trades in the last-period window.

**Last-period window sizing:**

- Compute `total_days = (max_date - min_date).days` for the full block.
- If `total_days >= 365` → `window_days = 365`.
- Else → `window_days = total_days // 2` (floor-half of available history).
- Boundary = `max_date - window_days`. Include every trade with `date_opened >= boundary`.

**Simulation loop (identical across all four scenarios except trade subset):**

```python
# Defaults — user may override via conversation
initial_nlv = 10_000_000
allocation_pct = 0.20
min_contracts = 10

nlv = initial_nlv
peak = nlv
max_dd_pct = 0
trade_returns = []

for trade in sorted_trades:  # chronological
    capital = allocation_pct * nlv
    contracts = max(floor(capital / trade.margin_per_contract), min_contracts)
    pl = trade.pl_per_contract * contracts
    trade_returns.append(pl / nlv)  # fractional return vs pre-trade NLV
    nlv += pl
    peak = max(peak, nlv)
    max_dd_pct = max(max_dd_pct, (peak - nlv) / peak * 100)
```

Then compute the row values:
- `Period = first_date → last_date` (of the simulated subset)
- `Final NLV = nlv`
- `CAGR % = ((nlv / initial_nlv)^(1/years) − 1) × 100`, where `years = (last_date − first_date).days / 365.25`
- `Max DD % = max_dd_pct`
- `Sharpe = mean(trade_returns) × periods_per_year / (std(trade_returns) × √periods_per_year)`, `periods_per_year = len(trade_returns) / years`
- `Sortino = mean(trade_returns) × periods_per_year / (√(Σ r² / n_neg) × √periods_per_year)` for negative returns only
- `MAR = CAGR / Max DD`
- `Avg ROR % = mean(rom_pct)` over the simulated subset — NOT derived from the equity curve, so this value matches the per-trade Avg ROR in Tables 1/2 and carries the same meaning.
- `Win Rate % = (sum(pl > 0) / len) × 100`

See the Table 3 section under Canonical Tables for the column/row layout and the caveats on Sharpe/Sortino frequency.

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
4. **Table 3 — Portfolio Simulation** (4-column: baseline vs filtered × full-history vs last-period). OO-style portfolio stats (CAGR, MDD, Sharpe, Sortino, MAR, Avg ROR, Win Rate) computed by simulating the equity curve under a fixed sizing model.
5. **Code block — Specific Dates** (whitelist; single label + single dates line)
6. **Code block — Blackout Dates** (one label + dates line per filter, blank line between filters)
7. **Log-status line** — one line at the very end: `Logged N row(s) → filter_run_log.csv (total: M rows)`. Written after Step 8 executes. N is 1 (filter_set only, unchanged baseline) or 2 (baseline + filter_set).

The three tables are the shared canonical layout defined below under **Canonical Tables**. The two code blocks use the label format defined in Step 5. Each section below specifies exactly one of these seven outputs; nothing is implied or optional.

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
| 5 | 6 | `Net ROR` | **Absolute P/L retention** = `sum(pl_kept) / sum(pl_baseline) * 100`. NOT a per-trade Net ROR ratio. See "Net ROR retention — the ONLY definition" in alex-entry-filter-analysis SKILL.md. | `XX.X%`, right-aligned |
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

---

### Table 3 — Portfolio Simulation (4-column)

**Purpose:** the Baseline and Marginal tables operate at the per-trade level and answer "does this filter pick better trades?". Table 3 operates at the portfolio level and answers "what happens to the equity curve, drawdown, and risk-adjusted return if I ship this filter set?". Portfolio metrics (CAGR, MDD, Sharpe, Sortino, MAR) depend on trade sequence and position sizing — they can't be read from per-trade averages alone.

**Emitted between Table 2 (Marginal Impact) and the Specific Dates code block.** Four fixed columns, ten fixed rows. No variance based on filter set — the structure is the same every run so the reader can scan it the same way.

**Simulation model — defaults:**

| Parameter | Default | Rationale |
|---|---|---|
| Initial NLV | `$10,000,000` | Large-account scale; 10-lot minimum rarely binds at this size. |
| Allocation | `20%` per trade | Conservative on a portfolio that would allocate 45% in a single-strategy backtest — lets the user see the stats at a sizing that leaves room for a multi-strategy portfolio. |
| Minimum contracts per trade | `10` | Ensures smooth scaling across the full history and prevents the sim from placing fractional / zero positions in the early-NLV period. |
| Contracts calculation | `max(floor(allocation × NLV / margin_per_contract), min_contracts)` | Matches OO's position-sizing logic (allocation-capped integer contracts, floored by margin requirement). |

**User can override** via conversation ("use 30% allocation", "start with $5M", "drop the 10-lot floor") — the defaults are a starting point, not fixed. If the user overrides, call out the override in a one-line note under the table.

**Windowing for the last-period columns:**

1. If the block's backtest covers **≥ 365 days**, the last-period window is the **last 365 days** (inclusive of the final trade date).
2. If the block covers **< 365 days**, use **half the available history** (by calendar days, not trade count). Examples:
   - 30-day backtest → last 15 days
   - 90-day backtest → last 45 days
   - 6-month backtest → last 3 months
3. Compute the window boundary as `max_date - window_days`, then include every trade with `date_opened >= boundary`.

The last-period window is applied to **both** the Baseline and Filtered simulations, giving a fair apples-to-apples view of recent behavior. The windowed simulations start from the same initial NLV (not from whatever NLV the full-history sim ended at) so the two periods can be compared side-by-side in absolute-return terms.

**Columns (fixed, in order):**

| # | Column label | Contents |
|---:|---|---|
| 1 | `Metric` | Row name from the fixed row list below |
| 2 | `Baseline (full history)` | Simulation over ALL trades in the block |
| 3 | `Filtered (full history)` | Simulation over the AND-intersection of the user's filter set — same trades as the Specific Dates code block |
| 4 | `Baseline (last N days)` | Full-history baseline restricted to the last-period window |
| 5 | `Filtered (last N days)` | Filtered set restricted to the last-period window |

The column headers MUST list the window size explicitly, e.g. `Baseline (last 365d)` / `Filtered (last 365d)`, so the reader never has to infer what "last period" means.

**Rows (fixed, in order):**

| # | Row label | Contents / formula | Formatting |
|---:|---|---|---|
| 1 | `Period` | Date range spanning the column's simulation (`YYYY-MM-DD → YYYY-MM-DD`) | String |
| 2 | `Trades` | Count of trades in the simulation | Integer |
| 3 | `Trades/year` | `Trades / Years` | `XX.X` |
| 4 | `Final NLV` | Ending equity | `$X,XXX,XXX` |
| 5 | `CAGR %` | `(Final / Initial)^(1/years) − 1` × 100 | `XX.XX%` |
| 6 | `Max DD %` | Max peak-to-trough decline in the equity curve, % of peak | `XX.XX%` |
| 7 | `Sharpe (trade-freq)` | `mean(trade_returns) × periods_per_year / (std(trade_returns) × √(periods_per_year))` where `periods_per_year = trade_count / years`. NOTE: **computed from per-trade returns**, not daily NLV returns. OO's Sharpe from the same data will be ~√(252 / trades_per_year) ≈ 2.5× higher for a weekly-frequency strategy. Absolute values therefore don't match OO's reported Sharpe — they scale consistently so cross-column comparisons are apples-to-apples. | `X.XX` |
| 8 | `Sortino (trade-freq)` | Same annualization as Sharpe but denominator uses only negative trade returns (`√(Σ r² / n)` for `r < 0`). | `X.XX` |
| 9 | `MAR` | `CAGR / Max DD` — risk-adjusted return ratio | `X.XX` |
| 10 | `Avg ROR %` | Mean `rom_pct` across the simulation's trades (NOT derived from the equity curve — matches the per-trade Avg ROR from Tables 1/2 so a reader can trust the value carries the same meaning). | `X.XX%` |
| 11 | `Win Rate %` | `trades_with_pl > 0 / trades × 100` | `XX.X%` |

**Row-label formatting note:** the `(trade-freq)` tag on Sharpe and Sortino is **mandatory** — it signals that the annualization uses trade frequency (weekly for most strategies here), not daily bars. Without that tag, a reader comparing to OO's `get_statistics` output will see a mismatch and assume a bug.

**Template:**

```
Portfolio Simulation — $10M initial · 20% allocation · 10-lot min

| Metric | Baseline (full history) | Filtered (full history) | Baseline (last 365d) | Filtered (last 365d) |
|---|---:|---:|---:|---:|
| Period | {start} → {end} | {start} → {end} | {start} → {end} | {start} → {end} |
| Trades | {N} | {N} | {N} | {N} |
| Trades/year | {X.X} | {X.X} | {X.X} | {X.X} |
| Final NLV | ${N:,} | ${N:,} | ${N:,} | ${N:,} |
| CAGR % | XX.XX% | XX.XX% | XX.XX% | XX.XX% |
| Max DD % | -XX.XX% | -XX.XX% | -XX.XX% | -XX.XX% |
| Sharpe (trade-freq) | X.XX | X.XX | X.XX | X.XX |
| Sortino (trade-freq) | X.XX | X.XX | X.XX | X.XX |
| MAR | X.XX | X.XX | X.XX | X.XX |
| Avg ROR % | X.XX% | X.XX% | X.XX% | X.XX% |
| Win Rate % | XX.X% | XX.X% | XX.X% | XX.X% |
```

The `$10M / 20% / 10-lot` sub-heading on the table is **required** — it tells the reader the simulation assumptions up front, and any user-supplied override changes the values in that header line.

**What this table tells you that the per-trade tables don't:**

- Whether the filter's edge survives **compounding and sequencing** (a filter that picks great trades in clusters may look better in per-trade averages than it actually does for portfolio growth).
- Whether the filter's **drawdown profile** improves with use (per-trade tables can't see drawdown — only the equity curve can).
- Whether the **last-period out-of-sample window** confirms the full-history result (if full-history Sharpe is 1.9 but last-period Sharpe is 0.6, the filter's edge has weakened and you should consider either retuning or accepting the reduced forward expectation).

**Sim caveats — include a short note under the table when relevant:**

- Sharpe/Sortino are trade-frequency values — noted above in the row semantics.
- Simulation ignores commissions and slippage (uses `pl_per_contract` which is pre-fee). OO's reported P/L is net of fees — actual CAGR will be ~0.3-0.5 pp lower per lot in realistic execution conditions.
- Simulation assumes no trade overlap — correct for weekly-entry strategies like SlimP but must be flagged for strategies with concurrent positions.

### Step 7: Offer Inverse

Offer: "Want the inverse of any individual filter (swap blackout ↔ keep)?"

### Step 8: Append to `filter_run_log.csv`

Every `/alex-create-datelist` invocation writes one or two rows to the block's
append-only filter-run log. This is the skill's **only persisted audit
artifact** — it's how the user backs up historical filter sets and how future
runs answer recall questions like "what was my highest MAR filter yesterday?"

**File path:** `{block}/alex-tradeblocks-ref/filter_run_log.csv`

**Lifecycle:** append-only. First invocation on a block creates the file with
the header row. Every subsequent invocation appends new rows at the end. The
log is never rewritten by the skill; if a row is wrong, the user hand-edits
it or re-runs the scenario to produce a corrected new row.

**Encoding:** UTF-8 with BOM (per project CSV rule in CLAUDE.md).

#### Schema (29 columns)

The same schema serves both `baseline` and `filter_set` rows — they differ
only in `row_type`, `filter_expressions`, and which trade subset populates
the `fh_*` / `lp_*` metrics.

| Column | Example | Notes |
|---|---|---|
| `timestamp` | `2026-04-20T14:35:02` | ISO local time, row-write time |
| `row_type` | `baseline` / `filter_set` | |
| `filter_expressions` | `RSI_14 <= 67.05; SLR >= 0.513` | `;`-joined (semicolon + space); blank for baseline |
| `n_filters` | `0` / `2` | |
| `source_trade_start` | `2018-01-22` | Earliest trade in the full source data |
| `source_trade_end` | `2026-04-13` | Latest trade in the full source data |
| `source_n_trades` | `333` | Full source count (baseline-change detector) |
| `initial_nlv` | `10000000` | Sim param |
| `alloc_pct` | `0.20` | Sim param |
| `min_lots` | `10` | Sim param |
| `last_period_days` | `365` | Window for last-period metrics |
| `fh_period_start` / `fh_period_end` | `2018-02-05` / `2026-04-13` | Subset that was simulated. For `baseline` row = full history. For `filter_set` row = filtered AND subset (same as Specific Dates code block). |
| `fh_n_trades` | `249` | |
| `fh_trades_per_year` | `30.4` | |
| `fh_final_nlv` | `144770017` | |
| `fh_cagr_pct` | `38.62` | |
| `fh_max_dd_pct` | `12.24` | |
| `fh_sharpe` | `1.91` | trade-freq |
| `fh_sortino` | `3.44` | trade-freq |
| `fh_mar` | `3.16` | |
| `fh_avg_ror_pct` | `5.66` | |
| `fh_win_rate_pct` | `58.2` | |
| `lp_period_start` / `lp_period_end` | `2025-04-21` / `2026-04-13` | Last-period slice of the same subset |
| `lp_n_trades` | `34` | |
| `lp_cagr_pct` / `lp_max_dd_pct` / `lp_sharpe` / `lp_sortino` / `lp_mar` / `lp_avg_ror_pct` / `lp_win_rate_pct` | …as above | Last-period metrics, same definitions |

Numeric formatting: `%.2f` for percentages and ratios, `%.1f` for
`trades_per_year` / `win_rate_pct`, integer for counts and NLV. Consistent
formatting makes later CSV sorts and filters work without type coercion.

#### Run flow

After Table 3 has been computed and the user has been offered the inverse
(Step 7), but **before** the conversation turn ends:

1. **Read the existing log** (if any). If the file doesn't exist, jump to
   step 3 with `log_rows = []`.
2. **Baseline-change detection.** Scan for the latest `row_type=baseline`
   row. If any of `source_trade_start`, `source_trade_end`, or
   `source_n_trades` differ from the current run, mark "new baseline
   needed". If no baseline row exists yet (empty log), also mark "new
   baseline needed".
3. **Write header** if the file doesn't exist yet. 29-column header row in
   schema order.
4. **Append a baseline row** if step 2 marked "new baseline needed". This
   row simulates over ALL trades in the current source data (not just the
   filtered set) and carries all `fh_*` / `lp_*` metrics from that
   unfiltered simulation.
5. **Always append a filter_set row** with the user's current filter
   expressions and the filtered-subset metrics — even if the filter
   expressions exactly match a prior row. The timestamp differs; the user
   wants run-frequency history preserved.

#### Silent-write — don't spam the conversation

The skill writes the log in a single line of Python without rendering the
rows in chat. Mention the write once per invocation as a one-line status
note at the very end of the output, after the datelist code blocks:

> `Logged 2 row(s) → filter_run_log.csv (total: N rows)`

or when only a filter_set row was written:

> `Logged 1 row → filter_run_log.csv (total: N rows)`

## Recall — querying the log for historical lookups

When the user asks a natural-language question about prior filter sets on a
block, **read the log and answer from it** rather than re-running
simulations. The log is the canonical history.

**Default comparison scope: same-baseline only.** "Best MAR" questions
compare against filter_set rows whose `source_trade_end` matches the
current data's max date (or the user's most recent baseline row). This
keeps the comparison apples-to-apples. For questions that clearly span
baselines ("including older backtests", "across all history"), relax the
filter and call out the baseline difference in the response.

**Example queries:**

| User asks | Python one-liner |
|---|---|
| "What was my highest MAR filter set on this block yesterday?" | `df[(df.row_type=='filter_set') & (df.source_trade_end==current_end) & (df.timestamp.str.startswith('2026-04-19'))].nlargest(1, 'fh_mar')` |
| "Is this filter set my best MAR on the current data?" | `df[(df.row_type=='filter_set') & (df.source_trade_end==current_end)]['fh_mar'].max()` — then compare to current run's MAR |
| "Lowest-drawdown filter set on this block?" | `df[(df.row_type=='filter_set') & (df.source_trade_end==current_end)].nsmallest(1, 'fh_max_dd_pct')` |
| "What filter sets did I run last week?" | `df[(df.row_type=='filter_set') & df.timestamp.between('2026-04-13','2026-04-20')]` |
| "Across all backtests (ignore baseline changes), best MAR ever?" | `df[df.row_type=='filter_set'].nlargest(1, 'fh_mar')` — note the baseline context of the winner in the response |

The skill doesn't need a query DSL — pandas one-liners cover every recall
question seen so far. If a query requires something more complex, fall back
to inline Python against the CSV.

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
- **Don't save the datelist output to a file — ever.** The two code blocks (specific + blackout) are the deliverable. The user copies them straight into OO; writing `.txt` files into the block folder just creates orphaned artifacts that drift out of sync with the latest filter thinking. In-conversation only. If the user explicitly asks for a datelist file anyway, push back once (remind them the skill is copy-paste-first) before writing. **Exception:** `filter_run_log.csv` is explicit audit data (Step 8), not user-facing output — it is always appended, not a copy-paste deliverable, and the "push back" rule does NOT apply to it.
- **Don't forget the comma before AND after each date** — OO requires this format.
- **Don't hardcode field mappings** — use the entry_filter_groups CSV and threshold analysis field mapping.
- **Don't mix open and close dates** — default is open (start) dates. Only use close dates if the user explicitly asks.
- **Don't skip the per-filter summary metrics** — the user needs to verify each filter is producing the expected number of dates.
- **Don't label Table 3 Sharpe/Sortino as if they match OO.** The `(trade-freq)` tag on those row labels is mandatory. Computed Sharpe values will be ~√(252 / trades_per_year) smaller than OO's reported Sharpe (~2.5× smaller for weekly-frequency strategies). Cross-column comparisons inside Table 3 are apples-to-apples; cross-skill comparisons (Table 3 vs `get_statistics`) require the user to know the frequency-factor delta.
- **Don't change the Table 3 default sim params silently.** If the user overrides (e.g. "use 30% allocation"), echo the override in the table sub-heading (`Portfolio Simulation — $10M initial · 30% allocation · 10-lot min`) so the values in the table always tie back to a visible assumption set.
- **Don't compute the last-period window from trade count.** Always use calendar days (`max_date − window_days`). A dense trade stretch can skew a count-based window to the wrong period, and an empty stretch can lose the user's actual last period entirely.
- **Don't skip Table 3 when the block has < 30 days of history.** The half-data rule still applies (2 weeks of data → 1 week window), but flag it explicitly: "Last-period window is 7 days because total history is 14 days — low statistical weight." If there's literally only one trade in the window, report the single trade's P/L as informational and mark Sharpe / Sortino / MAR as `N/A`.
- **Don't edit or delete past rows in `filter_run_log.csv`.** The log is append-only and the recall workflow assumes immutable history. If a prior row has bad data, the user hand-edits the CSV directly (outside the skill) — the skill never rewrites rows. New rows with corrected values can always be appended by re-running the scenario.
- **Don't skip the log write when the user's filter set is experimental.** Every invocation logs — that's the whole point of "was this my best MAR yesterday?". If the user wants to exclude a run from history, they hand-delete the row afterward; the default is always-append.
- **Don't cross-baseline compare silently in recall queries.** The default scope is same-baseline (matching `source_trade_end`). If the user's question spans baselines, relax the scope AND explicitly note the baseline difference in the response (e.g. "best MAR was 3.92 on 2025-11-10, on a shorter backtest ending 2025-10-27 — 154 trades vs current 333").

## Related Skills

- `alex-entry-filter-analysis` — one-shot orchestrator that runs the full pipeline and typically invokes this skill as its final step (Step 9 of that skill's Process). Use it when you want the recommended filter list built for you; come here directly when you already know the filters you want.
- `alex-entry-filter-threshold-analysis` — single-filter deep dive. Use to find a good threshold for one filter before adding it to a datelist.
- `alex-entry-filter-heatmap` — click-to-capture selections panel produces the exact filter expressions this skill consumes (copy from heatmap → paste here).
- `alex-entry-filter-build-data` — upstream. Produces the `entry_filter_data.csv` this skill reads. Required before this skill can run.

## Notes

- The datelist format matches Option Omega's date import: comma-wrapped ISO dates. Usage as whitelist or blackout is determined by context — the label describes the criteria so the user knows how to apply it.
- When generating from a prediction model column, note that the model was trained in-sample. Flag this in the label (e.g., "in-sample" or "gen {date}").
- **Two-block output model.** Specific dates (whitelist, AND-intersection) and blackout dates (per-filter, OR-veto) are always emitted as separate code blocks. The user copies whichever block matches the OO slot they're populating. Dropping a single filter from the blackout side is a line delete; dropping one from the specific side requires regenerating the intersection, which the user can do by re-invoking the skill without that filter.
