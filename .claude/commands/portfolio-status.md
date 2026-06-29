# /portfolio-status — Portfolio Strategy Health Check

Check the status of all paper-tracked portfolio strategies.

**Steps:**
1. Run: `uv run python scripts/trading_analysis_helper.py --api-base http://8.153.71.148/api --query portfolio`
2. For each strategy, report:
   - Current NAV, cumulative return, max drawdown, today's return
   - Current allocations (which assets, what weights)
   - Any pending rebalances
   - Signal status and next check date
   - Overall state (READY / NOT_DUE / BLOCKED / BOOTSTRAPPED)
3. Flag any issues:
   - BLOCKED = data problem, needs investigation
   - PENDING_EXECUTION = rebalance waiting for next close
   - Large drawdowns
4. Run the NAV series to show recent trend if requested

**Strategy reference:**
- BTC SuperTrend Satellite: RiskParity core (沪深300/纳指100/黄金) + BTC satellite (0-7.5%)
- Theme Alpha: Core80 / LVT20 / Def200 Cash with bimonthly rotation
