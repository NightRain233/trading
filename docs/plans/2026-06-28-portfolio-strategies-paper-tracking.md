# Portfolio Strategies Paper Tracking Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add two xquant-compatible portfolio strategies to trading with strict complete-close signals, target weights, an idempotent SQLite next-close paper ledger, APIs, and a nine-panel frontend page.

**Architecture:** Build a side-effect-free `portfolio_strategies` package behind a service layer. The service reuses existing Parquet refresh facilities, blocks invalid data, persists official signals and simulated next-close activity in SQLite, and exposes thin FastAPI endpoints. The frontend adds one lazy page through the existing tab/path mechanism; a full router migration remains separate.

**Tech Stack:** Python 3.12, FastAPI, pandas, pandas-ta, exchange-calendars, SQLite, pytest, React 19, TypeScript, Vite, Node test runner.

---

## Preconditions

- Work only on branch `codex/portfolio-strategies-paper-tracking`.
- Treat `/Users/zz/Desktop/Code/zsd/xquant` as read-only.
- Use xquant commit `1d1b36e0fd22239767d3e2293f750ce7a01ffb61` for fixture metadata.
- Never import from or open the xquant path at trading runtime or during normal tests.
- Official paper execution is next-close.
- Only BTC 7.5% and Theme Alpha create paper accounts.
- Keep the frontend router refactor out of this implementation.

### Task 1: Stabilize the existing baseline test

**Files:**

- Modify: `backend/tests/test_supertrend_scan.py`

**Step 1: Reproduce the existing failure**

Run:

```bash
cd backend
uv run pytest tests/test_supertrend_scan.py::test_supertrend_scan_returns_data_freshness_metadata -q
```

Expected: FAIL because the fixture ends at 2026-06-02 while the production
freshness function uses the real current date.

**Step 2: Make the test clock-independent**

Change the fixture index so its final row is based on
`datetime.now(main.PREWARM_TZ).date()`, retaining three ordered business-date
rows. Keep the assertions unchanged so the test still proves that a current,
gap-free frame is fresh.

Do not relax production freshness behavior.

**Step 3: Verify the focused and full baseline**

Run:

```bash
uv run pytest tests/test_supertrend_scan.py::test_supertrend_scan_returns_data_freshness_metadata -q
uv run pytest -q
```

Expected: focused test passes; full suite has no failures and retains the
existing environment-dependent skips.

**Step 4: Commit**

```bash
git add backend/tests/test_supertrend_scan.py
git commit -m "test: make SuperTrend freshness fixture time independent"
```

### Task 2: Add the package skeleton, calendar dependency, models, and registry

**Files:**

- Modify: `backend/pyproject.toml`
- Modify: `backend/uv.lock`
- Create: `backend/portfolio_strategies/__init__.py`
- Create: `backend/portfolio_strategies/models.py`
- Create: `backend/portfolio_strategies/registry.py`
- Test: `backend/tests/test_portfolio_strategy_registry.py`

**Step 1: Write registry tests**

Cover:

- official IDs are `btc_supertrend_satellite` and `theme_alpha`;
- BTC official cap is 0.075 and comparison caps are 0.05 and 0.10;
- BTC parameters are ATR10/SMA/multiplier3, RP window20, and 10 sessions;
- Theme Alpha is Core80/LVT20, MA60, momentum63, volatility60, Top3,
  RP window20, cap0.50, defense MA200;
- both official accounts use `next_close`;
- Theme Alpha threshold is 0.02 and max per-asset trade is 0.15;
- comparison variants reject official-ledger lookup.

Use immutable dataclasses or frozen Pydantic models. A representative assertion:

```python
def test_btc_official_registry_configuration():
    config = get_strategy("btc_supertrend_satellite")
    assert config.version == "1.0.0"
    assert config.paper_enabled is True
    assert config.params["btc_cap"] == 0.075
    assert config.execution == "next_close"
```

**Step 2: Run the tests and verify failure**

```bash
cd backend
uv run pytest tests/test_portfolio_strategy_registry.py -q
```

Expected: FAIL because the package does not exist.

**Step 3: Add the dependency and lock it**

Add `exchange-calendars` to `backend/pyproject.toml`, then run:

```bash
uv lock
uv sync
```

Use the installed XSHG calendar only to identify expected exchange sessions and
future check dates. Formal signals still require observed complete Parquet rows.

**Step 4: Implement minimal immutable models and registry**

Define:

- `StrategyMode`: `paper` or `comparison`;
- `ExecutionMode`: `next_close`;
- `AssetConfig`;
- `StrategyConfig`;
- `CostConfig`;
- `DataDiagnostic`;
- `StrategyObservation`;
- `TargetWeight`;
- `StrategyCalculation`.

Keep numeric parameters explicit in registry construction, not hidden in module
constants.

Use `initial_nav=100_000.0` and `base_currency="CNY"` for official paper
accounts. Mark BTC as a synthetic USD return proxy in its asset metadata.

**Step 5: Run tests**

```bash
uv run pytest tests/test_portfolio_strategy_registry.py -q
```

Expected: PASS.

**Step 6: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/portfolio_strategies backend/tests/test_portfolio_strategy_registry.py
git commit -m "feat: add portfolio strategy registry"
```

### Task 3: Implement deterministic indicator and allocation primitives

**Files:**

- Create: `backend/portfolio_strategies/indicators.py`
- Test: `backend/tests/test_portfolio_strategy_indicators.py`
- Create: `backend/tests/fixtures/portfolio_strategies/xquant_indicator_cases.json`

**Step 1: Create frozen indicator cases**

Copy only compact input/output cases derived from xquant's read-only
`src/xquant/indicators.py` tests and strategy rules. Include metadata:

```json
{
  "sourceRepository": "xquant",
  "sourceCommit": "1d1b36e0fd22239767d3e2293f750ce7a01ffb61",
  "sourceFiles": [
    "src/xquant/indicators.py",
    "research/notebooks/q10-live-readiness-stress-practice.ipynb"
  ],
  "atrWindow": 10,
  "atrMode": "sma",
  "multiplier": 3.0
}
```

Do not add generated notebook content or import xquant.

**Step 2: Write failing tests**

Test:

- true range includes overnight gaps;
- SuperTrend stays false through warmup;
- every frozen direction matches xquant;
- inverse-volatility weights sum to one;
- zero/NaN volatility fails closed;
- capped inverse-volatility redistribution leaves every selected asset <= cap;
- LVT filters by MA and positive momentum, then chooses lowest volatility Top3;
- ties are resolved deterministically by symbol.

**Step 3: Run and verify failure**

```bash
uv run pytest tests/test_portfolio_strategy_indicators.py -q
```

Expected: FAIL because functions are missing.

**Step 4: Implement primitives**

Implement:

```python
def true_range(high, low, close) -> pd.Series: ...
def supertrend(high, low, close, atr_window, multiplier) -> pd.DataFrame: ...
def inverse_volatility_weights(returns, symbols, window, cap=None) -> dict[str, float]: ...
def select_low_vol_trend(close, returns, date, universe, ma_window, momentum_window, volatility_window, top_n) -> list[str]: ...
```

Use pandas rolling/SMA/std operations. Preserve only xquant's final-band and
direction state transition in local code. Return both line and direction so
snapshot diagnostics can show the BTC close and active line.

Reject insufficient/non-finite inputs through a typed calculation exception
rather than returning fabricated zero-risk weights.

**Step 5: Run tests**

```bash
uv run pytest tests/test_portfolio_strategy_indicators.py -q
```

Expected: PASS.

**Step 6: Commit**

```bash
git add backend/portfolio_strategies/indicators.py backend/tests/test_portfolio_strategy_indicators.py backend/tests/fixtures/portfolio_strategies/xquant_indicator_cases.json
git commit -m "feat: add deterministic portfolio indicators"
```

### Task 4: Implement exchange-session schedules

**Files:**

- Create: `backend/portfolio_strategies/schedules.py`
- Test: `backend/tests/test_portfolio_strategy_schedules.py`

**Step 1: Write failing tests**

Test:

- XSHG session normalization;
- BTC 10-session due dates anchored from a frozen known xquant formal signal
  reference;
- schedule phase remains stable when the local price frame begins later;
- Theme dates use the first XSHG session on or after the 10th and 25th;
- a shifted date cannot cross into the next month;
- next formal date and remaining session count are returned;
- an observed frame missing a scheduled session is not silently re-anchored.

The fixture must store the BTC reference formal signal date determined from the
frozen xquant export during Task 6.

**Step 2: Run and verify failure**

```bash
uv run pytest tests/test_portfolio_strategy_schedules.py -q
```

Expected: FAIL because schedule functions are missing.

**Step 3: Implement schedules**

Implement calendar-backed pure functions:

```python
def xshg_sessions(start, end) -> pd.DatetimeIndex: ...
def every_n_session_dates(reference_date, sessions, every=10) -> set[pd.Timestamp]: ...
def bimonthly_signal_dates(sessions) -> set[pd.Timestamp]: ...
def schedule_status(config, as_of_date, observed_sessions) -> ScheduleStatus: ...
```

Do not infer an official session solely from weekdays. The exchange calendar
supplies expected sessions; observed complete rows authorize calculation.

**Step 4: Run tests**

```bash
uv run pytest tests/test_portfolio_strategy_schedules.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add backend/portfolio_strategies/schedules.py backend/tests/test_portfolio_strategy_schedules.py
git commit -m "feat: add portfolio strategy schedules"
```

### Task 5: Add strict completed-close market-data validation

**Files:**

- Create: `backend/portfolio_strategies/market_data.py`
- Test: `backend/tests/test_portfolio_strategy_market_data.py`

**Step 1: Write failing tests**

Use temporary Parquet files and a frozen `now` to cover:

- A-share same-day row before 15:10 Asia/Shanghai is incomplete;
- A-share same-day row after cutoff is complete;
- BTC row for the current UTC date is incomplete;
- latest common ETF session is used;
- one Theme asset missing that session blocks calculation;
- recent unexplained asset gaps block calculation;
- insufficient MA200 history blocks Theme Alpha;
- stale latest session returns structured diagnostics;
- no input frame is mutated;
- refresh delegates to `refresh_symbols_sync_with_timeout` using the fixed
  strategy universe, not the watchlist.

**Step 2: Run and verify failure**

```bash
uv run pytest tests/test_portfolio_strategy_market_data.py -q
```

Expected: FAIL.

**Step 3: Implement the adapter**

Create:

```python
class PortfolioMarketData:
    close: pd.DataFrame
    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    sessions: pd.DatetimeIndex
    market_data_date: date
    diagnostics: tuple[DataDiagnostic, ...]

def load_strategy_market_data(config, data_dir, now) -> PortfolioMarketData: ...
def refresh_strategy_universe(config, timeout_seconds) -> RefreshResult: ...
```

Normalize indices to date-like, timezone-naive session labels after evaluating
market-specific cutoffs. Never forward-fill missing Theme ETF closes.

BTC may be reindexed to the selected ETF signal date only if the corresponding
BTC daily bar exists and is complete.

**Step 4: Run tests**

```bash
uv run pytest tests/test_portfolio_strategy_market_data.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add backend/portfolio_strategies/market_data.py backend/tests/test_portfolio_strategy_market_data.py
git commit -m "feat: validate complete portfolio market data"
```

### Task 6: Implement the two pure strategies and frozen xquant snapshot regressions

**Files:**

- Create: `backend/portfolio_strategies/btc_satellite.py`
- Create: `backend/portfolio_strategies/theme_alpha.py`
- Test: `backend/tests/test_btc_satellite_strategy.py`
- Test: `backend/tests/test_theme_alpha_strategy.py`
- Create: `backend/tests/fixtures/portfolio_strategies/btc_snapshot_2026-06-26.json`
- Create: `backend/tests/fixtures/portfolio_strategies/theme_alpha_snapshot_2026-06-25.json`

**Step 1: Produce read-only decision-provenance fixtures**

Use the xquant commit and its generated files:

- `outputs/q10-live-readiness-stress/latest_signal_summary.csv`;
- `outputs/q10-live-readiness-stress/latest_target_weights.csv`;
- `outputs/theme-alpha-q8-signal-live-readiness/latest_target_weights.csv`;
- `outputs/theme-alpha-q8-signal-live-readiness/latest_sleeve_weights.csv`;
- `outputs/theme-alpha-q8-signal-live-readiness/paper_tracking_snapshot.csv`.

Record only source commit, source paths, dates, parameters, symbols, latest
observation state, sleeve weights, and target weights in JSON. Do not commit the
114-session BTC or 217-session Theme Alpha OHLC history. Runtime calculations
must load trading's existing Parquet cache; unit tests use deterministic
synthetic market frames.

Determine and freeze the actual last formal BTC 10-session signal date used by
the xquant target. Put that date into the BTC registry reference schedule and
fixture metadata.

Do not execute or modify the xquant notebooks.

**Step 2: Write failing BTC tests**

Test:

- formal observation includes close, SuperTrend line, and on/off;
- 7.5% goes to BTC when on and cash when off;
- core RP weights are scaled to 92.5%;
- comparison targets calculate but are marked non-paper;
- non-due observation preserves the latest formal target;
- the compact xquant decision snapshot preserves target-composition semantics
  within `1e-10` without embedding historical market rows.

**Step 3: Write failing Theme tests**

Test:

- Core80 and LVT20 sleeve composition;
- MA60 + positive 63-session momentum eligibility;
- lowest-volatility Top3 and cap50;
- CSI300 and Nasdaq MA200 defense move each affected core weight to cash
  independently;
- deterministic synthetic data exercises formal target and sleeve calculation;
- the compact xquant decision snapshot preserves sleeve-composition semantics
  within `1e-10`.

**Step 4: Run and verify failure**

```bash
uv run pytest tests/test_btc_satellite_strategy.py tests/test_theme_alpha_strategy.py -q
```

Expected: FAIL.

**Step 5: Implement side-effect-free calculators**

Expose:

```python
def calculate_btc_satellite(config, market_data, as_of_date) -> StrategyCalculation: ...
def calculate_theme_alpha(config, market_data, as_of_date) -> StrategyCalculation: ...
```

Ensure all output weights are finite, nonnegative, deterministically ordered,
and sum to one within tolerance. Include per-asset reason strings used by the
frontend.

**Step 6: Run regressions**

```bash
uv run pytest tests/test_btc_satellite_strategy.py tests/test_theme_alpha_strategy.py -q
```

Expected: PASS with synthetic strategy calculations and exact compact
decision-composition comparisons.

**Step 7: Prove no xquant runtime dependency**

```bash
rg -n "/Users/zz/Desktop/Code/zsd/xquant|import xquant|from xquant" backend --glob '!tests/fixtures/**'
```

Expected: no matches.

**Step 8: Commit**

```bash
git add backend/portfolio_strategies backend/tests/test_btc_satellite_strategy.py backend/tests/test_theme_alpha_strategy.py backend/tests/fixtures/portfolio_strategies
git commit -m "feat: migrate validated portfolio strategies"
```

### Task 7: Build the SQLite repository and idempotency constraints

**Files:**

- Create: `backend/portfolio_strategies/ledger.py`
- Test: `backend/tests/test_portfolio_strategy_ledger.py`

**Step 1: Write failing schema/repository tests**

Test:

- database creation enables foreign keys, WAL, and busy timeout;
- creating the same account twice returns one account;
- duplicate strategy/version/signal date returns the existing signal;
- duplicate rebalance or trade writes are rejected/idempotent;
- position and NAV uniqueness;
- comparison strategy cannot create an account;
- a forced exception rolls back signal/rebalance/trade writes atomically;
- two repository instances writing the same signal result in one row.

**Step 2: Run and verify failure**

```bash
uv run pytest tests/test_portfolio_strategy_ledger.py -q
```

Expected: FAIL.

**Step 3: Implement schema and repository**

Create the tables and uniqueness rules from the design document. Centralize
connection setup:

```python
def connect(db_path):
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.row_factory = sqlite3.Row
    return conn
```

Use `BEGIN IMMEDIATE` for mutations. Store JSON with sorted keys and
`allow_nan=False`. Store timestamps in UTC ISO-8601.

**Step 4: Run tests**

```bash
uv run pytest tests/test_portfolio_strategy_ledger.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add backend/portfolio_strategies/ledger.py backend/tests/test_portfolio_strategy_ledger.py
git commit -m "feat: add idempotent portfolio paper ledger"
```

### Task 8: Implement bootstrap, next-close execution, costs, positions, and NAV

**Files:**

- Modify: `backend/portfolio_strategies/ledger.py`
- Create: `backend/portfolio_strategies/paper_engine.py`
- Test: `backend/tests/test_portfolio_paper_engine.py`

**Step 1: Write failing lifecycle tests**

Test:

- bootstrap creates positions and NAV but no trade;
- bootstrap date differs from the originating formal signal date;
- a formal signal creates one pending next-close rebalance;
- it does not execute without the next complete ETF close;
- next-close execution uses that session's close for every asset;
- repeat reconciliation creates no duplicate rows;
- BTC threshold skip works, while a BTC switch is always recorded;
- Theme 2% turnover skip works;
- Theme per-asset deltas are clipped to 15%;
- costs use the registered asset rate;
- fractional synthetic units are allowed;
- post-trade cash, positions, and net NAV reconcile;
- daily valuation updates cumulative return and max drawdown;
- restart resumes a pending event.

**Step 2: Run and verify failure**

```bash
uv run pytest tests/test_portfolio_paper_engine.py -q
```

Expected: FAIL.

**Step 3: Implement lifecycle**

Use fractional units for paper positions. For BTC, units are explicitly
synthetic proxy units and do not imply CNY/USD conversion.

At execution:

1. value existing units at next-close;
2. calculate gross NAV;
3. derive current weights;
4. apply threshold and max-trade rules to produce executable weights;
5. iteratively solve net target notional and one-way costs to a stable cent;
6. persist all trades, cash, position snapshot, rebalance status, and NAV in one
   transaction.

Never create a historical fill for bootstrap.

**Step 4: Run tests**

```bash
uv run pytest tests/test_portfolio_paper_engine.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add backend/portfolio_strategies/ledger.py backend/portfolio_strategies/paper_engine.py backend/tests/test_portfolio_paper_engine.py
git commit -m "feat: simulate next-close portfolio paper trading"
```

### Task 9: Add orchestration and stale-safe snapshots

**Files:**

- Create: `backend/portfolio_strategies/service.py`
- Test: `backend/tests/test_portfolio_strategy_service.py`

**Step 1: Write failing service tests**

Test:

- refresh uses the fixed registry universe;
- calculation runs only after successful complete-close validation;
- non-due refresh returns observation and prior formal signal;
- due refresh writes one official signal;
- blocked data writes a quality event but no signal/trade;
- a pending event reconciles when the execution close arrives;
- GET-style snapshot construction causes no writes;
- service response contains current, desired, executable, delta, dates,
  diagnostics, ledger summary, NAV metrics, and next check;
- service can reopen the database and reconstruct current state.

**Step 2: Run and verify failure**

```bash
uv run pytest tests/test_portfolio_strategy_service.py -q
```

Expected: FAIL.

**Step 3: Implement service**

Create:

```python
class PortfolioStrategyService:
    def list_strategies(self) -> list[dict]: ...
    def get_snapshot(self, strategy_id) -> dict: ...
    def refresh(self, strategy_id, now=None) -> dict: ...
    def target_weights(self, strategy_id) -> dict: ...
    def rebalance_diff(self, strategy_id) -> dict: ...
    def ledger_events(self, strategy_id, limit, cursor=None) -> dict: ...
    def nav_series(self, strategy_id, start=None, end=None) -> dict: ...
```

Use dependency-injected data directory, database path, refresh function, and
clock for deterministic tests.

**Step 4: Run tests**

```bash
uv run pytest tests/test_portfolio_strategy_service.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add backend/portfolio_strategies/service.py backend/tests/test_portfolio_strategy_service.py
git commit -m "feat: orchestrate portfolio strategy tracking"
```

### Task 10: Expose the FastAPI contract

**Files:**

- Create: `backend/portfolio_strategies/api_models.py`
- Modify: `backend/main.py`
- Test: `backend/tests/test_portfolio_strategy_api.py`
- Modify: `docker-compose.yml`

**Step 1: Write failing endpoint tests**

Use FastAPI's test client or direct endpoint calls with a temporary service.
Cover:

- list;
- snapshot;
- target weights;
- rebalance diff;
- paginated ledger;
- NAV;
- refresh;
- unknown ID 404;
- comparison-only paper operation 409;
- blocked data response remains HTTP 200 with an explicit blocked state;
- invalid cursor/limit 400;
- repeated refresh remains idempotent.

**Step 2: Run and verify failure**

```bash
uv run pytest tests/test_portfolio_strategy_api.py -q
```

Expected: FAIL.

**Step 3: Implement API models and thin endpoints**

Add constants:

```python
PORTFOLIO_PAPER_DB = "backtest_results/portfolio_paper.sqlite"
```

Instantiate the default service lazily so importing `main.py` in tests does not
start writes. Endpoint handlers translate known domain exceptions into 404,
400, or 409 without swallowing unexpected failures.

Ensure `docker-compose.yml` continues mounting `./backend/backtest_results` so
the new database persists; add no new host path.

**Step 4: Run tests**

```bash
uv run pytest tests/test_portfolio_strategy_api.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add backend/main.py backend/portfolio_strategies/api_models.py backend/tests/test_portfolio_strategy_api.py docker-compose.yml
git commit -m "feat: expose portfolio strategy APIs"
```

### Task 11: Add frontend types, API parsing, and status tests

**Files:**

- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/utils.ts`
- Create: `frontend/src/portfolioStrategies.js`
- Create: `frontend/src/portfolioStrategies.d.ts`
- Test: `frontend/test/portfolio-strategies.test.mjs`

**Step 1: Write failing Node tests**

Keep deterministic business helpers in a plain JS module, matching the existing
frontend test style. Test:

- API snapshot normalization;
- desired/current/executable delta rows;
- status tone mapping;
- blocked states are dominant over stale/pending states;
- date labels distinguish market, signal, and execution dates;
- strategy list marks comparison-only candidates;
- malformed numeric values are rejected or normalized to null.

**Step 2: Run and verify failure**

```bash
cd frontend
node --test test/portfolio-strategies.test.mjs
```

Expected: FAIL because the module does not exist.

**Step 3: Implement types and helpers**

Add TypeScript interfaces for registry rows, asset rows, diagnostics, snapshot,
ledger event, and NAV point. Add fetch functions:

```typescript
fetchPortfolioStrategies()
fetchPortfolioStrategySnapshot(id)
refreshPortfolioStrategy(id)
fetchPortfolioLedger(id, cursor?)
fetchPortfolioNav(id)
```

Use the plain JS helper for normalization so it is directly covered by Node
tests.

**Step 4: Run tests**

```bash
node --test test/portfolio-strategies.test.mjs
```

Expected: PASS.

**Step 5: Commit**

```bash
git add frontend/src/types.ts frontend/src/utils.ts frontend/src/portfolioStrategies.js frontend/src/portfolioStrategies.d.ts frontend/test/portfolio-strategies.test.mjs
git commit -m "feat: add portfolio strategy frontend client"
```

### Task 12: Build the nine-panel portfolio strategies page and minimal tab integration

**Files:**

- Create: `frontend/src/components/PortfolioStrategiesPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Header.tsx`
- Modify: `frontend/src/index.css` only if existing utilities cannot express the
  required responsive states

**Step 1: Add component-level pure rendering helpers first**

Extend `frontend/src/portfolioStrategies.js` tests for:

- the exact nine panel keys and ordering;
- expanded asset rows for Theme Alpha;
- empty/bootstrap/pending/executed/blocked view models;
- refresh button disabled while refresh is in flight.

Run:

```bash
node --test test/portfolio-strategies.test.mjs
```

Expected: FAIL for the new view-model assertions.

**Step 2: Implement the view-model helpers**

Keep presentation mapping outside the React component. Rerun the test and
expect PASS.

**Step 3: Implement the page**

The page must:

- load registry and selected official snapshot;
- support strategy switching;
- call explicit refresh;
- show nine responsive panels;
- show the complete asset table;
- display BTC synthetic-proxy warning;
- show stale/blocked diagnostics before any positive signal styling;
- expose ledger and NAV history without triggering writes;
- never label comparison-only BTC variants as official paper accounts.

Use existing dark visual language and utility classes. Do not redesign other
pages and do not introduce React Router.

**Step 4: Integrate navigation**

Add `portfolio` to `AppTab`.

Map:

- `/portfolio-strategies` -> `portfolio`;
- `portfolio` -> `/portfolio-strategies`;
- existing history route remains unchanged;
- other existing tab behavior remains unchanged.

Lazy-load `PortfolioStrategiesPage`. Add the `组合` header tab.

**Step 5: Run frontend verification**

```bash
node --test test/*.test.mjs
./node_modules/.bin/tsc -b
./node_modules/.bin/vite build
```

Expected: all tests pass, typecheck succeeds, production bundle builds.

**Step 6: Commit**

```bash
git add frontend/src/components/PortfolioStrategiesPage.tsx frontend/src/App.tsx frontend/src/components/Header.tsx frontend/src/index.css frontend/src/portfolioStrategies.js frontend/test/portfolio-strategies.test.mjs
git commit -m "feat: add portfolio strategies dashboard"
```

### Task 13: Add operational documentation and complete verification

**Files:**

- Create: `docs/portfolio-strategies-paper-tracking.md`
- Modify: `README.md` if it contains the current page/API catalog

**Step 1: Document operations**

Include:

- strategy IDs, versions, parameters, and universes;
- all new endpoints with example response fields;
- database path and schema table purpose;
- bootstrap versus real paper execution semantics;
- next-close behavior;
- manual refresh behavior;
- blocked data states;
- fixture provenance;
- validation commands;
- backup/restore note for the SQLite file;
- unresolved live-trading risks: BTC proxy/FX, Yahoo corrections, ETF
  premium/discount, liquidity, market holidays, close-price attainability,
  fractional paper units, and no broker reconciliation.

**Step 2: Run focused regressions**

```bash
cd backend
uv run pytest \
  tests/test_portfolio_strategy_registry.py \
  tests/test_portfolio_strategy_indicators.py \
  tests/test_portfolio_strategy_schedules.py \
  tests/test_portfolio_strategy_market_data.py \
  tests/test_btc_satellite_strategy.py \
  tests/test_theme_alpha_strategy.py \
  tests/test_portfolio_strategy_ledger.py \
  tests/test_portfolio_paper_engine.py \
  tests/test_portfolio_strategy_service.py \
  tests/test_portfolio_strategy_api.py -q
```

Expected: PASS.

**Step 3: Run complete backend verification**

```bash
uv run pytest -q
```

Expected: PASS with only documented data-dependent skips.

**Step 4: Run complete frontend verification**

```bash
cd ../frontend
node --test test/*.test.mjs
./node_modules/.bin/tsc -b
./node_modules/.bin/vite build
```

Expected: PASS and successful production build.

**Step 5: Verify repository boundaries and cleanliness**

```bash
cd ..
rg -n "/Users/zz/Desktop/Code/zsd/xquant|import xquant|from xquant" backend frontend --glob '!backend/tests/fixtures/**'
git diff --check
git status --short
```

Expected: no runtime xquant references, no whitespace errors, and only intended
documentation changes remain.

**Step 6: Commit**

```bash
git add docs/portfolio-strategies-paper-tracking.md README.md
git commit -m "docs: document portfolio paper tracking"
```

### Task 14: Review the completed branch

**Step 1: Inspect commit and diff summary**

```bash
git log --oneline 114c897..HEAD
git diff --stat 114c897..HEAD
git diff --check 114c897..HEAD
```

**Step 2: Request code review**

Use `superpowers:requesting-code-review` and address only verified actionable
findings through `superpowers:receiving-code-review`.

**Step 3: Re-run final verification after review changes**

Run the complete backend and frontend commands from Task 13 again. Do not claim
completion without current successful output.

**Step 4: Finish the branch**

Use `superpowers:verification-before-completion`, then
`superpowers:finishing-a-development-branch` to present merge/PR options.
