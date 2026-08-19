---
name: portfolio-status
description: Use when the user asks to check paper-tracked portfolio strategy health, NAV, allocations, pending rebalances, drawdowns, or execution state.
---

# /portfolio-status — Portfolio Strategy Health Check

Check the status of all paper-tracked portfolio strategies.

For a daily order-first report, waiting-Open queue, bull-flip candidates, or MA200 gate results, use the dedicated `portfolio-daily-brief` skill instead.

**Steps:**
1. Run: `uv run python scripts/trading_analysis_helper.py --api-base http://8.153.71.148/api --query portfolio`
2. For each strategy, report:
   - Current NAV, cumulative return, max drawdown, today's return
   - Current allocations (which assets, what weights)
   - Any pending per-symbol orders or legacy rebalances
   - Signal status and next check date
   - Overall state (READY / NOT_DUE / BLOCKED / BOOTSTRAPPED)
3. Flag any issues:
   - BLOCKED = data problem, needs investigation
   - PENDING_EXECUTION = an order is waiting for its strategy's defined execution price; inspect `operations.orders` before describing next Open or next Close
   - Large drawdowns
4. Run the NAV series to show recent trend if requested

**Primary strategy reference:**
- RiskParity Core: frozen three-ETF next-open benchmark
- Core90 + MA200 Bull10: next-open core plus per-market bull-flip orders
- Theme Alpha: existing Core80 / LVT20 / Def200 Cash account
- BTC SuperTrend Satellite: existing 7.5% satellite account
