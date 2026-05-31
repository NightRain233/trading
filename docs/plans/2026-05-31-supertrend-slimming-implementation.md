# SuperTrend Signal Slimming Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add backtested SuperTrend slimming rules, report their five-year performance against baseline, and update the SuperTrend page default only when the data supports it.

**Architecture:** Extend the existing SuperTrend backtest with entry-mode predicates while keeping exit and portfolio logic unchanged. Add a strategy-comparison research section that computes pass/fail gates, then use the generated result to decide whether the frontend defaults to a slim daily mode or keeps full coverage with clearer layering.

**Tech Stack:** Python 3.12, pandas, pandas-ta, pytest, FastAPI backend data cache, React 19, TypeScript, Vite.

---

### Task 1: Backtest Entry Mode Contract

**Files:**
- Modify: `backend/tests/test_backtest.py`
- Modify: `backend/backtest.py`

**Step 1: Write failing tests**

Add focused tests near existing SuperTrend ADX tests:

```python
def test_supertrend_support_test_entry_enters_near_support(self):
    daily = _build_supertrend_daily_df(adx_at_entry=28.0)
    daily.loc[daily.index[2], "Low"] = 101.5
    daily.loc[daily.index[2], "Close"] = 102.0
    weekly = daily.copy()
    st = _build_supertrend_indicator(daily.index)
    st.loc[daily.index[2:], "SUPERTd_7_3.0"] = 1
    st.loc[daily.index[2:], "SUPERT_7_3.0"] = [101.0, 101.0, 101.0]
    weekly_st = pd.DataFrame({"SUPERTd_7_3.0": [1] * len(weekly)}, index=weekly.index)

    with patch("backtest.ta.supertrend", side_effect=[st, weekly_st]):
        trades = run_supertrend_backtest(
            "TEST",
            daily,
            filter_weekly_df=weekly,
            fee_bps=0,
            slippage_bps=0,
            entry_signal_mode="weekly_bull_support_test",
        )

    self.assertEqual(len(trades), 1)
    self.assertEqual(trades[0]["entrySignalMode"], "weekly_bull_support_test")
```

Also add tests for weekly-bear rejection and unsupported entry-mode validation.

**Step 2: Run tests to verify failure**

Run:

```bash
cd backend
PYTHONPATH=. uv run --python 3.12 pytest tests/test_backtest.py::BacktestTests::test_supertrend_support_test_entry_enters_near_support -q
```

Expected: fail because `entry_signal_mode` is not implemented.

**Step 3: Implement minimal entry-mode support**

In `run_supertrend_backtest`:

- Add `entry_signal_mode: str = "weekly_bull_daily_bull_flip"`.
- Build helper predicates for daily bull flip, daily support test, weekly bullish, and high-priority alerts.
- Validate supported modes.
- Keep the old default behavior equivalent to weekly bullish daily bull flip.
- Add `entrySignalMode` to each trade.
- Include mode in `strategyVersion`, except preserve current naming for the default baseline if needed by existing tests.

**Step 4: Run focused SuperTrend tests**

Run:

```bash
cd backend
PYTHONPATH=. uv run --python 3.12 pytest tests/test_backtest.py::BacktestTests::test_supertrend_adx_filter_skips_low_adx_flip tests/test_backtest.py::BacktestTests::test_supertrend_adx_filter_allows_trending_flip tests/test_backtest.py::BacktestTests::test_supertrend_support_test_entry_enters_near_support -q
```

Expected: pass.

---

### Task 2: Strategy Comparison Slimming Research

**Files:**
- Modify: `backend/tests/test_strategy_comparison.py`
- Modify: `backend/strategy_comparison.py`

**Step 1: Write failing report tests**

Add tests that:

- `format_markdown_report` includes "SuperTrend 精简层研究".
- Pass/fail judgment renders when `supertrendSlimmingRows` is provided.
- Retention values render as percentages.

**Step 2: Run tests to verify failure**

Run:

```bash
cd backend
PYTHONPATH=. uv run --python 3.12 pytest tests/test_strategy_comparison.py -q
```

Expected: fail because the section is missing.

**Step 3: Implement report generation**

In `strategy_comparison.py`:

- Define slimming mode metadata.
- Add `entry_signal_mode` to `build_supertrend_report` and pass it to `run_supertrend_backtest`.
- Add `_build_supertrend_slimming_rows`.
- Add `supertrendSlimmingRows` to the JSON report.
- Add assumptions for slimming gate thresholds.
- Render a markdown table with baseline, variant, retention, trade reduction, and judgment.

**Step 4: Run report tests**

Run:

```bash
cd backend
PYTHONPATH=. uv run --python 3.12 pytest tests/test_strategy_comparison.py -q
```

Expected: pass.

---

### Task 3: Run Five-Year Slimming Backtest

**Files:**
- Read/Generate: strategy comparison command output.

**Step 1: Run JSON report**

Run:

```bash
cd backend
PYTHONPATH=. uv run --python 3.12 python strategy_comparison.py --format json
```

**Step 2: Inspect results**

Identify whether any slimming rule passes:

- return/drawdown retention >= 0.85
- total-return retention >= 0.70
- trade count below baseline

**Step 3: Decide frontend path**

If any rule passes, choose the highest-retention passing rule as the daily default. If none passes, keep full coverage and implement UI layering only.

---

### Task 4: Frontend Daily View

**Files:**
- Modify: `frontend/src/components/SupertrendPage.tsx`

**Step 1: Implement based on Task 3 outcome**

If a slimming rule passes:

- Add `daily_focus` or the chosen rule to `FilterType`.
- Default `filter` to that rule.
- Add a "日常精简 / 全量扫描" control.
- Keep all existing filter chips.

If no slimming rule passes:

- Keep default full coverage.
- Group or fold low-priority rows so high-priority/actionable rows are visually first.
- Add copy that explains full coverage is retained because slimming rules did not pass the five-year gate.

**Step 2: Build frontend**

Run:

```bash
cd frontend
pnpm build
```

Expected: TypeScript and Vite build pass.

---

### Task 5: Final Verification

**Files:**
- All modified files.

**Step 1: Run backend focused tests**

Run:

```bash
cd backend
PYTHONPATH=. uv run --python 3.12 pytest tests/test_supertrend_alerts.py tests/test_strategy_comparison.py tests/test_backtest.py::BacktestTests::test_supertrend_adx_filter_skips_low_adx_flip tests/test_backtest.py::BacktestTests::test_supertrend_adx_filter_allows_trending_flip -q
```

Include new SuperTrend entry-mode tests in the same command.

**Step 2: Run report command**

Run:

```bash
cd backend
PYTHONPATH=. uv run --python 3.12 python strategy_comparison.py --format markdown
```

Expected: report renders and includes the slimming section.

**Step 3: Run frontend build**

Run:

```bash
cd frontend
pnpm build
```

Expected: build succeeds.

**Step 4: Report caveats**

Mention the pre-existing broad `test_backtest.py` resonance failures separately from the focused SuperTrend verification.
