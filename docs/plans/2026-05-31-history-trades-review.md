# History Trades Review Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an interactive historical buy/sell review page for a single symbol, starting with SuperTrend replay data.

**Architecture:** Add a backend replay helper that produces chart-ready candles, SuperTrend points, markers, trades, and summary for one symbol. Expose it through `GET /api/history-trades`, then add a dedicated frontend page at `/history-trades` using lightweight-charts and the app's existing header navigation pattern.

**Tech Stack:** FastAPI, pandas, pandas-ta, pytest, React 19, TypeScript, Vite, Tailwind CSS, lightweight-charts, lucide-react.

---

### Task 1: Backend SuperTrend Replay Helper

**Files:**
- Modify: `backend/backtest.py`
- Test: `backend/tests/test_backtest.py`

**Step 1: Write the failing test**

Add a test that patches `backtest.ta.supertrend` with a deterministic direction flip series, calls `build_supertrend_history_review`, and asserts:

- response symbol is uppercased
- candles are returned in ascending time order
- supertrend points include direction
- buy and sell markers exist
- one completed trade includes return percent, holding days, and exit reason
- summary trade count is 1

**Step 2: Run test to verify it fails**

Run:

```bash
cd backend
PYTHONPATH=. uv run pytest tests/test_backtest.py::BacktestTests::test_supertrend_history_review_returns_chart_payload -v
```

Expected: FAIL because `build_supertrend_history_review` is not defined.

**Step 3: Write minimal implementation**

Implement `build_supertrend_history_review(...)` in `backend/backtest.py`. Reuse existing SuperTrend calculation patterns and `_price_with_bps`. Return a dict with `symbol`, `strategy`, `start`, `end`, `candles`, `supertrend`, `markers`, `trades`, and `summary`.

**Step 4: Run test to verify it passes**

Run the same test. Expected: PASS.

### Task 2: Date Filtering Behavior

**Files:**
- Modify: `backend/backtest.py`
- Test: `backend/tests/test_backtest.py`

**Step 1: Write the failing test**

Add a test that calls `build_supertrend_history_review` with `start` after the first flip and asserts the first trade is filtered out and returned candles start at or after `start`.

**Step 2: Run test to verify it fails**

Run:

```bash
cd backend
PYTHONPATH=. uv run pytest tests/test_backtest.py::BacktestTests::test_supertrend_history_review_applies_date_filter -v
```

Expected: FAIL until filtering is complete.

**Step 3: Write minimal implementation**

Apply `start` and `end` to chart series output, and only open new trades when entry date is inside the date range.

**Step 4: Run test to verify it passes**

Run the same test. Expected: PASS.

### Task 3: API Endpoint

**Files:**
- Modify: `backend/main.py`
- Test: `backend/tests/test_history_trades_api.py`

**Step 1: Write failing tests**

Add tests for:

- unknown `strategy` returns 400
- missing local parquet returns 404
- happy path calls replay helper and returns its payload

**Step 2: Run tests to verify they fail**

Run:

```bash
cd backend
PYTHONPATH=. uv run pytest tests/test_history_trades_api.py -v
```

Expected: FAIL because `/api/history-trades` does not exist.

**Step 3: Write minimal implementation**

Add request query params to `main.py`, import `build_supertrend_history_review`, read `DATA_DIR/{symbol}.parquet`, and return the replay payload.

**Step 4: Run tests to verify they pass**

Run the same test file. Expected: PASS.

### Task 4: Frontend Page

**Files:**
- Create: `frontend/src/components/HistoryTradesPage.tsx`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/utils.ts`

**Step 1: Add types and utility**

Define `HistoryTradesResponse`, `HistoryTrade`, `HistoryMarker`, and `fetchHistoryTrades` in the frontend.

**Step 2: Implement page**

Build the page with form controls, loading/error/empty states, summary metrics, chart rendering, and trades table.

**Step 3: Verify TypeScript**

Run:

```bash
cd frontend
pnpm build
```

Expected: PASS.

### Task 5: Route and Navigation

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Header.tsx`

**Step 1: Add route state**

Track path/page state in `App.tsx`, listen to `popstate`, and render `HistoryTradesPage` when path is `/history-trades`.

**Step 2: Add Header tab**

Add a “复盘” tab with a chart/search style icon. Keep existing tab behavior unchanged.

**Step 3: Verify build**

Run:

```bash
cd frontend
pnpm build
```

Expected: PASS.

### Task 6: Final Verification

**Files:**
- All modified files

**Step 1: Run focused backend tests**

```bash
cd backend
PYTHONPATH=. uv run pytest tests/test_backtest.py::BacktestTests::test_supertrend_history_review_returns_chart_payload tests/test_backtest.py::BacktestTests::test_supertrend_history_review_applies_date_filter tests/test_history_trades_api.py -v
```

Expected: PASS.

**Step 2: Run backend suite**

```bash
cd backend
PYTHONPATH=. uv run pytest
```

Expected: PASS or documented pre-existing skips/failures.

**Step 3: Run frontend build**

```bash
cd frontend
pnpm build
```

Expected: PASS.

**Step 4: Start dev servers and inspect page**

Start backend and frontend, open `/history-trades`, run one symbol with cached data, and verify chart, markers, summary, and table render.
