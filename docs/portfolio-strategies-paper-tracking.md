# Portfolio Strategies Paper Tracking

## Quick Start

```bash
# Start backend
cd backend && uv run python main.py

# Start frontend (separate terminal)
cd frontend && pnpm dev
```

Open `http://localhost:5173/portfolio-strategies` or click the "组合" tab.

Click "刷新当前策略" to reconcile new market data and pending paper orders. Refresh never creates an account. Existing Theme Alpha and BTC accounts are never re-bootstrapped; every new account starts only from an explicit activation date and does not invent historical paper trades.

## Strategies

| ID | Name | Type | Rebalance |
|----|------|------|-----------|
| `risk_parity_core_next_open` | RiskParity Core | Paper | Every 10 common core sessions; next Open |
| `core90_ma200_bull10` | Core90 + MA200 Bull10 | Paper | Core every 10 sessions; bull orders per market |
| `btc_supertrend_satellite` | BTC SuperTrend Satellite 7.5% | Paper | Every 10 ETF sessions |
| `theme_alpha` | Theme Alpha | Paper | ~10th/25th monthly |
| `core90_raw_bull10` | Core90 + Raw Bull10 | Comparison | No paper account |
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

### Frozen xquant Next-Open Strategies

- RiskParity core: 510300.SS / 513100.SS / 518880.SS, 20 common-session returns, inverse volatility, every 10 common sessions, 10 bps one-way cost.
- Core signals are generated after the common Close and execute at the next common valid Open. Between rebalances, quantities remain unchanged and weights drift naturally.
- Bull sleeve: fixed 10% total budget, 10% maximum per satellite position, 10 positions maximum, ST 7/3, 5 bps commission plus 5 bps slippage each side.
- `setup=breakout` bull flips from production policy `scan_v2_right_side_5` are eligible even when formal permission is not `buy`.
- MA200 gates entries only. References are 510300.SS, 2800.HK, SPY, BTC-USD, and GC=F by market. A blocked signal is never bought later without a new bull flip.
- The monthly observation pool is point-in-time. The frozen 2026-07-01 xquant membership is stored as a hashed fixture; later months are generated from the information available at their month-end snapshot.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/portfolio-strategies` | List all strategies |
| GET | `/api/portfolio-strategies/{id}/snapshot` | Full state snapshot |
| GET | `/api/portfolio-strategies/{id}/target-weights` | Latest target weights |
| GET | `/api/portfolio-strategies/{id}/rebalance-diff` | Current vs target delta |
| GET | `/api/portfolio-strategies/{id}/ledger?limit=&cursor=` | Paginated events |
| GET | `/api/portfolio-strategies/{id}/nav?start=&end=` | NAV history |
| GET | `/api/portfolio-strategies/daily-job-status` | Last data-update and per-strategy job status |
| POST | `/api/portfolio-strategies/{id}/activate` | Explicit cash-only first activation |
| POST | `/api/portfolio-strategies/{id}/refresh` | Refresh, calculate, reconcile |

Errors: 404 (unknown ID), 409 (comparison-only operation), 400 (invalid params).

### Snapshot operations contract

`GET .../{id}/snapshot` and `POST .../{id}/refresh` include an `operations` block used by both the frontend and OpenClaw:

- `orders`: per-symbol paper orders with signal, expected/actual execution dates, next attempt, actual Open, side, quantity/weight delta, costs, status, and delay/rejection reason.
- `bullCandidates`: policy-eligible bull flips with PIT universe context and MA200 reference price, average, decision, and reason.
- `dueOrderCount`, `waitingOpenCount`, `pendingOrderCount`: execution queue counts. A missing Open remains pending and is retried.
- `ma200AllowedCount`, `ma200BlockedCount`: entry-gate counts; a block does not schedule a later catch-up buy.
- `grossExposure`: current non-cash exposure.
- `benchmark`: normalized NAV and return difference against `risk_parity_core_next_open`.
- `dataQualityEventCount`: append-only correction/data-quality audit count.

The strategy list also exposes `presentationGroup`, `isPrimary`, `benchmarkStrategyId`, `activationDate`, and `accountOrigin`. Daily surfaces expand only the four primary strategies; comparison strategies remain in the comparison area.

### Explicit activation

Activation is a deliberate operator action and is never called by startup, refresh, the scheduler, or the read-only Skill.

```bash
# Example only. Do not run until the paper start date has been approved.
curl -X POST http://127.0.0.1:8000/api/portfolio-strategies/risk_parity_core_next_open/activate \
  -H 'Content-Type: application/json' \
  -d '{"activationDate":"YYYY-MM-DD"}'
```

Calling activation again with the same date is idempotent. A different date is rejected. A new account contains cash and an activation-date NAV only; signals on or before activation are ignored. Existing legacy Theme Alpha or BTC accounts are returned unchanged and identified as `legacy_preexisting` when no activation record exists.

## Database

Path: `backend/backtest_results/portfolio_paper.sqlite`

Legacy next-close tables remain unchanged: `paper_accounts`, `signal_snapshots`, `signal_weights`, `rebalance_events`, `paper_trades`, `position_snapshots`, `nav_snapshots`, `data_quality_events`.

Next-open event tables are additive: `strategy_activations`, `universe_snapshots`, `universe_memberships`, `decision_runs`, `decision_items`, `paper_orders`, `paper_order_attempts`, `paper_executions`, `sleeve_transfer_events`, `portfolio_positions_v2`, `portfolio_nav_v2`, `data_quality_events_v2`.

WAL mode, foreign keys, busy timeout 5s. `BEGIN IMMEDIATE` for writes. Idempotent by uniqueness constraints.

## Execution Semantics

- **Next-close**: Signal at close of date D, executes at next ETF session close
- **Next-open core**: Signal at common core Close D, executes only when all three core ETFs have a later finite positive Open
- **Next-open satellite**: Each symbol has its own expected and actual execution date; one signal batch can execute on different dates
- **Per-symbol signal cursor**: `BULL_DAILY:{symbol}` decisions advance only on that symbol's completed sessions. Held positions catch up every unprocessed session and stop at the first complete ST 7/3 bearish date
- **Missing Open**: Keep the original expected date, append a delay attempt, and retry at the next valid Open; Close is never substituted
- **Append-only correction audit**: The first decision remains authoritative. Corrected inputs append a revision and data-quality event instead of overwriting history
- **Activation**: Creates cash only and no historical signals, positions, trades, or costs
- **Threshold**: Turnover below threshold → skipped (no trades, still values positions)
- **Max trade**: Theme Alpha clips per-asset deltas to 15%
- **Blocked data**: Returns diagnostics, preserves last valid signal, no silent trades

## Limitations

- BTC-USD is a synthetic return proxy — no CNY/USD conversion modeled
- No broker connectivity or automatic orders
- No backfilled historical paper trades
- Fractional paper units allowed
- Yahoo Finance data quality and corrections apply
- No intraday broker feed. A market's Open is booked once its completed daily bar is available; before then the order remains pending rather than being falsely delayed

## Daily Refresh

The maintained runner updates data, refreshes all four primary strategies independently, then renders the read-only OpenClaw report:

```bash
scripts/run_portfolio_daily.sh
```

It writes `backend/backtest_results/portfolio_daily_job_status.json` and `openclaw_portfolio_daily.md`. A strategy failure is recorded and does not stop the remaining strategies. File locks prevent overlapping runners and overlapping refreshes of one account.

Recommended `Asia/Shanghai` schedule:

- `16:40`: first pass after A-share/HK daily bars should be complete. US, gold, and UTC crypto keep their own latest completed dates and may remain pending.
- `07:15`: second/full pass after the prior US session and data providers have settled; generate the official daily report after this pass.
- If a market is not complete or is stale, do not synthesize a signal. The status/API and report show it as waiting/stale; a later rerun processes its next completed bar. Core staleness blocks only core rebalancing, not an independently completed satellite market.

Example cron entries:

```cron
CRON_TZ=Asia/Shanghai
40 16 * * 1-5 /home/zsd/trading/scripts/run_portfolio_daily.sh >> /home/zsd/trading/backend/backtest_results/portfolio_daily.log 2>&1
15 7 * * * /home/zsd/trading/scripts/run_portfolio_daily.sh >> /home/zsd/trading/backend/backtest_results/portfolio_daily.log 2>&1
```

The report can also be generated independently after a successful refresh:

```bash
python scripts/openclaw_supertrend_alerts.py \
  --api-base http://127.0.0.1:8000/api \
  --mode daily-brief \
  --format markdown \
  --include-portfolio
```

The report is deterministic and order-first: due orders, orders waiting for their own market's next valid Open, bull-flip/MA200 counts, holdings/cash/exposure, NAV/drawdown/relative RiskParity, then anomalies. It does not authorize the agent to modify a signal, parameter, allocation, or provide an out-of-rule trade recommendation.

### Activation checklist

Before calling any activation endpoint:

1. Confirm the approved start date and Shanghai calendar date.
2. Back up `portfolio_paper.sqlite` and verify the persistent volume points to `backend/backtest_results`.
3. Record current account, activation, trade, execution, and NAV row counts.
4. Confirm whether Theme Alpha/BTC are genuine legacy accounts. If absent, label them first activations; never imply historical continuation.
5. Confirm all four strategy versions/config hashes and the frozen PIT fixture hash.
6. Activate each approved account once, then verify cash-only NAV and zero new orders/executions.
7. Run the daily job only after activation and verify the status JSON before enabling cron.

### OpenClaw skill

The versioned skill source is `.agents/skills/portfolio-daily-brief/`. Install it in the OpenClaw workspace or managed skill root and start a new OpenClaw session if the skill watcher has not refreshed. Invoke it with:

```text
/portfolio-daily-brief
```

or ask “查看今天组合日报”“有没有等待 Open 的订单”“哪些 bull flip 被 MA200 拦截”。 The skill is intentionally read-only and never calls the portfolio refresh endpoint.

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
  tests/test_portfolio_paper_engine.py \
  tests/test_next_open_engine.py \
  tests/test_next_open_service.py \
  tests/test_xquant_next_open_parity.py \
  tests/test_openclaw_supertrend_alerts.py -q

# Frontend build
cd frontend && ./node_modules/.bin/tsc -b && ./node_modules/.bin/vite build
```
