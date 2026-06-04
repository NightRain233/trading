# SuperTrend Optimization Research Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend the SuperTrend research script so ST variants and asset buckets can be compared under the same close-confirmed, next-open execution rules.

**Architecture:** Keep this as a research-only layer. Modify `scripts/compare_supertrend_timeframes.py` to calculate reusable ST, ATR, and Bollinger Band context, then run several simple variants without changing backend API behavior, cache schema, or frontend defaults. Add focused tests for signal timing, squeeze filtering, no-chase filtering, and bucket summaries.

**Tech Stack:** Python 3.12, pandas, pandas-ta, uv, pytest.

---

### Task 1: Add Script-Level Regression Tests

**Files:**
- Create: `backend/tests/test_compare_supertrend_timeframes.py`
- Modify: none

**Step 1: Write failing tests**

Add tests that import `scripts/compare_supertrend_timeframes.py` via `importlib.util.spec_from_file_location`.

Cover these behaviors:
- A daily ST bull flip confirmed on one bar enters at the next bar open.
- A Bollinger squeeze filter only allows entries when bandwidth percentile is under the configured threshold.
- A no-chase filter rejects entries when the next open is too far above the ST line.
- Bucket summary groups rows by `assetBucket`.

**Step 2: Run tests and verify failure**

Run:

```bash
cd /Users/zz/Downloads/trading/backend
PYTHONPATH=. uv run pytest tests/test_compare_supertrend_timeframes.py -q
```

Expected: FAIL because the new variant/bucket APIs do not exist yet.

### Task 2: Add Indicator Context Helpers

**Files:**
- Modify: `scripts/compare_supertrend_timeframes.py`
- Test: `backend/tests/test_compare_supertrend_timeframes.py`

**Step 1: Extend `_add_supertrend`**

Return both ST direction and ST line:
- `_daily_dir`
- `_daily_line`
- `_weekly_dir`
- `_weekly_line`

Use pandas-ta columns with prefixes `SUPERTd_` for direction and `SUPERT_` for line.

**Step 2: Add Bollinger bandwidth context**

Create `_add_bollinger_context(daily)`:
- Calculate BB length 20, std 2.
- Add `_bb_width_pct = (upper - lower) / close * 100`.
- Add `_bb_width_rank_252`, a rolling 252-bar percentile rank of current bandwidth.

**Step 3: Run tests**

Run the focused test file. Expected: remaining failures only for strategy variants and bucket summary.

### Task 3: Add ST Variant Engine

**Files:**
- Modify: `scripts/compare_supertrend_timeframes.py`
- Test: `backend/tests/test_compare_supertrend_timeframes.py`

**Step 1: Add variant config**

Define simple variant dictionaries:
- `dailySt`: baseline daily ST.
- `dailyStBbSqueeze20`: daily ST entry only when `_bb_width_rank_252 <= 0.20`.
- `dailyStBbSqueeze30`: daily ST entry only when `_bb_width_rank_252 <= 0.30`.
- `dailyStNoChaseAtr1`: daily ST entry only when `(entry_open - st_line) / ATR <= 1.0`.
- `weeklyDailySt`: existing weekly-filtered daily ST.

**Step 2: Update `_daily_st_strategy`**

Accept optional parameters:
- `bb_squeeze_max_rank`
- `max_entry_distance_atr`
- `weekly_filter`
- `weekly_exit`

Preserve next-open execution. Evaluate filters on the confirmed signal bar and execute on the next bar open.

**Step 3: Update `_analyze_symbol`**

Return all variants in each row while keeping old keys for baseline compatibility.

**Step 4: Run focused tests**

Run:

```bash
cd /Users/zz/Downloads/trading/backend
PYTHONPATH=. uv run pytest tests/test_compare_supertrend_timeframes.py -q
```

Expected: PASS.

### Task 4: Add Asset Bucket Summary

**Files:**
- Modify: `scripts/compare_supertrend_timeframes.py`
- Test: `backend/tests/test_compare_supertrend_timeframes.py`

**Step 1: Add `_asset_bucket(meta)`**

Use simple deterministic buckets:
- `crypto`: symbols ending in `-USD` for BTC/ETH-style crypto.
- `commodity`: symbols such as `GC=F`, `SI=F`, `CL=F`.
- `a_share_etf`: symbols ending in `.SS` or `.SZ`.
- `us_etf`: common ETFs such as `SPY`, `QQQ`, `DIA`, `IWM`, `TLT`, `GLD`.
- `us_stock`: default for US single-name equities.

**Step 2: Add bucket summary**

Extend payload summary with:
- `byAssetBucket[bucket][strategy]`
- average return
- median return
- average max drawdown
- beat buy-hold return count
- beat buy-hold return/drawdown count

**Step 3: Run focused tests**

Run the focused test file. Expected: PASS.

### Task 5: Run Research Experiments

**Files:**
- No source edits expected.

**Step 1: Run BTC JSON**

```bash
cd /Users/zz/Downloads/trading
uv run --directory backend python ../scripts/compare_supertrend_timeframes.py --symbols BTC-USD --json
```

Record baseline, squeeze, no-chase, weekly, and combo results.

**Step 2: Run full watchlist table**

```bash
cd /Users/zz/Downloads/trading
uv run --directory backend python ../scripts/compare_supertrend_timeframes.py --limit 80
```

Record global and bucket-level summaries.

**Step 3: Run all tests if implementation changed shared behavior**

At minimum:

```bash
cd /Users/zz/Downloads/trading/backend
PYTHONPATH=. uv run pytest tests/test_compare_supertrend_timeframes.py -q
```

If any backend shared module is touched, run:

```bash
cd /Users/zz/Downloads/trading/backend
PYTHONPATH=. uv run pytest -q
```

### Task 6: Summarize Productization Decision

**Files:**
- No source edits required unless the user asks for a report file.

Summarize:
- Which variant improves BTC.
- Which variant survives across buckets.
- Whether ST optimization should become a frontend option.
- Which variants should stay research-only because they look overfit.

### Task 7: Add Parameter Grid Research

**Files:**
- Modify: `scripts/compare_supertrend_timeframes.py`
- Test: `backend/tests/test_compare_supertrend_timeframes.py`

**Step 1: Write failing tests**

Add focused tests for:
- Passing custom SuperTrend length/multiplier into pandas-ta.
- Parameter-grid summaries ranking configurations by return/drawdown ratio inside each asset bucket.

**Step 2: Implement parameterized ST helpers**

Update ST calculation and strategy functions to accept `st_length` and `st_multiplier`, defaulting to `7` and `3.0`.

**Step 3: Add CLI parameter-grid mode**

Add:

```bash
--param-grid
--st-lengths 5 7 10 14
--st-multipliers 2 3 4
```

Output compact JSON with `parameterGrid`, including global and `byAssetBucket` results.

### Task 8: Add Annual Stability Summary

**Files:**
- Modify: `scripts/compare_supertrend_timeframes.py`
- Test: `backend/tests/test_compare_supertrend_timeframes.py`

**Step 1: Write failing tests**

Add focused tests for:
- Building yearly windows from a start/end range.
- Summarizing annual rows without changing next-open execution rules.

**Step 2: Add annual summary mode**

Add:

```bash
--annual
```

When enabled, include `annualSummary` in JSON/table output. Each year should show the same strategy summary shape as the main period.

### Task 9: Run Expanded Research Experiments

**Files:**
- No source edits expected.

Run:

```bash
cd /Users/zz/Downloads/trading/backend
PYTHONPATH=. uv run pytest tests/test_compare_supertrend_timeframes.py -q
```

Then:

```bash
cd /Users/zz/Downloads/trading
uv run --directory backend python ../scripts/compare_supertrend_timeframes.py --symbols BTC-USD --annual --json
uv run --directory backend python ../scripts/compare_supertrend_timeframes.py --param-grid --json
```

Summarize:
- Best BTC parameter set.
- Best parameter set per asset bucket.
- Whether each best set is materially better than default ST.
- Whether annual results show one-off overfit or repeatable behavior.
