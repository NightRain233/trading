# xquant Frozen Strategy Next-Open Paper Engine

## Boundary

This implementation imports no runtime code from xquant and does not backfill paper trades. xquant is a read-only research source. Frozen parameters, source hashes, selected golden outputs, and the latest research membership snapshot are copied into versioned fixtures under `backend/portfolio_strategies/fixtures/` and `backend/tests/fixtures/portfolio_strategies/`.

Theme Alpha and BTC 7.5% continue to use the legacy next-close engine and legacy ledger tables. New strategies share the same API surface but use an additive event ledger. Creating or refreshing a new account never bootstraps, deletes, or updates old strategy rows.

## Decision and Execution Flow

1. Load each symbol on its own calendar and retain only completed Close bars for its market cutoff.
2. Reconcile previously pending orders first.
3. On a due common core session, freeze the 20-return inverse-volatility target and create three core orders.
4. For the bull sleeve, select the effective monthly PIT membership, consume the production decision stream, record all eligible and MA200-blocked candidates, and create orders only for eligible events.
5. Core orders execute together at the next common valid Open. Satellite orders execute independently at each symbol's next valid Open.
6. Missing or invalid Open data appends an order attempt and moves only the next-attempt date. The original expected date is immutable.
7. Positions, cash, NAV, decisions, orders, attempts, executions, and data-quality revisions are append-oriented and protected by deterministic unique keys.

## Cost and State Semantics

- Core turnover is computed against weights after the execution-day Open gap, not the prior Close weights.
- Quantities remain fixed between trades, so weights drift with prices.
- Core cost is 10 bps one-way on turnover.
- Core90/Bull10 sleeve budgets reset every 10 core sessions before that day's sleeve returns, with 10 bps resizing cost.
- Bull orders apply 5 bps slippage and 5 bps commission per side, matching 20 bps round trip.
- MA200 affects only new entries. Existing positions exit only after ST 7/3 is bearish, at the next valid Open.

## Operational Limitation

There is no broker or intraday Open feed. Orders are deterministic paper events and are booked after a completed daily bar makes the actual Open auditable. If that bar is not yet available, the order remains pending and is not marked delayed merely because another market has already closed.
