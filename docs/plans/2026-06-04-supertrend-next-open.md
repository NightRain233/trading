# SuperTrend Next Open Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove SuperTrend same-bar open lookahead bias by executing daily SuperTrend signals at the next daily open and invalidating legacy cached history results.

**Architecture:** Keep the existing SuperTrend strategy surface, exit modes, and API parameters. Add a stable execution mode/version to backend payloads and SQLite cache keys so old same-bar results cannot be reused.

**Tech Stack:** Python FastAPI backend, pandas/pandas-ta backtests, SQLite history cache, unittest/pytest.

---

### Task 1: Add Failing Tests

**Files:**
- Modify: `backend/tests/test_backtest.py`
- Modify: `backend/tests/test_history_trades_api.py`

**Steps:**
1. Add a test proving SuperTrend entries and flip exits execute on the next daily bar open.
2. Add a cache test proving execution mode is included in payload validation/cache scope.
3. Run the targeted tests and confirm they fail against current same-bar behavior.

### Task 2: Fix Backtest Execution

**Files:**
- Modify: `backend/backtest.py`

**Steps:**
1. Add a `SUPER_TREND_EXECUTION_MODE = "close_confirm_next_open"` constant.
2. Shift SuperTrend flip/support-test entries to the next bar open.
3. Shift SuperTrend flip exits in history review modes to the next bar open.
4. Include `executionMode` in history payloads.

### Task 3: Version Cache

**Files:**
- Modify: `backend/main.py`

**Steps:**
1. Add execution mode to history cache key and SQLite schema.
2. Reject cached payloads without the current execution mode.
3. Save execution mode with new cache entries.

### Task 4: Verify And Recompute

**Commands:**
- `uv run --directory backend pytest tests/test_backtest.py tests/test_history_trades_api.py`
- `uv run --directory backend python main.py --precompute-history-trades --start 2021-06-04 --force`

**Expected:** Tests pass and watchlist SuperTrend cache is regenerated under next-open semantics.
