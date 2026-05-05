import unittest

from strategy_versions import DEFAULT_STRATEGY_VERSION_ID
from strategy_versions import get_strategy_version
from strategy_versions import list_strategy_versions


class StrategyVersionTests(unittest.TestCase):
    def test_default_strategy_version_is_resonance_v2_atr_1_5(self):
        version = get_strategy_version()

        self.assertEqual(version.id, DEFAULT_STRATEGY_VERSION_ID)
        self.assertEqual(version.id, "resonance_v2_atr_1_5")
        self.assertEqual(version.atr_stop_multiplier, 1.5)
        self.assertEqual(version.atr_target_multiplier, 3.0)

    def test_can_lookup_resonance_v2_atr_2_0(self):
        version = get_strategy_version("resonance_v2_atr_2_0")

        self.assertEqual(version.id, "resonance_v2_atr_2_0")
        self.assertEqual(version.atr_stop_multiplier, 2.0)
        self.assertEqual(version.atr_target_multiplier, 4.0)

    def test_can_lookup_narrow_etf_established_version(self):
        version = get_strategy_version("resonance_v2_atr_2_0_spy_bullish_etf_established")

        self.assertEqual(version.atr_stop_multiplier, 2.0)
        self.assertEqual(version.market_filter, "bullish_ema")
        self.assertEqual(version.market_symbol, "SPY")
        self.assertEqual(version.asset_class_filter, "etf")
        self.assertEqual(version.pool_type_filter, "establishedTrend")

    def test_can_lookup_a_share_etf_established_version(self):
        version = get_strategy_version("resonance_v2_atr_2_0_csi300_bullish_etf_established")

        self.assertEqual(version.atr_stop_multiplier, 2.0)
        self.assertEqual(version.market_filter, "bullish_ema")
        self.assertEqual(version.market_symbol, "000300.SS")
        self.assertEqual(version.asset_class_filter, "etf")
        self.assertEqual(version.pool_type_filter, "establishedTrend")

    def test_can_lookup_strict_a_share_etf_established_version(self):
        version = get_strategy_version("resonance_v2_atr_2_0_csi300_strict_bullish_etf_established")

        self.assertEqual(version.atr_stop_multiplier, 2.0)
        self.assertEqual(version.market_filter, "bullish_ema")
        self.assertEqual(version.entry_market_filter, "bullish_ema")
        self.assertEqual(version.market_symbol, "000300.SS")
        self.assertEqual(version.asset_class_filter, "etf")
        self.assertEqual(version.pool_type_filter, "establishedTrend")

    def test_can_lookup_buffered_a_share_etf_established_version(self):
        version = get_strategy_version("resonance_v2_atr_2_0_csi300_entry_buffer_1_0_etf_established")

        self.assertEqual(version.atr_stop_multiplier, 2.0)
        self.assertEqual(version.market_filter, "bullish_ema")
        self.assertEqual(version.entry_market_filter, "bullish_ema")
        self.assertEqual(version.entry_market_min_close_vs_ema20_pct, 1.0)
        self.assertEqual(version.market_symbol, "000300.SS")
        self.assertEqual(version.asset_class_filter, "etf")
        self.assertEqual(version.pool_type_filter, "establishedTrend")

    def test_can_lookup_trend_runner_version(self):
        version = get_strategy_version("resonance_v3_trend_runner_csi300_entry_buffer_1_0_etf_established")

        self.assertEqual(version.atr_stop_multiplier, 2.0)
        self.assertEqual(version.atr_target_multiplier, 0.0)
        self.assertEqual(version.exit_mode, "warn_exit")
        self.assertEqual(version.market_filter, "bullish_ema")
        self.assertEqual(version.entry_market_filter, "bullish_ema")
        self.assertEqual(version.entry_market_min_close_vs_ema20_pct, 1.0)
        self.assertEqual(version.market_symbol, "000300.SS")
        self.assertEqual(version.asset_class_filter, "etf")
        self.assertEqual(version.pool_type_filter, "establishedTrend")

    def test_can_lookup_wide_target_a_share_etf_version(self):
        version = get_strategy_version("resonance_v3_atr_2_0_8_0_csi300_entry_buffer_1_0_etf_established")

        self.assertEqual(version.atr_stop_multiplier, 2.0)
        self.assertEqual(version.atr_target_multiplier, 8.0)
        self.assertEqual(version.exit_mode, "fixed_target")
        self.assertEqual(version.market_filter, "bullish_ema")
        self.assertEqual(version.entry_market_filter, "bullish_ema")
        self.assertEqual(version.entry_market_min_close_vs_ema20_pct, 1.0)
        self.assertEqual(version.market_symbol, "000300.SS")
        self.assertEqual(version.asset_class_filter, "etf")
        self.assertEqual(version.pool_type_filter, "establishedTrend")

    def test_can_lookup_relative_strength_top20_version(self):
        version = get_strategy_version("resonance_v4_rs_top20_csi300_entry_buffer_1_0_etf_established")

        self.assertEqual(version.atr_stop_multiplier, 2.0)
        self.assertEqual(version.atr_target_multiplier, 4.0)
        self.assertEqual(version.relative_strength_bucket_filter, "top20")
        self.assertEqual(version.market_filter, "bullish_ema")
        self.assertEqual(version.entry_market_filter, "bullish_ema")
        self.assertEqual(version.entry_market_min_close_vs_ema20_pct, 1.0)
        self.assertEqual(version.market_symbol, "000300.SS")
        self.assertEqual(version.asset_class_filter, "etf")
        self.assertEqual(version.pool_type_filter, "establishedTrend")

    def test_can_lookup_relative_strength_top50_version(self):
        version = get_strategy_version("resonance_v4_rs_top50_csi300_entry_buffer_1_0_etf_established")

        self.assertEqual(version.atr_stop_multiplier, 2.0)
        self.assertEqual(version.atr_target_multiplier, 4.0)
        self.assertEqual(version.relative_strength_bucket_filter, "top20,top50")
        self.assertEqual(version.market_filter, "bullish_ema")
        self.assertEqual(version.entry_market_filter, "bullish_ema")
        self.assertEqual(version.entry_market_min_close_vs_ema20_pct, 1.0)
        self.assertEqual(version.market_symbol, "000300.SS")
        self.assertEqual(version.asset_class_filter, "etf")
        self.assertEqual(version.pool_type_filter, "establishedTrend")

    def test_list_strategy_versions_returns_stable_ids(self):
        version_ids = [version.id for version in list_strategy_versions()]

        self.assertIn("resonance_v2_atr_1_5", version_ids)
        self.assertIn("resonance_v2_atr_2_0", version_ids)
        self.assertIn("resonance_v2_atr_2_0_spy_bullish_etf_established", version_ids)
        self.assertIn("resonance_v2_atr_2_0_csi300_bullish_etf_established", version_ids)
        self.assertIn("resonance_v2_atr_2_0_csi300_strict_bullish_etf_established", version_ids)
        self.assertIn("resonance_v2_atr_2_0_csi300_entry_buffer_1_0_etf_established", version_ids)
        self.assertIn("resonance_v3_trend_runner_csi300_entry_buffer_1_0_etf_established", version_ids)
        self.assertIn("resonance_v3_atr_2_0_8_0_csi300_entry_buffer_1_0_etf_established", version_ids)
        self.assertIn("resonance_v4_rs_top20_csi300_entry_buffer_1_0_etf_established", version_ids)
        self.assertIn("resonance_v4_rs_top50_csi300_entry_buffer_1_0_etf_established", version_ids)

    def test_unknown_strategy_version_raises_value_error(self):
        with self.assertRaises(ValueError):
            get_strategy_version("missing_version")


if __name__ == "__main__":
    unittest.main()
