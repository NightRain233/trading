# Portfolio Daily Brief API

Use one API base for an entire answer.

## Requests

```text
GET {apiBase}/portfolio-strategies
GET {apiBase}/portfolio-strategies/daily-job-status
GET {apiBase}/portfolio-strategies/{strategyId}/snapshot
GET {apiBase}/portfolio-strategies/{strategyId}/nav
```

This skill must not call:

```text
POST {apiBase}/portfolio-strategies/{strategyId}/refresh
POST {apiBase}/portfolio-strategies/{strategyId}/activate
```

## Strategy selection

From the list response, expand records where `isPrimary=true`. Preserve the frozen order in `SKILL.md`. Use `presentationGroup=comparison` only for a user-requested comparison. `paperEnabled=false` means there is no paper account to refresh or present as a live paper portfolio.

## Snapshot fields

Read `operations` first:

- `asOfDate`: report cutoff.
- `orders`: per-symbol order state.
- `dueOrderCount`: orders due as of the cutoff.
- `waitingOpenCount`: orders delayed or waiting for a valid Open.
- `pendingOrderCount`: all unfilled orders.
- `bullCandidates`: policy-eligible bull-flip decisions recorded for the latest signal date.
- `ma200AllowedCount`, `ma200BlockedCount`: new-entry gate results.
- `grossExposure`: non-cash exposure.
- `benchmark.relativeReturn`: strategy return minus normalized RiskParity return.
- `dataQualityEventCount`: append-only audit-event count, not automatically an unresolved current incident.

For each order preserve:

- `signalDate`
- `expectedExecutionDate`
- `nextAttemptDate`
- `actualExecutionDate`
- `actualOpen`
- `side`
- `requestedWeightDelta` and `quantityDelta`
- `commission` and `slippage`
- `status`, `delayReason`, and `rejectionReason`
- `due`

Use `currentWeights` for holdings and sleeve attribution. Use `nav` for cash, NAV, return, and drawdown. Use `diagnostics` and `calcError` for current problems. Use `dates.marketDataDate` and `dates.signalDate` to make staleness visible.

## State interpretation

- `PENDING_EXECUTION`: an order exists but has not filled.
- `BLOCKED`: required data or calculation is preventing normal progression.
- `EMPTY`: no activated/current paper state; not equivalent to zero exposure after a valid run.
- `READY` or `NOT_DUE`: no strategy-level block; still inspect individual orders.

An empty `orders` array is “no recorded orders” only when the snapshot request succeeded. A failed request is “unavailable”.

## Daily job status

- `dataUpdate.ok=false`: the run continued from cached data; do not claim all markets are current.
- `marketReadiness.{market}.ready=false`: that market's expected completed bar was not confirmed.
- `strategies.{strategyId}.ok=false`: report that refresh failure independently; other successful strategies remain valid.
- `strategies.{strategyId}.notActivated=true`: distinguish an inactive account from an activated all-cash portfolio.
