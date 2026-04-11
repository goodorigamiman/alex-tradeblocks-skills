---
name: example-skill
description: Placeholder skill demonstrating the correct SKILL.md format. Use as a template when creating new skills. Invoke with /alex-tradeblocks:example-skill.
compatibility: Requires TradeBlocks MCP server with trade data loaded
metadata:
  author: alex-tradeblocks
  version: "1.0"
---

# Example Skill

This is a placeholder skill that demonstrates the correct format for alex-tradeblocks skills. Copy this folder and modify it to create your own skills.

## Prerequisites

- TradeBlocks MCP server running
- Block with trade data loaded

## Process

### Step 1: Select Block

1. **Ask which block to analyze.** Use `list_blocks` to show available blocks.
2. **Load block info.** Call `get_block_info` with the selected blockId.
3. Display a summary of the block: strategies, date range, trade count.

### Step 2: Run Analysis

1. **Get baseline stats.** Call `get_statistics` for the block.
2. Present the core metrics:

| Metric | Value | Context |
|--------|-------|---------|
| Win Rate | | |
| Profit Factor | | |
| Sharpe | | |
| Max Drawdown | | |
| Trade Count | | |

### Step 3: Synthesis

Summarize findings and suggest next steps.

## Reference

- For detailed reference material, add markdown files to `references/` and link them here.

## What NOT to Do

- Don't assume strategy intent without asking
- Don't recommend threshold values without supporting data
- Don't ignore thin data warnings
