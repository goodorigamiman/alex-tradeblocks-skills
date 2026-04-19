# alex-tradeblocks-skills (dev source)

Canonical source for the `alex-tradeblocks-skills` plugin. This folder is the working directory where skills are developed, tested, and published. `alex-github-update` publishes from here to the marketplace.

Custom agent skills for analyzing Option Omega backtests and options trading portfolios, built on top of the [TradeBlocks MCP server](https://github.com/davidromeo/tradeblocks).

---

## Folder layout

```
Dev-TradeBlocks-Skills/
  README.md                      This file — plugin overview and workflow guide
  _shared/                       Shared reference data + SQL templates (see _shared/README.md)
  dev-<skill-name>/              One folder per skill in development
    SKILL.md                     Skill spec
    <skill-name>.py              (optional) Skill-local Python module
```

Skills follow the `dev-<name>/` convention while in development; on publish, `alex-github-update` renames to `alex-<name>/` and strips the `-dev` suffix from versions.

---

## What's in this plugin

9 skills organized into three groups:

### Startup & tooling

| Skill | Purpose |
|-------|---------|
| `alex-tradeblocks-startup` | Health check for MCP server, market data provider, plugin drift, DuckDB state, market data freshness, and enrichment. Auto-recovers Docker/ThetaData when possible. **Run this first in every session.** |
| `alex-github-update` | Publish dev skills to the GitHub marketplace. Handles version bumps, rename transforms, support-file sync, commits, and pushes. |
| `alex-normalize-statistics` | Run `get_statistics` via MCP and normalize P&L / margin to per-contract terms for cross-strategy comparison. |

### Entry filter analysis

| Skill | Purpose |
|-------|---------|
| `alex-entry-filter-build-data` | Build the shared `entry_filter_data.csv` for a block — one row per trade, every filter column + per-trade 1-lot economics + holiday-proximity enrichment. Upstream of every other entry-filter skill. |
| `alex-entry-filter-enrich-market-holiday` | Add Days_to_Holiday / Weeks_to_Holiday / Days_from_Holiday / Weeks_from_Holiday columns to `entry_filter_data.csv`. |
| `alex-entry-filter-threshold-sweep` | Pre-compute retention sweep results for every continuous AND categorical/binary entry filter. Writes two sibling CSVs (`entry_filter_threshold_results.csv` + `entry_filter_categorical_results.csv`) that downstream reports consume without recomputing. |
| `alex-entry-filter-heatmap` | Three-section retention heatmap: Discovery Map (global, 80r%-sorted), By Filter Group (per-Entry-Group Min/Max/Combo), Binary & Categorical Breakdown (clickable In/Out). Every cell click-captures a filter expression into a floating selections panel; Copy-to-clipboard feeds `alex-create-datelist`. |

### Threshold exploration

| Skill | Purpose |
|-------|---------|
| `alex-entry-filter-threshold-analysis` | Single-filter deep dive — threshold sweep, scatter, efficiency frontier with interactive zoom, and OO filter translation. Use when a heatmap cell surfaces an interesting filter and you want to explore its full curve. |
| `alex-create-datelist` | Generate OO-compatible datelists from filter expressions. Emits two code blocks: specific dates (AND-intersection, OO whitelist slot) and blackout dates (per-filter, OO blackout slot). |

---

## Installation (for plugin users)

### Via marketplace (recommended)

```
/plugin marketplace add goodorigamiman/alex-tradeblocks-skills
/plugin install alex-tradeblocks@alex-tradeblocks-skills
```

Then quit and relaunch Claude Code to activate.

### Persist MCP approval

After installation, add this to `~/.claude/settings.json` so you don't have to click "approve" on every session:

```json
"enabledMcpjsonServers": ["tradeblocks"]
```

(Replace `"tradeblocks"` with whatever key your project's `.mcp.json` uses for the TradeBlocks MCP server.)

---

## Requirements

- **[TradeBlocks MCP server](https://github.com/davidromeo/tradeblocks)** running via Docker compose in `$TB_ROOT/.mcp/`
- **Docker Desktop** (or Docker Engine on Linux)
- **Market data provider** — ThetaData (local daemon), Massive.com, or equivalent
- **Python 3 with `duckdb` and `pyyaml`** packages installed
- **GitHub CLI (`gh`)** authenticated — only needed for the `alex-tradeblocks-startup` drift check
- **Option Omega CSV exports** imported into block folders

No cross-plugin dependencies — every skill is self-contained.

### Before your first run — pre-flight checklist

`alex-tradeblocks-startup` will check and auto-recover where it can, but a clean first run is easier if you've got these in place beforehand:

- [ ] **TradeBlocks MCP installed** — see [davidromeo/tradeblocks](https://github.com/davidromeo/tradeblocks). This creates `$TB_ROOT/.mcp/docker-compose.yml`, `$TB_ROOT/analytics.duckdb`, and `$TB_ROOT/market.duckdb`.
- [ ] **Claude Code project config** — `$TB_ROOT/.mcp.json` points to your MCP server (created by the TB MCP installer or added manually).
- [ ] **Environment file** — `$TB_ROOT/.env` has `MARKET_DATA_PROVIDER=thetadata` (or your provider) plus any API credentials.
- [ ] **Docker Desktop installed and launchable** — you don't need to start it yet; the skill can auto-start on macOS/Linux.
- [ ] **Python 3** with `duckdb` and `pyyaml`: `python3 -m pip install duckdb pyyaml`.
- [ ] **GitHub CLI authenticated**: `gh auth login` (used only to check plugin drift against upstream).
- [ ] **Market data provider daemon** (if applicable) — e.g., ThetaTerminal jar downloaded. You don't need to start it; the skill can auto-start if you provide the command during first-run setup.

On first run, the startup skill probes every one of these and tells you exactly what's missing. **You can run it even if your install is incomplete** — it'll guide you through fixes rather than silently failing.

---

## Recommended daily workflow

The single most important thing: **start Docker and let it fully initialize *before* launching Claude Code**. The MCP client is bootstrapped once at session start and doesn't retry — if Docker isn't up or the MCP container hasn't bound its port when Claude launches, the tools won't be available for that entire session.

### The 3-step rhythm

1. **Start Docker Desktop** (menu bar icon → open). Wait for the icon to stop animating.
2. **Confirm the MCP container is up** — `docker ps` should show `tradeblocks-mcp` as `Up` with the configured port bound. This usually takes ~30–60 seconds after Docker starts.
3. **Launch Claude Code from your TradeBlocks Data root.** Run `/alex-tradeblocks:alex-tradeblocks-startup` as your first action — it verifies every layer and flags anything out of place.

Why this order matters:
- If Docker isn't up when Claude launches, the MCP client fails to connect → no MCP tools this session → you have to quit and relaunch.
- If the MCP container is booting but hasn't bound the port yet, the MCP client may connect in a broken state → same outcome.
- Launching Claude from the correct directory ensures `.mcp.json` is discovered.

### How long to wait

Timing varies by machine:
- Fast SSD, recent MacBook Pro: ~20 seconds from Docker launch to `tradeblocks-mcp` healthy
- Typical desktop: ~45–60 seconds
- First-boot-of-the-day or after system sleep: up to 2 minutes

Rather than timing it, watch `docker ps` for `tradeblocks-mcp | Up N seconds` with port binding visible (`0.0.0.0:3100->3100/tcp` or similar). That's the signal. The startup skill won't help if the MCP client wasn't mounted at session start — it can only report the problem and tell you to relaunch.

### Alternative: let the startup skill recover

If you forgot and Claude is already running:
1. Run `/alex-tradeblocks:alex-tradeblocks-startup`
2. It'll auto-start Docker, the MCP container, and ThetaData if needed, and tell you to quit and relaunch Claude Code.
3. Do that, and your next session will be fully mounted.

You'll only need the recovery path once per "I forgot to pre-start everything" mistake — the recovery log (`alex_tradeblocks_startup_log.md`) records what it did so you can see the pattern.

---

## How `alex-tradeblocks-startup` works (in detail)

The startup skill is **config-driven** with two persistent files in your TradeBlocks Data root:

| File | Purpose | When it's written |
|---|---|---|
| `alex_tradeblocks_startup_config.md` | Local configuration (paths, provider choice, MCP container name, plugin marketplace repos, legacy tables to ignore) | On first run only — never overwritten by skill updates |
| `alex_tradeblocks_startup_log.md` | Recovery action history (what was down, what command was run, how long it took to come up) | Appended each session that needed recovery |

### First-run setup

The first time you run the startup skill, it probes your environment (TB root, dev folder existence, `.env` provider, `.mcp` compose file, plugin marketplaces) and writes `alex_tradeblocks_startup_config.md`. It asks you to confirm each detected value before writing.

Expect questions like:
- *"I found `ThetaData` in your `.env`. What command starts it?"* → Provide the exact shell command so the skill can auto-recover when it's down
- *"You have `Dev-TradeBlocks-Skills/` — is this your dev workspace?"* → Answer yes/no. Pulled-only users answer no and get a simpler report

After first run, subsequent runs read the config silently and skip the interactive setup.

### What each run checks

Every run walks through five layers and stops at the first unrecoverable failure:

1. **Environment pre-flight** — python3, PyYAML, duckdb, gh, curl, git installed?
2. **MCP server** — Layer A (Docker daemon + container + port bound) and Layer B (MCP tools actually mounted in *this* Claude session)
3. **Market data provider** — endpoint reachable; auto-start daemon if configured
4. **Plugin drift** — upstream GitHub HEAD vs marketplace clone vs runtime cache (three-way check, not the stale `gitCommitSha` bookkeeping field)
5. **DuckDB state** — liveness probe, table inventory, market data freshness, enrichment coverage

The final report is one compact block: status summary, `Upstream vs Installed:` table, `Market data coverage:` table, recovery actions taken, config path.

### Learnings captured between sessions

Two mechanisms keep Claude smarter on repeat sessions:

- **CLAUDE.md Dev Skills Registry** — if you have a dev workspace, the skill writes a table of your in-flight dev skills into `$TB_ROOT/CLAUDE.md` between `<!-- DEV-SKILLS-REGISTRY:BEGIN -->` markers. This is auto-loaded by Claude Code on every session in the project, so Claude already knows what dev skills exist before you even invoke one.
- **Recovery log (`alex_tradeblocks_startup_log.md`)** — every recovery action (Docker start, ThetaData start, MCP container up) is logged with a timestamp. Over time this becomes a timing reference ("usually takes 30s") and lets future Claude predict what's likely to need recovery on your machine.

Edit either file by hand if you want — the skill only rewrites the delimited registry block in CLAUDE.md and only appends to the log. Everything else is preserved.

### Managing your config + log files

The two files (`alex_tradeblocks_startup_config.md`, `alex_tradeblocks_startup_log.md`) live in your TradeBlocks Data root and are yours to edit or delete.

**When to hand-edit the config:**

- Your ThetaData / market-provider start command changes
- You move the MCP compose directory
- You upgrade the MCP container image (bump `mcp_image_tag`)
- You add or remove a plugin marketplace
- You want to add a known-deprecated table to `legacy_tables_ignore` so it stops being flagged as stale

Re-running the skill after a hand-edit will pick up your changes — it reads the config fresh each run. If your edit produces a value that disagrees with what the skill detects at runtime, you'll see a "config drift" flag and be asked whether to update the config or investigate.

**If you want to reset and re-run first-run detection:** rename or delete `alex_tradeblocks_startup_config.md`. On the next skill invocation, first-run setup kicks in again with fresh probing.

**When to read the recovery log:**

- You notice the skill is always recovering the same thing — time to fix the root cause (e.g., set Docker to auto-start on login, or add the market-data provider to your login items).
- You're debugging "why was my session slow to start?" — the log has timestamps and commands for each recovery step.
- You're seeing unexpected recoveries — the log tells you which services went down.

The log is append-only. Claude never rewrites or truncates it. **If it grows too large** (thousands of entries across months), you can trim or archive it manually: move the old content into `alex_tradeblocks_startup_log.YYYY.md` and let the skill start fresh on the active file. The skill doesn't depend on historical entries.

**What NOT to edit:**

- Don't edit the `<!-- DEV-SKILLS-REGISTRY:BEGIN -->` ... `<!-- DEV-SKILLS-REGISTRY:END -->` block in `$TB_ROOT/CLAUDE.md` by hand. The skill rewrites it on every run with a dev workspace. Anything outside those markers is yours to edit freely.

### If first-run setup fails

Most common causes:

| Symptom | Likely cause | Fix |
|---|---|---|
| *"No MCP compose file found"* | TradeBlocks MCP not installed | Install per [davidromeo/tradeblocks](https://github.com/davidromeo/tradeblocks), then re-run |
| *"market.duckdb MISSING"* | Databases not created yet | Run the TradeBlocks MCP install + initial data import, then re-run |
| *"I don't know what command starts your provider"* | You haven't given ThetaTerminal / Massive a start script | Enter the exact shell command when prompted, or leave blank if cloud-hosted |
| *"python3 -c 'import yaml'" fails* | PyYAML not installed | `python3 -m pip install pyyaml duckdb` |
| *"gh: command not found"* | GitHub CLI missing | `brew install gh && gh auth login` (macOS) or equivalent |
| Config gets stuck with wrong values | Skill probed wrong env | Delete `alex_tradeblocks_startup_config.md`, edit `.env` to fix the underlying cause, re-run |

First-run writes the config only at the very end, after you've confirmed all values. If anything fails before then, no config file gets written — you can safely re-run.

---

## Troubleshooting

### MCP tools aren't showing up

Symptom: the startup skill says `session tools: NOT mounted — QUIT & RELAUNCH CLAUDE CODE`, or you try to call an MCP tool and it's not recognized.

Root cause: Claude Code bootstrapped MCP servers at session start when Docker or the MCP container wasn't ready. Two common triggers:
- You launched Claude Code before Docker finished starting
- The `"enabledMcpjsonServers"` setting doesn't include the tradeblocks key, so Claude is waiting for you to click "approve"

Fix:
1. Add `"enabledMcpjsonServers": ["tradeblocks"]` to `~/.claude/settings.json`
2. Confirm Docker is up and `tradeblocks-mcp` is running (`docker ps`)
3. **Quit** Claude Code (Cmd+Q on Mac) and relaunch from your TB root. `/clear` / `/reset` inside the same session will not help — the MCP client only rebuilds on a fresh process.

### Plugin shows DRIFT but files look fine

Symptom: `Upstream vs Installed:` table shows `DRIFT` for a plugin even though you just updated it.

Root cause: `installed_plugins.json → gitCommitSha` bookkeeping lag. The startup skill's 4.0-dev drift check compares upstream HEAD vs marketplace clone vs cache files directly (`diff -rq`), so this should no longer produce false positives. If you still see it, re-run the startup skill — the corrective runs only when status is OK.

### Market data is stale

Symptom: `[✗] DuckDB market: <old date> (stale — update to <newer>?)`.

Fix: confirm the prompt to update. The skill runs `python3 Scripts/update_market_data.py` which appends new bars via ThetaData REST + MCP imports and runs enrichment. Note: the standing script only enriches QQQ/SPX/SPY/IWM; VIX family stays raw (this is a pipeline scope issue, not a skill bug).

### "DuckDB MISSING" on fresh install

Symptom: `market.duckdb MISSING — fresh install?`

Fix: you haven't completed the TradeBlocks setup yet. Follow the install docs at https://github.com/davidromeo/tradeblocks to create the databases, then re-run the startup skill.

### Docker won't auto-start

Platform-specific:
- **macOS**: `open -a Docker` should work; if it doesn't, launch Docker Desktop manually from Applications
- **Linux**: the skill tries `systemctl start docker` which may require sudo — if it prompts, start it manually
- **Windows**: the skill will tell you to launch Docker Desktop by hand (automation there is unreliable)

---

## Development workflow

The dev loop is:

1. **Develop in `Dev-TradeBlocks-Skills/dev-<name>/`** — create or edit `SKILL.md`, `.py` modules, `.sql` templates. Test immediately as `/dev-<name>` (no publish needed).
2. **Iterate until ready** — the `dev-tradeblocks-startup` skill keeps the `CLAUDE.md` Dev Skills Registry in sync so you can reference dev skills across sessions.
3. **Publish when ready** — run `/alex-tradeblocks:alex-github-update`. It handles:
   - Rename `dev-<name>/` → `alex-<name>/`
   - Strip `-dev` from frontmatter version
   - Sync `_shared/` to the repo's `_shared/` folder (mirrors this dev layout)
   - Bump `plugin.json` + `marketplace.json` versions
   - Commit and push to GitHub
4. **Refresh cache** — after a successful publish, `/plugin` → update → quit and relaunch Claude Code.

The publish target repo path is configured in `alex_github_update_config.md` at the TB root.

---

## License

MIT
