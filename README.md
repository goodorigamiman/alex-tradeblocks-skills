# alex-tradeblocks-skills

Personal skill pack extending the [TradeBlocks MCP server](https://github.com/davidromeo/tradeblocks) with an end-to-end entry-filter analysis pipeline for Option Omega backtests. Built for Claude Code (or any compatible MCP-skill harness).

---

## Installation

```
/plugin marketplace add goodorigamiman/alex-tradeblocks-skills
/plugin install alex-tradeblocks@alex-tradeblocks-skills
```

Then quit and relaunch Claude Code to activate.

### Persist MCP approval

So you don't have to click "approve" every session, add this to `~/.claude/settings.json`:

```json
"enabledMcpjsonServers": ["tradeblocks"]
```

(Replace `"tradeblocks"` with the key your project's `.mcp.json` uses if different.)

---

## Requirements

- **[TradeBlocks MCP server](https://github.com/davidromeo/tradeblocks)** running via Docker compose in `$TB_ROOT/.mcp/`
- **Docker Desktop** (or Docker Engine on Linux)
- **Market data provider** — ThetaData (local daemon), Massive.com, or equivalent
- **Python 3** with `duckdb`, `pandas`, `numpy`, `pyyaml`
- **GitHub CLI (`gh`)** authenticated — only used by `alex-tradeblocks-startup` for plugin drift checks
- **Option Omega CSV exports** imported into block folders

No cross-plugin dependencies — every skill is self-contained.

### Pre-flight checklist

`alex-tradeblocks-startup` will check and auto-recover where it can, but a clean first run is easier with these in place:

- [ ] **TradeBlocks MCP installed** — see [davidromeo/tradeblocks](https://github.com/davidromeo/tradeblocks). Creates `$TB_ROOT/.mcp/docker-compose.yml`, `$TB_ROOT/analytics.duckdb`, `$TB_ROOT/market.duckdb`.
- [ ] **Claude Code MCP config** — `$TB_ROOT/.mcp.json` points to your MCP server.
- [ ] **Environment file** — `$TB_ROOT/.env` has `MARKET_DATA_PROVIDER=thetadata` (or your provider) plus credentials.
- [ ] **Docker Desktop installed**.
- [ ] **Python deps**: `python3 -m pip install duckdb pandas numpy pyyaml`.
- [ ] **GitHub CLI**: `gh auth login`.
- [ ] **Market data provider daemon** (if applicable) — e.g. ThetaTerminal jar downloaded.

You can run the startup skill even with an incomplete install — it tells you exactly what's missing.

---

## Published skills

<!-- SKILLS-TABLE:BEGIN (auto-managed by the github publish workflow — do not edit between markers; edit dev SKILL.md descriptions instead) -->

9 skills organized into three groups.

### Startup & tooling

| Skill | Purpose |
|---|---|
| `alex-tradeblocks-startup` | Health check at session start: MCP server, market provider, plugin drift (upstream vs cache), DuckDB liveness, market-data freshness, enrichment coverage. Auto-recovers Docker / market provider when possible. **Run this first in every session.** |
| `alex-normalize-statistics` | Wraps `get_statistics` and renormalizes P&L + margin to per-contract terms; flags wide margin ranges that distort return-on-margin reporting. |

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

## Recommended daily workflow

The single most important thing: **start Docker and let it fully initialize *before* launching Claude Code**. The MCP client is bootstrapped once at session start and doesn't retry — if Docker isn't up or the MCP container hasn't bound its port when Claude launches, the tools won't be available for that entire session.

### The 3-step rhythm

1. **Start Docker Desktop**. Wait for the icon to stop animating.
2. **Confirm the MCP container is up** — `docker ps` should show `tradeblocks-mcp` as `Up` with the configured port bound (~30–60 seconds after Docker starts).
3. **Launch Claude Code from your TradeBlocks Data root.** Run `/alex-tradeblocks:alex-tradeblocks-startup` as your first action — it verifies every layer and flags anything out of place.

### Alternative: let the startup skill recover

If you forgot and Claude is already running:
1. Run `/alex-tradeblocks:alex-tradeblocks-startup`
2. It auto-starts Docker, the MCP container, and the market provider if needed, and tells you to quit and relaunch Claude Code.
3. Do that, and your next session will be fully mounted.

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

## Troubleshooting

### MCP tools aren't showing up

Symptom: startup says `session tools: NOT mounted — QUIT & RELAUNCH CLAUDE CODE`, or an MCP tool call fails with "tool not found".

Root cause: Claude Code bootstrapped MCP servers at session start when Docker or the MCP container wasn't ready, OR `enabledMcpjsonServers` doesn't include the tradeblocks key.

Fix:
1. Add `"enabledMcpjsonServers": ["tradeblocks"]` to `~/.claude/settings.json`
2. Confirm Docker is up and `tradeblocks-mcp` is running (`docker ps`)
3. **Quit** Claude Code (Cmd+Q on Mac) and relaunch from your TB root. `/clear` / `/reset` inside the same session will not help — the MCP client only rebuilds on a fresh process.

### Plugin shows DRIFT but files look fine

Re-run the startup skill — the corrective for stale `installed_plugins.json` bookkeeping runs only when status is OK and rewrites the field to match the clone HEAD.

### Market data is stale

Confirm the prompt to update. The skill runs `python3 Scripts/update_market_data.py` which appends new bars via your provider + MCP imports and runs enrichment.

### "DuckDB MISSING" on fresh install

You haven't completed the TradeBlocks setup yet. Follow the install docs at https://github.com/davidromeo/tradeblocks to create the databases, then re-run the startup skill.

### Docker won't auto-start

- **macOS**: `open -a Docker` should work; if not, launch Docker Desktop manually.
- **Linux**: the skill tries `systemctl start docker` which may require sudo.
- **Windows**: launch Docker Desktop by hand.

---

## Feedback / issues / contributions

Open an issue at [goodorigamiman/alex-tradeblocks-skills/issues](https://github.com/goodorigamiman/alex-tradeblocks-skills/issues).

## License

MIT
