---
name: portfolio-daily-brief
description: View the deterministic daily paper-portfolio brief or a portfolio health check for the primary three-asset + BTC 7.5% satellite, including rebalance status, holdings, NAV, drawdown, the BTC daily SuperTrend switch, audit issues, and a one-line SuperTrend study scan. Read-only; do not use it to change strategy state.
---

# Portfolio Daily Brief

Generate or explain the trading project's daily paper-execution brief from the backend API. Treat API output as authoritative strategy state. This skill is read-only: do not call refresh endpoints, create orders, alter parameters, or infer discretionary trades.

## Choose the source

Prefer `http://127.0.0.1:8000/api` when the local backend is available. Use the production API (from the `TRADING_API_BASE` environment variable; never write the server address into the repository) only when the user asks for production data or the current OpenClaw deployment is configured to use it. State which source and `asOfDate` were used. Never combine local and production responses in one report.

If neither source is reachable, report that the daily brief is unavailable. Do not turn a connection failure into “no orders”.

## Full daily brief

When the project checkout and script are available, reuse the maintained renderer instead of composing a second implementation:

```bash
python3 scripts/openclaw_supertrend_alerts.py \
  --api-base http://127.0.0.1:8000/api \
  --mode daily-brief \
  --format markdown \
  --include-portfolio
```

Run it from the trading repository root. Substitute the configured production API base only under the source rule above. The script reads data and the latest daily-job status; it does not refresh or activate portfolios.

For a focused question, query the API directly. Read [references/api-contract.md](references/api-contract.md) before constructing direct requests or interpreting fields.

## Reporting rules

Expand only the primary portfolio: `btc_supertrend_satellite` (three-asset
inverse-volatility core plus a BTC 7.5% daily SuperTrend satellite). Keep
Core90 + MA200 Bull10, RiskParity, and Theme Alpha collapsed as forward
comparisons unless the user explicitly asks to compare them.

Report in this order:

1. Whether a rebalance is pending (signal date) or the next check date.
2. Current holdings, cash, NAV, and drawdown.
3. BTC daily SuperTrend: latest direction, distance to the ST line, and the
   formal switch from the last check (`observation.values.supertrend_on` and
   `formal_supertrend_on`). If they differ, say the flip executes at the next
   check, not that it already traded.
4. Active diagnostics, calculation errors, and data-quality audit events.
5. One line for the SuperTrend study scan: counts only, unless high priority.

Before stating that data is current, inspect `GET /portfolio-strategies/daily-job-status`. Report a failed strategy independently and identify markets whose completed daily bar was not confirmed. An inactive account is not the same as an activated all-cash account.

Do not describe a pending order as filled. For next-open strategies, a missing Open means delayed, never replaced with Close or silently cancelled. Different markets can execute on different dates. MA200 blocks only a new entry; it does not liquidate an existing holding or authorize a later catch-up purchase.

Theme Alpha and BTC 7.5% retain their existing accounts and next-close ledgers. Do not imply that they were re-bootstrapped or merged with the next-open accounts.

Keep comparison strategies collapsed unless the user explicitly asks for comparisons. `core90_ma200_bull10` and `core90_raw_bull10` keep their own forward paper ledgers, but they remain comparisons and are not primary daily candidates.

Explain deterministic output only. Do not change signals, parameters, allocations, or give a trade recommendation outside the frozen rules.

## Health check (formerly portfolio-status)

When the user asks how the portfolio accounts are doing rather than for today's brief:

```bash
uv run python scripts/trading_analysis_helper.py --query portfolio --timeout 120
```

Report the primary account first (NAV, cumulative return, drawdown, current vs desired weights, open orders, next check, state). Then one line per comparison account. Flag `BLOCKED` (data problem), pending orders (describe by the strategy's own execution price, not "filled"), and drawdowns beyond -15% (the backtest's worst was about -13%). Answer in plain Chinese; see [../shared/market-rules.md](../shared/market-rules.md) for the boundaries.
