# Multi-Asset Balanced Portfolio Research Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a reproducible research pipeline for a CNY-denominated, long-only multi-asset portfolio that combines monthly trend filters, inverse-volatility risk budgets, category caps, optional intra-class relative strength, and separate lump-sum/DCA evaluation.

**Architecture:** Keep the first version isolated in a standalone research script instead of changing the production backtest engine. Load a declarative universe, normalize every investable price into CNY, compute completed-month signals, construct capped target weights, simulate next-common-trading-day rebalances, and generate JSON plus a Markdown report with a hard productization verdict.

**Tech Stack:** Python 3.12, pandas, yfinance-backed local parquet caches, pytest, existing `uv` backend environment.

---

## Fixed Research Decisions

- Universe configuration: `backend/universes/multi_asset_balanced.json`.
- A-share core: all `bucket == "broad"` symbols from `backend/universes/a_share_etf_core.json`.
- US equity: `SPY`, `QQQ`.
- Gold proxy: `GLD`, currency USD.
- China bond proxy: `511010.SS`, currency CNY.
- Crypto proxy: `BTC-USD`, currency USD.
- FX series: `CNY=X`, interpreted as CNY per USD.
- Cash return: 0% in the first study, intentionally conservative.
- Portfolio accounting currency: CNY.
- Trend and volatility calculations: use CNY-normalized prices so signals match the investor's realized wealth.
- Signal dates: completed calendar months only.
- Execution: first date after month-end present in the intersection of the currently held and newly targeted tradable assets; execute at that date's CNY-normalized open.
- Default transaction assumptions: 5 bps fee and 5 bps slippage per side.
- Candidate BTC caps: 0%, 5%, 10%.
- No production API or frontend changes in this plan.

If `511010.SS` or `CNY=X` cannot be downloaded reliably, stop and document the blocker. Do not silently substitute a better-performing proxy.

### Task 1: Add the Declarative Research Universe

**Files:**
- Create: `backend/universes/multi_asset_balanced.json`
- Create: `backend/tests/test_research_multi_asset_balanced_portfolio.py`

**Step 1: Write the failing universe test**

Create the initial test loader used by all later tasks:

```python
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "research_multi_asset_balanced_portfolio.py"
UNIVERSE_PATH = ROOT / "backend" / "universes" / "multi_asset_balanced.json"


def load_research_module():
    spec = importlib.util.spec_from_file_location("research_multi_asset_balanced_portfolio", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_balanced_universe_declares_assets_currency_and_caps():
    payload = json.loads(UNIVERSE_PATH.read_text(encoding="utf-8"))
    by_symbol = {row["symbol"]: row for row in payload["assets"]}

    assert by_symbol["SPY"]["currency"] == "USD"
    assert by_symbol["QQQ"]["assetClass"] == "us_equity"
    assert by_symbol["GLD"]["assetClass"] == "gold"
    assert by_symbol["511010.SS"]["assetClass"] == "a_bond"
    assert by_symbol["BTC-USD"]["maxWeight"] == 0.05
    assert payload["fxSymbol"] == "CNY=X"
```

**Step 2: Run the test to verify it fails**

Run:

```bash
cd backend
uv run pytest tests/test_research_multi_asset_balanced_portfolio.py::test_balanced_universe_declares_assets_currency_and_caps -v
```

Expected: FAIL because the universe file does not exist.

**Step 3: Create the universe**

Use this structure:

```json
{
  "name": "multi-asset-balanced",
  "baseCurrency": "CNY",
  "fxSymbol": "CNY=X",
  "cashSymbol": "__CASH__",
  "categoryCaps": {
    "a_share_equity": 0.30,
    "us_equity": 0.40,
    "gold": 0.25,
    "crypto": 0.05
  },
  "assets": [
    {"symbol": "SPY", "name": "SPDR S&P 500 ETF", "assetClass": "us_equity", "currency": "USD", "maxWeight": 0.25},
    {"symbol": "QQQ", "name": "Invesco QQQ", "assetClass": "us_equity", "currency": "USD", "maxWeight": 0.25},
    {"symbol": "GLD", "name": "SPDR Gold Shares", "assetClass": "gold", "currency": "USD", "maxWeight": 0.25},
    {"symbol": "511010.SS", "name": "国债ETF", "assetClass": "a_bond", "currency": "CNY", "maxWeight": 1.00},
    {"symbol": "BTC-USD", "name": "Bitcoin", "assetClass": "crypto", "currency": "USD", "maxWeight": 0.05}
  ],
  "aShareUniverseFile": "a_share_etf_core.json",
  "aShareBucket": "broad"
}
```

The research loader will append A-share broad assets dynamically and assign each a 25% single-symbol cap.

**Step 4: Run the test to verify it passes**

Run the same pytest command.

Expected: PASS.

**Step 5: Commit**

```bash
git add backend/universes/multi_asset_balanced.json backend/tests/test_research_multi_asset_balanced_portfolio.py
git commit -m "research: define multi-asset balanced universe"
```

### Task 2: Add Data Loading and CNY Normalization

**Files:**
- Create: `scripts/research_multi_asset_balanced_portfolio.py`
- Modify: `backend/tests/test_research_multi_asset_balanced_portfolio.py`

**Step 1: Write failing tests for universe expansion and FX conversion**

Add tests using small deterministic frames:

```python
import pandas as pd


def test_load_universe_adds_only_a_share_broad_assets(tmp_path):
    module = load_research_module()
    a_share_path = tmp_path / "a_share.json"
    a_share_path.write_text(
        json.dumps({
            "symbols": [
                {"symbol": "510300.SS", "bucket": "broad"},
                {"symbol": "512760.SS", "bucket": "sector"}
            ]
        }),
        encoding="utf-8",
    )
    config = {
        "assets": [],
        "aShareUniverseFile": a_share_path.name,
        "aShareBucket": "broad",
    }

    assets = module.expand_assets(config, a_share_path.parent)

    assert [row["symbol"] for row in assets] == ["510300.SS"]
    assert assets[0]["assetClass"] == "a_share_equity"
    assert assets[0]["currency"] == "CNY"


def test_normalize_ohlc_to_cny_multiplies_usd_prices_by_known_fx():
    module = load_research_module()
    dates = pd.to_datetime(["2025-01-02", "2025-01-03"])
    asset = pd.DataFrame(
        {"Open": [10.0, 11.0], "High": [11.0, 12.0], "Low": [9.0, 10.0], "Close": [10.5, 11.5]},
        index=dates,
    )
    fx = pd.DataFrame(
        {"Open": [7.0, 7.1], "High": [7.0, 7.1], "Low": [7.0, 7.1], "Close": [7.0, 7.1]},
        index=dates,
    )

    converted = module.normalize_ohlc_to_cny(asset, "USD", fx)

    assert converted.loc[dates[0], "Open"] == 70.0
    assert converted.loc[dates[1], "Close"] == 81.65


def test_fx_alignment_never_backfills_future_rates():
    module = load_research_module()
    dates = pd.to_datetime(["2025-01-02", "2025-01-03"])
    asset = pd.DataFrame({"Close": [10.0, 11.0]}, index=dates)
    fx = pd.DataFrame({"Close": [7.0]}, index=pd.to_datetime(["2025-01-03"]))

    converted = module.normalize_ohlc_to_cny(asset, "USD", fx)

    assert pd.isna(converted.loc[pd.Timestamp("2025-01-02"), "Close"])
    assert converted.loc[pd.Timestamp("2025-01-03"), "Close"] == 77.0
```

**Step 2: Run tests to verify they fail**

Run:

```bash
cd backend
uv run pytest tests/test_research_multi_asset_balanced_portfolio.py -k "load_universe or normalize_ohlc or fx_alignment" -v
```

Expected: FAIL because the research module and helpers do not exist.

**Step 3: Implement the minimal data layer**

Implement:

- `load_config(path)`.
- `expand_assets(config, universe_dir)`.
- `load_frame(symbol, data_dir)`.
- `load_all_frames(assets, fx_symbol, data_dir)`.
- `normalize_ohlc_to_cny(frame, currency, fx_frame)`.
- `coverage_audit(frames)`.

Rules:

- Normalize indexes to timezone-naive `DatetimeIndex`.
- Sort and deduplicate indexes.
- Require `Open` and `Close`; retain `High`, `Low`, and `Volume` when present.
- Reindex FX to the asset index and forward-fill only from past observations.
- Never use `bfill`.
- Leave pre-FX-history rows as `NaN`.
- CNY assets return an unchanged copy.

Add CLI arguments:

```text
--config
--data-dir
--start
--end
--output
--report
```

Do not implement the simulation yet.

**Step 4: Run tests to verify they pass**

Run the same pytest selection.

Expected: PASS.

**Step 5: Backfill the fixed missing data**

Run:

```bash
cd /Users/zz/Downloads/trading/backend
uv run python ../scripts/backfill_historical_data.py \
  --symbols 511010.SS CNY=X GLD SPY QQQ BTC-USD \
  --start 2000-01-01 \
  --end 2026-06-06 \
  --output backtest_results/multi_asset_balanced_backfill_2026-06-06.json
```

Expected:

- `511010.SS` and `CNY=X` have non-empty daily parquet files.
- The output reports actual start dates without claiming unavailable 2008 coverage.
- Existing cache files are merged, not truncated.

Inspect:

```bash
cd /Users/zz/Downloads/trading/backend
uv run python -c "import pandas as pd; from pathlib import Path; [(lambda f: print(f.name, pd.read_parquet(f).index.min(), pd.read_parquet(f).index.max(), len(pd.read_parquet(f))))(Path('data') / f'{s}.parquet') for s in ['511010.SS','CNY=X','GLD','SPY','QQQ','BTC-USD']]"
```

**Step 6: Commit**

```bash
git add scripts/research_multi_asset_balanced_portfolio.py backend/tests/test_research_multi_asset_balanced_portfolio.py backend/backtest_results/multi_asset_balanced_backfill_2026-06-06.json
git commit -m "research: add CNY multi-asset data layer"
```

Do not commit rewritten parquet cache files unless repository policy already tracks those exact files.

### Task 3: Implement Completed-Month Trend Signals

**Files:**
- Modify: `scripts/research_multi_asset_balanced_portfolio.py`
- Modify: `backend/tests/test_research_multi_asset_balanced_portfolio.py`

**Step 1: Write failing signal tests**

Cover all three signal modes and unfinished-month handling:

```python
def test_monthly_trend_signals_use_only_completed_months():
    module = load_research_module()
    index = pd.date_range("2024-01-02", "2025-02-14", freq="B")
    close = pd.Series(range(100, 100 + len(index)), index=index, dtype="float64")
    frame = pd.DataFrame({"Close": close})

    signals = module.build_monthly_trend_signals(frame, mode="ma10")

    assert signals.index.max() <= pd.Timestamp("2025-01-31")
    assert pd.Timestamp("2025-02-14") not in signals.index


def test_combined_trend_requires_ma10_and_positive_12_month_momentum():
    module = load_research_module()
    monthly = pd.Series(
        [100, 102, 104, 106, 108, 110, 112, 114, 116, 118, 120, 122, 121],
        index=pd.date_range("2024-01-31", periods=13, freq="ME"),
        dtype="float64",
    )

    result = module.evaluate_monthly_trend(monthly, mode="ma10_and_mom12")

    assert bool(result.iloc[-1]) is True
```

Add a negative case where price is above MA10 but below its 12-month-ago close; combined mode must be false.

**Step 2: Run tests to verify they fail**

```bash
cd backend
uv run pytest tests/test_research_multi_asset_balanced_portfolio.py -k "trend" -v
```

Expected: FAIL with missing signal helpers.

**Step 3: Implement signal helpers**

Implement:

- `completed_monthly_close(frame, as_of=None)`.
- `evaluate_monthly_trend(monthly_close, mode)`.
- `build_monthly_trend_signals(frame, mode, as_of=None)`.
- `latest_completed_signal(signals, signal_month)`.

Signal definitions:

```python
ma10 = monthly_close > monthly_close.rolling(10, min_periods=10).mean()
mom12 = monthly_close.pct_change(12) > 0
```

For `ma10_and_mom12`, use `ma10 & mom12`.

Drop the current calendar month unless the input data contains a date at or beyond that calendar month's actual end. In normal daily cache usage, this means the current unfinished month is excluded.

**Step 4: Run tests to verify they pass**

Run the same pytest selection.

Expected: PASS.

**Step 5: Commit**

```bash
git add scripts/research_multi_asset_balanced_portfolio.py backend/tests/test_research_multi_asset_balanced_portfolio.py
git commit -m "research: add completed-month trend filters"
```

### Task 4: Implement Risk Budgets, Caps, and Intra-Class RS

**Files:**
- Modify: `scripts/research_multi_asset_balanced_portfolio.py`
- Modify: `backend/tests/test_research_multi_asset_balanced_portfolio.py`

**Step 1: Write failing allocation tests**

Add deterministic tests:

```python
def test_inverse_volatility_gives_less_weight_to_high_volatility_asset():
    module = load_research_module()
    weights = module.inverse_volatility_weights({"LOW": 0.10, "HIGH": 0.40})

    assert weights["LOW"] == 0.8
    assert weights["HIGH"] == 0.2


def test_apply_caps_redistributes_without_breaking_category_or_symbol_caps():
    module = load_research_module()
    assets = {
        "SPY": {"assetClass": "us_equity", "maxWeight": 0.25},
        "QQQ": {"assetClass": "us_equity", "maxWeight": 0.25},
        "GLD": {"assetClass": "gold", "maxWeight": 0.25},
    }
    raw = {"SPY": 0.45, "QQQ": 0.35, "GLD": 0.20}
    category_caps = {"us_equity": 0.40, "gold": 0.25}

    capped = module.apply_weight_caps(raw, assets, category_caps)

    assert capped["SPY"] <= 0.25
    assert capped["QQQ"] <= 0.25
    assert capped["SPY"] + capped["QQQ"] <= 0.40
    assert capped["GLD"] <= 0.25
    assert sum(capped.values()) <= 1.0


def test_crypto_cap_override_supports_zero_five_and_ten_percent():
    module = load_research_module()
    assets = {"BTC-USD": {"assetClass": "crypto", "maxWeight": 0.05}}

    assert module.with_btc_cap(assets, 0.0)["BTC-USD"]["maxWeight"] == 0.0
    assert module.with_btc_cap(assets, 0.10)["BTC-USD"]["maxWeight"] == 0.10


def test_a_share_rs_selects_only_assets_with_sufficient_history():
    module = load_research_module()
    date = pd.Timestamp("2025-06-30")
    frames = {
        "A": pd.DataFrame({"Close": range(100, 221)}, index=pd.date_range("2025-01-01", periods=121, freq="B")),
        "B": pd.DataFrame({"Close": range(100, 161)}, index=pd.date_range("2025-04-01", periods=61, freq="B")),
    }

    selected = module.select_relative_strength(frames, ["A", "B"], date, lookback=120, top_n=1)

    assert selected == ["A"]
```

**Step 2: Run tests to verify they fail**

```bash
cd backend
uv run pytest tests/test_research_multi_asset_balanced_portfolio.py -k "volatility or caps or crypto_cap or relative_strength" -v
```

Expected: FAIL with missing allocation helpers.

**Step 3: Implement allocation helpers**

Implement:

- `annualized_volatility(close, as_of, lookback)`.
- `inverse_volatility_weights(vol_by_symbol)`.
- `apply_weight_caps(raw_weights, asset_metadata, category_caps)`.
- `with_btc_cap(asset_metadata, btc_cap)`.
- `select_relative_strength(frames, symbols, as_of, lookback, top_n)`.
- `build_target_weights(...)`.

Cap algorithm:

1. Normalize positive raw weights.
2. Clamp individual symbols.
3. Clamp each category proportionally.
4. Redistribute residual only among uncapped eligible assets.
5. Repeat until no cap changes or 20 iterations are reached.
6. Leave any unresolved residual as cash.

Do not force all weights to sum to one after caps.

Variant behavior:

- `static_risk_budget`: all eligible assets, no trend gate.
- `trend_risk_budget`: trend-qualified assets, no RS selection.
- `trend_risk_budget_rs`: select top 1 and top 2 A-share variants; separately test equal SPY/QQQ eligibility versus RS tilt.

Fallback:

- If no risk asset is eligible, allocate to A bond when its trend is positive.
- Otherwise allocate 100% to cash.
- A bond is not included in inverse-volatility competition with risk assets; it receives residual defensive weight.

**Step 4: Run tests to verify they pass**

Run the same pytest selection.

Expected: PASS.

**Step 5: Commit**

```bash
git add scripts/research_multi_asset_balanced_portfolio.py backend/tests/test_research_multi_asset_balanced_portfolio.py
git commit -m "research: add capped risk-budget allocation"
```

### Task 5: Implement the Monthly Portfolio Simulator

**Files:**
- Modify: `scripts/research_multi_asset_balanced_portfolio.py`
- Modify: `backend/tests/test_research_multi_asset_balanced_portfolio.py`

**Step 1: Write failing execution tests**

Tests must prove:

- A January signal cannot use January data before January is complete.
- Rebalance occurs on the next common tradable date.
- Trades use that date's open.
- Drift threshold suppresses small trades.
- Fees and slippage reduce equity.
- Cash is explicit and never negative.

Example:

```python
def test_rebalance_executes_at_next_common_open_after_completed_month():
    module = load_research_module()
    dates_a = pd.to_datetime(["2025-01-30", "2025-02-03", "2025-02-04"])
    dates_b = pd.to_datetime(["2025-01-31", "2025-02-04", "2025-02-05"])
    frames = {
        "A": pd.DataFrame({"Open": [100, 110, 111], "Close": [101, 110, 111]}, index=dates_a),
        "B": pd.DataFrame({"Open": [200, 220, 221], "Close": [201, 220, 221]}, index=dates_b),
    }

    assert module.next_common_trading_date(frames, ["A", "B"], pd.Timestamp("2025-01-31")) == pd.Timestamp("2025-02-04")


def test_trade_costs_reduce_final_equity():
    module = load_research_module()
    no_cost = module.simulate_monthly_portfolio_for_test(fee_bps=0, slippage_bps=0)
    with_cost = module.simulate_monthly_portfolio_for_test(fee_bps=5, slippage_bps=5)

    assert with_cost["equityCurve"][-1]["equity"] < no_cost["equityCurve"][-1]["equity"]
```

Use a test-only deterministic target-weight callback rather than invoking live strategy logic.

**Step 2: Run tests to verify they fail**

```bash
cd backend
uv run pytest tests/test_research_multi_asset_balanced_portfolio.py -k "rebalance or trade_costs or drift or cash" -v
```

Expected: FAIL with missing simulator helpers.

**Step 3: Implement the simulator**

Implement:

- `next_common_trading_date(frames, symbols, after_date)`.
- `price_on(frame, date, field)`.
- `portfolio_value_cny(state, frames, date)`.
- `current_weights(state, frames, date)`.
- `should_trade(current, target, drift_threshold)`.
- `rebalance_at_open(...)`.
- `simulate_monthly_portfolio(...)`.

State:

```python
{
    "cash": 1.0,
    "shares": {},
    "lastPrices": {},
    "costPaid": 0.0
}
```

Execution order:

1. Sell reductions at slipped open and subtract fees.
2. Recompute cash.
3. Buy increases at slipped open and subtract fees.
4. Scale buys proportionally when cash is insufficient.
5. Never allow negative cash.

The daily equity curve uses each asset's latest known CNY close on or before the portfolio date. It must not forward-fill beyond a configurable stale-price limit of 7 calendar days; when exceeded, flag the day in diagnostics.

Record each rebalance:

- signal month.
- execution date.
- prior and target weights.
- trades and transaction cost.
- trend states.
- volatility estimates.
- cap hits.
- reasons for cash or bond allocation.

**Step 4: Run tests to verify they pass**

Run the same pytest selection.

Expected: PASS.

**Step 5: Run the complete research test file**

```bash
cd backend
uv run pytest tests/test_research_multi_asset_balanced_portfolio.py -v
```

Expected: all tests PASS.

**Step 6: Commit**

```bash
git add scripts/research_multi_asset_balanced_portfolio.py backend/tests/test_research_multi_asset_balanced_portfolio.py
git commit -m "research: simulate monthly multi-asset portfolios"
```

### Task 6: Add Metrics, DCA Accounting, and Product Gates

**Files:**
- Modify: `scripts/research_multi_asset_balanced_portfolio.py`
- Modify: `backend/tests/test_research_multi_asset_balanced_portfolio.py`

**Step 1: Write failing metric tests**

Cover:

- CAGR.
- maximum drawdown.
- longest recovery period.
- annualized volatility.
- Sharpe, Sortino, Calmar.
- rolling 3/5-year windows.
- time-weighted versus money-weighted DCA reporting.
- hard rejection above 20% drawdown.

Example:

```python
def test_product_gate_rejects_drawdown_above_twenty_percent():
    module = load_research_module()
    verdict = module.evaluate_product_gate({
        "cagrPct": 10.0,
        "maxDrawdownPct": 20.01,
        "worstRolling3YearReturnPct": 5.0,
    })

    assert verdict["eligible"] is False
    assert "hard_drawdown_limit" in verdict["failedGates"]


def test_dca_principal_is_not_counted_as_strategy_return():
    module = load_research_module()
    result = module.summarize_dca(
        contributions=[{"date": "2025-01-01", "amount": 1000}, {"date": "2025-02-01", "amount": 1000}],
        ending_value=2100,
        time_weighted_return_pct=5.0,
    )

    assert result["principal"] == 2000
    assert result["profit"] == 100
    assert result["timeWeightedReturnPct"] == 5.0
```

**Step 2: Run tests to verify they fail**

```bash
cd backend
uv run pytest tests/test_research_multi_asset_balanced_portfolio.py -k "product_gate or dca or drawdown or recovery or rolling" -v
```

Expected: FAIL with missing metric helpers.

**Step 3: Implement metrics**

Implement:

- `summarize_equity_curve(curve)`.
- `annual_stats(curve)`.
- `rolling_window_stats(curve, years)`.
- `drawdown_recovery_stats(curve)`.
- `risk_contribution_stats(returns, weights)`.
- `return_contribution_stats(...)`.
- `summarize_dca(...)`.
- `evaluate_product_gate(summary)`.

Gate output:

```json
{
  "eligible": false,
  "targetReturnMet": false,
  "targetDrawdownMet": false,
  "hardDrawdownMet": true,
  "failedGates": [],
  "notes": []
}
```

Rules:

- CAGR 8%～12% is the target band, not a guarantee.
- Drawdown <=15% meets target.
- Drawdown >20% is an automatic rejection.
- Results with less than 5 years of common investable history cannot be productized.
- Missing rolling-window or recovery metrics produce `eligible: false`, not optimistic defaults.

For DCA, simulate a fixed monthly CNY contribution into the same target allocation. Report principal, ending value, profit, money-weighted return when calculable, and strategy time-weighted return separately.

**Step 4: Run tests to verify they pass**

Run the same pytest selection.

Expected: PASS.

**Step 5: Commit**

```bash
git add scripts/research_multi_asset_balanced_portfolio.py backend/tests/test_research_multi_asset_balanced_portfolio.py
git commit -m "research: add balanced portfolio metrics and gates"
```

### Task 7: Build the Fixed Variant Matrix and Benchmarks

**Files:**
- Modify: `scripts/research_multi_asset_balanced_portfolio.py`
- Modify: `backend/tests/test_research_multi_asset_balanced_portfolio.py`

**Step 1: Write the failing variant-matrix test**

```python
def test_variant_matrix_reports_every_predeclared_parameter_combination():
    module = load_research_module()
    variants = module.build_variant_specs()

    keys = {row["id"] for row in variants}
    assert "static_risk_budget_vol60_btc0" in keys
    assert "trend_ma10_vol60_btc5" in keys
    assert "trend_mom12_vol120_btc10" in keys
    assert "trend_combined_vol120_btc5" in keys
    assert "trend_combined_vol120_btc5_rs_top1" in keys
```

Also assert that all three trend modes, both volatility windows, both rebalance modes, and all BTC caps are represented. Do not allow the script to generate only a selected best subset.

**Step 2: Run the test to verify it fails**

```bash
cd backend
uv run pytest tests/test_research_multi_asset_balanced_portfolio.py::test_variant_matrix_reports_every_predeclared_parameter_combination -v
```

Expected: FAIL with missing matrix builder.

**Step 3: Implement variants and benchmarks**

Implement `build_variant_specs()` and orchestration for:

- Static risk budget at 60/120-day volatility.
- Trend modes `ma10`, `mom12`, `ma10_and_mom12`.
- 60/120-day volatility.
- Full monthly rebalance and 5-point drift threshold.
- BTC caps 0%, 5%, 10%.
- RS enhancement with A-share top 1/top 2 and optional SPY/QQQ tilt.

Benchmarks:

- SPY buy-and-hold in CNY.
- QQQ buy-and-hold in CNY.
- Fixed monthly SPY DCA in CNY.
- Fixed monthly QQQ DCA in CNY.
- Static allocation: 20% A-share broad equal weight, 30% US equity split equally, 20% GLD, 30% A bond.
- Static inverse-volatility portfolio.
- Existing global RS + monthly MACD, clearly labeled as using its existing non-CNY production research implementation unless converted separately.

Do not rank DCA account value against lump-sum total return.

**Step 4: Run tests to verify they pass**

Run:

```bash
cd backend
uv run pytest tests/test_research_multi_asset_balanced_portfolio.py -v
```

Expected: all tests PASS.

**Step 5: Commit**

```bash
git add scripts/research_multi_asset_balanced_portfolio.py backend/tests/test_research_multi_asset_balanced_portfolio.py
git commit -m "research: define balanced portfolio experiment matrix"
```

### Task 8: Generate the Research Artifacts and Verdict

**Files:**
- Modify: `scripts/research_multi_asset_balanced_portfolio.py`
- Create: `backend/backtest_results/multi_asset_balanced_portfolio_2026-06-06.json`
- Create: `docs/multi-asset-balanced-portfolio-research-2026-06-06.md`
- Modify: `backend/tests/test_research_multi_asset_balanced_portfolio.py`

**Step 1: Write failing report tests**

Test report structure from a small fixture payload:

```python
def test_render_report_includes_failed_candidates_and_coverage_limitations():
    module = load_research_module()
    markdown = module.render_markdown_report({
        "coverage": {"commonStartDate": "2015-01-01", "missingStressPeriods": ["2008"]},
        "variants": [
            {"id": "bad", "summary": {"cagrPct": 9.0, "maxDrawdownPct": 25.0}, "gate": {"eligible": False}}
        ],
        "benchmarks": [],
        "recommendation": {"status": "no_eligible_default"}
    })

    assert "2008" in markdown
    assert "bad" in markdown
    assert "没有合格默认策略" in markdown
```

**Step 2: Run the test to verify it fails**

```bash
cd backend
uv run pytest tests/test_research_multi_asset_balanced_portfolio.py::test_render_report_includes_failed_candidates_and_coverage_limitations -v
```

Expected: FAIL with missing report renderer.

**Step 3: Implement JSON and Markdown output**

The JSON must include:

- Inputs and fixed assumptions.
- Data coverage by symbol.
- Common investable period.
- Missing stress periods.
- Every variant, not only the best.
- Benchmarks.
- Full-period, 3/5/10-year, annual, rolling 3/5-year metrics.
- Rebalance logs.
- Turnover and costs.
- Currency contribution.
- Asset/category return and risk contributions.
- BTC marginal comparison.
- Product gate result.

The Markdown report must contain:

1. Plain-language conclusion.
2. Data coverage and limitations.
3. Fixed assumptions.
4. Candidate comparison table.
5. Benchmark table.
6. BTC 0/5/10 sensitivity.
7. Trend and volatility parameter stability.
8. Annual and rolling-window results.
9. Drawdown and recovery analysis.
10. Cost and turnover analysis.
11. Lump-sum versus DCA results with distinct accounting.
12. Productization verdict.

If no strategy passes, write:

```text
当前没有合格默认策略。
```

Do not substitute language such as "closest winner" in the recommendation field. A near miss can be listed as further research only.

**Step 4: Run report tests**

Run:

```bash
cd backend
uv run pytest tests/test_research_multi_asset_balanced_portfolio.py -v
```

Expected: all tests PASS.

**Step 5: Run the full research**

```bash
cd /Users/zz/Downloads/trading/backend
PYTHONPATH=. uv run python ../scripts/research_multi_asset_balanced_portfolio.py \
  --config universes/multi_asset_balanced.json \
  --data-dir data \
  --end 2026-06-06 \
  --output backtest_results/multi_asset_balanced_portfolio_2026-06-06.json \
  --report ../docs/multi-asset-balanced-portfolio-research-2026-06-06.md
```

Expected:

- Both output files are created.
- No variant is omitted.
- The report states the actual common start date.
- 2008 is marked unavailable when the investable universe does not cover it.
- Every result has a gate verdict.

**Step 6: Inspect the top-level output**

```bash
cd /Users/zz/Downloads/trading/backend
jq '{
  coverage: .coverage,
  recommendation: .recommendation,
  eligible: [.variants[] | select(.gate.eligible == true) | .id],
  hardFailures: [.variants[] | select(.summary.maxDrawdownPct > 20) | .id]
}' backtest_results/multi_asset_balanced_portfolio_2026-06-06.json
```

Expected: valid JSON with no missing gate fields.

**Step 7: Commit**

```bash
git add \
  scripts/research_multi_asset_balanced_portfolio.py \
  backend/tests/test_research_multi_asset_balanced_portfolio.py \
  backend/backtest_results/multi_asset_balanced_portfolio_2026-06-06.json \
  docs/multi-asset-balanced-portfolio-research-2026-06-06.md
git commit -m "research: evaluate multi-asset balanced portfolios"
```

### Task 9: Run Final Regression Verification

**Files:**
- Verify only; no planned edits.

**Step 1: Run the focused research tests**

```bash
cd backend
uv run pytest tests/test_research_multi_asset_balanced_portfolio.py -v
```

Expected: PASS.

**Step 2: Run existing backtest and research regressions**

```bash
cd backend
uv run pytest \
  tests/test_backtest.py \
  tests/test_research_rs_rotation_robustness.py \
  tests/test_research_rs_rotation_lookahead_audit.py \
  tests/test_research_a_share_dca_timing.py \
  tests/test_research_multi_asset_balanced_portfolio.py \
  -v
```

Expected: PASS, with only previously documented data-dependent skips.

**Step 3: Validate formatting and repository state**

```bash
git diff --check
git status --short
```

Expected:

- `git diff --check` has no output.
- Worktree is clean after the final commit.

**Step 4: Review the result against the design**

Open:

- `docs/plans/2026-06-06-multi-asset-balanced-portfolio-design.md`
- `docs/multi-asset-balanced-portfolio-research-2026-06-06.md`

Confirm:

- No leverage or shorting.
- CNY accounting includes FX.
- BTC 0/5/10 all reported.
- 15% target and 20% hard drawdown gates are unchanged.
- Failed variants remain visible.
- No production strategy, API, or frontend default changed.
