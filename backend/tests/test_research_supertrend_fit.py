import importlib.util
from pathlib import Path

import pandas as pd


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "research_supertrend_fit.py"
SPEC = importlib.util.spec_from_file_location("research_supertrend_fit", SCRIPT_PATH)
research_supertrend_fit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(research_supertrend_fit)


def test_walk_forward_windows_use_two_year_train_and_future_six_month_test():
    windows = research_supertrend_fit._build_walk_forward_windows(
        "2021-01-01",
        "2024-01-15",
        train_years=2,
        test_months=6,
        step_months=6,
    )

    assert windows == [
        {
            "trainStart": "2021-01-01",
            "trainEnd": "2023-01-01",
            "testStart": "2023-01-02",
            "testEnd": "2023-07-01",
        },
        {
            "trainStart": "2021-07-01",
            "trainEnd": "2023-07-01",
            "testStart": "2023-07-02",
            "testEnd": "2024-01-01",
        },
    ]


def test_safe_rdd_uses_minimum_drawdown_denominator():
    assert research_supertrend_fit._safe_rdd(10.0, 0.0) == 2.0
    assert research_supertrend_fit._safe_rdd(10.0, 2.0) == 2.0
    assert research_supertrend_fit._safe_rdd(10.0, 10.0) == 1.0


def test_insufficient_trade_penalty_requires_at_least_two_training_trades():
    assert research_supertrend_fit._insufficient_trade_penalty(0) == 1.0
    assert research_supertrend_fit._insufficient_trade_penalty(1) == 0.5
    assert research_supertrend_fit._insufficient_trade_penalty(2) == 0.0
    assert research_supertrend_fit._insufficient_trade_penalty(5) == 0.0


def test_assign_tiers_ranks_per_asset_bucket_and_marks_low_sample():
    rows = [
        {"symbol": "A", "assetBucket": "a_share_stock", "historyScore": 3.0},
        {"symbol": "B", "assetBucket": "a_share_stock", "historyScore": 2.0},
        {"symbol": "C", "assetBucket": "a_share_stock", "historyScore": 1.0},
        {"symbol": "D", "assetBucket": "us_etf", "historyScore": 2.0},
        {"symbol": "E", "assetBucket": "us_etf", "historyScore": 1.0},
    ]

    ranked = research_supertrend_fit._assign_tiers(rows, "historyScore", "history")
    by_symbol = {row["symbol"]: row for row in ranked}

    assert by_symbol["A"]["historyTier"] == "top"
    assert by_symbol["B"]["historyTier"] == "mid"
    assert by_symbol["C"]["historyTier"] == "bottom"
    assert by_symbol["A"]["historyRank"] == 1
    assert by_symbol["A"]["historyPercentile"] == 1.0
    assert by_symbol["C"]["historyPercentile"] == 1 / 3

    assert by_symbol["D"]["historyTier"] == "top"
    assert by_symbol["E"]["historyTier"] == "bottom"
    assert by_symbol["D"]["historyLowSample"] is True


def test_robust_normalize_rows_uses_provided_training_cohort_only():
    rows = [
        {"symbol": "A", "normalizationCohort": "a_share", "raw": 1.0},
        {"symbol": "B", "normalizationCohort": "a_share", "raw": 2.0},
        {"symbol": "C", "normalizationCohort": "a_share", "raw": 3.0},
        {"symbol": "D", "normalizationCohort": "us", "raw": 100.0},
    ]

    normalized = research_supertrend_fit._robust_normalize_rows(rows, ["raw"])
    by_symbol = {row["symbol"]: row for row in normalized}

    assert by_symbol["A"]["rawZ"] < 0
    assert by_symbol["B"]["rawZ"] == 0
    assert by_symbol["C"]["rawZ"] > 0
    assert by_symbol["D"]["rawZ"] == 0


def test_history_raw_fields_compute_excess_metrics_and_trade_reliability():
    row = research_supertrend_fit._history_raw_fields(
        {
            "dailySt": {
                "returnPct": 20.0,
                "maxDrawdownPct": 10.0,
                "tradeCount": 2,
                "winRatePct": 50.0,
                "averageTradeReturnPct": 5.0,
            },
            "buyHold": {"returnPct": 10.0, "maxDrawdownPct": 20.0},
        }
    )

    assert row["trainDailyStRddSafe"] == 2.0
    assert row["trainBuyHoldRddSafe"] == 0.5
    assert row["excessRddSafe"] == 1.5
    assert row["drawdownReductionPct"] == 0.5
    assert row["trainTradeCount"] == 2
    assert row["tradeReliability"] == 0.5
    assert row["insufficientTradePenalty"] == 0.0


def _shape_prices(periods=180):
    index = pd.date_range("2022-01-01", periods=periods, freq="D")
    close = pd.Series([100.0 + i * 0.2 for i in range(periods)], index=index)
    return pd.DataFrame(
        {
            "Open": close.shift(1).fillna(close.iloc[0]),
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": [1000] * periods,
        },
        index=index,
    )


def test_compute_shape_features_uses_only_training_window_rows():
    base = _shape_prices()
    future = pd.DataFrame(
        {
            "Open": [5000.0],
            "High": [6000.0],
            "Low": [4000.0],
            "Close": [5500.0],
            "Volume": [1000],
        },
        index=[pd.Timestamp("2022-07-15")],
    )

    features = research_supertrend_fit._compute_shape_features(base, "2022-01-01", "2022-06-15")
    features_with_future = research_supertrend_fit._compute_shape_features(
        pd.concat([base, future]).sort_index(),
        "2022-01-01",
        "2022-06-15",
    )

    assert features == features_with_future


def test_score_rows_outputs_history_shape_and_hybrid_components():
    rows = [
        {
            "symbol": "A",
            "assetBucket": "a_share_stock",
            "normalizationCohort": "a_share",
            "dailySt": {
                "returnPct": 20.0,
                "maxDrawdownPct": 10.0,
                "tradeCount": 4,
                "winRatePct": 50.0,
                "averageTradeReturnPct": 5.0,
            },
            "buyHold": {"returnPct": 10.0, "maxDrawdownPct": 20.0},
            "shapeFeatures": {
                "trendEfficiency63Median": 0.5,
                "adx14TrendShare": 0.8,
                "emaBullPersistence": 0.7,
                "stFlipRatePerYear": 2.0,
                "atrPctIqrOverMedian": 0.1,
            },
        },
        {
            "symbol": "B",
            "assetBucket": "a_share_stock",
            "normalizationCohort": "a_share",
            "dailySt": {
                "returnPct": 0.0,
                "maxDrawdownPct": 20.0,
                "tradeCount": 1,
                "winRatePct": 0.0,
                "averageTradeReturnPct": -2.0,
            },
            "buyHold": {"returnPct": 10.0, "maxDrawdownPct": 20.0},
            "shapeFeatures": {
                "trendEfficiency63Median": 0.2,
                "adx14TrendShare": 0.2,
                "emaBullPersistence": 0.1,
                "stFlipRatePerYear": 8.0,
                "atrPctIqrOverMedian": 1.0,
            },
        },
    ]

    scored = research_supertrend_fit._score_rows(rows)
    by_symbol = {row["symbol"]: row for row in scored}

    assert by_symbol["A"]["historyScore"] > by_symbol["B"]["historyScore"]
    assert by_symbol["A"]["shapeScore"] > by_symbol["B"]["shapeScore"]
    assert by_symbol["A"]["hybridScore"] > by_symbol["B"]["hybridScore"]
    assert by_symbol["A"]["historyContribution"] == 0.60 * by_symbol["A"]["adjustedHistoryScore"]
    assert by_symbol["A"]["shapeContribution"] == 0.40 * by_symbol["A"]["shapeScore"]
    assert by_symbol["B"]["insufficientTradePenalty"] == 0.5


def test_spearman_handles_ties_and_empty_inputs():
    assert research_supertrend_fit._spearman([], []) is None
    assert research_supertrend_fit._spearman([1, 2, 3], [1, 2, 3]) == 1.0
    assert research_supertrend_fit._spearman([1, 2, 3], [3, 2, 1]) == -1.0
    assert research_supertrend_fit._spearman([1, 1, 2], [3, 2, 1]) < 0


def test_summarize_score_mode_reports_tiers_and_top_bottom_spread():
    rows = [
        {
            "symbol": "A",
            "assetBucket": "a_share_stock",
            "historyScore": 3.0,
            "historyTier": "top",
            "testExcessRddSafe": 2.0,
            "testDailyStReturnPct": 10.0,
            "testDailyStMaxDrawdownPct": 5.0,
            "testBeatBuyHoldRdd": True,
        },
        {
            "symbol": "B",
            "assetBucket": "a_share_stock",
            "historyScore": 2.0,
            "historyTier": "mid",
            "testExcessRddSafe": 1.0,
            "testDailyStReturnPct": 5.0,
            "testDailyStMaxDrawdownPct": 6.0,
            "testBeatBuyHoldRdd": False,
        },
        {
            "symbol": "C",
            "assetBucket": "a_share_stock",
            "historyScore": 1.0,
            "historyTier": "bottom",
            "testExcessRddSafe": -1.0,
            "testDailyStReturnPct": -5.0,
            "testDailyStMaxDrawdownPct": 8.0,
            "testBeatBuyHoldRdd": False,
        },
    ]

    summary = research_supertrend_fit._summarize_score_mode(rows, "history")
    bucket = summary["byAssetBucket"]["a_share_stock"]

    assert bucket["tiers"]["top"]["symbolCount"] == 1
    assert bucket["tiers"]["top"]["avgTestExcessRddSafe"] == 2.0
    assert bucket["topMinusBottom"]["testExcessRddSafe"] == 3.0
    assert bucket["rankCorrelation"] == 1.0


def test_build_window_rows_scores_before_validation_metrics(monkeypatch):
    meta = {"symbol": "AAA", "assetBucket": "a_share_stock", "alias": "", "group": "test"}
    daily = _shape_prices(periods=220)
    weekly = daily.resample("W").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    )
    calls = []

    def fake_analyze(meta_arg, daily_arg, weekly_arg, start, end, **kwargs):
        calls.append((start, end))
        if start == "2022-01-01":
            return {
                **meta_arg,
                "assetBucket": "a_share_stock",
                "dailySt": {
                    "returnPct": 20.0,
                    "maxDrawdownPct": 10.0,
                    "tradeCount": 4,
                    "winRatePct": 50.0,
                    "averageTradeReturnPct": 5.0,
                },
                "buyHold": {"returnPct": 10.0, "maxDrawdownPct": 20.0},
            }
        return {
            **meta_arg,
            "assetBucket": "a_share_stock",
            "dailySt": {
                "returnPct": -99.0,
                "maxDrawdownPct": 99.0,
                "tradeCount": 1,
                "winRatePct": 0.0,
                "averageTradeReturnPct": -99.0,
            },
            "buyHold": {"returnPct": 1.0, "maxDrawdownPct": 5.0},
        }

    monkeypatch.setattr(research_supertrend_fit.compare_st, "_analyze_symbol_from_data", fake_analyze)
    window = {
        "trainStart": "2022-01-01",
        "trainEnd": "2022-06-01",
        "testStart": "2022-06-02",
        "testEnd": "2022-08-01",
    }

    rows = research_supertrend_fit._build_window_rows(
        [{"meta": meta, "daily": daily, "weekly": weekly}],
        window,
    )

    assert calls == [("2022-01-01", "2022-06-01"), ("2022-06-02", "2022-08-01")]
    assert rows[0]["trainDailyStReturnPct"] == 20.0
    assert rows[0]["testDailyStReturnPct"] == -99.0
    assert rows[0]["historyScore"] > -1.0
