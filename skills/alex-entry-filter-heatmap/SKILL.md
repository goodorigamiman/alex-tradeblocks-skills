---
name: alex-entry-filter-heatmap
description: >
  ROR retention heatmap for all Report V1 entry filters. Shows the threshold value
  at which each filter retains 90% through 10% of baseline Net ROR, colored by Avg ROM
  of surviving trades. Surfaces which filters can trim losing trades without destroying
  cumulative returns. Shares Phase 1 data CSV with Pareto/Threshold/Parallel Coords skills.
compatibility: Requires TradeBlocks MCP server with trade data and market data loaded.
metadata:
  author: alex-tradeblocks
  version: "2.0"
---

# Entry Filter Retention Heatmap

One-page view showing how aggressively each entry filter can trim trades before destroying cumulative returns. For every Report V1 filter, the heatmap finds the threshold that retains 90%, 80%, ... 10% of baseline Net ROR, and colors cells by the Avg ROM of surviving trades (green = positive, red = negative).

**Shared data with Pareto, Threshold, and Parallel Coords skills.** When the shared `entry_filter_data.csv` exists, this skill reads directly from it -- no SQL needed.

---

## Two-Phase Architecture

### Phase 1: Build Data CSV (skip if cached)

**Gate:** If `{block_folder}/alex-tradeblocks-ref/entry_filter_data.csv` exists, skip to Phase 2.

Otherwise, build via the shared Phase 1 pipeline:

1. Read `entry_filter_groups.default.csv` from `_shared/`
2. Run sufficiency checks from `_shared/phase1_sufficiency_checks.default.sql`
3. Build data query from `_shared/phase1_entry_filter_data.default.sql`
4. Write CSV to `{block_folder}/alex-tradeblocks-ref/entry_filter_data.csv`

### Phase 2: Generate Heatmap (always runs)

Read CSV + groups CSV, compute retention thresholds, generate static HTML.

---

## Shared Module Architecture (v2.0)

All heatmap logic lives in the shared module `gen_heatmap.py` (skill-local). Block-specific scripts are thin wrappers that call `generate(config)` with a config dict.

### Wrapper Template

Create `gen_heatmap.py` in the block folder:

```python
#!/usr/bin/env python3
"""Entry filter retention heatmap for this block."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '_shared'))
from gen_heatmap import generate

generate({
    'block_folder': os.path.dirname(os.path.abspath(__file__)),
    'block_name':   '20250926 - SPX DC 5-7 22.5-15d oF',
})
```

### Config Reference

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `block_folder` | str | Yes | Absolute path to the block folder |
| `block_name` | str | Yes | Display name for subtitle |
| `groups_csv` | str | No | Override path to entry_filter_groups CSV (default: `_shared/entry_filter_groups.default.csv`) |

## File Dependencies

| File | Location | Purpose |
|------|----------|---------|
| `gen_heatmap.py` | skill-local | Shared chart generator module |
| `entry_filter_groups.default.csv` | skill-local | Filter registry: Index, Filter, Entry Group, Filter Type, CSV Column, Report V1 |
| `entry_filter_data.csv` | `{block}/alex-tradeblocks-ref/` | One row per trade, all filter columns + rom_pct |
| `phase1_sufficiency_checks.default.sql` | skill-local | Phase 1 only |
| `phase1_entry_filter_data.default.sql` | skill-local | Phase 1 only |
| `gen_heatmap.py` | `{block_folder}/` | Thin wrapper script (created per block) |

## Output

`{block_folder}/entry_filter_heatmap.html` -- static HTML table with inline CSS, no external dependencies.

---

## Process Steps

### Step 1: Identify Block

Use `list_blocks` to find the target block. Confirm block ID and trade count with the user.

### Step 2: Load Groups CSV

Read `entry_filter_groups.default.csv`. Parse all rows. Filter to rows where:
- `Report V1` is not `FALSE`
- `CSV Column` is non-blank

Classify each filter by `Filter Type`: `continuous`, `binary`, or `categorical`.

### Step 3: Check for Cached Data CSV

If `{block_folder}/alex-tradeblocks-ref/entry_filter_data.csv` exists, read it and skip to Step 7.

### Steps 4-6: Phase 1 Pipeline (only if CSV missing)

Follow the same Phase 1 pipeline as the Pareto skill:
- Step 4: Run sufficiency checks from shared SQL file
- Step 5: Run data query from shared SQL file (replace `{blockId}` placeholder)
- Step 6: Write CSV

### Step 7: Compute Baseline Metrics

From the data CSV:
```
baseline_net_ror = SUM(rom_pct)           -- sum of all per-trade ROMs
baseline_avg_ror = AVG(rom_pct)           -- mean of all per-trade ROMs
baseline_trades  = COUNT(*)               -- total trade count
baseline_wr      = COUNT(rom_pct > 0) / COUNT(*) * 100
```

### Step 8: Classify Report Filters

From Step 2 results, build three lists:
- **Continuous filters** (get Min + Max rows): all where Filter Type = `continuous`
- **Binary filters** (single row, n/a cells): Filter Type = `binary`
- **Categorical filters** (single row, n/a cells): Filter Type = `categorical`

Order within each Entry Group by Index.

### Step 9: Compute Retention Thresholds (continuous only)

For each continuous filter, for both MIN and MAX directions, for each retention target in [90, 80, 70, 60, 50, 40, 30, 20, 10]:

**MIN direction (>= threshold):**

1. Sort trades by filter value ascending
2. Get all unique filter values as candidate thresholds
3. For each candidate threshold `t` (walking upward from lowest):
   - Survivors = trades where `filter_value >= t`
   - `retention = SUM(survivors.rom_pct) / baseline_net_ror * 100`
4. Find the **tightest threshold** (highest `t`) where retention is still >= target
5. If removing the next trade would drop from 93% to 89% for the 90r% target, report the threshold at 93%
6. Record: threshold value, survivor count, Avg ROM of survivors, actual retention %

**MAX direction (<= threshold):**

1. Sort trades by filter value descending
2. Get all unique filter values as candidate thresholds
3. For each candidate threshold `t` (walking downward from highest):
   - Survivors = trades where `filter_value <= t`
   - `retention = SUM(survivors.rom_pct) / baseline_net_ror * 100`
4. Find the **tightest threshold** (lowest `t`) where retention is still >= target
5. Record same metrics

**Edge cases:**
- If even the most extreme threshold still retains >= target: show that extreme value
- If no threshold meets the target: show "--"
- Skip filters where > 10% of values are null

### Step 10: Compute Binary/Categorical Summaries

**Binary filters** (Gap_Filled, Is_Opex): For each value (0 and 1), compute:
- Trade count, Avg ROM, Net ROR, % of baseline Net ROR, Win Rate

**Categorical filters** (Day_of_Week, Month, Vol_Regime, Term_Structure_State, Weeks_to_Holiday, Weeks_from_Holiday): For each unique value, compute the same metrics.

**Categorical display rules:**
- **Weeks_to_Holiday / Weeks_from_Holiday:** Only show values 0-3. Higher values are noise (too far from holiday to matter). Aggregate values > 3 into a single "4+" row if needed for completeness.
- **Days_to_Holiday / Days_from_Holiday:** Exclude from the heatmap by default (too many unique values, low signal density). Use threshold analysis for deep dive on these fields instead.
- **Day_of_Week:** Display as Mon-Fri labels, not raw integers.
- **Month:** Display as Jan-Dec labels.
- **Vol_Regime:** Display as regime labels (1=very_low through 6=extreme).

### Step 11: Generate HTML

Build a single static HTML file. All values pre-computed in Python -- no client-side JS needed except for tooltip hover effects.

#### Table Structure

```
<table>
  <thead>
    <tr><th>Entry Filter</th><th>Dir</th><th>90r%</th><th>80r%</th>...<th>10r%</th></tr>
  </thead>
  <tbody>
    <!-- Group header row (colspan=11) -->
    <tr class="group-hdr"><td colspan="11">A: Volatility Level</td></tr>

    <!-- Continuous filter: 2 rows -->
    <tr>
      <td rowspan="2">VIX at Trade Open</td>
      <td>Min</td>
      <td style="background:..."><div class="cv">18.5</div><div class="cs">142t - 15.2%</div></td>
      ...
    </tr>
    <tr>
      <td>Max</td>
      <td style="background:..."><div class="cv">32.1</div><div class="cs">148t - 14.8%</div></td>
      ...
    </tr>

    <!-- Binary filter: 1 row, n/a span -->
    <tr>
      <td>Gap Filled</td>
      <td>--</td>
      <td colspan="9" class="na">=1: 14.2% (89t) | =0: 13.0% (68t)</td>
    </tr>
  </tbody>
</table>
```

#### Cell Content

Each retention cell contains:
- **Primary:** threshold value (formatted by filter: 2 decimals for most, 4 for SLR)
- **Subscript:** `{trade_count}t - {avg_rom:.1f}%`
- **Title attribute:** `"Threshold: >=18.5 | 142 trades | Avg ROM: 15.2% | Retention: 93.1%"`
- **"--"** if target is unreachable

#### Heatmap Color Function

Color driven by Avg ROM of survivors at that cell's threshold:

```python
def rom_to_color(avg_rom, max_rom, min_rom):
    if avg_rom >= 0:
        intensity = min(avg_rom / max_rom, 1.0) if max_rom > 0 else 0
        alpha = 0.08 + intensity * 0.47
        return f"rgba(46,204,113,{alpha:.2f})"
    else:
        intensity = min(abs(avg_rom) / abs(min_rom), 1.0) if min_rom < 0 else 0
        alpha = 0.08 + intensity * 0.47
        return f"rgba(231,76,60,{alpha:.2f})"
```

Green saturates at the highest Avg ROM across all cells; red saturates at the most negative.

#### Binary/Categorical Summary Table

Below the heatmap, render a secondary table:

```
<h3>Binary & Categorical Filter Breakdown</h3>
<table>
  <tr><th>Filter</th><th>Category</th><th>Trades</th><th>Avg ROM</th><th>Net ROR</th><th>% Baseline</th><th>WR</th></tr>
  <tr><td rowspan="2">Gap Filled</td><td>Yes (1)</td><td>89</td><td>14.2%</td>...</tr>
  <tr><td>No (0)</td><td>68</td><td>13.0%</td>...</tr>
  ...
</table>
```

#### CSS Theme

```css
body { background: #1a1a2e; color: #e0e0e0; font-family: 'Segoe UI', system-ui, sans-serif; padding: 20px 30px; }
h1 { font-size: 1.4em; color: #fff; }
.subtitle { color: #aaa; font-size: 0.85em; }
table { border-collapse: collapse; font-size: 0.82em; width: 100%; }
th { background: #0f3460; color: #888; padding: 8px 10px; text-transform: uppercase; font-size: 0.75em; }
td { padding: 8px 10px; text-align: center; border-bottom: 1px solid rgba(255,255,255,0.05); }
.group-hdr td { background: #0f3460; color: #f39c12; font-weight: 700; text-align: left; }
.cv { font-size: 13px; font-weight: 700; color: #fff; }
.cs { font-size: 9px; color: rgba(255,255,255,0.5); margin-top: 1px; }
.na { color: #666; font-style: italic; font-size: 0.78em; text-align: left; padding-left: 16px; }
td[rowspan] { vertical-align: middle; text-align: left; font-weight: 600; color: #ccc; }
.dir-cell { color: #888; font-size: 0.78em; }
```

### Step 12: Present Results

1. Write HTML to `{block_folder}/entry_filter_heatmap.html`
2. Open in browser
3. Summarize key findings:
   - Which filters have the steepest retention gradient (small threshold change = large ROR loss)
   - Which filters can be tightened aggressively (wide range of thresholds still retain 80%+)
   - Any filters where Min and Max directions tell different stories

---

## What NOT to Do

1. **Never compute ROM as avg(P/L) / avg(margin).** ROM is per-trade: `pl[i] / margin[i] * 100`, then average.
2. **Never color cells by the threshold value.** Color by Avg ROM of survivors only.
3. **Never show Min/Max rows for binary or categorical filters.** They get a single row with n/a.
4. **Never confuse "retention %" with "% of trades kept."** Retention = % of baseline Net ROR retained, not trade count.
5. **Never use Chart.js or external charting.** This is a pure HTML table -- keep it simple and fast.

---

## Related Skills

| Skill | Relationship |
|-------|-------------|
| `dev-entry-filter-pareto` | Pareto shows optimal threshold per filter side-by-side. Heatmap shows the full retention curve. |
| `dev-threshold-analysis` | Deep dive on a single filter with interactive chart. Heatmap is the summary view. |
| `dev-create-datelist` | Generate OO-compatible date lists from filter criteria identified in the heatmap. |

---

## Notes

- All computation runs in Python during HTML generation. No client-side JS needed for the static table.
- The heatmap complements the Pareto chart: Pareto shows "what's the best single threshold?", heatmap shows "how does performance degrade across the full range?"
- Filters with steep gradients (small threshold change causes large ROR loss) indicate the filter is capturing a few high-impact outlier trades -- useful but fragile.
- Filters with flat gradients (wide threshold range retains most ROR) indicate the filter has broad discriminative power -- more robust.
