# SuperTrend Opportunity Lifecycle Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add opportunity lifecycle context and lightweight manual marks to the SuperTrend scan so signals do not appear to vanish without explanation.

**Architecture:** Keep the existing alert type and priority model. Add a separate opportunity lifecycle layer in the backend response, then render it as contextual tags in the React ST cards. Manual marks are client-local for the first version to avoid turning this into a portfolio ledger.

**Tech Stack:** FastAPI/Python, unittest/pytest, React TypeScript, Tailwind CSS, lucide-react.

---

### Task 1: Backend Opportunity Lifecycle

**Files:**
- Modify: `backend/supertrend_alerts.py`
- Modify: `backend/main.py`
- Test: `backend/tests/test_supertrend_alerts.py`

**Steps:**
1. Add failing tests for fresh bull age, pullback zone, extended move, and invalidated/risk state.
2. Extend `classify_supertrend_alert` to return `opportunityStage`, `opportunityLabel`, `opportunityAgeBars`, and `opportunityReason`.
3. Calculate current SuperTrend direction age in `/api/supertrend/scan` and pass it to the classifier.
4. Run the focused backend tests.

### Task 2: Frontend Card Semantics

**Files:**
- Modify: `frontend/src/components/SupertrendPage.tsx`

**Steps:**
1. Extend `STItem` with opportunity lifecycle fields.
2. Add visual styles and labels for lifecycle tags without replacing existing alert tags.
3. Add local manual marks: none, watch, holding, ignored.
4. Keep marked watch/holding cards visible even when low priority is folded.
5. Add compact holding risk display using ST stop line and distance.

### Task 3: Verification

**Commands:**
- `cd backend && uv run pytest tests/test_supertrend_alerts.py`
- `cd frontend && pnpm build`

**Manual QA:**
- Open the ST page on desktop and mobile widths.
- Check that card header, tags, mark controls, risk row, and chart do not overlap.
