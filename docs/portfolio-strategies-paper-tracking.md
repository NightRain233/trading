# Portfolio Strategies Paper Tracking

## Quick Start

```bash
# Start backend
cd backend && uv run python main.py

# Start frontend (separate terminal)
cd frontend && pnpm dev
```

Open `http://localhost:5173/portfolio-strategies` or click the "组合" tab.

Click "刷新" to download data and bootstrap paper accounts.

## Strategies

| ID | Name | Type | Rebalance |
|----|------|------|-----------|
| `btc_supertrend_satellite` | BTC SuperTrend Satellite 7.5% | Paper | Every 10 ETF sessions |
| `theme_alpha` | Theme Alpha | Paper | ~10th/25th monthly |
| `btc_supertrend_satellite_5` | BTC 5% variant | Comparison | — |
| `btc_supertrend_satellite_10` | BTC 10% variant | Comparison | — |

### BTC SuperTrend Satellite

- Core: inverse-volatility RP on 510300.SS / 513100.SS / 518880.SS
- Satellite: BTC-USD at 7.5% when SuperTrend is on, cash otherwise
- SuperTrend: ATR(10, SMA), multiplier 3
- Threshold: 1% target change (BTC switch always executes)

### Theme Alpha

- 80% Core + 20% LVT satellite
- Core: inverse-volatility RP, independent MA200 defense for CSI300 and Nasdaq
- LVT: MA60 + 63-session momentum eligible → lowest-vol Top3
- Threshold: 2% turnover; 15% max per-asset change

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/portfolio-strategies` | List all strategies |
| GET | `/api/portfolio-strategies/{id}/snapshot` | Full state snapshot |
| GET | `/api/portfolio-strategies/{id}/target-weights` | Latest target weights |
| GET | `/api/portfolio-strategies/{id}/rebalance-diff` | Current vs target delta |
| GET | `/api/portfolio-strategies/{id}/ledger?limit=&cursor=` | Paginated events |
| GET | `/api/portfolio-strategies/{id}/nav?start=&end=` | NAV history |
| POST | `/api/portfolio-strategies/{id}/refresh` | Refresh, calculate, reconcile |

Errors: 404 (unknown ID), 409 (comparison-only operation), 400 (invalid params).

## Database

Path: `backend/backtest_results/portfolio_paper.sqlite`

Tables: `paper_accounts`, `signal_snapshots`, `signal_weights`, `rebalance_events`, `paper_trades`, `position_snapshots`, `nav_snapshots`, `data_quality_events`.

WAL mode, foreign keys, busy timeout 5s. `BEGIN IMMEDIATE` for writes. Idempotent by uniqueness constraints.

## Execution Semantics

- **Next-close**: Signal at close of date D, executes at next ETF session close
- **Bootstrap**: Creates positions at target weights, no historical trades or costs
- **Threshold**: Turnover below threshold → skipped (no trades, still values positions)
- **Max trade**: Theme Alpha clips per-asset deltas to 15%
- **Blocked data**: Returns diagnostics, preserves last valid signal, no silent trades

## Limitations

- BTC-USD is a synthetic return proxy — no CNY/USD conversion modeled
- No broker connectivity or automatic orders
- No backfilled historical paper trades
- Fractional paper units allowed
- Yahoo Finance data quality and corrections apply

## Verification

```bash
# Backend tests
cd backend && uv run pytest -q

# Backend tests — portfolio only
uv run pytest \
  tests/test_portfolio_strategy_registry.py \
  tests/test_portfolio_strategy_indicators.py \
  tests/test_portfolio_strategy_schedules.py \
  tests/test_portfolio_strategy_market_data.py \
  tests/test_btc_satellite_strategy.py \
  tests/test_theme_alpha_strategy.py \
  tests/test_portfolio_strategy_ledger.py \
  tests/test_portfolio_paper_engine.py -q

# Frontend build
cd frontend && ./node_modules/.bin/tsc -b && ./node_modules/.bin/vite build
```
