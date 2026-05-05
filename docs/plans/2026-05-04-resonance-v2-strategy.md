# Resonance V2 Strategy Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade resonance signals from boolean pattern detection to a risk-aware opportunity model.

**Architecture:** Keep existing resonance v1 fields backward compatible. Add a v2 evaluator in `backend/analysis.py` that classifies pool type, scores entry quality, estimates ATR-based stop/risk, and exposes these fields through API and frontend types. Do not change existing v1 buy/exit semantics in this pass.

**Tech Stack:** Python, pandas, FastAPI/Pydantic, unittest, TypeScript.

---

### Task 1: Add failing strategy v2 tests

**Files:**
- Modify: `backend/tests/test_resonance_strategy.py`

**Steps:**
1. Import `_evaluate_resonance_strategy_v2`.
2. Add a test for an older-but-intact trend returning `poolType="establishedTrend"` and `inPool=True`.
3. Add a test for a buy setup returning ATR stop price, risk percent, and reward/risk ratio.
4. Run `cd backend && uv run python -m unittest tests.test_resonance_strategy -v`.
5. Confirm tests fail because the v2 evaluator does not exist.

### Task 2: Implement minimal backend v2 evaluator

**Files:**
- Modify: `backend/analysis.py`

**Steps:**
1. Add constants for established-trend lookback and ATR stop/target multiples.
2. Add `_evaluate_resonance_strategy_v2(df_daily, df_weekly)`.
3. Preserve v1 results and add:
   - `poolType`
   - `entryScore`
   - `riskScore`
   - `riskLevel`
   - `stopPrice`
   - `riskPercent`
   - `targetPrice`
   - `rewardRiskRatio`
4. Add v2 fields to `analyze_stock` and `analyze_stock_summary`.
5. Run targeted backend tests until green.

### Task 3: Expose contract fields

**Files:**
- Modify: `backend/main.py`
- Modify: `frontend/src/types.ts`

**Steps:**
1. Add optional pydantic response fields.
2. Add optional TypeScript fields to `StockData`.
3. Keep all fields optional to preserve old cached payload compatibility.

### Task 4: Light UI surfacing

**Files:**
- Modify: `frontend/src/components/SortableStockRow.tsx`

**Steps:**
1. Add compact desktop/mobile labels for entry score and risk level only when values exist.
2. Use existing row badge style; avoid new layout sections.
3. Run frontend type/build verification.

### Task 5: Verification

**Files:**
- No direct edits.

**Steps:**
1. Run `cd backend && uv run python -m unittest discover -s tests`.
2. Run `cd frontend && pnpm build`.
3. Report changed files and any remaining caveats.
