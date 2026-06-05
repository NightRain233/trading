# SuperTrend Fit Research Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build and run an offline SuperTrend fit-screening study that scores symbols using prior two-year data and validates on future six-month windows.

**Architecture:** Add one research script that reuses existing SuperTrend data loading, asset bucketing, buy-hold stats, and daily ST backtest helpers from `scripts/compare_supertrend_timeframes.py`. The script computes history, shape, and hybrid scores on each training window, assigns tiers before reading validation metrics, then writes JSON and a Markdown report.

**Tech Stack:** Python, pandas, pandas-ta, pytest, local parquet cache, existing backend research helpers.

---

### Task 1: Add Walk-Forward and Scoring Tests

**Files:**
- Create: `backend/tests/test_research_supertrend_fit.py`
- Create: `scripts/research_supertrend_fit.py`

**Step 1: Write failing tests**

Add tests that import `scripts/research_supertrend_fit.py` by file path, following the style in `backend/tests/test_compare_supertrend_timeframes.py`.

Test these behaviors:

- `_build_walk_forward_windows("2021-01-01", "2024-01-15", train_years=2, test_months=6, step_months=6)` returns non-overlapping train/test windows where `testStart > trainEnd`.
- `_safe_rdd(return_pct, max_drawdown_pct)` uses a minimum 5% denominator.
- `_insufficient_trade_penalty(0) == 1.0`, `1 == 0.5`, `2 == 0.0`.
- `_assign_tiers()` ranks rows per asset bucket and marks buckets smaller than three as `lowSample`.

**Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=. uv run pytest backend/tests/test_research_supertrend_fit.py -v
```

Expected: fail because `scripts/research_supertrend_fit.py` does not exist or functions are missing.

**Step 3: Implement minimal helpers**

Create `scripts/research_supertrend_fit.py` with:

- imports
- `_date_str`
- `_add_months`
- `_build_walk_forward_windows`
- `_safe_rdd`
- `_insufficient_trade_penalty`
- `_assign_tiers`

**Step 4: Run tests**

Run the same pytest command. Expected: pass for Task 1 tests.

### Task 2: Add Feature and Score Tests

**Files:**
- Modify: `backend/tests/test_research_supertrend_fit.py`
- Modify: `scripts/research_supertrend_fit.py`

**Step 1: Write failing tests**

Add tests for:

- `_robust_normalize_rows()` computes normalized fields from the provided rows only.
- `_history_raw_fields()` computes `excessRddSafe`, `drawdownReductionPct`, `excessLogReturn`, and trade reliability.
- `_compute_shape_features()` uses only data through `trainEnd`; append a large future price spike and assert training features do not change.
- `_score_rows()` outputs `historyScore`, `adjustedHistoryScore`, `shapeScore`, `hybridScore`, and contribution fields.

**Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=. uv run pytest backend/tests/test_research_supertrend_fit.py -v
```

Expected: new tests fail because scoring helpers are missing.

**Step 3: Implement scoring helpers**

Implement:

- `_robust_z_values`
- `_robust_normalize_rows`
- `_history_raw_fields`
- `_compute_shape_features`
- `_score_rows`

Use `pandas_ta` for ADX, EMA, ATR, and SuperTrend direction, with defensive fallbacks if a library call returns empty data.

**Step 4: Run tests**

Run the same pytest command. Expected: pass.

### Task 3: Add Walk-Forward Study Assembly

**Files:**
- Modify: `backend/tests/test_research_supertrend_fit.py`
- Modify: `scripts/research_supertrend_fit.py`

**Step 1: Write failing tests**

Add tests for:

- `_build_window_rows()` does not include validation metrics in score/tier inputs.
- `_summarize_score_mode()` computes tier summaries and top-minus-bottom spread.
- `_spearman()` handles ties and empty inputs.

**Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=. uv run pytest backend/tests/test_research_supertrend_fit.py -v
```

**Step 3: Implement assembly**

Implement:

- dynamic import of `scripts/compare_supertrend_timeframes.py`
- `_load_prepared_symbols`
- `_build_window_rows`
- `_summarize_score_mode`
- `_summarize_all`
- `build_supertrend_fit_research`

Reuse `_analyze_symbol_from_data()` for train and validation stats.

**Step 4: Run tests**

Run:

```bash
PYTHONPATH=. uv run pytest backend/tests/test_research_supertrend_fit.py backend/tests/test_compare_supertrend_timeframes.py -v
```

Expected: pass.

### Task 4: Add CLI and Run Research

**Files:**
- Modify: `scripts/research_supertrend_fit.py`

**Step 1: Add CLI**

Add arguments:

- `--start`, default `2021-06-05`
- `--end`, default today
- `--train-years`, default `2`
- `--test-months`, default `6`
- `--step-months`, default `6`
- `--output`, default `backend/backtest_results/supertrend_fit_research_2026-06-05.json`
- `--json`, print payload to stdout

**Step 2: Run script**

Run:

```bash
PYTHONPATH=. uv run python scripts/research_supertrend_fit.py --output backend/backtest_results/supertrend_fit_research_2026-06-05.json
```

Expected: JSON result file is written.

### Task 5: Write Result Report

**Files:**
- Create: `docs/supertrend-fit-research-2026-06-05.md`

**Step 1: Inspect JSON output**

Use a small command to extract:

- params
- window count
- symbol counts per asset bucket
- by-bucket history/shape/hybrid top-minus-bottom spreads
- warnings for low-sample buckets

**Step 2: Write Markdown report**

Report:

- research method and anti-look-ahead controls
- A-share ETF result
- A-share stock result
- US ETF result
- US stock result
- comparison of history vs shape vs hybrid
- product recommendation

**Step 3: Verify**

Run:

```bash
PYTHONPATH=. uv run pytest backend/tests/test_research_supertrend_fit.py backend/tests/test_compare_supertrend_timeframes.py -v
```

Expected: pass.

Run the research script again. Expected: output JSON exists and includes `summary`.
