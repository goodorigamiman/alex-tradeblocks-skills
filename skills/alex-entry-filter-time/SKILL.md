---
name: alex-entry-filter-time
description: >
  Build intraday premium curve CSV for entry filter time analysis. For each trade, computes the
  net 4-leg position premium at every minute of the trading day (09:30-15:59) using ThetaData 1-min
  option bars. Output: wide CSV (trades x 394 columns) for downstream time-of-day entry analysis.
compatibility: Requires ThetaData terminal running on port 25503 and analytics.duckdb with trade data.
metadata:
  author: alex-tradeblocks
  version: "1.0"
---

# Entry Filter Time — Intraday Premium Curve Builder

Builds a CSV capturing how each trade's net option premium evolves minute-by-minute throughout the entry day. Answers: "what if we entered at a different time?"

For each trade, pulls 1-minute OHLC bars for all legs on the trade's open date, then computes the net position premium at each of 390 minutes (09:30-15:59 ET).

## Output

`{block_folder}/alex-tradeblocks-ref/entry_filter_time_data.csv`

| Column | Type | Description |
|---|---|---|
| `date_opened` | DATE | Trade open date |
| `ror_pct` | FLOAT | Return on risk % (`pl / margin_req * 100`) |
| `entry_premium_1lot` | FLOAT | Actual entry premium per contract |
| `margin_1lot` | FLOAT | Margin per contract |
| `prem_0930` | FLOAT | Net position premium at 09:30 ET |
| `prem_0931` | FLOAT | Net position premium at 09:31 ET |
| ... | ... | ... |
| `prem_1559` | FLOAT | Net position premium at 15:59 ET |

**390 time columns** (09:30-15:59 = 6.5 hours = 390 minutes). Total: 394 columns.

## Prerequisites

1. **ThetaData terminal** running on `http://127.0.0.1:25503` (run `/start-thetadata` to verify)
2. **analytics.duckdb** with `trades.trade_data` populated for the target block
3. Python 3 with `duckdb` package

## How to Run

### Step 1: Verify ThetaData is running

```bash
lsof -i :25503
```

If not running, start with `/start-thetadata`.

### Step 2: Run the direct builder script

```bash
cd "{block_folder}"
python3 build_entry_filter_time_direct.py
```

The script:
1. Loads all trades from `analytics.duckdb` (read-only)
2. Parses each trade's legs into (expiration, strike, right) tuples
3. Deduplicates to unique (leg, date) pairs
4. Tests API connectivity with a sample call
5. Fetches 1-min OHLC bars for each unique pair from ThetaData REST API
6. Computes net premium at each minute using forward-fill
7. Writes CSV to `alex-tradeblocks-ref/entry_filter_time_data.csv`

**Expected runtime:** ~4 minutes for 628 unique option-date pairs (0.15s rate limit between calls).

## Key Implementation Details

### ThetaData v3 API

```
GET /v3/option/history/ohlc?symbol=SPXW&expiration=YYYYMMDD&strike={raw_int}&right=C|P
    &start_date=YYYYMMDD&end_date=YYYYMMDD&interval=1m
```

- `symbol`: Use `SPXW` for all SPX options (ThetaData convention)
- `strike`: Raw integer price (e.g., 3975), NOT multiplied by 1000
- `interval`: String `"1m"`, not milliseconds
- Response: CSV with columns `timestamp,open,high,low,close,volume,vwap,...`
- Price selection: `close` if `volume > 0`, otherwise `vwap` (running VWAP carries forward)

### Leg Parsing

Trades store legs as pipe-delimited strings:
```
9 May 25 3740 P STO 19.35 | 9 May 25 3975 C STO 10.05 | 9 May 27 3740 P BTO 30.60 | 9 May 27 3975 C BTO 16.85
```

Each segment: `{qty} {month} {day} {strike} {P/C} {STO/BTO} {premium}`

Year inferred from open_date. If leg month < open month, year increments (handles Dec-Jan rollover).

### Premium Sign Convention

- `STO` (sold) = `+1` (receive premium)
- `BTO` (bought) = `-1` (pay premium)
- Net premium = `SUM(sign * price)` across all legs
- More positive = more premium collected

### Forward-Fill Strategy

Initialize `last_prices` dict from each leg's entry price. At each minute, update with bar data if available. Missing bars inherit the last known price. This ensures every minute has a value even if a specific option didn't trade in that minute.

## Adapting to Other Blocks

To adapt `build_entry_filter_time_direct.py` for a different block:

1. Update `BLOCK_DIR` and `BLOCK_ID` constants
2. Update `THETA_ROOT` if underlying uses a different root symbol (e.g., `QQQ` instead of `SPXW`)
3. Verify strike format — some underlyings may need `strike * 1000`

## Alternative: DuckDB-Cached Version

`build_entry_filter_time.py` is an alternative that reads from `market.duckdb` instead of calling the API directly. It requires intraday bars to already be cached in `market.intraday` via MCP `import_from_api`. Use the `--audit` flag to check coverage:

```bash
python3 build_entry_filter_time.py --audit    # Check which tickers need importing
python3 build_entry_filter_time.py            # Build CSV from cached bars
```

The direct version (`build_entry_filter_time_direct.py`) is recommended as it's self-contained and doesn't require pre-importing data.

## Files

| File | Location | Purpose |
|---|---|---|
| `build_entry_filter_time_direct.py` | `{block_folder}/` | Primary script — calls ThetaData API directly |
| `build_entry_filter_time.py` | `{block_folder}/` | Alternative — reads from market.duckdb cache |
| `entry_filter_time_data.csv` | `{block_folder}/alex-tradeblocks-ref/` | Output CSV |

## Related Skills

- `dev-entry-filter-time-overlay` — Overlay chart of premium evolution using the CSV built by this skill
- `dev-entry-filter-pareto` — Compare time-of-day filter against all other entry filters
