# Portfolio Strategies Paper Tracking Design

## Status

Approved for implementation on 2026-06-28.

The implementation baseline is trading commit `114c897b16bf764b7cd58129dabfc8959146d339`.
The frozen xquant research/export reference is commit
`1d1b36e0fd22239767d3e2293f750ce7a01ffb61`.

## Objective

Migrate two validated xquant candidates into trading as independent, runtime-safe
portfolio strategies with:

- latest complete-close signal calculation;
- explicit target weights and rebalance differences;
- a persistent, idempotent SQLite paper ledger;
- paper positions, trades, costs, NAV, cumulative return, and max drawdown;
- a new portfolio-strategies tab with a nine-panel summary;
- no broker integration and no automatic order placement.

xquant remains read-only and is used only to define rules and record compact
decision-provenance snapshots. Production trading code and tests must not read
the xquant repository.

## Scope Decisions

### Migration architecture

Implement the rules in a pure strategy package inside trading. Do not read
xquant exports at runtime and do not create a shared package between the two
repositories.

### Execution convention

Official paper trades use `next-close`: a signal is calculated after the close
of signal date D and is simulated at the closing price of the next valid ETF
trading session. Same-close execution is forbidden. BTC next-open may be shown
later as comparison metadata but is not a second official ledger.

### Frontend navigation

Add an independent `PortfolioStrategiesPage` through the existing lightweight
tab/path mechanism, with a stable `/portfolio-strategies` path. A full
React-Router migration is explicitly out of scope and will be handled as a
separate follow-up.

### Indicator reuse

Use pandas/pandas-ta for generic operations such as returns, rolling averages,
true range, and standard deviation. Preserve the xquant SuperTrend state
transition semantics in a small internal helper because pandas-ta's configured
SMA implementation does not produce identical historical directions.

The existing trading SuperTrend screens remain unchanged.

## Strategy Registry

Every strategy definition is immutable and includes:

- `strategy_id`;
- `strategy_version`;
- display name and description;
- asset universe and aliases;
- schedule and schedule anchor;
- indicator and allocator parameters;
- execution convention;
- rebalance thresholds and per-asset trade caps;
- cost model;
- official paper/comparison-only status.

### BTC SuperTrend Satellite

Official paper strategy:

- ID: `btc_supertrend_satellite`;
- version: `1.0.0`;
- core: `510300.SS`, `513100.SS`, `518880.SS`;
- satellite: `BTC-USD`;
- core allocator: inverse 20-session volatility RiskParity;
- BTC cap: 7.5%;
- BTC trend: ATR 10, SMA true-range average, multiplier 3;
- when BTC is off, its 7.5% target becomes cash;
- formal check every 10 common ETF trading sessions using the frozen research
  anchor;
- 1% target-change threshold, while a BTC switch change must be recorded;
- 20 bps transaction cost plus 10 bps slippage assumption.

The 5% and 10% variants remain registry comparison candidates. They may expose
calculated targets but never create paper accounts, trades, or NAV in phase one.

### Theme Alpha

Official paper strategy:

- ID: `theme_alpha`;
- version: `1.0.0`;
- core: `510300.SS`, `513100.SS`, `518880.SS`;
- expanded LVT universe:
  `513100.SS`, `512400.SS`, `159995.SZ`, `515880.SS`, `518880.SS`,
  `510880.SS`, `159930.SZ`, `512880.SS`, `513180.SS`, `512170.SS`;
- 80% core and 20% LVT satellite;
- formal dates near the 10th and 25th, shifted to the next valid ETF session
  within the month;
- LVT eligibility: close above MA60 and positive 63-session momentum;
- choose the three eligible assets with lowest 60-session volatility;
- LVT allocation: inverse 20-session volatility RiskParity, 50% single-asset
  cap inside the sleeve;
- core defense: independently move the CSI300 or Nasdaq core allocation to cash
  when that asset is not above MA200;
- 2% portfolio turnover threshold;
- 15% maximum absolute target change per asset per rebalance;
- 20 bps base one-way cost plus xquant's 5/10/20 bps asset friction ladder.

## Backend Architecture

Create `backend/portfolio_strategies/` with the following responsibilities:

- `models.py`: immutable configs, market-data diagnostics, signals, targets,
  rebalance decisions, and paper-ledger response models;
- `registry.py`: the two official strategies and BTC comparison variants;
- `indicators.py`: deterministic SuperTrend direction, capped inverse-volatility
  allocation, and LVT selection;
- `schedules.py`: 10-session and fixed bimonthly schedules;
- `market_data.py`: Parquet loading, refresh integration, complete-close
  validation, and common-session construction;
- `btc_satellite.py` and `theme_alpha.py`: side-effect-free strategy functions;
- `ledger.py`: SQLite schema, transactions, idempotent writes, positions, trades,
  and NAV;
- `service.py`: refresh, validation, calculation, bootstrap, execution, and API
  orchestration.

`backend/main.py` exposes thin FastAPI adapters only. Strategy calculations and
ledger SQL must not be embedded in endpoint functions.

## Market Data and Freshness Rules

The data adapter reuses trading's existing symbol locks, global yfinance
download lock, Parquet retention, and refresh functions.

An official signal is allowed only when:

- all required symbols have enough history;
- OHLC rows are complete and finite;
- the signal session is a completed market close, not an in-progress daily bar;
- all ETF assets agree on the applicable ETF session;
- no required asset has a recent unexplained gap;
- the BTC daily bar used by the BTC strategy is complete under its UTC daily
  cutoff;
- data is not stale relative to the strategy calendar.

Theme Alpha must not forward-fill a missing official ETF close. BTC is sampled
onto the ETF decision calendar only after its corresponding daily bar is
complete.

Validation failures produce structured diagnostics and preserve the last valid
official signal. They never silently generate a signal, trade, or NAV update.

The API distinguishes:

- current observation state;
- last formal signal state;
- pending next-close execution;
- last completed execution.

This prevents an intraperiod BTC trend observation from being mistaken for a
formal 10-session target change.

## Data Flow

1. A scheduled job or explicit refresh requests the fixed strategy universe.
2. Existing refresh infrastructure updates Parquet files under normal locks.
3. The strategy data adapter constructs a strict completed-close snapshot.
4. The pure strategy calculates observations and, when due, a formal target.
5. The service inserts the signal and target weights idempotently.
6. A signal remains pending until the next complete ETF close is available.
7. The ledger applies threshold/cap rules, records simulated next-close trades
   and costs once, and updates positions atomically.
8. Complete valuation sessions append NAV snapshots.
9. Read APIs return the latest materialized snapshot, history, and diagnostics.

GET endpoints never create paper trades. Ledger mutations happen only through
the refresh/reconcile service.

## Bootstrap Semantics

The first successful run creates one account per official strategy and records:

- the most recent valid formal strategy target;
- a position snapshot at the latest complete valuation close;
- `origin = bootstrap`;
- initial NAV and cash configuration.

Bootstrap creates no historical paper trades, charges no invented historical
cost, and produces no pre-bootstrap NAV history. Subsequent formal signals and
next-close executions form the real paper ledger.

The bootstrap valuation date and originating formal signal date are stored
separately.

## SQLite Ledger

Database path:

`backend/backtest_results/portfolio_paper.sqlite`

Tables:

- `paper_accounts`: strategy/version identity, initial NAV, base currency,
  bootstrap metadata;
- `signal_snapshots`: formal signal date, market-data date, origin, state,
  reason, config hash, and input hash;
- `signal_weights`: normalized desired target per signal and symbol;
- `rebalance_events`: pending/executed/skipped event, execution date, turnover,
  cost, and reason;
- `paper_trades`: symbol, side, price, weight delta, gross notional, fees, and
  slippage;
- `position_snapshots`: valuation-date symbol quantity/notional, price, value,
  and weight;
- `nav_snapshots`: gross NAV, net NAV, cash, daily return, cumulative return,
  drawdown, and running maximum;
- `data_quality_events`: blocked refresh diagnostics without an official signal.

Required uniqueness:

- `(strategy_id, strategy_version)` on accounts;
- `(strategy_id, strategy_version, signal_date)` on signals;
- one rebalance event per signal;
- `(rebalance_event_id, symbol)` on trades;
- `(account_id, valuation_date, symbol)` on positions;
- `(account_id, valuation_date)` on NAV.

SQLite uses foreign keys, WAL mode, `busy_timeout`, and `BEGIN IMMEDIATE`.
Database uniqueness is authoritative across the two uvicorn workers; process
locks are not sufficient.

## API Contract

- `GET /api/portfolio-strategies`
  returns registry entries, official/comparison mode, versions, and summary
  status.
- `GET /api/portfolio-strategies/{strategy_id}/snapshot`
  returns dates, freshness, observation, formal signal, current/desired/
  executable weights, paper metrics, latest rebalance, and next check.
- `GET /api/portfolio-strategies/{strategy_id}/target-weights`
  returns the latest formal desired and executable targets.
- `GET /api/portfolio-strategies/{strategy_id}/rebalance-diff`
  returns current versus target weights and threshold/cap effects.
- `GET /api/portfolio-strategies/{strategy_id}/ledger`
  returns paginated bootstrap, signal, rebalance, and trade events.
- `GET /api/portfolio-strategies/{strategy_id}/nav`
  returns valuation-date NAV and drawdown points.
- `POST /api/portfolio-strategies/{strategy_id}/refresh`
  refreshes the fixed universe, validates data, reconciles pending work, and
  returns the resulting snapshot.

Unknown strategy IDs return 404. Comparison-only variants reject ledger and
refresh operations that would create an account.

## Frontend

Add a lazily loaded `PortfolioStrategiesPage` and a `组合` header tab.
`/portfolio-strategies` is handled by the current pathname mapping without
introducing React Router.

The page includes a strategy selector and nine summary panels:

1. market-data, signal, and execution dates;
2. data freshness and blocking diagnostics;
3. formal signal state and reasons;
4. current paper holdings;
5. desired and executable target weights;
6. rebalance differences;
7. NAV, cumulative return, and max drawdown;
8. latest rebalance, trades, and costs;
9. next check and pending-execution state.

Theme Alpha's full universe is shown in an expandable asset table because it
contains more than nine assets. Each row includes sleeve, observation state,
current weight, desired weight, executable weight, delta, reason, and freshness.

The page is responsive as one column on small screens and a three-column grid on
large screens. Blocked/stale data is visually dominant and cannot look like a
tradable signal.

The page focuses on the latest paper positions and ledger activity created
after bootstrap. It does not import or display xquant's historical NAV as
trading paper performance.

## Error Handling

Expected public states include:

- `READY`;
- `NOT_DUE`;
- `PENDING_EXECUTION`;
- `EXECUTED`;
- `BOOTSTRAPPED`;
- `BLOCKED_MISSING_DATA`;
- `BLOCKED_INCOMPLETE_CLOSE`;
- `BLOCKED_STALE_DATA`;
- `BLOCKED_SESSION_MISMATCH`;
- `BLOCKED_INSUFFICIENT_HISTORY`.

Refresh failures return the last valid snapshot plus diagnostics where possible.
They do not erase prior signals or positions. SQL transactions roll back the
entire execution if any trade, position, or NAV write fails.

## Testing

### xquant decision-provenance fixtures

Commit compact JSON decision snapshots under
`backend/tests/fixtures/portfolio_strategies/`. Each fixture records:

- xquant commit;
- export date;
- source notebook/output paths;
- strategy parameters;
- signal date and market-data date;
- expected signal state and target weights.

Do not commit the 114-session BTC or 217-session Theme Alpha historical market
frames. Pure strategy tests use deterministic synthetic frames; production
calculations use trading's existing Parquet cache after the normal refresh and
complete-close validation flow. Tests must prove that no xquant path or frozen
historical payload is required.

### Backend unit tests

- SuperTrend warmup, line state, and direction versus xquant fixture;
- inverse-volatility RiskParity and cap redistribution;
- 10-session anchored schedule;
- bimonthly holiday/weekend shift;
- MA60/63-day momentum/low-vol Top3;
- independent MA200 core defense;
- threshold and max-trade behavior;
- complete-close and stale/gap/session mismatch rejection.

### Ledger tests

- bootstrap produces positions but no historical trades;
- next-close pending event executes only after the next complete close;
- repeat refresh creates no duplicate signal, rebalance, trade, position, or NAV;
- concurrent repository instances respect uniqueness;
- transaction rollback leaves no partial trade set;
- restart resumes pending execution.

### API and frontend tests

- endpoint models and error codes;
- comparison-only restrictions;
- frontend parsing and status mapping;
- nine-panel loading, blocked, bootstrap, pending, and executed states;
- stable `/portfolio-strategies` refresh/deep link;
- frontend production build.

### Final verification

- all backend pytest tests;
- all frontend Node tests;
- TypeScript production build;
- explicit fixture regression command;
- repository runtime scan proving no xquant path dependency.

## Out of Scope

- broker connectivity or automatic orders;
- parameter optimization;
- additional trading research candidates;
- backfilled historical paper trades;
- multiple official BTC-cap ledgers;
- a second next-open official ledger;
- full frontend router migration;
- FX conversion or claims that `BTC-USD` is a directly investable CNY product.

BTC remains a synthetic return proxy in phase one, and this limitation is
displayed in the UI and final risk notes.
