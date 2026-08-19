---
name: portfolio-daily-brief
description: View the deterministic daily paper-portfolio brief, including due orders, orders waiting for Open, bull flips, MA200 gates, holdings, NAV, benchmark differences, and audit issues. Read-only; do not use it to change strategy state.
---

# Portfolio Daily Brief

Generate or explain the trading project's daily paper-execution brief from the backend API. Treat API output as authoritative strategy state. This skill is read-only: do not call refresh endpoints, create orders, alter parameters, or infer discretionary trades.

## Choose the source

Prefer `http://127.0.0.1:8000/api` when the local backend is available. If it is unavailable, use `http://8.153.71.148/api` only when the user asks for production data or the current OpenClaw deployment is configured to use that server. State which source and `asOfDate` were used. Never combine local and production responses in one report.

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

Run it from the trading repository root. Substitute the configured production API base only under the source rule above. The script reads data; it does not refresh portfolios.

For a focused question, query the API directly. Read [references/api-contract.md](references/api-contract.md) before constructing direct requests or interpreting fields.

## Reporting rules

Expand exactly these four primary portfolios in this order:

1. `risk_parity_core_next_open`
2. `core90_ma200_bull10`
3. `theme_alpha`
4. `btc_supertrend_satellite`

Report in this order:

1. Orders due today.
2. Pending or delayed orders waiting for each symbol's next valid Open.
3. Today's policy-eligible bull flips and MA200 allowed/blocked counts.
4. Current holdings, cash, and gross exposure.
5. NAV, drawdown, and difference versus RiskParity.
6. Active diagnostics, calculation errors, and data-quality audit events.

Do not describe a pending order as filled. For next-open strategies, a missing Open means delayed, never replaced with Close or silently cancelled. Different markets can execute on different dates. MA200 blocks only a new entry; it does not liquidate an existing holding or authorize a later catch-up purchase.

Theme Alpha and BTC 7.5% retain their existing accounts and next-close ledgers. Do not imply that they were re-bootstrapped or merged with the next-open accounts.

Keep comparison strategies collapsed unless the user explicitly asks for comparisons. `core90_raw_bull10` is comparison-only and is not an official daily candidate.

Explain deterministic output only. Do not change signals, parameters, allocations, or give a trade recommendation outside the frozen rules.
