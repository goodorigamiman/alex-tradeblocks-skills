---
name: alex-entry-filter-parallel-coords
description: >
  Interactive parallel coordinate plot of entry filter values per trade, colored by ROM.
  Each axis is a Report V1 filter, grouped by Entry Group (A–H), with ROM as the final axis.
  Shares Phase 1 data CSV with dev-entry-filter-pareto. D3.js Canvas+SVG hybrid, fully self-contained HTML.
compatibility: Requires TradeBlocks MCP server with trade data and market data loaded.
metadata:
  author: alex-tradeblocks
  version: "2.0.1"
---

# Entry Filter Parallel Coordinates

Interactive parallel coordinate plot showing every trade as a line passing through all entry filter axes, colored by ROM (return on margin). Brush any axis to filter trades and watch the stats bar update live.

**Shared data with Pareto skill.** Phase 1 (data CSV) is identical — if the Pareto skill already built `entry_filter_data.csv`, this skill skips straight to Phase 2.

## Shared Module Architecture (v2.0)

All parallel coordinate plot logic lives in the shared module `build_parallel_coords.py` (skill-local). Block-specific scripts are thin wrappers that call `generate(config)` with a config dict.

### Wrapper Template

Create `build_parallel_coords.py` in the block folder:

```python
#!/usr/bin/env python3
"""Entry filter parallel coordinates for this block."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '_shared'))
from build_parallel_coords import generate

generate({
    'block_folder': os.path.dirname(os.path.abspath(__file__)),
    'block_name':   '20250926 - SPX DC 5-7 22.5-15d oF',
})
```

### Config Reference

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `block_folder` | str | Yes | Absolute path to the block folder |
| `block_name` | str | Yes | Display name for title/subtitle |
| `groups_csv` | str | No | Override path to entry_filter_groups CSV (default: `_shared/entry_filter_groups.default.csv`) |

### Key Improvements in v2.0

- **Dynamic uninformative axis detection:** Instead of hardcoding which axes to skip (e.g., Day_of_Week for Friday-only strategies), the module automatically detects and skips any axis where all trades have the same value. Reports skipped axes in console output.
- **Parameterized block name:** Title and subtitle use the config `block_name` instead of a hardcoded string.
- **Portable paths:** No hardcoded absolute paths; all paths derived from `block_folder` config.

## Two-Phase Architecture

**Phase 1 (Data):** Identical to alex-entry-filter-pareto. Builds `entry_filter_data.csv` with one row per trade, one column per filter. Cached — skips if CSV exists.

**Phase 2 (Visualization):** Read data CSV + entry_filter_groups CSV → build DIMS array from Report V1 filters → generate self-contained D3.js parallel coordinate HTML. Phase 2 is fully handled by the shared module.

## File Dependencies

### Shared Module

| File | Location | Purpose |
|------|----------|---------|
| `build_parallel_coords.py` | skill-local | Shared parallel coordinate plot generator |
| `build_parallel_coords.py` | `{block_folder}/` | Thin wrapper script (created per block) |

### entry_filter_groups CSV

Same file, same resolution order as alex-entry-filter-pareto:
1. User specifies a file at invocation → use that
2. `_shared/entry_filter_groups.csv` (no `.default`) → use that
3. `_shared/entry_filter_groups.default.csv` → use that
4. Neither exists → copy from plugin cache

**Key columns this skill reads:**

| Column | Phase | Purpose |
|--------|-------|---------|
| TB Filter | 1 | TRUE = include in data query |
| CSV Column | 1+2 | Column name in entry_filter_data.csv; becomes the axis key |
| Report V1 | 2 | TRUE = include as an axis in the plot |
| Filter | 2 | Human-readable axis label |
| Entry Group | 2 | Group header above axis cluster |
| Filter Type | 2 | continuous / binary / categorical — determines axis domain/ticks |

### entry_filter_data.csv (Phase 1 output)

One row per trade, columns: `date_opened`, `pl_per_contract`, `margin_per_contract`, `rom_pct`, plus all filter columns. This is the SAME file built by alex-entry-filter-pareto.

## Outputs

- `{block_folder}/alex-tradeblocks-ref/entry_filter_data.csv` — shared data (Phase 1)
- `{block_folder}/filter_parallel_coords.html` — self-contained interactive visualization

## Prerequisites

- TradeBlocks MCP server running
- At least one block with trade data loaded (50+ trades)
- Market data imported for SPX, VIX, VIX9D, VIX3M
- All trades must have `margin_req > 0`
- `_shared/entry_filter_groups.default.csv` must exist

## Process

### Step 1: Select Target Block

1. Use `list_blocks` to show available blocks if not already established.
2. Confirm which block to analyze.

### Step 2: Load Entry Filter Groups

1. Read `entry_filter_groups.csv` using the resolution order.
2. Parse all rows. Report: "Found {n} queryable filters, {p} marked for Report V1."

### Step 3: Check Cache (Phase 1 gate)

1. Check if `{block_folder}/alex-tradeblocks-ref/entry_filter_data.csv` exists.
2. **If it exists:** "Using cached filter data." **Skip to Step 7.**
3. **If not:** Run Phase 1 (Steps 4–6) — identical to alex-entry-filter-pareto Steps 4–6.

### Steps 4–6: Phase 1 (Data CSV)

**Identical to alex-entry-filter-pareto.** The SQL lives in shared files in `_shared/`:

- **Step 4:** Run sufficiency checks from `phase1_sufficiency_checks.default.sql` (replace `{blockId}`, execute each tagged query)
- **Step 5:** Run the data CTE from `phase1_entry_filter_data.default.sql` (replace `{blockId}`, execute via `run_sql`)
- **Step 6:** Write query results to `alex-tradeblocks-ref/entry_filter_data.csv`

See alex-entry-filter-pareto Steps 4–6 for detailed interpretation rules (coverage thresholds, SLR fallback, VIX_Gap_Pct handling).

---

## Phase 2: Generate Parallel Coordinate Plot

### Step 7: Read Data and Build Axis Configuration

Read `entry_filter_data.csv` and `entry_filter_groups.csv`.

**Select Report V1 axes:** Filter to rows where `Report V1 = TRUE` and `CSV Column` is non-blank. Sort by Entry Group order (A→H), then by Index within group.

**Build the DIMS array.** For each Report V1 filter, create an axis definition:

```javascript
{
  key: '<CSV Column>',       // e.g. 'VIX_Close'
  label: '<Filter name>',    // e.g. 'VIX Close'
  group: '<Entry Group>',    // e.g. 'A: Vol Level'
  domain: [min, max],        // from data, with 5% padding
  ticks: [...],              // auto-generated: 6–10 evenly spaced values
  fmt: v => ...              // number formatter appropriate to the field
}
```

**Always append ROM as the final axis:**
```javascript
{
  key: 'rom_pct',
  label: 'RoR %',
  group: 'OUTCOME',
  domain: [min_rom - 5, max_rom + 5],
  ticks: [...],  // auto-scaled
  fmt: v => (v >= 0 ? '+' : '') + v.toFixed(1) + '%'
}
```

**Axis configuration rules by Filter Type:**

| Filter Type | Domain | Ticks | Formatter |
|-------------|--------|-------|-----------|
| continuous | [min−5%pad, max+5%pad] | 6–10 evenly spaced | `v.toFixed(N)` where N = auto based on range |
| binary | [−0.2, 1.2] | [0, 1] | `v => v >= 0.5 ? 'Yes' : 'No'` |
| categorical | [min−0.4, max+0.4] | unique values | Named map (e.g., Term Structure: -1→Back, 0→Flat, 1→Cont) |

**Handle uninformative axes:** If all trades have the same value for an axis (e.g., Day_of_Week = 5 for a Friday-only strategy), **exclude that axis** and note it: "Day of Week excluded — all trades on Friday."

### Step 8: Build Group Color Mapping

Map each Entry Group to a color. Use these defaults:

```javascript
const GROUP_COLORS = {
  'A: Vol Level':     '#e67e22',  // orange
  'B: Rel Vol':       '#9b59b6',  // purple
  'C: Momentum':      '#2ecc71',  // green
  'D: Price Action':  '#3498db',  // blue
  'E: Calendar':      '#1abc9c',  // teal
  'F: Term Str':      '#e74c3c',  // red
  'G: VIX Event':     '#f39c12',  // amber
  'H: Premium':       '#95a5a6',  // silver
  'OUTCOME':          '#dd4466',  // red-pink
};
```

Short group labels for headers:

| Entry Group | Short Label |
|-------------|------------|
| A: Volatility Level | A: Vol Level |
| B: Relative Volatility | B: Rel Vol |
| C: Momentum / Trend | C: Momentum |
| D: Daily Price Action | D: Price Action |
| E: Calendar | E: Calendar |
| F: Term Structure | F: Term Str |
| G: VIX Event | G: VIX Event |
| H: Premium & Structure | H: Premium |

### Step 9: Compute Color Scale Bounds

```javascript
const LO = <min rom_pct>;   // e.g. -31.1
const HI = <max rom_pct>;   // e.g. 60.8
```

Use the three-zone color function from the style guide:
- `t < 0.45` → red gradient (losses)
- `0.45 ≤ t < 0.55` → neutral grey-blue (near-zero ROM)
- `t ≥ 0.55` → green gradient (profits)

### Step 10: Serialize Data

Convert the CSV rows to a columnar JSON object for embedding:

```javascript
const D = {
  'VIX_Close': [29.35, 24.72, ...],
  'ATR_Pct': [2.65, 2.35, ...],
  // ... one array per axis key
  'rom_pct': [56.06, 4.87, ...],
};
const TOTAL = 157;
```

Only include columns that are axes in the plot (Report V1 + rom_pct). Do NOT include all 44 CSV columns — only the ~18–21 that appear as axes.

### Step 11: Generate Self-Contained HTML

Save to: `{block_folder}/filter_parallel_coords.html`

**Architecture: Canvas + SVG hybrid (per style guide)**

- `<canvas id="cvs">` — draws all trade lines (fast, handles thousands)
- `<svg id="pc">` — overlaid at same size for axes, labels, group headers, brush boxes
- D3.js v7 loaded from CDN: `https://d3js.org/d3.v7.min.js`

**Layout:**

```javascript
const M = { top: 90, bottom: 30, left: 48, right: 48 };
```

The 90px top margin provides space for:
- Group label row at `M.top - 28` (colored ALL-CAPS text)
- Group underline bar at `M.top - 22` (colored line spanning group's axes)
- Axis label at `M.top - 6` (white text, 12.5px bold)

**Canvas width:** Responsive, minimum 1200px. Scale axis spacing to fit: `axisSpacing = (width - M.left - M.right) / (numAxes - 1)`.

**Dark theme:**
- Body background: `#0f1117`
- Canvas background: `#0f1117`
- Axis lines: `#334466`
- Axis labels: `#e8ecff`, 12.5px bold
- Tick labels: `#6677aa`, 9px
- Group headers: colored ALL-CAPS text, matching GROUP_COLORS

**Trade line rendering:**
- Each trade = one polyline passing through all axes at its filter values
- Color = `rorColor(rom_pct)` using the three-zone color function
- Opacity: slider-controlled (default 30%)
- Unselected lines (outside brush): 4% opacity
- Lines with NULL values on any axis: skip that axis segment, draw remaining segments

**Brush interaction:**
- Click + drag on any axis → create range filter (semi-transparent colored box)
- Double-click on axis → clear that brush
- Reset All button → clear all brushes
- `brushState = { key: [lo, hi] | null }` in data units
- On brush change: redraw canvas, update stats bar

**Stats bar (bottom of chart):**
- Dark panel (`#12151f`)
- Shows: N trades | % of total | Avg RoR% | Win Rate% | Profit Factor
- Updates live on every brush change
- Font: 'Courier New', monospace, 13px
- Labels in `#8899bb`, values in `#e8ecff`

**Stats bar logic:**
```javascript
function updateStats() {
  const hasBrush = Object.values(brushState).some(v => v !== null);
  const subset = hasBrush ? rows.filter(isSelected) : rows;
  const n = subset.length;
  const rs = subset.map(r => r.rom_pct);
  const ws = rs.filter(r => r > 0), ls = rs.filter(r => r < 0);
  const avg = rs.reduce((a, b) => a + b, 0) / n;
  const wr  = ws.length / n * 100;
  const sumPos = ws.reduce((a, b) => a + b, 0);
  const sumNeg = Math.abs(ls.reduce((a, b) => a + b, 0));
  const pf  = sumNeg > 0 ? sumPos / sumNeg : 999;
  const pct = n / TOTAL * 100;
  // Update DOM elements
}
```

**Controls bar (above chart):**
1. **Opacity slider** (`id="opSlider"`, range 5–100, default 30) — line opacity for selected trades
2. **Color By dropdown** (`id="colorBy"`) — options:
   - `ror` (default) — ROM-based three-zone gradient
   - `year` — extracted from date_opened
   - `month` — extracted from date_opened
   - `ts` — Term Structure State: -1=red, 0=grey, 1=blue

**Complete rendering pipeline:**

```
1. Parse D → transpose to rows[]
2. Build D3 scales (one yScale per axis)
3. Draw canvas lines (all trades, colored by ROM)
4. Draw SVG axes, labels, group headers
5. Attach brush handlers
6. Compute initial stats (no brush = all trades)
```

### Step 12: Inline D3 (Optional, for offline use)

If the user requests a fully self-contained file:
1. Download D3: `curl -s https://d3js.org/d3.v7.min.js -o /tmp/d3.v7.min.js`
2. Replace `<script src="..."></script>` with `<script>{d3_source}</script>`
3. Final file size: ~800–900KB

Default behavior: use CDN link (smaller file, requires internet).

### Step 13: Present Results

Display:
1. File location: `{block_folder}/filter_parallel_coords.html`
2. Summary: "{n} trades × {m} axes ({p} Entry Groups + ROM)"
3. Excluded axes (if any) with reason
4. Quick tips:
   - "Drag on any axis to brush-filter trades"
   - "Double-click to clear a brush"
   - "Use the opacity slider to reveal density patterns"
   - "Switch Color By to 'year' to spot temporal regime shifts"

## Chart Specification Reference

### Color Scale (ROM-based)

```javascript
function rorColor(v) {
  const t = Math.max(0, Math.min(1, (v - LO) / (HI - LO)));
  if (t < 0.45) {
    const s = t / 0.45;
    return `rgb(${Math.round(190-60*s)}, ${Math.round(45+20*s)}, ${Math.round(45+20*s)})`;
  } else if (t < 0.55) {
    return `rgb(80, 80, 105)`;  // near-zero = neutral grey-blue
  } else {
    const s = (t - 0.55) / 0.45;
    return `rgb(${Math.round(40+30*s)}, ${Math.round(160+80*s)}, ${Math.round(100+30*s)})`;
  }
}
```

### Additional Color-By Modes

```javascript
const YEAR_COLORS = {2022:'#8855ee', 2023:'#33aaee', 2024:'#33dd99', 2025:'#ddcc33', 2026:'#ff7733'};
const TS_COLORS   = {'-1':'#ee5533', '0':'#8899aa', '1':'#33aaee'};
// month: hsl((v-1)/11*240, 60%, 55%)
```

### Group Header Rendering

```javascript
// For each unique group in DIMS order:
svg.append('text')
  .attr('x', groupCenterX)
  .attr('y', M.top - 28)
  .text(groupShortLabel)
  .attr('fill', groupColor)
  .attr('font-size', '11px')
  .attr('font-weight', '700')
  .attr('text-anchor', 'middle')
  .style('text-transform', 'uppercase');

// Underline bar spanning group's axes
svg.append('line')
  .attr('x1', firstAxisX - 10)
  .attr('x2', lastAxisX + 10)
  .attr('y1', M.top - 22)
  .attr('y2', M.top - 22)
  .attr('stroke', groupColor)
  .attr('stroke-width', 2);
```

### Axis Rendering

```javascript
// Per axis:
// Vertical axis line from M.top to height - M.bottom
// Tick marks + labels on alternating sides (left/right) to prevent overlap
// Axis label centered above axis at M.top - 6
```

## Customization

- **Change which axes appear:** Edit `Report V1` column in entry_filter_groups.csv. No data rebuild needed.
- **Add a filter axis:** Add row to entry_filter_groups.csv with CSV Column etc. Delete `entry_filter_data.csv` to rebuild.
- **Remove an axis:** Set Report V1 = FALSE. No rebuild needed.
- **Force data rebuild:** Delete `alex-tradeblocks-ref/entry_filter_data.csv`
- **Change color-by default:** "Default color by year instead of ROR"
- **Inline D3:** "Make the file fully self-contained (no CDN)"
- **Change axis order:** "Put VIX group first" — reorder Entry Groups in the DIMS build step

## What NOT to Do

- **Don't draw all 44 CSV columns as axes** — only Report V1 filters. Too many axes = unreadable.
- **Don't use Chart.js** — parallel coordinates requires D3.js for proper axis/brush/canvas rendering.
- **Don't draw lines on SVG** — use Canvas for lines (performance). SVG is only for axes, labels, brushes.
- **Don't hardcode axis definitions** — read from entry_filter_groups.csv. DIMS is built dynamically.
- **Don't include axes where all trades have the same value** — uninformative (e.g., Day_of_Week on a Friday-only strategy).
- **Don't skip the shared Phase 1 cache check** — avoid re-querying if data CSV already exists.
- **Don't estimate ROM from average P/L** — always use `pl / margin_req * 100` per trade.
- **Don't use close-derived fields without prior-day lag** — lookahead bias.

## Related Skills

- `alex-entry-filter-pareto` — Pareto chart of same filters (bar chart view, shares data CSV)
- `alex-threshold-analysis` — Deep dive into a single filter
- `/tradeblocks:dc-analysis` — Comprehensive DC strategy analysis

## Notes

- The data CSV is shared with alex-entry-filter-pareto. Building either skill first creates the cache for both.
- D3.js v7 from CDN by default. Inline option available for offline use (~900KB).
- Canvas handles 7000+ trade lines smoothly. For blocks with < 500 trades, SVG-only rendering would also work but Canvas is used for consistency.
- Binary axes (Gap_Filled, Is_Opex) render as two-tick axes (0/1 with Yes/No labels). Trades cluster on two horizontal lines — brush one value to isolate.
- Categorical axes (Term_Structure, Month) render with named ticks. Trades cluster at discrete values.
- The style guide's original 13 axes (QQQ DC) become ~18–21 axes here (SPX DC), requiring wider canvas or tighter axis spacing. Auto-scale axis spacing to fit.
- NULL values in a trade's filter column: skip that axis segment, draw remaining connected segments. This prevents a single missing value from dropping the entire trade line.
