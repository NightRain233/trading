# Strategy Roadmap Priorities

Last updated: 2026-05-05

This document is the short-term strategy backlog. Use
`docs/plans/2026-05-05-strategy-continuation-status.md` for the current
handoff summary and exact commands.

## Status Board

### Done

1. **Resonance v2 risk-aware signal**
   - Added pool type, entry score, risk level, ATR stop, target, risk percent,
     and reward/risk fields.
   - Exposed the fields through backend response models, frontend types, and
     compact watchlist row badges.

2. **Backtest MVP**
   - Backend-only historical backtest over cached parquet data.
   - Assumptions are explicit: signal after close, next-open entry, one position
     per symbol, OHLC stop/target checks, hard-exit support, fee/slippage bps.
   - Reports summary, pool type, asset class, year, symbol contribution, and
     diagnostics.

3. **Strategy versioning**
   - Added named versions:
     - `resonance_v2_atr_1_5`
     - `resonance_v2_atr_2_0`
     - `resonance_v2_atr_2_0_spy_bullish_etf_established`
     - `resonance_v2_atr_2_0_csi300_bullish_etf_established`
     - `resonance_v2_atr_2_0_csi300_strict_bullish_etf_established`
     - `resonance_v2_atr_2_0_csi300_entry_buffer_1_0_etf_established`
   - Backtest outputs are traceable to strategy ids.

4. **ETF universe files**
   - Added `backend/universes/etf_core.json`.
   - Added `backend/universes/a_share_etf_core.json`.

5. **Market regime filter**
   - Added `bullish_ema` filter.
   - US ETF version uses SPY.
   - A-share ETF version uses `000300.SS`.
   - Fixed CLI override behavior so version-level market symbols are respected
     when `--market-symbol` is omitted.

6. **Backtest diagnostics**
   - Added loss summary, worst trades, entry score buckets, risk level groups,
     exit reason groups, exit-time market regime groups, and diagnostics by year.

### Next

1. **Compare buffered strategy across broader samples**
   - Current best A-share ETF candidate is
     `resonance_v2_atr_2_0_csi300_entry_buffer_1_0_etf_established`.
   - It requires CSI 300 to be bullish at signal and entry, and requires entry
     close to be at least 1% above EMA20.
   - Next check: run the same comparison on broader ETF universes and different
     date ranges before treating it as a preferred production signal.

2. **Data quality panel**
   - Show stale data, missing bars, invalid OHLC rows, missing weekly cache, and
     last data timestamp.
   - Start backend-only; UI can come after the checks stabilize.

3. **Position model**
   - Turn signals into managed simulated/manual positions with entry date,
     entry price, stop, target, holding days, and current P/L.
   - No brokerage integration yet.

4. **Structured signal explanation**
   - Convert free-form reasons into stable reason codes.
   - Use the same reason fields for UI, LLM summaries, and backtest attribution.

5. **Universe expansion and bias control**
   - Add more A-share ETFs only after data quality checks can identify missing
     or stale cache clearly.
   - Track universe membership in JSON rather than relying on the watchlist.

6. **Regime-aware risk sizing**
   - The buffered entry filter helps avoid weak market entries, but high-risk
     ETF trades can still dominate worst-trade lists.
   - Candidate follow-up: reduce size or tighten stops for `riskLevel="high"`.

## Near-Term Rule

Do not tune resonance thresholds blindly. Any strategy change should first add
or update a named strategy version, then run at least:

- watchlist backtest;
- US ETF universe backtest if the change affects ETFs broadly;
- A-share ETF universe backtest with `000300.SS` market regime filter.

The system should prefer measurable strategy changes over adding more indicators.
