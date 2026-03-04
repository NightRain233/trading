# List Mini MACD Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在列表迷你图中同时展示 EMA 主图和 MACD 副图。

**Architecture:** 后端先扩展 mini candles 字段，保持接口不变；前端在 `MiniChart` 使用两个 stacked chart 实例共享同一时间范围，主图显示 K+EMA，副图显示 MACD 柱和 DIF/DEA。通过过滤非有限数确保绘图稳定。

**Tech Stack:** FastAPI, pandas, React 19, TypeScript, lightweight-charts

---

### Task 1: 后端返回 mini MACD 字段

**Files:**
- Modify: `backend/analysis.py`
- Test: `backend/tests/test_candle_order.py`

**Step 1: Write the failing test**
- 在 `test_candle_order.py` 新增测试，构造包含 `MACD_DIF/DEA/Hist` 的 DataFrame。
- 断言 `_build_mini_candles` 返回记录含 `macd_dif/macd_dea/macd_hist`。

**Step 2: Run test to verify it fails**
Run: `cd backend && UV_CACHE_DIR=.uv-cache uv run python -m unittest tests/test_candle_order.py`
Expected: FAIL，缺少 `macd_*` 字段。

**Step 3: Write minimal implementation**
- 在 `_build_mini_candles` 的 `optional_cols` 增加 MACD 映射。

**Step 4: Run test to verify it passes**
Run: `cd backend && UV_CACHE_DIR=.uv-cache uv run python -m unittest tests/test_candle_order.py`
Expected: PASS

### Task 2: 前端迷你图增加 MACD 副图

**Files:**
- Modify: `frontend/src/components/MiniChart.tsx`

**Step 1: Write a failing expectation proxy**
- 先运行构建，记录当前无 MACD 副图作为基线。

**Step 2: Write minimal implementation**
- 拆分主图与副图容器，高度例如 70% / 30%。
- 主图保留蜡烛和 EMA。
- 副图新增 histogram(`macd_hist`) + line(`macd_dif`, `macd_dea`)。
- 共享 crosshair 与 tooltip，新增 MACD 数值行。

**Step 3: Run verification**
Run: `cd frontend && pnpm build`
Expected: PASS

### Task 3: 回归验证

**Files:**
- Modify: none (verification only)

**Step 1: Backend tests**
Run: `cd backend && UV_CACHE_DIR=.uv-cache uv run python -m unittest discover -s tests`
Expected: PASS

**Step 2: Frontend build**
Run: `cd frontend && pnpm build`
Expected: PASS

**Step 3: Manual check**
- 切换 `showCharts`，确认列表每行出现 EMA 主图 + MACD 副图。
- hover tooltip 同时显示 EMA 与 MACD 值。
