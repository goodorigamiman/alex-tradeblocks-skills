# SqueezeMetrics — Learning Notes

Compact reference extracted from four SqueezeMetrics sources:
1. **Gamma Exposure** white paper (Dec 2017) — GEX mechanics.
2. **Short Is Long** paper (Mar 2018) — DIX derivation and predictive evidence.
3. **The Implied Order Book: GEX Ed.** (Jul 2020) — extends to VEX and GEX+; crash mechanics.
4. **sqzme Documentation** — the four-axis (P / V / G / D) per-ticker framework and export schema.

Covers the tradable signals, their mechanics, predictive relationships, assumptions, and how to use the attached `DIX-3.csv` in analysis.

---

## 1 · Dataset inventory

**`DIX-3.csv`** — 3,764 rows, daily, covering **2011-05-02 → 2026-04-20**. Columns: `date, price, dix, gex`.

| Column | Range observed | Notes |
|---|---|---|
| `price` | S&P 500 daily close | Reference level, not SPX spot used for GEX calc |
| `dix` | 0.3306 – 0.5516 (mean 0.4362, median 0.4333) | Dark Index; dollar-weighted fraction |
| `gex` | −$7.5B to +$24.2B (mean +$3.0B) | SPX Gamma Exposure in dollars |
| negative-GEX days | 346 / 3,764 ≈ 9.2% | Regime flag — volatility-amplifying state is roughly 1 in 11 days |

---

## 2 · GEX (Gamma Exposure) — what it is

**Definition:** dollar-denominated aggregate of `Γ · OI · 100` across every SPX option strike and expiry, signed so that calls contribute positive gamma and puts contribute negative gamma. Quantifies the hedging burden on SPX option dealers.

**Core four assumptions driving the calc:**
1. All traded options are facilitated by delta-hedging dealers.
2. Calls are sold by investors, bought by market-makers (call overwriting / collars dominate).
3. Puts are bought by investors, sold by market-makers (protective puts).
4. Market-makers hedge to the option delta (simplification of real-world hedging bands).

**Hedging mechanics that make GEX predictive:**
- Dealer is long call gamma & short put gamma (from assumptions 2 & 3).
- On net long gamma: dealer sells into rallies, buys into dips → **dampens volatility**.
- On net short gamma: dealer buys into rallies, sells into dips → **amplifies volatility**.

---

## 3 · GEX — predictive relationships

**Key empirical findings (2004-present, white paper):**

| GEX state | Expected next-day SPX behavior | 1-day σ of SPX returns (from paper) |
|---|---|---|
| **Positive & high** (>Q3) | Tight range, mean-reverting | **0.55%** |
| Positive & moderate (Q2-Q3) | Normal range | 0.85% |
| Near zero | Unhedged, "natural" market | — |
| **Negative** | Volatility expansion, trend-following | Exponentially larger |

**Comparison to VIX:**
- VIX correlation to next 30d realized vol = 0.75; correlation to **prior** 30d realized vol = 0.85 → VIX is more a backward indicator than forward.
- VIX loses discrimination at its lower readings (Q1 σ=0.51% vs Q2 σ=0.66% — barely different).
- High-GEX Q3-Q4 separation (0.55% vs 0.85%) is cleaner than VIX's low quartiles.

**Rule of thumb for analysis:**
- **GEX > median (~$2.5B)**: expect volatility compression, range-bound days, mean-reversion strategies favored.
- **GEX near zero or negative**: expect volatility expansion, trend days, gap risk higher — size down or skip vol-short entries.
- **Negative-GEX days are regime flags** — only ~9% of history, but disproportionately carry the tails.

**Cross-asset extension (note from paper):** GEX can be computed for any optionable equity; the paper notes that screening S&P 500 components for GEX near zero "yielded excess returns" — a dispersion / individual-name volatility opportunity, not just SPX.

---

## 3b · VEX and GEX+ (from The Implied Order Book)

GEX alone has a blind spot: very high implied volatility pushes option gammas toward zero, so GEX can collapse to near-zero not because dealers have balanced books but because IVs are elevated. During those periods, the real driver is **vanna** — dealer delta sensitivity to changes in IV.

**VEX (Vanna Exposure)** quantifies how many dollars of the index dealers must trade for each 1-vol-point change in IV. Like GEX, it's summed across DDOI.

**DDOI (Dealer Directional Open Interest)** — the prerequisite to measuring both GEX and VEX properly. Open interest tells you contracts exist; DDOI tells you the *direction* (dealer net long vs net short each strike × expiry × type). Derived by parsing transaction-level tape and reconciling against daily OI changes.

**Sign conventions for dealers:**

| Customer position | Dealer side | GEX impact | VEX impact (OTM) | VEX impact (ITM) |
|---|---|---|---|---|
| Short OTM put | Long put | +GEX (supply liq) | +VEX | −VEX (flips when ITM) |
| Long OTM put | Short put | −GEX (take liq) | −VEX | +VEX (flips when ITM) |
| Short OTM call | Long call | +GEX | +VEX | −VEX |
| Long OTM call | Short call | −GEX | −VEX | +VEX |

**Key asymmetry — why GEX is rarely negative:** selling an option both raises GEX and lowers IV (which further raises GEX). Buying an option lowers GEX and raises IV (which mutes the GEX hit). Result: gamma-originated liquidity supply is amplified; gamma-originated liquidity removal is tempered. GEX has been <$−200mm/pt very rarely across 2004 → present.

**Key asymmetry — VEX is capable of going deeply negative.** In late 2008 and during the 2020 COVID crash, VEX hit ≈ −$400mm/pt. The reason: common post-2008 investor positioning (sold OTM puts, sold OTM calls) sits on the `*` positions in the vanna cheat sheet, which compel dealers to *sell* the index when IVs rise. Negative VEX is what drives sustained crash regimes.

**GEX+ = GEX + VEX** — the combined implied-order-book measure. Additive because both are dollar measures of dealer hedging demand.

- GEX+ observed range: +$2B (deep liquidity supply) to −$500M (liquidity removal).
- Scatterplot vs next-day SPX return shows GEX+ is a cleaner predictor than GEX alone — the "clump of volatile days at GEX=0" largely disappears once vanna is accounted for.

**Crash mechanics — the vanna feedback loop:**
1. Customers have sold many OTM puts (common "premium collection" positioning).
2. Market dips; those puts move ITM. Vanna sign flips on the newly-ITM puts.
3. IV rises because liquidity is worsening.
4. Rising IV on ITM short-put inventory forces dealers to short more index (negative VEX).
5. Dealer selling worsens liquidity further → IV rises more → more forced dealer selling.
6. Feedback ends only when IV can't rise further (VIX blowoff), then vanna reverses and produces the mechanical bear-market-rally snapback.

**Contrast — long puts don't cause crashes.** A customer long put that goes ITM has its vanna flip to *positive* — dealers must buy when IVs rise. Protective puts thus produce sharp, self-limiting corrections, not feedback-loop crashes.

**GIV (Gamma-Implied Volatility)** — the implied volatility level that would correspond to observed GEX+ given current positioning. When GIV substantially exceeds VIX, the vol market is "offsides" — VIX is too low to price in the liquidity that would be taken if the index fell. Usable as a tail-risk alert signal.

**The "implied order book" map** — a 2D grid of (SPX price × VIX level) shaded by GEX+. The red zone is where GEX+ goes negative = where dealer hedging flips to liquidity-taking = where stops cluster. When the map "runs out" in a direction (no historical analog for the implied GEX+), it indicates regime-change territory with no data to calibrate against.

**Rules of thumb from this paper:**
- **GEX+ < 0**: avoid short-vol structures; expect trending days with tail risk.
- **GIV > VIX by a material margin**: hedging is underpriced; consider cheap OTM put protection.
- **Post-2008 investor positioning (short puts) × declining market**: crash watch. Monitor the put-buy/put-sell ratio — crashes cluster when put-selling is the norm.

---

## 3c · Rarely-stated rules from the Implied Order Book paper

- **Selling an option *always* increases GEX.** No exceptions — regardless of strike, DTE, call/put.
- **Buying an option *always* decreases GEX.** But the impact is muted by the IV-up response.
- **Moneyness flips VEX sign.** OTM and ITM positions of the same type produce opposite VEX. So a fixed-strike put has different VEX effect in different market states — track dynamically.
- **IV rises with option buying pressure, falls with selling pressure.** This is the coupling that makes GEX so one-sided.
- **"Options are the order book."** Post-2008 S&P 500 liquidity is fundamentally driven by option-dealer hedging. VIX is a proxy for that liquidity, not an independent measure of future variance.

---

## 4 · DIX (Dark Index) — what it is

**Definition:** dollar-weighted percentage of short volume in S&P 500 component stocks traded through FINRA's off-exchange venues (ATSs + internalizers, collectively called "dark pools"). Covers the full SPX component universe since 2011.

**Counter-intuitive interpretation:** higher DIX = more **buying** pressure, not selling.

**Why "short is long":**
- Dealers quote a spread with no inventory → their offers are always entered as short sales (they don't own what they're "selling").
- When an investor **buys** from a dealer, the trade prints as a short sale. When an investor **sells** to a dealer, the trade prints as long (non-short).
- Therefore dark-pool short-volume % is a proxy for investor buying pressure.
- This structure is reinforced post-2005 Reg NMS by maker-taker rebates — dealers compete aggressively to stand between the bid/ask, making them the de-facto counterparty to essentially every retail order.

**Empirical backing (2010-present, short-is-long paper):**
- Mean intraday return across 12.74M name-days: +0.003%.
- Days with dark-pool short volume 0–49%: mean intraday return **−0.059%**.
- Days with dark-pool short volume 50–100%: mean intraday return **+0.118%**.
- Nearly **linear relationship** between single-name dark-pool short-volume % and same-day open-to-close return in the 20%–60% short-vol band.

---

## 5 · DIX — predictive relationships

| DIX reading | Mean 60-market-day fwd return (paper) | Interpretation |
|---|---|---|
| Dataset mean | **+2.8%** | Baseline |
| DIX ≥ 45% (dollar-weighted) | **+5.3%** | Strong accumulation signal |

**Key behavioral observations:**
- DIX **rises into corrections** — investors accumulate S&P components at lowered valuations, visible in off-exchange buying before price recovers.
- High DIX = positive medium-term (weeks-to-months) outlook, not a day-trading signal.
- DIX is constructed dollar-weighted, so large/liquid names dominate — it's an SPX-cap-weighted sentiment gauge, not an equal-weighted one.

**Rule of thumb for analysis:**
- **DIX ≥ 0.45**: accumulation signal, bullish fwd 1–3 months. Size up SPX-long exposures; consider trimming hedges.
- **DIX ≤ 0.40**: reduced accumulation. Not automatically bearish, but the tailwind is weaker.
- **DIX < 0.35 for extended periods**: historically coincides with topping / pre-correction phases (visible in the scatter at the low end).

---

## 5b · The sqzme Four-Axis Framework (P / V / G / D)

Per-ticker evolution of the DIX/GEX work, found on the sqzme platform. Available for any covered security as a CSV export. Each axis is scaled by a rolling 1-year tanh normalization so values across time and across tickers are comparable.

| Axis | Range | Meaning |
|---|---|---|
| **P** (price-trend) | ≈ [−1, +1] | Volatility-adjusted recent price trend. +1 = nearly every past-month day closed up, normalized by realized vol. Comparable cross-asset. |
| **V** (volatility-trend) | ≈ [−1, +1] | Same units as P but tracks realized volatility itself. +V = realized vol rising (measured as 1-month avg daily move). |
| **G** (gamma-ratio) | [0, 1] | Proportion of call gamma to total gamma. 0.5 = balanced; 1.0 = all calls; 0.0 = all puts. Uses constant-vol Black-Scholes deltas (ignores skew). |
| **D** (dark-ratio) | [0, 1] | Proportion of dark-pool short sales in total dark volume over the past week. Same concept as DIX but per-ticker. Higher D = more investor buying pressure. |

**How the platform uses them:**
- k-NN forecast: given today's (P, V, G, D, IV), find the 12.5% of historical days nearest in 5D space and report the resulting forward-return distribution.
- "Best" / "Worst" combos: user-draggable scatterplots that expose which 4-axis combinations historically produced the best or worst forward returns.
- Forward-return horizons: 5-day and 21-day default.

**CSV export schema (per the documentation):**

| Column | Notes |
|---|---|
| `DATE` | YYYY-MM-DD |
| `P` / `P_NORM` | Raw and tanh-normalized price-trend |
| `V` / `V_NORM` | Raw and tanh-normalized vol-trend |
| `G` / `G_NORM` | Raw and tanh-normalized gamma-ratio |
| `D` / `D_NORM` | Raw and tanh-normalized dark-ratio |
| `IV` / `IV_NORM` | Interpolated 1-mo ATM straddle IV, annualized |
| `P_NN` | k-NN-derived 1-month price forecast (normalized) |
| `OPEN, HIGH, LOW, CLOSE` | Standard OHLC |
| `VOLUME` | Lit + dark total daily volume |
| `ADM21` | 21-day average daily move (realized vol proxy) |
| `R_21F` | 21-day forward return (%) |
| `P_21F` | 21-day forward normalized P |

Normalization: tanh over 1-year rolling → maps each raw value to [−1, +1] (or [0, 1] for G/D). Future sessions can replicate this normalization for our own dark-pool / gamma metrics without needing the sqzme platform.

**API endpoint** (mentioned but not detailed): `/latest` returns the most recent day's data for all covered securities in JSON or CSV.

**Research implications for TradeBlocks:**
- Single-name versions of DIX (our "D") and GEX (our "G") are tractable with FINRA Reg SHO data + CBOE options data. The methodology exists; the inputs are public.
- The P and V axes are computable from market data we already have (`market.daily` has close prices; realized vol is a trivial aggregate).
- A 4-axis k-NN lookup is a natural candidate for a future "regime-match" skill — find the N most similar historical days to today and report their forward-return distribution.

---

## 6 · Combined GEX × DIX reading (derived from papers, not stated)

The two signals are independent and measure different things (hedging-flow mechanics vs investor accumulation). Combined quadrants:

| | **DIX high** (accumulation) | **DIX low** (no accumulation) |
|---|---|---|
| **GEX high** (vol-damped) | Strongest constructive — buying + range-bound. | Complacency; vulnerable to regime shift if GEX inverts. |
| **GEX low / negative** (vol-amplified) | Accumulation during correction; buy-the-dip regime. | Distribution + vol expansion — avoid short-vol strategies. |

**Application to option-selling strategies (calendars, condors, diagonals):**
- Prefer high-GEX environments regardless of DIX — dealer hedging absorbs the moves short-vol structures dislike.
- Beware negative-GEX regimes especially when DIX is also low — compounded unfavorable conditions.
- DIX rising while GEX is negative can signal a contrarian entry for longer-horizon deployment.

---

## 7 · Known caveats & limits

- **DIX covers only S&P 500 components**; single-name dark-pool short-volume signal exists but requires FINRA Reg SHO data wrangling. Paper provides URLs for the raw files.
- **Lit-exchange short volume is not included** in DIX — adding it would get closer to the SEC's ~49% figure; CBOE/BATS data is free, NASDAQ/NYSE charges.
- **GEX assumes dealers hedge to option delta** — real dealers use hedging bands, so GEX is an approximation. The relationship is robust enough in aggregate that the approximation works.
- **Extreme dark-pool short readings are noisy** — >80% often reflects illiquid block shorting into customer accounts; <20% often reflects large bilateral blocks with no dealer intermediary. Use the 20–60% band where the signal is clean.
- **Short-exempt volume is ignored** in both the paper's analysis and presumably DIX — it's a small carve-out.
- **Academic backtest paper vintage**: white paper is Dec 2017, short-is-long is Mar 2018. Relationships have held through the CSV's Apr 2026 coverage but regime changes (e.g. 0DTE options dominance since 2022) could shift the GEX calc's applicability — worth re-validating on post-2022 data before using as a standalone signal.

---

## 8 · Integration ideas for TradeBlocks analysis

- **Add `dix` and `gex` as `entry_filter_data.csv` columns** — they become candidate entry-filter dimensions on par with VIX/VIX9D/term-structure. Derived columns to consider:
  - `gex_sign` (binary: 1 if gex >= 0, else 0) — cleanest regime flag given the 9.2% negative-GEX base rate.
  - `dix_band` (categorical: [<0.40, 0.40-0.45, >=0.45]) — three-regime sentiment axis.
- **Candidate filters to test:**
  - `gex >= 0` (skip negative-GEX days) — likely lifts short-vol strategy edge.
  - `gex >= 2.5e9` (top-half GEX regime) — tighter compression, favors calendars / iron condors.
  - `dix >= 0.45` (accumulation signal) — favors bullish-biased structures; may lower P/L volatility for multi-day holds.
  - **`gex × dix` quadrant filter** — the four-quadrant reading from section 6. High-GEX × high-DIX is the cleanest environment for short-vol structures.
- **Correlation sanity check:** GEX should be negatively correlated with VIX, DIX should be lightly correlated with SPX forward return. Run the correlations once ingested to verify data quality.
- **Exit-side use:** high-GEX regimes suggest tighter profit-target / stop-loss bands (smaller expected move); low-GEX suggests wider exits. Useful for exit-tuning skills.

**Advanced ideas enabled by the newer papers (would need per-trade position data or tick-level options tape):**
- **GEX+ approximation** — if we can estimate a VEX proxy from skew + IV-level changes, adding to GEX would materially sharpen the vol-regime classifier. Worth exploring whether a cheap proxy exists via OCC open-interest + CBOE IV data.
- **GIV vs VIX divergence** — when implied-gamma-vol exceeds realized VIX by a threshold, that's a contrarian tail-risk entry signal. Requires the GEX+ map.
- **Vanna crash-risk monitor** — tracking aggregate put-selling ratio (PSR) across SPX components as a leading indicator for crash-feedback conditions. Can be derived from DDOI data via FINRA tape parsing, or approximated from open-interest changes.
- **Regime-match via 4-axis k-NN** — build P, V, G, D (or analogs) from our market data and implement k-NN forecasting as a skill. Inputs available: close prices (→ P, V), daily OHLCV (→ ADM21), VIX chain (→ IV). Only G and D require external ingestion (options gamma aggregate + FINRA dark short-volume).
- **Cross-asset sanity extension** — apply per-ticker G and D to the SPY / QQQ / IWM blocks we already have market data for; use as regime context for multi-underlying strategies.

---

## 9 · Data-provenance pointers

- **FINRA Reg SHO Daily Files** (single-stock dark-pool short volume): http://regsho.finra.org/regsho-Index.html
- **FINRA Monthly Short Sale Transaction Files** (tick-level off-exchange shorts): http://www.finra.org/industry/trf/trf-regulation-sho-2018
- **CBOE free short-volume feeds** (bzx, byx, edga, edgx): https://markets.cboe.com/us/equities/market_statistics/short_sale/
- **SqueezeMetrics DIX dashboard** (as of 2018 paper): http://dix.sqzme.co

The DIX in `DIX-3.csv` is already aggregated and dollar-weighted — don't re-derive unless validating or extending the methodology.

---

## 10 · Referenced academic sources (from papers)

- Avellaneda & Lipkin 2003 — market-induced stock pinning (GEX precursor theory).
- Frey & Stremme 1997 — feedback effects from dynamic hedging.
- Pearson, Poteshman & White 2007 — pervasive option-trading impact on underlying.
- Sorescu 2000 — option-listing effect on stock prices (1973-1995).
- Bartlett & McCrary 2015 — dark-pool pricing rules & HFT liquidity provision.
- Ye 2016 — dark pool impact on price discovery.

These are the underpinning academic work if the model's validity needs defense in a future analysis.
