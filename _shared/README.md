# Shared Supporting Files (`_shared/`)

Reference data shared across multiple dev skills. These files are the **source of truth** for shared dependencies — they ship with the plugin (via `_shared/` in the repo, mirroring this dev folder's layout) and are copied to the plugin cache on install.

---

## Folder Organization

```
_shared/
  README.md                                       This file
  
  # Filter registry (single source of truth for what feeds the entry-filter pipeline)
  entry_filter_groups.default.csv                 Filter taxonomy: 158 rows × 23 cols, organized into 11 groups
  entry_filter_correlations.default.csv           Pairwise correlation matrix (legacy, may need regen after groups changes)
  
  # Datelist files — SINGLE SOURCE OF TRUTH for each data type
  # (calendar-aligned feature tables, joined by entry_filter_data builder)
  entry_filter_dates_calendar.default.csv         Calendar features (date primitives + holidays + period ends)
  entry_filter_dates_calendar_notes.md            Companion notes
  entry_filter_dates_opex.default.csv             Options expirations (monthly, triple witching, VIX monthly)
  entry_filter_dates_opex_notes.md                Companion notes
  entry_filter_dates_econ_calendar.default.csv    Econ calendar (event-indexed, FOMC/CPI/PMI/etc.)
  entry_filter_dates_econ_calendar_notes.md       Companion notes
  entry_filter_dates_earnings.default.csv         Earnings calendar (per-stock + index-threshold proximity)
  entry_filter_dates_earnings_notes.md            Companion notes
  entry_filter_dates_sm.default.csv               SqueezeMetrics DIX/GEX (continuous + derived percentile/categorical)
  entry_filter_dates_sm_notes.md                  Companion notes
```

**No "source" files in `_shared/`.** The datelist files are themselves the source of truth — there is one canonical file per data type, not a "source + derived" pair. To refresh, download fresh data from the provider to a temp location, then run the appropriate build script (lives in conversation history or future `dev-entry-filter-build-datelists` skill) which reads the temp file and overwrites the datelist atomically. Each datelist's notes file documents the provider URL and refresh procedure.

### Naming Convention

| Pattern | Meaning |
|---------|---------|
| `*.default.csv` / `*.default.md` | Shipped defaults — maintained by the plugin author |
| `*.csv` / `*.md` (no `.default`) | User override — your customization, never overwritten |

### How Files Flow

```
_shared/ (dev)  →  repo/_shared/ (GitHub)  →  plugin cache  →  block folder (on first run)
```

1. **Dev:** edit files here in `_shared/`
2. **Publish:** `dev-github-update` copies `_shared/` contents to `repo/_shared/`
3. **Cache:** users get the files when they install/update the plugin
4. **Block:** on first skill run in a block, `entry_filter_groups.*.csv` is copied from cache to `{block}/alex-tradeblocks-ref/` so users can customize per-block

### Resolution Order (at runtime)

When a skill needs a shared file:

1. **User specifies a file at invocation** → use that
2. **User override exists** (no `.default` suffix) in `_shared/` → use that
3. **Default copy exists** (`.default` suffix) in `_shared/` → use that
4. **Neither exists** → copy `.default` from plugin cache to `_shared/`, then use it

To refresh defaults after a plugin update: delete or rename the local `.default` file. The next skill run will re-provision from the updated cache.

### Skill-Local Python Modules

Each skill has its own `.py` modules **inside its skill folder**, not in `_shared/`. Examples:

| Module | Skill Folder | Purpose |
|--------|-------------|---------|
| `build_entry_filter_data.py` | `dev-entry-filter-build-data/` | Build the entry_filter_data.csv (Phase 1 pipeline) |
| `build_pareto_report.py` | `dev-entry-filter-pareto/` | Pareto chart generator |
| `gen_heatmap.py` | `dev-entry-filter-heatmap/` | Heatmap generator |
| `build_parallel_coords.py` | `dev-entry-filter-parallel-coords/` | Parallel coords chart |

These modules use `sys.path` to reference `_shared/` for CSV imports. They are NOT stored in `_shared/` — they travel with their skill.

---

## File Documentation

### `entry_filter_groups.default.csv` — the registry

**Purpose:** unified reference for every available entry filter, organized into 11 groups across 4 sections.

**Schema (23 columns, in file order):**

| # | Column | Description |
|---|---|---|
| 1 | `Index` | Sequential row number (1–158) |
| 2 | `Filter` | Human-readable filter name |
| 3 | `Short Name` | Compact label (used in heatmap, terminal reports) |
| 4 | `CSV Column` | Exact column name in `entry_filter_data.csv` (the build output) |
| 5 | `Section` | High-level theme (Market Conditions / Dealer Hedging / Events / Premium & Structure) |
| 6 | `Entry Group` | Lettered cluster (A–K) within the section |
| 7 | `OO Filter` | TRUE if Option Omega has a native equivalent |
| 8 | `TB Filter` | TRUE if TradeBlocks has the column natively in `parquet market.enriched` or similar |
| 9 | `TV Filter` | (Reserved) |
| 10 | `Entry Filter` | TRUE if usable as an entry filter (FALSE for post-entry/exit-only fields like VIX_at_Close) |
| 11 | `Report V1` | TRUE = include in default V1 report |
| 12 | `Report Heatmap` | TRUE = include in default heatmap |
| 13 | `Threshold Analysis Default Report` | TRUE = include in default threshold sweeps |
| 14 | `Filter Type` | `continuous` / `categorical` / `binary` |
| 15 | `TB Field` | Source field name in TB native schema (where applicable) |
| 16 | `TB Table` | Source table reference (legacy display label) |
| 17 | **`Location`** | **Source data location — see "Location semantics" below** |
| 18 | `TB Notes` | Operational notes (build/lookup details, semantics) |
| 19 | `OO Parameters` | Parameter format in OO |
| 20 | `OO Notes` | OO-specific notes |
| 21 | `Implication` | Mechanic / interpretation |
| 22 | `Computation` | Formula or source description |
| 23 | `tool_tip_info` | User-facing detailed description |

### Location semantics

The `Location` column is the canonical pointer to where each filter's source data lives. Three formats:

| Format | Example | Means |
|---|---|---|
| `parquet <view>` | `parquet market.spot_daily` | Data is in a parquet-backed view (read via DuckDB or MCP `run_sql`) |
| `duck.db <table>` | `duck.db analytics.trades.trade_data` | Data is in the analytics DuckDB |
| `<filename>.csv` | `entry_filter_dates_calendar.default.csv` | Data is in a CSV file in `_shared/` (datelist file). Build script reads and joins on `date` |
| (blank) | | Per-block local data (e.g. OO leg-level export) — see TB Notes for details |

The build script (`dev-entry-filter-build-data`) uses `Location` to dispatch the source query/read. CSV-source filters are joined on the `date` column of the datelist file against `date_opened` of the trade.

### Group structure (11 groups, 4 sections)

| Section | Group | Rows | Source |
|---|---|---:|---|
| Market Conditions | A: Volatility | 21 | `parquet market.spot_daily` |
| Market Conditions | B: Term Structure | 2 | `parquet market.spot_daily` / `enriched_context` |
| Market Conditions | C: Vol Events | 2 | `parquet market.enriched_context` |
| Market Conditions | D: Momentum / Trend | 14 | `parquet market.spot_daily` / `market.spot` |
| Market Conditions | E: Price Action | 8 | `parquet market.spot_daily` / `market.spot` / `duck.db trades.trade_data` |
| Dealer Hedging | F: Dealer Hedging | 6 | `entry_filter_dates_sm.default.csv` |
| Events | G: Calendar | 18 | `entry_filter_dates_calendar.default.csv` |
| Events | H: OPEX | 12 | `entry_filter_dates_opex.default.csv` |
| Events | I: Econ Calendar | 32 | `entry_filter_dates_econ_calendar.default.csv` |
| Events | J: Earnings | 36 | `entry_filter_dates_earnings.default.csv` |
| Premium & Structure | K: Premium & Structure | 7 | `duck.db analytics.trades.trade_data` |

**Forward-extension policy** (shared across all five datelist files): never pre-extend a datelist past its source's data range. Rebuild by extending the source first, then regenerating the datelist file. See each datelist's notes file for source provenance and rebuild instructions.

---

### `entry_filter_correlations.default.csv` — pairwise correlation matrix

**Purpose:** redundancy analysis. 73 pairwise correlations across market fields since 2006. Used to identify near-redundant filters (r > 0.87) for elimination during filter selection.

**Status:** **Legacy** — generated against the older 38-filter group taxonomy. After the recent expansion to 158 filters across 11 groups (most of which weren't in the original correlation analysis), this file no longer covers the full filter set. Regenerating against the current groups CSV is a future task.

**Columns:** `field_a`, `field_b`, `r`, `group_a`, `group_b`, `same_group`, `implication`.

---

### Datelist files — `entry_filter_dates_*.default.csv`

Five calendar-aligned feature tables. Each has its own companion `_notes.md` documenting build process, schema, semantics, and regeneration steps. The notes files are the canonical reference for each datelist.

| File | Indexing | Rows × Cols | Notes file |
|---|---|---:|---|
| `entry_filter_dates_calendar.default.csv` | Weekday (Mon–Fri incl. closures) | 2,349 × 27 | `entry_filter_dates_calendar_notes.md` |
| `entry_filter_dates_opex.default.csv` | Calendar day (incl. weekends) | 3,287 × 51 | `entry_filter_dates_opex_notes.md` |
| `entry_filter_dates_econ_calendar.default.csv` | Event (multiple per date) | 12,524 × 42 | `entry_filter_dates_econ_calendar_notes.md` |
| `entry_filter_dates_earnings.default.csv` | Trading day | 1,251 × 37 | `entry_filter_dates_earnings_notes.md` |
| `entry_filter_dates_sm.default.csv` | Trading day | 3,766 × 8 | `entry_filter_dates_sm_notes.md` |

**Naming convention** for columns within each datelist file:

```
<dataset_stem>_<unit>_<direction>_<event>      e.g. calendar_days_to_closure
<dataset_stem>_<bool|categorical_name>          e.g. sm_gex_sign, calendar_day_of_week
```

The `<dataset_stem>` matches the file name (`calendar_*`, `opex_*`, `econ_calendar_*`, `earnings_*`, `sm_*`). Source columns retained from upstream files preserve their original naming (e.g. `aapl_days_to_earnings`, `Id`, `Start DateTime` — see each notes file for the per-file source-vs-derived split).

---

### Refresh procedure (download → build → overwrite datelist)

To refresh a datelist file, download fresh data from its upstream provider to a temp location, then run the build script which reads the temp file and overwrites the datelist atomically. **No persistent source files in `_shared/`** — the datelist file is the canonical artifact.

| Datelist | Upstream provider | Refresh URL / source |
|---|---|---|
| `entry_filter_dates_calendar.default.csv` | Hand-curated | Edit datelist directly to extend (add new holiday rows for new years; rebuild proximity calcs) |
| `entry_filter_dates_econ_calendar.default.csv` | Google Sheet pinned in `test-strats` channel | Pull CSV snapshot from sheet, run econ-build transform |
| `entry_filter_dates_opex.default.csv` | Cboe Options Calendar PDFs | See historical context in conversation; rebuild via opex-build transform |
| `entry_filter_dates_earnings.default.csv` | Local feature-engineering pipeline at `Build Earnings Data/feature engineering/output/` | Re-run pipeline, copy result, run threshold-proximity transform |
| `entry_filter_dates_sm.default.csv` | SqueezeMetrics — `https://squeezemetrics.com/monitor/static/DIX.csv` | Download CSV, run rename + derived-features transform |

---

## CSV file conventions (Excel-friendly)

All CSV files in this folder follow these rules (per the project's CSV file rules in `CLAUDE.md`):

- **Pure ASCII content** where possible — non-ASCII chars (`—`, `×`, `≈`, `±`, etc.) replaced with ASCII equivalents (`-`, `x`, `~`, `+/-`).
- **No UTF-8 BOM** required when content is pure ASCII.
- **LF line endings**.
- **Comma-safe fields**: any field containing a comma is double-quoted.
- **No bare newlines** inside fields (quote the entire field if it must contain a newline).
- **ISO date format** (`YYYY-MM-DD`) for any `date` column.

**Excel warning**: opening a CSV in Excel and saving back can reformat dates from ISO `YYYY-MM-DD` to `M/D/YY` and convert large numbers to scientific notation. Inspect via Excel; do not save back from Excel.

---

## Version History

| Version | Date | Changes |
|---|---|---|
| 1.0 | 2026-04-12 | Initial release: groups CSV (38 filters, 8 groups) and correlations CSV (73 pairs) |
| 1.1 | 2026-04-14 | Added entry_filter_holidays.default.csv (71 US options market holidays, 2021-2026) |
| 1.2 | 2026-04-14 | Expanded groups CSV to 59 filters; restored Entry Groups B/F/G; added SMA/EMA series and 4 holiday proximity columns; fixed phase1 SQL VIX_Gap_Pct reference |
| 1.3 | 2026-04-16 | Migrated shared files into the dev workspace's `_shared/` folder; removed stale .py duplicates |
| 1.4 | 2026-04-16 | Repo-side rename: `Alex-TradeBlocks-Skills/` → `_shared/` |
| **2.0** | 2026-05-01 | **Major refactor.** Added 5 datelist files (`entry_filter_dates_*.default.csv`) covering calendar / opex / econ / earnings / SM. Expanded groups CSV to 158 rows × 23 cols across 11 groups in 4 sections. Added `Location` column (source pointer); `Section` column moved to position 5 (before `Entry Group`). Removed obsolete `phase1_*.sql` templates (driver builds queries dynamically). All non-ASCII content replaced with ASCII equivalents for Excel compatibility. |
