# SuperTrend Position Sizing Research Design

## Goal

Research whether SuperTrend is more useful as a portfolio exposure and drawdown control layer than as a symbol fit screener.

The first version focuses on A-share ETF RS rotation because the project already has a tested A-share ETF universe, long local parquet cache, and an existing RS rotation baseline.

## Hypothesis

SuperTrend should not select symbols. RS rotation selects symbols. SuperTrend controls how much capital is exposed to the selected symbols.

Expected benefit:

- lower max drawdown
- shorter bad-year damage
- similar or better return/drawdown ratio
- acceptable return retention

## Data

Use only local files:

- `backend/universes/a_share_etf_core.json`
- `backend/data/*.parquet`
- `510300.SS` as the A-share market proxy

No data download.

## Baselines

1. `rs_monthly_macd_baseline`
   - Existing RS rotation style.
   - Top 5.
   - 20 trading day rebalance.
   - 60 bar lookback.
   - CSI300 monthly MACD filter.
   - Volume filter: 1e8.

2. `rs_no_filter_reference`
   - Same RS rotation, no market filter.
   - Used only to understand what the current monthly MACD filter is doing.

## ST Position Variants

### Market ST Exposure

RS still ranks and selects top 5 ETFs. Market SuperTrend decides total portfolio exposure.

Market proxy: `510300.SS`.

Use default `ST(7,3)` on daily and weekly bars.

Exposure table:

| Weekly ST | Daily ST | Total exposure |
|---|---|---:|
| bull | bull | 1.00 |
| bull | bear | 0.50 |
| bear | bull | 0.50 |
| bear | bear | 0.25 |

The uninvested part stays cash.

### Market + Symbol ST Exposure

First apply market exposure. Then each selected ETF gets a symbol-level multiplier:

| Symbol daily ST | Symbol multiplier |
|---|---:|
| bull | 1.00 |
| bear | 0.00 |

Final per-slot allocation:

```text
slot_allocation = portfolio_value / top_n * market_exposure * symbol_multiplier
```

This tests whether ST should also suppress weak selected ETFs, or whether market-level exposure is enough.

## Anti-Look-Ahead Rule

At each rebalance date, ranking and ST state use data with index `<= rebalance_date`. No future bar can affect:

- RS ranking
- market ST exposure
- symbol ST multiplier
- rebalance target holdings

The simulation uses the same close-on-or-before execution style as existing RS rotation research.

## Metrics

Portfolio-level:

- total return
- max drawdown
- return/drawdown ratio
- return retention vs current monthly MACD baseline
- drawdown reduction vs current monthly MACD baseline
- average exposure
- cash days / low-exposure days

Annual:

- return
- max drawdown
- average exposure
- worst-year behavior

Decision gates:

```text
Promising if:
- max drawdown improves by at least 20%, and
- total return retains at least 70% of baseline, and
- return/drawdown ratio improves.
```

## Output

Create:

- `scripts/research_st_position_sizing.py`
- `backend/tests/test_research_st_position_sizing.py`
- `docs/supertrend-position-sizing-research-2026-06-05.md`

JSON output is written to ignored local results:

- `backend/backtest_results/supertrend_position_sizing_2026-06-05.json`

## Product Boundary

This remains research only. If the ST exposure layer works, productization should start as a read-only portfolio research view before changing live defaults.
