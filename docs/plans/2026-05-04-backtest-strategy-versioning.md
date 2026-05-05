# Backtest And Strategy Versioning Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

Status: implemented, expanded with ETF universes, market filters, and diagnostics.
Last updated: 2026-05-05

**Goal:** Add a minimal backtest engine and explicit strategy version registry so resonance strategy changes can be measured and compared.

**Architecture:** Create a small `strategy_versions.py` registry that owns tunable strategy parameters and a `backtest.py` module that can evaluate historical daily/weekly DataFrames without calling the network. Keep the MVP backend-only: tests exercise pure functions, and the CLI loads cached parquet files from `backend/data`.

**Tech Stack:** Python 3.12, pandas, unittest, existing `analysis.py` strategy helpers.

---

### Task 1: Record future development priorities

Status: done. The roadmap now lives in
`docs/plans/2026-05-04-strategy-roadmap-priorities.md`, with a handoff summary
in `docs/plans/2026-05-05-strategy-continuation-status.md`.

**Files:**
- Create: `docs/plans/2026-05-04-strategy-roadmap-priorities.md`

**Steps:**
1. Write the priority order:
   - Backtest MVP
   - Strategy versioning
   - Data quality panel
   - Position model
   - Market regime filter
   - Stock universe management
   - Structured signal explanation
2. Include why each item matters and what should not be built yet.

### Task 2: Strategy version registry

Status: done. Registry includes baseline ATR versions, a SPY-filtered ETF
version, and a CSI-300-filtered A-share ETF version.

**Files:**
- Create: `backend/strategy_versions.py`
- Create: `backend/tests/test_strategy_versions.py`
- Modify: `backend/analysis.py`

**Steps:**
1. Write tests for default version lookup and custom ATR parameter lookup.
2. Run `cd backend && uv run python -m unittest tests.test_strategy_versions -v` and confirm import failure.
3. Implement `StrategyVersion`, `get_strategy_version`, `list_strategy_versions`.
4. Update `_evaluate_resonance_strategy_v2` to accept a version id/config and include `strategyVersion` in the result.
5. Add a resonance strategy test proving `resonance_v2_atr_2_0` changes stop distance.

### Task 3: Backtest MVP

Status: done and expanded. The MVP now supports universe files, market regime
filters, asset/pool filters, symbol contribution, loss diagnostics, and
diagnostics by year.

**Files:**
- Create: `backend/backtest.py`
- Create: `backend/tests/test_backtest.py`

**Steps:**
1. Write tests with synthetic daily and weekly DataFrames:
   - A generated buy signal enters on the next bar.
   - A target hit exits with positive return and reports `target`.
   - Summary includes trade count, win rate, average return, max drawdown, and strategy version.
2. Run `cd backend && uv run python -m unittest tests.test_backtest -v` and confirm failure.
3. Implement `run_backtest_for_symbol` and `summarize_trades`.
4. Add a CLI that loads `{symbol}.parquet` and `{symbol}_weekly.parquet` from `DATA_DIR`.
5. Keep assumptions explicit: one position at a time per symbol, next-open entry, OHLC stop/target checks, fixed fee/slippage bps.

### Task 4: Verification

Status: done for the current implementation. Re-run the verification commands
after any future strategy or report changes.

**Files:**
- No direct edits.

**Steps:**
1. Run `cd backend && uv run python -m unittest discover -s tests`.
2. Run `cd frontend && npm run build` to ensure earlier contract changes remain sound.
3. Run `cd backend && uv run python -m backtest --symbols AAPL --strategy-version resonance_v2_atr_1_5` if cached data exists.

### Follow-Up Tasks

1. Build a stricter A-share ETF strategy version that avoids broad-market
   pullbacks. The first candidate should require CSI 300 to remain above EMA20
   at both signal and entry.
2. Add report comparison tooling so two strategy versions can be compared with
   the same universe and date range.
3. Add a data quality summary before trusting wider universe results.
4. Add a simple UI or generated markdown report once the backend diagnostics
   settle.
