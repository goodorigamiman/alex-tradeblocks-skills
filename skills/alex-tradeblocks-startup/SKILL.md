---
name: alex-tradeblocks-startup
description: TradeBlocks startup check. Verifies MCP server, market data provider, skills (published + local dev), and DuckDB databases. Auto-starts services if down. Reads `startup_config.md` in the TradeBlocks Data root for user-specific paths and settings; on first run, discovers values and writes the config. Use at session start or when TradeBlocks tooling feels broken.
compatibility: Requires Docker. Market data provider (ThetaData, Massive, or other) and dev workspace layout are discovered from the local config — no assumptions baked in.
metadata:
  author: alex-tradeblocks
  version: "3.0"
---

# Dev TradeBlocks Startup

Walk through the health checks in order (MCP server, market provider, skills inventory, DuckDB databases + data freshness + enrichment). For each: probe, report, and auto-recover if possible. Record recovery steps to `startup_log.md`. The skill is **config-driven**: on first run it discovers user-specific values and writes `startup_config.md`; on subsequent runs it reads that file first and uses the stored paths, provider choice, repo sources, etc.

---

## Step 0: Load (or Create) Local Config

Look for `$TB_ROOT/startup_config.md` (where `$TB_ROOT` is the TradeBlocks Data root — typically the current working directory, or the nearest ancestor containing `analytics.duckdb` and `market.duckdb`).

### If config exists

**Parse the YAML frontmatter with a real YAML parser** — not grep or regex. The frontmatter has nested keys (`plugin_marketplaces:`, `forbidden_env_vars:`, `legacy_tables_ignore:`) and line-matching approaches silently drop the nested children. Use:

```python
import re, yaml, pathlib
txt = pathlib.Path('startup_config.md').read_text()
fm = re.search(r'^---\n(.*?)\n---', txt, re.DOTALL).group(1)
config = yaml.safe_load(fm)
# config is now a dict with all nested keys intact
```

If PyYAML is unavailable, install with `pip install pyyaml` or fall back to a Python dict literal parse — do NOT use line-by-line regex.

Use the parsed values for all subsequent steps. If any stored value disagrees with what you detect (e.g. config says `provider: thetadata` but `.env` says `massive`), flag it as a **config drift** in the final summary and ask the user whether to update the config or investigate.

### If config does NOT exist (first run)

Detect the following by probing, then present the detected values to the user and ask for confirmation before writing the config:

| Key | How to detect |
|---|---|
| `tb_root` | Directory containing `analytics.duckdb` and `market.duckdb` |
| `dev_skills_folder` | Look for a folder in `$TB_ROOT` matching `Dev-*Skills*`, `*-dev-skills`, or similar. If multiple or none, ask the user. Store as a path relative to `tb_root`, or absolute if outside. Set to `none` if the user has no local dev workspace. |
| `market_provider` | Read `$TB_ROOT/.env` for `MARKET_DATA_PROVIDER`. Common values: `thetadata`, `massive`, `polygon`. If unset, ask the user. |
| `market_provider_endpoint` | Read `.env` for the provider-specific URL (e.g. `THETADATA_BASE_URL`, `MASSIVE_API_URL`). For cloud APIs with only a key (no URL), store `cloud`. |
| `market_provider_start_cmd` | Ask the user for the exact command to start their provider (e.g. for ThetaData: `cd ~/ThetaTerminal && nohup java -jar ThetaTerminalv3.jar > theta.log 2>&1 &`). Optional — leave blank if the provider is always-on / cloud. |
| `market_provider_process_name` | The process name for `pgrep -f` to check if the provider daemon is running (e.g. `ThetaTerminalv3.jar`). Blank for cloud providers. Derive from `market_provider_start_cmd` if obvious, otherwise ask the user. |
| `mcp_image_tag` | Read `$TB_ROOT/.mcp/tradeblocks-mcp.version` |
| `mcp_container_name` | Read `$TB_ROOT/.mcp/docker-compose.yml` — grep `container_name:` |
| `mcp_compose_dir` | `.mcp` (relative to `tb_root`) |
| `plugin_marketplaces` | Parse `~/.claude/plugins/installed_plugins.json` — each plugin id → its `extraKnownMarketplaces` entry in `~/.claude/settings.json` has the GH repo |
| `legacy_tables_ignore` | Ask the user if they have any tables in `market.duckdb` that show stale dates but are known deprecated. Default empty. |

Write the result to `$TB_ROOT/startup_config.md` using the schema in the Config Schema section below.

**Never write user-specific values (paths, repo names, provider choice) into the SKILL.md itself.** That file is the published skill; it gets overwritten on update. All user-specific state lives in `startup_config.md` which the skill only creates, never overwrites.

### Updating an existing config

If values change (user moves dev folder, swaps provider, bumps MCP image), the user should edit `startup_config.md` by hand. The skill detects drift and prompts — it does not silently overwrite.

---

## Step 1: TradeBlocks MCP Server

**Probe:** Call `list_blocks` via the MCP tool interface.

If unavailable:
1. Check Docker daemon: `docker info`. If Docker is not running, start it: `open -a Docker` (macOS) or equivalent; poll every 3s up to 30s for `docker info` to succeed.
2. Start the MCP container: `cd $TB_ROOT/{mcp_compose_dir} && docker compose up -d`
3. Wait 5s, re-probe. If still failing, tail `docker compose logs --tail=40` and surface to user.

**Report:** MCP image tag (from config), # blocks (from `list_blocks`), # tools available, recovery actions taken.

---

## Step 2: Market Data Provider

Use `{market_provider}` from config to select probe + recovery path.

### Providers with local daemons (e.g. thetadata)

**Probe:** `curl` the provider's known-good endpoint from config `{market_provider_endpoint}`. For ThetaData: `curl -s -m 3 "{endpoint}/v3/index/history/eod?symbol=SPX&start_date=<recent>&end_date=<recent>&format=json"` — parse for expected keys.

If down:
1. Check process: `pgrep -f <daemon-process-name>`
2. Start with `{market_provider_start_cmd}` from config
3. Wait 10s, re-probe. Retry once after another 10s if first fails.
4. If still down, show relevant log tail.

### Providers without local daemons (cloud APIs)

**Probe:** simple GET against the documented health endpoint. Report version if available. No auto-start applicable.

**Report:** provider name, status (OK / recovered / failed), version if retrievable, recovery actions.

---

## Step 3: Skills & Version Inventory

Three slices: (A) upstream vs installed, (B) loaded cache set, (C) local dev vs cache.

### 3A. Upstream vs installed

For each plugin in `plugin_marketplaces` from config:
- Fetch upstream HEAD sha: `gh api repos/{gh_repo}/commits/main --jq '.sha[0:7]'`
- Read installed sha from `~/.claude/plugins/installed_plugins.json` (field `gitCommitSha`, first 7 chars)
- Compare → OK or DRIFT

For the MCP server (if `mcp_source: npm`):
- Upstream: `curl -s https://registry.npmjs.org/{mcp_package_name}/latest | jq -r .version`
- Installed: `{mcp_image_tag}` from config
- Compare (normalize `2.3` vs `2.3.0` to same form before comparing)

Output as a single compact table with columns: Component | Upstream | Installed | Status. Suggest the update command for any DRIFT row.

### 3B. Loaded cache set

For each plugin in `plugin_marketplaces`, glob `~/.claude/plugins/cache/<mkt>/<plugin>/<ver>/skills/*/SKILL.md` and list skill names. One row per namespace, comma-separated skill list. No per-skill versions — this section just confirms what's loaded.

### 3D. Tools & Skills Inventory Table

After completing 3A–3C, emit a consolidated table showing every tool/skill source available in the environment. This gives a single at-a-glance view of what Claude can use.

**Collect counts from prior steps:**
- **MCP tools:** count distinct tool names available from the TradeBlocks MCP server (from the Step 1 probe — e.g. `list_blocks`, `get_statistics`, `run_sql`, etc.)
- **Plugin skills:** for each plugin in `plugin_marketplaces`, count the skills found in the cache glob from 3B. Read version from `~/.claude/plugins/installed_plugins.json` (`version` field).
- **Dev skills:** count from the dev folder glob in 3C. Use `--` for version since dev skills have individual versions.

**Output format** (compact monospace, column-aligned):

```
Tools & Skills:
  Source                     Type        Location                                Version  Count
  TradeBlocks MCP            MCP server  .mcp/ (tradeblocks-mcp)                 2.3      M tools
  tradeblocks-skills         Plugin      davidromeo/tradeblocks-skills            1.0.0    9 skills
  alex-tradeblocks-skills    Plugin      goodorigamiman/alex-tradeblocks-skills   1.2.0    3 skills
  Dev-TradeBlocks-Skills     Local dev   Dev-TradeBlocks-Skills/                  --       11 skills
```

Location values come from `plugin_marketplaces` in config (GitHub repo for plugins, compose dir for MCP, folder name for dev).

### 3C. Local dev vs cache + Dev Skills Registry

Skip this section entirely if `dev_skills_folder: none` in config.

Otherwise, do two things:

**(i) Drift table** (version comparison — same as before):

1. Glob `$TB_ROOT/{dev_skills_folder}/*/SKILL.md`
2. For each dev skill, read `version:` from frontmatter
3. Try to match to a cache skill by stem (strip leading `dev-` from dev name, try each cache namespace with and without prefix additions like `alex-`)
4. Compare:
   - Dev version ending in `-dev` → **DEV-AHEAD** if cache version is lower, **DEV-ONLY** if no cache match
   - Dev version lower than cache → **REGRESSION** (flag loudly)
   - Dev version equals cache → **OK (synced)**

**(ii) Dev Skills Registry — write into project `CLAUDE.md`** (persists across sessions):

The goal is for the dev skills to be **known to Claude in every future session of this project, without running startup each time**. Solution: inline the registry into `$TB_ROOT/CLAUDE.md`, which Claude Code auto-loads on every session whose cwd is inside the project tree. The skill rewrites only a delimited section; everything else in CLAUDE.md is preserved.

**Steps:**

1. Glob `$TB_ROOT/{dev_skills_folder}/*/SKILL.md`.
2. For each dev skill, parse frontmatter with `yaml.safe_load` (NOT line-grep — handles folded-scalar descriptions correctly). Extract `name`, `metadata.version`, `description`.
3. Build the registry block using the template below. Truncate descriptions to ~160 chars. Replace smart quotes / ensure ASCII.
4. Open `$TB_ROOT/CLAUDE.md`:
   - Look for the marker pair: `<!-- DEV-SKILLS-REGISTRY:BEGIN -->` … `<!-- DEV-SKILLS-REGISTRY:END -->`
   - If markers exist: replace the content strictly between them (inclusive of the markers). Nothing outside is touched.
   - If markers don't exist: append a blank line + the full block (with markers) to the end of CLAUDE.md.
5. Write CLAUDE.md back.

**Registry block template:**

```markdown
<!-- DEV-SKILLS-REGISTRY:BEGIN (auto-generated by dev-tradeblocks-startup — do not edit by hand; re-run skill to refresh) -->
## Dev Skills Registry ({N} skills, last updated {YYYY-MM-DD})

Skills under active development in `{dev_skills_folder}/`. Read the full `SKILL.md` at the listed path when invoking one of these. Dev versions take precedence over any same-stem cache skill.

| Skill | Version | Purpose |
|---|---|---|
| dev-entry-filter-pareto | 3.0-dev | [one-line description, ≤160 chars] |
| ... | ... | ... |

Paths: `{tb_root}/{dev_skills_folder}/<skill-name>/SKILL.md`
<!-- DEV-SKILLS-REGISTRY:END -->
```

**Rules for when the user later invokes a dev skill:**

- If user says "run dev-X" or references a skill name from this registry: **read the full SKILL.md at the listed path** and execute its instructions. Do not guess or substitute the cache version.
- If user says "run X" (no `dev-` prefix) and a dev version exists with the same stem: note the ambiguity and ask which they want. Dev is usually the intended one when the user is actively developing it.
- If the skill at the path has moved or no longer exists: flag stale registry, suggest re-running startup.

**One-line summary after registry:** "N dev skills · M ahead of cache · K dev-only · 0 regressions · CLAUDE.md registry updated."

### Why this design

- **Survives skill updates** — the registry lives in `CLAUDE.md` at the TB root, not in the skill folder. Pulling a new `SKILL.md` from GitHub can't touch it.
- **Survives session restart** — Claude Code reads `CLAUDE.md` on every session whose cwd is inside the project. Claude starts each session already knowing the dev skills exist.
- **Project-scoped** — opening Claude from outside the TB root does NOT load this registry. No pollution of unrelated projects.
- **Preserves user edits** — only the content between the `BEGIN`/`END` markers is rewritten. Any other content in CLAUDE.md (trigger tables, analysis rules, notes) is left alone.
- **Simpler than a sidecar file** — one fewer file to manage, and the file that gets loaded is the same one that already gets loaded.

### Context-cost note

Each dev skill adds roughly one table row (~50–100 tokens). 8 skills ≈ 500 tokens of every-session overhead, for the win of Claude always knowing what's in-flight. If the dev folder exceeds ~20 skills and the budget matters, add a `dev_registry_verbosity: compact` flag in config to drop descriptions and keep just the names.

---

## Step 4: DuckDB Databases

### 4A. Liveness & Table Inventory

**Liveness probe** (read-only, safe):

```python
import duckdb
for path in ['{tb_root}/analytics.duckdb', '{tb_root}/market.duckdb']:
    try:
        with duckdb.connect(path, read_only=True) as con:
            con.execute('SELECT 1').fetchone()
            print(path, 'OK')
    except Exception as e:
        print(path, 'ERROR', str(e)[:200])
```

If locked, do NOT force-kill. Report and ask the user.

**Table inventory** — for each database, list all schemas and tables with row count, latest date (if date column exists), and status. Use read-only Python connections:

```python
import duckdb
for db_name, db_path in [('analytics', '{tb_root}/analytics.duckdb'), ('market', '{tb_root}/market.duckdb')]:
    with duckdb.connect(db_path, read_only=True) as con:
        # Query information_schema for all tables, row counts, and max date
        ...
```

**Status classification per table:**
- **Active**: table is populated and being updated by the daily pipeline (latest date is recent)
- **Active (derived)**: `_`-prefixed tables that are actively maintained and queried (e.g. `_context_derived`). These are derived/enrichment tables — distinguish from raw-data tables but treat as active.
- **Superseded**: table exists but is no longer updated — listed in `legacy_tables_ignore` from config, or latest date is frozen well behind active tables. Mark with the reason (e.g. "migrated to daily + _context_derived on 2026-03-26")
- **Empty**: table exists but has 0 rows (schema placeholder, not yet populated)
- **Internal**: `_`-prefixed tables that are purely operational and not queried for analysis (e.g. `_sync_metadata`)

**Output format:**

```
DuckDB table inventory:
  analytics.duckdb:
    Schema     Table               Rows    Latest       Status
    profiles   strategy_profiles      1    --           Active
    trades     trade_data        19,976    --           Active
    trades     reporting_data        88    --           Active
    trades     _sync_metadata        13    --           Internal

  market.duckdb:
    Schema     Table               Rows    Latest       Status
    market     daily             32,312    2026-04-14   Active
    market     _context_derived   5,123    2026-04-14   Active (derived)
    market     intraday         708,238    2026-04-14   Active
    market     context            5,089    2026-03-25   Superseded (migrated to daily + _context_derived)
    market     _sync_metadata       961    --           Internal
    market     data_coverage          0    --           Empty
    market     option_chain           0    --           Empty
```

Cross-reference `legacy_tables_ignore` from config to label superseded tables. If a table not in the ignore list has a latest date far behind the active tables, flag it as **Possibly stale** and ask the user whether it should be added to `legacy_tables_ignore`.

### 4B. Market Data Freshness

**Query** via read-only Python or MCP `run_sql`:

```sql
SELECT ticker, COUNT(*) AS n, MIN(date) AS earliest, MAX(date) AS latest
FROM market.daily GROUP BY ticker ORDER BY ticker;

SELECT COUNT(*) AS n, MAX(date) AS latest FROM market._context_derived;
```

**Skip any tables listed in `legacy_tables_ignore` from config** — those are known-deprecated and are expected to show stale dates.

**Staleness check:** compute the expected latest date as the most recent past weekday (yesterday if yesterday was a weekday, otherwise last Friday). If any ticker's latest date is behind the expected date, the data is stale.

**Staleness prompt:** if latest date is behind the expected date, prompt with specific dates: *"Market data latest is YYYY-MM-DD. Update through YYYY-MM-DD (yesterday)?"* Do not auto-run — wait for user confirmation. If user confirms, run `python3 Scripts/update_market_data.py`.

### 4C. Calculated Fields Health Check

After the ticker coverage table, verify that enriched/derived columns are fully populated and current. This catches enrichment failures, partially-enriched tickers, or new tickers that were imported but never enriched.

**Enriched columns to check — detect dynamically:**

Do NOT hardcode column lists. Instead, query the schema and exclude the known raw OHLCV columns:

```python
RAW_COLUMNS = {'ticker', 'date', 'open', 'high', 'low', 'close'}

# For market.daily:
all_cols = con.execute("SELECT column_name FROM information_schema.columns WHERE table_name='daily'").fetchall()
enriched_daily = [c[0] for c in all_cols if c[0] not in RAW_COLUMNS]

# For _context_derived:
all_cols = con.execute("SELECT column_name FROM information_schema.columns WHERE table_name='_context_derived'").fetchall()
enriched_ctx = [c[0] for c in all_cols if c[0] != 'date']
```

This ensures new enrichment columns are automatically checked without updating the skill.

**Enrichment tickers — detect dynamically:**

Do NOT hardcode the ticker list. Instead, identify which tickers have enriched data by sampling:

```python
# Pick the first enriched column from market.daily
sample_col = enriched_daily[0]
enrichment_tickers = con.execute(f"""
    SELECT DISTINCT ticker FROM market.daily
    WHERE "{sample_col}" IS NOT NULL
    ORDER BY ticker
""").fetchall()
enrichment_tickers = [t[0] for t in enrichment_tickers]
```

Index-only tickers (VIX, VIX3M, VIX9D, etc.) will naturally be excluded because they have NULL enriched columns.

**SQL approach** — for each enrichment ticker, run one query per table:

```sql
-- For market.daily, per ticker:
SELECT '{ticker}' AS ticker,
       MAX(date) AS max_date,
       MAX(CASE WHEN Prior_Close IS NOT NULL THEN date END) AS Prior_Close_latest,
       MAX(CASE WHEN Gap_Pct IS NOT NULL THEN date END) AS Gap_Pct_latest,
       -- ... repeat for each enriched column ...
       MAX(CASE WHEN ivp IS NOT NULL THEN date END) AS ivp_latest
FROM market.daily WHERE ticker = '{ticker}';

-- For _context_derived (no ticker dimension):
SELECT MAX(date) AS max_date,
       MAX(CASE WHEN Vol_Regime IS NOT NULL THEN date END) AS Vol_Regime_latest,
       MAX(CASE WHEN Term_Structure_State IS NOT NULL THEN date END) AS Term_Structure_State_latest,
       MAX(CASE WHEN Trend_Direction IS NOT NULL THEN date END) AS Trend_Direction_latest,
       MAX(CASE WHEN VIX_Spike_Pct IS NOT NULL THEN date END) AS VIX_Spike_Pct_latest,
       MAX(CASE WHEN VIX_Gap_Pct IS NOT NULL THEN date END) AS VIX_Gap_Pct_latest
FROM market._context_derived;
```

**Status logic per field:**
- **Current**: latest non-null date == max date for that ticker/table
- **Stale**: latest non-null date < max date (enrichment lagging behind raw data)
- **Empty**: all values are NULL (enrichment never ran for this field)

**Output format — compact unless issues found:**

When all fields are current:
```
Calculated fields:
  market.daily:            28 enriched fields · all current through 2026-04-14
  market._context_derived:  5 enriched fields · all current through 2026-04-14
```

When issues exist, expand only the problem fields:
```
Calculated fields:
  market.daily:            28 enriched fields · 26 current · 2 STALE:
    ivr   (SPY): latest non-null 2026-04-10 (4 bdays behind)
    ivp   (SPY): latest non-null 2026-04-10 (4 bdays behind)
  market._context_derived:  5 enriched fields · all current through 2026-04-14
```

**Enrichment staleness prompt:** if any calculated fields are STALE (not EMPTY — empty fields are a schema/pipeline gap to report, not something the update script fixes), prompt: *"Calculated fields are behind raw data (latest enriched: YYYY-MM-DD, latest raw: YYYY-MM-DD). Re-run enrichment?"* Do not auto-run — wait for user confirmation. If user confirms, run `enrich_market_data` via the MCP tool for each affected ticker.

Note: EMPTY fields (e.g. ivr/ivp that have never been populated) should be reported as a gap but not offered for re-run — they indicate a pipeline limitation, not a stale-data problem.

**Report:** per-ticker coverage table, table inventory, calculated fields check, staleness prompts (market data + enrichment) if applicable.

---

## Final Summary

Emit one compact block:

```
TradeBlocks Startup — YYYY-MM-DD HH:MM

[✓|✗] MCP Server        {image_tag}  · N blocks  · M tools
[✓|✗] Market Provider   {provider}   · <version/status>
[✓|✗] Skills            <OK|DRIFT>  · dev: N skills (M ahead, K dev-only)
[✓|✗] DuckDB            N tables (M active, K superseded, J empty) · analytics: OK
[✓|✗] Market Data       latest: <date> (<current|stale — update to YYYY-MM-DD?>)
[✓|✗] Enrichment        N fields · all current (or: K STALE — re-run enrichment?)

Recovery actions this session: <list or "none">
Config: {tb_root}/startup_config.md
```

Then emit the detail sections (each only if non-empty or always shown):
1. **Upstream vs Installed** table (always)
2. **Tools & Skills** table (always)
3. Dev skills one-liner (always, if dev folder exists)
4. **DuckDB table inventory** (always — both databases, all tables with status)
5. **Market data coverage** ticker table (always)
6. **Calculated fields** check (always)
7. Plugin update commands (only if DRIFT detected)
8. **Staleness prompts** (only if market data or enrichment is behind — ask user before running)

---

## Recovery Log (`startup_log.md`)

Only append when recovery actions were taken. Format:

```markdown
## YYYY-MM-DD HH:MM
- <what was down>. Ran: `<exact command>`. Ready after ~Ns.
```

One bullet per action with the exact command used. Serves as a reference for repeat-session speedup.

---

## Config Schema (`startup_config.md`)

Use this template when writing the config file on first run. YAML frontmatter holds parsed values; the body is free-form notes.

```markdown
---
schema_version: 1

# Paths
tb_root: /path/to/TradeBlocks Data
dev_skills_folder: Dev-TradeBlocks-Skills  # relative to tb_root, or absolute, or "none"

# Market data provider
market_provider: thetadata                   # thetadata | massive | polygon | other
market_provider_endpoint: http://127.0.0.1:25503
market_provider_start_cmd: "cd ~/ThetaTerminal && nohup java -jar ThetaTerminalv3.jar > theta.log 2>&1 &"
market_provider_process_name: ThetaTerminalv3.jar   # for pgrep; blank for cloud providers
forbidden_env_vars:                          # vars that MUST NOT be set (e.g. after cutover)
  - MASSIVE_API_KEY

# MCP server
mcp_source: npm                              # npm | ghcr | other
mcp_package_name: tradeblocks-mcp
mcp_image_tag: "2.3"                         # matches .mcp/tradeblocks-mcp.version
mcp_container_name: tradeblocks-mcp
mcp_compose_dir: .mcp

# Plugin marketplaces (plugin_id → GitHub repo)
plugin_marketplaces:
  tradeblocks@tradeblocks-skills: davidromeo/tradeblocks-skills
  alex-tradeblocks@alex-tradeblocks-skills: <user>/<fork-or-personal-repo>

# DuckDB
analytics_db: analytics.duckdb
market_db: market.duckdb
legacy_tables_ignore:
  - market.context   # example: migrated to market.daily + _context_derived on YYYY-MM-DD
---

# TradeBlocks Startup — Local Config

Notes and context for the startup skill. This file is generated on first run and NEVER overwritten by skill updates.

Edit by hand if your environment changes (e.g. switching providers, moving the dev folder, bumping MCP image).

## Known quirks

(free-form — document one-off things the skill should know. Examples:)

- **DB lock contention**: the persistent MCP container holds the DuckDB lock. Update scripts auto-stop/start it.
- **Massive cutover** (YYYY-MM-DD): project is ThetaData-only. `MASSIVE_API_KEY` must not be set.
```

---

## What Goes Where — Design Rules

| Belongs in `SKILL.md` (published) | Belongs in `startup_config.md` (local) |
|---|---|
| The four-step process | TradeBlocks Data root path |
| Probe logic (generic) | Dev skills folder (if any, and where) |
| Config schema template | Market data provider choice |
| Drift detection rules | Provider endpoint URL |
| Report format | Provider start command |
|  | MCP image tag, container name, package source |
|  | List of personal/fork GitHub repos |
|  | Legacy tables/fields to ignore |
|  | Free-form quirks specific to this install |

If a future skill version needs to change *how* a thing works (e.g. different probe endpoint because the provider API changed), update `SKILL.md`. If the *value* of something changes (e.g. user moved to a new TB data root), edit `startup_config.md`.

---

## What NOT to Do

- Do not hardcode user paths, repo names, or provider choices in `SKILL.md`.
- Do not overwrite `startup_config.md` on any run except the very first. Subsequent runs may only append notes under existing sections if explicitly asked.
- Do not silently ignore config drift — if detected values don't match the config, surface it and ask.
- Do not force-kill processes or containers without user confirmation.
- Do not auto-run the market data update or enrichment re-run — only prompt and wait for user confirmation.
