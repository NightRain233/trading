# Weekly BB Pullback Entry Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a pullback-confirmed entry path to the weekly Bollinger Band strategy while keeping the existing breakout entry.

**Architecture:** Keep the existing `evaluate_weekly_bb_breakout` signal as the fast trend entry. Add `evaluate_weekly_bb_pullback` for symbols that already had a recent weekly upper-band breakout, then either pulled back to weekly BB mid / MA20 or made a shallower daily EMA20 pullback with daily EMA20 and MA30 confirmation. The scan API returns a new `pullback` state and the frontend adds filtering and labeling for it.

**Tech Stack:** Python, pandas, FastAPI backend; React/TypeScript frontend.

---

### Task 1: Backend Signal Tests

**Files:**
- Modify: `backend/tests/test_backtest.py`
- Modify: `backend/backtest.py`

**Step 1: Write failing tests**

Add tests that assert:
- A weekly series with a prior breakout, current low near weekly BB mid, current close back above BB mid, current close above MA30, and daily close above EMA20 and MA30 returns `buySignal=True` with `poolType="weeklyBBPullback"`.
- A weekly series with a prior breakout and no weekly-mid touch still returns `buySignal=True` when the latest 10 daily bars touched EMA20 within 1% and the latest daily close reclaimed EMA20 and MA30.
- The same weekly pullback is rejected when the latest daily close remains below EMA20.

**Step 2: Run tests to verify red**

Run: `uv run pytest backend/tests/test_backtest.py -k weekly_bb_pullback -v`

Expected: fail because `evaluate_weekly_bb_pullback` does not exist yet.

### Task 2: Backend Implementation

**Files:**
- Modify: `backend/backtest.py`
- Modify: `backend/main.py`

**Step 1: Implement pullback signal**

Add `evaluate_weekly_bb_pullback(df_weekly, df_daily=None, breakout_lookback=8, pullback_tolerance_pct=3.0, daily_pullback_lookback=10, daily_pullback_tolerance_pct=1.0)`.

Signal rules:
- Required weekly columns: `Close`, `Low`, `BOLL_Upper`, `BOLL_Lower`, `BOLL_Mid`, `MA30`.
- Latest weekly close must be above MA30.
- A prior week within the lookback window must have closed above weekly BB upper and above MA30.
- Weekly pullback path: latest weekly low must touch the weekly BB mid zone, and latest weekly close must reclaim weekly BB mid.
- Daily pullback path: recent daily low must touch the daily EMA20 zone, and latest daily close must be above both `EMA20` and `MA30`.
- Return stop at weekly MA30 and `strategyVersion="weekly_bb_breakout_ma30"`.

**Step 2: Run tests to verify green**

Run: `uv run pytest backend/tests/test_backtest.py -k weekly_bb_pullback -v`

Expected: pass.

### Task 3: Scan API and UI State

**Files:**
- Modify: `backend/main.py`
- Modify: `frontend/src/components/WeeklyBreakoutPage.tsx`
- Modify: `docs/weekly-bb-breakout.md`

**Step 1: Add API state**

In `/api/weekly-breakout/scan`, evaluate pullback after breakout and before exit/squeeze. Return `state="pullback"`, the pullback stop price, and `entryType` as `weeklyPullback` or `dailyPullback`.

**Step 2: Add frontend state**

Add `pullback` to the TypeScript union, label map, color map, filter buttons, and sort order.

**Step 3: Update docs**

Document the dual entry rhythm: `挤压 -> 突破 / 等回踩 -> 回踩确认 -> 离场`.

### Task 4: Verification

Run:
- `uv run pytest backend/tests/test_backtest.py -k "weekly_bb or weekly_bb_pullback" -v`
- `uv run pytest backend/tests/test_strategy_versions.py -v`
- Frontend type/build check if dependencies are present.
