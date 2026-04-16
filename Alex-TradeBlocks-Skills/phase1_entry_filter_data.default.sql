-- Phase 1: Entry Filter Data Query
-- Single CTE returning one row per trade with all filter columns.
-- LEFT JOINs ensure trades with missing market data get NULLs.
-- Placeholders: {blockId}, {ticker} (underlying, e.g. SPX, QQQ)
--
-- Notes:
-- - VIX_Gap_Pct: If market.daily VIX has a Gap_Pct column, use same-day VIX join.
--   Otherwise compute as VIX_Open - prior_VIX_Close. Adjust the COALESCE below.
-- - Use LIMIT 500 as safety (well above any block's trade count).
-- - If query times out (correlated subqueries), split into 3 queries:
--   (1) trade_base + trade-level, (2) SPX + VIX fields, (3) VIX9D + VIX3M + context.
--   Merge by date_opened.

-- QUERY: entry_filter_data
WITH trade_base AS (
  SELECT
    t.date_opened,
    CAST(t.date_opened AS DATE) as trade_date,
    t.pl,
    t.margin_req,
    CAST(t.pl / NULLIF(t.margin_req, 0) * 100 AS DOUBLE) as rom_pct,
    -- Trade-level computed fields
    (CAST(regexp_extract(t.legs, 'P STO ([0-9.]+)', 1) AS DOUBLE) +
     CAST(regexp_extract(t.legs, 'C STO ([0-9.]+)', 1) AS DOUBLE)) / NULLIF(
     CAST(regexp_extract(t.legs, 'P BTO ([0-9.]+)', 1) AS DOUBLE) +
     CAST(regexp_extract(t.legs, 'C BTO ([0-9.]+)', 1) AS DOUBLE), 0) as SLR,
    CAST(t.premium AS DOUBLE) / t.num_contracts as premium_per_contract,
    CAST(t.margin_req AS DOUBLE) / t.num_contracts as margin_per_contract,
    CAST(t.pl AS DOUBLE) / t.num_contracts as pl_per_contract,
    t.num_contracts
  FROM trades.trade_data t
  WHERE t.block_id = '{blockId}'
),
-- SPX prior day (close-derived fields: RSI, ATR, RV, returns, etc.)
spx_pd AS (
  SELECT tb.trade_date,
    m.RSI_14, m.ATR_Pct, m.Realized_Vol_5D, m.Realized_Vol_20D,
    m.Return_5D, m.Return_20D, m.Intraday_Range_Pct, m.Intraday_Return_Pct,
    m.Close_Position_In_Range, m.Gap_Filled, m.Consecutive_Days,
    m.Price_vs_SMA50_Pct, m.Price_vs_EMA21_Pct
  FROM trade_base tb
  JOIN market.daily m ON m.ticker = '{ticker}'
    AND CAST(m.date AS DATE) = (
      SELECT MAX(CAST(m2.date AS DATE)) FROM market.daily m2
      WHERE m2.ticker = 'SPX' AND CAST(m2.date AS DATE) < tb.trade_date)
),
-- SPX same day (open-known and static fields)
spx_sd AS (
  SELECT tb.trade_date,
    m.Gap_Pct, m.Prev_Return_Pct, m.Prior_Range_vs_ATR,
    m.Day_of_Week, m.Month, m.Is_Opex
  FROM trade_base tb
  JOIN market.daily m ON m.ticker = '{ticker}'
    AND CAST(m.date AS DATE) = tb.trade_date
),
-- VIX prior day (close-derived)
vix_pd AS (
  SELECT tb.trade_date,
    m.close as VIX_Close, m.high as VIX_High, m.low as VIX_Low,
    m.ivr as VIX_IVR, m.ivp as VIX_IVP
  FROM trade_base tb
  JOIN market.daily m ON m.ticker = 'VIX'
    AND CAST(m.date AS DATE) = (
      SELECT MAX(CAST(m2.date AS DATE)) FROM market.daily m2
      WHERE m2.ticker = 'VIX' AND CAST(m2.date AS DATE) < tb.trade_date)
),
-- VIX same day (open-known)
vix_sd AS (
  SELECT tb.trade_date,
    m.open as VIX_Open,
    CAST(m.open AS DOUBLE) - CAST(LAG(m.close) OVER (ORDER BY m.date) AS DOUBLE) as VIX_Gap_raw
  FROM trade_base tb
  JOIN market.daily m ON m.ticker = 'VIX'
    AND CAST(m.date AS DATE) = tb.trade_date
),
-- VIX9D same day (for ratio)
vix9d_sd AS (
  SELECT tb.trade_date, m.open as VIX9D_Open
  FROM trade_base tb
  JOIN market.daily m ON m.ticker = 'VIX9D'
    AND CAST(m.date AS DATE) = tb.trade_date
),
-- VIX9D prior day (close-derived metrics)
vix9d_pd AS (
  SELECT tb.trade_date,
    m.close as VIX9D_Close, m.ivr as VIX9D_IVR, m.ivp as VIX9D_IVP
  FROM trade_base tb
  JOIN market.daily m ON m.ticker = 'VIX9D'
    AND CAST(m.date AS DATE) = (
      SELECT MAX(CAST(m2.date AS DATE)) FROM market.daily m2
      WHERE m2.ticker = 'VIX9D' AND CAST(m2.date AS DATE) < tb.trade_date)
),
-- VIX3M same day
vix3m_sd AS (
  SELECT tb.trade_date, m.open as VIX3M_Open
  FROM trade_base tb
  JOIN market.daily m ON m.ticker = 'VIX3M'
    AND CAST(m.date AS DATE) = tb.trade_date
),
-- VIX3M prior day
vix3m_pd AS (
  SELECT tb.trade_date,
    m.close as VIX3M_Close, m.ivr as VIX3M_IVR, m.ivp as VIX3M_IVP
  FROM trade_base tb
  JOIN market.daily m ON m.ticker = 'VIX3M'
    AND CAST(m.date AS DATE) = (
      SELECT MAX(CAST(m2.date AS DATE)) FROM market.daily m2
      WHERE m2.ticker = 'VIX3M' AND CAST(m2.date AS DATE) < tb.trade_date)
),
-- Context derived (prior day)
ctx AS (
  SELECT tb.trade_date,
    c.Vol_Regime, c.Term_Structure_State, c.VIX_Spike_Pct
  FROM trade_base tb
  JOIN market._context_derived c ON CAST(c.date AS DATE) = (
    SELECT MAX(CAST(c2.date AS DATE)) FROM market._context_derived c2
    WHERE CAST(c2.date AS DATE) < tb.trade_date)
)
SELECT
  tb.date_opened, tb.pl_per_contract, tb.margin_per_contract, tb.rom_pct,
  -- Trade-level
  tb.SLR, tb.premium_per_contract,
  -- VIX prior day
  vp.VIX_Close, vp.VIX_High, vp.VIX_Low, vp.VIX_IVR, vp.VIX_IVP,
  -- VIX same day
  vs.VIX_Open,
  -- VIX Gap: use _context_derived VIX_Gap_Pct (same-day, open-known), fallback to computed
  COALESCE(ctx.VIX_Gap_Pct, vs.VIX_Gap_raw) as VIX_Gap_Pct,
  -- VIX9D
  v9s.VIX9D_Open,
  CAST(v9s.VIX9D_Open AS DOUBLE) / NULLIF(CAST(vs.VIX_Open AS DOUBLE), 0) as VIX9D_VIX_Ratio,
  v9p.VIX9D_Close, v9p.VIX9D_IVR, v9p.VIX9D_IVP,
  -- VIX3M
  v3s.VIX3M_Open,
  v3p.VIX3M_Close, v3p.VIX3M_IVR, v3p.VIX3M_IVP,
  -- Context derived
  ctx.Vol_Regime, ctx.Term_Structure_State, ctx.VIX_Spike_Pct,
  -- SPX prior day
  sp.RSI_14, sp.ATR_Pct, sp.Realized_Vol_5D, sp.Realized_Vol_20D,
  sp.Return_5D, sp.Return_20D, sp.Intraday_Range_Pct, sp.Intraday_Return_Pct,
  sp.Close_Position_In_Range, sp.Gap_Filled, sp.Consecutive_Days,
  sp.Price_vs_SMA50_Pct, sp.Price_vs_EMA21_Pct,
  -- SPX same day
  ss.Gap_Pct, ss.Prev_Return_Pct, ss.Prior_Range_vs_ATR,
  ss.Day_of_Week, ss.Month, ss.Is_Opex
FROM trade_base tb
LEFT JOIN spx_pd sp ON sp.trade_date = tb.trade_date
LEFT JOIN spx_sd ss ON ss.trade_date = tb.trade_date
LEFT JOIN vix_pd vp ON vp.trade_date = tb.trade_date
LEFT JOIN vix_sd vs ON vs.trade_date = tb.trade_date
LEFT JOIN vix9d_sd v9s ON v9s.trade_date = tb.trade_date
LEFT JOIN vix9d_pd v9p ON v9p.trade_date = tb.trade_date
LEFT JOIN vix3m_sd v3s ON v3s.trade_date = tb.trade_date
LEFT JOIN vix3m_pd v3p ON v3p.trade_date = tb.trade_date
LEFT JOIN ctx ON ctx.trade_date = tb.trade_date
ORDER BY tb.date_opened
LIMIT 500;
