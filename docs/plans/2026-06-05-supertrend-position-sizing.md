# SuperTrend Position Sizing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build and run an offline A-share ETF portfolio study that compares current RS rotation with SuperTrend-driven portfolio exposure control.

**Architecture:** Add a standalone research script that imports existing RS ranking helpers from `backend/backtest.py`, calculates daily/weekly SuperTrend state from local parquet frames, simulates RS rotation with configurable exposure multipliers, and writes JSON plus a Markdown report.

**Tech Stack:** Python, pandas, pandas-ta, pytest, existing local parquet cache.

---

### Task 1: TDD Exposure Helpers

**Files:**
- Create: `backend/tests/test_research_st_position_sizing.py`
- Create: `scripts/research_st_position_sizing.py`

**Steps:**

1. Write tests for `_market_exposure(weekly_dir, daily_dir)`.
2. Write tests for `_symbol_exposure(daily_dir)`.
3. Write tests that `_latest_st_dir()` uses only rows up to `as_of`.
4. Run:

   ```bash
   cd backend
   PYTHONPATH=.. uv run pytest tests/test_research_st_position_sizing.py -v
   ```

   Expected: fail because script/functions are missing.

5. Implement minimal helpers.
6. Re-run tests. Expected: pass.

### Task 2: TDD Exposure-Aware Portfolio Simulation

**Files:**
- Modify: `backend/tests/test_research_st_position_sizing.py`
- Modify: `scripts/research_st_position_sizing.py`

**Steps:**

1. Write a tiny synthetic portfolio test proving market exposure leaves cash uninvested.
2. Write a test proving symbol ST bear state suppresses that symbol in the dual-layer variant.
3. Implement `simulate_rs_rotation_with_st_exposure()`.
4. Re-run tests.

### Task 3: Add Study Assembly and CLI

**Files:**
- Modify: `scripts/research_st_position_sizing.py`

**Steps:**

1. Load `backend/universes/a_share_etf_core.json`.
2. Load local daily/weekly parquet frames.
3. Run variants:
   - `rs_no_filter_reference`
   - `rs_monthly_macd_baseline`
   - `rs_market_st_exposure`
   - `rs_market_symbol_st_exposure`
4. Add annual summaries and exposure summaries.
5. Add CLI:

   ```bash
   cd backend
   PYTHONPATH=. uv run python ../scripts/research_st_position_sizing.py \
     --output backtest_results/supertrend_position_sizing_2026-06-05.json
   ```

### Task 4: Run Research and Write Report

**Files:**
- Create: `docs/supertrend-position-sizing-research-2026-06-05.md`

**Steps:**

1. Run tests.
2. Run research script.
3. Extract core metrics from JSON.
4. Write report with conclusion and recommendation.
5. Re-run tests and script before final response.
