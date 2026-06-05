# SuperTrend Fit Research Design

## Goal

Build an offline SuperTrend fit-screening study for the current watchlist and local parquet cache. The study scores each symbol using only the prior two years of data, then validates the score on the next six months. It compares A-share and US stocks/ETFs separately and avoids look-ahead bias.

## Scope

Use only:

- `backend/watchlist.json`
- `backend/data/*.parquet`
- Existing SuperTrend execution semantics from `scripts/compare_supertrend_timeframes.py`

Do not download new data. Do not change backend API behavior, frontend behavior, or production strategy defaults.

## Walk-Forward Window

Each window has:

- Training period: two years ending at `trainEnd`
- Validation period: six months after `trainEnd`
- Step: six months

The script computes all scores from `trainStart <= date <= trainEnd`. The validation window starts after `trainEnd`; validation returns, drawdowns, trades, ranks, and distributions must not influence scoring, normalization, tiering, or weights.

## Asset Buckets

Reuse `_asset_bucket()` from `scripts/compare_supertrend_timeframes.py`:

- `a_share_etf`
- `a_share_stock`
- `us_etf`
- `us_stock`

Crypto and commodity rows may remain in raw output if present, but the report focuses on A-share and US stock/ETF buckets.

## Strategy Under Test

First version predicts fit for default daily SuperTrend `ST(7,3)`.

Do not mix parameter selection into this study. `ST(10,3)` for individual stocks remains a separate sensitivity question from prior reports.

## Score Modes

The research script should calculate three scores on the same walk-forward windows.

### History Score

Uses training-period SuperTrend results versus buy-and-hold.

Raw fields:

- `excessRddSafe = stRddSafe - buyHoldRddSafe`
- `drawdownReductionPct = (buyHoldMaxDrawdownPct - stMaxDrawdownPct) / max(buyHoldMaxDrawdownPct, 5.0)`
- `excessLogReturn = log(max(0.01, 1 + stReturnPct / 100)) - log(max(0.01, 1 + buyHoldReturnPct / 100))`
- `avgTradeReturnPct`

Normalize raw fields inside the current training cohort, then:

```text
historyScore =
  0.45 * z(excessRddSafe)
+ 0.25 * z(drawdownReductionPct)
+ 0.20 * z(excessLogReturn)
+ 0.10 * z(avgTradeReturnPct)
```

Apply reliability adjustment:

```text
tradeReliability = min(1.0, trainTradeCount / 4)
adjustedHistoryScore = historyScore * tradeReliability
```

### Shape Score

Uses training-period OHLCV shape features, not training ST returns.

Core features:

- `trendEfficiency63Median`: median 63-day directional efficiency.
- `adx14TrendShare`: share of training days with ADX(14) >= 20.
- `emaBullPersistence`: share of days where `Close > EMA50` and `EMA20 > EMA50`.
- `stFlipRatePerYear`: ST direction flips per year.
- `atrPctIqrOverMedian`: IQR of `ATR14 / Close` divided by its median.

Normalize raw fields inside the current training cohort, then:

```text
shapeScore =
  0.30 * z(trendEfficiency63Median)
+ 0.25 * z(adx14TrendShare)
+ 0.20 * z(emaBullPersistence)
+ 0.15 * z(-stFlipRatePerYear)
+ 0.10 * z(-atrPctIqrOverMedian)
```

### Hybrid Score

Fixed formula:

```text
hybridScore = 0.60 * adjustedHistoryScore + 0.40 * shapeScore - insufficientTradePenalty
```

Where:

```text
insufficientTradePenalty =
  1.00 if trainTradeCount == 0
  0.50 if trainTradeCount == 1
  0.00 if trainTradeCount >= 2
```

Do not fit weights from results. Do not tune weights after seeing validation output.

## Normalization

Use robust normalization per walk-forward window.

For each raw feature:

```text
winsorized = clip(raw, cohort_p05, cohort_p95)
robustZ = (winsorized - cohort_median) / max(IQR / 1.349, epsilon)
normalized = clip(robustZ, -3, 3) / 3
```

Preferred normalization cohort is `assetBucket`. If a bucket has fewer than eight rows, normalize by parent market cohort:

- `a_share_etf` and `a_share_stock` -> `a_share`
- `us_etf` and `us_stock` -> `us`

Final tiering and summaries remain by exact asset bucket.

## Tiering

For each score mode and each walk-forward window, sort rows inside each asset bucket:

- `top`: top third
- `mid`: middle third
- `bottom`: bottom third

For small buckets, keep deterministic ranking and set `lowSample=true`. US ETF will be low-sample in the current watchlist.

## Validation Metrics

Validation fields:

- `testDailyStReturnPct`
- `testDailyStMaxDrawdownPct`
- `testDailyStRddSafe`
- `testBuyHoldReturnPct`
- `testBuyHoldMaxDrawdownPct`
- `testBuyHoldRddSafe`
- `testExcessRddSafe`
- `testExcessLogReturn`
- `testBeatBuyHoldReturn`
- `testBeatBuyHoldRdd`
- `testTradeCount`

Summaries by score mode, asset bucket, and tier:

- average and median `testExcessRddSafe`
- average and median ST return
- average max drawdown
- beat buy-and-hold R/DD rate
- top-minus-bottom spread
- Spearman rank correlation between score and validation `testExcessRddSafe`

## Output

Create:

- `backend/backtest_results/supertrend_fit_research_2026-06-05.json`
- `docs/supertrend-fit-research-2026-06-05.md`

JSON shape:

```text
params
windows[]
rows[]
summary
```

Rows should expose score components so the report can distinguish history-driven, shape-driven, and hybrid-driven rankings.

## Testing

Add tests for:

- walk-forward windows: two-year training, six-month future validation, no overlap
- robust normalization uses only the current training cohort
- history score penalizes low training trade count
- shape score does not depend on training ST returns
- hybrid output includes history and shape contributions
- tier assignment happens before validation metrics are summarized
- small buckets do not crash and are marked `lowSample`

## Decision Boundary

This is not machine learning. It is a fixed heuristic scoring study with sample-out validation. A future ML baseline may be considered only after this study shows that training-period features contain useful out-of-sample signal.
