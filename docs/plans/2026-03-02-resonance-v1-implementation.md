# Resonance V1 Strategy Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `resonance_v1` strategy signal that combines weekly trend protection, daily EMA20/50 recent golden-cross pool filtering, and daily pullback confirmation buy signal.

**Architecture:** Keep existing `trend/signal` untouched and add independent strategy fields in backend analysis payload. Implement the strategy as pure helper functions in `analysis.py` so they are testable with synthetic DataFrames. Surface results via API models and frontend types without changing current UI behavior.

**Tech Stack:** Python (FastAPI, pandas, pandas-ta), unittest, TypeScript types.

---

### Task 1: Define expected resonance behavior with failing tests

**Files:**
- Create: `backend/tests/test_resonance_strategy.py`
- Test: `backend/tests/test_resonance_strategy.py`

1. Write tests for:
   - Weekly + daily pool match + pullback confirm => `buySignal=True`.
   - Weekly filter fail => `inPool=False`.
   - Golden cross too old (>15 bars) => `inPool=False`.
   - Pullback without volume shrink => `buySignal=False`.
2. Run `cd backend && uv run python -m unittest tests.test_resonance_strategy -v` and confirm failure first.

### Task 2: Implement minimal backend strategy logic

**Files:**
- Modify: `backend/analysis.py`

1. Add helper functions:
   - recent EMA20/50 golden-cross detection (with lookback window).
   - pullback confirmation detection for EMA5/EMA10.
   - resonance strategy evaluator returning structured fields.
2. Add strategy output fields to `analyze_stock` and `analyze_stock_summary`.
3. Keep existing `trend`, `signal`, RSI logic unchanged.
4. Run target tests and confirm pass.

### Task 3: Expose strategy fields through API contracts

**Files:**
- Modify: `backend/main.py`
- Modify: `frontend/src/types.ts`

1. Add optional response/type fields:
   - `resonanceInPool`
   - `resonanceBuySignal`
   - `resonancePoolReason`
   - `resonanceBuyReason`
2. Ensure new fields are backward compatible.
3. Run backend tests again to confirm no regression.

### Task 4: Verification

**Files:**
- Modify: none (verification only)

1. Run `cd backend && uv run python -m unittest -v`.
2. If frontend checks are available locally, run type-check/build for contract safety.
3. Summarize implemented behavior, constraints, and follow-up recommendations.
