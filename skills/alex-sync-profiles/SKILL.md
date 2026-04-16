---
name: alex-sync-profiles
description: >
  Walk all block folders, find trade_profile.json files, and upsert each into the
  profiles.strategy_profiles table via the profile_strategy MCP tool. Closes the gap where JSON files
  are declared the source of truth but no automatic sync exists today. Reports per-block diffs (created,
  updated, unchanged, errored) and dry-runs by default.
compatibility: Requires TradeBlocks MCP server. Reads trade_profile.json from each block folder; calls profile_strategy MCP tool to write.
metadata:
  author: alex-tradeblocks
  version: "1.0.1"
---

# alex-sync-profiles

`trade_profile.json` is the declared source of truth for strategy profiles, but `profiles.strategy_profiles` in `analytics.duckdb` is what the MCP tools actually read. Today nothing automatically reconciles the two. This skill closes the gap.

## When to invoke

- When the user says "sync profiles" or "push profiles to db".
- After a hand-edit to one or more `trade_profile.json` files.
- Periodically as a hygiene check.

## Process

### Step 1: Default to dry-run

Always start with `dry_run=true` semantics: build the full plan, show the per-block diff, and only execute writes when the user confirms. Never write on the first pass.

### Step 2: Walk block folders

From the TB root, find every directory matching the block-folder pattern (`YYYYMMDD - …`) that contains a `trade_profile.json`. For each:

```python
import json, pathlib
for p in pathlib.Path('.').glob('*/trade_profile.json'):
    block_dir = p.parent.name
    profile_json = json.loads(p.read_text())
    # ...
```

### Step 3: Compare against current DB state

For each block, call `list_profiles(blockId=<block_dir>)` and `get_strategy_profile(blockId=<block_dir>, strategyName=...)`. Build a diff:

- **CREATE** — JSON exists, no DB row.
- **UPDATE** — JSON exists, DB row exists, fields differ.
- **UNCHANGED** — JSON and DB agree on every field the JSON specifies.
- **ORPHAN** — DB row exists, no JSON. Do NOT auto-delete; report only.
- **ERROR** — JSON missing required fields, malformed, or a field doesn't map to the MCP schema.

### Step 4: Map JSON → profile_strategy params

The `trade_profile.json` schema is narrower than what `profile_strategy` accepts. Map known fields and **prompt the user for the rest** before writing:

| trade_profile.json | profile_strategy param | Notes |
|---|---|---|
| `id` / `title` | `strategyName` | Use `title` if present, fallback to `id` |
| `underlying` | `underlying` | direct |
| `strategy` | `structureType` | direct (e.g. `iron_condor`, `calendar_spread`) |
| `entry.time` | `entryFilters[]` (one entry with `field: "Time", operator: "==", value: "<time>", source: "execution"`) | Time is execution-level, not market data |
| `entry.days` | `entryFilters[]` (one entry with `field: "Day_of_Week", operator: "in", value: [...], source: "market"`) | |
| `entry.allocation_pct` | `positionSizing.allocationPct` + `positionSizing.method: "pct_of_portfolio"` | |
| `entry.filters.vix_min` | `entryFilters[]` (`field: "VIX_Open", operator: ">=", value: <n>, source: "market"`) | |
| `entry.filters.min_short_long_ratio` | `entryFilters[]` (`field: "Short_Long_Ratio", operator: ">=", value: <n>, source: "market"`) | |
| `legs[]` | `legs[]` | Direct map: action→type prefix, type→C/P, qty, delta, dte. `"same_strike"` delta → strikeMethod: "delta", strikeValue: 0 with note. |
| `exit.profit_target_pct` | `exitRules[]` (`type: "profit_target", trigger: "<n>%"`) | |
| `exit.stop_loss_ratio_min` | `exitRules[]` (`type: "stop_loss", stopLossType: "sl_ratio", stopLossValue: <n>`) | |
| `exit.time_based_adjustment` | `exitRules[]` (`type: "time_exit"`) | Map specifics from JSON |
| `exit.leg_delta_exits[]` | `exitRules[]` (`type: "conditional"` with leg delta trigger) | |
| `performance` | `keyMetrics{}` | Selectively: expectedWinRate, profitTarget, etc. |
| **MISSING from JSON** | `greeksBias` | **Must prompt user** (theta_positive / vega_negative / etc.) |
| **MISSING from JSON** | `expectedRegimes[]` | Prompt or default to `[]` |
| **MISSING from JSON** | `thesis` | Prompt or default to "" |

If any required `profile_strategy` field can't be derived, show the diff entry with status **NEEDS_INPUT** and list the missing fields. Do not write profiles with placeholder values.

### Step 5: Show the plan

Report a compact table to the user:

```
Sync plan (dry-run)
─────────────────────────────────────────────────────
20250519 - QQQ DC 2:4 …          UPDATE   (3 fields differ: positionSizing, exitRules, keyMetrics)
20250926 - SPX DC 5-7 …          CREATE
20260319 - Sam Port              NEEDS_INPUT  (missing: greeksBias, expectedRegimes)
20260326 - Call Fly 30 70w …     UNCHANGED
─────────────────────────────────────────────────────
Orphans in DB (no matching JSON): <list or none>

Confirm to apply CREATE + UPDATE actions. NEEDS_INPUT entries skipped — fill in JSONs and re-run.
```

### Step 6: Apply on confirmation

For each CREATE/UPDATE row, call `profile_strategy` with the mapped args. Capture the result. If a write fails, report and continue with the rest — do not stop the sync.

### Step 7: Final report

```
Sync complete
─────────────────────────────────────────────────────
Created   : N
Updated   : M
Unchanged : K
Skipped   : J  (NEEDS_INPUT — fix and re-run)
Errors    : E
Orphans   : O  (DB rows with no JSON — review manually)
```

## What NOT to do

- Do not write on the first pass. Always dry-run first.
- Do not invent missing field values. If `greeksBias` isn't in the JSON, prompt the user — don't default to "delta_neutral" or any other guess.
- Do not delete DB rows that have no JSON (orphans). Report only.
- Do not modify `trade_profile.json` files. Sync is one-way: JSON → DB.
- Do not block the whole sync on one failed write. Continue and report at the end.
