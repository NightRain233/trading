# A-share ETF ST vs RS Fair Comparison Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a same-universe, same-date-window research comparison for A-share ETF RS rotation and pure SuperTrend portfolio variants.

**Architecture:** Add one offline research script that reuses the existing pure ST portfolio simulator and backend RS rotation simulator, then runs all strategies over identical cached ETF frames and identical windows. The report will separate full-cache results from the recent 5-year window so the previous baseline mismatch is visible instead of hidden.

**Tech Stack:** Python, pandas, pandas-ta, local parquet cache, backend `backtest.py`, pytest.

---

### Task 1: Add Fair-Comparison Tests

**Files:**
- Create: `backend/tests/test_research_a_share_etf_st_rs_fair_comparison.py`
- Create later: `scripts/research_a_share_etf_st_rs_fair_comparison.py`

**Step 1: Write failing tests**

Test three behaviors:
- `_window_label()` formats explicit windows predictably.
- `_summarize_window_payload()` returns only strategy summaries and keeps numeric values stable.
- `build_fair_comparison()` can run from monkeypatched tiny windows without fetching external data.

**Step 2: Run test to verify it fails**

Run:

```bash
cd backend && uv run pytest tests/test_research_a_share_etf_st_rs_fair_comparison.py -q
```

Expected: fail because `scripts/research_a_share_etf_st_rs_fair_comparison.py` does not exist yet.

### Task 2: Implement Offline Fair-Comparison Script

**Files:**
- Create: `scripts/research_a_share_etf_st_rs_fair_comparison.py`

**Step 1: Implement imports and helpers**

Import the previously committed `research_a_share_etf_pure_st_portfolio.py` by path. Use its `build_research()` so ST variants and RS baseline share the same simulator implementation and parameters.

**Step 2: Implement `build_fair_comparison()`**

Run windows:
- `full_cache`: `2015-01-01` to `2026-06-05`
- `recent_5y`: `2021-05-06` to `2026-06-05`

For each window, collect:
- `rs_monthly_macd_baseline`
- `equal_weight_buy_hold`
- `daily_st_equal_weight`
- `weekly_daily_st_equal_weight`
- `daily_st_top5_rs`

**Step 3: Write Markdown report**

Create `docs/a-share-etf-st-rs-fair-comparison-2026-06-06.md` with:
- Parameters and common cost model.
- Full-cache table.
- Recent-window table.
- Interpretation explaining the baseline mismatch.

### Task 3: Verify and Commit

**Files:**
- `scripts/research_a_share_etf_st_rs_fair_comparison.py`
- `backend/tests/test_research_a_share_etf_st_rs_fair_comparison.py`
- `docs/a-share-etf-st-rs-fair-comparison-2026-06-06.md`

**Step 1: Run tests**

```bash
cd backend && uv run pytest tests/test_research_a_share_etf_st_rs_fair_comparison.py -q
```

Expected: all pass.

**Step 2: Run research**

```bash
cd backend && PYTHONHASHSEED=0 PYTHONPATH=. uv run python ../scripts/research_a_share_etf_st_rs_fair_comparison.py --output backtest_results/a_share_etf_st_rs_fair_comparison_2026-06-06.json --report ../docs/a-share-etf-st-rs-fair-comparison-2026-06-06.md
```

Expected: JSON and Markdown are written.

**Step 3: Commit**

```bash
git add scripts/research_a_share_etf_st_rs_fair_comparison.py backend/tests/test_research_a_share_etf_st_rs_fair_comparison.py docs/a-share-etf-st-rs-fair-comparison-2026-06-06.md docs/plans/2026-06-06-a-share-etf-st-rs-fair-comparison.md
git commit -m "research: compare a-share etf st and rs fairly"
```
