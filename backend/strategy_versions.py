from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class StrategyVersion:
    id: str
    label: str
    established_trend_lookback: int
    atr_stop_multiplier: float
    atr_target_multiplier: float
    market_filter: str = "none"
    entry_market_filter: str = "none"
    entry_market_min_close_vs_ema20_pct: float = 0.0
    market_symbol: Optional[str] = None
    asset_class_filter: Optional[str] = None
    pool_type_filter: Optional[str] = None
    exit_mode: str = "fixed_target"
    relative_strength_bucket_filter: Optional[str] = None
    signal_type: str = "resonance"  # "resonance" | "weekly_bb_breakout" | "weekly_bb_pullback_atr"


DEFAULT_STRATEGY_VERSION_ID = "resonance_v2_atr_1_5"


STRATEGY_VERSIONS = {
    "resonance_v2_atr_1_5": StrategyVersion(
        id="resonance_v2_atr_1_5",
        label="Resonance v2 ATR 1.5/3.0",
        established_trend_lookback=80,
        atr_stop_multiplier=1.5,
        atr_target_multiplier=3.0,
    ),
    "resonance_v2_atr_2_0": StrategyVersion(
        id="resonance_v2_atr_2_0",
        label="Resonance v2 ATR 2.0/4.0",
        established_trend_lookback=80,
        atr_stop_multiplier=2.0,
        atr_target_multiplier=4.0,
    ),
    "resonance_v2_atr_2_0_spy_bullish_etf_established": StrategyVersion(
        id="resonance_v2_atr_2_0_spy_bullish_etf_established",
        label="Resonance v2 ATR 2.0 ETF established trend with SPY bullish filter",
        established_trend_lookback=80,
        atr_stop_multiplier=2.0,
        atr_target_multiplier=4.0,
        market_filter="bullish_ema",
        market_symbol="SPY",
        asset_class_filter="etf",
        pool_type_filter="establishedTrend",
    ),
    "resonance_v2_atr_2_0_csi300_bullish_etf_established": StrategyVersion(
        id="resonance_v2_atr_2_0_csi300_bullish_etf_established",
        label="Resonance v2 ATR 2.0 ETF established trend with CSI 300 bullish filter",
        established_trend_lookback=80,
        atr_stop_multiplier=2.0,
        atr_target_multiplier=4.0,
        market_filter="bullish_ema",
        market_symbol="000300.SS",
        asset_class_filter="etf",
        pool_type_filter="establishedTrend",
    ),
    "resonance_v2_atr_2_0_csi300_strict_bullish_etf_established": StrategyVersion(
        id="resonance_v2_atr_2_0_csi300_strict_bullish_etf_established",
        label="Resonance v2 ATR 2.0 ETF established trend with strict CSI 300 bullish filter",
        established_trend_lookback=80,
        atr_stop_multiplier=2.0,
        atr_target_multiplier=4.0,
        market_filter="bullish_ema",
        entry_market_filter="bullish_ema",
        market_symbol="000300.SS",
        asset_class_filter="etf",
        pool_type_filter="establishedTrend",
    ),
    "resonance_v2_atr_2_0_csi300_entry_buffer_1_0_etf_established": StrategyVersion(
        id="resonance_v2_atr_2_0_csi300_entry_buffer_1_0_etf_established",
        label="Resonance v2 ATR 2.0 ETF established trend with CSI 300 entry buffer 1.0",
        established_trend_lookback=80,
        atr_stop_multiplier=2.0,
        atr_target_multiplier=4.0,
        market_filter="bullish_ema",
        entry_market_filter="bullish_ema",
        entry_market_min_close_vs_ema20_pct=1.0,
        market_symbol="000300.SS",
        asset_class_filter="etf",
        pool_type_filter="establishedTrend",
    ),
    "resonance_v3_trend_runner_csi300_entry_buffer_1_0_etf_established": StrategyVersion(
        id="resonance_v3_trend_runner_csi300_entry_buffer_1_0_etf_established",
        label="Resonance v3 trend runner ETF established trend with CSI 300 entry buffer 1.0",
        established_trend_lookback=80,
        atr_stop_multiplier=2.0,
        atr_target_multiplier=0.0,
        market_filter="bullish_ema",
        entry_market_filter="bullish_ema",
        entry_market_min_close_vs_ema20_pct=1.0,
        market_symbol="000300.SS",
        asset_class_filter="etf",
        pool_type_filter="establishedTrend",
        exit_mode="warn_exit",
    ),
    "resonance_v3_atr_2_0_8_0_csi300_entry_buffer_1_0_etf_established": StrategyVersion(
        id="resonance_v3_atr_2_0_8_0_csi300_entry_buffer_1_0_etf_established",
        label="Resonance v3 ATR 2.0/8.0 ETF established trend with CSI 300 entry buffer 1.0",
        established_trend_lookback=80,
        atr_stop_multiplier=2.0,
        atr_target_multiplier=8.0,
        market_filter="bullish_ema",
        entry_market_filter="bullish_ema",
        entry_market_min_close_vs_ema20_pct=1.0,
        market_symbol="000300.SS",
        asset_class_filter="etf",
        pool_type_filter="establishedTrend",
    ),
    "resonance_v4_rs_top20_csi300_entry_buffer_1_0_etf_established": StrategyVersion(
        id="resonance_v4_rs_top20_csi300_entry_buffer_1_0_etf_established",
        label="Resonance v4 ETF established trend with CSI 300 entry buffer and RS top 20",
        established_trend_lookback=80,
        atr_stop_multiplier=2.0,
        atr_target_multiplier=4.0,
        market_filter="bullish_ema",
        entry_market_filter="bullish_ema",
        entry_market_min_close_vs_ema20_pct=1.0,
        market_symbol="000300.SS",
        asset_class_filter="etf",
        pool_type_filter="establishedTrend",
        relative_strength_bucket_filter="top20",
    ),
    "resonance_v4_rs_top50_csi300_entry_buffer_1_0_etf_established": StrategyVersion(
        id="resonance_v4_rs_top50_csi300_entry_buffer_1_0_etf_established",
        label="Resonance v4 ETF established trend with CSI 300 entry buffer and RS top 50",
        established_trend_lookback=80,
        atr_stop_multiplier=2.0,
        atr_target_multiplier=4.0,
        market_filter="bullish_ema",
        entry_market_filter="bullish_ema",
        entry_market_min_close_vs_ema20_pct=1.0,
        market_symbol="000300.SS",
        asset_class_filter="etf",
        pool_type_filter="establishedTrend",
        relative_strength_bucket_filter="top20,top50",
    ),
    "weekly_bb_pullback_atr_spy_monthly_macd": StrategyVersion(
        id="weekly_bb_pullback_atr_spy_monthly_macd",
        label="周线BB回踩 · ATR止损 · SPY月MACD过滤",
        established_trend_lookback=30,
        atr_stop_multiplier=1.5,
        atr_target_multiplier=0.0,
        exit_mode="warn_exit",
        signal_type="weekly_bb_pullback_atr",
        market_filter="monthly_macd",
        market_symbol="SPY",
    ),
    "weekly_bb_pullback_atr_stop": StrategyVersion(
        id="weekly_bb_pullback_atr_stop",
        label="周线BB回踩 · ATR动态止损",
        established_trend_lookback=30,
        atr_stop_multiplier=1.5,
        atr_target_multiplier=0.0,
        exit_mode="warn_exit",
        signal_type="weekly_bb_pullback_atr",
    ),
    "weekly_bb_breakout_ma30": StrategyVersion(
        id="weekly_bb_breakout_ma30",
        label="周线BB突破 · MA30趋势过滤",
        established_trend_lookback=30,
        atr_stop_multiplier=0.0,
        atr_target_multiplier=0.0,
        exit_mode="warn_exit",
        signal_type="weekly_bb_breakout",
    ),
}


def get_strategy_version(version_id: Optional[str] = None) -> StrategyVersion:
    resolved_id = version_id or DEFAULT_STRATEGY_VERSION_ID
    try:
        return STRATEGY_VERSIONS[resolved_id]
    except KeyError as exc:
        raise ValueError(f"Unknown strategy version: {resolved_id}") from exc


def list_strategy_versions() -> List[StrategyVersion]:
    return [STRATEGY_VERSIONS[key] for key in sorted(STRATEGY_VERSIONS)]
