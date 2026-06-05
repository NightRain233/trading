# RS Rotation Robustness Research Design

## Goal

Test whether the current RS rotation conclusion depends on hindsight universe selection, a short favorable cycle, or an A-share-only opportunity set.

## Scope

The research keeps the existing RS engine unchanged: 60-bar momentum, 20-trading-day rebalance, top-N holdings, 5 bps fee and 5 bps slippage. It compares multiple universes and reports full-period, calendar-year, rolling 3-year, and rolling 5-year behavior.

## Universes

- `a_share_broad`: broad A-share ETFs only.
- `a_share_broad_style`: broad ETFs plus dividend/value style ETFs.
- `a_share_core_current`: current configured A-share ETF universe.
- `us_available`: local US data currently available in `backend/data`.
- `global_available`: A-share core plus locally available SPY/QQQ/BTC/GC.

This is not a full historical ETF membership reconstruction. The report must state that current-pool results can still contain universe selection bias.

## Filters

- A-share symbols use `510300.SS` monthly MACD.
- US symbols use `SPY` monthly MACD.
- Crypto uses `BTC-USD` monthly MACD.
- Commodity uses `GC=F` monthly MACD.

## Outputs

Each variant reports total return, max drawdown, return/drawdown ratio, start/end dates, annual returns, rolling 3-year and 5-year windows, worst year, positive year count, and return concentration.

## Tests

Tests cover universe construction, per-class filter construction, annual stats, and rolling-window stats.
