---
name: alex-normalize-statistics
description: 'Normalize get_statistics results to per-contract terms. Runs the standard get_statistics MCP call, augments with per-trade SQL dividing P&L and margin_req by num_contracts, aggregates avg/max/min margin per contract, and leads the report with the return-on-margin implication. Flags wide margin ranges where the average understates current capital requirements.

  '
compatibility: Requires TradeBlocks MCP server with trade data loaded. Block must have margin_req and num_contracts populated on trades.
metadata:
  author: alex-tradeblocks
  version: 1.0.2
---

# alex-normalize-statistics

When the user asks for stats on a block (or runs `get_statistics`), they expect the report in **per-contract, return-on-margin** terms — not raw totals. This skill is the standard procedure.

## When to invoke

- Any time you would call `get_statistics` to report block performance.
- When the user says "stats", "performance", "how did X do", or similar.
- When normalizing across strategies that traded with different position sizes.

If the user explicitly asks for raw totals or per-trade dollars, skip this skill.

## Process

### Step 1: Identify the block

If not specified, call `list_blocks` and ask the user. Confirm the chosen `blockId` before proceeding.

### Step 2: Run the standard stats

Call `get_statistics(blockId=...)`. Capture the full result.

### Step 3: Per-trade per-contract SQL

Run the following via `run_sql`, substituting the block id:

```sql
WITH per_trade AS (
  SELECT
    pl / NULLIF(num_contracts, 0)         AS pl_per_contract,
    margin_req / NULLIF(num_contracts, 0) AS margin_per_contract,
    num_contracts
  FROM trades.trade_data
  WHERE block_id = '<blockId>'
    AND num_contracts > 0
    AND margin_req > 0
)
SELECT
  COUNT(*)                              AS n_trades,
  AVG(pl_per_contract)                  AS avg_pl_1lot,
  AVG(margin_per_contract)              AS avg_margin_1lot,
  MIN(margin_per_contract)              AS min_margin_1lot,
  MAX(margin_per_contract)              AS max_margin_1lot,
  AVG(pl_per_contract) / NULLIF(AVG(margin_per_contract), 0) AS rom_avg
FROM per_trade;
```

### Step 4: Compose the report

Lead with the **return-on-margin implication**, not the raw P/L. Suggested order:

1. **Headline:** "Strategy returns ~X% per dollar of margin per trade on average (Y trades)."
2. **Per-contract economics:** avg P/L per 1-lot, avg margin per 1-lot.
3. **Margin range note:** if `max_margin / min_margin >= 3` → flag explicitly: "Margin per contract ranges from $A to $B (>3× spread). Average understates current capital requirements; size against the upper bound, not the mean." `[TODO: verify the 3× threshold rationale and source — currently inherited from prior CLAUDE.md guidance.]`
4. **Standard get_statistics summary** (win rate, Sharpe, max DD, etc.) below the per-contract block.

### Step 5: Format

- All percentages with one decimal.
- Dollar values rounded to nearest cent for per-contract figures, nearest dollar for totals.
- If reporting alongside another block (comparison), show both blocks' per-contract numbers side by side using the same template.

## What NOT to do

- Do not report dollar totals as the headline — they're misleading across position sizes.
- Do not skip the margin range check. A 3×+ spread silently breaks position sizing assumptions.
- Do not divide aggregated `pl` by aggregated `num_contracts` post-hoc — that's a different (often misleading) average. Always divide at the trade level first, then aggregate.
- Do not run this if the block has no `margin_req` or `num_contracts` populated; report the gap and stop.
