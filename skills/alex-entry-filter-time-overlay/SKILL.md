---
name: alex-entry-filter-time-overlay
description: >
  Intraday premium overlay chart showing all trades' 4-leg net premium paths
  throughout the entry day (09:30-15:59 ET) with percentile bands (p10/p95, p20/p80,
  p30/p50) and dashed median. Follows the overlay_trade_replays.md visual style.
compatibility: Requires entry_filter_time_data.csv (built by dev-entry-filter-time skill).
metadata:
  author: alex-tradeblocks
  version: "1.0"
---

# Entry Filter Time Overlay

Generates a self-contained HTML overlay chart showing how net option premium evolves
minute-by-minute across all trades on their entry day. Each trade is rendered as a thin
trace (green=win, red=loss) with percentile probability bands layered underneath.

Answers: "What does the premium distribution look like throughout the day? Is there a
consistently better time to enter?"

## Prerequisites

- `entry_filter_time_data.csv` in `{block_folder}/alex-tradeblocks-ref/`
  (built by the `dev-entry-filter-time` skill)

No database access needed. No MCP calls. Reads only from the CSV.

## How to Run

```bash
cd "{block_folder}"
python3 gen_entry_filter_time_overlay.py
```

Output: `{block_folder}/alex-tradeblocks-ref/entry_filter_time_overlay.html`

## Chart Elements

### Percentile Bands

| Band | Lower | Upper | Opacity | Meaning |
|------|-------|-------|---------|---------|
| Outer | p10 | p95 | 0.08 | 85% of trades fall within |
| Middle | p20 | p80 | 0.12 | 60% of trades fall within |
| Inner | p30 | p50 | 0.18 | 20% of trades fall within (below median) |

### Median Line

Dashed white line at p50 — the typical premium at each minute.

### Individual Traces

All 157 trades rendered as thin transparent lines:
- Green (`rgba(56,166,84,0.06)`) — trades that ended profitable
- Red (`rgba(248,81,73,0.06)`) — trades that ended as losses

### X-Axis

390 minutes from 09:30 to 15:59 ET. Hour boundaries shown as dashed vertical lines
(10am, 11am, 12pm, 1pm, 2pm, 3pm). Hourly tick labels on axis.

### Y-Axis

Net position premium in $/option: `SUM(sign * price)` across all 4 legs where
STO = +1, BTO = -1. More positive = more premium collected.

### Stats Bar

Trades | Win Rate | Avg ROR | Median ROR | Avg Entry Prem | Med Prem 9:30 | Med Prem 12:00

### Zero Line

Horizontal white line at $0 (break-even between net credit and net debit).

## Visual Style

Follows `overlay_trade_replays.md` exactly:

| Element | Value |
|---------|-------|
| Background | `#0d1117` |
| Card/panel | `#161b22`, border `#30363d` |
| Text primary | `#e6edf3` |
| Text muted | `#8b949e` |
| Grid lines | `rgba(48,54,61,0.5)` |
| Zero line | `rgba(255,255,255,0.25)`, lineWidth 1.5 |
| Font | `'SF Mono', 'Fira Code', monospace` |
| Chart.js CDN | `chart.js@4.4.4` |

## Adapting to Other Blocks

1. Update `BLOCK_DIR`, `BLOCK_ID` constants in `gen_entry_filter_time_overlay.py`
2. Ensure `entry_filter_time_data.csv` exists in the block's `alex-tradeblocks-ref/` folder
3. Run the script — no other changes needed

## Files

| File | Location | Purpose |
|------|----------|---------|
| `gen_entry_filter_time_overlay.py` | `{block_folder}/` | Chart generator script |
| `entry_filter_time_overlay.html` | `{block_folder}/alex-tradeblocks-ref/` | Output chart |
| `entry_filter_time_data.csv` | `{block_folder}/alex-tradeblocks-ref/` | Input data (from dev-entry-filter-time) |

## Related Skills

- `dev-entry-filter-time` — Builds the entry_filter_time_data.csv that this skill visualizes
- `dev-entry-filter-pareto` — Compare time-of-day filter against all other entry filters

## What NOT to Do

- **Don't run without entry_filter_time_data.csv** — this skill requires the CSV built by `dev-entry-filter-time`. Run that first.
- **Don't modify the CSV format** — the overlay chart expects exact column names (HH:MM format for each minute).
- **Don't average premium across trades before plotting** — plot each trade individually, then compute percentile bands.

## Dependencies

- Python 3 (standard library only — no numpy, no external packages)
- Chart.js 4.4.4 (loaded from CDN at render time)
