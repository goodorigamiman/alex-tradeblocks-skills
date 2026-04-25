---
name: alex-tradeblocks-startup
description: TradeBlocks startup check (3.0 Parquet-mode aware). Verifies MCP server, market data provider, skills (published + local dev), analytics DuckDB, Parquet market data, enrichment, and optional SqueezeMetrics reference data. Status block splits Parquet and DuckDB into their own rows so each backend's health is visible at a glance. Always tail-ends the report with a Root Organization memory-refresher (database files, market Parquet layout, alex-data, dev workspace, MCP files) so the user re-anchors on the folder layout at session start. Auto-starts services if down. Reads `alex_tradeblocks_startup_config.md` in the TradeBlocks Data root for user-specific paths and settings; on first run, discovers values and writes the config. Use at session start or when TradeBlocks tooling feels broken.
compatibility: Requires Docker + TradeBlocks MCP 3.0+ in Parquet mode. Market data probes route through the MCP (`run_sql` over registered views that read Parquet). Market data provider (ThetaData, Massive, or other) and dev workspace layout are discovered from the local config — no assumptions baked in.
metadata:
  author: alex-tradeblocks
  version: "5.2.0"
---

# Dev TradeBlocks Startup

Walk through the health checks in order (MCP server, market provider, skills inventory, analytics DB + Parquet market views + freshness + enrichment + optional SqueezeMetrics). For each: probe, report, and auto-recover if possible. Record recovery steps to `alex_tradeblocks_startup_log.md`. The skill is **config-driven**: on first run it discovers user-specific values and writes `alex_tradeblocks_startup_config.md`; on subsequent runs it reads that file first and uses the stored paths, provider choice, repo sources, etc.

### Pulled-only vs dev modes

This skill supports two user profiles and detects which one applies from `dev_skills_folder` in config:

- **Pulled-only user** — `dev_skills_folder: none`. No local dev workspace. The skill runs Steps 0, 1, 2, 3A, 3B, 3D, 4 and the Final Summary. **It skips all dev-folder logic** (Step 3C, the `Local dev` row in the Tools & Skills table, the `· dev: ...` suffix in the Final Summary, and the CLAUDE.md Dev Skills Registry writeback). Skills drift is evaluated purely as upstream-GH vs marketplace-clone vs cache — exactly what a pulled user needs. Config first-run detects `none` automatically when no `Dev-*Skills*` folder is found in `$TB_ROOT`; the user is asked to confirm.
- **Dev user** — `dev_skills_folder: <path>`. Additional Step 3C compares dev skills against their cache counterparts, maintains the CLAUDE.md registry, and flags unpublished changes.

Nothing in the pulled-only path touches the dev folder, writes a registry, or assumes its existence. If you're reading this as a pulled user: everything below that mentions dev folders, `Dev-*Skills`, or the registry is a no-op for you.

---

## Step 0: Load (or Create) Local Config

Look for `$TB_ROOT/alex_tradeblocks_startup_config.md` (where `$TB_ROOT` is the TradeBlocks Data root — typically the current working directory, or the nearest ancestor containing `database/analytics.duckdb`). Older 2.x installs had the DuckDB files at the root — for mixed-state machines, fall back to detecting root-level `analytics.duckdb` if the `database/` subfolder isn't present.

### If config exists

**Parse the YAML frontmatter with a real YAML parser** — not grep or regex. The frontmatter has nested keys (`plugin_marketplaces:`, `forbidden_env_vars:`, `legacy_tables_ignore:`) and line-matching approaches silently drop the nested children. Use:

```python
import re, yaml, pathlib
txt = pathlib.Path('alex_tradeblocks_startup_config.md').read_text()
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
| `tb_root` | Directory containing `database/analytics.duckdb` (3.0 canonical). Fall back to a directory containing root-level `analytics.duckdb` for mixed-state machines mid-migration. |
| `dev_skills_folder` | Look for a folder in `$TB_ROOT` matching `Dev-*Skills*`, `*-dev-skills`, or similar. If multiple or none, ask the user. Store as a path relative to `tb_root`, or absolute if outside. Set to `none` if the user has no local dev workspace. |
| `market_provider` | Read `$TB_ROOT/.env` for `MARKET_DATA_PROVIDER`. Common values: `thetadata`, `massive`, `polygon`. If unset, ask the user. |
| `market_provider_endpoint` | Read `.env` for the provider-specific URL (e.g. `THETADATA_BASE_URL`, `MASSIVE_API_URL`). For cloud APIs with only a key (no URL), store `cloud`. |
| `market_provider_start_cmd` | Ask the user for the exact command to start their provider (e.g. for ThetaData: `cd ~/ThetaTerminal && nohup java -jar ThetaTerminalv3.jar > theta.log 2>&1 &`). Optional — leave blank if the provider is always-on / cloud. |
| `market_provider_process_name` | The process name for `pgrep -f` to check if the provider daemon is running (e.g. `ThetaTerminalv3.jar`). Blank for cloud providers. Derive from `market_provider_start_cmd` if obvious, otherwise ask the user. |
| `mcp_image_tag` | Read `$TB_ROOT/.mcp/tradeblocks-mcp.version` |
| `mcp_container_name` | Read `$TB_ROOT/.mcp/docker-compose.yml` — grep `container_name:` |
| `mcp_compose_dir` | `.mcp` (relative to `tb_root`) |
| `plugin_marketplaces` | Parse `~/.claude/plugins/installed_plugins.json` — each plugin id → its `extraKnownMarketplaces` entry in `~/.claude/settings.json` has the GH repo |
| `legacy_tables_ignore` | Safety net for the analytics side. Ask if any tables in `database/analytics.duckdb` are known deprecated and should be suppressed from the "Possibly stale" flag in Step 4A. Default empty. Market-side legacy tables were dropped by 3.0 on first open and are not probed. |

Write the result to `$TB_ROOT/alex_tradeblocks_startup_config.md` using the schema in the Config Schema section below.

**Never write user-specific values (paths, repo names, provider choice) into the SKILL.md itself.** That file is the published skill; it gets overwritten on update. All user-specific state lives in `alex_tradeblocks_startup_config.md` which the skill only creates, never overwrites.

### Updating an existing config

If values change (user moves dev folder, swaps provider, bumps MCP image), the user should edit `alex_tradeblocks_startup_config.md` by hand. The skill detects drift and prompts — it does not silently overwrite.

### Environment pre-flight (run before any other step)

Probe required external dependencies **before** starting health checks; failures here mean no step further down can succeed:

| Dependency | Probe | Failure message |
|---|---|---|
| `python3` on PATH | `python3 -V` | `Python 3.x required. Install via brew/apt/choco.` |
| PyYAML | `python3 -c "import yaml"` | `Install with: python3 -m pip install pyyaml` |
| duckdb package | `python3 -c "import duckdb"` | `Install with: python3 -m pip install duckdb` |
| `gh` CLI (only needed for Step 3A) | `gh --version` | `Install and auth: brew install gh && gh auth login` |
| `curl` (macOS/Linux usually pre-installed) | `curl --version` | `Install via brew/apt/choco` |
| `git` | `git --version` | `Install Xcode Command Line Tools (macOS) or apt/choco` |

Report each missing dep explicitly. Do not continue with a dep missing if the skill will need it — but *do* continue past missing `gh` (Step 3A can skip the upstream-HEAD check if unavailable and fall back to "clone vs cache" only).

### Fresh-install detection

If **any** of these are missing on first run, mark the install as "incomplete" and surface a short checklist before proceeding:
- `$TB_ROOT/database/analytics.duckdb` (3.0 canonical) OR `$TB_ROOT/analytics.duckdb` (legacy root) → trades DB not created yet
- `$TB_ROOT/market/` → Parquet market data root not created yet (expected once `refresh_market_data` has run at least once)
- `$TB_ROOT/.mcp/docker-compose.yml` → MCP server not installed
- `$TB_ROOT/.mcp.json` → MCP client config not created
- `$TB_ROOT/.env` → environment not configured

Don't try to recover these — they require user setup per the TradeBlocks install docs. Surface the gap, point at docs, and let the user come back.

---

## Step 1: TradeBlocks MCP Server

There are **two independent layers** to check, and both must pass for Claude to actually call MCP tools in the current session:

**Layer A — Server health (infrastructure):** Docker daemon + MCP container + port reachable.
**Layer B — Session mounting (Claude client):** `.mcp.json` discoverable at session cwd + server approved + MCP client connected at session bootstrap.

Layer B is evaluated **once at Claude session start** and never retried mid-session. If Claude had to auto-start Docker in Layer A, Layer B has already failed silently — tools will not appear without a **Claude Code restart** (quit and relaunch Claude Code — not a computer restart).

### Pre-flight: derive endpoint + server key from `.mcp.json` (don't hardcode)

Before probing, parse `$TB_ROOT/.mcp.json` once and extract:

```python
import json, pathlib, re
mcp_json = json.loads((pathlib.Path(tb_root) / ".mcp.json").read_text())
# First server entry — Claude Code supports multiple but TradeBlocks configs use one
server_key = next(iter(mcp_json["mcpServers"]))           # e.g. "tradeblocks"
server_cfg = mcp_json["mcpServers"][server_key]
# Endpoint varies: stdio (npx mcp-remote <url>), http, streamable-http, etc.
# Extract URL from args or url field:
url = server_cfg.get("url") or next(
    (a for a in server_cfg.get("args", []) if a.startswith("http")), None)
port = int(re.search(r":(\d+)", url).group(1)) if url else None
mcp_path = re.search(r"https?://[^/]+(/.*)$", url).group(1) if url else "/mcp"
```

Use `{server_key}`, `{port}`, and `{mcp_path}` below — never hardcode `tradeblocks` or `3100`. If `.mcp.json` is missing or malformed, flag and skip Layer A probing (Layer B will still detect the issue as "no `.mcp.json` found").

### Layer A — Server health

1. **Docker daemon:** `docker info`. If down, start it platform-appropriately:
   - **macOS** (`uname` → `Darwin`): `open -a Docker`
   - **Linux**: `systemctl start docker` (may require sudo; if it prompts, stop and ask user)
   - **Windows**: `Start-Service docker` via PowerShell, or tell user to launch Docker Desktop manually
   Poll every 3s up to 30s for `docker info` to succeed. Record to recovery log. **Do not assume a platform** — detect with `platform.system()` or `uname`.
2. **Compose file exists:** verify `$TB_ROOT/{mcp_compose_dir}/docker-compose.yml` is present. If missing, this is a fresh install — tell the user: *"No MCP compose file found at `{path}`. See TradeBlocks MCP install docs: https://github.com/davidromeo/tradeblocks"*. Stop Layer A here.
3. **MCP container:** `docker ps --filter "name={mcp_container_name}" --format "{{.Status}}"`. If not running, `cd $TB_ROOT/{mcp_compose_dir} && docker compose up -d`. Wait 5s for port binding.
4. **HTTP endpoint reachable:** `curl -s -m 3 -o /dev/null -w "%{http_code}" http://localhost:{port}{mcp_path}`. Any response (even 4xx) confirms the port is bound. Timeout means the container isn't serving yet — wait another 5s and retry once.
5. If still failing, tail `docker compose logs --tail=40` and surface to the user.

### Layer B — Session mounting

Run these checks regardless of Layer A outcome — they reveal the state Claude was in at session bootstrap.

1. **`.mcp.json` discoverable.** Check for `$TB_ROOT/.mcp.json`. If missing, flag — Claude Code only loads project MCP config from cwd or an ancestor.
2. **Session cwd is correct.** `pwd` should be `$TB_ROOT` or a descendant. If Claude was launched from elsewhere, `.mcp.json` was never loaded this session. Tell user to relaunch from `$TB_ROOT`.
3. **Server approved.** Parse `~/.claude/settings.json` (may not exist on fresh installs — treat as `{}`):
   - If `enableAllProjectMcpServers: true` → all project servers auto-approved. OK.
   - Else if `{server_key}` (derived above from `.mcp.json`) is in `enabledMcpjsonServers` → OK.
   - Else → **NOT APPROVED**. Claude is waiting for a click-through that didn't happen.
4. **Tools actually callable.** Attempt a trivial MCP call (e.g. `list_blocks`). Distinguish three outcomes:
   - Call succeeds → tools mounted, all good.
   - Call fails with "tool not found" / "no such server" → **tools not mounted this session**.
   - Call fails with server error → server mounted but unhealthy (log issue, don't restart).

### User prompt when tools not mounted

If Layer B shows the MCP tools aren't attached to this session, emit this message **verbatim and prominently** (it's the only action that resolves it):

> ⚠ **MCP tools are not attached to this Claude Code session.** The container is running, but Claude Code bootstraps MCP servers only at session start and does not retry. To activate the tools:
> 1. If `~/.claude/settings.json` does not include `"enabledMcpjsonServers": ["{server_key}"]`, add it now (prevents re-approval every session).
> 2. Confirm Docker + `{mcp_container_name}` are up (they are now, thanks to recovery this session).
> 3. **Quit and relaunch Claude Code** from `$TB_ROOT`. (This is a Claude Code app restart — *not* a computer restart and *not* a `/clear` or `/reset` within the existing session. The MCP client state only rebuilds on a fresh Claude Code process.) On the next session start both gates pass and tools mount automatically.
>
> **To avoid this next time:** start Docker (and wait for `{mcp_container_name}` to show `Up` with port `{port}` bound) *before* launching Claude Code. Then the startup skill is a pure verification pass.

Offer to apply the `enabledMcpjsonServers` edit if it's missing — but **do not** attempt to relaunch Claude Code yourself (and never suggest a computer restart).

**Report:** MCP image tag (from config), container status, HTTP probe result, `.mcp.json` presence, approval state, tool-call probe result, recovery actions taken. Be explicit about whether tools are mounted *in this session* — don't conflate container health with tool availability.

### Layer C — Multi-server inventory (added 2026-04-25)

The user may have **multiple MCP servers** configured in `.mcp.json` — typically a baseline (prod npm-published, in Docker) plus one or more dev variants (host-process running from a fork). Layers A + B above probe ONE server (the baseline from config). This layer enumerates ALL configured servers and reports each.

For each entry in `mcp_json["mcpServers"]`:

```python
import json, pathlib, re, subprocess
mcp_json = json.loads((tb_root / ".mcp.json").read_text())
servers_report = []
for key, cfg in mcp_json["mcpServers"].items():
    # Extract URL + port from the server config (mcp-remote arg or url field)
    url = cfg.get("url") or next((a for a in cfg.get("args", []) if a.startswith("http")), None)
    port = int(re.search(r":(\d+)", url).group(1)) if url else None

    # Determine kind: container or host process
    container = subprocess.run(
        ['docker','ps','--filter',f'publish={port}','--format','{{.Names}}|{{.Image}}|{{.Status}}'],
        capture_output=True, text=True).stdout.strip()
    if container:
        name, image, status = container.split("|", 2)
        kind = "container"
        version_tag = image.rsplit(":", 1)[-1]   # e.g. "3.0.0-beta.2"
        version_str = version_tag
        process_info = f"container {name} · {status}"
    else:
        # No container on this port — assume host process
        proc = subprocess.run(
            ['lsof','-iTCP:'+str(port),'-sTCP:LISTEN','-P','-n','-Fpc'],
            capture_output=True, text=True).stdout
        # Parse lsof Fpc format: -p<pid>\n-c<command>
        pid = re.search(r'^p(\d+)', proc, re.MULTILINE)
        if pid:
            kind = "host"
            # If we know dev MCP source dir, read its package.json + git state
            dev_repo = pathlib.Path.home() / "Developer/tradeblocks"
            if dev_repo.exists():
                pkg = json.loads((dev_repo / "packages/mcp-server/package.json").read_text())
                pkg_ver = pkg.get("version", "unknown")
                sha = subprocess.check_output(['git','-C',str(dev_repo),'rev-parse','--short','HEAD']).decode().strip()
                branch = subprocess.check_output(['git','-C',str(dev_repo),'rev-parse','--abbrev-ref','HEAD']).decode().strip()
                version_str = f"{pkg_ver} (host: {branch}@{sha})"
            else:
                version_str = "host process · source unknown"
            process_info = f"PID {pid.group(1)}"
        else:
            kind = "missing"
            version_str = "—"
            process_info = "NOT RUNNING"

    # Health probe
    code = subprocess.run(
        ['curl','-s','-m','3','-o','/dev/null','-w','%{http_code}', url],
        capture_output=True, text=True).stdout.strip()
    healthy = code in ('405', '200')

    # Designate baseline vs variant. The "baseline" is the prod container
    # named in config (mcp_container_name). Anything else is a dev variant.
    is_baseline = (kind == "container" and name == config.get('mcp_container_name'))

    servers_report.append({
        'key': key, 'kind': kind, 'version': version_str, 'healthy': healthy,
        'http_code': code, 'process_info': process_info, 'port': port,
        'is_baseline': is_baseline,
    })
```

**Report inline in the main report as `MCP servers:` with five columns:**

```
MCP servers:
  Key                Kind        Version                                          Process                Status
  tradeblocks        container   3.0.0-beta.2                                     container tradeblocks-mcp · Up 18h    :3100 · 405 · BASELINE
  tradeblocks-dev    host        3.0.0-beta.2 (host: feat/tradeblocks-3.0@c602309) PID 32806              :3101 · 405 · dev variant
```

Column rules:
- **Key**: server entry name in `.mcp.json`.
- **Kind**: `container` (Docker), `host` (Node process on host), `missing` (configured but not running).
- **Version**: for containers, the image tag (e.g. `3.0.0-beta.2`); for host processes, `<package.json version> (host: <branch>@<sha>)`. The git context makes "which fork/branch the dev MCP was built from" auditable.
- **Process**: container name + `Up <time>` for containers; `PID <n>` for host; `NOT RUNNING` for missing.
- **Status**: `<port> · <http_code> · BASELINE | dev variant`. `BASELINE` is loud-uppercase to signal "this is the user's prod"; `dev variant` is lowercase / quieter.

**Baseline upstream-update check**: only for the BASELINE server, additionally compare the installed image tag against `npm registry tradeblocks-mcp` (latest + beta dist-tags) and report:
- `tracking npm latest` if installed matches `dist-tags.latest` (and isn't a beta).
- `tracking npm beta` if installed matches `dist-tags.beta`.
- `outdated — npm latest is X.Y.Z, beta is A.B.C` if installed is older than both.
- `npm has a newer version (X.Y.Z available)` if a newer one exists in the channel the user is on.

If a newer version is available in the user's tracked channel, append a one-line suggestion:
```
→ Run `/dev pipeline-update` (or `dev-tradeblocks-pipeline-update`) to bump prod to <new_version>.
```

This is the cross-reference to the pipeline-update skill — the canonical path for updating prod versions.

**Dev variants do NOT get the npm-update flag.** Their version is whatever the fork's source is; "outdated" is meaningless without knowing what the user intended.

**Missing servers** (entry in `.mcp.json` but no process on the port): report as `NOT RUNNING` and suggest the recovery path. For dev variants whose source is `~/Developer/tradeblocks/`, suggest `~/Developer/run-dev-mcp.sh`. For the baseline, suggest `cd <TB_ROOT>/.mcp && docker compose up -d`.

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

### 3A. Upstream / Clone / Cache drift check

**Empty-marketplace guard:** if `plugin_marketplaces` from config is empty or missing (brand-new install, no plugins pulled yet), emit the `Upstream vs Installed:` table with a single row: `  (no plugins tracked — pull via /plugin marketplace add …)` and skip to the MCP version row. Do not error.

**Do NOT use `installed_plugins.json → gitCommitSha` for drift detection.** That field is bookkeeping, not ground truth — it can lag silently when upstream pushes content without bumping the `plugin.json` version, producing false "DRIFT" alarms even when cache files are current. Use the three authoritative signals below instead:

| Signal | Source | What it tells you |
|---|---|---|
| `upstream_sha` | `gh api repos/{gh_repo}/commits/main --jq '.sha'` | where upstream HEAD actually is |
| `clone_sha` | `git -C ~/.claude/plugins/marketplaces/{mkt} rev-parse HEAD` | what the local clone has fetched |
| `cache_matches_clone` | `diff -rq {clone} {cache} --exclude=.git` (empty output = match) | whether the runtime cache files equal the clone files |

For each plugin in `plugin_marketplaces`:

```python
import subprocess, json, pathlib

def sha_short(s): return s[:7]

upstream = sha_short(subprocess.check_output(
    ["gh","api",f"repos/{gh_repo}/commits/main","--jq",".sha"]).decode().strip())

clone_dir = pathlib.Path.home() / ".claude/plugins/marketplaces" / mkt_name
clone = sha_short(subprocess.check_output(
    ["git","-C",str(clone_dir),"rev-parse","HEAD"]).decode().strip())

# Resolve cache path from installed_plugins.json → installPath
installed = json.loads((pathlib.Path.home()/".claude/plugins/installed_plugins.json").read_text())
cache_dir = pathlib.Path(installed["plugins"][plugin_id][0]["installPath"])
diff_out = subprocess.run(
    ["diff","-rq",str(clone_dir),str(cache_dir),"--exclude=.git"],
    capture_output=True, text=True).stdout
cache_matches = (diff_out.strip() == "")
```

**Four-way classification:**

| `clone == upstream` | `cache matches clone` | Status | Action |
|---|---|---|---|
| ✓ | ✓ | **OK** | none |
| ✓ | ✗ | **CACHE STALE** | `/plugin → {plugin_id} → Update now`, then quit and relaunch Claude Code |
| ✗ | ✓ | **CLONE STALE** | `git -C {clone_dir} fetch origin && git reset --hard origin/main`, then CACHE STALE action |
| ✗ | ✗ | **BOTH STALE** | clone fetch + plugin update + Claude Code relaunch (do in that order) |

For the MCP server (if `mcp_source: npm`):
- Upstream: `curl -s https://registry.npmjs.org/{mcp_package_name}/latest | jq -r .version`
- Installed: `{mcp_image_tag}` from config
- Compare (normalize `2.3` vs `2.3.0` to same form before comparing)

**Output format — always emit inline in the main report as `Upstream vs Installed:` with exactly these five columns:**

```
Upstream vs Installed:
  Component                  Source                                           Upstream   Installed    Status
  tradeblocks-skills         GitHub davidromeo/tradeblocks-skills             8bc00ac    8bc00ac      OK
  alex-tradeblocks-skills    GitHub goodorigamiman/alex-tradeblocks-skills    4cd6dbd    92c0237      DRIFT
  tradeblocks-mcp            npm registry (tradeblocks-mcp)                   2.3.0      2.3          OK
```

Column rules:
- **Component** — plugin id short name (strip the `@{marketplace}` suffix). MCP row is labeled with just `{mcp_package_name}`; the `(npm)` suffix now lives in the Source column.
- **Source** — where Upstream is fetched from, so the reader can trace any row without re-reading the skill.
  - Plugin rows: `GitHub {owner}/{repo}` using the value from `plugin_marketplaces` in config.
  - MCP row: `npm registry ({mcp_package_name})` when `mcp_source: npm`; `GHCR ({image})` when `mcp_source: ghcr`; otherwise the literal `mcp_source` value + package/image.
  - Keep the column width consistent — pad to the longest Source string so the next columns stay aligned.
- **Upstream** — 7-char sha from `gh api` for plugins; version string for the MCP row.
- **Installed** — 7-char sha identifying the cache content. When `cache matches clone` → use `clone_sha[:7]`. When it doesn't match → show the `installed_plugins.json → gitCommitSha[:7]` with no decoration (Status column conveys the mismatch).
- **Status** — exactly one of `OK` / `CACHE STALE` / `CLONE STALE` / `BOTH STALE` / `DRIFT`. Use the four-way classification above; `DRIFT` is a legacy alias for any non-OK state if the specific four-way breakdown isn't computed.

**Do not replace this table with a summary sentence**, even when every row is OK. The table is the single source of truth for "what version am I running." A reader scanning the startup report needs to see the shas side-by-side.

Below non-OK rows, suggest the exact fix per the four-way table (e.g. `Fix: /plugin → alex-tradeblocks@alex-tradeblocks-skills → Update now, then quit and relaunch Claude Code`). Inline under the table, not in a separate prompts section.

### Stale-bookkeeping corrective

If status is **OK** but `installed_plugins.json → gitCommitSha` doesn't match the clone HEAD (common when upstream pushed content without a version bump — cache files are current but the bookkeeping field wasn't refreshed), rewrite the field to match `git -C {clone_dir} rev-parse HEAD`. Surface as "corrected stale bookkeeping" — not a recovery action, just metadata. **Never** do this on non-OK statuses — it would mask real drift.

### 3B. Loaded cache set

For each plugin in `plugin_marketplaces`, glob `~/.claude/plugins/cache/<mkt>/<plugin>/<ver>/skills/*/SKILL.md` and list skill names. One row per namespace, comma-separated skill list. No per-skill versions — this section just confirms what's loaded.

### 3D. Tools & Skills Inventory (emit on request only)

**This table is NOT emitted in the default report.** The Final Summary's `Upstream vs Installed:` block already conveys what plugins are active and healthy; a separate Tools & Skills table would be redundant. Emit this only when the user explicitly asks (*"show me what skills are loaded"*, *"list tools available"*) or when debugging a missing-skill problem.

**When you do emit it** (compact monospace, column-aligned):

```
Tools & Skills:
  Source                     Type        Location                                Version  Count
  TradeBlocks MCP            MCP server  .mcp/ (tradeblocks-mcp)                 2.3      M tools
  tradeblocks-skills         Plugin      davidromeo/tradeblocks-skills            1.0.0    9 skills
  alex-tradeblocks-skills    Plugin      goodorigamiman/alex-tradeblocks-skills   2.0.2    13 skills
  <dev-workspace>            Local dev   (your dev_skills_folder path)            --       N skills
```

Rules:
- **Omit the `Local dev` row** when `dev_skills_folder: none`.
- **Omit the `TradeBlocks MCP` row** when MCP tools aren't mounted in the current session (per Step 1 Layer B). Show the `M tools` count only when tools are callable; otherwise note "not mounted" in the summary line, not in this table.
- Location values come from `plugin_marketplaces` in config.

### 3C. Local dev vs cache + Dev Skills Registry

Skip this section entirely if `dev_skills_folder: none` in config.

Otherwise, do two things:

**(i) Drift table** (version comparison — same as before):

1. Glob `$TB_ROOT/{dev_skills_folder}/*/SKILL.md`
2. For each dev skill, read `version:` from frontmatter
3. Try to match to a cache skill by stem (strip leading `dev-` from dev name, try each cache namespace with and without prefix additions like `alex-`)
4. Compare version AND content:
   - Dev version (stripped of `-dev`) > cache version → **DEV-AHEAD** (ready to publish)
   - No cache match → **DEV-ONLY** (not yet published)
   - Dev version < cache version → **REGRESSION** (flag loudly)
   - Dev version == cache version, content unchanged → **OK (synced)**
   - Dev version == cache version, content changed → **UNPUBLISHED CHANGES** (dev has edits that won't reach the cache without a version bump — flag and suggest running the local publish workflow)

   Content comparison: compare SKILL.md body (after frontmatter) between dev and the repo copy at `{repo_path}/skills/{published_prefix}{stem}/SKILL.md`. Ignore expected frontmatter transforms (prefix, [DEV] tag, -dev suffix). Also compare any `.py`/`.sql` files in the dev folder to their repo counterparts.

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
<!-- DEV-SKILLS-REGISTRY:BEGIN (auto-generated by alex-tradeblocks-startup — do not edit by hand; re-run skill to refresh) -->
## Dev Skills Registry ({N} skills, last updated {YYYY-MM-DD})

Skills under active development in `{dev_skills_folder}/`. Read the full `SKILL.md` at the listed path when invoking one of these. Dev versions take precedence over any same-stem cache skill.

| Skill | Version | Purpose |
|---|---|---|
| dev-example-skill | 1.0-dev | [one-line description, ≤160 chars] |
| ... | ... | ... |

Paths: `{tb_root}/{dev_skills_folder}/<skill-name>/SKILL.md`
<!-- DEV-SKILLS-REGISTRY:END -->
```

**Rules for when the user later invokes a dev skill:**

- If user says "run dev-X" or references a skill name from this registry: **read the full SKILL.md at the listed path** and execute its instructions. Do not guess or substitute the cache version.
- If user says "run X" (no `dev-` prefix) and a dev version exists with the same stem: note the ambiguity and ask which they want. Dev is usually the intended one when the user is actively developing it.
- If the skill at the path has moved or no longer exists: flag stale registry, suggest re-running startup.

**One-line summary after registry:** "N dev skills · M ahead · K dev-only · J unpublished changes · 0 regressions · CLAUDE.md registry updated."

### Design rationale (short)

Registry lives in `$TB_ROOT/CLAUDE.md` (not the skill folder) so it survives skill updates and project-scopes to the TB workspace. Only the content between `BEGIN`/`END` markers is rewritten — all other CLAUDE.md content is preserved. Each dev skill costs ~50–100 tokens per session; if the dev folder exceeds ~20 skills, add `dev_registry_verbosity: compact` to config to drop descriptions.

---

## Step 4: Databases & Market Data

In TB 3.0 Parquet mode, trades still live in DuckDB (`database/analytics.duckdb`) but market data is in Parquet partitions under `market/`. The legacy `database/market.duckdb` file is frozen post-migration — **this skill does not probe it**. Market-side inventory and freshness go through the MCP's registered views (`market.spot`, `market.spot_daily`, `market.enriched`, `market.enriched_context`, `market.option_chain`, `market.option_quote_minutes`), which read the Parquet files on demand.

### 4A. Liveness & Inventory

**Analytics DuckDB liveness** (read-only, direct Python):

```python
import duckdb, pathlib
path = pathlib.Path('{tb_root}/database/analytics.duckdb')
if not path.exists():
    # Fall back to legacy root location for mixed-state machines
    legacy = pathlib.Path('{tb_root}/analytics.duckdb')
    if legacy.exists():
        print('analytics.duckdb found at legacy root location — 3.0 migration not completed for this file')
        path = legacy
    else:
        print('analytics.duckdb MISSING — fresh install? Database not yet created.')
else:
    try:
        with duckdb.connect(str(path), read_only=True) as con:
            con.execute('SELECT 1').fetchone()
            print(path, 'OK')
    except Exception as e:
        print(path, 'ERROR', str(e)[:200])
```

**Three distinct states:**
- **MISSING**: DB file doesn't exist. Likely a fresh install or the user moved the file. Do not auto-create; prompt the user to verify path in config or run the TradeBlocks install.
- **LOCKED/ERROR**: DB exists but can't be opened read-only (another process holds the write lock, or the file is corrupt). Do NOT force-kill or delete. Report verbatim and ask the user.
- **OK**: proceed with inventory.

**Analytics table inventory** — list `trades.*` and `profiles.*` tables in `database/analytics.duckdb` with row counts. Use a read-only Python connection. Status classification:

- **Active**: populated and maintained
- **Empty**: exists but has 0 rows
- **Internal**: `_`-prefixed operational tables (e.g. `_sync_metadata`)

**Market data inventory (Parquet, via MCP)** — call `mcp__tradeblocks__run_sql` once per canonical view. **Do NOT combine into one UNION ALL query** — empty Parquet-backed views (common for `option_chain` / `option_quote_minutes` before `fetch_chain` / `fetch_quotes` has run) throw a Catalog Error that aborts the whole UNION. Per-view queries let you catch the error and report that view as Empty.

```sql
SELECT COUNT(*) AS rows, COUNT(DISTINCT ticker) AS tickers, MAX(date) AS latest
FROM market.spot_daily;

SELECT COUNT(*) AS rows, COUNT(DISTINCT ticker) AS tickers, MAX(CAST(date AS DATE)) AS latest
FROM market.enriched;

SELECT COUNT(*) AS rows, MAX(CAST(date AS DATE)) AS latest
FROM market.enriched_context;

-- And similarly for market.option_chain, market.option_quote_minutes
-- Catch "Catalog Error: Table with name X does not exist" → report view as Empty (no Parquet files yet)
```

**Output format:**

```
Database inventory:
  analytics.duckdb (database/):
    Schema     Table               Rows    Status
    profiles   strategy_profiles      1    Active
    trades     trade_data        19,976    Active
    trades     reporting_data        88    Active
    trades     _sync_metadata        13    Internal

  market/ (Parquet via MCP views):
    View                       Rows      Tickers   Latest       Status
    spot_daily                 12,016    8         2026-04-22   Active
    enriched                        0    0         --           Empty (pending enrich_market_data)
    enriched_context                2    --        2026-04-22   Active
    option_chain                    0    --        --           Empty
    option_quote_minutes            0    --        --           Empty
```

**Status logic for market views:**
- **Active**: `rows > 0` and `latest` is recent
- **Empty**: `rows = 0` (view registered but no data yet — common for `option_chain` / `option_quote_minutes` until the user runs `fetch_chain` / `fetch_quotes`)
- **Stale**: `rows > 0` but `latest` is far behind expected (covered in Step 4B + 4C with the per-ticker detail)

The `legacy_tables_ignore` config key is kept for analytics-side safety (surfaces any deprecated analytics tables the user still wants suppressed). It no longer applies to market data — legacy market tables were dropped by 3.0 on first open.

### 4B. Market Data Freshness

Route all queries through `mcp__tradeblocks__run_sql`. Market data in 3.0 Parquet mode is accessed via the MCP's registered views over Hive-partitioned Parquet — direct Python file I/O against `database/market.duckdb` is meaningless (that file is frozen post-migration).

**Query — per-ticker daily coverage via `market.spot_daily`:**

```sql
SELECT ticker, COUNT(DISTINCT date) AS n, MIN(date) AS earliest, MAX(date) AS latest
FROM market.spot_daily GROUP BY ticker ORDER BY n DESC;
```

**Query — regime-context coverage via `market.enriched_context`** (note: `date` in this view is VARCHAR, cast before comparing):

```sql
SELECT COUNT(*) AS n, MAX(CAST(date AS DATE)) AS latest FROM market.enriched_context;
```

**Staleness check:** compute the expected latest date as the most recent past weekday (yesterday if yesterday was a weekday, otherwise last Friday). If any ticker's latest date is behind the expected date, the data is stale.

**Output format — always emit inline in the main report as `Market data coverage:` with exactly these four columns:**

```
Market data coverage:
  Ticker   Rows     Earliest      Latest
  SPX      1,571    2022-01-03    2026-04-22
  VIX      1,571    2022-01-03    2026-04-22
  VIX3M    1,571    2022-01-03    2026-04-22
  VIX9D    1,571    2022-01-03    2026-04-22
  IWM      1,571    2022-01-03    2026-04-22
  QQQ      1,459    2022-01-03    2025-12-31
  SPY      1,282    2022-01-03    2025-10-07
  VIX1D    1,095    2023-04-24    2026-04-22

  enriched_context: 2 rows through 2026-04-22
```

Column rules:
- **Ticker** — symbol as stored in `market.spot` (ticker partition key).
- **Rows** — `COUNT(DISTINCT date)` for that ticker (trading days covered, not minute-bar rows). Use thousands separators (`1,571` not `1571`).
- **Earliest / Latest** — `MIN(date)` and `MAX(date)` in ISO format.
- **No Status column.** Staleness is conveyed by the summary `[✓|✗] Market Data` line at the top of the report (e.g. `market: 2026-04-22 (current)` or `market: 2026-04-22 (stale — update to 2026-04-23?)`). The ticker table stays clean.

Ordering: sort by **Rows DESC** (longest-history tickers first — correlates with earliest start date, which is what readers usually scan for first). Not alphabetical.

After the ticker rows, emit **`enriched_context`** as an indented closing line (not a separate section). Use the same 2-space indent as the table rows so it reads as part of the coverage block: `  enriched_context: {N:,} rows through {max_date}`.

**Do not replace this table with a summary sentence**, even when every ticker is current. Readers use the earliest column to spot newly added tickers and uneven start dates; that information vanishes in a one-line summary.

**Staleness prompt:** if latest date is behind the expected date, prompt with specific dates: *"Market data latest is YYYY-MM-DD. Update through YYYY-MM-DD (yesterday)?"* Do not auto-run — wait for user confirmation. If user confirms, call the `refresh_market_data` MCP tool with `asOf = YYYY-MM-DD` and the project's standard spot/chain/quote universe (see CLAUDE.md's "Standard refresh universe" section) — auto-enriches and auto-computes VIX context. The retired `Scripts/update_market_data.py` + `Scripts/run_mcp_update.py` scripts were removed in the 3.0 migration.

### 4C. Calculated Fields Health Check

After the ticker coverage table, verify that enriched/derived columns are fully populated and current. This catches enrichment failures, partially-enriched tickers, or new tickers that were imported but never enriched.

**In 3.0, enrichment lives in two views** (both backed by Parquet under `market/enriched/`):
- `market.enriched` — per-ticker indicator columns (RSI_14, ATR_Pct, Return_5D, etc.)
- `market.enriched_context` — cross-ticker regime columns (Vol_Regime, Term_Structure_State, VIX_Spike_Pct, etc.)

Neither view contains raw OHLCV — that's in `market.spot_daily`. So there's no "raw vs enriched" split to do inside these views; every non-key column is an enriched field.

**Enriched columns to check — detect dynamically via MCP `run_sql`:**

```sql
-- Per-ticker indicators (exclude key columns)
SELECT * FROM (DESCRIBE market.enriched);

-- Cross-ticker regime (exclude key column)
SELECT * FROM (DESCRIBE market.enriched_context);
```

Parse the returned column list, drop key columns:
- `market.enriched` key cols to drop: `ticker`, `date`
- `market.enriched_context` key cols to drop: `date`

Every remaining column is an enriched field to check. This keeps the skill agnostic to schema drift as TB evolves.

**Enrichment tickers — detect dynamically:**

```sql
SELECT DISTINCT ticker FROM market.enriched ORDER BY ticker;
```

Returns tickers that have at least one enriched row. Index-only tickers where enrichment can't produce meaningful values (e.g. VIX1D pre-warm-up) will simply not appear.

**Staleness SQL — per (ticker, column) against `market.enriched`:**

Build dynamically from the column list. Note that `date` in both enriched views is VARCHAR — cast before comparing/max-ing:

```sql
SELECT ticker,
       MAX(CAST(date AS DATE)) AS max_raw,
       MAX(CASE WHEN "<col>" IS NOT NULL THEN CAST(date AS DATE) END) AS max_enriched
FROM market.enriched
GROUP BY ticker;
```

And for context:

```sql
SELECT MAX(CAST(date AS DATE)) AS max_date,
       MAX(CASE WHEN Vol_Regime IS NOT NULL THEN CAST(date AS DATE) END) AS Vol_Regime_latest,
       ...
FROM market.enriched_context;
```

**Status logic per field:**
- **Current**: latest non-null date equals the ticker's max date in that view
- **Stale**: latest non-null date < max date (enrichment lagging behind raw data)
- **Empty**: all values are NULL (enrichment never ran for this field — or the view itself is empty, which is a common post-backfill state until `enrich_market_data` is called)

**Output format — compact unless issues found:**

When all fields are current:
```
Calculated fields:
  market.enriched:          28 enriched fields · all current through 2026-04-22
  market.enriched_context:   5 enriched fields · all current through 2026-04-22
```

When the enrichment table is fully empty (e.g. right after a bulk backfill):
```
Calculated fields:
  market.enriched:          EMPTY (0 rows — run enrich_market_data to populate)
  market.enriched_context:   5 enriched fields · all current through 2026-04-22
```

When partial issues exist, expand only the problem fields:
```
Calculated fields:
  market.enriched:          28 enriched fields · 26 current · 2 STALE:
    ivr   (SPY): latest non-null 2026-04-10 (4 bdays behind)
    ivp   (SPY): latest non-null 2026-04-10 (4 bdays behind)
  market.enriched_context:   5 enriched fields · all current through 2026-04-22
```

**Enrichment staleness prompt:** if any calculated fields are STALE (not EMPTY — empty fields are a schema/pipeline gap to report, not something the update script fixes), prompt: *"Calculated fields are behind raw data (latest enriched: YYYY-MM-DD, latest raw: YYYY-MM-DD). Re-run enrichment?"* Do not auto-run — wait for user confirmation. If user confirms, run `enrich_market_data` via the MCP tool for each affected ticker.

Note: EMPTY fields (e.g. ivr/ivp that have never been populated, or the whole view being empty after a skip-enrichment backfill) should be reported as a gap but not offered for staleness re-run — they indicate a pipeline state, not stale-data-needing-refresh. If the whole `market.enriched` view is empty, the suggestion should be: *"Market.enriched is empty. Run `enrich_market_data` per ticker to populate from the cached spot data?"*

### 4D. SqueezeMetrics Data Freshness

Covers user-added SqueezeMetrics DIX/GEX data under `alex-data/squeezemetrics/data.parquet`, maintained by the `alex-squeezemetrics-update-data` skill. Optional — some users don't track this dataset.

**Preflight — skip gracefully:** If `$TB_ROOT/alex-data/.sync-meta.json` does not exist, skip this entire step silently. Do not emit anything to the report. Do not emit the Status-line row in the Final Summary. The user hasn't opted into this dataset.

**Probe:** read `$TB_ROOT/alex-data/.sync-meta.json`, extract the `squeezemetrics` key (if present). Required sub-fields: `latest_date` (ISO date), `last_refresh` (ISO timestamp), `row_count`.

If the `squeezemetrics` key is missing from the JSON but the file exists, treat as "watermark corrupt" — report the gap, do not prompt for refresh (user should investigate manually).

**Staleness rule:** *"More than 1 trading day behind expected latest."* Compute expected latest the same way as Step 4B (most recent past weekday). If `(expected_latest − latest_date)` spans more than one trading day, flag **STALE**. Exactly one trading day behind is NOT stale — SqueezeMetrics publishes with a real-world lag and zero-day-behind is rare.

Helper logic (pseudo-code):
```python
import datetime
def trading_days_between(earlier, later):
    # Count weekdays strictly between the two dates (exclusive of `earlier`, inclusive of `later`)
    d = earlier
    n = 0
    while d < later:
        d += datetime.timedelta(days=1)
        if d.weekday() < 5:  # Mon-Fri
            n += 1
    return n

behind = trading_days_between(latest_date, expected_latest)
is_stale = behind > 1
```

**Output — always emit when the dataset exists**, inline in the main report as a closing block after the `Market data coverage:` section:

```
SqueezeMetrics: latest 2026-04-22 · 3,766 rows · last refresh 2026-04-23T15:42 ET
```

When stale:

```
SqueezeMetrics: latest 2026-04-20 · 3,764 rows · last refresh 2026-04-21T09:15 ET  (2 trading days behind)
```

**Staleness prompt (only when `is_stale` is true):** *"SqueezeMetrics data latest is YYYY-MM-DD (N trading days behind). Refresh to YYYY-MM-DD?"* Do not auto-run — wait for user confirmation. If user confirms, invoke the `alex-squeezemetrics-update-data` skill (trigger phrase: *"update squeezemetrics data"*). The skill knows where its driver script lives — no need to invoke a literal path here.

The refresh skill is self-contained — it fetches from squeezemetrics.com, appends new rows to the canonical CSV at `_shared/DIX-3.csv`, rewrites the Parquet mirror, and updates the watermark in `alex-data/.sync-meta.json`. On its next invocation this step will see the new `latest_date` and report current.

**Report:** per-ticker coverage table, market inventory, calculated fields check, SqueezeMetrics freshness, staleness prompts (market data + enrichment + SqueezeMetrics) if applicable.

---

## Final Summary

Emit the report as **markdown with explicit section headers and blank lines between sections** — not as a single fenced block. Readers scan by section; crowding everything into one block makes it hard to locate a specific table. Exact layout:

````markdown
## TradeBlocks Startup — YYYY-MM-DD HH:MM

### Status

```
[✓|✗] MCP Servers        {N} mounted ({P} prod · {D} dev) · baseline {image_tag} {tracking-channel} {· upstream-update-available}
                          · session tools: <mounted|NOT mounted — QUIT & RELAUNCH CLAUDE CODE>
[✓|✗] Market Provider    {provider}  · <status> (<endpoint>)
[✓|✗] Skills             <OK|DRIFT>  [· dev: N skills (K unpublished edits)]
[✓|✗] Parquet            market: <date> (<current|stale>)  [· enrichment STALE|EMPTY]
[✓|✗] DuckDB             analytics: OK  [· {N} active · {K} empty]
[✓|✗] SqueezeMetrics     latest: <date>  · <current|stale — N trading days behind>     # omit row entirely if alex-data/.sync-meta.json doesn't exist
```

### Upstream vs Installed

```
Component                  Source                                           Upstream   Installed    Status
tradeblocks-skills         GitHub davidromeo/tradeblocks-skills             {sha}      {sha}        {OK|…}
alex-tradeblocks-skills    GitHub {owner}/{repo}                            {sha}      {sha}        {OK|…}
tradeblocks-mcp            npm registry (tradeblocks-mcp)                   {ver}      {ver}        {OK|…}
```

### MCP Servers

```
Key                Kind        Version                                          Process                      Status
tradeblocks        container   {image_tag}                                      container {name} · Up {time}  :{port} · {http} · BASELINE
tradeblocks-dev    host        {pkg_ver} (host: {branch}@{sha})                 PID {pid}                     :{port} · {http} · dev variant
...
```

When the baseline has an upstream update available, append a one-liner under the table:

```
→ Run `/dev pipeline-update` (or `dev-tradeblocks-pipeline-update`) to bump prod from {installed} to {available}.
```

(Section always emitted. Multi-server inventory is the single source of truth for "what MCPs are mounted, and which is prod.")

### Dev Skills

N total · M ahead · K dev-only · J regressions · **P unpublished changes** · CLAUDE.md registry refreshed

- `skill-name` (reason — e.g. "version bumped, not yet published", "body edits, version unchanged")
- ...

Fix: run `alex-github-update` to publish, or bump `-dev` version if edits are intentional drafts.

### Market Data Coverage

```
Ticker   Rows     Earliest      Latest
{sym}    {n:,}    {date}        {date}
...

enriched_context: {n:,} rows through {date}
```

### SqueezeMetrics

```
latest: {date}  · {n:,} rows  · last refresh {iso timestamp}  [· {N} trading days behind]
```

(Section omitted entirely when `alex-data/.sync-meta.json` doesn't exist.)

Refresh to {expected_latest}? → run `alex-squeezemetrics-update-data` (trigger: "update squeezemetrics data")

### Calculated Fields

N enriched daily cols · <status>

```
{ticker(s)}   {short field list} → {frozen date}  ({M bdays behind})
...
```

Re-run enrichment to {latest raw date}? ({ticker list})

### Recovery Actions

- {what was done, or "none"}

### Root Organization

Terse memory-refresher for the TB data root, emitted on every run so the user re-anchors at session start. Pull dynamic values from config + a live directory scan — don't hardcode ticker lists or block folder names. Omit any line whose path doesn't exist (e.g. skip `alex-data/squeezemetrics/` if the folder is absent; skip the dev-skills line when `dev_skills_folder: none`).

```
database/
  analytics.duckdb       trades.* (trade_data, reporting_data) + profiles.*   · DuckDB · actively written by MCP
  market.duckdb          legacy/frozen in 3.0 Parquet mode · views point at /data/market/ · skill skips probing

market/                  Parquet · canonical market data in 3.0
  spot/ticker=X/date=Y/  raw OHLCV (intraday minute bars)
  enriched/ticker=X/     per-ticker indicators (RSI_14, ATR_Pct, Return_*, Gap_Pct, …)
  enriched/context/      cross-ticker regime (Vol_Regime, Term_Structure_State, VIX_*)
  underlyings.json       registered option underlyings

alex-data/               user-managed datasets · path-disjoint from MCP writes
  squeezemetrics/        DIX/GEX Parquet (optional · refresh via "update squeezemetrics data")
  .sync-meta.json        watermarks for alex-data pipelines

{dev_skills_folder}/     {N} dev skills · full list in CLAUDE.md Dev Skills Registry      # omit if dev_skills_folder: none
.mcp/                    docker-compose.yml · tradeblocks-mcp.version ({mcp_image_tag})
.mcp.json                Claude Code MCP client config ({server_key} → :{port}{mcp_path})
Scripts/                 standing utilities — see CLAUDE.md "Running the Standing Scripts"
<YYYYMMDD - TICKER STRATEGY PARAMS>/   block folders · each has trade CSVs + trade_profile.json
```

Query paths:
  analytics.duckdb  →  direct Python `duckdb.connect(..., read_only=True)` inside a context manager, OR MCP `run_sql`
  market/*.parquet  →  MCP `run_sql` over registered views: spot, spot_daily, enriched, enriched_context, option_chain, option_quote_minutes

Config: `alex_tradeblocks_startup_config.md`
````

Rules:
- **Blank lines between sections are required.** Every `###` header has one blank line before and after. Inside a fenced code block, preserve internal spacing (e.g. the blank line separating ticker rows from `_context_derived`).
- **Both tables are always present** (`Upstream vs Installed` and `Market Data Coverage`). Never compress either into a summary sentence, even when every row is OK. See the output-format blocks in Step 3A and Step 4B for exact column layouts and ordering.
- **Omit the `### Dev Skills` section entirely** when `dev_skills_folder: none` in config. Also drop the `· dev: ...` suffix on the Status line.
- **Omit the `### Calculated Fields` section** when every enriched field is current — no point padding the report with an "all green" line. Always emit when anything is STALE or EMPTY.
- **Omit the `### SqueezeMetrics` section** entirely when `alex-data/.sync-meta.json` doesn't exist. Also drop the `[✓|✗] SqueezeMetrics` row from the Status block in that case.
- **Storage is split across two rows** so each backend's health is visible at a glance:
  - `[✓|✗] Parquet` covers the Parquet-backed market data (Step 4A market views + Step 4B coverage). Staleness shows inline (e.g. `market: 2026-04-22 (stale — update to 2026-04-23?)`); the `· enrichment STALE` or `· enrichment EMPTY` tail appears only when Step 4C found stale or empty fields. Set `✗` when market data is stale OR enrichment is STALE/EMPTY.
  - `[✓|✗] DuckDB` covers `database/analytics.duckdb` (Step 4A analytics inventory). Optional tail `· {N} active · {K} empty` gives a one-glance view of non-internal table status; drop it if everything is Active. Set `✗` only when the DB is MISSING or LOCKED/ERROR.
- **`[✓|✗] SqueezeMetrics` row** uses the Step 4D staleness rule (more than 1 trading day behind). When stale, show the day-count suffix: `stale — 2 trading days behind`.
- **No Tools & Skills table in the main summary.** It's redundant with Upstream vs Installed. Emit only on explicit request.
- **No Database inventory table in the main summary** (covers both `analytics.duckdb` tables and the Parquet market views from Step 4A). Detail-level; emit only when a view's status changes or the user asks.
- **`### Root Organization` is always emitted** — it's the session-start memory refresher. Omit individual lines for paths that don't exist (`alex-data/squeezemetrics/`, the `{dev_skills_folder}/` line when `none`), but never compress the block into a summary sentence. The whole value is in seeing the layout.

When there's drift, staleness, or a recovery-required state, emit the specific fix **inline beneath the relevant row**, not in a separate prompts section. E.g. under a `CACHE STALE` row in `Upstream vs Installed`, the next line reads `Fix: /plugin → {plugin_id} → Update now, then quit and relaunch Claude Code`.

**Expanded detail sections** (database/view inventory, full Calculated fields breakdown, Tools & Skills) are emitted **only when the user explicitly asks** ("show me the tables", "break down enrichment") or when a failure condition requires them (e.g. analytics DuckDB liveness probe fails → full inventory follows automatically). Do not emit them as default padding.

---

## Recovery Log (`alex_tradeblocks_startup_log.md`)

Only append when recovery actions were taken. Format:

```markdown
## YYYY-MM-DD HH:MM
- <what was down>. Ran: `<exact command>`. Ready after ~Ns.
```

One bullet per action with the exact command used. Serves as a reference for repeat-session speedup.

---

## Config Schema (`alex_tradeblocks_startup_config.md`)

Use this template when writing the config file on first run. YAML frontmatter holds parsed values; the body is free-form notes.

```markdown
---
schema_version: 1

# Paths
tb_root: /path/to/TradeBlocks Data
dev_skills_folder: <your-dev-folder-or-none>  # name relative to tb_root (maintainers), absolute path, or "none" (pulled-only users)

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
mcp_image_tag: "3.0.0-beta.2"                # matches .mcp/tradeblocks-mcp.version
mcp_container_name: tradeblocks-mcp
mcp_compose_dir: .mcp

# Plugin marketplaces (plugin_id → GitHub repo)
plugin_marketplaces:
  tradeblocks@tradeblocks-skills: davidromeo/tradeblocks-skills
  alex-tradeblocks@alex-tradeblocks-skills: <user>/<fork-or-personal-repo>

# Databases (3.0 canonical locations)
analytics_db: database/analytics.duckdb      # trades + profiles (DuckDB, actively written)
market_db: database/market.duckdb            # legacy/frozen in Parquet mode — skill does not probe
legacy_tables_ignore:                        # safety net for analytics-side tables only
  - market.context                           # example (3.0 drops market.context on open; kept for mixed-state reference)
---

# TradeBlocks Startup — Local Config

Notes and context for the startup skill. This file is generated on first run and NEVER overwritten by skill updates.

Edit by hand if your environment changes (e.g. switching providers, moving the dev folder, bumping MCP image).

## Known quirks

(free-form — document one-off things the skill should know. Examples:)

- **DB lock contention**: the persistent MCP container holds the `analytics.duckdb` write lock. Ad-hoc `docker run` of the MCP image will collide — stop compose first or use the existing container. Market data moved to Parquet in 3.0 (no lock).
- **Parquet mode** (YYYY-MM-DD): `TRADEBLOCKS_PARQUET=true` set. Market data writes go to Parquet under `market/`; legacy `market.daily` / `market.intraday` / `market.date_context` tables dropped by 3.0 on first open.
- **Massive cutover** (YYYY-MM-DD): project is ThetaData-only. `MASSIVE_API_KEY` must not be set.
```

---

## What Goes Where — Design Rules

| Belongs in `SKILL.md` (published) | Belongs in `alex_tradeblocks_startup_config.md` (local) |
|---|---|
| The step-by-step process (Steps 0–4) | TradeBlocks Data root path |
| Probe logic (generic) | Dev skills folder (if any, and where) |
| Config schema template | Market data provider choice |
| Drift detection rules | Provider endpoint URL |
| Report format | Provider start command |
|  | MCP image tag, container name, package source |
|  | List of personal/fork GitHub repos |
|  | Legacy tables/fields to ignore |
|  | Free-form quirks specific to this install |

If a future skill version needs to change *how* a thing works (e.g. different probe endpoint because the provider API changed), update `SKILL.md`. If the *value* of something changes (e.g. user moved to a new TB data root), edit `alex_tradeblocks_startup_config.md`.

---

## What NOT to Do

- Do not hardcode user paths, repo names, or provider choices in `SKILL.md`.
- Do not overwrite `alex_tradeblocks_startup_config.md` on any run except the very first. Subsequent runs may only append notes under existing sections if explicitly asked.
- Do not silently ignore config drift — if detected values don't match the config, surface it and ask.
- Do not force-kill processes or containers without user confirmation.
- Do not auto-run market data update, enrichment re-run, or SqueezeMetrics refresh — only prompt and wait for user confirmation.
