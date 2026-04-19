# Entry Filter Threshold Sweep — Background & Guide

This README is the "why" companion to `SKILL.md` (which is the "what"). It walks through the concepts, the two calculation variants we support, worked examples showing when they agree and when they diverge, and common questions that came up during design.

If you're looking for CLI syntax or the exact exit-code table, read `SKILL.md` instead.

---

## What the sweep does in one paragraph

For every continuous entry filter on a block (SLR, VIX_Close, RSI_14, …), the sweep asks: "if I apply this filter at various settings, how much of my baseline Net ROR do I keep, and what's the average per-trade edge of the survivors?" It does this sweep three ways (low threshold, high threshold, combo range) against two metrics (avg ROR, avg PCR) using two selection rules (tightest, max_avg). The result is a pre-computed CSV that downstream reports (heatmap, pareto, etc.) read instead of recomputing the O(threshold × retention_target) loops on every run. One sweep, many reports.

---

## Concepts

### Net ROR retention

The denominator for the "did this filter keep my edge?" question.

```
retention(filter_setting, T) = sum(rom_pct of survivors) / sum(rom_pct of all trades) × 100
```

A filter retention of 80% means: applying this filter kept 80% of my baseline cumulative return. A retention above 100% means the filter *boosted* Net ROR by dropping losers.

### Threshold direction

Three ways to apply a filter:

- **Low threshold (>=):** keep trades with `filter_value >= t`. Example: "only trade when VIX >= 18". The `t` is a lower bound; low threshold = "minimum VIX" semantic.
- **High threshold (<=):** keep trades with `filter_value <= t`. Example: "only trade when VIX <= 25". The `t` is an upper bound.
- **Combo [lo, hi]:** keep trades with `lo <= filter_value <= hi`. Example: "only trade when VIX between 15 and 25". Two-parameter range.

### Retention target columns

The CSV has a column for each retention target T: `R_115`, `R_110`, `R_105`, …, `R_5`, `R_0` (in 5% steps, data-driven upper bound). Each cell answers a question of the form: *"What's the best filter setting that still keeps at least T% of baseline Net ROR, and what's the avg metric of its survivors?"*

"Best" is where the two **variants** differ.

### Variants: `tightest` vs `max_avg`

This is the central design choice. Both select among qualifying thresholds (any `t` where retention ≥ T), but they define "best" differently.

| Variant | Selection rule | Meaning |
|---|---|---|
| **`tightest`** | Smallest survivor count among qualifiers (= most selective threshold). For low direction, highest `t`; for high direction, lowest `t`; for combo, smallest `n`. | "What's the most aggressive filter I can apply and still keep T% of my edge?" |
| **`max_avg`** | Highest avg of the chosen metric (ROR or PCR) among qualifiers. | "What's the best-performing filter setting that clears the T% retention constraint?" |

In **monotonic** retention curves (the standard case — tighter filter = lower retention = higher per-trade edge), both variants pick the same threshold. The two rows in the CSV are identical.

In **non-monotonic** curves — where the retention curve rises before falling, because the low end of the filter range is disproportionately loss-heavy — they can pick meaningfully different thresholds. See the second worked example below.

### Threshold rows vs avg rows

The `metric` column has four values per (filter × direction × variant):

- **`AvgROR`** — the avg per-trade ROR of survivors at the chosen threshold. Cell = a %.
- **`AvgPCR`** — the avg per-trade PCR of survivors at the chosen threshold. Cell = a %.
- **`ThresholdROR`** — the actual filter value(s) that drove the AvgROR row. Cell = a number (low/high direction) or `"lo|hi"` string (combo).
- **`ThresholdPCR`** — the actual filter value(s) that drove the AvgPCR row.

For the `tightest` variant, the same threshold drives both ROR and PCR selection (the selection is metric-agnostic), so `ThresholdROR` and `ThresholdPCR` are equal.

For the `max_avg` variant, ROR and PCR rankings of survivors can disagree — a threshold that maximizes ROR may not maximize PCR, and vice versa — so the two threshold rows can differ.

### `max_net_ror` column

Right before the `R_` columns. One value per (filter × direction), repeated across the 8 rows of that pair. It's the **peak retention achieved** by any qualifying threshold for that filter/direction, regardless of which target buckets we report.

Why? The bucketed retention columns tell you what happened at 5% increments; `max_net_ror` tells you the ceiling without bucket rounding. Useful when the peak sits between two target columns, or when you just want to know "does this filter ever beat baseline?" at a glance.

---

## Worked examples

### Example 1: monotonic retention curve (the easy case)

Filter: a well-behaved one. As we raise the threshold, we exclude trades uniformly — no systematic loss cluster at either end. Retention drops smoothly, and per-trade edge rises (the remaining trades are the more selective subset).

| t | survivors | retention | avg ROR | avg PCR |
|---|---|---|---|---|
| 0.29 | 173 | 100% | +8% | +5% |
| 0.40 | 140 | 85% | +10% | +6% |
| 0.50 | 110 | 70% | +12% | +7% |
| 0.60 | 80 | 55% | +14% | +8% |
| 0.70 | 55 | 40% | +16% | +9% |
| 0.80 | 30 | 25% | +18% | +10% |

For retention target R_70 (keep at least 70% of baseline):
- Qualifying thresholds: t = 0.29, 0.40, 0.50 (retention 100, 85, 70 — all >= 70).
- **Tightest**: t = 0.50 (smallest survivor count among qualifiers = 110). Report avg ROR +12%, avg PCR +7%.
- **Max_avg for ROR**: t = 0.50 (highest avg ROR among qualifiers = +12%). Same.
- **Max_avg for PCR**: t = 0.50 (highest avg PCR among qualifiers = +7%). Same.

Both variants agree. The CSV's `tightest` and `max_avg` rows are identical for this filter.

Rows walking from R_0 rightward to R_100:
- R_0: t=0.80, avg ROR +18%
- R_25: t=0.80, avg ROR +18%
- R_40: t=0.70, avg ROR +16%
- R_55: t=0.60, avg ROR +14%
- R_70: t=0.50, avg ROR +12%
- R_85: t=0.40, avg ROR +10%
- R_100: t=0.29, avg ROR +8%

As T increases (stricter retention), avg ROR decreases. Clean monotonic efficiency frontier.

### Example 2: non-monotonic retention curve (where variants diverge)

Filter: first 20% of trades (by filter value) are a loss cluster. Raising the threshold initially *boosts* retention (we're dropping losers), peaks at t=0.55 (retention 125%, avg ROR +16%), then falls back as we start dropping winners too.

| t | survivors | retention | avg ROR | avg PCR |
|---|---|---|---|---|
| 0.29 | 173 | 100% | +8% | +3% |
| 0.45 | 138 | 118% | +14% | +10% |
| **0.55** | **130** | **125% (peak)** | **+16%** | **+12%** |
| 0.60 | 120 | 120% | +15% | +13% |
| 0.70 | 100 | 112% | +13% | +14% (peak PCR) |
| 0.80 | 85 | 103% | +11% | +13% |
| 0.85 | 70 | 99% | +10% | +12% |
| 0.90 | 50 | 80% | +8% | +10% |

For retention target R_100:
- Qualifying thresholds (retention >= 100%): t = 0.29, 0.45, 0.55, 0.60, 0.70, 0.80 (all retention >= 100).
- **Tightest**: t = 0.80 (smallest survivor count = 85 among qualifiers). Report avg ROR +11%, avg PCR +13%.
- **Max_avg for ROR**: t = 0.55 (highest avg ROR = +16%). Report avg ROR +16%.
- **Max_avg for PCR**: t = 0.70 (highest avg PCR = +14%). Report avg PCR +14%.

All three pick different thresholds. The `tightest` row shows where the threshold ends up if you just "keep tightening until you bump into the 100% floor"; `max_avg` rows show where the best-performing subset actually lives. In this scenario, the tightest threshold is on the *far side* of both the ROR and PCR peaks — further-in than optimal.

This is why both variants are in the CSV. Tightest reveals the *shape* of the filter's behavior (where does it peak? at which target does it stop paying off?); max_avg reveals the *optimum* (what's the best you can do under this constraint?).

### Example 3: combo direction, max_avg variant

Filter: VIX_Gap_Pct. Combo is a two-sided filter `[lo, hi]` — "only trade when VIX O/N is between lo and hi".

At R_80 for `variant = max_avg`:
- `AvgROR` row: picks `ThresholdROR = 0.465 | 0.649` (combo range 0.465–0.649), reports +13.10% avg ROR.
- `AvgPCR` row: picks `ThresholdPCR = 0.292 | 0.578` (combo range 0.292–0.578), reports −7.25% avg PCR.

The two ranges are different because the "best ROR" combo and the "best PCR" combo don't overlap exactly — the filter cluster that produces high per-trade ROR is not quite the same as the one producing high per-trade PCR. That's precisely why we report both thresholds: the user can read each one as its own answer to the question "what filter setting gives me the best X at this retention constraint?"

---

## FAQ

### Q: When should I use `tightest` vs `max_avg`?

Use **`tightest`** for:
- Heatmap-style overviews where you want to see the curve's shape.
- "How aggressive can I get while still keeping T% edge?" framings.
- Diagnostic work — spotting non-monotonic behavior, spotting where a filter stops producing marginal gains.

Use **`max_avg`** for:
- Picking an actual filter setting to deploy.
- Pareto charts — "what's the best achievable edge at each retention budget?"
- Optimization — you have a retention floor and want maximum expected per-trade return.

The heatmap defaults to `tightest` because it visualizes the curve shape. The pareto skill (future) will default to `max_avg` because it's picking one point on the frontier per filter.

### Q: Why does the same threshold show up in many R_T columns for tightest?

In monotonic curves, the tightest threshold that clears a strict retention target (say 80%) also clears any looser target (60%, 40%, …). So as you walk rightward (lower T), the tightest threshold stays the same until you hit a retention level where a *tighter* threshold becomes available.

Concretely in Example 1: R_85 picks t=0.40 (retention 85% exactly). R_70 picks t=0.50 (retention 70% exactly). Between those two, no threshold has a retention in (70%, 85%), so R_80 and R_75 don't exist as options — they fall back to t=0.40 (since that's the tightest clearing 80% and 75% both).

If the grid were finer (step=1% instead of 5%), the CSV would track these finer-grained boundaries.

### Q: Why is ThresholdROR sometimes equal to ThresholdPCR in max_avg rows?

Because the ROR-best threshold and PCR-best threshold *coincide* when the trade that pushes up ROR is the same one pushing up PCR. For many filters on many blocks, ROR and PCR move together (big winners have both high ROR and high PCR). They only diverge when there's a premium-vs-margin sizing mismatch in the trade set — some trades have high ROR but modest PCR, others the reverse.

### Q: What's the difference between `max_net_ror` and the highest `R_*` column?

- `R_115` (or whatever the ceiling column is) = avg metric at the chosen threshold for the retention target of 115%. It's a *cell value* reflecting the avg ROR or PCR of survivors.
- `max_net_ror` = the actual peak retention observed, regardless of bucketing. It's a *scalar per row* reflecting the raw retention number (e.g., 111.0%, not a cell content).

Use `max_net_ror` to identify filters that beat baseline; use the highest non-blank `R_*` column to see *at what retention level* they beat and by how much.

### Q: Why is the sweep a separate skill instead of part of the heatmap?

Because multiple downstream skills want these numbers — not just the heatmap. The pareto skill, a future report-comparison skill, any ad-hoc Excel analysis — all benefit from reading the CSV once. Computing the sweep inline in every consumer was O(N_filters × pairs × targets) *per run*; now it's O(N_filters × pairs × targets) *once*, then O(read) forever after.

Also: the sweep CSV is a stable artifact. You can commit it alongside a strategy's other artifacts, diff it across revisions, open it in Excel, join it in pandas. That's harder when the data only exists inside generated HTML.

### Q: Why exclude binary/categorical filters?

"Sweep a threshold" is a continuous-filter concept. For binary filters (Gap_Filled), there are two values — no threshold to sweep. For categorical filters (Day_of_Week, Vol_Regime), each value is its own cluster; there's no ordering to walk along.

The heatmap computes binary/categorical breakdowns directly from `entry_filter_data.csv` — it doesn't need precomputation because those analyses are O(trades), not O(trades × thresholds × targets).

### Q: Why is the retention ceiling data-driven?

Two reasons:
1. **CSV width scales with need.** Blocks where nothing beats baseline cap at R_105 (24 target cols). Blocks with above-baseline subsets extend (e.g., R_145 for a filter that drops losers and retains 141% of baseline). You don't pay for the wide columns unless your data actually uses them.
2. **Visual cue.** We always include *one* blank column above the max achieved — so seeing a blank `R_115` next to populated `R_110` tells you "111% was the absolute best; R_115 was probed and nobody qualified". If the top column has data, the filter *might* go higher and we just didn't extend the grid — a signal to rerun with a higher step or inspect the underlying data.

### Q: Can I use this for a filter that has >10% nulls?

No. Filters with >10% null values in the data column are skipped by the sweep (reported in the console as "skipped (column not in data)" or "skipped (>10% nulls)"). Reason: sparsely-populated filters give biased retention numbers because the baseline is computed across all trades but the retention subset can only be computed across non-null trades.

If you need such a filter, either fix the data pipeline (via `dev-entry-filter-build-data`) so the column is fully populated, or accept that the filter is out of scope for this analysis.

---

## Downstream use cases

### Heatmap (currently live)

`dev-entry-filter-heatmap` reads the sweep CSV, filters to one (metric, variant) pair — default `(AvgROR, tightest)` — and renders:
- Discovery Map (Min/Max cells per filter × retention target).
- Retention Detail (Min/Max/Combo with cell values).
- Binary/Categorical breakdown (computed directly, not from sweep CSV).

A `--sweep-variant max_avg` flag re-renders the same heatmap using the max-avg rows instead — useful for spotting filters where the tightest threshold under-reports the achievable edge.

### Pareto (future refactor)

Replace the current recompute-in-script sweep with a read from the CSV. At a single retention target (say 80%), list every filter's best avg ROR (from max_avg rows) side by side. The list is a one-shot snapshot of "which filter has the best edge at 80% retention?"

### Efficiency frontier export

The sweep CSV's `R_*` columns for one filter (max_avg variant) are effectively the x/y pairs of its efficiency frontier. Export a single row to a charting library and you have the frontier without re-running the sweep.

### Cross-block comparison

Keep sweep CSVs alongside each block's trade data. Compare a filter's efficiency curve between, say, a 2022 backtest block and a live-trading block — spot drift in edge-per-retention as a data-quality check. Requires some pandas gymnastics but the CSV shape makes it straightforward.

### Ad-hoc curation

Open the CSV in Excel. Sort by `max_net_ror` descending to find filters that most strongly beat baseline. Look at the `R_100` column (avg metric at 100% retention) — filters where this is well above baseline are candidates for inclusion even without tightening. Filters where `max_net_ror` barely exceeds 100 are mostly giving you the baseline back after subsetting — less edge than noise.

### Threshold-analysis skill (doesn't read the sweep CSV)

The single-filter interactive `dev-entry-filter-threshold-analysis` intentionally recomputes client-side in JavaScript — so the user can zoom the X axis, adjust bounds, etc. without requiring a round-trip. The sweep CSV is not a substitute for that skill's interactive drill-down.

---

## Semantics summary table

| Situation | Tightest picks | Max_avg (ROR) picks | Max_avg (PCR) picks |
|---|---|---|---|
| Monotonic curve (standard) | Same as max_avg (both = tightest qualifying threshold) | Same as tightest | Same as tightest |
| Non-monotonic — peak in middle, both ends below T | Tightest survivor count on the side past the peak | Threshold at/near the peak with best ROR | Threshold at/near the peak with best PCR |
| Combo, monotonic | Smallest-n pair meeting T | Highest-avg-ROR pair meeting T | Highest-avg-PCR pair meeting T |
| Combo, non-monotonic | Smallest-n pair (often narrow, possibly far from ROR/PCR optima) | Highest-avg-ROR pair | Highest-avg-PCR pair (can differ from ROR's choice) |

---

## File layout inside the skill folder

```
dev-entry-filter-threshold-sweep/
├── SKILL.md     ← CLI reference, exit codes, schema table (the "what")
├── README.md    ← this file (the "why")
└── gen_sweep.py ← the Python driver
```

`SKILL.md` is the quick-reference; read it when you're invoking the skill and need exact syntax. `README.md` is the conceptual onboarding; read it when you're trying to understand the output CSV or decide which variant to use.
