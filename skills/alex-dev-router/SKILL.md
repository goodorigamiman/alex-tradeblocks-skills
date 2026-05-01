---
name: dev
description: Slash-invoked router (`/dev`) for dev resources. Interprets the user's request as referencing a dev skill OR a dev MCP tool variant — never the cached/published version. Auto-discovers available dev resources from the configured dev skills folder and `mcp__tradeblocks-dev__*` tools, performs fuzzy matching against natural-language input, asks for confirmation when ambiguous, and executes the dev variant deterministically. **Always trigger this skill when the user types `/dev <anything>`** — slash invocation bypasses the unreliable "prefer-dev" heuristic that silently falls through to cached versions. Also trigger when the user says "use the dev version", "route to dev", or asks for the dev variant of a tool/skill by any phrasing. The whole point is that "/dev" means "I am asserting this exists in dev — find it." Never fall through to prod silently.
compatibility: >
  Reads the dev skills folder under TB root (path resolved at runtime from the user's startup config — see "Resolving the dev skills folder" below).
  Reads `mcp__tradeblocks-dev__*` tools (deferred — use ToolSearch to load schemas before calling).
  Optional config at `<TB_ROOT>/alex_dev_router_config.md` for friendly aliases.
  Requires Python 3 + difflib (stdlib) for fuzzy matching.
  PUBLISHING NOTE — this skill follows the standard `dev-` folder prefix convention (folder `alex-dev-router` → published `alex-dev-router`), but the frontmatter `name` field is just `dev` so the slash command is `/dev`.
  The dev-github-update transform "replace `dev-` with `alex-` in the name field" is a substring replace; since `dev` (the literal value) does not contain the `dev-` substring, the transform is a no-op for this skill and the `name` field set to `dev` survives unchanged through publishing.
  No exception needed — the existing transform handles this naturally.
  ENVIRONMENT NOTE — this skill assumes a maintainer-side environment with a dev folder. On a pulled-only install (no dev folder), the skill reports "no dev environment detected" rather than silently routing to prod.
metadata:
  author: alex-tradeblocks
  version: "1.0.0"
---

# /dev — Dev Router

The user has hit a recurring failure mode: when they say "dev <thing>", Claude sometimes correctly reads the local `<dev-folder>/dev-<thing>/SKILL.md` and sometimes silently reaches for the published cache version under `~/.claude/plugins/cache/...`. The "prefer dev" rule in CLAUDE.md is probabilistic; it's been observed to fail in real sessions.

Slash-command invocation is the one mechanism Claude Code guarantees deterministic routing through the Skill tool. **This skill is the deterministic entry point** — once the user types `/dev`, this skill executes, looks up where the dev variant of what they asked for lives, and runs it explicitly. No interpretation, no fallback, no silent cache-version substitution.

The skill name is intentionally `dev` (not `alex-dev-router` or `alex-dev`) so the slash command stays short — `/dev <thing>`. The folder is `alex-dev-router` for clarity but the frontmatter `name:` is what determines the slash command.

---

## Hard rules

1. **`/dev` ALWAYS routes to a dev variant.** Never call a `mcp__tradeblocks__*` (prod) tool from inside this skill. Never read a cache `~/.claude/plugins/cache/...` skill from inside this skill. If the user wants prod, they don't use this skill.

2. **Confirm low-confidence matches; execute high-confidence ones.** Use difflib's similarity ratio:
   - **≥ 0.85** (very close) → "Routing to <X>." Execute.
   - **0.60–0.85** (probable) → "Did you mean <X>? (y/n)" Wait for explicit y.
   - **< 0.60** with multiple candidates → "I see these dev resources that look related: [list]. Which one?" Don't guess.
   - **< 0.60** with no candidates → "No dev resource matches '<request>'. Available: [short list]. What did you want?"

3. **Never silently fall through to prod.** If no dev variant exists for what the user asked for, **ask** rather than execute prod. The user's mental contract is "/dev means dev exists somewhere." If that's wrong, the user wants to know, not get redirected.

4. **Auto-discover, don't hardcode.** Available dev resources are discovered each invocation by:
   - Globbing the dev skills folder (resolved per "Resolving the dev skills folder" below) for `dev-*/SKILL.md`.
   - Inspecting available tools for `mcp__tradeblocks-dev__*` for dev MCP tool names.
   This means new dev skills appear in the router automatically, no config maintenance.

5. **Optional config = friendly aliases only.** If `<TB_ROOT>/alex_dev_router_config.md` exists, it adds short aliases (e.g. `startup` → `alex-tradeblocks-startup`) on top of the auto-discovered list. The router works without the config, but the config makes natural phrasing more reliable.

---

## Step 1: Parse the user's request

The user's message after the slash command is free-form. Examples to handle:

| User says | Parsed alias | Likely target |
|---|---|---|
| `/dev startup` | `startup` | dev skill `alex-tradeblocks-startup` |
| `/dev list blocks` | `list blocks` | dev MCP tool `list_blocks` |
| `/dev list-blocks` | `list blocks` | dev MCP tool `list_blocks` (hyphen normalized to space) |
| `/dev enrich VIX` | `enrich` (head) + `VIX` (args) | dev MCP tool `enrich_market_data(ticker="VIX")` |
| `/dev pipeline update` | `pipeline update` | dev skill `dev-tradeblocks-pipeline-update` |
| `/dev heatmpa` (typo) | `heatmpa` | fuzzy match → `heatmap` → dev skill `alex-entry-filter-heatmap` |
| `/dev list` | `list` (special) | dump all available routes |

Normalization rules:
- Lowercase the request.
- Hyphens and underscores → spaces; collapse runs of whitespace.
- Strip leading/trailing whitespace.
- Strip dev/alex prefixes the user might have typed redundantly: `/dev dev-startup` → `startup`.

---

## Resolving the dev skills folder

The dev folder name is **not hardcoded**. It's resolved at runtime in this priority order:

1. **From `<TB_ROOT>/alex_tradeblocks_startup_config.md`** — if the user has run the startup skill at least once, this config has a `dev_skills_folder:` key whose value is the folder name (e.g. typically a folder of the form `Dev-*Skills*` at TB root). Canonical source.
2. **Auto-discovery via glob** — if no startup config exists, glob `<TB_ROOT>/Dev-*Skills*` for matching folders. Use the first match.
3. **None found** — emit *"No dev environment detected. `/dev` requires a dev skills folder under TB root. If you're a maintainer, run the startup skill first to set up the config; if you're a pulled-only user, this skill is not applicable to your install."* Stop. Do NOT route to prod.

The TB root is the directory containing `alex_tradeblocks_startup_config.md` (the standard "find the nearest ancestor with that file" pattern). The skill resolves this fresh on every invocation — no caching across calls.

---

## Step 2: Build the candidate list

```python
import re, pathlib, json, subprocess
from difflib import SequenceMatcher
import yaml

# Resolve TB_ROOT (parent of cwd that contains the startup config)
def find_tb_root():
    here = pathlib.Path.cwd()
    for parent in [here, *here.parents]:
        if (parent / "alex_tradeblocks_startup_config.md").exists():
            return parent
    return None

TB_ROOT = find_tb_root()
if TB_ROOT is None:
    raise SystemExit("No dev environment detected — TB root not found.")

# Resolve dev skills folder per "Resolving the dev skills folder" section above.
def resolve_dev_folder(tb_root):
    cfg_path = tb_root / "alex_tradeblocks_startup_config.md"
    if cfg_path.exists():
        m = re.search(r'^---\n(.*?)\n---', cfg_path.read_text(), re.DOTALL)
        if m:
            cfg = yaml.safe_load(m.group(1)) or {}
            folder_name = cfg.get("dev_skills_folder")
            if folder_name and folder_name != "none":
                candidate = tb_root / folder_name
                if candidate.exists() and candidate.is_dir():
                    return candidate
    # Fallback: glob for Dev-*Skills* pattern
    for candidate in sorted(tb_root.glob("Dev-*Skills*")):
        if candidate.is_dir():
            return candidate
    return None

DEV_SKILLS_DIR = resolve_dev_folder(TB_ROOT)
if DEV_SKILLS_DIR is None:
    print("No dev environment detected. /dev is not applicable on this install.")
    raise SystemExit(0)

# 2a. Auto-discover dev skill names (folder = name)
dev_skill_names = sorted([
    p.name for p in DEV_SKILLS_DIR.iterdir()
    if p.is_dir() and (p / "SKILL.md").exists()
])

# 2b. Auto-discover dev MCP tool names. The deferred-tools list in the
# session is the authoritative source. From the session context, look for
# entries matching mcp__tradeblocks-dev__<tool>. Strip the namespace prefix.
# The skill instructs Claude to read the available-tools list at execution
# time (and refresh via ToolSearch query "select:mcp__tradeblocks-dev__*"
# if a specific tool's schema is needed before calling).
dev_mcp_tools = [
    # Populated at execution time by reading the available tools list.
]

# 2c. Friendly aliases from config (optional)
config_path = TB_ROOT / "alex_dev_router_config.md"
aliases = {}  # alias -> target
if config_path.exists():
    txt = config_path.read_text()
    fm = re.search(r'^---\n(.*?)\n---', txt, re.DOTALL)
    if fm:
        import yaml
        cfg = yaml.safe_load(fm.group(1))
        aliases = (cfg or {}).get("aliases", {}) or {}

# Final searchable space
candidates = {}
for name in dev_skill_names:
    candidates[name] = ("skill", name)
    # Also the "stripped" form: alex-tradeblocks-startup -> tradeblocks startup
    stripped = name.removeprefix("dev-").replace("-", " ")
    candidates.setdefault(stripped, ("skill", name))
    # Last word as a shortcut
    last_word = stripped.split()[-1]
    candidates.setdefault(f"_lastword:{last_word}", ("skill", name))

for tool in dev_mcp_tools:
    candidates[tool] = ("tool", tool)
    candidates[tool.replace("_", " ")] = ("tool", tool)

for alias, target in aliases.items():
    if target in dev_skill_names:
        candidates[alias.lower()] = ("skill", target)
    elif target in dev_mcp_tools:
        candidates[alias.lower()] = ("tool", target)
    # else: bad alias, ignore (could warn)
```

The `candidates` dict is what fuzzy match runs against. Keys are searchable strings; values are `(kind, target_name)` tuples.

---

## Step 3: Fuzzy match

```python
def best_matches(query: str, candidates: dict, top_k: int = 5):
    scored = []
    for key, (kind, target) in candidates.items():
        if key.startswith("_lastword:"):
            if " " in query: continue   # last-word matching only for single-word queries
            ratio = SequenceMatcher(None, query, key.removeprefix("_lastword:")).ratio()
        else:
            ratio = SequenceMatcher(None, query, key).ratio()
        scored.append((ratio, kind, target, key))
    scored.sort(reverse=True)
    return scored[:top_k]

matches = best_matches(normalized_request, candidates)

top_score, top_kind, top_target, top_key = matches[0]
runner_score = matches[1][0] if len(matches) > 1 else 0.0

if top_score >= 0.85 and (top_score - runner_score) >= 0.10:
    decision = "execute"        # high-confidence single match
elif top_score >= 0.60:
    decision = "confirm"        # probable match — ask y/n
elif any(score >= 0.40 for score, *_ in matches):
    decision = "disambiguate"   # several lukewarm — list and ask
else:
    decision = "no-match"       # nothing close — show available, ask
```

---

## Step 4: Execute or ask

### High-confidence (decision == "execute")

Announce the route, then execute:

```
Routing to: <kind> <target>
  (matched '<top_key>', score <top_score:.2f>)
```

- If `kind == "skill"`: read `<DEV_SKILLS_DIR>/<top_target>/SKILL.md` with the Read tool, then follow its instructions step by step. **Do not invoke via the Skill tool with a cache name** — read the dev SKILL.md directly so the dev version's content is what runs.
- If `kind == "tool"`: call `mcp__tradeblocks-dev__<top_target>` with whatever args the user supplied after the matched portion of their request. Use ToolSearch to load the schema first if not already loaded.

### Confirm (decision == "confirm")

```
Best match: <kind> <target> (score <top_score:.2f>)
Other candidates:
  <runner-up 1> (<score>)
  <runner-up 2> (<score>)

Run <target>? (y/n/<number to pick a runner-up>)
```

Wait for the user's response. Execute only on `y` or numeric pick.

### Disambiguate (decision == "disambiguate")

```
'<request>' didn't match cleanly. These dev resources look related:
  1. <kind> <name>  (score <s>)
  2. <kind> <name>  (score <s>)
  3. <kind> <name>  (score <s>)

Which one? (number, or describe what you wanted)
```

### No match (decision == "no-match")

```
No dev resource matches '<request>'.

Available dev skills (from configured dev folder):
  <list>

Available dev MCP tools (mcp__tradeblocks-dev__*):
  <list, limited to ~15 most relevant or all if short>

What did you want? (paste a name, or say 'cancel')
```

---

## Step 5: Special commands

A few non-routing commands the skill should handle inline:

| Input | Action |
|---|---|
| `list` (alone) | Print full `candidates` table grouped by kind. Don't execute anything. |
| `list skills` | Print only dev skills. |
| `list tools` | Print only dev MCP tools. |
| `aliases` | Print the friendly-alias section of the config. |
| `help` | Print a one-screen explainer of how to use `/dev`. |
| `<empty>` | Same as `help`. |

These short-circuit before fuzzy matching.

---

## Step 6: After execution

When the routed dev skill or tool finishes, append a short trailer:

```
(routed via /dev → <kind> <target>)
```

This makes it visible-in-transcript that the dev path was used. Useful when reviewing past sessions to verify nothing accidentally went through prod.

---

## Worked examples

**Example 1 — exact match, high confidence:**

```
User: /dev startup
Router: matched "startup" → skill "alex-tradeblocks-startup" (score 1.00)
        Reading <dev-folder>/alex-tradeblocks-startup/SKILL.md ...
        [executes the dev startup skill]
        (routed via /dev → skill alex-tradeblocks-startup)
```

**Example 2 — typo, mid-confidence:**

```
User: /dev heatmpa
Router: best match: skill "alex-entry-filter-heatmap" (score 0.71)
        runners-up: dev-entry-filter-time-overlay (0.42), dev-entry-filter-pareto (0.39)
        Did you mean alex-entry-filter-heatmap? (y/n)
User: y
Router: Reading <dev-folder>/alex-entry-filter-heatmap/SKILL.md ...
        [executes]
```

**Example 3 — args after the route:**

```
User: /dev enrich VIX
Router: parsed alias "enrich", args "VIX"
        matched "enrich" → tool "enrich_market_data" (via config alias)
        Calling mcp__tradeblocks-dev__enrich_market_data(ticker="VIX")...
        [tool result]
        (routed via /dev → tool enrich_market_data)
```

**Example 4 — no clean match:**

```
User: /dev xyzzy
Router: 'xyzzy' didn't match any dev resource.

Available dev skills (18):
  alex-create-datelist, alex-entry-filter-analysis, alex-entry-filter-build-data,
  alex-entry-filter-enrich-market-holiday, alex-entry-filter-heatmap, ...

Available dev MCP tools (~80):
  list_blocks, run_sql, describe_database, enrich_market_data, fetch_bars, ...

What did you want? (paste a name, or say 'cancel')
```

---

## Optional config: friendly aliases

When the auto-discovered names are awkward to type, drop a config at `<TB_ROOT>/alex_dev_router_config.md`. Format:

```yaml
aliases:
  startup:        alex-tradeblocks-startup
  heatmap:        alex-entry-filter-heatmap
  list-blocks:    list_blocks
  enrich:         enrich_market_data
```

The router merges these into the candidate list, so `startup` (very natural) routes the same as `alex-tradeblocks-startup` (verbose) or `tradeblocks startup` (auto-stripped). Aliases trump auto-discovered keys when they collide.

This file is **optional** and **not parsed strictly**: missing keys, extra keys, smartypants quotes — all tolerated. The router falls back to auto-discovery when the config is absent or malformed.

---

## Publishing this skill — naturally compatible with dev-github-update

The folder follows convention: `alex-dev-router` (local) → `alex-dev-router` (published). The frontmatter `name:` field is `dev` (no prefix), and **the standard `dev-github-update` transform happens to preserve it unchanged** because:

1. **Folder transform**: `alex-dev-router` → `alex-dev-router` (standard, by Step 2A's rsync to the prefixed folder).
2. **`name:` field transform**: Step 2A.3 says *"replace `{dev_prefix}` with `{published_prefix}`"* — i.e. substring replace `dev-` → `alex-`. The value `dev` does NOT contain the substring `dev-`, so no replacement happens. The published SKILL.md retains `name: dev`.
3. **`version:` field transform**: `1.0.0-dev` → `1.0.0` strips `-dev` suffix. Standard, fine.
4. **`description:` field transform**: strips leading `[DEV] `. This skill's description doesn't start with `[DEV] `, so no change.
5. **Body cross-skill rewrite**: Step 2A.3's body transform looks for `dev-{stem}` patterns matching publish-set skill names, then rewrites to `alex-{stem}`. For this skill, the stem is `dev-router` (folder name minus `dev-` prefix), so `alex-dev-router` in body text gets rewritten to `alex-dev-router`. References to bare `/dev` (no stem after) don't match the pattern. **The slash command `/dev` survives intact in the published body.**

When it's safe to publish:
- Folder: `<dev-folder>/alex-dev-router/`
- Local frontmatter `name`: `dev` → published `name`: `dev` (unchanged by transform)
- Local slash command: `/dev` → published slash command: `/dev` (unchanged)
- Published folder: `alex-dev-router/` (standard transform)

This means `dev-github-update` can publish `alex-dev-router` without modification. The convention coincidentally produces the right outcome because `name: dev` is the empty-stem edge case.

**Verify after publish**: in the cache, run `cat ~/.claude/plugins/cache/<marketplace>/<plugin>/<ver>/skills/alex-dev-router/SKILL.md | head -3` — frontmatter `name:` field should still read `dev`. If it doesn't, dev-github-update has a bug to fix (it's transforming names it shouldn't).

---

## What this skill is NOT

- **Not a wrapper around prod.** This skill never touches `mcp__tradeblocks__*` or any cache skill. If the user wants prod, they don't invoke this skill.
- **Not an automation.** It's a router — it picks WHICH dev resource runs and runs it. The routed resource still does its own work (asks confirmations, writes files, etc.) per its own SKILL.md.
- **Not a replacement for the dev startup ritual.** `/dev startup` will route to `alex-tradeblocks-startup`, but the dev environment must already be healthy. Use the startup skill to verify, not assume.
- **Not a multi-step orchestrator.** One slash invocation = one routed call. Use `dev-tradeblocks-pipeline-update` or other skills for orchestration.

---

## Future enhancements (after first real use)

- **Argument parsing for MCP tool calls.** Currently the user passes args after the matched alias as a free-form string; the router needs to translate that into the tool's typed args. v1 supports the most common single-arg case (e.g. `enrich VIX` → `ticker="VIX"`). v2: smarter arg parsing or prompt-for-each-arg.
- **`/dev last`** — re-run the most recent route. Useful for "I want to re-run the same dev tool after a code change."
- **Match scoring tweaks.** Track which suggestions the user accepted vs rejected; learn over time.
- **Cross-skill dispatch.** If a routed dev skill needs to call another dev skill internally, route through `/dev` rather than re-implementing routing.

These are deferred until a real failure mode shows which one matters most.

---

## What NOT to do

- Do not silently call prod tools when no dev match is found. Always ask.
- Do not hardcode the dev MCP server name or skill folder paths beyond what's at the top of this skill — those are stable for the user's setup but should be config-driven if portability is needed later.
- Do not auto-execute medium-confidence matches without confirmation. The whole point of this skill is determinism via explicit user assent.
- Do not modify any files other than reading the skill body for execution and the optional config. This skill is pure dispatch; routed skills/tools own their own side effects.
- Do not strip the "(routed via ...)" trailer from output — it's the audit signal.
- Publishing via `dev-github-update` works as-is — no exception needed (see "Publishing this skill" above). After publishing, manually verify the cache copy's frontmatter `name:` is still `dev` to catch any bug regression in the transform.
