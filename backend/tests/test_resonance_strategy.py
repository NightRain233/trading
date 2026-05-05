import unittest

import pandas as pd

from analysis import _evaluate_resonance_strategy
from analysis import _evaluate_resonance_strategy_v2
from analysis import _evaluate_resonance_exit_no_position


def _build_daily_df(cross_index: int, final_volume: float) -> pd.DataFrame:
    """Build a synthetic daily DataFrame for resonance strategy tests."""
    dates = pd.date_range("2025-01-01", periods=30, freq="B")

    ema50 = [100.0] * 30
    ema20 = []
    for i in range(30):
        if i < cross_index:
            ema20.append(99.0)
        else:
            ema20.append(101.0 + (i - cross_index) * 0.05)

    ema10 = [100.5 + i * 0.05 for i in range(30)]
    ema5 = [100.8 + i * 0.06 for i in range(30)]
    close = [102.0] * 30
    high = [103.0] * 30
    low = [101.5] * 30
    volume = [1000.0] * 29 + [final_volume]
    atr = [2.0] * 30

    # Last bar forms pullback-reclaim around EMA10/EMA5 but still above EMA20.
    low[-1] = ema10[-1] - 0.3
    close[-1] = ema10[-1] + 0.2
    high[-1] = close[-1] + 0.8
    low[-2] = ema10[-2] + 0.1
    close[-2] = ema10[-2] + 0.3

    return pd.DataFrame(
        {
            "Close": close,
            "High": high,
            "Low": low,
            "EMA5": ema5,
            "EMA10": ema10,
            "EMA20": ema20,
            "EMA50": ema50,
            "Volume": volume,
            "ATR": atr,
        },
        index=dates,
    )


def _build_weekly_df(macd_w: float, signal_w: float, ma5_w: float) -> pd.DataFrame:
    dates = pd.date_range("2024-01-07", periods=12, freq="W")
    return pd.DataFrame(
        {
            "MACD_W": [0.1] * 11 + [macd_w],
            "MACD_Signal_W": [0.05] * 11 + [signal_w],
            "MA5_W": [100.0] * 11 + [ma5_w],
        },
        index=dates,
    )


def _build_exit_daily_df(
    final_close: float,
    final_ema20: float = 101.0,
    final_ema50: float = 100.0,
    final_macd_dif: float = 0.3,
    final_macd_dea: float = 0.2,
) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=30, freq="B")
    close = [102.0] * 29 + [final_close]
    ema20 = [100.8] * 29 + [final_ema20]
    ema50 = [100.0] * 30
    macd_dif = [0.25] * 29 + [final_macd_dif]
    macd_dea = [0.2] * 29 + [final_macd_dea]
    low = [101.5] * 30
    volume = [1000.0] * 30

    return pd.DataFrame(
        {
            "Close": close,
            "Low": low,
            "EMA20": ema20,
            "EMA50": ema50,
            "MACD_DIF": macd_dif,
            "MACD_DEA": macd_dea,
            "Volume": volume,
        },
        index=dates,
    )


class ResonanceStrategyTests(unittest.TestCase):
    def test_resonance_buy_signal_when_pool_and_pullback_confirmed(self):
        daily = _build_daily_df(cross_index=20, final_volume=600.0)
        weekly = _build_weekly_df(macd_w=0.4, signal_w=0.2, ma5_w=100.0)

        result = _evaluate_resonance_strategy(daily, weekly)

        self.assertTrue(result["inPool"])
        self.assertTrue(result["buySignal"])

    def test_resonance_not_in_pool_when_weekly_filter_fails(self):
        daily = _build_daily_df(cross_index=20, final_volume=600.0)
        weekly = _build_weekly_df(macd_w=0.1, signal_w=0.2, ma5_w=100.0)

        result = _evaluate_resonance_strategy(daily, weekly)

        self.assertFalse(result["inPool"])
        self.assertFalse(result["buySignal"])

    def test_resonance_not_in_pool_when_golden_cross_too_old(self):
        daily = _build_daily_df(cross_index=2, final_volume=600.0)
        weekly = _build_weekly_df(macd_w=0.4, signal_w=0.2, ma5_w=100.0)

        result = _evaluate_resonance_strategy(daily, weekly)

        self.assertFalse(result["inPool"])
        self.assertFalse(result["buySignal"])

    def test_resonance_no_buy_signal_without_volume_shrink(self):
        daily = _build_daily_df(cross_index=20, final_volume=1200.0)
        weekly = _build_weekly_df(macd_w=0.4, signal_w=0.2, ma5_w=100.0)

        result = _evaluate_resonance_strategy(daily, weekly)

        self.assertTrue(result["inPool"])
        self.assertFalse(result["buySignal"])

    def test_resonance_v2_keeps_established_trend_in_pool_after_old_cross(self):
        daily = _build_daily_df(cross_index=2, final_volume=600.0)
        daily.iloc[-1, daily.columns.get_loc("Close")] = daily.iloc[-1]["EMA20"] + 0.5
        weekly = _build_weekly_df(macd_w=0.4, signal_w=0.2, ma5_w=100.0)

        result = _evaluate_resonance_strategy_v2(daily, weekly)

        self.assertTrue(result["inPool"])
        self.assertEqual(result["poolType"], "establishedTrend")
        self.assertGreaterEqual(result["entryScore"], 60)

    def test_resonance_v2_returns_atr_risk_model_for_buy_setup(self):
        daily = _build_daily_df(cross_index=20, final_volume=600.0)
        weekly = _build_weekly_df(macd_w=0.4, signal_w=0.2, ma5_w=100.0)

        result = _evaluate_resonance_strategy_v2(daily, weekly)

        self.assertTrue(result["buySignal"])
        self.assertEqual(result["poolType"], "earlyTrend")
        self.assertAlmostEqual(result["stopPrice"], result["entryPrice"] - 3.0, places=4)
        self.assertGreater(result["riskPercent"], 0)
        self.assertAlmostEqual(result["rewardRiskRatio"], 2.0, places=2)
        self.assertIn(result["riskLevel"], ("low", "medium", "high"))

    def test_resonance_v2_uses_strategy_version_risk_parameters(self):
        daily = _build_daily_df(cross_index=20, final_volume=600.0)
        weekly = _build_weekly_df(macd_w=0.4, signal_w=0.2, ma5_w=100.0)

        result = _evaluate_resonance_strategy_v2(
            daily,
            weekly,
            strategy_version="resonance_v2_atr_2_0",
        )

        self.assertEqual(result["strategyVersion"], "resonance_v2_atr_2_0")
        self.assertAlmostEqual(result["stopPrice"], result["entryPrice"] - 4.0, places=4)
        self.assertAlmostEqual(result["rewardRiskRatio"], 2.0, places=2)

    def test_exit_hard_when_close_below_ema50(self):
        daily = _build_exit_daily_df(final_close=99.0, final_ema20=101.0, final_ema50=100.0)
        weekly = _build_weekly_df(macd_w=0.4, signal_w=0.2, ma5_w=95.0)

        result = _evaluate_resonance_exit_no_position(daily, weekly)

        self.assertTrue(result["exitSignal"])
        self.assertEqual(result["exitLevel"], "hard")

    def test_exit_hard_when_weekly_filter_breaks(self):
        daily = _build_exit_daily_df(final_close=103.0, final_ema20=101.0, final_ema50=100.0)
        weekly = _build_weekly_df(macd_w=0.1, signal_w=0.2, ma5_w=100.0)

        result = _evaluate_resonance_exit_no_position(daily, weekly)

        self.assertTrue(result["exitSignal"])
        self.assertEqual(result["exitLevel"], "hard")

    def test_exit_warn_when_close_below_ema20_but_not_hard(self):
        daily = _build_exit_daily_df(final_close=100.5, final_ema20=101.0, final_ema50=100.0)
        weekly = _build_weekly_df(macd_w=0.4, signal_w=0.2, ma5_w=99.0)

        result = _evaluate_resonance_exit_no_position(daily, weekly)

        self.assertTrue(result["exitSignal"])
        self.assertEqual(result["exitLevel"], "warn")

    def test_exit_warn_when_daily_macd_dead_cross(self):
        daily = _build_exit_daily_df(
            final_close=102.0,
            final_ema20=101.0,
            final_ema50=100.0,
            final_macd_dif=0.1,
            final_macd_dea=0.2,
        )
        weekly = _build_weekly_df(macd_w=0.4, signal_w=0.2, ma5_w=99.0)

        result = _evaluate_resonance_exit_no_position(daily, weekly)

        self.assertTrue(result["exitSignal"])
        self.assertEqual(result["exitLevel"], "warn")

    def test_exit_none_when_trend_intact(self):
        daily = _build_exit_daily_df(
            final_close=103.0,
            final_ema20=101.0,
            final_ema50=100.0,
            final_macd_dif=0.3,
            final_macd_dea=0.2,
        )
        weekly = _build_weekly_df(macd_w=0.4, signal_w=0.2, ma5_w=99.0)

        result = _evaluate_resonance_exit_no_position(daily, weekly)

        self.assertFalse(result["exitSignal"])
        self.assertEqual(result["exitLevel"], "none")


if __name__ == "__main__":
    unittest.main()
