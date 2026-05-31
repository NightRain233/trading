# SuperTrend Signal Slimming Design

## Goal

Reduce day-to-day SuperTrend page noise without silently damaging risk-adjusted performance. A slimming rule can become the default daily view only when its five-year backtest keeps at least 85% of the baseline return/drawdown ratio, keeps at least 70% of baseline total return, and lowers trade count.

## Current Context

- `backend/supertrend_alerts.py` already classifies live scan rows into buy candidates, support tests, risk alerts, hold states, priorities, and actionable flags.
- `backend/backtest.py` currently models the baseline SuperTrend strategy as daily SuperTrend bear-to-bull flip entry, weekly SuperTrend bullish filter, and daily SuperTrend flip/line stop exit.
- `backend/strategy_comparison.py` already generates the five-year strategy comparison report and can host an additional SuperTrend slimming research section.
- `frontend/src/components/SupertrendPage.tsx` already supports several filters, but defaults to all rows and does not distinguish a research-backed daily view from full coverage.

## Slimming Layers

The research will compare these layers against the existing baseline:

- `high_priority_alerts`: weekly bullish plus daily bull flip or weekly bullish plus daily support test.
- `daily_bull_flip`: daily SuperTrend just flipped bullish, without a weekly bullish filter.
- `support_test`: daily bullish trend and price near SuperTrend support, without a weekly bullish filter.
- `weekly_bull_daily_bull_flip`: weekly bullish plus daily SuperTrend just flipped bullish.
- `weekly_bull_support_test`: weekly bullish plus daily support test.

Support test uses the same thresholds as live alerts: distance to SuperTrend is at most 1.5% of price or at most 0.5 ATR.

## Backtest Design

Add an `entry_signal_mode` parameter to `run_supertrend_backtest`. It changes only entry eligibility. Position management remains the same across baseline and variants:

- Exit when daily SuperTrend turns bearish or the daily low touches the current SuperTrend line.
- Keep existing fee, slippage, max-position, and mark-to-market portfolio assumptions.
- Avoid repeat support-test entries while already in a position.

`strategyVersion` should include the selected entry mode so summaries and trade exports remain auditable.

## Report Design

Extend `strategy_comparison.py` with `supertrendSlimmingRows`. Each row should include:

- Asset group.
- Baseline total return, max drawdown, return/drawdown ratio, trade count, win rate, and average holding days.
- Variant total return, max drawdown, return/drawdown ratio, trade count, win rate, and average holding days.
- Total-return retention vs baseline.
- Return/drawdown-ratio retention vs baseline.
- Trade-count reduction vs baseline.
- `passesSlimmingGate`.

The markdown report should include a "SuperTrend 精简层研究" section with a compact table and a clear pass/fail judgment.

## Frontend Design

After the backtest is available, run the local five-year report:

```bash
cd backend
PYTHONPATH=. uv run --python 3.12 python strategy_comparison.py --format json
```

If at least one rule passes the slimming gate:

- Default the page to the best passing daily mode.
- Keep a visible "日常精简 / 全量扫描" switch.
- Preserve all existing filters so the full scan remains available.

If no rule passes the gate:

- Keep full scan coverage.
- Improve the page with UI layering: highlight high-priority/current actionable groups first and fold low-priority observations behind a quieter control.

## Testing

- Add focused unit tests for each new entry mode behavior in `backend/tests/test_backtest.py`.
- Add report-format tests in `backend/tests/test_strategy_comparison.py`.
- Run focused backend tests first, then the strategy report command.
- Run frontend type/build checks after changing `SupertrendPage.tsx`.

## Known Baseline Caveat

On the isolated worktree, the broader `backend/tests/test_backtest.py` suite currently has four unrelated resonance-strategy failures. SuperTrend-specific tests and report tests should be used as the primary red/green signal for this change, and the final report should mention the pre-existing failures.
