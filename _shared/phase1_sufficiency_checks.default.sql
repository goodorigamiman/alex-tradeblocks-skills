-- Phase 1: Data Sufficiency Checks
-- Run ALL three checks before building the data query.
-- Placeholder: {blockId}

-- ── Check 1: Trade count and margin coverage ────────────────────────────
-- Minimum: 50 trades, all with margin > 0.
-- QUERY: sufficiency_trades
SELECT COUNT(*)::INT as trades,
       COUNT(CASE WHEN margin_req > 0 THEN 1 END)::INT as has_margin
FROM trades.trade_data WHERE block_id = '{blockId}';

-- ── Check 2: Market data coverage by ticker ─────────────────────────────
-- Minimum: 90% coverage per source.
-- If any source < 90%, exclude its filters and report which ones.
-- QUERY: sufficiency_market
SELECT
  CAST(SUM(CASE WHEN vix_sd.close IS NOT NULL THEN 1.0 ELSE 0.0 END) AS INT) as vix_same_day,
  CAST(SUM(CASE WHEN vix_pd.close IS NOT NULL THEN 1.0 ELSE 0.0 END) AS INT) as vix_prior_day,
  CAST(SUM(CASE WHEN spx_pd.RSI_14 IS NOT NULL THEN 1.0 ELSE 0.0 END) AS INT) as spx_prior_day,
  CAST(SUM(CASE WHEN spx_sd.Gap_Pct IS NOT NULL THEN 1.0 ELSE 0.0 END) AS INT) as spx_same_day,
  CAST(SUM(CASE WHEN vix9d_sd.open IS NOT NULL THEN 1.0 ELSE 0.0 END) AS INT) as vix9d_same_day,
  CAST(SUM(CASE WHEN vix3m_sd.open IS NOT NULL THEN 1.0 ELSE 0.0 END) AS INT) as vix3m_same_day,
  CAST(SUM(CASE WHEN cd.Vol_Regime IS NOT NULL THEN 1.0 ELSE 0.0 END) AS INT) as context_derived,
  CAST(COUNT(*) AS INT) as total
FROM trades.trade_data t
LEFT JOIN market.daily vix_sd ON vix_sd.ticker = 'VIX' AND CAST(vix_sd.date AS DATE) = CAST(t.date_opened AS DATE)
LEFT JOIN market.daily vix_pd ON vix_pd.ticker = 'VIX' AND CAST(vix_pd.date AS DATE) = (
  SELECT MAX(CAST(m2.date AS DATE)) FROM market.daily m2 WHERE m2.ticker = 'VIX' AND CAST(m2.date AS DATE) < CAST(t.date_opened AS DATE))
LEFT JOIN market.daily spx_pd ON spx_pd.ticker = 'SPX' AND CAST(spx_pd.date AS DATE) = (
  SELECT MAX(CAST(m2.date AS DATE)) FROM market.daily m2 WHERE m2.ticker = 'SPX' AND CAST(m2.date AS DATE) < CAST(t.date_opened AS DATE))
LEFT JOIN market.daily spx_sd ON spx_sd.ticker = 'SPX' AND CAST(spx_sd.date AS DATE) = CAST(t.date_opened AS DATE)
LEFT JOIN market.daily vix9d_sd ON vix9d_sd.ticker = 'VIX9D' AND CAST(vix9d_sd.date AS DATE) = CAST(t.date_opened AS DATE)
LEFT JOIN market.daily vix3m_sd ON vix3m_sd.ticker = 'VIX3M' AND CAST(vix3m_sd.date AS DATE) = CAST(t.date_opened AS DATE)
LEFT JOIN market._context_derived cd ON CAST(cd.date AS DATE) = (
  SELECT MAX(CAST(c2.date AS DATE)) FROM market._context_derived c2 WHERE CAST(c2.date AS DATE) < CAST(t.date_opened AS DATE))
WHERE t.block_id = '{blockId}';

-- ── Check 3: SLR parseability ───────────────────────────────────────────
-- If not all parseable, set SLR CSV Column to NULL (skip in data query).
-- QUERY: sufficiency_slr
SELECT COUNT(*)::INT as total,
       COUNT(CASE WHEN legs LIKE '%STO%' AND legs LIKE '%BTO%' THEN 1 END)::INT as parseable
FROM trades.trade_data WHERE block_id = '{blockId}';
