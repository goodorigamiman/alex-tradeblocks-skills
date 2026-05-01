#!/usr/bin/env python3
"""
alex-entry-filter-build-data — build entry_filter_data.csv for a block.

Reads the filter groups CSV to decide which columns to build, pulls trade +
market data via read-only DuckDB, computes per-trade 1-lot economics, populates
every filter column declared in the groups registry, and enriches with market
holiday proximity. Writes {block}/alex-tradeblocks-ref/entry_filter_data.csv
and prints a summary report.

Usage:
    python3 build_entry_filter_data.py "BLOCK_ID" [--tb-root PATH]

See SKILL.md for the full workflow.
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import os
import pathlib
import re
import shutil
import sys
from collections import defaultdict
from typing import Optional, Tuple, List, Dict

import duckdb
import pandas as pd


MIN_TRADES = 50
MIN_COVERAGE_FRAC = 0.90
MAX_NULL_FRAC = 0.20
MIN_COVERAGE_YEARS = 2.0


def default_tb_root() -> pathlib.Path:
    """
    Resolve TB root by walking up from the current working directory, looking
    for a folder that contains a TradeBlocks 3.0 layout: a `market/` directory
    (Parquet datasets) plus `analytics.duckdb` either at the root or under
    `database/`. Falls back to the cwd itself if neither ancestor nor cwd
    match — the downstream sufficiency check will then surface the mismatch
    clearly.

    This lets the skill be invoked from anywhere inside the TB project without
    a hardcoded absolute path. Users can still override with --tb-root.
    """
    cwd = pathlib.Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        has_analytics = ((candidate / "database" / "analytics.duckdb").exists()
                         or (candidate / "analytics.duckdb").exists())
        has_market = (candidate / "market").is_dir()
        if has_analytics and has_market:
            return candidate
    return cwd


# ── Path resolution ──────────────────────────────────────────────────────────

def resolve_groups_csv(
    ref_folder: pathlib.Path,
    shared_dir: pathlib.Path,
    explicit: Optional[pathlib.Path] = None,
) -> Tuple[pathlib.Path, str, Optional[str]]:
    """
    Return (path, source_tag, copied_from).

    source_tag ∈ {"explicit", "block-local", "copied-from-shared"}
    copied_from = the source path string if the shared default was just copied in
                  (only non-None when source_tag == "copied-from-shared"), else None.

    Resolution order:
      1. explicit (--groups-csv arg) — must exist; used as-is without copying.
      2. Block-local — any file matching entry_filter_groups.*.csv in ref_folder.
      3. Shared — single match in _shared/, copied into ref_folder preserving filename.

    Multiple matches in ref_folder OR shared_dir (when auto-resolving) raises a clear
    error listing candidates. The user can disambiguate by passing --groups-csv.
    """
    ref_folder.mkdir(parents=True, exist_ok=True)

    if explicit is not None:
        if not explicit.is_file():
            raise RuntimeError(f"--groups-csv file not found: {explicit}")
        return explicit.resolve(), "explicit", None

    local = sorted(ref_folder.glob("entry_filter_groups.*.csv"))
    if len(local) > 1:
        names = ", ".join(p.name for p in local)
        raise RuntimeError(
            f"Multiple filter-groups files in block ref folder: {names}. "
            f"Pass --groups-csv PATH to pick one, or delete the others."
        )
    if local:
        return local[0], "block-local", None

    shared = sorted(shared_dir.glob("entry_filter_groups.*.csv"))
    if len(shared) > 1:
        names = ", ".join(p.name for p in shared)
        raise RuntimeError(
            f"Multiple filter-groups files in {shared_dir}: {names}. "
            f"Pass --groups-csv PATH to pick one, or keep only one in _shared/."
        )
    if not shared:
        raise RuntimeError(f"No entry_filter_groups.*.csv in {shared_dir}.")
    src = shared[0]
    dst = ref_folder / src.name
    shutil.copy(src, dst)
    return dst, "copied-from-shared", str(src)


def resolve_holidays_csv(shared_dir: pathlib.Path) -> pathlib.Path:
    """User override (.csv) wins, else .default.csv."""
    override = shared_dir / "entry_filter_holidays.csv"
    if override.exists():
        return override
    default = shared_dir / "entry_filter_holidays.default.csv"
    if default.exists():
        return default
    raise RuntimeError(f"No entry_filter_holidays*.csv in {shared_dir}.")


# ── Groups CSV parsing ───────────────────────────────────────────────────────

LAG_PRIOR = "prior"
LAG_SAME_DAY = "same_day"
LAG_UNKNOWN = "unknown"


def classify_lag(notes: str) -> str:
    if not notes or pd.isna(notes):
        return LAG_UNKNOWN
    s = str(notes).lower()
    if "prior day" in s or "prior day lag" in s:
        return LAG_PRIOR
    if "same day" in s or "same-day" in s or "open-known" in s or "static" in s:
        return LAG_SAME_DAY
    if "computed ratio" in s:
        return LAG_SAME_DAY  # ratios derive from same-day opens in our conventions
    return LAG_UNKNOWN


TB_TABLE_RE = re.compile(r"^\s*([^\s(]+)(?:\s*\(\s*([^)]+)\s*\))?\s*$")


def parse_tb_table(tb_table: str) -> tuple[str, str | None]:
    """Return (schema.table, ticker_or_None). e.g. 'market.daily (VIX)' → ('market.daily', 'VIX').

    Operates on the user-facing TB Table value from the groups CSV (legacy
    schema strings: market.daily, market._context_derived, market.intraday).
    The build pipeline maps these to the 3.0 Parquet views internally.
    """
    if not tb_table or pd.isna(tb_table):
        return ("", None)
    m = TB_TABLE_RE.match(str(tb_table))
    if not m:
        return (str(tb_table).strip(), None)
    return (m.group(1).strip(), (m.group(2) or "").strip() or None)


def load_groups(path: pathlib.Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    df["TB Filter"] = df["TB Filter"].astype(str).str.upper() == "TRUE"
    df["CSV Column"] = df["CSV Column"].fillna("").astype(str).str.strip()
    df["active"] = df["TB Filter"] & (df["CSV Column"] != "")
    df["_lag"] = df["TB Notes"].apply(classify_lag)
    df[["_tb_schema", "_tb_ticker"]] = df["TB Table"].apply(lambda v: pd.Series(parse_tb_table(v)))
    return df


# ── DB access ────────────────────────────────────────────────────────────────

def _resolve_analytics_path(tb_root: pathlib.Path) -> pathlib.Path:
    """
    Return the analytics.duckdb path. Looks in two locations:
      - `database/analytics.duckdb` (canonical 3.0 prod-Docker layout, per CLAUDE.md)
      - `analytics.duckdb` at the root (dev-host MCP layout)

    When both exist (a common state on machines that run both the prod
    container and a dev host process), pick the one with the more recent
    mtime. This guarantees the script reads whichever DB the active MCP is
    writing to without requiring the user to know which is which. If only
    one exists, return it. If neither exists, raise.
    """
    candidates = [tb_root / "database" / "analytics.duckdb",
                  tb_root / "analytics.duckdb"]
    existing = [p for p in candidates if p.exists()]
    if not existing:
        raise RuntimeError(
            f"analytics.duckdb not found under {tb_root}. "
            f"Tried database/analytics.duckdb and analytics.duckdb."
        )
    if len(existing) == 1:
        return existing[0]
    # Both exist — choose the most recently modified.
    return max(existing, key=lambda p: p.stat().st_mtime)


def connect_readonly(tb_root: pathlib.Path):
    """
    Open analytics.duckdb read-only and register Parquet-backed views for
    market data. In TradeBlocks 3.0, the legacy market.duckdb is frozen and
    the canonical sources are Parquet files under market/. These view names
    mirror the MCP server's registrations so the script reads the same data
    shape as `mcp__tradeblocks__run_sql`.

    The Parquet datasets are lock-free, so multiple concurrent readers (this
    script alongside the MCP container) are safe.

    Views created:
      market_spot               1-min OHLCV bars (replaces legacy market.intraday)
      market_spot_daily         RTH daily aggregate of spot, computed on demand
      market_enriched           per-ticker indicators (RSI_14, ATR_Pct, etc.)
      market_enriched_context   cross-ticker regime data (Vol_Regime, etc.)
      market_daily              compatibility view: spot_daily LEFT JOIN enriched
                                — exposes the legacy fat-table column set
                                so existing query templates work unchanged.
    """
    analytics = _resolve_analytics_path(tb_root)
    con = duckdb.connect(str(analytics), read_only=True)

    market_root = (tb_root / "market").resolve()
    spot_glob = str(market_root / "spot" / "**" / "*.parquet").replace("'", "''")
    enr_glob = str(market_root / "enriched" / "ticker=*" / "data.parquet").replace("'", "''")
    ctx_glob = str(market_root / "enriched" / "context" / "data.parquet").replace("'", "''")

    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW market_spot AS
        SELECT * FROM read_parquet('{spot_glob}', hive_partitioning=true)
    """)

    # RTH-only daily aggregate. Mirrors the MCP server's market.spot_daily
    # definition: first(open), max(high), min(low), last(close) within RTH
    # bars, grouped by (ticker, date).
    #
    # NULLIF(price, 0) is critical: the spot Parquet is zero-filled at the
    # open bar for several index tickers (VIX, VIX9D, VIX3M) — bars at 09:30
    # land with open=0/low=0 but a real high/close. Without NULLIF, arg_min
    # picks up the zero and corrupts the daily open; min(low) returns 0 for
    # every day. With NULLIF, the aggregation skips zero values (DuckDB
    # aggregates ignore NULLs by default), and the result reflects the first
    # real bar of the session.
    #
    # Casts date to DATE because hive_partitioning emits the partition
    # column as VARCHAR when reading from a glob — DATE is required for
    # downstream joins to trades.trade_data.
    con.execute("""
        CREATE OR REPLACE TEMP VIEW market_spot_daily AS
        SELECT
            ticker,
            CAST(date AS DATE)              AS date,
            arg_min(NULLIF(open, 0), time)  AS open,
            max(NULLIF(high, 0))            AS high,
            min(NULLIF(low, 0))             AS low,
            arg_max(NULLIF(close, 0), time) AS close
        FROM market_spot
        WHERE time >= '09:30' AND time <= '15:59'
        GROUP BY ticker, CAST(date AS DATE)
        -- Exclude non-trading days (weekends, holidays) where the partition
        -- file exists but every bar is zero-filled. Without this, prior-day
        -- lag lookups (MAX(date) < trade_date) can land on a Sunday and
        -- pull a row whose OHLC are all NULL.
        HAVING count(*) FILTER (WHERE close > 0) > 0
    """)

    # The Parquet `date` column is stored as VARCHAR in the enriched datasets,
    # so we cast it to DATE on the way in for downstream join compatibility.
    #
    # Filter out weekends: the enriched dataset can contain Saturday/Sunday
    # rows (zero-filled or carried-forward indicators) that the legacy
    # market.daily table didn't surface. Without this filter, a prior-day
    # MAX(date) lookup on a Monday picks Saturday and pulls a row with NULL
    # OHLC — silently corrupting prior-day VIX/SPX/etc. lag fields.
    # DuckDB dayofweek: Sunday=0, Monday=1, …, Saturday=6.
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW market_enriched AS
        SELECT
            * EXCLUDE (date),
            CAST(date AS DATE) AS date
        FROM read_parquet('{enr_glob}', hive_partitioning=true)
        WHERE dayofweek(CAST(date AS DATE)) BETWEEN 1 AND 5
    """)

    # Same VARCHAR-date issue and weekend filter as market_enriched.
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW market_enriched_context AS
        SELECT
            * EXCLUDE (date),
            CAST(date AS DATE) AS date
        FROM read_parquet('{ctx_glob}')
        WHERE dayofweek(CAST(date AS DATE)) BETWEEN 1 AND 5
    """)

    # Legacy-compat view: legacy market.daily was a fat denormalized table
    # carrying both OHLCV and per-ticker indicators. 3.0 splits these across
    # spot_daily + enriched, and the two sources can have different date
    # coverage windows (e.g., spot_daily starts in 2024-09 from ThetaData
    # while enriched was backfilled from older sources to 2022). A FULL
    # OUTER JOIN preserves every (ticker, date) row from either side so the
    # legacy query templates see the union of available data — exactly what
    # they would have seen against the legacy fat table.
    #
    # COALESCE on (ticker, date) so every row has populated key columns
    # regardless of which side the row came from.
    con.execute("""
        CREATE OR REPLACE TEMP VIEW market_daily AS
        SELECT
            COALESCE(s.ticker, e.ticker)                  AS ticker,
            CAST(COALESCE(s.date, e.date) AS DATE)        AS date,
            s.open, s.high, s.low, s.close,
            e.Prior_Close, e.Gap_Pct, e.ATR_Pct, e.RSI_14,
            e.Price_vs_EMA21_Pct, e.Price_vs_SMA50_Pct,
            e.Realized_Vol_5D, e.Realized_Vol_20D,
            e.Return_5D, e.Return_20D,
            e.Intraday_Range_Pct, e.Intraday_Return_Pct,
            e.Close_Position_In_Range, e.Gap_Filled,
            e.Consecutive_Days, e.Prev_Return_Pct, e.Prior_Range_vs_ATR,
            e.High_Time, e.Low_Time, e.High_Before_Low, e.Reversal_Type,
            e.Opening_Drive_Strength, e.Intraday_Realized_Vol,
            e.Day_of_Week, e.Month, e.Is_Opex, e.ivr, e.ivp
        FROM market_spot_daily s
        FULL OUTER JOIN market_enriched e
          ON e.ticker = s.ticker AND e.date = s.date
    """)

    return con


def detect_underlying(con, block_id: str) -> Optional[str]:
    r = con.execute(
        "SELECT MODE() WITHIN GROUP (ORDER BY ticker) FROM trades.trade_data WHERE block_id = ?",
        [block_id],
    ).fetchone()
    return (r[0] or "").strip() if r and r[0] else None


def run_sufficiency_checks(con, block_id: str, underlying: str) -> dict:
    checks = {"underlying": underlying}
    r = con.execute(
        "SELECT COUNT(*)::INT, COUNT(CASE WHEN margin_req>0 THEN 1 END)::INT "
        "FROM trades.trade_data WHERE block_id = ?",
        [block_id],
    ).fetchone()
    total, with_margin = r[0], r[1]
    checks["trades"] = total
    checks["has_margin"] = with_margin
    checks["trade_count_ok"] = total >= MIN_TRADES and with_margin == total

    # Coverage — one big left join, one pass
    r = con.execute(f"""
        SELECT
            SUM(CASE WHEN vix.close IS NOT NULL THEN 1 ELSE 0 END)::INT,
            SUM(CASE WHEN spx.Gap_Pct IS NOT NULL THEN 1 ELSE 0 END)::INT,
            SUM(CASE WHEN u.Gap_Pct IS NOT NULL THEN 1 ELSE 0 END)::INT,
            SUM(CASE WHEN v9.open IS NOT NULL THEN 1 ELSE 0 END)::INT,
            SUM(CASE WHEN v3.open IS NOT NULL THEN 1 ELSE 0 END)::INT,
            SUM(CASE WHEN cd.Vol_Regime IS NOT NULL THEN 1 ELSE 0 END)::INT,
            COUNT(*)::INT
        FROM trades.trade_data t
        LEFT JOIN market_daily vix ON vix.ticker='VIX' AND CAST(vix.date AS DATE)=CAST(t.date_opened AS DATE)
        LEFT JOIN market_daily spx ON spx.ticker='SPX' AND CAST(spx.date AS DATE)=CAST(t.date_opened AS DATE)
        LEFT JOIN market_daily u ON u.ticker='{underlying}' AND CAST(u.date AS DATE)=CAST(t.date_opened AS DATE)
        LEFT JOIN market_daily v9 ON v9.ticker='VIX9D' AND CAST(v9.date AS DATE)=CAST(t.date_opened AS DATE)
        LEFT JOIN market_daily v3 ON v3.ticker='VIX3M' AND CAST(v3.date AS DATE)=CAST(t.date_opened AS DATE)
        LEFT JOIN market_enriched_context cd ON CAST(cd.date AS DATE) = (
            SELECT MAX(CAST(c2.date AS DATE)) FROM market_enriched_context c2
            WHERE CAST(c2.date AS DATE) < CAST(t.date_opened AS DATE))
        WHERE t.block_id = ?
    """, [block_id]).fetchone()
    vix_n, spx_n, u_n, v9_n, v3_n, ctx_n, n = r
    cov = lambda x: (x / n) if n else 0.0
    checks["cov_vix"] = cov(vix_n)
    checks["cov_spx"] = cov(spx_n)
    checks["cov_underlying"] = cov(u_n)
    checks["cov_vix9d"] = cov(v9_n)
    checks["cov_vix3m"] = cov(v3_n)
    checks["cov_context"] = cov(ctx_n)

    r = con.execute(
        "SELECT COUNT(*)::INT, COUNT(CASE WHEN legs LIKE '%STO%' AND legs LIKE '%BTO%' THEN 1 END)::INT "
        "FROM trades.trade_data WHERE block_id = ?",
        [block_id],
    ).fetchone()
    checks["slr_parseable"] = (r[1] / r[0]) if r[0] else 0.0
    return checks


# ── Frame builders ───────────────────────────────────────────────────────────

def build_base_frame(con, block_id: str) -> pd.DataFrame:
    """8 locked base columns + the computed _slr_computed for later aliasing."""
    return con.execute("""
        WITH t AS (
            SELECT
                CAST(date_opened AS DATE) AS date_opened,
                time_opened,
                pl, margin_req, premium, num_contracts, legs,
                ROW_NUMBER() OVER (ORDER BY date_opened, time_opened, rowid) AS trade_index
            FROM trades.trade_data
            WHERE block_id = ?
        )
        SELECT
            trade_index,
            date_opened,
            time_opened,
            CAST(margin_req AS DOUBLE) / NULLIF(num_contracts, 0) AS margin_per_contract,
            -- Per-lot premium in price units (notional/100). Sign: (-) debit, (+) credit.
            -- Structure-agnostic unnest: splits legs on '|', parses each leg's qty and
            -- price, sums (qty × price) with STO positive (credit received) and BTO
            -- negative (debit paid), divides by num_contracts.
            -- Note: num_contracts in OO is actually # of LOTS for ratio spreads
            -- (e.g. SlimP 10/9 → 1 lot = 38 individual contracts). The column name
            -- premium_per_contract is historic — it's really premium_per_lot.
            -- Does NOT use OO's Premium column (which the MCP preserves as $ per lot);
            -- computed from legs so the value is independent of CSV rounding/fees.
            -- For 2022-05-16 SlimP: verified -273.40 per lot (matches OO Premium/100).
            CAST(list_sum(
              list_transform(
                string_split(legs, '|'),
                leg -> CASE
                  WHEN regexp_matches(trim(leg), ' STO ')
                  THEN CAST(regexp_extract(trim(leg), '^(\d+)', 1) AS DOUBLE) *
                       CAST(regexp_extract(trim(leg), '([0-9.]+)$', 1) AS DOUBLE)
                  WHEN regexp_matches(trim(leg), ' BTO ')
                  THEN -1 * CAST(regexp_extract(trim(leg), '^(\d+)', 1) AS DOUBLE) *
                            CAST(regexp_extract(trim(leg), '([0-9.]+)$', 1) AS DOUBLE)
                  ELSE 0 END
              )
            ) AS DOUBLE) / NULLIF(num_contracts, 0) AS premium_per_contract,
            CAST(pl AS DOUBLE) / NULLIF(num_contracts, 0) AS pl_per_contract,
            CAST(pl AS DOUBLE) / NULLIF(margin_req, 0) * 100 AS rom_pct,
            -- PCR (Premium Capture Rate): what % of at-risk premium the trade captured.
            -- User spec: pcr_pct = (1-lot P/L $) / abs(premium_per_lot_priceunits × 100) × 100
            -- where premium_per_lot_priceunits is the legs-derived signed per-lot premium.
            -- Uses abs() in the denominator so credit (+) and debit (-) trades both produce
            -- denominators that are positive — PCR sign then tracks P/L sign directly
            -- (positive PCR = winning trade, regardless of debit vs credit entry).
            -- Algebraic simplification (num_contracts and ×100 both cancel):
            --   pcr_pct = pl / abs(sum(qty × signed_price across all legs))
            -- Computed from legs, not OO's Premium column — independent of CSV rounding.
            -- For 2022-05-16 SlimP: 9483.52 / abs(-4374.40) = 2.168% (winner, debit entry).
            CAST(pl AS DOUBLE) / NULLIF(ABS(
              list_sum(list_transform(string_split(legs, '|'),
                leg -> CASE
                  WHEN regexp_matches(trim(leg), ' STO ')
                  THEN CAST(regexp_extract(trim(leg), '^(\d+)', 1) AS DOUBLE) *
                       CAST(regexp_extract(trim(leg), '([0-9.]+)$', 1) AS DOUBLE)
                  WHEN regexp_matches(trim(leg), ' BTO ')
                  THEN -1 * CAST(regexp_extract(trim(leg), '^(\d+)', 1) AS DOUBLE) *
                            CAST(regexp_extract(trim(leg), '([0-9.]+)$', 1) AS DOUBLE)
                  ELSE 0 END
              ))
            ), 0) AS pcr_pct,
            -- Internal, renamed later if SLR is requested in groups CSV.
            -- Structure-agnostic: splits the legs string on '|', parses each leg's
            -- qty and price, sums (qty * price) separately for STO and BTO legs,
            -- then takes the ratio. Works for any combination of 1-8+ legs with any
            -- quantities. Verified against OO export for 4-leg DC equal qty (0.7619),
            -- 4-leg SlimP 10/9 ratio (0.6778), 2-leg verticals, 6-leg asymmetric,
            -- 8-leg double calendar, and 1-leg naked structures.
            CAST(list_sum(
              list_transform(
                string_split(legs, '|'),
                leg -> CASE
                  WHEN regexp_matches(trim(leg), ' STO ')
                  THEN CAST(regexp_extract(trim(leg), '^(\d+)', 1) AS DOUBLE) *
                       CAST(regexp_extract(trim(leg), '([0-9.]+)$', 1) AS DOUBLE)
                  ELSE 0 END
              )
            ) AS DOUBLE) / NULLIF(
            CAST(list_sum(
              list_transform(
                string_split(legs, '|'),
                leg -> CASE
                  WHEN regexp_matches(trim(leg), ' BTO ')
                  THEN CAST(regexp_extract(trim(leg), '^(\d+)', 1) AS DOUBLE) *
                       CAST(regexp_extract(trim(leg), '([0-9.]+)$', 1) AS DOUBLE)
                  ELSE 0 END
              )
            ) AS DOUBLE), 0) AS _slr_computed
        FROM t
        ORDER BY trade_index
    """, [block_id]).df()


# ── Intraday + OO CSV fallback for VIX_at_Entry / VIX_at_Close / Intra_Move ──

def build_intraday_columns(con, block_id: str, underlying: str) -> pd.DataFrame:
    """
    Pull VIX_at_Entry, VIX_at_Close, and Intra_Move_Pct from market_spot
    where coverage exists. VIX-at-entry/close uses the VIX 15-min bar's `open`
    (= price at bar start, cleanest "at this timestamp" reading, no lookahead).
    Intra_Move_Pct = (underlying bar open at entry − underlying daily open) /
    underlying daily open × 100 — percentage move from today's open to entry.

    Also returns `underlying_daily_open_tb` so the OO CSV fallback layer can
    convert OO's `Movement` (in points) to percentage using the same denominator.

    time_opened / time_closed in trades.trade_data are 'HH:MM:SS';
    market_spot.time is 'HH:MM' — substring(1,5) strips seconds.

    Returns DataFrame with columns:
        trade_index, VIX_at_Entry_tb, VIX_at_Close_tb, Intra_Move_Pct_tb,
        underlying_daily_open_tb
    NULLs mean no bar matched — the OO CSV fallback will try next.
    """
    return con.execute(f"""
        WITH t AS (
            SELECT
                ROW_NUMBER() OVER (ORDER BY date_opened, time_opened, rowid) AS trade_index,
                CAST(date_opened AS DATE) AS date_opened,
                SUBSTRING(time_opened, 1, 5) AS time_opened_bar,
                CAST(date_closed AS DATE) AS date_closed,
                SUBSTRING(time_closed, 1, 5) AS time_closed_bar
            FROM trades.trade_data
            WHERE block_id = ?
        )
        SELECT
            t.trade_index,
            vix_entry.open AS VIX_at_Entry_tb,
            vix_close.open AS VIX_at_Close_tb,
            -- Use u_entry.open (= underlying price AT the bar's timestamp, e.g. 15:45:00)
            -- rather than .close (which is price at bar end, ~15:59:59). Matches OO's
            -- Opening Price convention. Converted to percentage of today's open.
            -- Verified 2022-05-16 SPX: u_entry.open=4007.08, u_day.open=4013.02
            -- → Intra_Move = -5.94 pts / 4013.02 × 100 = -0.148%.
            CASE
                WHEN u_day.open IS NULL OR u_day.open = 0 THEN NULL
                ELSE (u_entry.open - u_day.open) / u_day.open * 100
            END AS Intra_Move_Pct_tb,
            u_day.open AS underlying_daily_open_tb,
            u_day.Prior_Close AS underlying_prior_close_tb
        FROM t
        LEFT JOIN market_spot vix_entry
          ON vix_entry.ticker = 'VIX'
         AND vix_entry.date = t.date_opened
         AND vix_entry.time = t.time_opened_bar
        LEFT JOIN market_spot vix_close
          ON vix_close.ticker = 'VIX'
         AND vix_close.date = t.date_closed
         AND vix_close.time = t.time_closed_bar
        LEFT JOIN market_spot u_entry
          ON u_entry.ticker = '{underlying}'
         AND u_entry.date = t.date_opened
         AND u_entry.time = t.time_opened_bar
        LEFT JOIN market_daily u_day
          ON u_day.ticker = '{underlying}'
         AND u_day.date = t.date_opened
        ORDER BY t.trade_index
    """, [block_id]).df()


def find_oo_trade_log(block_folder: pathlib.Path) -> Optional[pathlib.Path]:
    """
    Locate the OO trade-log CSV in the block folder. Skips the
    alex-tradeblocks-ref/ subfolder (our own outputs) and returns the first
    CSV whose header has 'Date Opened' + 'Time Opened' + 'Legs' — the minimum
    schema of an OO trade-log export.
    """
    for p in sorted(block_folder.glob("*.csv")):
        if "alex-tradeblocks-ref" in p.parts:
            continue
        try:
            header = pd.read_csv(p, nrows=0).columns.tolist()
        except Exception:
            continue
        if {"Date Opened", "Time Opened", "Legs"}.issubset(set(header)):
            return p
    return None


def build_oo_fallback(block_folder: pathlib.Path) -> Tuple[pd.DataFrame, Dict[str, object]]:
    """
    Read the OO trade-log CSV to provide fallback values for trades where
    market_spot had no bar. Returns (df, meta).

    The returned df is keyed on normalized (date_opened, time_opened) strings
    ('YYYY-MM-DD' and 'HH:MM:SS') and carries:
        VIX_at_Entry_oo, VIX_at_Close_oo, Intra_Move_oo
    NaN for any column the CSV doesn't carry — OO's default export does NOT
    include VIX, so those will almost always be NaN. 'Movement' IS exported,
    so Intra_Move_oo is typically populated for every trade.

    meta carries:
        csv_path      — the discovered path (or None if no CSV found)
        vix_entry_col — column name matched for entry-VIX (or None)
        vix_close_col — column name matched for close-VIX (or None)
        movement_col  — True if 'Movement' column exists
    """
    meta: Dict[str, object] = {
        "csv_path": None, "vix_entry_col": None,
        "vix_close_col": None, "movement_col": False, "gap_col": False,
    }
    log_path = find_oo_trade_log(block_folder)
    if log_path is None:
        return pd.DataFrame(), meta
    meta["csv_path"] = log_path

    raw = pd.read_csv(log_path)

    # Normalized match keys — strings to dodge timezone / type drift.
    date_key = pd.to_datetime(raw["Date Opened"], errors="coerce").dt.strftime("%Y-%m-%d")
    time_key = raw["Time Opened"].astype(str).str.slice(0, 8)

    # VIX column detection — check likely custom-column names.
    vix_entry_candidates = ["VIX at Entry", "VIX Entry", "Opening VIX", "VIX"]
    vix_close_candidates = ["VIX at Close", "VIX Close", "Closing VIX", "VIX at Exit"]
    vix_entry_col = next((c for c in vix_entry_candidates if c in raw.columns), None)
    vix_close_col = next((c for c in vix_close_candidates if c in raw.columns), None)
    if vix_entry_col == vix_close_col and vix_entry_col is not None:
        # The bare column 'VIX' would map to both — ambiguous. Treat as entry only.
        vix_close_col = None
    meta["vix_entry_col"] = vix_entry_col
    meta["vix_close_col"] = vix_close_col

    out = pd.DataFrame({
        "_date_opened_oo": date_key,
        "_time_opened_oo": time_key,
    })
    out["VIX_at_Entry_oo"] = (pd.to_numeric(raw[vix_entry_col], errors="coerce")
                              if vix_entry_col else pd.Series([pd.NA] * len(raw)))
    out["VIX_at_Close_oo"] = (pd.to_numeric(raw[vix_close_col], errors="coerce")
                              if vix_close_col else pd.Series([pd.NA] * len(raw)))
    # OO Movement is in POINTS — kept as-is here; the coalesce layer converts
    # to percentage using the underlying's daily open so the scale matches
    # the intraday-derived Intra_Move_Pct.
    if "Movement" in raw.columns:
        out["Intra_Move_Points_oo"] = pd.to_numeric(raw["Movement"], errors="coerce")
        meta["movement_col"] = True
    else:
        out["Intra_Move_Points_oo"] = pd.Series([pd.NA] * len(raw))

    # OO Gap is in POINTS (today's open − prior close). Coalesce layer converts
    # to percentage using underlying PRIOR CLOSE (standard Gap% convention).
    # Fallback path for the groups-CSV-resolved Gap_Pct when market_daily
    # coverage for the block's underlying is absent pre-some-date.
    if "Gap" in raw.columns:
        out["Gap_Points_oo"] = pd.to_numeric(raw["Gap"], errors="coerce")
        meta["gap_col"] = True
    else:
        out["Gap_Points_oo"] = pd.Series([pd.NA] * len(raw))
        meta["gap_col"] = False

    return out, meta


def coalesce_trade_context(
    df: pd.DataFrame,
    intraday: pd.DataFrame,
    oo: pd.DataFrame,
) -> Tuple[pd.DataFrame, Dict[str, Dict[str, int]]]:
    """
    Merge intraday (primary) + OO CSV (fallback) into df. Adds these columns:
        VIX_at_Entry, VIX_at_Close, Intra_Move_Pct
    OO CSV's `Movement` column is in points; we convert to percentage using
    the underlying's daily open (from intraday lookup) so the scale matches
    the intraday-derived values.
    Drops intermediate _tb / _oo / _date_*_oo / _time_*_oo / underlying_daily_open_tb.

    Returns (df, coverage). coverage is a dict keyed by output column name;
    each value is {'tb_intraday': N, 'oo_csv': N, 'missing': N}.
    """
    if not intraday.empty:
        df = df.merge(intraday, on="trade_index", how="left")
    else:
        for c in ("VIX_at_Entry_tb", "VIX_at_Close_tb",
                  "Intra_Move_Pct_tb", "underlying_daily_open_tb",
                  "underlying_prior_close_tb"):
            df[c] = pd.NA

    if not oo.empty:
        df["_date_opened_oo"] = df["date_opened"].astype(str)
        df["_time_opened_oo"] = df["time_opened"].astype(str).str.slice(0, 8)
        df = df.merge(oo, on=["_date_opened_oo", "_time_opened_oo"], how="left")
        df = df.drop(columns=["_date_opened_oo", "_time_opened_oo"], errors="ignore")
    else:
        for c in ("VIX_at_Entry_oo", "VIX_at_Close_oo",
                  "Intra_Move_Points_oo", "Gap_Points_oo"):
            df[c] = pd.NA

    # Convert OO points to percentages using appropriate denominators:
    #   Intra_Move_Pct = Movement / today_open × 100
    #   Gap_Pct        = Gap      / prior_close × 100  (standard Gap% convention)
    # Guard against div-by-zero explicitly rather than relying on deprecated
    # `use_inf_as_na` — replace inf with NaN after the division.
    import numpy as np
    u_open = pd.to_numeric(df.get("underlying_daily_open_tb", pd.Series([pd.NA]*len(df))), errors="coerce")
    u_prior = pd.to_numeric(df.get("underlying_prior_close_tb", pd.Series([pd.NA]*len(df))), errors="coerce")
    oo_move_pts = pd.to_numeric(df.get("Intra_Move_Points_oo", pd.Series([pd.NA]*len(df))), errors="coerce")
    oo_gap_pts = pd.to_numeric(df.get("Gap_Points_oo", pd.Series([pd.NA]*len(df))), errors="coerce")
    safe_open = u_open.where(u_open != 0, other=np.nan)
    safe_prior = u_prior.where(u_prior != 0, other=np.nan)
    df["Intra_Move_Pct_oo"] = (oo_move_pts / safe_open * 100).replace([np.inf, -np.inf], np.nan)
    df["Gap_Pct_oo"] = (oo_gap_pts / safe_prior * 100).replace([np.inf, -np.inf], np.nan)

    coverage: Dict[str, Dict[str, int]] = {}
    for out_col, tb_col, oo_col in [
        ("VIX_at_Entry",   "VIX_at_Entry_tb",   "VIX_at_Entry_oo"),
        ("VIX_at_Close",   "VIX_at_Close_tb",   "VIX_at_Close_oo"),
        ("Intra_Move_Pct", "Intra_Move_Pct_tb", "Intra_Move_Pct_oo"),
    ]:
        tb = pd.to_numeric(df[tb_col], errors="coerce") if tb_col in df.columns else pd.Series([pd.NA] * len(df))
        oo_series = pd.to_numeric(df[oo_col], errors="coerce") if oo_col in df.columns else pd.Series([pd.NA] * len(df))
        df[out_col] = tb.fillna(oo_series)
        n_tb = int(tb.notna().sum())
        n_oo = int((tb.isna() & oo_series.notna()).sum())
        n_missing = int((tb.isna() & oo_series.isna()).sum())
        coverage[out_col] = {"tb_intraday": n_tb, "oo_csv": n_oo, "missing": n_missing}

    # Gap_Pct gets a different treatment: the groups-CSV filter resolver is the
    # PRIMARY path (pulls market_daily enrichment's Gap_Pct). This fallback only
    # fires if that path failed. Keep Gap_Pct_oo in the dataframe for main() to
    # apply as a post-merge fill after filter_frame is merged in.

    df = df.drop(columns=["VIX_at_Entry_tb", "VIX_at_Close_tb",
                          "Intra_Move_Pct_tb", "underlying_daily_open_tb",
                          "underlying_prior_close_tb",
                          "VIX_at_Entry_oo", "VIX_at_Close_oo",
                          "Intra_Move_Points_oo", "Intra_Move_Pct_oo",
                          "Gap_Points_oo"],
                 errors="ignore")
    # NOTE: Gap_Pct_oo intentionally NOT dropped — main() uses it for post-fill.
    return df, coverage


def summarize_pcr(df: pd.DataFrame) -> str:
    """Report summary stats on pcr_pct so the user can eyeball the formula."""
    pcr = df["pcr_pct"].dropna()
    if pcr.empty:
        return "pcr_pct is all-null (premium or num_contracts missing)"
    return (
        f"pcr_pct mean={pcr.mean():.2f}%  median={pcr.median():.2f}%  "
        f"range=[{pcr.min():.2f}%, {pcr.max():.2f}%]"
    )


# Map CSV Column → actual market_daily DB column for ticker-prefixed cases
TICKER_PREFIX_MAP = {
    "Open": "open",
    "Close": "close",
    "High": "high",
    "Low": "low",
    "IVR": "ivr",
    "IVP": "ivp",
    "Gap_Pct": "Gap_Pct",
    "Trade": "open",  # VIX_Trade = VIX open on trade day (groups CSV convention)
}

# For ratio resolution where TB Field uses old-SQL names — map to current CSV Column
RATIO_ALIASES = {
    "VIX_Open": "VIX_Trade",  # old SQL had VIX_Open; groups CSV uses VIX_Trade
}

_MARKET_DAILY_COLS_CACHE: Optional[set] = None


def market_daily_columns(con) -> set:
    """Cached set of actual column names in market_daily."""
    global _MARKET_DAILY_COLS_CACHE
    if _MARKET_DAILY_COLS_CACHE is None:
        r = con.execute("SELECT * FROM market_daily LIMIT 1").df()
        _MARKET_DAILY_COLS_CACHE = set(r.columns)
    return _MARKET_DAILY_COLS_CACHE


def resolve_db_field(con, csv_col: str, tb_field: str, ticker: Optional[str]) -> Optional[str]:
    """Return the actual market_daily column to query for csv_col, or None if unresolvable."""
    cols = market_daily_columns(con)
    # If CSV Column directly matches a DB column, use it (handles SPX/QQQ direct fields)
    if csv_col in cols:
        return csv_col
    # Try TB Field as a direct column name
    if tb_field and tb_field in cols:
        return tb_field
    # Ticker-prefix stripping: e.g., VIX_Close → close, VIX9D_Open → open
    if ticker:
        prefix = f"{ticker}_"
        if csv_col.startswith(prefix):
            suffix = csv_col[len(prefix):]
            if suffix in TICKER_PREFIX_MAP:
                candidate = TICKER_PREFIX_MAP[suffix]
                if candidate in cols:
                    return candidate
            # Sometimes CSV Column after prefix stripping matches a DB column directly
            if suffix in cols:
                return suffix
    return None


# Fetch fields from market_daily for a given ticker and lag type
def fetch_ticker_fields(con, block_id: str, ticker: str,
                        entries: List[Tuple[str, str]],
                        lag: str) -> Tuple[pd.DataFrame, Dict[str, str]]:
    """
    entries: list of (csv_col_out, db_col_in).
    Returns (DataFrame with date_opened + renamed csv_cols, {unresolved csv_col: reason}).
    """
    if not entries:
        return pd.DataFrame(), {}
    # Build SELECT list with aliasing
    select_parts = [f'm."{db}" AS "{csv}"' for csv, db in entries]
    select_sql = ", ".join(select_parts)
    if lag == LAG_SAME_DAY:
        sql = f"""
            SELECT CAST(t.date_opened AS DATE) AS date_opened, {select_sql}
            FROM trades.trade_data t
            LEFT JOIN market_daily m ON m.ticker = ?
              AND CAST(m.date AS DATE) = CAST(t.date_opened AS DATE)
            WHERE t.block_id = ?
        """
        params = [ticker, block_id]
    else:
        sql = f"""
            SELECT CAST(t.date_opened AS DATE) AS date_opened, {select_sql}
            FROM trades.trade_data t
            LEFT JOIN market_daily m ON m.ticker = ?
              AND CAST(m.date AS DATE) = (
                SELECT MAX(CAST(m2.date AS DATE)) FROM market_daily m2
                WHERE m2.ticker = ? AND CAST(m2.date AS DATE) < CAST(t.date_opened AS DATE))
            WHERE t.block_id = ?
        """
        params = [ticker, ticker, block_id]
    return con.execute(sql, params).df(), {}


def fetch_context_fields(con, block_id: str, fields: list[str]) -> pd.DataFrame:
    if not fields:
        return pd.DataFrame()
    field_sql = ", ".join(f"c.{f}" for f in fields)
    sql = f"""
        SELECT CAST(t.date_opened AS DATE) AS date_opened, {field_sql}
        FROM trades.trade_data t
        LEFT JOIN market_enriched_context c ON CAST(c.date AS DATE) = (
            SELECT MAX(CAST(c2.date AS DATE)) FROM market_enriched_context c2
            WHERE CAST(c2.date AS DATE) < CAST(t.date_opened AS DATE))
        WHERE t.block_id = ?
    """
    return con.execute(sql, [block_id]).df()


# ── Orchestration ────────────────────────────────────────────────────────────

# How a TB Table string maps to (schema, ticker_resolver)
def resolve_ticker(tb_ticker: str | None, underlying: str) -> str | None:
    if not tb_ticker:
        return None
    t = tb_ticker.strip().lower()
    if t == "underlying":
        return underlying
    if "/" in t:  # e.g. 'VIX9D / VIX' — handled via computation, no direct fetch
        return None
    # Else pass the ticker literally (VIX, SPX, VIX9D, VIX3M)
    return tb_ticker.strip()


def build_filter_columns(con, block_id: str, underlying: str, groups: pd.DataFrame, skipped: dict) -> pd.DataFrame:
    """Returns a DataFrame keyed by date_opened with every requested filter column."""
    merged = pd.DataFrame()
    # Bucket active rows by (schema, ticker, lag)
    buckets: dict = defaultdict(list)  # (schema, ticker, lag) -> list of (csv_col, tb_field)
    deferred_computed = []  # rows needing post-hoc computation

    for _, r in groups[groups["active"]].iterrows():
        csv_col = r["CSV Column"]
        schema = r["_tb_schema"]
        ticker = resolve_ticker(r["_tb_ticker"], underlying)
        lag = r["_lag"]
        tb_field = str(r["TB Field"]).strip() if not pd.isna(r["TB Field"]) else ""

        # Schema comparisons match the user-facing TB Table values in the
        # groups CSV (legacy names: market.daily / market._context_derived /
        # market.intraday). These are translated to 3.0 view names when SQL
        # is built — see connect_readonly() for the view registrations.
        if schema.startswith("market.intraday"):
            skipped[csv_col] = "intraday source not supported by this skill"
            continue

        if schema == "trades.trade_data":
            # Handled against the base frame (see finalization)
            continue

        if r["_tb_ticker"] and "/" in r["_tb_ticker"]:
            # Computed ratio like VIX9D_Open / VIX_Open — defer to post-step
            deferred_computed.append((csv_col, r))
            continue

        if schema == "market._context_derived":
            buckets[("context", None, LAG_PRIOR)].append((csv_col, tb_field))
            continue

        if schema == "market.daily":
            if not ticker:
                skipped[csv_col] = f"unresolvable ticker from TB Table '{r['TB Table']}'"
                continue
            db_col = resolve_db_field(con, csv_col, tb_field, ticker)
            if not db_col:
                skipped[csv_col] = f"no DB column resolvable for ticker={ticker} (tried csv_col, TB Field='{tb_field}', ticker-strip)"
                continue
            buckets[("market_daily", ticker, lag)].append((csv_col, db_col))
            continue

        skipped[csv_col] = f"unknown TB Table '{r['TB Table']}'"

    # Execute bucket queries
    for (kind, ticker, lag), entries in buckets.items():
        try:
            if kind == "context":
                # entries is list of (csv_col, db_col) but for context we only need db_cols
                ctx_fields = [e[1] for e in entries]
                raw = fetch_context_fields(con, block_id, ctx_fields)
                # Rename using the map (context table: csv_col == db_col typically)
                rename_map = {e[1]: e[0] for e in entries if e[0] != e[1]}
                if rename_map:
                    raw = raw.rename(columns=rename_map)
            else:
                raw, _ = fetch_ticker_fields(con, block_id, ticker, entries, lag)
        except Exception as e:
            msg = str(e).split("\n")[0][:140]
            for csv_col, _ in entries:
                skipped[csv_col] = f"query failed ({msg})"
            continue

        if raw.empty:
            for csv_col, _ in entries:
                skipped[csv_col] = "query returned empty"
            continue

        raw = raw.drop_duplicates(subset=["date_opened"], keep="first")
        if merged.empty:
            merged = raw
        else:
            merged = merged.merge(raw, on="date_opened", how="outer")

    return merged, deferred_computed


def apply_null_threshold(df: pd.DataFrame, cols: list[str], skipped: dict, exempt: set[str]) -> pd.DataFrame:
    """Drop columns exceeding MAX_NULL_FRAC nulls UNLESS the populated rows
    span at least MIN_COVERAGE_YEARS of date_opened — that fallback keeps
    indicator filters whose lookback warmup eats the early years but whose
    populated history still spans enough trading time to be analyzable.
    Locked base cols listed in `exempt` always pass."""
    drop_cols = []
    has_dates = "date_opened" in df.columns
    for c in cols:
        if c not in df.columns or c in exempt:
            continue
        if len(df) == 0:
            continue
        null_frac = df[c].isna().mean()
        if null_frac <= MAX_NULL_FRAC:
            continue
        # Over the null threshold — check the date-span fallback.
        span_years = None
        if has_dates:
            non_null_dates = pd.to_datetime(
                df.loc[df[c].notna(), "date_opened"], errors="coerce"
            ).dropna()
            if not non_null_dates.empty:
                span_years = (non_null_dates.max() - non_null_dates.min()).days / 365.25
                if span_years >= MIN_COVERAGE_YEARS:
                    continue  # passes coverage fallback
        if span_years is not None:
            skipped[c] = (
                f"{null_frac*100:.1f}% nulls, only {span_years:.1f}y span "
                f"(needs ≤{MAX_NULL_FRAC*100:.0f}% nulls OR ≥{MIN_COVERAGE_YEARS:.0f}y coverage)"
            )
        else:
            skipped[c] = (
                f"{null_frac*100:.1f}% nulls in join (> {MAX_NULL_FRAC*100:.0f}% threshold; no date span available)"
            )
        drop_cols.append(c)
    return df.drop(columns=drop_cols, errors="ignore")


def apply_computed_ratios(df: pd.DataFrame, deferred: list, skipped: dict) -> pd.DataFrame:
    """Handle rows whose TB Table was e.g. 'VIX9D / VIX' — evaluate from already-present cols."""
    for csv_col, row in deferred:
        tb_field = str(row["TB Field"]).strip()
        # Known pattern: 'A / B' where A and B are already column names
        m = re.match(r"^\s*([A-Za-z0-9_]+)\s*/\s*([A-Za-z0-9_]+)\s*$", tb_field)
        if not m:
            skipped[csv_col] = f"unparseable ratio TB Field '{tb_field}'"
            continue
        num = RATIO_ALIASES.get(m.group(1), m.group(1))
        den = RATIO_ALIASES.get(m.group(2), m.group(2))
        if num not in df.columns or den not in df.columns:
            skipped[csv_col] = f"ratio requires missing columns: {num}, {den}"
            continue
        import numpy as np
        num_vals = pd.to_numeric(df[num], errors="coerce")
        den_vals = pd.to_numeric(df[den], errors="coerce").replace(0, np.nan)
        df[csv_col] = num_vals / den_vals
    return df


# ── Holiday enrichment ───────────────────────────────────────────────────────

def enrich_holidays(df: pd.DataFrame, holidays_csv: pathlib.Path) -> pd.DataFrame:
    hdf = pd.read_csv(holidays_csv, encoding="utf-8-sig")
    date_col = next((c for c in hdf.columns if c.lower() == "date"), None)
    if date_col is None:
        raise RuntimeError(f"holidays CSV missing 'Date' column: {holidays_csv.name}")
    holidays = sorted(pd.to_datetime(hdf[date_col]).dt.date.unique())

    def iso_week_monday(d: dt.date) -> dt.date:
        y, w, _ = d.isocalendar()
        return dt.date.fromisocalendar(y, w, 1)

    # Precompute ISO-week Mondays for holidays, sorted.
    holiday_weeks = sorted(set(iso_week_monday(h) for h in holidays))

    def compute(d):
        if hasattr(d, "date"):
            d = d.date()

        # DAYS — calendar distance to nearest holiday date (directional).
        # next_h: strictly after d → days_to >= 1 always.
        # prev_h: at-or-before d → days_from = 0 when trade is on an early close day.
        # If the holiday registry doesn't cover the trade's range (no past or no
        # future holiday available), return None instead of clamping. Silently
        # clamping mislabels every out-of-range trade as "in a holiday week",
        # which inflates the Weeks_to/from = 0 buckets.
        next_h = next((h for h in holidays if h > d), None)
        prev_h = next((h for h in reversed(holidays) if h <= d), None)
        days_to = (next_h - d).days if next_h is not None else None
        days_from = (d - prev_h).days if prev_h is not None else None

        # WEEKS — ISO-week distance to nearest holiday week (directional).
        # If ANY holiday falls in the trade's ISO week, both weeks_to = weeks_from = 0
        # (this is the same-week case: trade_mon coincides with a holiday-week mon
        # so it appears in BOTH future_mons and past_mons).
        # Otherwise: weeks_to = weeks to the nearest future holiday week,
        #            weeks_from = weeks since the nearest past holiday week.
        # Out-of-range trades get None on the relevant side.
        trade_mon = iso_week_monday(d)
        future_mons = [hm for hm in holiday_weeks if hm >= trade_mon]
        past_mons = [hm for hm in holiday_weeks if hm <= trade_mon]
        next_mon = future_mons[0] if future_mons else None
        prev_mon = past_mons[-1] if past_mons else None
        weeks_to = (next_mon - trade_mon).days // 7 if next_mon is not None else None
        weeks_from = (trade_mon - prev_mon).days // 7 if prev_mon is not None else None

        return pd.Series({
            "Days_to_Holiday": days_to,
            "Weeks_to_Holiday": weeks_to,
            "Days_from_Holiday": days_from,
            "Weeks_from_Holiday": weeks_from,
        })

    enriched = df["date_opened"].apply(compute)
    for col in ["Days_to_Holiday", "Weeks_to_Holiday", "Days_from_Holiday", "Weeks_from_Holiday"]:
        df[col] = enriched[col].astype("Int64")
    return df


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Build entry_filter_data.csv for a block.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("block_id", help="Block folder name under TB root")
    ap.add_argument("--tb-root", default=None,
                    help=("TradeBlocks Data root directory. If omitted, walks up "
                          "from cwd looking for a TB 3.0 layout (a market/ folder "
                          "plus analytics.duckdb either at the root or under "
                          "database/) and uses the first ancestor that has both."))
    ap.add_argument("--groups-csv", default=None,
                    help=("Path to a specific filter-groups CSV to use "
                          "(e.g. a .V1 / .V2 / .calendar variant). Overrides auto-resolution. "
                          "Path may be absolute or relative to TB root."))
    args = ap.parse_args()

    tb_root = (pathlib.Path(args.tb_root).resolve() if args.tb_root
               else default_tb_root())
    skill_folder = pathlib.Path(__file__).resolve().parent
    shared_dir = (skill_folder.parent / "_shared").resolve()
    block_folder = tb_root / args.block_id
    ref_folder = block_folder / "alex-tradeblocks-ref"

    if not block_folder.is_dir():
        print(f"ERROR: block folder not found: {block_folder}", file=sys.stderr)
        return 2

    print(f"Block: {args.block_id}")
    print(f"TB root: {tb_root}")

    # Step 2 — resolve groups CSV
    explicit: Optional[pathlib.Path] = None
    if args.groups_csv:
        candidate = pathlib.Path(args.groups_csv)
        if not candidate.is_absolute():
            candidate = (tb_root / candidate).resolve()
        explicit = candidate

    try:
        groups_path, source, copied_from = resolve_groups_csv(ref_folder, shared_dir, explicit)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    # Display path relative to TB root when possible, else absolute
    try:
        display_path = groups_path.relative_to(tb_root)
    except ValueError:
        display_path = groups_path
    print(f"Groups CSV: {display_path}")
    print(f"  Filename:   {groups_path.name}")
    print(f"  Source:     {source}")
    if copied_from:
        print(f"  FYI: no groups CSV found in block ref folder, so copied the shared default:")
        print(f"       {copied_from}")
        print(f"       → {groups_path}")
        print(f"       (You can edit the block copy to customize filters for this block only.)")

    groups = load_groups(groups_path)

    # Step 3+4+5 — DB work inside a single read-only connection
    with connect_readonly(tb_root) as con:
        underlying = detect_underlying(con, args.block_id)
        if not underlying:
            print(f"ERROR: could not detect underlying ticker for block", file=sys.stderr)
            return 2
        print(f"Underlying: {underlying}")

        checks = run_sufficiency_checks(con, args.block_id, underlying)
        print(f"\nSufficiency checks:")
        print(f"  Trades: {checks['trades']} (with margin: {checks['has_margin']}) — {'OK' if checks['trade_count_ok'] else 'FAIL'}")
        print(f"  VIX coverage: {checks['cov_vix']*100:.1f}%")
        print(f"  SPX coverage: {checks['cov_spx']*100:.1f}%")
        print(f"  {underlying} coverage: {checks['cov_underlying']*100:.1f}%")
        print(f"  VIX9D coverage: {checks['cov_vix9d']*100:.1f}%")
        print(f"  VIX3M coverage: {checks['cov_vix3m']*100:.1f}%")
        print(f"  Context coverage: {checks['cov_context']*100:.1f}%")
        print(f"  SLR parseable: {checks['slr_parseable']*100:.1f}%")

        if not checks["trade_count_ok"]:
            print(f"\nERROR: sufficiency check failed — need ≥{MIN_TRADES} trades, all with margin>0.", file=sys.stderr)
            return 2

        # Base frame
        base = build_base_frame(con, args.block_id)
        print(f"\nPCR summary: {summarize_pcr(base)}")

        # Intraday VIX / underlying lookup at each trade's entry and close times.
        # Primary source for VIX_at_Entry, VIX_at_Close, Intra_Move_Pct.
        # Uses the block's detected `underlying` ticker (SPX / QQQ / IWM / SPY /
        # etc.) — don't hardcode SPX.
        intraday_ctx = build_intraday_columns(con, args.block_id, underlying)

        # Filter frame
        skipped: dict[str, str] = {}
        filter_frame, deferred = build_filter_columns(con, args.block_id, underlying, groups, skipped)

    # Merge base + filters
    if filter_frame.empty:
        df = base.copy()
    else:
        df = base.merge(filter_frame, on="date_opened", how="left")

    # Handle trade-level filter aliases. Columns already populated by base_frame
    # or coalesce_trade_context fall through without warning; unknown columns
    # land in `skipped`. The post-conditions of SLR, premium_per_contract, and
    # margin_per_contract are guaranteed by build_base_frame; VIX_at_Entry,
    # VIX_at_Close, and Intra_Move_Pct are populated further down by the
    # intraday + OO-fallback coalesce layer.
    _trade_level_already_present = {
        "premium_per_contract", "margin_per_contract",
        "VIX_at_Entry", "VIX_at_Close", "Intra_Move_Pct",
    }
    for _, r in groups[groups["active"] & (groups["_tb_schema"] == "trades.trade_data")].iterrows():
        csv_col = r["CSV Column"]
        if csv_col == "SLR":
            df["SLR"] = df["_slr_computed"]
        elif csv_col in _trade_level_already_present:
            pass
        else:
            skipped[csv_col] = f"trade-level filter '{csv_col}' not implemented"

    df = df.drop(columns=["_slr_computed"], errors="ignore")

    # Merge intraday + OO CSV fallback for VIX_at_Entry / VIX_at_Close / Intra_Move.
    # Primary = market_spot (TB-native), fallback = OO trade-log CSV in block folder.
    oo_fallback_df, oo_meta = build_oo_fallback(block_folder)
    df, coverage = coalesce_trade_context(df, intraday_ctx, oo_fallback_df)

    # Gap_Pct is populated by the groups-CSV filter resolver from market_daily
    # enrichment (primary). Apply OO CSV fallback (Gap_Pct_oo from coalesce)
    # where primary produced NaN — belt-and-suspenders for blocks on tickers
    # with limited market_daily coverage (e.g. SPY/IWM pre-2024-03).
    gap_coverage = {"market_daily": 0, "oo_csv": 0, "missing": 0}
    if "Gap_Pct" in df.columns:
        primary = pd.to_numeric(df["Gap_Pct"], errors="coerce")
        fallback = pd.to_numeric(df.get("Gap_Pct_oo", pd.Series([pd.NA]*len(df))), errors="coerce")
        df["Gap_Pct"] = primary.fillna(fallback)
        gap_coverage["market_daily"] = int(primary.notna().sum())
        gap_coverage["oo_csv"] = int((primary.isna() & fallback.notna()).sum())
        gap_coverage["missing"] = int((primary.isna() & fallback.isna()).sum())
    elif "Gap_Pct_oo" in df.columns:
        # Gap_Pct wasn't requested in groups CSV but OO has it — still expose.
        df["Gap_Pct"] = pd.to_numeric(df["Gap_Pct_oo"], errors="coerce")
        gap_coverage["oo_csv"] = int(df["Gap_Pct"].notna().sum())
        gap_coverage["missing"] = int(df["Gap_Pct"].isna().sum())
    df = df.drop(columns=["Gap_Pct_oo"], errors="ignore")
    coverage["Gap_Pct"] = gap_coverage  # attach to the same coverage dict for reporting

    # Post-hoc ratios (e.g., VIX9D/VIX_Ratio)
    df = apply_computed_ratios(df, deferred, skipped)

    # Null-threshold filter — don't prune locked base cols or requested non-null cols
    exempt = {"trade_index", "date_opened", "time_opened", "margin_per_contract",
              "premium_per_contract", "pl_per_contract", "rom_pct", "pcr_pct",
              "VIX_at_Entry", "VIX_at_Close", "Intra_Move_Pct"}
    candidate_cols = [r["CSV Column"] for _, r in groups[groups["active"]].iterrows()
                      if r["CSV Column"] in df.columns]
    df = apply_null_threshold(df, candidate_cols, skipped, exempt)

    # Order columns: locked base (including new context cols), then groups CSV order.
    locked = ["trade_index", "date_opened", "time_opened", "margin_per_contract",
              "premium_per_contract", "pl_per_contract", "rom_pct", "pcr_pct",
              "VIX_at_Entry", "VIX_at_Close", "Intra_Move_Pct"]
    filter_order = [r["CSV Column"] for _, r in groups[groups["active"]].iterrows()
                    if r["CSV Column"] in df.columns and r["CSV Column"] not in locked]
    # de-dupe while preserving order
    seen = set()
    filter_order = [c for c in filter_order if not (c in seen or seen.add(c))]
    df = df[locked + filter_order]

    # Holiday enrichment
    holidays_csv: Optional[pathlib.Path] = None
    try:
        holidays_csv = resolve_holidays_csv(shared_dir)
        df = enrich_holidays(df, holidays_csv)
        holiday_ok = True
        holiday_note = f"enriched from {holidays_csv.name}"
    except Exception as e:
        holiday_ok = False
        holiday_note = f"enrichment failed: {e}"

    # Write
    out_csv = ref_folder / "entry_filter_data.csv"
    df.to_csv(out_csv, index=False)

    # ─── Post-action summary ───────────────────────────────────────────────
    n_base = len(locked)
    n_filter = len(filter_order)
    n_holiday = 4 if holiday_ok else 0
    n_skipped = len(skipped)

    print()
    print("=" * 78)
    print("Entry filter data built.")
    print("=" * 78)

    # Section 1 — SOURCES (explicit file provenance)
    try:
        groups_rel = groups_path.relative_to(tb_root)
    except ValueError:
        groups_rel = groups_path
    try:
        out_rel = out_csv.relative_to(tb_root)
    except ValueError:
        out_rel = out_csv
    try:
        holidays_rel = holidays_csv.relative_to(tb_root) if holiday_ok else None
    except ValueError:
        holidays_rel = holidays_csv if holiday_ok else None

    # Tag each path as [block-local] (lives in block's alex-tradeblocks-ref/) or
    # [shared] (lives in the plugin's _shared/ folder) or [explicit] (user-supplied).
    def locality_tag(p: pathlib.Path) -> str:
        try:
            p_resolved = p.resolve()
        except Exception:
            p_resolved = p
        if ref_folder.resolve() in p_resolved.parents or p_resolved.parent == ref_folder.resolve():
            return "block-local"
        if shared_dir in p_resolved.parents or p_resolved.parent == shared_dir:
            return "shared"
        return "external"

    groups_tag = "explicit" if source == "explicit" else locality_tag(groups_path)
    out_tag = locality_tag(out_csv)
    holidays_tag = locality_tag(holidays_csv) if holiday_ok else None

    print("\nSources (all used)")
    print(f"  Block:          {args.block_id}")
    print(f"  Groups CSV:     {groups_rel}  [{groups_tag}]")
    if holiday_ok:
        print(f"  Holidays CSV:   {holidays_rel}  [{holidays_tag}]")
    else:
        print(f"  Holidays CSV:   (not loaded — {holiday_note})")
    if oo_meta.get("csv_path"):
        try:
            oo_rel = oo_meta["csv_path"].relative_to(tb_root)
        except ValueError:
            oo_rel = oo_meta["csv_path"]
        print(f"  OO trade log:   {oo_rel}  [block-local]  (fallback source)")
    else:
        print(f"  OO trade log:   (none found in block folder — no fallback available)")
    print(f"  Output CSV:     {out_rel}  [{out_tag}]")

    # Section 2 — BUILD STATS
    print("\nBuild stats")
    print(f"  Trades:           {len(df)}")
    print(f"  Base columns:     {n_base}")
    print(f"  Filter columns:   {n_filter} populated, {n_skipped} skipped")
    print(f"  Holiday columns:  {n_holiday}")
    print(f"  Total columns:    {len(df.columns)}")

    # Section 2b — TRADE-CONTEXT COVERAGE
    # Sources: VIX_at_Entry / VIX_at_Close / Intra_Move_Pct come from
    # market_spot (primary) or OO trade-log CSV (fallback).
    # Gap_Pct comes from market_daily enrichment (primary) or OO CSV (fallback).
    # Trades missing in both sources stay NaN and are flagged here.
    print("\nTrade-context coverage")
    any_warnings = False
    for col_name, cov in coverage.items():
        # Use "primary" / "fallback" / "missing" language — source names differ
        # per column (tb_intraday vs market_daily) but the shape is the same.
        primary_key = "market_daily" if "market_daily" in cov else "tb_intraday"
        primary_label = "market_daily" if primary_key == "market_daily" else "TB intraday"
        total = cov.get(primary_key, 0) + cov.get("oo_csv", 0) + cov.get("missing", 0)
        if total == 0:
            continue
        parts = [f"{primary_label}: {cov.get(primary_key, 0)}"]
        if cov.get("oo_csv", 0) > 0:
            parts.append(f"OO CSV fallback: {cov['oo_csv']}")
        if cov.get("missing", 0) > 0:
            parts.append(f"missing: {cov['missing']}")
        print(f"  {col_name:<15} {'  ·  '.join(parts)}")
        if cov.get("oo_csv", 0) > 0 or cov.get("missing", 0) > 0:
            any_warnings = True
    if any_warnings:
        if oo_meta.get("csv_path") is None:
            print("  ⚠  No OO trade log CSV found in block folder — cannot backfill pre-intraday trades.")
        else:
            found = []
            if oo_meta.get("vix_entry_col"):
                found.append(f"VIX entry = '{oo_meta['vix_entry_col']}'")
            if oo_meta.get("vix_close_col"):
                found.append(f"VIX close = '{oo_meta['vix_close_col']}'")
            if oo_meta.get("movement_col"):
                found.append("Movement = 'Movement'")
            if oo_meta.get("gap_col"):
                found.append("Gap = 'Gap'")
            if found:
                print(f"  OO columns used for fallback: {', '.join(found)}")
            else:
                print(f"  ⚠  OO CSV has no usable fallback columns.")
    else:
        print("  (all trades covered by primary source — no fallback needed)")

    # Section 3 — SKIPPED FILTERS (explicit missing-filter block)
    print("\nSkipped filters")
    if not skipped:
        print("  (none — all requested filters populated)")
    else:
        for col, reason in sorted(skipped.items()):
            print(f"  - {col:<28} {reason}")

    # Section 4 — PER-COLUMN SUMMARY (transposed describe)
    print("\nPer-column summary (numeric columns only)")
    numeric = df.select_dtypes(include="number")
    if numeric.empty:
        print("  (no numeric columns to summarize)")
    else:
        desc = numeric.describe(percentiles=[0.05, 0.25, 0.50, 0.75, 0.95]).T
        # Reorder columns into a more useful sequence
        stat_order = ["count", "mean", "std", "min", "5%", "25%", "50%", "75%", "95%", "max"]
        desc = desc[[c for c in stat_order if c in desc.columns]]
        # Also report null count per column for completeness
        desc.insert(1, "nulls", df[numeric.columns].isna().sum().loc[desc.index].astype(int))

        # Format: count & nulls as int, stats to 3 significant decimals
        def fmt(v, col):
            if pd.isna(v):
                return "—"
            if col in ("count", "nulls"):
                return f"{int(v)}"
            if abs(v) >= 1000:
                return f"{v:,.1f}"
            if abs(v) >= 1:
                return f"{v:.3f}"
            return f"{v:.4f}"

        col_widths = {c: max(len(c), max(len(fmt(desc[c].iloc[i], c)) for i in range(len(desc)))) for c in desc.columns}
        name_width = max(max(len(str(r)) for r in desc.index), len("column"))

        header = f"  {'column':<{name_width}}  " + "  ".join(f"{c:>{col_widths[c]}}" for c in desc.columns)
        print(header)
        print("  " + "-" * (len(header) - 2))
        for row_name, row in desc.iterrows():
            cells = "  ".join(f"{fmt(row[c], c):>{col_widths[c]}}" for c in desc.columns)
            print(f"  {str(row_name):<{name_width}}  {cells}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
