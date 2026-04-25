---
name: alex-squeezemetrics-update-data
description: >
  Refreshes SqueezeMetrics DIX/GEX data from https://squeezemetrics.com/monitor/static/DIX.csv.
  Maintains the canonical CSV at `<plugin_root>/_shared/DIX-3.csv` (sibling to the skill folder)
  and mirrors it to a Parquet file at `<TB_ROOT>/alex-data/squeezemetrics/data.parquet` so it can
  be queried via run_sql + read_parquet. Runtime is deliberately narrow — fetches upstream, appends
  new dates to the CSV, rewrites the Parquet, updates .sync-meta.json. Touches nothing else.
compatibility: Python 3 with pandas and pyarrow. Uses standard-library urllib for the fetch (no extra deps). Invoke from anywhere — the driver resolves paths relative to its own location.
metadata:
  author: alex-tradeblocks
  version: "1.0.0"
---

# Refresh SqueezeMetrics DIX/GEX Data

Keep the SqueezeMetrics DIX/GEX daily time series current. DIX (Dark Index) tracks the dark-pool short component of SPX price discovery; GEX (Gamma Exposure) is the market-maker hedging pressure in dollar terms. Both are daily SPX-wide scalars, useful as regime context or as features for entry-filter analysis.

The canonical CSV is git-tracked under `_shared/` so other users of the dev-skills package get the data alongside the skill. The Parquet mirror lives under `alex-data/` at the TB root — a sibling to `market/` that the TB MCP never writes to, so there's no conflict with MCP-managed data.

## Contract

**Canonical CSV:** `<plugin_root>/_shared/DIX-3.csv` (sibling to this skill's folder; same path resolves correctly in both the maintainer's dev layout and the subscriber's plugin cache)

Columns (preserved from upstream):

| Column | Type | Meaning |
|---|---|---|
| `date` | ISO `YYYY-MM-DD` | Trading day |
| `price` | float | SPX daily close (reference) |
| `dix` | float | Dark Index, 0–1 scale (observed ~0.33–0.55) |
| `gex` | float | Gamma exposure in USD (observed ~−$7.5B to +$24B) |

**Parquet mirror:** `alex-data/squeezemetrics/data.parquet`

Same 4 columns as the CSV, plus one provenance column:

| Column | Type | Meaning |
|---|---|---|
| `source_updated` | TIMESTAMPTZ | When this row was appended by this skill. Pre-existing rows (from the CSV that shipped with the skill) get the timestamp of the first Parquet build. New rows get the fetch time of the run that added them. |

No Hive partitions. Single-file "global time series" shape from `Alex Signals TB 3.0 Migration.md` §8.

**Watermark:** `alex-data/.sync-meta.json` — per-dataset metadata (source URL, paths, last refresh, latest date, row count). Shared with any other dataset under `alex-data/`.

## When to invoke

- At the start of a session when SqueezeMetrics data is stale (the skill's CSV latest date is older than yesterday).
- Before any analysis that joins DIX or GEX against a recent date range.
- On demand via the trigger phrase **"update squeezemetrics data"**.

The skill is **idempotent** — a refresh with no new upstream rows produces zero file changes (CSV and Parquet both untouched, only `.sync-meta.json.last_refresh` updates). Safe to call any number of times per day.

## Process

1. **Resolve paths.** Layout-agnostic — works for both dev folder and published cache:
   - `CSV_PATH = <plugin_root>/_shared/DIX-3.csv` (script probes both `SKILL_DIR.parent/_shared/` and `SKILL_DIR.parent.parent/_shared/`)
   - `PARQUET_PATH = <TB_ROOT>/alex-data/squeezemetrics/data.parquet`
   - `SYNC_META = <TB_ROOT>/alex-data/.sync-meta.json` (TB_ROOT discovered by walking up from cwd looking for `alex_tradeblocks_startup_config.md`)
2. **Read canonical CSV.** Note latest date and row count.
3. **Fetch upstream CSV** from `https://squeezemetrics.com/monitor/static/DIX.csv` via `urllib.request` with a descriptive User-Agent. Parse.
4. **Diff by date.** Rows with `date > local_latest` are the new rows.
5. **Append to CSV** (if any new rows). Atomic write via `.tmp + os.replace`. Skip entirely if no new rows.
6. **Rewrite Parquet** from the merged CSV. For rows that exist in the old Parquet, preserve the existing `source_updated`; new rows get `source_updated = now`. Atomic write.
7. **Update `.sync-meta.json`** with new watermark (`latest_date`, `row_count`, `last_refresh`). Atomic write. Other dataset keys in the file are left untouched.
8. **Report** rows fetched, new rows added, date range added, final row count.

## Prerequisites

- Python 3 with `pandas` and `pyarrow` available (already used by other dev-skills — no extra install).
- Network access to `squeezemetrics.com`.

## Invocation

Trigger phrase: **"update squeezemetrics data"** — invoke via Claude. The skill resolves the script path automatically.

For ad-hoc shell invocation (debugging), the script lives next to this SKILL.md:

```bash
python3 "$(dirname "$(realpath ~/path/to/SKILL.md)")/refresh_squeezemetrics.py"
```

Or just `cd` into the skill's folder and run `python3 refresh_squeezemetrics.py`.

Optional flags:

- `--dry-run` — fetch and diff, but write nothing. Useful for verifying upstream connectivity and seeing pending rows without committing.

## Output format

```
Local CSV: 3,766 rows, latest date 2026-04-20
Fetching https://squeezemetrics.com/monitor/static/DIX.csv ...
Upstream: 3,768 rows, latest date 2026-04-22
New rows: 2 (dates 2026-04-21 → 2026-04-22)
CSV updated: 3,768 rows → <plugin_root>/_shared/DIX-3.csv
Parquet rewritten: 3,768 rows → alex-data/squeezemetrics/data.parquet
Sync meta updated: alex-data/.sync-meta.json

=== Summary ===
Rows fetched: 3,768
New rows added: 2
Date range added: 2026-04-21 → 2026-04-22
Final row count: 3,768
```

Idempotent run output:

```
Local CSV: 3,768 rows, latest date 2026-04-22
Fetching https://squeezemetrics.com/monitor/static/DIX.csv ...
Upstream: 3,768 rows, latest date 2026-04-22
No new rows — already up to date.
```

## Reading the Parquet from MCP

The Parquet isn't auto-registered by the TB MCP (non-canonical subfolder). Read via explicit path in `run_sql`:

```sql
SELECT COUNT(*), MIN(date), MAX(date)
FROM read_parquet('alex-data/squeezemetrics/data.parquet')
```

Join against MCP canonical data (e.g., the cross-ticker regime context):

```sql
SELECT s.date, s.dix, s.gex, e.Vol_Regime, e.Term_Structure_State
FROM read_parquet('alex-data/squeezemetrics/data.parquet') s
LEFT JOIN market.enriched_context e ON e.date = s.date
WHERE s.date BETWEEN '2026-03-01' AND '2026-04-22'
```

## What NOT to do

- **Do not** read or write `<TB_ROOT>/Squeezemetrics Data/` — that folder is orphaned after the migration to `_shared/`. User will remove it manually once satisfied.
- **Do not** touch any file under `market/`, `market-meta/`, `blocks/`, `database/` — MCP territory.
- **Do not** modify CLAUDE.md or any other config on every run — those are one-time setup edits, not runtime concerns.
- **Do not** introduce new dependencies (avoid `requests`, `beautifulsoup4`, etc.). The current fetch uses `urllib` which ships with Python.
- **Do not** change the CSV schema or column order. Downstream consumers (analysis skills that will join on this data) depend on stable columns.

## File dependencies

| File | Role |
|---|---|
| `<plugin_root>/_shared/DIX-3.csv` | canonical CSV — git-shared |
| `<skill_dir>/refresh_squeezemetrics.py` | the driver |
| `<skill_dir>/README.md` | background on DIX/GEX semantics (copy of the original `LEARNING.md` from the source folder) |
| `<skill_dir>/Documentation/` | SqueezeMetrics whitepaper PDFs |
| `<TB_ROOT>/alex-data/squeezemetrics/data.parquet` | Parquet mirror |
| `<TB_ROOT>/alex-data/.sync-meta.json` | watermark |
| `<TB_ROOT>/alex-data/README.md` | index doc for the `alex-data/` subtree |

## Related skills

- Future consumer skills (entry-filter analysis, regime comparison) can `read_parquet` from `alex-data/squeezemetrics/data.parquet` and JOIN with `market.enriched_context` for DIX/GEX-enriched analysis.
- See `Alex Signals TB 3.0 Migration.md` in the TB root for the full spec governing the `alex-data/` subtree.
