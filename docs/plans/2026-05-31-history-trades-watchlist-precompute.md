# History Trades Watchlist Precompute Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Precompute five years of history-trades results for `backend/watchlist.json` symbols into the existing SQLite cache.

**Architecture:** Keep the existing history-trades SQLite schema and single-symbol endpoint. Add watchlist-only catalog helpers, missing-data hydration through `batch_fetch_and_update`, five-year default dates, and a local CLI entry point for smoke or full runs.

**Tech Stack:** FastAPI, Python stdlib argparse/sqlite3/datetime, pandas parquet, yfinance through the existing analysis pipeline, pytest/unittest.

---

### Task 1: Watchlist-Only Precompute Catalog

**Files:**
- Modify: `backend/main.py`
- Test: `backend/tests/test_history_trades_api.py`

**Step 1: Write the failing test**

Add a test that patches `main.load_watchlist` to return one watchlist symbol, patches `main.collect_history_trade_symbol_catalog` to include an unrelated symbol if called, writes parquet only for the watchlist symbol, and asserts `precompute_history_trades()` computes only the watchlist symbol.

**Step 2: Run test to verify it fails**

Run:

```bash
cd backend
PYTHONPATH=. uv run pytest tests/test_history_trades_api.py::HistoryTradesApiTests::test_precompute_history_trades_uses_watchlist_only -v
```

Expected: FAIL because precompute still calls the broader catalog helper.

**Step 3: Write minimal implementation**

Add `collect_watchlist_history_trade_symbol_catalog()` and call it from `precompute_history_trades()`.

**Step 4: Run test to verify it passes**

Run the same command. Expected: PASS.

### Task 2: Missing Data Hydration

**Files:**
- Modify: `backend/main.py`
- Test: `backend/tests/test_history_trades_api.py`

**Step 1: Write the failing test**

Add a test where no parquet exists initially. Patch `main.batch_fetch_and_update` to write `TEST.parquet`, then assert precompute writes SQLite cache and reports one downloaded symbol.

**Step 2: Run test to verify it fails**

Run:

```bash
cd backend
PYTHONPATH=. uv run pytest tests/test_history_trades_api.py::HistoryTradesApiTests::test_precompute_history_trades_downloads_missing_daily_data -v
```

Expected: FAIL because missing data is skipped.

**Step 3: Write minimal implementation**

Before skipping missing data, call `batch_fetch_and_update([symbol])`; if the daily parquet exists afterward, proceed and increment `downloaded`.

**Step 4: Run test to verify it passes**

Run the same command. Expected: PASS.

### Task 3: Five-Year Default Start

**Files:**
- Modify: `backend/main.py`
- Test: `backend/tests/test_history_trades_api.py`

**Step 1: Write the failing test**

Patch `main.datetime.now()` to return `2026-05-31`, call `precompute_history_trades(start=None)`, and assert `build_supertrend_history_review` receives `start="2021-05-31"`.

**Step 2: Run test to verify it fails**

Run:

```bash
cd backend
PYTHONPATH=. uv run pytest tests/test_history_trades_api.py::HistoryTradesApiTests::test_precompute_history_trades_defaults_to_five_years -v
```

Expected: FAIL because the old default start is static.

**Step 3: Write minimal implementation**

Add `_default_history_precompute_start(today=None)` and use it when `start` is `None`.

**Step 4: Run test to verify it passes**

Run the same command. Expected: PASS.

### Task 4: CLI Entry Point

**Files:**
- Modify: `backend/main.py`
- Test: `backend/tests/test_history_trades_api.py`

**Step 1: Write the failing test**

Patch `main.precompute_history_trades`, call `main.main(["--precompute-history-trades", "--symbol", "TEST"])`, and assert the precompute function receives `symbols=["TEST"]`.

**Step 2: Run test to verify it fails**

Run:

```bash
cd backend
PYTHONPATH=. uv run pytest tests/test_history_trades_api.py::HistoryTradesApiTests::test_history_precompute_cli_targets_single_symbol -v
```

Expected: FAIL because there is no CLI main.

**Step 3: Write minimal implementation**

Add an argparse-based `main(argv=None)` and `if __name__ == "__main__": main()` in `backend/main.py`.

**Step 4: Run test to verify it passes**

Run the same command. Expected: PASS.

### Task 5: Verification and Smoke Run

**Files:**
- Verify: `backend/tests/test_history_trades_api.py`
- Runtime: `backend/main.py`

**Step 1: Run focused tests**

```bash
cd backend
PYTHONPATH=. uv run pytest tests/test_history_trades_api.py -v
```

Expected: PASS.

**Step 2: Run one-symbol smoke command**

```bash
cd backend
PYTHONPATH=. uv run python main.py --precompute-history-trades --symbol 510500.SS
```

Expected: JSON summary with `computed` or `cached` for `510500.SS`, and `backtest_results/history_trades_cache.sqlite` contains a row for that symbol.
