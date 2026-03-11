# List Timeframe Toggle Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 列表页支持日/周切换，并让后端图表接口和周线指标完整支持该切换。

**Architecture:** 后端先扩展周线指标与 `batch/charts` 请求参数，再由前端新增 timeframe 状态与分桶缓存，确保切换时读取/请求对应周期数据，不影响现有日线流程。

**Tech Stack:** FastAPI, pandas, React 19, TypeScript

---

### Task 1: 后端先写失败测试

**Files:**
- Create: `backend/tests/test_weekly_indicators.py`
- Create: `backend/tests/test_batch_charts_timeframe.py`

**Step 1: 写周线 EMA5/EMA10 测试**
- 调 `_calculate_weekly_indicators`，断言存在 `EMA5`/`EMA10` 且有有效值。

**Step 2: 写 batch/charts timeframe 测试**
- 使用 `TestClient` 调 `/api/quotes/batch/charts`，断言 `timeframe=1W` 返回周线数据。

**Step 3: 运行测试确认失败**
Run: `cd backend && UV_CACHE_DIR=.uv-cache uv run python -m unittest discover -s tests`
Expected: FAIL

### Task 2: 后端实现

**Files:**
- Modify: `backend/analysis.py`
- Modify: `backend/main.py`

**Step 1: 周线指标新增 EMA5/EMA10**
- 在 `_calculate_weekly_indicators` 增加 `EMA5`/`EMA10`。

**Step 2: batch/charts 支持 timeframe**
- `BatchQuoteRequest` 加 `timeframe` 字段。
- 接口按 timeframe 选择日线或周线 DataFrame。

**Step 3: 运行后端测试确认通过**
Run: `cd backend && UV_CACHE_DIR=.uv-cache uv run python -m unittest discover -s tests`
Expected: PASS

### Task 3: 前端接入

**Files:**
- Modify: `frontend/src/components/Header.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/utils.ts`

**Step 1: 增加 timeframe 切换按钮**
- Header 增加 `1D/1W` 切换 UI。

**Step 2: fetchBatchCharts 带 timeframe**
- 请求体增加 `timeframe`。

**Step 3: App 使用 timeframe 分桶缓存图表**
- `chartData` 改为按 timeframe 管理。
- 切换 timeframe 时按需加载缺失 symbol。

**Step 4: 前端构建验证**
Run: `cd frontend && pnpm build`
Expected: PASS
