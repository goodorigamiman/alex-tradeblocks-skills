# SqueezeMetrics DIX/GEX Datelist — Trading-Day-Indexed Continuous + Derived Feature Table

File: `entry_filter_dates_sm.default.csv`

## Scope

Trading-day-indexed feature table covering one row per **trading day** from 2011-05-02 through 2026-04-22 (3,766 rows × 8 columns). Each row carries SqueezeMetrics' three published daily metrics (S&P 500 reference price, the Dark Index DIX, and Gamma Exposure GEX) plus four derived features built on top: 1-year rolling percentile ranks for DIX and GEX, a positive/negative sign categorical for GEX, and a low/mid/high band categorical for DIX based on SM's published regime thresholds.

This file is **anchor-agnostic** — consumed by the entry-filter build pipeline via a left-join on `date_opened`. The builder handles anchor prefixing (`Open_*`, `ShortExp_*`, etc.); this file does not.

## Source

**This file is the source of truth** — there is no separate source CSV in `_shared/`. Original data comes from **SqueezeMetrics** (https://squeezemetrics.com), a research firm publishing dealer-hedging and dark-pool flow indicators. Their published CSV is freely available:

> **Refresh URL**: https://squeezemetrics.com/monitor/static/DIX.csv

This datelist file aggregates (a) S&P 500 daily reference price, (b) the proprietary DIX (Dark Index) — dollar-weighted dark-pool short-volume share for the SPX component universe, and (c) GEX (Gamma Exposure) — dollar-aggregate dealer gamma across SPX option strikes — plus 4 derived features (rolling percentile ranks + categorical bands). Coverage starts 2011-05-02 (DIX inception); SqueezeMetrics updates the upstream feed end-of-day each trading day.

**Provenance**: data is sourced and computed by SqueezeMetrics from FINRA Reg SHO files (DIX) and CBOE option open-interest tapes (GEX). The SM CSV is treated as ground truth — we re-shape it (column rename + derived features) but make no analytical changes.

## Build process

A two-stage Python transform: stage 1 copies and renames source columns; stage 2 derives the 4 categorical/percentile features.

### Stage 1 — column rename

1. Read `DIX-3.csv` (4 columns: `date`, `price`, `dix`, `gex`).
2. Rename `price` → `sm_price`, `dix` → `sm_dix`, `gex` → `sm_gex`. The `date` column kept as-is (PK convention shared across all `entry_filter_dates_*` files).

### Stage 2 — derived features

Add 4 derived columns after the source columns:

**1. `sm_dix_pct_rank_252d` — 1-year rolling percentile rank of DIX**

For each row, compute the percentile rank of `sm_dix` within the trailing 252-trading-day window (window includes today). Convention: fraction of window values `<=` today's value, scaled 0–100, rounded to 2 decimals.

```python
def rolling_pct_rank(series, window=252):
    return series.rolling(window=window, min_periods=window).apply(
        lambda w: 100.0 * (w <= w.iloc[-1]).sum() / len(w),
        raw=False
    )

df['sm_dix_pct_rank_252d'] = rolling_pct_rank(df['sm_dix'], 252).round(2)
```

- Output range: 0.0 to 100.0
- Warmup: first 251 rows are `NULL` (need full 252-day window before ranking is meaningful)
- Interpretation: `>50` = above 1-yr median, `>80` = top 20%, `<20` = bottom 20%
- Window choice: 252 trading days ≈ 1 calendar year, matches the file's trading-day indexing

**2. `sm_gex_pct_rank_252d` — 1-year rolling percentile rank of GEX**

Same algorithm, applied to `sm_gex`:

```python
df['sm_gex_pct_rank_252d'] = rolling_pct_rank(df['sm_gex'], 252).round(2)
```

Same warmup pattern (first 251 rows `NULL`). Robust to GEX's heavily skewed distribution since percentile rank is non-parametric — no assumption about Gaussian shape.

**3. `sm_gex_sign` — positive/negative categorical for GEX**

```python
import numpy as np
df['sm_gex_sign'] = np.where(df['sm_gex'] >= 0, 'positive', 'negative')
```

- Values: `positive` (GEX ≥ 0, vol-damping regime) or `negative` (GEX < 0, vol-amplifying regime)
- No warmup — per-row independent
- Distribution in current data: ~91% positive, ~9% negative
- Boundary at 0 inclusive (GEX = 0 → `positive`); GEX is essentially never exactly zero in practice (continuous values)

**4. `sm_dix_band` — low/mid/high categorical for DIX**

Bins follow SqueezeMetrics' published regime cuts (see `Source data semantics` for context):

```python
def dix_band(v):
    if v < 0.40:  return 'low'    # No accumulation
    if v < 0.45:  return 'mid'    # Neutral
    return 'high'                  # Accumulation regime

df['sm_dix_band'] = df['sm_dix'].apply(dix_band)
```

- Values: `low` (DIX < 0.40), `mid` (0.40 ≤ DIX < 0.45), `high` (DIX ≥ 0.45)
- No warmup — per-row independent
- Distribution in current data: low 15.7%, mid 51.0%, high 33.2%
- Boundaries half-open right: `<0.40` is `low`; exactly 0.40 is `mid`; exactly 0.45 is `high`

### Stage 3 — write

Write atomically (`.tmp` + `os.replace`) to `entry_filter_dates_sm.default.csv` with LF line endings, no BOM, numeric values in raw decimal form (no scientific notation). 8 columns total: `date`, `sm_price`, `sm_dix`, `sm_gex`, `sm_dix_pct_rank_252d`, `sm_gex_pct_rank_252d`, `sm_gex_sign`, `sm_dix_band`.

## Why this shape

**Continuous source values + derived classification features.** The other four datelist files (holidays, econ_calendar, opex, earnings) all derive proximity features (days/weeks to/from events). DIX and GEX are *regime-state* indicators — they describe a continuous condition each trading day, not events to count distance to. The natural derived features here are:

- **Threshold buckets** (categorical) — `sm_gex_sign` and `sm_dix_band` are ready-to-use regime flags.
- **Rolling percentile rank** — `sm_dix_pct_rank_252d` and `sm_gex_pct_rank_252d` capture regime shifts relative to the trailing year, robust to outliers.

Other potential derivations (z-scores, GEX × DIX quadrants, longer/shorter rolling windows) are deferred — see Open design questions.

**Trading-day indexed** (not weekday or calendar-day). Source publishes one value per trading day — no weekend or closure-day rows. Joins to `entry_filter_data.date_opened` work cleanly.

## Source data semantics

### What the data measures

**`sm_price`** — S&P 500 daily close as recorded by SqueezeMetrics. Reference level only; not the SPX spot used inside SM's GEX calculation. Use it for sanity-checking date alignment, not as an authoritative SPX feed.

**`sm_dix` (Dark Index)** — dollar-weighted percentage of *short* volume in S&P 500 component stocks executed through FINRA's off-exchange venues (ATSs + internalizers, collectively "dark pools"). Range: 0.33–0.55 (~0.43 mean, σ≈0.04).

> **Counter-intuitive interpretation**: higher DIX = more *buying* pressure, not selling. Why: market-makers in dark pools quote spreads with no inventory, so when an investor *buys* from a dealer, the dealer's side prints as a short sale. Dark-pool short-volume % is therefore a proxy for investor buying pressure, not a bearish indicator. SqueezeMetrics' "Short Is Long" paper (Mar 2018) is the canonical reference.

**`sm_gex` (Gamma Exposure)** — dollar-denominated aggregate of `Γ · OI · 100` across every SPX option strike and expiry, signed so that calls contribute positive gamma and puts contribute negative gamma. Quantifies the dealer hedging burden. Range: −$7.5B to +$24.2B (mean +$3.0B, median +$2.5B). Negative-GEX days are ~9% of history.

### Mechanics that make these signals predictive

**GEX hedging mechanics** — SqueezeMetrics' Dec 2017 white paper:
- Dealers are net long call gamma (calls overwritten by investors) and net short put gamma (puts bought by investors).
- **Net long gamma → dealer sells into rallies, buys into dips → dampens volatility.**
- **Net short gamma → dealer buys into rallies, sells into dips → amplifies volatility.**

Empirical: positive-and-high-GEX days (top quartile) had 0.55% next-day SPX σ vs 0.85% on moderate-positive days. Negative-GEX days carry exponentially larger σ — they're rare (~9% of history) but disproportionately drive the tails.

**DIX accumulation mechanics** — "Short Is Long" paper:
- Mean 60-day forward SPX return at dataset baseline: +2.8%.
- Mean 60-day forward SPX return when DIX ≥ 0.45: **+5.3%**.
- DIX *rises into corrections* — investors accumulate components at lowered valuations through dark-pool buying, visible before price recovery.
- Medium-term signal (weeks-to-months), not intraday.

**Regime thresholds (used for `sm_dix_band`):**
- DIX ≥ 0.45: accumulation signal, bullish forward 1–3 months. → `band = high`
- DIX 0.40–0.45: neutral, weaker tailwind. → `band = mid`
- DIX < 0.40: reduced accumulation. Extended periods <0.35 historically coincide with topping/pre-correction. → `band = low`

### Combined GEX × DIX reading (derived, not in source)

The two signals are independent and measure different mechanics. The four-quadrant interpretation:

| | **DIX high** (accumulation) | **DIX low** (no accumulation) |
|---|---|---|
| **GEX high** (vol-damped) | Strongest constructive — buying + range-bound | Complacency; vulnerable to regime shift if GEX inverts |
| **GEX low / negative** (vol-amplified) | Accumulation during correction; buy-the-dip regime | Distribution + vol expansion — avoid short-vol structures |

For option-selling strategies (calendars, condors, diagonals), the cleanest setup is high-GEX regardless of DIX — dealer hedging absorbs the moves these structures dislike. Negative-GEX with low DIX is the worst environment.

### Known caveats from SqueezeMetrics

- **DIX covers only S&P 500 components.** Single-name dark-pool signal exists but requires raw FINRA data wrangling.
- **Lit-exchange short volume is excluded** — adding it would get closer to the SEC's ~49% figure but would change the signal calibration.
- **GEX assumes dealers hedge to option delta** — real dealers use hedging bands, so GEX is an approximation. The relationship is robust enough in aggregate.
- **Extreme dark-pool short readings are noisy** — >80% often reflects illiquid block shorting; <20% often reflects bilateral blocks with no dealer intermediary. Use the 20–60% band where the signal is clean.
- **Post-2022 0DTE options dominance** could shift GEX's applicability — paper vintage is 2017, relationships have held through coverage but worth re-validating on post-2022 data before using as a standalone signal.

## Column reference

In file order:

| # | Column | Type | Definition |
|---|---|---|---|
| 1 | `date` | ISO date | Trading day; PK. |
| 2 | `sm_price` | continuous | S&P 500 daily close (reference level only — not authoritative SPX feed). |
| 3 | `sm_dix` | continuous (0–1) | SqueezeMetrics Dark Index — dollar-weighted dark-pool short-volume share of SPX components. Higher = more investor buying pressure. |
| 4 | `sm_gex` | continuous (USD) | SqueezeMetrics Gamma Exposure — aggregate dealer gamma across SPX options in dollars. Positive = vol-damping regime; negative = vol-amplifying. |
| 5 | `sm_dix_pct_rank_252d` | continuous (0–100), nullable | 1-year rolling percentile rank of `sm_dix` (252 trading days). NULL for first 251 rows (warmup). See Build process for algorithm. |
| 6 | `sm_gex_pct_rank_252d` | continuous (0–100), nullable | 1-year rolling percentile rank of `sm_gex` (252 trading days). NULL for first 251 rows (warmup). |
| 7 | `sm_gex_sign` | categorical | `positive` (GEX ≥ 0, ~91% of days) or `negative` (GEX < 0, ~9% of days). |
| 8 | `sm_dix_band` | categorical | `low` (DIX < 0.40), `mid` (0.40 ≤ DIX < 0.45), or `high` (DIX ≥ 0.45). Bins from SM's published regime thresholds. |

### Feature list for entry filter data build

All 7 non-date columns are eligible features. Names follow the canonical snake_case convention:

```
sm_price                       continuous (USD)
sm_dix                         continuous (0–1)
sm_gex                         continuous (USD)
sm_dix_pct_rank_252d           continuous (0–100, nullable on warmup)
sm_gex_pct_rank_252d           continuous (0–100, nullable on warmup)
sm_gex_sign                    categorical {positive, negative}
sm_dix_band                    categorical {low, mid, high}
```

Total feature columns available to the entry filter builder: **7** (excluding `date` join key). Mix of continuous values, rolling normalizations, and pre-built regime classifiers.

## Semantics

This file does not use the proximity (days/weeks to/from) or same-week-zero conventions used by the other four datelist files — those apply only to event-derived features. Instead:

**Continuous values:**
- `sm_dix` is unitless in [0, 1]; treat as a percentage (0.45 = 45%).
- `sm_gex` is in raw USD (e.g. `2509335000` = $2.5B). No scaling applied.
- `sm_price` is in raw USD (e.g. `7137.9` = SPX 7137.9). No scaling.

**Percentile ranks:**
- 0–100 scale, where 50 = trailing-year median.
- Convention: fraction of trailing 252-day window with values `<=` today's value, scaled to 0–100.
- Warmup: first 251 rows `NULL` (insufficient history for full window).

**Categorical features:**
- `sm_gex_sign` ∈ {`positive`, `negative`}. Boundary GEX=0 is `positive`.
- `sm_dix_band` ∈ {`low`, `mid`, `high`}. Boundaries half-open right: 0.40 → `mid`, 0.45 → `high`.

**Null handling:**
- Source has no NULLs in DIX or GEX within the published range.
- Percentile rank columns have NULLs in the first 251 rows (warmup). Treat as missing-value at consumer level.
- Categorical columns never have NULLs (defined for every row).

**Naming convention:**
- snake_case throughout.
- All value columns prefixed `sm_*` (parallel to `holidays_*`, `econ_calendar_*`, `opex_*`, `earnings_*`).

## Coverage gaps and forward-extension policy

| Range | Affected columns | Reason |
|---|---|---|
| 2011-05-02 to 2012-04-29 (first 251 rows) | `sm_dix_pct_rank_252d`, `sm_gex_pct_rank_252d` | Rolling 252-day window not yet full. First valid percentile rank: 2012-04-30. |
| Before 2011-05-02 | All | DIX inception is 2011-05-02; SqueezeMetrics has no earlier data. |
| After the latest source refresh date | All | SM publishes daily; any gap reflects a missed manual refresh. |

The current file ends 2026-04-22, which is **earlier than the other four datelist files** (those end 2026-12-XX). SM data updates daily but our copy reflects the most recent manual download. Refresh cadence is the user's responsibility (see Regenerating below).

**Forward-extension policy** (shared across all five datelist files): never pre-extend the file forward beyond the source's published range. Pre-extension would silently produce all-NULL rows that downstream consumers would have to special-case. Better to keep the file bounded to actual source data and have the entry filter builder treat out-of-range trades as missing-value (skip).

## Philosophy decisions

1. **Source columns kept as a thin layer.** No transformation of values, no rounding, no rescaling. The DIX value of `0.4836678367242191` is preserved exactly as SqueezeMetrics published it.

2. **Derived features added directly in the file** rather than computed at consumption time. The percentile ranks and categorical bands are stable functions of the source data and don't change between consumers — pre-computing them keeps the entry filter analysis simpler.

3. **`sm_*` prefix on all value columns** to match the dataset stem (parallel to `holidays_*`, `econ_calendar_*`, `opex_*`, `earnings_*`). The `date` column is unprefixed by convention across all five files.

4. **Trading-day indexed.** Source already publishes one value per trading day — preserved that structure.

5. **252-day window for rolling percentile.** Approximates 1 calendar year of trading days (252 ≈ 365 × 5/7 × ~252/261 weekdays-trading-days ratio). Captures regime changes relative to recent baseline rather than all-time history. Could use 60-day or 504-day windows for shorter/longer-term regime views (deferred — see Open design questions).

6. **Percentile rank over z-score.** Percentile rank is non-parametric (no Gaussian assumption) and robust to outliers. GEX has heavy tails (range −$7.5B to +$24.2B); z-score would be sensitive to those tails. DIX is closer to normal but using percentile rank for both maintains a consistent interpretation across features.

7. **Null warmup, not back-filled with shorter windows.** First 251 rows of percentile rank columns are NULL. Alternatives (expanding window for warmup, smaller minimum window) would produce values that mean different things at different points in the file — better to be explicit about the warmup gap.

8. **`sm_gex_sign` boundary at 0 inclusive (positive).** GEX is essentially never exactly zero in practice (continuous values), so the boundary choice is academic. Using `>=` gives a clean two-state split.

9. **`sm_dix_band` boundaries from SM's published thresholds.** 0.40 and 0.45 are the cuts cited in SM's papers as accumulation regime boundaries. Using their values keeps the categorical feature interpretable in their terms.

10. **Manual refresh, not automated.** Refresh is the user's responsibility — download the CSV from SqueezeMetrics and re-run the build transform. No automated scheduler / scraper.

11. **No forward extension past source data** (shared across all five datelist files).

## Statistics

| Metric | Value |
|---|---:|
| Trading days in file | 3,766 |
| Earliest / latest date | 2011-05-02 / 2026-04-22 |
| Total columns | 8 |
| Source columns | 4 (date + price + dix + gex) |
| Derived feature columns | 4 |
| `sm_price` range | $1,099.23 – $7,137.90 |
| `sm_dix` range | 0.331 – 0.552 |
| `sm_dix` mean / median | 0.436 / 0.433 |
| `sm_gex` range | −$7.50B – +$24.22B |
| `sm_gex` mean / median | +$3.00B / +$2.51B |
| `sm_gex_sign = positive` | 3,420 (90.8%) |
| `sm_gex_sign = negative` | 346 (9.2%) |
| `sm_dix_band = low` (<0.40) | 592 (15.7%) |
| `sm_dix_band = mid` (0.40–0.45) | 1,922 (51.0%) |
| `sm_dix_band = high` (≥0.45) | 1,252 (33.2%) |
| Warmup rows with NULL percentile ranks | 251 (first valid: 2012-04-30) |

**Coverage span comparison vs the other datelists:**

| Dataset | Earliest | Latest | Years |
|---|---|---|---:|
| Holidays | 2018-01-01 | 2026-12-31 | 9 |
| Econ Calendar | 2022-01-03 | 2026-12-31 | 5 |
| OPEX | 2018-01-01 | 2026-12-31 | 9 |
| Earnings | 2022-01-03 | 2026-12-18 | ~5 |
| **SM (this file)** | **2011-05-02** | **2026-04-22** | **~15** |

This is the longest-history datelist in the set — useful for studying regime behavior across multiple business cycles.

### GEX distribution detail

GEX is **heavily right-skewed** with heavy tails (skew = 1.73, kurtosis = 7.08). Mean ($3.00B) > median ($2.51B) confirms the upward tilt. Quantile breakdown:

| Percentile | GEX value |
|---:|---:|
| 1% | −$1.92B |
| 5% | −$0.62B |
| 10% | +$0.07B |
| 25% | +$1.29B |
| 50% (median) | +$2.51B |
| 75% | +$4.20B |
| 90% | +$6.53B |
| 95% | +$7.86B |
| 99% | +$13.39B |

Histogram (count of trading days in $2B bins):

```
   bin       n      bar
  -8 to -6    2     
  -6 to -4    3     
  -4 to -2   29    █
  -2 to  0  312    ████████████              ← negative GEX = vol-amplifying (~9.2%)
   0 to +2 1119    ███████████████████████████████████████████
  +2 to +4 1285    ██████████████████████████████████████████████████  ← median + mean
  +4 to +6  555    █████████████████████
  +6 to +8  284    ███████████
  +8 to+10  100    ███
 +10 to+12   29    █
 +12 to+14   17    
 +14 to+16   14    
 +16+        31    
```

**Where the mass lives**:
- ~64% of all days fall in `[$0, +$4B]` — the "normal" vol-damping regime
- ~9.2% are negative — SM's vol-amplifying regime
- <1% exceed +$10B — extreme deep-positive regimes

Implication for the `sm_gex_pct_rank_252d` feature: the rolling rank converts these absolute levels into regime-relative positioning. A +$5B reading in a calm year (2024) might rank in the bottom quartile; the same +$5B in 2022 ranks in the top quartile. Same absolute value, very different regime context.

### GEX regime by year

The annual breakdown tells a vivid market-history story — regime context that the rolling percentile can't fully capture on its own:

| Year | n_days | Mean | Min | Max | Neg-GEX days | Neg % | Notes |
|---|---:|---:|---:|---:|---:|---:|---|
| 2011 | 170 | +$0.78B | −$1.19B | +$4.18B | 30 | 17.6% | Eurozone crisis, S&P downgrade |
| 2012 | 250 | +$1.78B | −$1.22B | +$8.99B | 13 | 5.2% | Recovery |
| 2013 | 252 | +$2.17B | −$0.28B | +$8.99B | 2 | 0.8% | QE-driven calm |
| 2014 | 252 | +$2.79B | −$0.49B | +$6.66B | 5 | 2.0% | Calm; Russia / oil crisis late year |
| 2015 | 252 | +$1.59B | −$1.27B | +$3.80B | 23 | 9.1% | China devaluation Aug |
| 2016 | 252 | +$1.72B | −$1.82B | +$4.34B | 22 | 8.7% | Brexit, US election |
| 2017 | 251 | +$3.07B | −$0.15B | +$5.49B | 2 | 0.8% | Calmest bull year on record |
| 2018 | 251 | +$2.45B | −$2.57B | +$7.95B | 39 | 15.5% | Vol-mageddon Feb + Q4 rate-hike sell-off |
| 2019 | 252 | +$2.73B | −$1.23B | +$9.99B | 18 | 7.1% | Repo crisis Sep |
| 2020 | 253 | +$3.90B | −$2.96B | +$17.44B | 31 | 12.3% | COVID crash → unprecedented stimulus |
| **2021** | 252 | **+$6.87B** | −$5.63B | **+$24.22B** | 16 | 6.3% | **Highest mean & all-time max — meme stock / squeeze era** |
| **2022** | 251 | +$1.02B | **−$7.50B** | +$9.43B | **104** | **41.4%** | **Fed hiking cycle / bear market — most negative-GEX year on record** |
| 2023 | 250 | +$2.74B | −$1.63B | +$8.55B | 23 | 9.2% | Banking stress March, normalizing |
| 2024 | 252 | +$5.07B | −$0.04B | +$9.66B | 1 | 0.4% | Calmest year by far — one negative day |
| 2025 | 250 | +$5.37B | −$1.94B | +$9.97B | 9 | 3.6% | Continuation of post-2024 vol-suppression |
| 2026 | 76 | +$3.79B | −$7.24B | +$9.89B | 8 | 10.5% | YTD through Apr 22 |

**Two extremes worth knowing**:

1. **2022 is the structural outlier** — 41.4% of days were negative-GEX vs the long-term ~9% baseline. Anyone running short-vol strategies through 2022 was operating in a regime almost 5× more vol-amplifying than typical history. Use this year for stress-testing strategies that depend on positive-GEX regimes.

2. **2024 is the structural opposite** — only 1 negative day all year (0.4%), and the year mean ($5.07B) is in the historical 75th percentile range. Use as a counter-example for over-fitting risk: any strategy back-tested mostly on 2024 data will look great but will be operating in a vol-suppression regime that may not persist.

### Notable extreme periods

**Right-tail (>$15B) clustered in early 2021** — peak post-COVID stimulus + meme stock activity:

| Date | GEX |
|---|---:|
| 2021-04-12 | +$24.22B (all-time high) |
| 2021-04-09 | +$23.00B |
| 2021-04-08 | +$23.63B |
| 2021-01-11 | +$22.47B |
| 2020-12-16 | +$17.44B |

23 days total exceed +$15B. These represent extreme institutional hedging buildup — call-overwriting and collar inventory at peak.

**Left-tail (<−$3B) clustered in 2022** — Fed rate-hike-driven repricing:

| Date | GEX |
|---|---:|
| 2022-01-20 | −$7.50B (all-time low) |
| 2026-03-27 | −$7.24B (recent extreme — second-lowest reading in dataset) |
| 2021-09-30 | −$5.63B |
| 2022-04-12 | −$4.37B |
| 2021-03-04 | −$4.26B |

11 days total fall below −$3B. 8 of those 11 occurred in 2022 alone — the heart of the rate-hike cycle.

## Open design questions (deferred)

1. **Add additional rolling-window percentile horizons.** Currently only 252-day (~1yr). Could add 60-day (`sm_*_pct_rank_60d`) for shorter-term regime, 504-day (`sm_*_pct_rank_504d`) for longer-term. Trivial to extend the build script.

2. **Add z-scores alongside percentile ranks.** Despite percentile being more robust, z-score gives finer granularity for the DIX side (which is closer to normal). E.g. `sm_dix_zscore_252d`. Useful if a downstream model wants to split on "today is 2σ above 1yr average."

3. **Add combined GEX × DIX quadrant feature.** Categorical `sm_quadrant` ∈ {`high_gex_high_dix`, `high_gex_low_dix`, `low_gex_high_dix`, `low_gex_low_dix`} based on percentile-rank median splits. Compresses the four-quadrant table into a single feature for the entry filter to split on.

4. **Add `sm_gex_plus` (= GEX + VEX) once VEX is sourced.** SqueezeMetrics has VEX (Vanna Exposure) data on the platform but it's not in the public CSV. If we ever ingest it separately, GEX+ is a sharper next-day predictor than GEX alone — eliminates the "GEX-near-zero is meaningless because IV is high" blind spot.

5. **Adopt SM's four-axis (P/V/G/D) framework.** SqueezeMetrics' sqzme platform exports per-ticker time-series of (P, V, G, D) tanh-normalized to [−1, +1]. Worth replicating with our market data once we have a reason to do per-ticker regime classification.

6. **Finer-grained DIX bands.** SM's papers note that DIX < 0.35 for extended periods coincides with topping/pre-correction phases. Adding a 4th band `extreme_low` (<0.35) could surface that regime distinctly. Currently subsumed under `low`.

## Regenerating

**Manual refresh process** (the user owns the cadence — no automated scheduler):

1. **Download** the latest CSV from SqueezeMetrics to a temp location (NOT in `_shared/` — keep `_shared/` clean of intermediates):
   ```
   https://squeezemetrics.com/monitor/static/DIX.csv
   ```
   Use a browser, `curl`, or whatever tool you prefer. The file updates daily after market close.

2. **Rebuild** this datelist file by re-running the inline transform documented in **Build process** above, pointing at the temp CSV. Stage 1 reads the temp file and renames columns (`price`->`sm_price`, `dix`->`sm_dix`, `gex`->`sm_gex`); stage 2 derives the 4 features (`sm_dix_pct_rank_252d`, `sm_gex_pct_rank_252d`, `sm_gex_sign`, `sm_dix_band`). Atomic write back to `entry_filter_dates_sm.default.csv`.

3. **Delete** the temp CSV after the build succeeds. `_shared/` should only contain the active datelist file, not intermediates.

4. **Verify** the date range advanced and the row count grew by approximately the number of trading days since the last refresh. Spot-check the warmup behavior: the first 251 rows should still have `NULL` for both percentile-rank columns; the `sm_gex_sign` and `sm_dix_band` columns should be populated for every row.

The build script lives inline in this notes file's Build process section above (copy-paste from there). A future skill (e.g. `dev-entry-filter-build-datelists`) should wrap it alongside the holidays, econ_calendar, OPEX, and earnings builds. Note: that future skill should *not* automate the SM download — it should trust whatever `DIX-3.csv` the user has placed in `_shared/`.

**SqueezeMetrics website**: https://squeezemetrics.com — has the DIX dashboard, the white papers (Gamma Exposure Dec 2017, Short Is Long Mar 2018, The Implied Order Book Jul 2020), and product details for the sqzme platform if you want per-ticker DIX/GEX or the four-axis P/V/G/D data.

**Excel warning**: opening this CSV in Excel and saving it back can reformat dates from ISO YYYY-MM-DD to M/D/YY and may convert large GEX values to scientific notation. Inspect via text editor or pandas; do not save from Excel.

## File format

- Encoding: UTF-8, no BOM (pure ASCII content).
- Line endings: LF.
- Numeric values written without scientific notation (raw decimal — e.g. `1897312571.486` not `1.897312571486e+09`).
- Percentile-rank columns rounded to 2 decimals.
- Excel-clean: opens directly without import-wizard prompts (large GEX values display fine; just don't save back from Excel).
