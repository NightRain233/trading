import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from backtest import load_universe_symbols
from backtest import annotate_relative_strength
from backtest import evaluate_weekly_bb_pullback
from backtest import run_backtest_for_symbol
from backtest import run_supertrend_backtest
from backtest import resolve_market_settings
from backtest import simulate_closed_trade_portfolio
from backtest import simulate_mark_to_market_portfolio
from backtest import summarize_buy_and_hold_benchmark
from backtest import summarize_backtest_report
from backtest import summarize_trades
from strategy_versions import get_strategy_version


def _build_backtest_daily_df() -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=36, freq="B")
    signal_idx = 24
    entry_idx = signal_idx + 1

    ema50 = [100.0] * len(dates)
    ema20 = [99.0 if i < 10 else 101.0 + i * 0.03 for i in range(len(dates))]
    ema10 = [101.2 + i * 0.05 for i in range(len(dates))]
    ema5 = [101.5 + i * 0.06 for i in range(len(dates))]
    close = [103.0] * len(dates)
    open_ = [103.0] * len(dates)
    high = [104.0] * len(dates)
    low = [102.0] * len(dates)
    volume = [1000.0] * len(dates)
    atr = [2.0] * len(dates)

    low[signal_idx] = ema10[signal_idx] - 0.2
    close[signal_idx] = ema10[signal_idx] + 0.2
    high[signal_idx] = close[signal_idx] + 0.4
    volume[signal_idx] = 600.0

    open_[entry_idx] = close[signal_idx] + 0.1
    high[entry_idx] = close[signal_idx] + 6.2
    low[entry_idx] = close[signal_idx] - 0.2
    close[entry_idx] = close[signal_idx] + 5.8

    return pd.DataFrame(
        {
            "Open": open_,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": volume,
            "EMA5": ema5,
            "EMA10": ema10,
            "EMA20": ema20,
            "EMA50": ema50,
            "ATR": atr,
            "MACD_DIF": [0.3] * len(dates),
            "MACD_DEA": [0.2] * len(dates),
        },
        index=dates,
    )


def _build_trend_runner_daily_df() -> pd.DataFrame:
    daily = _build_backtest_daily_df()
    signal_idx = 24
    entry_idx = signal_idx + 1
    for idx in range(entry_idx, len(daily)):
        daily.iloc[idx, daily.columns.get_loc("Open")] = 104.0 + (idx - entry_idx) * 1.2
        daily.iloc[idx, daily.columns.get_loc("Close")] = 105.0 + (idx - entry_idx) * 1.2
        daily.iloc[idx, daily.columns.get_loc("High")] = 106.0 + (idx - entry_idx) * 1.2
        daily.iloc[idx, daily.columns.get_loc("Low")] = 103.5 + (idx - entry_idx) * 1.2
        daily.iloc[idx, daily.columns.get_loc("EMA20")] = 101.0 + idx * 0.03
        daily.iloc[idx, daily.columns.get_loc("EMA50")] = 100.0
    warn_idx = 31
    daily.iloc[warn_idx, daily.columns.get_loc("Open")] = 116.0
    daily.iloc[warn_idx, daily.columns.get_loc("High")] = 117.0
    daily.iloc[warn_idx, daily.columns.get_loc("Low")] = 112.0
    daily.iloc[warn_idx, daily.columns.get_loc("Close")] = 114.0
    daily.iloc[warn_idx, daily.columns.get_loc("EMA20")] = 115.0
    daily.iloc[warn_idx, daily.columns.get_loc("EMA50")] = 100.0
    return daily


def _build_backtest_weekly_df() -> pd.DataFrame:
    dates = pd.date_range("2024-12-29", periods=12, freq="W")
    return pd.DataFrame(
        {
            "MACD_W": [0.4] * len(dates),
            "MACD_Signal_W": [0.2] * len(dates),
            "MA5_W": [100.0] * len(dates),
        },
        index=dates,
    )


def _build_weekly_bb_pullback_df(latest_low: float = 101.0, latest_close: float = 103.0) -> pd.DataFrame:
    dates = pd.date_range("2025-01-05", periods=12, freq="W")
    close = [100.0] * len(dates)
    low = [99.0] * len(dates)
    upper = [110.0] * len(dates)
    mid = [100.0] * len(dates)
    lower = [90.0] * len(dates)
    ma30 = [95.0] * len(dates)

    close[-4] = 112.0
    low[-1] = latest_low
    close[-1] = latest_close

    return pd.DataFrame(
        {
            "Open": close,
            "High": [max(c, u) for c, u in zip(close, upper)],
            "Low": low,
            "Close": close,
            "BOLL_Upper": upper,
            "BOLL_Mid": mid,
            "BOLL_Lower": lower,
            "MA30": ma30,
        },
        index=dates,
    )


def _build_daily_pullback_confirmation_df(close: float = 105.0, pullback_low: float | None = None) -> pd.DataFrame:
    dates = pd.date_range("2025-03-17", periods=5, freq="B")
    lows = [close - 1.0] * len(dates)
    if pullback_low is not None:
        lows[-2] = pullback_low
    return pd.DataFrame(
        {
            "Open": [close] * len(dates),
            "High": [close + 1.0] * len(dates),
            "Low": lows,
            "Close": [close] * len(dates),
            "EMA20": [103.0] * len(dates),
            "MA30": [102.0] * len(dates),
        },
        index=dates,
    )


def _build_market_regime_df(bullish: bool = True) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=36, freq="B")
    if bullish:
        close = [110.0] * len(dates)
        ema20 = [105.0] * len(dates)
        ema50 = [100.0] * len(dates)
    else:
        close = [95.0] * len(dates)
        ema20 = [100.0] * len(dates)
        ema50 = [105.0] * len(dates)
    return pd.DataFrame(
        {
            "Close": close,
            "EMA20": ema20,
            "EMA50": ema50,
        },
        index=dates,
    )


def _build_supertrend_daily_df(adx_at_entry: float) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=5, freq="B")
    return pd.DataFrame(
        {
            "Open": [100.0, 100.0, 101.0, 103.0, 102.0],
            "High": [101.0, 101.0, 104.0, 105.0, 103.0],
            "Low": [99.0, 99.0, 100.5, 102.0, 98.0],
            "Close": [100.0, 100.0, 103.0, 104.0, 99.0],
            "ADX": [15.0, 15.0, adx_at_entry, 30.0, 30.0],
            "ATR": [2.0, 2.0, 4.0, 4.0, 4.0],
        },
        index=dates,
    )


def _build_supertrend_indicator(index: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "SUPERT_7_3.0": [101.0, 101.0, 98.0, 99.0, 100.0],
            "SUPERTd_7_3.0": [-1, -1, 1, 1, -1],
        },
        index=index,
    )


class BacktestTests(unittest.TestCase):
    def test_supertrend_adx_filter_skips_low_adx_flip(self):
        daily = _build_supertrend_daily_df(adx_at_entry=18.0)
        weekly = daily.copy()
        st = _build_supertrend_indicator(daily.index)
        weekly_st = pd.DataFrame(
            {
                "SUPERT_7_3.0": [98.0] * len(weekly),
                "SUPERTd_7_3.0": [1] * len(weekly),
            },
            index=weekly.index,
        )

        with patch("backtest.ta.supertrend", side_effect=[st, weekly_st]):
            trades = run_supertrend_backtest(
                "TEST",
                daily,
                filter_weekly_df=weekly,
                fee_bps=0,
                slippage_bps=0,
                min_adx_for_entry=25.0,
            )

        self.assertEqual(trades, [])

    def test_supertrend_adx_filter_allows_trending_flip(self):
        daily = _build_supertrend_daily_df(adx_at_entry=28.0)
        weekly = daily.copy()
        st = _build_supertrend_indicator(daily.index)
        weekly_st = pd.DataFrame(
            {
                "SUPERT_7_3.0": [98.0] * len(weekly),
                "SUPERTd_7_3.0": [1] * len(weekly),
            },
            index=weekly.index,
        )

        with patch("backtest.ta.supertrend", side_effect=[st, weekly_st]):
            trades = run_supertrend_backtest(
                "TEST",
                daily,
                filter_weekly_df=weekly,
                fee_bps=0,
                slippage_bps=0,
                min_adx_for_entry=25.0,
            )

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["strategyVersion"], "supertrend_adx_25")
        self.assertEqual(trades[0]["entryAdx"], 28.0)

    def test_supertrend_support_test_entry_enters_near_support(self):
        daily = _build_supertrend_daily_df(adx_at_entry=28.0)
        weekly = daily.copy()
        st = pd.DataFrame(
            {
                "SUPERT_7_3.0": [101.0, 101.0, 101.0, 101.0, 100.0],
                "SUPERTd_7_3.0": [-1, 1, 1, 1, -1],
            },
            index=daily.index,
        )
        weekly_st = pd.DataFrame(
            {
                "SUPERT_7_3.0": [98.0] * len(weekly),
                "SUPERTd_7_3.0": [1] * len(weekly),
            },
            index=weekly.index,
        )

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
        self.assertEqual(trades[0]["entryDate"], str(daily.index[2].date()))

    def test_supertrend_weekly_bull_support_test_rejects_weekly_bearish(self):
        daily = _build_supertrend_daily_df(adx_at_entry=28.0)
        weekly = daily.copy()
        st = pd.DataFrame(
            {
                "SUPERT_7_3.0": [101.0, 101.0, 101.0, 101.0, 100.0],
                "SUPERTd_7_3.0": [-1, 1, 1, 1, -1],
            },
            index=daily.index,
        )
        weekly_st = pd.DataFrame(
            {
                "SUPERT_7_3.0": [98.0] * len(weekly),
                "SUPERTd_7_3.0": [-1] * len(weekly),
            },
            index=weekly.index,
        )

        with patch("backtest.ta.supertrend", side_effect=[st, weekly_st]):
            trades = run_supertrend_backtest(
                "TEST",
                daily,
                filter_weekly_df=weekly,
                fee_bps=0,
                slippage_bps=0,
                entry_signal_mode="weekly_bull_support_test",
            )

        self.assertEqual(trades, [])

    def test_supertrend_daily_bull_flip_ignores_weekly_bearish_filter(self):
        daily = _build_supertrend_daily_df(adx_at_entry=28.0)
        weekly = daily.copy()
        st = _build_supertrend_indicator(daily.index)
        weekly_st = pd.DataFrame(
            {
                "SUPERT_7_3.0": [98.0] * len(weekly),
                "SUPERTd_7_3.0": [-1] * len(weekly),
            },
            index=weekly.index,
        )

        with patch("backtest.ta.supertrend", side_effect=[st, weekly_st]):
            trades = run_supertrend_backtest(
                "TEST",
                daily,
                filter_weekly_df=weekly,
                fee_bps=0,
                slippage_bps=0,
                entry_signal_mode="daily_bull_flip",
            )

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["entrySignalMode"], "daily_bull_flip")

    def test_supertrend_rejects_unknown_entry_signal_mode(self):
        daily = _build_supertrend_daily_df(adx_at_entry=28.0)

        with self.assertRaises(ValueError):
            run_supertrend_backtest(
                "TEST",
                daily,
                fee_bps=0,
                slippage_bps=0,
                entry_signal_mode="unknown_mode",
            )

    def test_weekly_bb_pullback_confirms_after_prior_breakout(self):
        weekly = _build_weekly_bb_pullback_df()
        daily = _build_daily_pullback_confirmation_df()

        signal = evaluate_weekly_bb_pullback(weekly, daily)

        self.assertTrue(signal["buySignal"])
        self.assertEqual(signal["poolType"], "weeklyBBPullback")
        self.assertEqual(signal["strategyVersion"], "weekly_bb_breakout_ma30")
        self.assertEqual(signal["entryType"], "weeklyPullback")
        self.assertAlmostEqual(signal["stopPrice"], 95.0)

    def test_weekly_bb_pullback_accepts_daily_ema20_pullback_after_prior_breakout(self):
        weekly = _build_weekly_bb_pullback_df(latest_low=108.0, latest_close=108.0)
        daily = _build_daily_pullback_confirmation_df(close=105.0, pullback_low=103.5)

        signal = evaluate_weekly_bb_pullback(weekly, daily)

        self.assertTrue(signal["buySignal"])
        self.assertEqual(signal["entryType"], "dailyPullback")
        self.assertEqual(signal["poolType"], "weeklyBBPullback")

    def test_weekly_bb_pullback_rejects_without_daily_reclaim(self):
        weekly = _build_weekly_bb_pullback_df()
        daily = _build_daily_pullback_confirmation_df(close=101.0)

        signal = evaluate_weekly_bb_pullback(weekly, daily)

        self.assertFalse(signal["buySignal"])

    def test_backtest_enters_next_bar_and_exits_on_target(self):
        daily = _build_backtest_daily_df()
        weekly = _build_backtest_weekly_df()

        trades = run_backtest_for_symbol(
            "TEST",
            daily,
            weekly,
            strategy_version="resonance_v2_atr_1_5",
            fee_bps=0,
            slippage_bps=0,
        )

        self.assertEqual(len(trades), 1)
        trade = trades[0]
        self.assertEqual(trade["symbol"], "TEST")
        self.assertEqual(trade["strategyVersion"], "resonance_v2_atr_1_5")
        self.assertEqual(trade["entryDate"], str(daily.index[25].date()))
        self.assertEqual(trade["exitReason"], "target")
        self.assertGreater(trade["returnPct"], 0)

    def test_backtest_summary_reports_core_metrics(self):
        daily = _build_backtest_daily_df()
        weekly = _build_backtest_weekly_df()
        trades = run_backtest_for_symbol("TEST", daily, weekly)

        summary = summarize_trades(trades, strategy_version="resonance_v2_atr_1_5")

        self.assertEqual(summary["strategyVersion"], "resonance_v2_atr_1_5")
        self.assertEqual(summary["tradeCount"], 1)
        self.assertEqual(summary["winRate"], 1.0)
        self.assertGreater(summary["averageReturnPct"], 0)
        self.assertIn("maxDrawdownPct", summary)
        self.assertEqual(summary["exitReasonCounts"], {"target": 1})

    def test_trend_runner_strategy_lets_winner_run_past_fixed_target(self):
        daily = _build_trend_runner_daily_df()
        weekly = _build_backtest_weekly_df()

        fixed_target_trades = run_backtest_for_symbol(
            "TEST",
            daily,
            weekly,
            strategy_version="resonance_v2_atr_2_0",
            fee_bps=0,
            slippage_bps=0,
        )
        trend_runner_trades = run_backtest_for_symbol(
            "TEST",
            daily,
            weekly,
            strategy_version="resonance_v3_trend_runner_csi300_entry_buffer_1_0_etf_established",
            fee_bps=0,
            slippage_bps=0,
        )

        self.assertEqual(fixed_target_trades[0]["exitReason"], "target")
        self.assertEqual(trend_runner_trades[0]["exitReason"], "warn_exit")
        self.assertGreater(trend_runner_trades[0]["returnPct"], fixed_target_trades[0]["returnPct"])

    def test_wide_target_strategy_uses_larger_profit_target(self):
        daily = _build_backtest_daily_df()
        weekly = _build_backtest_weekly_df()

        trades = run_backtest_for_symbol(
            "TEST",
            daily,
            weekly,
            strategy_version="resonance_v3_atr_2_0_8_0_csi300_entry_buffer_1_0_etf_established",
            fee_bps=0,
            slippage_bps=0,
        )

        self.assertEqual(len(trades), 1)
        self.assertGreater(trades[0]["targetPrice"] - trades[0]["stopPrice"], 15.0)

    def test_backtest_can_filter_by_entry_date_range(self):
        daily = _build_backtest_daily_df()
        weekly = _build_backtest_weekly_df()

        excluded = run_backtest_for_symbol(
            "TEST",
            daily,
            weekly,
            start="2025-03-01",
        )
        included = run_backtest_for_symbol(
            "TEST",
            daily,
            weekly,
            start="2025-01-01",
            end="2025-12-31",
        )

        self.assertEqual(excluded, [])
        self.assertEqual(len(included), 1)

    def test_load_universe_symbols_from_json_file(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "universe.json"
            path.write_text(
                """
                {
                  "name": "test-etfs",
                  "symbols": ["SPY", {"symbol": "QQQ"}, "SPY", "  "]
                }
                """
            )

            symbols = load_universe_symbols(str(path))

        self.assertEqual(symbols, ["SPY", "QQQ"])

    def test_strategy_version_market_symbol_is_used_when_cli_does_not_override(self):
        version = get_strategy_version("resonance_v2_atr_2_0_csi300_bullish_etf_established")

        market_filter, market_symbol = resolve_market_settings(
            cli_market_filter="none",
            cli_market_symbol=None,
            version=version,
        )

        self.assertEqual(market_filter, "bullish_ema")
        self.assertEqual(market_symbol, "000300.SS")

    def test_backtest_report_groups_by_pool_type_and_asset_class(self):
        trades = [
            {
                "symbol": "AAPL",
                "strategyVersion": "resonance_v2_atr_1_5",
                "poolType": "earlyTrend",
                "returnPct": 4.0,
                "holdingDays": 3,
                "exitReason": "target",
                "entryDate": "2025-01-03",
            },
            {
                "symbol": "SPY",
                "strategyVersion": "resonance_v2_atr_1_5",
                "poolType": "establishedTrend",
                "returnPct": -1.0,
                "holdingDays": 5,
                "exitReason": "hard_exit",
                "entryDate": "2025-02-03",
            },
            {
                "symbol": "BTC-USD",
                "strategyVersion": "resonance_v2_atr_1_5",
                "poolType": "earlyTrend",
                "returnPct": 2.0,
                "holdingDays": 2,
                "exitReason": "target",
                "entryDate": "2026-01-03",
            },
        ]

        report = summarize_backtest_report(trades, strategy_version="resonance_v2_atr_1_5")

        self.assertEqual(report["byPoolType"]["earlyTrend"]["tradeCount"], 2)
        self.assertEqual(report["byPoolType"]["establishedTrend"]["tradeCount"], 1)
        self.assertEqual(report["byAssetClass"]["stock"]["tradeCount"], 1)
        self.assertEqual(report["byAssetClass"]["etf"]["tradeCount"], 1)
        self.assertEqual(report["byAssetClass"]["crypto"]["tradeCount"], 1)
        self.assertEqual(report["byYear"]["2025"]["tradeCount"], 2)
        self.assertEqual(report["byYear"]["2026"]["tradeCount"], 1)
        self.assertEqual(report["symbolContribution"][0]["symbol"], "AAPL")
        self.assertEqual(report["symbolContribution"][0]["totalReturnPct"], 4.0)

    def test_buy_and_hold_benchmark_summarizes_symbols_and_equal_weight(self):
        first = pd.DataFrame(
            {"Open": [100.0, 110.0], "Close": [100.0, 120.0]},
            index=pd.to_datetime(["2025-01-01", "2025-01-10"]),
        )
        second = pd.DataFrame(
            {"Open": [50.0, 55.0], "Close": [50.0, 55.0]},
            index=pd.to_datetime(["2025-01-01", "2025-01-10"]),
        )

        benchmark = summarize_buy_and_hold_benchmark(
            {"AAA": first, "BBB": second},
            fee_bps=0,
            slippage_bps=0,
        )

        self.assertEqual(benchmark["symbolCount"], 2)
        self.assertAlmostEqual(benchmark["equalWeightReturnPct"], 15.0)
        self.assertEqual(benchmark["symbols"][0]["symbol"], "AAA")
        self.assertAlmostEqual(benchmark["symbols"][0]["returnPct"], 20.0)

    def test_closed_trade_portfolio_respects_position_slots(self):
        trades = [
            {
                "symbol": "AAA",
                "entryDate": "2025-01-01",
                "exitDate": "2025-01-10",
                "returnPct": 10.0,
            },
            {
                "symbol": "BBB",
                "entryDate": "2025-01-02",
                "exitDate": "2025-01-08",
                "returnPct": 20.0,
            },
            {
                "symbol": "CCC",
                "entryDate": "2025-01-11",
                "exitDate": "2025-01-20",
                "returnPct": -5.0,
            },
        ]

        portfolio = simulate_closed_trade_portfolio(trades, max_positions=1)

        self.assertEqual(portfolio["acceptedTradeCount"], 2)
        self.assertEqual(portfolio["skippedTradeCount"], 1)
        self.assertAlmostEqual(portfolio["totalReturnPct"], 4.5)
        self.assertGreater(portfolio["maxDrawdownPct"], 0)

    def test_mark_to_market_portfolio_tracks_open_trade_equity_daily(self):
        daily = pd.DataFrame(
            {"Close": [100.0, 110.0, 120.0]},
            index=pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"]),
        )
        trades = [
            {
                "symbol": "AAA",
                "entryDate": "2025-01-01",
                "exitDate": "2025-01-03",
                "entryPrice": 100.0,
                "returnPct": 20.0,
            },
            {
                "symbol": "BBB",
                "entryDate": "2025-01-02",
                "exitDate": "2025-01-03",
                "entryPrice": 100.0,
                "returnPct": 5.0,
            },
        ]

        portfolio = simulate_mark_to_market_portfolio(
            trades,
            {"AAA": daily, "BBB": daily},
            max_positions=1,
        )

        self.assertEqual(portfolio["mode"], "daily_mark_to_market_equal_slot")
        self.assertEqual(portfolio["acceptedTradeCount"], 1)
        self.assertEqual(portfolio["skippedTradeCount"], 1)
        self.assertAlmostEqual(portfolio["equityCurve"][1]["equity"], 1.1)
        self.assertAlmostEqual(portfolio["totalReturnPct"], 20.0)

    def test_relative_strength_annotation_ranks_trades_at_entry_date(self):
        dates = pd.date_range("2025-01-01", periods=4, freq="B")
        frames = {
            "AAA": pd.DataFrame({"Close": [100.0, 105.0, 110.0, 120.0]}, index=dates),
            "BBB": pd.DataFrame({"Close": [100.0, 101.0, 103.0, 105.0]}, index=dates),
            "CCC": pd.DataFrame({"Close": [100.0, 98.0, 97.0, 95.0]}, index=dates),
        }
        trades = [
            {
                "symbol": "BBB",
                "entryDate": str(dates[-1].date()),
                "returnPct": 2.0,
            },
        ]

        annotated = annotate_relative_strength(trades, frames, lookback_bars=2)

        self.assertEqual(annotated[0]["relativeStrengthRank"], 2)
        self.assertEqual(annotated[0]["relativeStrengthUniverseSize"], 3)
        self.assertGreater(annotated[0]["relativeStrengthPct"], 0)
        self.assertEqual(annotated[0]["relativeStrengthBucket"], "middle")

    def test_backtest_report_can_apply_asset_and_pool_filters(self):
        trades = [
            {
                "symbol": "SPY",
                "assetClass": "etf",
                "strategyVersion": "resonance_v2_atr_2_0",
                "poolType": "establishedTrend",
                "returnPct": 3.0,
                "holdingDays": 5,
                "exitReason": "target",
                "entryDate": "2025-02-03",
            },
            {
                "symbol": "AAPL",
                "assetClass": "stock",
                "strategyVersion": "resonance_v2_atr_2_0",
                "poolType": "establishedTrend",
                "returnPct": -1.0,
                "holdingDays": 5,
                "exitReason": "hard_exit",
                "entryDate": "2025-02-04",
            },
            {
                "symbol": "QQQ",
                "assetClass": "etf",
                "strategyVersion": "resonance_v2_atr_2_0",
                "poolType": "earlyTrend",
                "returnPct": 2.0,
                "holdingDays": 5,
                "exitReason": "target",
                "entryDate": "2025-02-05",
            },
        ]

        report = summarize_backtest_report(
            trades,
            strategy_version="resonance_v2_atr_2_0",
            asset_class_filter="etf",
            pool_type_filter="establishedTrend",
        )

        self.assertEqual(report["summary"]["tradeCount"], 1)
        self.assertEqual(report["symbolContribution"][0]["symbol"], "SPY")

    def test_backtest_report_can_apply_relative_strength_bucket_filter(self):
        trades = [
            {
                "symbol": "AAA",
                "assetClass": "etf",
                "strategyVersion": "resonance_v4",
                "poolType": "establishedTrend",
                "relativeStrengthBucket": "top20",
                "returnPct": 5.0,
                "holdingDays": 6,
                "exitReason": "target",
                "entryDate": "2025-02-03",
            },
            {
                "symbol": "BBB",
                "assetClass": "etf",
                "strategyVersion": "resonance_v4",
                "poolType": "establishedTrend",
                "relativeStrengthBucket": "middle",
                "returnPct": -1.0,
                "holdingDays": 5,
                "exitReason": "hard_exit",
                "entryDate": "2025-02-04",
            },
        ]

        report = summarize_backtest_report(
            trades,
            strategy_version="resonance_v4",
            relative_strength_bucket_filter="top20",
        )

        self.assertEqual(report["summary"]["tradeCount"], 1)
        self.assertEqual(report["symbolContribution"][0]["symbol"], "AAA")
        self.assertEqual(report["filters"]["relativeStrengthBucket"], "top20")

    def test_backtest_report_accepts_multiple_relative_strength_buckets(self):
        trades = [
            {
                "symbol": "AAA",
                "assetClass": "etf",
                "strategyVersion": "resonance_v4",
                "poolType": "establishedTrend",
                "relativeStrengthBucket": "top20",
                "returnPct": 5.0,
                "holdingDays": 6,
                "exitReason": "target",
                "entryDate": "2025-02-03",
            },
            {
                "symbol": "BBB",
                "assetClass": "etf",
                "strategyVersion": "resonance_v4",
                "poolType": "establishedTrend",
                "relativeStrengthBucket": "top50",
                "returnPct": 1.0,
                "holdingDays": 5,
                "exitReason": "target",
                "entryDate": "2025-02-04",
            },
            {
                "symbol": "CCC",
                "assetClass": "etf",
                "strategyVersion": "resonance_v4",
                "poolType": "establishedTrend",
                "relativeStrengthBucket": "middle",
                "returnPct": -1.0,
                "holdingDays": 5,
                "exitReason": "hard_exit",
                "entryDate": "2025-02-05",
            },
        ]

        report = summarize_backtest_report(
            trades,
            strategy_version="resonance_v4",
            relative_strength_bucket_filter="top20,top50",
        )

        self.assertEqual(report["summary"]["tradeCount"], 2)
        self.assertEqual(report["filters"]["relativeStrengthBucket"], "top20,top50")

    def test_backtest_report_includes_loss_diagnostics(self):
        trades = [
            {
                "symbol": "ETF1",
                "assetClass": "etf",
                "strategyVersion": "resonance_v2_atr_2_0",
                "poolType": "establishedTrend",
                "entryScore": 72,
                "riskLevel": "medium",
                "returnPct": -4.0,
                "holdingDays": 4,
                "exitReason": "stop",
                "entryDate": "2026-01-03",
                "exitDate": "2026-01-07",
                "marketRegimeAtExit": "bullish_trend_pullback",
            },
            {
                "symbol": "ETF2",
                "assetClass": "etf",
                "strategyVersion": "resonance_v2_atr_2_0",
                "poolType": "establishedTrend",
                "entryScore": 95,
                "riskLevel": "low",
                "returnPct": 5.0,
                "holdingDays": 8,
                "exitReason": "target",
                "entryDate": "2026-02-03",
                "exitDate": "2026-02-11",
                "marketRegimeAtExit": "bullish_ema",
            },
            {
                "symbol": "ETF3",
                "assetClass": "etf",
                "strategyVersion": "resonance_v2_atr_2_0",
                "poolType": "establishedTrend",
                "entryScore": 55,
                "riskLevel": "high",
                "returnPct": -6.0,
                "holdingDays": 2,
                "exitReason": "hard_exit",
                "entryDate": "2025-12-03",
                "exitDate": "2025-12-05",
                "marketRegimeAtExit": "bearish_ema",
            },
        ]

        report = summarize_backtest_report(trades, strategy_version="resonance_v2_atr_2_0")

        diagnostics = report["diagnostics"]
        self.assertEqual(diagnostics["lossSummary"]["lossTradeCount"], 2)
        self.assertEqual(diagnostics["lossSummary"]["worstReturnPct"], -6.0)
        self.assertEqual(diagnostics["worstTrades"][0]["symbol"], "ETF3")
        self.assertEqual(diagnostics["worstTrades"][1]["symbol"], "ETF1")
        self.assertEqual(diagnostics["byEntryScoreBucket"]["50-69"]["tradeCount"], 1)
        self.assertEqual(diagnostics["byEntryScoreBucket"]["70-89"]["tradeCount"], 1)
        self.assertEqual(diagnostics["byEntryScoreBucket"]["90-100"]["tradeCount"], 1)
        self.assertEqual(diagnostics["byExitReason"]["stop"]["tradeCount"], 1)
        self.assertEqual(diagnostics["byRiskLevel"]["high"]["tradeCount"], 1)
        self.assertEqual(diagnostics["byMarketRegimeAtExit"]["bearish_ema"]["tradeCount"], 1)
        self.assertEqual(report["diagnosticsByYear"]["2026"]["lossSummary"]["lossTradeCount"], 1)

    def test_market_regime_filter_blocks_bearish_index_context(self):
        daily = _build_backtest_daily_df()
        weekly = _build_backtest_weekly_df()
        bearish_market = _build_market_regime_df(bullish=False)

        trades = run_backtest_for_symbol(
            "TEST",
            daily,
            weekly,
            market_regime_daily=bearish_market,
            market_filter="bullish_ema",
        )

        self.assertEqual(trades, [])

    def test_market_regime_filter_allows_bullish_index_context(self):
        daily = _build_backtest_daily_df()
        weekly = _build_backtest_weekly_df()
        bullish_market = _build_market_regime_df(bullish=True)

        trades = run_backtest_for_symbol(
            "TEST",
            daily,
            weekly,
            market_regime_daily=bullish_market,
            market_filter="bullish_ema",
            fee_bps=0,
            slippage_bps=0,
        )

        self.assertEqual(len(trades), 1)

    def test_entry_market_filter_blocks_pullback_on_entry_date(self):
        daily = _build_backtest_daily_df()
        weekly = _build_backtest_weekly_df()
        market = _build_market_regime_df(bullish=True)
        entry_date = daily.index[25]
        market.loc[entry_date:, "Close"] = 100.0

        loose_trades = run_backtest_for_symbol(
            "TEST",
            daily,
            weekly,
            market_regime_daily=market,
            market_filter="bullish_ema",
            fee_bps=0,
            slippage_bps=0,
        )
        strict_trades = run_backtest_for_symbol(
            "TEST",
            daily,
            weekly,
            market_regime_daily=market,
            market_filter="bullish_ema",
            entry_market_filter="bullish_ema",
            fee_bps=0,
            slippage_bps=0,
        )

        self.assertEqual(len(loose_trades), 1)
        self.assertEqual(strict_trades, [])

    def test_entry_market_buffer_blocks_thin_bullish_context(self):
        daily = _build_backtest_daily_df()
        weekly = _build_backtest_weekly_df()
        market = _build_market_regime_df(bullish=True)
        entry_date = daily.index[25]
        market.loc[entry_date:, "Close"] = 105.5

        strict_trades = run_backtest_for_symbol(
            "TEST",
            daily,
            weekly,
            market_regime_daily=market,
            market_filter="bullish_ema",
            entry_market_filter="bullish_ema",
            fee_bps=0,
            slippage_bps=0,
        )
        buffered_trades = run_backtest_for_symbol(
            "TEST",
            daily,
            weekly,
            market_regime_daily=market,
            market_filter="bullish_ema",
            entry_market_filter="bullish_ema",
            entry_market_min_close_vs_ema20_pct=1.0,
            fee_bps=0,
            slippage_bps=0,
        )

        self.assertEqual(len(strict_trades), 1)
        self.assertEqual(buffered_trades, [])


class RsRotationRegressionTests(unittest.TestCase):
    """
    Regression tests pinning exact output of simulate_rs_rotation_portfolio.
    If these numbers change after a refactor, the strategy logic has changed.
    Tolerance is ±0.5% to allow for minor floating-point differences.
    """

    @classmethod
    def setUpClass(cls):
        import os
        from backtest import simulate_rs_rotation_portfolio, load_universe_symbols

        DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
        if not os.path.exists(DATA_DIR):
            raise unittest.SkipTest("data/ directory not found — skipping integration regression tests")

        symbols = load_universe_symbols(os.path.join(os.path.dirname(__file__), "..", "universes", "a_share_etf_core.json"))
        frames_a = {}
        for s in symbols:
            p = os.path.join(DATA_DIR, f"{s.upper()}.parquet")
            if os.path.exists(p):
                frames_a[s.upper()] = pd.read_parquet(p)

        frames_g = dict(frames_a)
        for s in ["SPY", "QQQ", "GC=F", "BTC-USD"]:
            p = os.path.join(DATA_DIR, f"{s}.parquet")
            if os.path.exists(p):
                frames_g[s] = pd.read_parquet(p)

        csi_path = os.path.join(DATA_DIR, "510300.SS.parquet")
        spy_path = os.path.join(DATA_DIR, "SPY.parquet")
        btc_path = os.path.join(DATA_DIR, "BTC-USD.parquet")
        gc_path  = os.path.join(DATA_DIR, "GC=F.parquet")

        for p in [csi_path, spy_path, btc_path, gc_path]:
            if not os.path.exists(p):
                raise unittest.SkipTest(f"Missing {p} — skipping regression tests")

        csi = pd.read_parquet(csi_path)
        spy = pd.read_parquet(spy_path)
        if csi.index.min() > pd.Timestamp("2020-01-01") or spy.index.min() > pd.Timestamp("2020-01-01"):
            raise unittest.SkipTest("Data does not cover 2020 — skipping regression tests")
        btc = pd.read_parquet(btc_path)
        gc  = pd.read_parquet(gc_path)

        cls.frames_a = frames_a
        cls.frames_g = frames_g
        cls.csi = csi
        cls.per_class_global = {
            "a_share":   (csi,  "monthly_macd"),
            "us":        (spy,  "monthly_macd"),
            "crypto":    (btc,  "monthly_macd"),
            "commodity": (gc,   "monthly_macd"),
        }

    def _run_a(self, start, end=None):
        from backtest import simulate_rs_rotation_portfolio
        return simulate_rs_rotation_portfolio(
            self.frames_a, top_n=5, rebalance_days=20, lookback_bars=60,
            start=start, end=end, fee_bps=5.0, slippage_bps=5.0,
            min_history_bars=0, min_avg_volume=1e8,
            market_filter_df=self.csi, market_filter_mode="monthly_macd",
        )

    def _run_g(self, start, end=None):
        from backtest import simulate_rs_rotation_portfolio
        return simulate_rs_rotation_portfolio(
            self.frames_g, top_n=5, rebalance_days=20, lookback_bars=60,
            start=start, end=end, fee_bps=5.0, slippage_bps=5.0,
            min_history_bars=0, min_avg_volume=0,
            per_class_filters=self.per_class_global,
        )

    def test_a_share_2020_bearish_year_returns_negative(self):
        # A股月MACD过滤在2020年无法规避A股熊市，全年亏损约-9.7%
        r = self._run_a("2020-01-01", "2020-12-31")
        self.assertAlmostEqual(r["totalReturnPct"], -9.73, delta=0.5)
        self.assertAlmostEqual(r["maxDrawdownPct"], 21.93, delta=1.0)

    def test_global_2020_captures_us_bull_market(self):
        # 全球版本2020年因持有美股/BTC而大幅跑赢A股版本，约+33%
        r = self._run_g("2020-01-01", "2020-12-31")
        self.assertAlmostEqual(r["totalReturnPct"], 27.86, delta=0.5)
        self.assertAlmostEqual(r["maxDrawdownPct"], 10.36, delta=1.0)

    def test_global_outperforms_a_share_in_2020(self):
        ra = self._run_a("2020-01-01", "2020-12-31")
        rg = self._run_g("2020-01-01", "2020-12-31")
        self.assertGreater(rg["totalReturnPct"], ra["totalReturnPct"] + 30)

    def test_volume_filter_limits_universe_in_early_years(self):
        # 2015年只有3个ETF通过1亿日均量门槛（510300/510050/159915）
        # 这验证了流动性过滤在早期年份有效防止look-ahead bias
        from backtest import simulate_rs_rotation_portfolio
        r_filtered = simulate_rs_rotation_portfolio(
            self.frames_a, top_n=5, rebalance_days=20, lookback_bars=60,
            start="2015-01-01", end="2015-12-31", fee_bps=5.0, slippage_bps=5.0,
            min_history_bars=0, min_avg_volume=1e8,
            market_filter_df=self.csi, market_filter_mode="monthly_macd",
        )
        r_unfiltered = simulate_rs_rotation_portfolio(
            self.frames_a, top_n=5, rebalance_days=20, lookback_bars=60,
            start="2015-01-01", end="2015-12-31", fee_bps=5.0, slippage_bps=5.0,
            min_history_bars=0, min_avg_volume=0,
            market_filter_df=self.csi, market_filter_mode="monthly_macd",
        )
        # 过滤后收益应低于无过滤（无过滤包含了事后才知道好的ETF）
        self.assertLess(r_filtered["totalReturnPct"], r_unfiltered["totalReturnPct"])

    def test_monthly_macd_filter_goes_to_cash_in_bear_market(self):
        # 熊市期间（A股月MACD空头）策略应空仓，equity curve中有空仓记录
        r = self._run_a("2018-01-01", "2018-12-31")
        empty_holding_days = sum(1 for p in r["equityCurve"] if p["openPositions"] == 0)
        self.assertGreater(empty_holding_days, 0)

    def test_per_class_filter_blocks_us_stocks_in_us_bear_market(self):
        # 2022年美股月MACD大部分时间空头，全球策略持有美股天数应远少于A股版本
        # 注：2022年3月SPY月MACD短暂转多（DIF>DEA），策略会短暂持有，这是正确行为
        r = self._run_g("2022-01-01", "2022-12-31")
        ra = self._run_a("2022-01-01", "2022-12-31")
        # 全球版本2022年亏损应小于A股版本（因为分散到其他资产类别）
        # 或者至多相当，不会因为持有美股而大幅跑输
        us_held_days = sum(
            1 for p in r["equityCurve"]
            if "SPY" in p["holdings"] or "QQQ" in p["holdings"]
        )
        # 全年252个交易日，美股持有天数应少于一半（月MACD大部分时间空头）
        self.assertLess(us_held_days, 126)


if __name__ == "__main__":
    unittest.main()
