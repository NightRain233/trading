# Resonance V1 Exit + UI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add no-position resonance exit signals and integrate resonance buy/exit badges and filters into the watchlist UI.

**Architecture:** Extend existing resonance computation with a separate exit evaluator in `analysis.py`, then expose optional fields through API contracts and consume them in frontend filtering/presentation. Keep current trend/signal behavior unchanged.

**Tech Stack:** Python (FastAPI, pandas), unittest, React + TypeScript.

---

### Task 1: Add failing backend tests for exit evaluator

**Files:**
- Modify: `backend/tests/test_resonance_strategy.py`

1. Add tests for `hard` exit cases.
2. Add tests for `warn` exit case.
3. Add tests for `none` case.
4. Run `cd backend && uv run python -m unittest tests.test_resonance_strategy -v` and verify fail first.

### Task 2: Implement no-position exit evaluator in backend

**Files:**
- Modify: `backend/analysis.py`

1. Add `_evaluate_resonance_exit_no_position(df_daily, df_weekly)`.
2. Inject exit fields into `analyze_stock` and `analyze_stock_summary`.
3. Keep current `trend/signal` and existing resonance buy logic unchanged.
4. Re-run target tests and ensure pass.

### Task 3: Expose exit fields through API/types

**Files:**
- Modify: `backend/main.py`
- Modify: `frontend/src/types.ts`

1. Add response/type fields: `resonanceExitSignal`, `resonanceExitLevel`, `resonanceExitReason`.
2. Keep fields optional for backward compatibility.

### Task 4: Show resonance badges and filters in frontend

**Files:**
- Modify: `frontend/src/components/SortableStockRow.tsx`
- Modify: `frontend/src/components/FilterBar.tsx`
- Modify: `frontend/src/App.tsx`

1. Show buy/exit badges in row (mobile + desktop).
2. Add resonance filter chips in `FilterBar`.
3. Wire filter logic in `App.tsx` to `resonanceBuySignal/resonanceExitSignal`.

### Task 5: Verification

**Files:**
- Modify: none

1. Run backend test suite: `cd backend && uv run python -m unittest discover -s tests -p 'test_*.py' -v`.
2. Run frontend type check: `cd frontend && pnpm -s exec tsc --noEmit`.
