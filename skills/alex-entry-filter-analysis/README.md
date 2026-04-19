# dev-entry-filter-analysis

One-shot orchestrator + analyst + learner for the entry-filter pipeline. Turns "I want to analyze this block's entry filters" into a single invocation that runs every upstream skill in order, reads the generated reports, and hands back a baseline-anchored filter shortlist — with warnings, correlation checks, and cross-session learnings applied.

## What this skill does

Produces a ready-to-act filter recommendation for a block by running the full entry-filter pipeline and reading every generated report. One entry point replaces four sequential invocations plus manual interpretation. The recommendation is **grounded** — every filter it names comes from a row in the generated CSVs — and **scoped** — no more than 2 filters per Entry Group in the final list. It's the bridge between raw trade data and an OO-ready datelist.

It also **learns**. When the user corrects a recommendation, flags bad data, or shares a durable insight, the skill offers to save that as a scoped learning in a preferences file at the TB root. Future runs read the file and apply matching scopes (Global / Block / Strategy-Type / Date-Range), so lessons carry over between sessions without cross-contaminating unrelated blocks.

## Data flow

```
entry_filter_groups.*.csv ──┐
                             │  (labels, Entry Group, Threshold Analysis Default Report flag)
                             │
   raw trade data (MCP) ─→ dev-entry-filter-build-data ─→ entry_filter_data.csv
                                                                 │
                                                                 ├─→ dev-entry-filter-threshold-sweep ─→ entry_filter_threshold_results.csv (continuous)
                                                                 │                                       entry_filter_categorical_results.csv (binary+categorical)
                                                                 │
                                                                 ├─→ dev-entry-filter-heatmap ─→ entry filter heatmap.html
                                                                 │
                                                                 └─→ dev-entry-filter-threshold-analysis × N ─→ entry filter threshold analysis {name}.html
                                                                             (one HTML per filter flagged with
                                                                              Threshold Analysis Default Report = TRUE)

   _shared/entry_filter_correlations.default.csv ──┐
   alex_entry_filter_analysis_preferences.md       │
                                                    ▼
                  ┌────────────── dev-entry-filter-analysis (this skill) ───────────────┐
                  │                                                                      │
                  │  READS:  threshold_results.csv  (metric-filtered: AvgROR OR AvgPCR)  │
                  │          categorical_results.csv (metric-filtered)                   │
                  │          groups.csv  (labels + Entry Group membership)               │
                  │          correlations.csv  (pairwise r for redundancy checks)        │
                  │          preferences.md  (Global / Block / Strategy-Type / Date-Rng) │
                  │          entry_filter_data.csv:Day_of_Week (unique-value count)      │
                  │                                                                      │
                  │  PRODUCES (in conversation):                                         │
                  │    • Preference reminders                                            │
                  │    • Run log                                                         │
                  │    • Warnings                                                        │
                  │    • Baseline Impact table (each filter vs All Trades, ≤2/group)     │
                  │    • Marginal Impact table (each filter's contribution to AND set)   │
                  │    • "Other interesting" sidebar                                     │
                  │    • Standby for /dev-create-datelist hand-off                       │
                  │                                                                      │
                  │  APPENDS (on explicit user confirm):                                 │
                  │    • Learnings to preferences.md, scoped by tag                      │
                  │                                                                      │
                  └──────────────────────────────────────────────────────────────────────┘

                                     User decides next:
                                     (a) go with Claude's picks  → /dev-create-datelist
                                     (b) paste own picks         → /dev-create-datelist
                                     (c) drill further, swap, re-analyze with PCR, etc.
```

## Capabilities

- **One-shot orchestration** — runs build-data → threshold-sweep → heatmap → threshold-analysis (×N) in order, with exit-code checks and remediation pointers on failure.
- **Grounded recommendations** — every recommended filter corresponds to a row in the generated CSVs. Nothing invented.
- **Context-gap detection** — if the user mentions a concept with no matching filter in the groups CSV, it surfaces as an explicit warning instead of being silently incorporated.
- **Correlation-aware shortlist** — pairs with `|r| ≥ 0.85` get deduped (pick one, drop the other with a note); `|r| ≥ 0.95` never co-recommended.
- **Per-Entry-Group cap** — no more than 2 filters per group in the final list, picked by combined avg-ROR lift + net-ROM bump with trade count as tie-breaker.
- **Confidence floor** — filter subsets below 10 trades flagged LOW CONFIDENCE; excluded unless no alternative exists.
- **Outlier-boundary framing** — extreme-tail thresholds preferred over mid-range bands when edge is comparable (framed as regime-shift risk management).
- **Day-of-Week gate** — if the block trades only one day, DoW analysis is skipped entirely with an explicit note.
- **Holiday-week probe** — always checks `Weeks_to_Holiday == 0` and `Weeks_from_Holiday == 0` buckets; surfaces them if deviation ≥ 2pp vs baseline.
- **Cross-session learning** — scoped preferences (Global / Block / Strategy-Type / Date-Range) persist between sessions.
- **Metric isolation** — loads only the active metric's rows (AvgROR by default, AvgPCR on explicit request) to keep context tight.
- **Baseline anchoring** — Baseline Impact table starts with an All Trades row so every delta reads against the same anchor.
- **Marginal (leave-one-out) analysis** — Marginal Impact table adds a second view: for each filter, what does it contribute to the final AND set? Surfaces redundant filters (ones whose trades are already caught by others) that Baseline alone would mistakenly present as strong contributors.
- **Shared canonical format with dev-create-datelist** — the two tables' columns and conventions are identical to what `dev-create-datelist` prints right before generating the OO code blocks. The user sees the same numbers whether they're still in analysis or ready to ship.

## Understanding the two impact tables

Every analysis presents two tables that share a column set but answer different questions:

- **Baseline Impact** — "What does each filter do on its own, compared to doing nothing?"
- **Marginal Impact** — "What does each filter contribute to the set we're actually shipping?"

A filter can look strong in one and weak in the other; both views are needed before accepting a shortlist. This format is shared 1:1 with the downstream `dev-create-datelist` skill — the same tables appear there immediately before the datelist code blocks, so the user sees the same numbers at every step of the pipeline.

### Shared column set

Both tables use compressed headers: `Filter / Keep / Out / % / Net ROR / +pts / Avg ROR / +pts / WR / +pts`. Marginal adds an `N-1` column at position 2, making it 11 columns total (Baseline is 10).

The three `+pts` columns are unqualified — column order pairs each `+pts` with the metric directly to its left. All three `+pts` columns are **absolute pp deltas** between the row's anchor and the row's subject (no ratios, no mixed framings). Only the anchor differs between tables.

### Baseline Impact — anchor is All Trades

Row 1 is `All Trades (baseline)` with `Keep = total`, `Net ROR = 100.0%`, `Avg ROR = baseline_avg`, `WR = baseline_wr`, and `—` in every `+pts` column. Filter rows show that filter's solo subset; `+pts` = subset value − baseline value in pp. Last row is `All AND (specific dates)` — what the full recommended set does together vs baseline.

Example reading for a row "`VIX_IVP <= 92.032 ... Net ROR = 111.0%, +pts = +11.0 pp`": applying this filter alone keeps 91.9% of trades and retains 111% of baseline Net ROR — i.e., the excluded tail trades were net-negative contributors, so the filter *lifts* total edge. A "free filter" in Baseline shows `Net ROR +pts > 0 AND Avg ROR +pts > 0`.

### Marginal Impact — anchor is the full N-filter AND set

Row 1 is `All N filters (AND set)` with absolute numbers, all `+pts = —`. Filter rows are labelled `Marginal: {filter expression}` and show the named filter's contribution on top of the OTHER (N-1) filters.

Column meanings in filter rows:

- `N-1` = size of the pool available to the filter (the subset of trades that pass every OTHER filter). **Satisfies `N-1 = Keep + Out` — the arithmetic consistency check.**
- `Keep` = trades surviving the filter = full AND count (constant across Marginal filter rows).
- `Out` = trades this filter *uniquely* excludes from the N-1 pool.
- `%` = `Keep / N-1` × 100 = this filter's passthrough rate on the pool it operates on.
- `Net ROR` = full AND's retention of baseline Net ROR (constant across filter rows).
- `Net ROR +pts` = full AND's baseline-retention MINUS N-1 pool's baseline-retention, in pp. Negative = filter costs retention; positive = filter *improves* retention (signals a "free" contributor); zero = fully redundant inside the set.
- `Avg ROR` = full AND's mean ROM (constant).
- `Avg ROR +pts` = full AND's avg MINUS N-1 pool's avg, in pp (how much the filter concentrates per-trade edge).
- `WR` / `WR +pts` = same structure for win rate.

### Marginal = 0 is a signal, not a bug

When a filter's Marginal row shows `Out = 0` and all `+pts = 0`, the filter is **fully redundant inside this AND set** — every trade it would exclude is already excluded by at least one other filter. The observed Baseline signal was likely driven by a correlated continuous filter already in the set (this pattern is captured as a Global learning in `alex_entry_filter_analysis_preferences.md`).

A redundant filter is often still worth keeping in the OO blackout slot as a safety net against filter-set changes (dropping one of the "real" filters would un-cover the trades the redundant filter catches). But it shouldn't be presented as a distinct signal in the recommendation narrative.

### How the two tables read together

- **Strong in Baseline, weak in Marginal** → filter's effect was driven by trades already handled by others; consider dropping.
- **Weak in Baseline, strong in Marginal** → filter's value shows up only in combination; keep.
- **Strong in both** → core contributor; keep.
- **Weak in both** → not worth including.
- **Negative `Net ROR +pts` in both** → filter trades total edge for per-trade concentration; whether that's a good trade depends on your strategy's sizing and risk tolerance.

## Methodology

How a recommendation gets picked, step by step:

### 1. Candidate pool

For each continuous filter in the sweep CSV (matching the active metric), extract the top candidates by avg-ROR lift (`+avg pts`) across the retention grid. For each categorical filter, extract the In-Group and Out-Group stats per value. Holiday-week buckets (`Weeks_to_Holiday == 0`, `Weeks_from_Holiday == 0`) are always probed regardless of TA-flag status.

### 2. Sufficiency gate

Drop any candidate where the surviving subset is below 10 trades. Flag as LOW CONFIDENCE. Keep only if no alternative exists in the same Entry Group.

### 3. Outlier-boundary preference

If two candidate thresholds on the same filter both pass sufficiency and retention, prefer the more extreme (closer to the tail) threshold UNLESS the less-extreme one offers materially better avg-ROR lift AND net-ROM bump (both ≥ 1.5× better). Rationale: extreme-tail filters are risk management against regime shift; mid-range bands risk overfitting.

### 4. Correlation deduplication

Cross-check every pair in the current candidate set against `_shared/entry_filter_correlations.default.csv`:
- `|r| ≥ 0.95` → drop one, note the other as "redundant, covered by {winner}."
- `|r| ≥ 0.85` → warn, pick at most one.
- Missing from matrix → flag "correlation check skipped" but keep both (user decides).

### 5. Per-group cap

Cap at 2 filters per Entry Group. Tie-break by combined rank of avg-ROR lift + net-ROM bump, then trade count, then preference-weighted (a filter matching a "validated threshold" preference wins ties).

### 6. Preferences application

Apply loaded preference entries:
- Bad-data date entries → exclude affected trades from sufficiency counts (warn user with affected count).
- Validated-threshold entries → weight the named threshold in tie-breaks.
- Durable constraints → shape candidate selection (e.g. "always outlier-trim VIX3M").

### 7. Holiday bucket probe

Always check `Weeks_to_Holiday == 0` and `Weeks_from_Holiday == 0` In-Group rows. If deviation ≥ 2pp, surface as exclusion filter (`!= 0`) candidates in the recommendation. If material but below confidence floor, note as LOW CONFIDENCE.

### 8. Day-of-Week gate

Run `Day_of_Week` unique-value count on `entry_filter_data.csv`:
- Count == 1 → skip all DoW analysis, report skip in warnings.
- Count > 1 → DoW filters eligible; apply standard candidate logic.

### 9. Final table assembly

Build the recommendation table:
- Row 1: All Trades (baseline), Net ROR = 100.0%, `—` in +pts columns.
- Per-filter rows grouped by Entry Group, ≤ 2 per group.
- Last row: All AND (specific dates), showing combined effect.

All metrics sourced directly from the CSVs. No re-derivation.

## Limitations & known issues

### PCR analysis is immature

AvgPCR rows live in the sweep CSVs alongside AvgROR, and this skill can run in PCR mode on explicit request. **But the analytic protocol above is calibrated for ROR semantics.** Specifically:

- **Correlation thresholds** (`0.85`, `0.95`) were chosen based on ROR's sensitivity to filter pair interactions. PCR's correlation structure may differ; recommendations may be under- or over-dedupe-aggressive.
- **Outlier-boundary framing** assumes ROR's regime-shift logic applies to PCR equivalently. This is plausible but unvalidated.
- **Per-group cap** logic uses avg-ROR lift + net-ROM bump as the tie-breaker. PCR analog is avg-PCR lift + net-PCR bump, but the weighting hasn't been validated against actual PCR-driven strategy variants.
- **Holiday bucket probe threshold** (≥ 2pp deviation) was calibrated on ROR output.

**Treat PCR output as exploratory.** The summary header always prints the active metric so there's no ambiguity about which regime is being reported. A future release should calibrate PCR-specific protocol rules and label the skill as PCR-ready.

### Correlation matrix is static and shared

`_shared/entry_filter_correlations.default.csv` is a shared reference, not block-specific. Filter pairs added to the groups CSV after the matrix was built (or custom filters not captured in the shared matrix) won't have correlation data. The skill flags "correlation check skipped for X vs Y" in the warnings block — but can't fill in the missing data.

**Future enhancement candidate:** per-block correlation matrix override.

### Preferences file has no UI

Learnings are stored as markdown bullets in `$TB_ROOT/alex_entry_filter_analysis_preferences.md`. There's no search, no deduplication, no expiry, no edit-in-place. Long-lived blocks will accumulate entries over time. The file is hand-editable; the user is responsible for pruning stale entries.

The skill never deletes learnings automatically. If a saved learning turns out wrong, hand-edit the file to remove the bullet.

### Strategy-type matching depends on trade profile

By-Strategy-Type preferences only match if the block has a synced `trade_profile.json` with a populated `structureType` field. Blocks without profiles (or with missing `structureType`) fall back to Global + Block scopes only. The skill reports which strategy-type scope it matched in the run summary, so mismatches are visible.

### Date-range preferences don't interact with the sweep

Flagging "2023-03-13 is bad data" surfaces a warning in the summary — but does NOT re-run the sweep with those trades excluded. The sweep CSVs still include those trades in their computed metrics. To actually exclude bad-data trades from the analysis, the user would need to either:

1. Re-export trades without the bad dates and rebuild `entry_filter_data.csv`.
2. Accept the flag and interpret results with caveat (affected-trade count is surfaced).

**Future enhancement candidate:** a "rebuild with date-range exclusion" path that feeds preferences back into build-data.

### No undo on preference saves

If a learning is saved with the wrong scope or turns out to be wrong, the only recourse is hand-editing the file. There is no built-in undo or rollback. The scope-confirmation step during save helps prevent this — Claude never saves without an explicit scope choice — but the user should read the proposed entry carefully before confirming.

### Skill depends on four upstream skills being installed

This skill is pure orchestration. If any of `dev-entry-filter-build-data`, `dev-entry-filter-threshold-sweep`, `dev-entry-filter-heatmap`, or `dev-entry-filter-threshold-analysis` is missing or broken, the pipeline halts at that step and surfaces the error. The skill doesn't work around failures in its dependencies — it reports them.

### No parallelism

The N threshold-analysis reports (one per TA-flagged filter) run sequentially. On blocks with many flagged filters this can take a while. Progress is announced; there's no concurrent execution.

## Future opportunities

- **PCR-aware protocol calibration** — derive correlation thresholds and outlier-boundary rules from PCR semantics instead of reusing ROR's.
- **Per-block correlation matrix override** — let a block-local correlations CSV supplement the shared default.
- **Preference-driven sweep re-runs** — feed "bad-data date" preferences back into build-data so the excluded trades actually leave the metrics, not just the warnings.
- **Preference dedup / expiry** — tooling to find near-duplicate learnings or auto-archive old entries.
- **Parallel threshold-analysis execution** — run the N deep-dive reports concurrently when the block has many flagged filters.

## Related skills

- `/dev-entry-filter-build-data` — upstream step 1. Produces `entry_filter_data.csv` from raw trade data.
- `/dev-entry-filter-threshold-sweep` — upstream step 2. Produces the two result CSVs this skill reads.
- `/dev-entry-filter-heatmap` — upstream step 3. Generates the interactive visual reference (click-to-capture flows into Step 9's hand-off).
- `/dev-entry-filter-threshold-analysis` — upstream step 4. Per-filter deep dive, one HTML per TA-flagged filter.
- `/dev-create-datelist` — downstream. Typical next step after analysis; takes the accepted filter list and produces OO-compatible datelists (specific + blackout blocks).
