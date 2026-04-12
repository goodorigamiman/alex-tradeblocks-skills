# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Claude Code plugin providing custom analysis skills for Option Omega backtests and options trading portfolios. Requires the [TradeBlocks](https://github.com/davidromeo/tradeblocks) MCP server to be running separately. Distributed via the Agent Skills marketplace.

## Architecture

```
.claude-plugin/            Plugin metadata (plugin.json, marketplace.json)
skills/                    Skill directories, each with SKILL.md + optional references/
Alex-TradeBlocks-Skills/   Supporting files (default CSVs, reference data) for skills
```

**Skills are workflow choreographers, not implementations.** Each SKILL.md describes a multi-step analysis workflow that invokes MCP tools in sequence. The actual logic lives in the TradeBlocks MCP server (50+ tools for trade queries, simulations, and analysis), which users install separately.

**Reference files are interpretation guides.** Each `references/*.md` explains how to read analysis results — thresholds, tables, domain-specific nuance. Skills link to them contextually, not as prerequisites.

## Setup

No build, lint, or test steps — skills are static markdown. The TradeBlocks MCP server must be installed and running separately.

## Skill Structure

Every skill follows this pattern in its SKILL.md:

```yaml
---
name: skill-id
description: one-liner + trigger conditions
compatibility: MCP server requirements
metadata:
  author: alex-tradeblocks
  version: "1.0"
---
```

Followed by: Prerequisites > Process (numbered steps with specific MCP tool calls) > Interpretation Reference > Related Skills.

## Plugin Distribution

- `.claude-plugin/plugin.json` — name, version, author for the plugin itself
- `.claude-plugin/marketplace.json` — lists all skills, sets `strict: true`, defines marketplace entry
- Install: `/plugin marketplace add goodorigamiman/alex-tradeblocks-skills` then `/plugin install alex-tradeblocks@alex-tradeblocks-skills`

## Dependencies

- **TradeBlocks MCP server** — required. All skills invoke MCP tools for data access and analysis.
- **Market data API** — required for regime analysis, enrichment, and intraday replay. Any provider with OHLCV + VIX data works (Massive.com, ThetaData, CSV import, etc.).
- **Option Omega** — trade data source. CSV exports are imported into blocks via `import_csv`.
- **No external skill dependencies.** Skills in this repo are fully self-contained. Any workflow components inspired by other skill authors (Romeo, Amy, etc.) are copied directly into the skill rather than referenced as a dependency. This avoids version coupling and ensures skills work standalone.

## Supporting Files (`Alex-TradeBlocks-Skills/`)

Reference data and dependencies that skills read at runtime. Ships with the plugin and gets copied to the user's TradeBlocks Data root on first skill run.

### File Convention

- **`.default.csv`** — shipped defaults, maintained by the plugin author. Updated via push + version bump.
- **User overrides** — same filename without `.default` suffix (e.g., `entry_filter_groups.csv`). Created by the user if they want to customize.

### Resolution Order (for skills)

When a skill needs a supporting file, resolve in this order:

1. **User specifies a file at invocation** → use that
2. **User version exists** in `Alex-TradeBlocks-Skills/` in the working directory (no `.default` suffix) → use that
3. **Local `.default` copy exists** in `Alex-TradeBlocks-Skills/` in the working directory → use that
4. **Neither exists** → copy `.default` files from the plugin cache to `Alex-TradeBlocks-Skills/` in the working directory, then use them

To find the plugin cache path, resolve the latest version directory:
```
~/.claude/plugins/cache/alex-tradeblocks-skills/alex-tradeblocks/{latest-version}/Alex-TradeBlocks-Skills/
```
Sort version directories lexicographically and pick the last one.

### Refreshing Defaults

Local `.default.csv` files are copied once and not auto-updated. After a plugin update ships new defaults, users must delete or rename their local `.default.csv` files for the skill to re-provision from the updated cache.

### Current Files

| File | Purpose |
|------|---------|
| `entry_filter_groups.default.csv` | 38 entry filters with OO/TB mapping, Entry Group (A–H), and Implication columns |
| `entry_filter_correlations.default.csv` | 73 pairwise correlations across market fields with group labels and implications |

## Domain Concepts

- **Blocks** — named strategy containers in the DuckDB database. Most tools require a `blockId` from `list_blocks`.
- **Strategy profiles** — persistent metadata about a strategy's structure, entry filters, and expected regimes. Created by `profile_strategy`, consumed by analysis skills.

## Development Workflow

Skills are developed locally and promoted to this repo when ready.

### Dev → Promote → Publish

1. **Dev** — Create `dev-<skill-name>/SKILL.md` in the project-level `.claude/skills/` directory. Test as `/dev-<skill-name>`. Changes are live immediately.
2. **Promote** — When the skill works, copy to this repo's `skills/alex-<skill-name>/` (replace `dev-` with `alex-`). Update `name` in frontmatter and `metadata.author` to `alex-tradeblocks`.
3. **Publish** — Bump version in both `plugin.json` and `marketplace.json`, commit, push, tag. Cache is keyed by version — **no bump = no update**.
4. **Test published** — Run `/plugin marketplace update alex-tradeblocks-skills`, restart Claude Code, invoke as `/alex-tradeblocks:<skill-name>`.
5. **Clean up** — Delete the `dev-` copy from `.claude/skills/` so it doesn't shadow the plugin version.

### Naming Convention

| Stage | Location | Name | Invocation |
|-------|----------|------|------------|
| Dev | `.claude/skills/dev-my-skill/` | `dev-my-skill` | `/dev-my-skill` |
| Published | `skills/alex-my-skill/` (this repo) | `alex-my-skill` | `/alex-tradeblocks:alex-my-skill` |

The `dev-` prefix identifies in-development skills. The `alex-` prefix identifies published skills and avoids name collisions with skills from other authors (e.g., Romeo's `tradeblocks:dc-analysis` vs `alex-tradeblocks:alex-dc-analysis`). Both can coexist during testing.

### Version Bumping

Always bump version when adding or changing skills. Follow semver:
- **Patch** (1.1.0 → 1.1.1): Bug fixes, wording changes within existing skills
- **Minor** (1.1.0 → 1.2.0): New skills added, significant skill changes
- **Major** (1.x → 2.0.0): Breaking changes to skill behavior or removal of skills
