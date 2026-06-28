# Static Allocation Weight Stability Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a deterministic ±5/±10 percentage-point weight grid around the 20/30/20/30 static stock-bond-gold benchmark, backtest every valid point, evaluate the agreed neighborhood gates, and update the research artifacts.

**Architecture:** Extend the existing standalone multi-asset research script. Generalize the static allocation target builder, generate a stable category-level grid, run each point through the existing monthly CNY simulator, retain compact summaries, and feed the aggregate stability verdict into recommendation and report rendering.

**Tech Stack:** Python 3.12, pandas, pytest, existing `uv` backend environment.

---

### Task 1: Specify the deterministic grid

**Files:**
- Modify: `backend/tests/test_research_multi_asset_balanced_portfolio.py`
- Modify: `scripts/research_multi_asset_balanced_portfolio.py`

1. Add failing tests for 85 broad points, 19 core points, unique IDs, exact 100% sums, and deterministic ordering.
2. Run the focused tests and confirm failure due to missing grid helpers.
3. Implement constants and `build_static_weight_grid()`.
4. Run the focused tests and confirm they pass.

### Task 2: Specify neighborhood gates

**Files:**
- Modify: `backend/tests/test_research_multi_asset_balanced_portfolio.py`
- Modify: `scripts/research_multi_asset_balanced_portfolio.py`

1. Add failing tests for core unanimity, broad 80% target rate, and broad 20% hard drawdown rejection.
2. Run the focused tests and confirm failure.
3. Implement compact point and neighborhood summaries in `summarize_static_weight_stability()`.
4. Run the focused tests and confirm they pass.

### Task 3: Generalize static allocation simulation

**Files:**
- Modify: `backend/tests/test_research_multi_asset_balanced_portfolio.py`
- Modify: `scripts/research_multi_asset_balanced_portfolio.py`

1. Add a failing test proving custom category weights split A-shares equally and US equities equally.
2. Expose a reusable target-weight helper and allow `simulate_static_allocation_benchmark()` to accept category weights.
3. Run the focused and complete research tests.

### Task 4: Integrate the grid and report

**Files:**
- Modify: `scripts/research_multi_asset_balanced_portfolio.py`
- Modify: `backend/tests/test_research_multi_asset_balanced_portfolio.py`
- Modify: `docs/multi-asset-balanced-portfolio-research-2026-06-06.md`
- Modify: `backend/backtest_results/multi_asset_balanced_portfolio_2026-06-06.json`

1. Add failing report and recommendation tests.
2. Backtest all 85 points using the existing simulation cache.
3. Add `staticWeightStability` to JSON and render the report section.
4. Let the static benchmark become eligible only when both neighborhood gates pass.
5. Run the full research command to regenerate JSON and Markdown.

### Task 5: Verify

1. Run `uv run pytest tests/test_research_multi_asset_balanced_portfolio.py -v`.
2. Run the relevant broader research/backtest regression suite.
3. Run `git diff --check`.
4. Inspect grid counts, pass rates, worst points, recommendation, and report wording from the generated JSON.
