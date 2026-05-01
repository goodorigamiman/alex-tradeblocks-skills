# alex-tradeblocks-skills

Personal skill pack extending the [TradeBlocks MCP server](https://github.com/davidromeo/tradeblocks) with an end-to-end entry-filter analysis pipeline for Option Omega backtests. Built for Claude Code (or any compatible MCP-skill harness).

---

> **Prerequisite — TradeBlocks 3.x.x with Parquet mode**
>
> These skills require the TradeBlocks MCP server running version **3.x.x** with `TRADEBLOCKS_PARQUET=true`. Skills on `main` read Parquet-backed market views (`market.spot`, `market.option_quote_minutes`, `market.enriched_context`, etc.) directly and will fail or return empty results against the legacy DuckDB-only market store.
>
> **If you're on TradeBlocks 2.x or still running DuckDB-mode market data**, install the last 2.x-compatible release instead:
> - Branch: [`legacy/tb-2x`](https://github.com/goodorigamiman/alex-tradeblocks-skills/tree/legacy/tb-2x)
> - Tag / release: [`v2.6.2`](https://github.com/goodorigamiman/alex-tradeblocks-skills/releases/tag/v2.6.2)

---

## Installation

```
/plugin marketplace add goodorigamiman/alex-tradeblocks-skills
/plugin install alex-tradeblocks@alex-tradeblocks-skills
```

Then quit and relaunch Claude Code to activate.

---

## Requirements

- **[TradeBlocks MCP server](https://github.com/davidromeo/tradeblocks) 3.x.x** running with `TRADEBLOCKS_PARQUET=true` (Docker, Node, or any supported run method — see TB docs). For 2.x / DuckDB-only setups, see the prerequisite callout above and install [`v2.6.2`](https://github.com/goodorigamiman/alex-tradeblocks-skills/releases/tag/v2.6.2) instead.
- **Market data provider** — ThetaData (local daemon), Massive.com, TradingView (CSV import), or equivalent
- **Python 3** with `duckdb`, `pandas`, `numpy`, `pyyaml`
- **Option Omega CSV exports** imported into block folders

No cross-plugin dependencies — every skill is self-contained.

---

## Published skills

<!-- SKILLS-TABLE:BEGIN (auto-managed by the github publish workflow — do not edit between markers; edit dev SKILL.md descriptions instead) -->

11 skills organized into three groups.

### Startup & tooling

| Skill | Purpose |
|---|---|
| `alex-tradeblocks-startup` | Health check at session start (TradeBlocks 3.0 / Parquet-mode aware): MCP server inventory (baseline + dev variants), market provider, plugin drift, DuckDB liveness, Parquet market data freshness, enrichment coverage, optional SqueezeMetrics freshness. Auto-recovers when possible. **Run this first in every session.** |
| `alex-dev-router` | Slash-invoked router (`/dev <thing>`) for dev resources. Auto-discovers from the configured dev folder and `mcp__tradeblocks-dev__*` tools, fuzzy-matches user requests, asks for confirmation when ambiguous, and executes the dev variant deterministically. Maintainer-side; on a pulled-only install reports "no dev environment detected" rather than silently falling through to prod. |
| `alex-normalize-statistics` | Wraps `get_statistics` and renormalizes P&L + margin to per-contract terms; flags wide margin ranges that distort return-on-margin reporting. |
| `alex-squeezemetrics-update-data` | Refreshes SqueezeMetrics DIX/GEX daily data from upstream. Maintains canonical CSV under `_shared/`, mirrors to Parquet under `alex-data/squeezemetrics/`, updates `.sync-meta.json` watermark. Idempotent + atomic. Trigger: *"update squeezemetrics data"*. |

### Entry filter analysis

| Skill | Purpose |
|---|---|
| `alex-entry-filter-build-data` | Builds the canonical `entry_filter_data.csv` for a block — one row per trade with per-contract economics, every requested market regime field, and holiday-proximity enrichment. CSV-driven: filter columns are declared in `entry_filter_groups.csv`, not in code. |
| `alex-entry-filter-enrich-market-holiday` | Adds 4 holiday-proximity columns (`Days_to_Holiday`, `Weeks_to_Holiday`, `Days_from_Holiday`, `Weeks_from_Holiday`) to `entry_filter_data.csv`. |
| `alex-entry-filter-threshold-sweep` | Pre-computes retention curves for every continuous, binary, and categorical filter. Writes two sibling CSVs (`entry_filter_threshold_results.csv` + `entry_filter_categorical_results.csv`) consumed by every downstream report. No second data pass required. |
| `alex-entry-filter-heatmap` | Interactive HTML heatmap with three sections: Discovery Map (global, sorted by 80% retention delta), By Filter Group (per-Entry-Group Min/Max/Combo), Binary & Categorical Breakdown (clickable In/Out). Click any cell to capture a filter expression; localStorage-persisted; copy-to-clipboard feeds `alex-create-datelist`. |
| `alex-entry-filter-analysis` | One-shot orchestrator + analyst + learner. Runs build-data → sweep → heatmap → threshold-analysis (for flagged filters), then produces a baseline-anchored Marginal-Impact filter shortlist with correlation deduplication. Captures user feedback into a scoped preferences file (Global / Block / Strategy-Type / Date-Range). |

### Threshold exploration & output

| Skill | Purpose |
|---|---|
| `alex-entry-filter-threshold-analysis` | Per-filter deep dive — interactive Chart.js HTML with scatter, threshold sweep, efficiency frontier, and OO-formatted filter translations. One filter per run. |
| `alex-create-datelist` | Generates Option Omega-compatible ISO datelists from filter expressions. Emits two code blocks: AND-intersection whitelist + per-filter blackout block, both copy-paste ready. |

<!-- SKILLS-TABLE:END -->


---

## Design philosophy

### 1. Local config + log files (`alex_*` prefix)

Skills that need user-specific state write to files in your TradeBlocks Data root prefixed with `alex_`:

| File | Purpose | When written |
|---|---|---|
| `alex_tradeblocks_startup_config.md` | Local config (paths, provider choice, MCP container name, plugin marketplaces, legacy tables to ignore) | On first run only — never overwritten by skill updates |
| `alex_tradeblocks_startup_log.md` | Recovery action history (what was down, what command was run, how long it took) | Appended each session that needed recovery |
| `alex_entry_filter_analysis_preferences.md` | Cross-session learnings scoped Global / Block / Strategy-Type / Date-Range | Appended on explicit user confirmation only |

**Skill `SKILL.md` files contain zero user-specific values.** Discovery-then-confirm flow on first run handles personalization. You can hand-edit any `alex_*` file when your environment changes; the skill picks up changes on next run and surfaces "config drift" if detected values disagree.

### 2. CSV-driven data flow

Each skill reads and writes well-known CSVs at predictable locations rather than hard-coding SQL or filter lists:

```
{block}/alex-tradeblocks-ref/
├── entry_filter_data.csv                ← per-trade base + filter columns
├── entry_filter_groups.*.csv            ← filter registry (which columns to build, how to display)
├── entry_filter_threshold_results.csv   ← continuous sweep results
└── entry_filter_categorical_results.csv ← categorical sweep results
```

Adding a new filter = adding a row to the groups CSV. No skill code changes. Downstream skills (heatmap, analysis, threshold-analysis, datelist) route purely off the metadata in those CSVs.

### 3. Set-mapping via the Filter Type column

The groups CSV declares each filter's `Filter Type` (`continuous`, `categorical`, `binary`) and which reports it appears in (`Report Heatmap`, `Threshold Analysis Default Report`, `TB Filter`, etc.). Each skill subsets the registry with its own column flag — same data, different views, no drift.

### 4. Block-local overrides

The first time you analyze a block, the shared default groups CSV is copied into `{block}/alex-tradeblocks-ref/` and used from there forever. Edit the block-local copy to customize filters per strategy without affecting other blocks. Skill updates can refresh the shared default without trampling your edits.

### 5. Strict provenance

Every report names its sources explicitly (data CSV, groups CSV, holidays CSV, output CSV) with `[block-local]` / `[shared]` / `[explicit]` tags so you can always trace any number back to the file that produced it.

---

## How `alex-tradeblocks-startup` works (in detail)

### First-run setup

The first time you run the startup skill, it probes your environment (TB root, dev workspace existence, `.env` provider, `.mcp` compose file, plugin marketplaces) and writes `alex_tradeblocks_startup_config.md`. It asks you to confirm each detected value before writing.

Expect questions like:
- *"I found `ThetaData` in your `.env`. What command starts it?"*
- *"I detected a dev workspace folder — is this your local maintainer workspace?"* (Pulled-only users answer no and get a simpler report.)

After first run, subsequent runs read the config silently and skip the interactive setup.

### What each run checks

Every run walks through five layers and stops at the first unrecoverable failure:

1. **Environment pre-flight** — python3, PyYAML, duckdb, gh, curl, git installed?
2. **MCP server** — Layer A (Docker daemon + container + port bound) and Layer B (MCP tools actually mounted in *this* Claude session)
3. **Market data provider** — endpoint reachable; auto-start daemon if configured
4. **Plugin drift** — upstream GitHub HEAD vs marketplace clone vs runtime cache (three-way check, not the stale `gitCommitSha` bookkeeping field)
5. **DuckDB state** — liveness probe, table inventory, market data freshness, enrichment coverage

The final report is one compact block: status summary, `Upstream vs Installed:` table, `Market data coverage:` table, recovery actions taken, config path.

### Managing your config + log files

**When to hand-edit the config:**
- Your market-provider start command changes
- You move the MCP compose directory or upgrade the container image
- You add/remove a plugin marketplace
- You want to add a known-deprecated table to `legacy_tables_ignore`

**To reset:** rename or delete `alex_tradeblocks_startup_config.md`. On the next run, first-run setup kicks in again.

**The recovery log** (`alex_tradeblocks_startup_log.md`) is append-only and useful for spotting patterns ("Docker is always down at session start — set it to launch on login"). Trim or archive manually if it grows large.

---

## Feedback / issues / contributions

Open an issue at [goodorigamiman/alex-tradeblocks-skills/issues](https://github.com/goodorigamiman/alex-tradeblocks-skills/issues).

## License

MIT
