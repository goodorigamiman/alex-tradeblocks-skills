---
name: alex-entry-filter-analysis
description: >
  One-shot orchestrator for entry-filter analysis on a block. Runs
  build-data → threshold-sweep → heatmap → threshold-analysis (for filters
  flagged in the groups CSV's "Threshold Analysis Default Report" column),
  then reads the result CSVs + correlations + groups metadata + a local
  preferences file to produce a baseline-anchored summary and a filter
  shortlist (≤2 per Entry Group) ready to feed to dev-create-datelist.
  Analysis is grounded in the generated reports; out-of-context insights
  surface as explicit gap warnings. Default metric AvgROR; AvgPCR only on
  explicit user request (and PCR output is exploratory — see README
  limitations). Cross-session learning via alex_entry_filter_analysis_preferences.md
  at TB root.
compatibility: Orchestrator only. No Python. Depends on four upstream
  entry-filter dev skills.
metadata:
  author: alex-tradeblocks
  version: "1.2.2"
---

# Entry Filter Analysis

Orchestrator + analyst + learner. One invocation runs the entire entry-filter pipeline on a block, interprets the result CSVs, and produces a baseline-anchored filter shortlist ready for `alex-create-datelist`. Claude is the executor — no Python; this skill is pure protocol.

## Purpose

Before this skill existed, producing a filter shortlist for a block required four separate invocations (build-data → threshold-sweep → heatmap + per-filter threshold-analysis) followed by manual interpretation of the heatmap HTML and sweep CSVs. This skill collapses that into one entry point with three distinct responsibilities:

1. **Orchestrator** — runs the four upstream skills in the right order and surfaces any failures with remediation pointers.
2. **Analyst** — reads the generated CSVs + correlations + groups + preferences and produces a structured recommendation (≤2 filters per Entry Group, baseline-anchored, correlation-deduped, confidence-gated).
3. **Learner** — on explicit user feedback, appends timestamped learnings to a scoped preferences file at the TB root. On subsequent runs, reads the file and applies matching scopes (Global / Block / Strategy-Type / Date-Range) to tune recommendations and surface caveats.

## Process

### Step 1 — Confirm the target block

If the block ID isn't already established in the conversation, call `list_blocks` and confirm with the user. The block ID equals the folder name under the TB root (e.g. `20250519 - QQQ DC 2:4 20d oM Lambo - No Filters`).

### Step 2 — Load preferences

Check for `$TB_ROOT/alex_entry_filter_analysis_preferences.md`.

**If it doesn't exist:** create it with the schema below (empty sections). Report "Preferences file created at first run — no learnings yet."

**If it exists:** read it. Identify applicable entries:

- **Global** — always applied.
- **By Block** — match the exact current block ID against section headers under `## By Block`.
- **By Strategy Type** — if the block has a synced `trade_profile.json` with a `structureType`, match that (case-insensitive, aliases like `DC` = `double_calendar`). If no profile or no `structureType`, skip strategy-type matching.
- **By Date Range** — each entry has a scope tag (`[YYYY-MM-DD, scope DATE]` or `[YYYY-MM-DD, scope START to END]`). Match against the block's trade date range; if any trade falls in the scope window, the entry applies.

Hold the applicable entries for Step 7's summary ("Preference reminders" section).

### Step 3 — Run upstream skills (build-data → sweep → heatmap)

In order:

1. `/alex-entry-filter-build-data BLOCK_ID` — creates `entry_filter_data.csv` (skill is idempotent; checks if CSV is current before rebuilding).
2. `/alex-entry-filter-threshold-sweep BLOCK_ID` — always runs. Writes `entry_filter_threshold_results.csv` and `entry_filter_categorical_results.csv`.
3. `/alex-entry-filter-heatmap BLOCK_ID` — renders `entry filter heatmap.html`. Announce the path.

On any non-zero exit, stop and surface the error + remediation pointer from that skill's SKILL.md.

### Step 4 — Resolve the TA-flagged filter list

Read the block's groups CSV (`{block}/alex-tradeblocks-ref/entry_filter_groups.*.csv`, or fall back to `_shared/entry_filter_groups.default.csv` if the block override doesn't exist). Filter to rows where the `Threshold Analysis Default Report` column equals `TRUE` (case-insensitive). Missing or blank values count as FALSE. Sort by `Index`.

This is the shortlist for Step 5's deep-dive reports.

### Step 5 — Run threshold-analysis per flagged filter

For each filter from Step 4, invoke `/alex-entry-filter-threshold-analysis BLOCK_ID "<Short Name>"`. Collect the output HTML paths. One HTML per flagged filter; if the user has many flagged filters, this step can take a while — announce progress.

### Step 6 — Load the result CSVs into context (metric-filtered)

Load:

| File | Rows to load | Notes |
|---|---|---|
| `entry_filter_threshold_results.csv` | `metric in ("AvgROR", "ThresholdROR")` by default | Skip AvgPCR/ThresholdPCR rows entirely unless PCR mode is active. |
| `entry_filter_categorical_results.csv` | `metric == "AvgROR"` by default | Skip AvgPCR rows entirely unless PCR mode is active. |
| `_shared/entry_filter_correlations.default.csv` | all rows | Small file; always fully loaded. |
| `entry_filter_groups.*.csv` | all rows | Already loaded in Step 4. |

**Rationale for metric isolation:** the sweep CSVs carry both AvgROR and AvgPCR versions of every cell. Loading both doubles the context volume with zero benefit when only one metric drives the analysis. Default AvgROR. Switch to AvgPCR only if the user explicitly says something like "analyze with PCR" or "use PCR instead" — and when you do, apply the inverse filter (skip AvgROR/ThresholdROR rows).

Also run a one-column read on `entry_filter_data.csv` for `Day_of_Week` — count unique values to drive the DoW gate in Step 7.

### Step 7 — Run the Analysis Protocol

Apply the Claude Analysis Guidance rules below. Produce the summary output described under "Output format."

### Step 8 — Stand by

Present the summary. Pause. Do NOT auto-invoke `/alex-create-datelist`.

The user will either:
1. Accept Claude's recommendation — "go with your picks" / "yes build the datelist" / similar.
2. Paste their own filter list (from clicking heatmap cells, or from their own interpretation of the reports).
3. Ask for drill-downs, substitutions, or a different metric.
4. Give feedback that triggers a learning save (see "Feedback capture" below).

### Step 9 — Hand off to datelist

On go-ahead, format the accepted filter expressions exactly as `alex-create-datelist` expects (e.g. `VIX_IVP <= 92.032`, `SLR >= 0.47`, `VIX_Close ∈ [13.34, 31.62]`, `Weeks_to_Holiday != 0`, `Gap_Filled == 1`). Invoke `/alex-create-datelist` with the list.

### Step 10 — Feedback capture (runs concurrently throughout Steps 7-9)

When the user pushes back, flags bad data, states a preference, or shares a durable insight, propose saving a learning. Specific trigger phrases to watch for:

- "That's wrong because…" / corrections of analysis or recommendations
- "This data point is bad" / "2023-03-13 had a glitch" / data quality flags
- "Always / never do X for this block" / durable block-level preference
- "For DC strategies in general…" / strategy-type insight
- "Remember this" / "save this" / "add this to preferences"

On any trigger:
1. Draft a one-sentence learning, dated today.
2. Ask the user which scope it applies to: **Global** (all analyses), **Block** (this block only), **Strategy Type** (match by trade profile), or **Date Range** (single date or start–end window).
3. For Date-Range: ask for the exact date(s) in the scope.
4. Confirm, then append to the preferences file under the right section. Never save without explicit scope + confirmation.

## Claude Analysis Guidance (locked rules)

### Net ROR retention — the ONLY definition (non-negotiable)

**"Net ROR retention" ALWAYS means absolute P/L retention, not a per-trade Net ROR ratio.** This is the single most important definition in the skill. Miss it and every `+pts Net ROR` number in the output is wrong by a factor of 2–5×.

**Formula — memorize this, do not deviate:**

```
Net ROR retention (%) = sum(pl_per_contract for kept trades) / sum(pl_per_contract for ALL trades) * 100
```

- Denominator is always the **baseline total P/L** across all trades in the block. Not the kept subset's total, not the margin-weighted anything.
- Numerator is the kept subset's total P/L.
- Bounded roughly at `[negative, ~110%]` in practice — can exceed 100% only when excluded trades have **negative** aggregate P/L (removing losers lifts retention above baseline).
- Values above ~150% are a **red flag** — you've almost certainly computed the wrong formula. Stop and check.

**What this is NOT:**

- ❌ `(sum_pl_kept / sum_margin_kept) / (sum_pl_base / sum_margin_base)` — this is a per-trade Net ROR **ratio**, not retention. Produces numbers like 300-400% for aggressive filters. **Do not compute this.**
- ❌ `avg_rom_kept / avg_rom_base` — similar trap, same wrong scale.
- ❌ Anything involving margin in the denominator.

**Where the sweep CSV sits:** the sweep's `max_net_ror` column and every `R_T` retention-target column use the absolute-retention formula above. When you compute retention for AND sets from raw trade data, use the SAME formula so downstream comparisons are apples-to-apples.

**Self-check before emitting any Baseline or Marginal Impact table:** pick the row with the highest `Net ROR` value. If it exceeds ~110%, re-derive from first principles: `sum_pl_kept / sum_pl_baseline`. If the number changes materially, your code is wrong — fix it before the table ships.

### Scope lock (non-negotiable)

Recommendations MUST be grounded in data actually present in the generated reports:

- **Allowed inputs**: `entry_filter_threshold_results.csv`, `entry_filter_categorical_results.csv`, `entry_filter_groups.*.csv`, `_shared/entry_filter_correlations.default.csv`, and the preferences file.
- **Disallowed inputs**: conversation context, prior sessions' memory, general knowledge of trading, academic papers, etc.

If the user mentions a concept (e.g. "skew slope matters" / "term structure bend") and there is no matching filter in the groups CSV, report it as a WARNING labelled "Context gap: {concept} referenced but no matching filter in groups CSV — cannot evaluate." Do NOT incorporate the concept into the recommendation.

### Metric isolation

- Load ONE metric per run. Default AvgROR.
- Never mix AvgROR and AvgPCR in the same analysis.
- When AvgROR is active: skip every sweep-CSV row where `metric in ("AvgPCR", "ThresholdPCR")`.
- PCR mode: only triggered by explicit user request. Flag PCR output as EXPLORATORY in the summary header (see README limitations).

### Preferences first

Before building the shortlist, explicitly apply the preferences loaded in Step 2:

- **Bad-data date entries** → exclude affected trades from sufficiency counts; warn in output with affected-trade count.
- **Validated-threshold entries** → weight the named threshold in the shortlist even if a stricter alternative surfaces.
- **Durable constraints** → shape candidate selection (e.g. "always outlier-trim VIX3M" biases toward extreme-boundary filters on VIX3M).

List every applied preference in the "Preference reminders" section of the summary. If none apply, say so explicitly so the user knows the file was checked.

### Confidence floor

Any filter subset with fewer than 10 trades in either In or Out column is LOW CONFIDENCE. Do not recommend unless no alternative exists in the same Entry Group — and when forced to, label the row explicitly.

### Outlier-boundary framing

Filters that trim only the extreme tails of the distribution (e.g. a `<=` at the 95th percentile, a `>=` at the 5th percentile) are PREFERRED when similar edge can be obtained at a less aggressive threshold. Rationale: extreme-trim filters are risk management against regime shift (they prevent trading into genuinely new market conditions), not overfits to mid-range bands.

When two candidate thresholds on the same filter both pass confidence + retention checks, and one is more extreme than the other, prefer the more extreme threshold unless the less-extreme one offers materially better avg-ROR lift AND net-ROM bump (both ≥ 1.5× better, not just one).

### Correlation discipline

Before finalizing the recommended set, cross-check every pair against `_shared/entry_filter_correlations.default.csv`.

- `|r| >= 0.95` — treat as near-identical. Never recommend both. Pick the one with stronger solo edge; note the other as "redundant, covered by {winner}."
- `|r| >= 0.85` — trigger a warning. Pick at most one of the pair; surface the other as "correlated with {winner}, dropped for set efficiency."
- Pairs not in the correlation matrix — flag as "correlation check skipped for {A} vs {B}; not in correlations CSV."

### Per-group cap

At most 2 filters per `Entry Group` in the final recommendation. If a group has more candidates, tie-break by:

1. Combined rank of avg-ROR lift + net-ROM bump (higher is better).
2. Trade count (prefer larger surviving subset, more robust).
3. Preference-weighted: a filter that matches a "validated threshold" preference entry wins ties.

If the user explicitly asks for more than 2 from a specific group, honor the request but warn that going beyond 2 increases correlation risk.

### Baseline-anchored metrics — TWO tables, canonical format

Every recommendation presents **two tables** using the same canonical layout as `alex-create-datelist`. The two skills share the format so the user sees the same tables in the same shape whether they invoke analysis (which shows recommendations) or datelist (which confirms the output just before generating the OO blocks). The spec below is the shared source of truth for both skills — update both together if it changes.

**Table 1 — Baseline Impact** (10 compressed columns). Anchor = `All Trades (baseline)`. Each filter row's `+pts` deltas are measured vs the baseline row.

```
Baseline Impact

| Filter | Keep | Out | % | Net ROR | +pts | Avg ROR | +pts | WR | +pts |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **All Trades (baseline)** | Nₜ | 0 | 100.0% | 100.0% | — | B.BB% | — | W.W% | — |
| {f1} | N₁ | K₁ | T₁% | R₁% | ±ΔR₁ | A₁% | ±ΔA₁ | W₁% | ±ΔW₁ |
| … | … | … | … | … | … | … | … | … | … |
| **All AND (specific dates)** | N∩ | B∪ | T∩% | R∩% | ±ΔR∩ | A∩% | ±ΔA∩ | W∩% | ±ΔW∩ |
```

**Table 2 — Marginal Impact** (11 compressed columns — adds `N-1` at position 2). Anchor = `All N filters (AND set)`. Each filter row shows the filter's effect on the N-1 subset that passes the OTHER filters.

```
Marginal Impact — each row shows the filter's effect on the subset that already passes the OTHER filters.

| Filter | N-1 | Keep | Out | % | Net ROR | +pts | Avg ROR | +pts | WR | +pts |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **All N filters (AND set)** | — | N∩ | T−N∩ | T∩% | R∩% | — | A∩% | — | W∩% | — |
| Marginal: {f1} | P₁ | N∩ | O₁ | Q₁% | M₁% | ±ΔM₁ | A∩% | ±ΔA₁ | W∩% | ±ΔW₁ |
| Marginal: {f2} | P₂ | N∩ | O₂ | Q₂% | M₂% | ±ΔM₂ | A∩% | ±ΔA₂ | W∩% | ±ΔW₂ |
| … | … | … | … | … | … | … | … | … | … | … |
```

**Column semantics (canonical — must match `alex-create-datelist` SKILL.md exactly):**

| Column | Baseline anchor row | Filter row (Baseline) | Filter row (Marginal) |
|---|---|---|---|
| `N-1` | — (not in Baseline table) | — (not in Baseline table) | size of the pool that passes all OTHER filters |
| `Keep` | total trades | trades passing this filter | full AND count (constant across Marginal filter rows) |
| `Out` | 0 | non-null trades failing this filter | trades this filter excludes from the N-1 pool |
| `%` | 100% (of total) | Keep / total | Keep / N-1 (passthrough rate on N-1 pool) |
| `Net ROR` | 100% | **absolute P/L retention** = `sum(pl_kept) / sum(pl_baseline) * 100` — see the locked "Net ROR retention" rule above | **full AND absolute P/L retention** (constant across Marginal rows) |
| `Net ROR +pts` | — | Net ROR − 100 (in absolute pp) | (full AND retention) − (N-1 retention) in absolute pp |
| `Avg ROR` | baseline avg | subset avg | full AND avg (constant) |
| `Avg ROR +pts` | — | subset avg − baseline avg | full AND avg − N-1 avg in absolute pp |
| `WR` | baseline WR | subset WR | full AND WR (constant) |
| `WR +pts` | — | subset WR − baseline WR | full AND WR − N-1 WR in absolute pp |

**Unified +pts reading:** all three `+pts` columns in both tables mean the same thing — an absolute pp delta between the row's anchor and the row's subject. In Baseline, anchor = All Trades, subject = filter's keep subset. In Marginal, anchor = N-1 pool for that filter, subject = full AND (landing state). No ratios or mixed framings.

**Consistency checks — run these before emitting either table:**

1. **Marginal row accounting:** every filter row must satisfy `N-1 = Keep + Out`. If it doesn't, the pool computation is wrong.
2. **Net ROR sanity:** no row's `Net ROR` should exceed ~110% unless excluded trades have a genuinely negative aggregate P/L. Values of 130%+ almost always mean the per-trade-ratio trap (see the locked "Net ROR retention" rule). Re-derive as `sum_pl_kept / sum_pl_baseline` and confirm before shipping.
3. **Baseline row always reads 100% Net ROR.** If your baseline row is showing something else, your formula is wrong.

**How to read the two tables together:** Baseline Impact answers "what does each filter do on its own?" Marginal Impact answers "what does each filter contribute to the set we're actually shipping?" A filter that reads strong in Baseline but shows `Out=0, +pts=0` in Marginal is redundant inside the AND set — its Baseline effect is driven by a correlated filter already in the set. See the Preferences file's Global learnings for more on interpreting Marginal=0 patterns.

**Row ordering (both tables):** filters appear in the order set by the groups CSV `Index` column. **Do not insert Entry Group headers, bold section rows, or any group-level dividers inside the tables** — headers add clutter and break the clean 10-column / 11-column grid readers scan. The Entry Group is still enforced by the per-group cap rule (≤2 filters per group in the final recommendation) but that rule shapes *selection*, not presentation. If a user asks "which group is this filter in?", refer them to the groups CSV or mention it in the Other-Interesting sidebar — not in the main table.

### Categorical: always probe holiday-week buckets

Check `entry_filter_categorical_results.csv` for rows where:
- `csv_column == "Weeks_to_Holiday"` AND `category_value == "0"`, and
- `csv_column == "Weeks_from_Holiday"` AND `category_value == "0"`.

For each, if the In-sample delta vs baseline is ≥ 2pp in either direction OR the net-bump (pct_baseline - pct_trades) is ≥ 2pp, surface as a candidate EXCLUSION filter (`!= 0`). Rationale: holiday-week trades often behave materially differently from normal-week trades and are a natural first-cut exclusion.

If the bucket exists but shows < 2pp deviation, emit "Holiday buckets checked, not material" so the user knows the check happened.

If the bucket has < 10 trades, fall to LOW CONFIDENCE handling.

### Categorical: Day-of-Week gate

Before recommending any DoW filter, check the unique `Day_of_Week` values in `entry_filter_data.csv` (Step 6's one-column read):

- **Unique count == 1** → SKIP all DoW analysis. Emit "Day-of-Week filters not meaningful — strategy trades a single day." Do not include any DoW row in the recommendation or sidebar.
- **Unique count > 1** → DoW filters are in scope; apply the standard candidate/correlation/confidence logic.

### Warning, never silent

Any issue detected during analysis surfaces as a labelled warning in the summary. Categories and examples:

- **context-gap** — user referenced a concept with no matching filter.
- **data-sufficiency** — filter subset below the 10-trade floor.
- **correlation** — high-r pair detected; one dropped from the set.
- **skipped-analysis** — DoW gate triggered, holiday bucket too sparse, etc.
- **preference-override** — a preference entry shaped the recommendation differently than the raw data would suggest.

Every warning has a fix pointer when one exists (e.g. "run build-data to refresh" or "edit preferences to remove stale entry").

### Feedback capture

See Step 10 above. Never auto-save; always ask for scope + confirmation.

## Output format

The structured summary Claude emits after Step 7. Section order is fixed: version header → Preference reminders → Run log → Warnings → **Baseline Impact table** → **Marginal Impact table** → Other-interesting sidebar → Next-step prompt.

```
alex-entry-filter-analysis v{version} · {block_id} · metric={AvgROR|AvgPCR} · gen {YYYYMMDD}

Preference reminders:
  [Global] …
  [Block] …
  [Strategy Type: {type}] …
  [Date Range: {scope}] … (N affected trades)
  (or "No applicable preferences — file checked.")

Run log:
  ✓ alex-entry-filter-build-data        (entry_filter_data.csv, 173 trades)
  ✓ alex-entry-filter-threshold-sweep   (816 continuous + 214 categorical rows)
  ✓ alex-entry-filter-heatmap           (entry filter heatmap.html)
  ✓ alex-entry-filter-threshold-analysis × 6  (SLR, VIX_IVP, …)

Warnings:
  [context-gap] …
  [data-sufficiency] …
  [correlation] …
  [skipped-analysis] Day-of-Week filters not meaningful — strategy trades a single day.
  [preference-override] …
  (or "No warnings.")

Baseline Impact (AvgROR, metric-isolated):

| Filter | Keep | Out | % | Net ROR | +pts | Avg ROR | +pts | WR | +pts |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **All Trades (baseline)** | Nₜ | 0 | 100.0% | 100.0% | — | B.BB% | — | W.W% | — |
| {f1} | N₁ | K₁ | T₁% | R₁% | ±ΔR₁ | A₁% | ±ΔA₁ | W₁% | ±ΔW₁ |
| {f2} | N₂ | K₂ | T₂% | R₂% | ±ΔR₂ | A₂% | ±ΔA₂ | W₂% | ±ΔW₂ |
| … | … | … | … | … | … | … | … | … | … |
| **All AND (specific dates)** | N∩ | B∪ | T∩% | R∩% | ±ΔR∩ | A∩% | ±ΔA∩ | W∩% | ±ΔW∩ |

(One row per filter in groups-CSV Index order. No Entry Group headers — tables stay flat.)

Marginal Impact (same AvgROR, each row = filter's effect on the N-1 subset):

| Filter | N-1 | Keep | Out | % | Net ROR | +pts | Avg ROR | +pts | WR | +pts |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **All N filters (AND set)** | — | N∩ | T−N∩ | T∩% | R∩% | — | A∩% | — | W∩% | — |
| Marginal: {f1} | P₁ | N∩ | O₁ | Q₁% | M₁% | ±ΔM₁ | A∩% | ±ΔA₁ | W∩% | ±ΔW₁ |
| Marginal: {f2} | P₂ | N∩ | O₂ | Q₂% | M₂% | ±ΔM₂ | A∩% | ±ΔA₂ | W∩% | ±ΔW₂ |

Other interesting but not recommended:
  • {filter} — strong solo but correlated r=0.91 with {winner}; covered.
  • {filter} — below confidence floor (8 trades in Out-group).
  • {filter} — lost per-group tie-break to {winner}.
  • {categorical filter} — Baseline showed strong edge but Marginal=0 inside the set; treated as
    correlated-driver artifact (see preferences file for the "Marginal=0 redundancy" rule).

Next step: ready to build a datelist with the recommended filters, or do you want
to swap any in/out first? Paste alternate picks if you used the heatmap click-capture.
```

## File Dependencies

| File | Role | Produced by |
|---|---|---|
| `{block}/alex-tradeblocks-ref/entry_filter_data.csv` | Trade-level data; Day_of_Week probe | `alex-entry-filter-build-data` |
| `{block}/alex-tradeblocks-ref/entry_filter_groups.*.csv` | Filter registry, `Threshold Analysis Default Report` flag | `alex-entry-filter-build-data` |
| `{block}/alex-tradeblocks-ref/entry_filter_threshold_results.csv` | Continuous sweep results + block baselines | `alex-entry-filter-threshold-sweep` |
| `{block}/alex-tradeblocks-ref/entry_filter_categorical_results.csv` | Binary + categorical In/Out stats | `alex-entry-filter-threshold-sweep` |
| `{block}/entry filter heatmap.html` | Visual reference; user may click-capture filters here | `alex-entry-filter-heatmap` |
| `{block}/entry filter threshold analysis {Short Name}.html` | Per-filter drill-down; one per TA-flagged filter | `alex-entry-filter-threshold-analysis` |
| `_shared/entry_filter_correlations.default.csv` | Pairwise r-correlations for redundancy checks | Shared reference (static) |
| `$TB_ROOT/alex_entry_filter_analysis_preferences.md` | Cross-session scoped learnings | This skill (append-only) |

## Prerequisites

- All four upstream dev skills installed:
  - `alex-entry-filter-build-data`
  - `alex-entry-filter-threshold-sweep`
  - `alex-entry-filter-heatmap`
  - `alex-entry-filter-threshold-analysis`
- `alex-create-datelist` installed (for hand-off in Step 9).
- Block has trade data loaded via MCP.

## CLI / Invocation

This skill has no CLI of its own. User invokes via `/alex-entry-filter-analysis` (optionally with block ID) and Claude orchestrates the upstream skills via their `/alex-*` slash commands.

## Preferences file — schema

Created at `$TB_ROOT/alex_entry_filter_analysis_preferences.md` on first run. Per the CLAUDE.md `alex_*` convention: skill-managed, user-editable, never auto-overwritten.

```markdown
---
schema_version: 1
---

# Entry Filter Analysis — Learnings & Preferences

Each learning is a bullet under the scope that applies. alex-entry-filter-analysis
reads ALL matching scopes before an analysis starts and notes applicable learnings
in the summary's "Preference reminders" section. Learnings accumulate over time;
remove by hand-editing.

## Global (applies to every analysis)

(empty)

## By Block

(empty — add a `### {block_id}` subsection per block with block-specific learnings below it)

## By Strategy Type

(empty — add a `### {structure_type}` subsection per type, e.g. `### double_calendar`)

## By Date Range

(empty — entries use the format `- [YYYY-MM-DD, scope DATE] …` for a single date, or
`- [YYYY-MM-DD, scope START to END] …` for a window)
```

## What NOT to Do

- **Don't bypass the Analysis Protocol.** The locked rules exist to keep recommendations grounded. Breaking them turns analyst output into silent overreach.
- **Don't load both AvgROR and AvgPCR rows in the same run.** Skip the inactive metric entirely — the context budget is finite.
- **Don't auto-invoke `/alex-create-datelist`.** Always wait for the user's go-ahead so they can swap filters first.
- **Don't silently widen the per-group cap above 2.** If the user wants more, they ask explicitly and accept the correlation-risk warning.
- **Don't skip the correlation cross-check.** Even one high-r pair in the recommendation undermines the shortlist's validity.
- **Don't recompute metrics that the CSVs already hold.** Read, don't re-derive — the sweep CSVs are the source of truth for every metric.
- **Don't invent a custom Net ROR formula for the AND set.** When the AND set forces you to compute from raw trade data (because the sweep is per-single-filter), use the exact same formula the sweep uses: `sum(pl_kept) / sum(pl_baseline) * 100`. Do not divide by margin totals. Do not take a ratio of average per-trade ROR. See the locked "Net ROR retention" rule — this is the bug that costs users real decisions.
- **Don't add Entry Group headers inside Baseline or Marginal tables.** Clean flat tables only. Grouping drives *selection logic* (per-group cap), not presentation.
- **Don't auto-save preferences.** Every learning requires explicit user confirmation AND a scope choice before being written.
- **Don't overwrite the preferences file.** Appends only. Hand-edit to remove or correct.
- **Don't treat PCR output as production-grade.** The protocol is calibrated for ROR. See README limitations.
- **Don't run DoW analysis on single-day strategies.** The DoW gate must fire first; skipping it wastes context and produces meaningless rows.
- **Don't report a sum of `pl_per_contract` as a dollar total, and never without the word "sum".** `pl_per_contract` is a 1-lot-normalized per-trade P/L — summing it across trades produces a synthetic aggregate (what a hypothetical run-exactly-1-contract-per-trade version of the backtest would have made) that does NOT correspond to any real outcome. The actual backtest sized contracts dynamically, and under filtering the live sizing logic rebalances — so "sum of pl_per_contract for kept trades" has no mapping to dollars the user would actually earn. If you must surface the number (e.g. for a sanity check on Net ROR retention), label it explicitly as `sum(pl_per_contract) [1-lot-equivalent, NOT a real dollar total]` and always pair it with the retention ratio. Default: don't show it at all. Net ROR retention %, Avg ROR %, and WR from the sweep CSV are scale-invariant and already answer every question the user is asking. **Why:** surfaced 2026-04-20 when I reported "P/L per contract $124K / $132K / $152K" as a side-by-side comparison on the SlimP block — user correctly pushed back that scaling is arbitrary under filtering and the dollar framing implies a false equivalence to real trade outcomes.

## Related skills

- `alex-entry-filter-build-data` — upstream step 1.
- `alex-entry-filter-threshold-sweep` — upstream step 2.
- `alex-entry-filter-heatmap` — upstream step 3; generates the visual reference users can click-capture from.
- `alex-entry-filter-threshold-analysis` — upstream step 4; per-filter deep dive.
- `alex-create-datelist` — downstream; consumes the recommended filter list and produces OO-ready datelists.
