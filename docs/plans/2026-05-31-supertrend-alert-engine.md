# SuperTrend Alert Engine Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the existing SuperTrend scan into an actionable alert feed for watchlist monitoring and OpenClaw scheduled jobs.

**Architecture:** Add a small pure Python classifier that converts SuperTrend state, weekly alignment, price, ST line, and ATR into structured alerts. Reuse it in `/api/supertrend/scan`, display the fields in the existing React page, and provide a standalone Python script that calls the local API and prints OpenClaw-friendly output.

**Tech Stack:** FastAPI, pandas-ta, pytest, React 19, TypeScript, lightweight-charts, stdlib Python HTTP client.

---

### Task 1: Backend Alert Classifier

**Files:**
- Create: `backend/supertrend_alerts.py`
- Test: `backend/tests/test_supertrend_alerts.py`

**Steps:**
1. Write failing tests for bull flip, support test, bear flip, resistance test, and missing ST values.
2. Run the test module and confirm it fails because the classifier does not exist.
3. Implement `classify_supertrend_alert(...)` with stable JSON-safe fields.
4. Run the test module again and confirm it passes.

### Task 2: Scan API Integration

**Files:**
- Modify: `backend/main.py`

**Steps:**
1. Import the classifier in `main.py`.
2. Pass latest close, ATR, daily state, weekly state, ST value, and flip flags to the classifier.
3. Merge alert fields into each `/api/supertrend/scan` item.
4. Run the SuperTrend alert tests and a focused import check.

### Task 3: Frontend Scan UI

**Files:**
- Modify: `frontend/src/components/SupertrendPage.tsx`

**Steps:**
1. Extend `STItem` with alert fields returned by the API.
2. Add compact alert badges, ST distance, and key level display in each grid item.
3. Add quick filters for actionable alerts while preserving current state filters.
4. Run TypeScript build.

### Task 4: OpenClaw Script

**Files:**
- Create: `scripts/openclaw_supertrend_alerts.py`

**Steps:**
1. Add a stdlib-only CLI that calls `http://127.0.0.1:8000/api/supertrend/scan`.
2. Support `--format markdown|json`, `--min-priority`, `--only-actionable`, and `--api-base`.
3. Sort alerts by priority and distance to SuperTrend.
4. Run `--help` and a no-server smoke path to confirm error handling is clean.
