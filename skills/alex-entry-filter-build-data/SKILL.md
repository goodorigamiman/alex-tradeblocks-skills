---
name: alex-entry-filter-build-data
description: >
  Build the shared entry_filter_data.csv for a block. Reads the filter groups
  registry (block-local override if present, else the shared default), pulls trade and
  market data via the TradeBlocks data layer, computes per-trade 1-lot economics
  (margin, premium, P/L, ROM%, PCR%), populates every filter column declared in the
  groups CSV, and enriches with market holiday proximity. Writes to
  {block}/alex-tradeblocks-ref/entry_filter_data.csv and reports which filter columns
  were populated vs skipped. Shared CSV for heatmap, pareto, parallel coords, threshold,
  and holiday enrichment skills.
compatibility: Requires TradeBlocks MCP server with trade data and market data loaded. Python 3 with pandas and duckdb.
metadata:
  author: alex-tradeblocks
  version: "1.0.2"
---

# Build Entry Filter Data CSV

Centralize the Phase 1 pipeline that every entry filter skill needs. Historically each consumer (heatmap, pareto, parallel coords, threshold, holiday enrichment) re-implemented "check cache, run sufficiency checks, run data SQL, write CSV." That duplication drifted — the SQL grew a `VIX_Gap_Pct` dependency that wasn't in the cached defaults, broke silently, and forced ad-hoc Python workarounds. This skill owns the build once.

## Contract

**Output artifact:** `{block_folder}/alex-tradeblocks-ref/entry_filter_data.csv`

**Schema:**
- Locked base columns (always present, in this exact order):
  1. `trade_index` (int, 1-based, ordered by date_opened + time_opened)
  2. `date_opened` (date)
  3. `time_opened` (time)
  4. `margin_per_contract` (float, 1-lot margin)
  5. `premium_per_contract` (float, 1-lot premium)
  6. `pl_per_contract` (float, 1-lot P/L)
  7. `rom_pct` (float, return on margin = pl / margin_req × 100)
  8. `pcr_pct` (float, Premium Capture Rate = pl / (premium × num_contracts) × 100)
- Filter columns: **names and inclusion come from the groups CSV**, not from this skill. Every row where `TB Filter = TRUE` and `CSV Column` is non-blank becomes a column.
- Holiday columns (appended by this skill): `Days_to_Holiday`, `Weeks_to_Holiday`, `Days_from_Holiday`, `Weeks_from_Holiday`.

**Side effect:** On first run for a block, copies the shared filter groups CSV to `{block}/alex-tradeblocks-ref/` preserving its filename (e.g., `entry_filter_groups.default.csv`). Subsequent runs prefer the block-local copy, letting the user customize filters per block without affecting other blocks.

## When to invoke

- Any entry-filter skill finds `entry_filter_data.csv` missing for the block and needs to build it.
- User says "rebuild entry filter data", "refresh filter CSV", or similar.
- After changing the shared groups CSV and wanting to refresh a specific block.

## Prerequisites

- TradeBlocks MCP server running with trade data for the target block and market data loaded (VIX, VIX9D, VIX3M, underlying ticker daily bars, `market._context_derived`).
- A shared `entry_filter_groups.*.csv` is available (either block-local, or in the plugin's `_shared/` folder). The driver resolves this automatically.
- Python 3 with `pandas` and `duckdb` installed.

## Process

### Step 1 — Confirm target block

If the block ID isn't already known, call `list_blocks` and confirm with the user. The block folder name equals the block ID.

### Step 2 — Run the build

Invoke the Python driver from this skill's base directory (announced at skill load as "Base directory for this skill"):

```bash
python3 "{skill_dir}/build_entry_filter_data.py" "<block_id>"
```

Run from the TradeBlocks Data root (the script resolves TB root automatically).

**Optional: pick a specific groups CSV variant.** If the user is experimenting with multiple filter-group variants (e.g. `entry_filter_groups.V1.csv`, `entry_filter_groups.calendar.csv`), pass `--groups-csv PATH` to select one explicitly. Path may be absolute or relative to the TB root.

```bash
python3 "{skill_dir}/build_entry_filter_data.py" "<block_id>" \
    --groups-csv "/absolute/or/tb-root-relative/path/to/entry_filter_groups.V2.csv"
```

The script:

1. **Resolves the groups CSV** — explicit `--groups-csv` wins. Otherwise globs `{block}/alex-tradeblocks-ref/entry_filter_groups.*.csv` first; if none, globs the shared dir, copies the match to the block ref folder preserving its filename (`entry_filter_groups.default.csv`, `entry_filter_groups.calendar.csv`, whatever). If the block or shared dir has multiple candidates without `--groups-csv`, errors with a message listing them. **Always prints the full resolved path, filename, and source tag (`explicit` | `block-local` | `copied-from-shared`).** When the shared default is freshly copied in, prints a FYI block pointing out that the copy happened so the user can edit it if they want to customize per-block.
2. **Runs sufficiency checks** — trade count ≥ 50, all with margin > 0, VIX/underlying/VIX9D/VIX3M/context coverage ≥ 90%, SLR parseability. Coverage misses mark the dependent columns as "skipped" but do not fail the run. Trade-count failure aborts with a clear message.
3. **Builds the base frame** — 8 locked columns per the Contract above. `pcr_pct` is computed in SQL and its formula is sanity-checked against OO's stored `P/L %` column on the first sample trade; a mismatch aborts with the computed-vs-stored values shown.
4. **Builds the filter frame** — for each row in the groups CSV with `TB Filter = TRUE` and non-blank `CSV Column`, joins the appropriate `market.daily` / `market._context_derived` / `trades.trade_data` field with correct lag semantics (prior-day vs open-known same-day), applies any `Computation` (e.g., ratios) post-query, and merges into the running frame on `date_opened`. Per-column null rates are tracked.
5. **Enriches with holidays** — appends the 4 holiday proximity columns using `_shared/entry_filter_holidays.default.csv` (or the `.csv` override if present). Logic mirrors `alex-entry-filter-enrich-market-holiday`.
6. **Writes CSV** — `{block}/alex-tradeblocks-ref/entry_filter_data.csv`, one row per trade, sorted by `trade_index`.
7. **Prints a structured post-action summary** with four explicit sections:

   **Sources** — full paths (relative to TB root) to the block, the groups CSV (with source tag `explicit` | `block-local` | `copied-from-shared`), the holidays CSV, and the output CSV. Full provenance in one place.

   **Build stats** — trade count, base column count, filter columns populated vs skipped, holiday columns, total columns.

   **Skipped filters** — one line per filter that was requested in the groups CSV but couldn't be populated, with the specific reason (missing DB column, >10% nulls, intraday source out of scope, etc.). Explicit "(none)" when everything populated successfully.

   **Per-column summary** — transposed describe-style table for every numeric column in the output CSV: `count`, `nulls`, `mean`, `std`, `min`, `5%`, `25%`, `50%`, `75%`, `95%`, `max`. One row per column. Formatted for terminal-friendly reading (thousands separators for large values, 3–4 decimals for stats). Lets the user sanity-check ranges and spot zero-variance columns (e.g., `Day_of_Week = 1` for a Monday-only strategy confirms the entry rule is respected).

### Step 3 — Report results to the user (mandated format)

When reporting the build to the user in chat, follow this exact structure in this order. Every section is required. Do not summarize or omit sections.

---

**Build complete — `<block_id>`**

**Sources (all used):**
- Groups CSV: `<filename>` `[block-local]` / `[shared]` / `[explicit]` — one-line qualifier if relevant (e.g. "your block-level copy, any edits persist here")
- Holidays CSV: `<relative_path>` `[shared]`
- Output: `<relative_path>` `[block-local]`

**Build stats:** `<N>` trades × `<M>` columns (`<B>` base + `<F>` filters + `<H>` holidays).

**Missing filters (`<K>` skipped):**

| Filter | Reason |
|---|---|
| ... | ... |

Collapse trivially grouped rows (e.g. SMA_5, SMA_10, SMA_20, SMA_200) into a single table row when they share the same reason. If `<K>` = 0, write "None — all requested filters populated." instead of a table.

**Anomalies in per-column summary worth flagging:**
- Bullet list. Include any zero-variance columns in what should be a multi-valued dimension (data-coverage bug), extreme tail outliers (e.g. `max` > 10× `p95`), unexpected null counts, and confirmatory observations that validate a strategy rule (e.g. `Day_of_Week` std=0 for a Monday-only strategy — that's *good* to surface). If nothing stands out, write "None — distributions look clean."
- End with a one-line wrap-up: "Everything else populated cleanly with 0 nulls." (or equivalent).

**Per-column summary:** (the full describe table goes HERE, as the last item in the response, inside a single triple-backtick code block so it renders in monospace and the user can expand it from the action log).

Paste the full `Per-column summary` block from the script stdout verbatim — do not trim rows. This table is the final item in the response; nothing should follow it.

---

Example: see the format used in the user-approved screenshot that established this template (Build complete heading, bullet-list Sources with `[block-local]` tags, Markdown table for Missing filters with collapsed rows, bullet-list anomalies, code-block describe table last).

**Operational notes** (context for decisions, not part of the response):
- If missing data caused the skips, offer `/tradeblocks:market-data` as the next step.
- Intraday-only filters (marked "intraday source not supported" in the script output) are out of scope for this skill — they require intraday-premium-curve data that this skill doesn't produce. Handle them via a dedicated intraday-aware pipeline outside this skill.
- The `[block-local]` vs `[shared]` vs `[explicit]` tag is the single most important visual cue — never omit it.

### Step 4 — Let downstream skills reuse the output

Once the CSV exists, any of the following skills can read it without rebuilding: `alex-entry-filter-heatmap`, `alex-entry-filter-threshold-analysis`, `alex-entry-filter-threshold-sweep`, `alex-entry-filter-enrich-market-holiday`. They should check for the file and invoke this skill only if missing.

## Data Access

The Python driver uses **read-only DuckDB** (per CLAUDE.md's standing convention for ad-hoc Python analysis: open inside a `with` block, `read_only=True`, release immediately). The groups-CSV-driven query pattern means no monolithic SQL — each source table is queried independently and joined in pandas. This mirrors the chunked approach that MCP `run_sql` would require, so the skill can be ported to pure MCP later if needed. The driver never holds a write lock.

## File Dependencies

| File | Location | Purpose |
|---|---|---|
| `build_entry_filter_data.py` | this skill folder | The driver |
| `entry_filter_groups.*.csv` | `_shared/` (shared default) or `{block}/alex-tradeblocks-ref/` (block override) | Filter registry — determines which columns to build |
| `entry_filter_holidays.default.csv` (or `.csv` override) | `_shared/` | Holiday reference dates for enrichment |
| `phase1_sufficiency_checks.default.sql` | `_shared/` | **Reference only** — the driver reimplements these in Python for clarity and to avoid MCP size constraints |
| `phase1_entry_filter_data.default.sql` | `_shared/` | **Reference only** — the driver builds queries dynamically from the groups CSV instead |

## What NOT to do

- Do **not** hard-code filter column names. Every filter column is defined by the groups CSV. `SLR` lives there too.
- Do **not** use direct DuckDB write connections — the MCP container holds the write lock.
- Do **not** auto-delete the block-local groups CSV on re-run. Users customize it intentionally; preserve their edits across re-builds.
- Do **not** fail silently when a filter's source data is missing — surface it in the report with a specific reason (low coverage, unresolvable field, intraday source, etc.).
- Do **not** write partial output if any required step fails. Either write the full CSV or write nothing.

## Related Skills

- `alex-entry-filter-heatmap`, `alex-entry-filter-threshold-analysis`, `alex-entry-filter-threshold-sweep` — consume the output CSV.
- `alex-entry-filter-enrich-market-holiday` — the original holiday enrichment skill; this skill inlines its logic for self-containment.
- `tradeblocks:market-data` — run if sufficiency checks flag missing market data.
