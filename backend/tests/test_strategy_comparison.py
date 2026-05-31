import unittest

from strategy_comparison import format_markdown_report
from strategy_comparison import make_strategy_verdict
from strategy_comparison import _supertrend_strategy_version


class StrategyComparisonTests(unittest.TestCase):
    def test_verdict_prefers_supertrend_when_risk_adjusted_results_are_better(self):
        report = {
            "comparisonRows": [
                {
                    "assetGroup": "BTC",
                    "supertrend": {"returnDrawdownRatio": 49.39, "totalReturnPct": 828.87},
                    "momentum": {"returnDrawdownRatio": 8.26, "totalReturnPct": 401.23},
                },
                {
                    "assetGroup": "China ETF",
                    "supertrend": {"returnDrawdownRatio": 4.29, "totalReturnPct": 82.27},
                    "momentum": {"returnDrawdownRatio": 1.17, "totalReturnPct": 36.25},
                },
            ]
        }

        verdict = make_strategy_verdict(report)

        self.assertEqual(verdict["defaultStrategy"], "supertrend")
        self.assertIn("收益回撤比", verdict["reason"])

    def test_supertrend_strategy_version_includes_adx_and_entry_mode_when_combined(self):
        version = _supertrend_strategy_version(25.0, "support_test")

        self.assertEqual(version, "supertrend_adx_25_support_test")

    def test_markdown_report_includes_asset_rows_and_data_caveats(self):
        report = {
            "window": {"start": "2021-05-31", "end": "2026-05-30"},
            "verdict": {
                "defaultStrategy": "supertrend",
                "reason": "SuperTrend 收益回撤比更稳定。",
                "caveat": "美股强趋势单边牛市里，买入持有可能更强。",
            },
            "comparisonRows": [
                {
                    "assetGroup": "BTC",
                    "supertrend": {
                        "totalReturnPct": 828.8711,
                        "maxDrawdownPct": 16.7806,
                        "returnDrawdownRatio": 49.3945,
                    },
                    "momentum": {
                        "totalReturnPct": 401.2291,
                        "maxDrawdownPct": 48.5479,
                        "returnDrawdownRatio": 8.2646,
                    },
                    "buyHold": {"equalWeightReturnPct": 107.0814},
                }
            ],
            "adxResearchRows": [
                {
                    "assetGroup": "BTC",
                    "baseline": {"returnDrawdownRatio": 49.3945, "totalReturnPct": 828.8711},
                    "bestAdx": {"threshold": 25, "returnDrawdownRatio": 52.1234, "totalReturnPct": 760.0},
                    "variants": [],
                }
            ],
            "weeklyBbRows": [
                {
                    "assetGroup": "BTC",
                    "portfolio": {
                        "totalReturnPct": 210.0,
                        "maxDrawdownPct": 22.0,
                        "returnDrawdownRatio": 9.5455,
                    },
                    "tradeCount": 4,
                    "winRate": 0.75,
                    "averageHoldingDays": 41.25,
                }
            ],
            "supertrendSlimmingRows": [
                {
                    "assetGroup": "BTC",
                    "mode": "weekly_bull_daily_bull_flip",
                    "label": "周多日刚翻多",
                    "baseline": {
                        "totalReturnPct": 828.8711,
                        "maxDrawdownPct": 16.7806,
                        "returnDrawdownRatio": 49.3945,
                        "tradeCount": 15,
                        "winRate": 0.8,
                        "averageHoldingDays": 36.9,
                    },
                    "variant": {
                        "totalReturnPct": 760.0,
                        "maxDrawdownPct": 16.0,
                        "returnDrawdownRatio": 47.5,
                        "tradeCount": 10,
                        "winRate": 0.7,
                        "averageHoldingDays": 42.0,
                    },
                    "totalReturnRetention": 0.917,
                    "returnDrawdownRatioRetention": 0.962,
                    "tradeCountReductionPct": 0.3333,
                    "passesSlimmingGate": True,
                }
            ],
            "dataCaveats": ["部分中国 ETF 只有不足五年缓存。"],
        }

        markdown = format_markdown_report(report)

        self.assertIn("| BTC |", markdown)
        self.assertIn("828.9%", markdown)
        self.assertIn("ADX 过滤研究", markdown)
        self.assertIn("ADX >= 25", markdown)
        self.assertIn("周线 BB 突破+回踩", markdown)
        self.assertIn("210.0%", markdown)
        self.assertIn("SuperTrend 精简层研究", markdown)
        self.assertIn("周多日刚翻多", markdown)
        self.assertIn("通过", markdown)
        self.assertIn("91.7%", markdown)
        self.assertIn("部分中国 ETF", markdown)


if __name__ == "__main__":
    unittest.main()
