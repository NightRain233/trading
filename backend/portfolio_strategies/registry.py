from __future__ import annotations

from .models import AssetConfig, CostConfig, StrategyConfig, StrategyMode


class UnknownStrategyError(KeyError):
    pass


class ComparisonStrategyError(ValueError):
    pass


CORE_ASSETS = (
    AssetConfig("510300.SS", "沪深300ETF", "core"),
    AssetConfig("513100.SS", "纳指100ETF", "core_lvt"),
    AssetConfig("518880.SS", "黄金ETF", "core_lvt"),
)

BTC_ASSET = AssetConfig(
    "BTC-USD",
    "BTC",
    "satellite",
    market="CRYPTO_UTC",
    synthetic_proxy=True,
    note="Synthetic return proxy; no CNY/USD conversion is modeled.",
)

THEME_ASSETS = CORE_ASSETS + (
    AssetConfig("512400.SS", "有色金属ETF", "lvt"),
    AssetConfig("159995.SZ", "芯片ETF", "lvt"),
    AssetConfig("515880.SS", "通信ETF", "lvt"),
    AssetConfig("510880.SS", "红利ETF", "lvt"),
    AssetConfig("159930.SZ", "能源ETF", "lvt"),
    AssetConfig("512880.SS", "证券ETF", "lvt"),
    AssetConfig("513180.SS", "恒生科技ETF", "lvt"),
    AssetConfig("512170.SS", "医疗ETF", "lvt"),
)


def _btc_config(
    strategy_id: str,
    cap: float,
    mode: StrategyMode,
    display_name: str,
) -> StrategyConfig:
    return StrategyConfig(
        strategy_id=strategy_id,
        version="1.0.0",
        display_name=display_name,
        description="Three-asset RiskParity core with a BTC SuperTrend satellite.",
        mode=mode,
        execution="next_close",
        initial_nav=100_000.0,
        base_currency="CNY",
        assets=CORE_ASSETS + (BTC_ASSET,),
        params={
            "btc_cap": cap,
            "risk_parity_window": 20,
            "rebalance_sessions": 10,
            "schedule_reference_date": "2026-06-15",
            "schedule_source_anchor": "2016-06-21",
            "supertrend_atr_window": 10,
            "supertrend_atr_mode": "sma",
            "supertrend_multiplier": 3.0,
            "rebalance_threshold": 0.01,
        },
        costs=CostConfig(base_bps=20, slippage_bps=10),
    )


BTC_OFFICIAL = _btc_config(
    "btc_supertrend_satellite",
    0.075,
    StrategyMode.PAPER,
    "BTC SuperTrend Satellite 7.5%",
)

THEME_ALPHA = StrategyConfig(
    strategy_id="theme_alpha",
    version="1.0.0",
    display_name="Theme Alpha",
    description="Core80 / Expanded LVT20 / Def200 Cash.",
    mode=StrategyMode.PAPER,
    execution="next_close",
    initial_nav=100_000.0,
    base_currency="CNY",
    assets=THEME_ASSETS,
    params={
        "core_allocation": 0.80,
        "lvt_allocation": 0.20,
        "ma_window": 60,
        "momentum_window": 63,
        "volatility_window": 60,
        "top_n": 3,
        "risk_parity_window": 20,
        "single_asset_cap": 0.50,
        "defense_ma_window": 200,
        "rebalance_threshold": 0.02,
        "max_asset_trade": 0.15,
        "signal_days": (10, 25),
    },
    costs=CostConfig(
        base_bps=20,
        asset_extra_bps={
            "510300.SS": 5,
            "518880.SS": 5,
            "510880.SS": 5,
            "513100.SS": 20,
            "513180.SS": 20,
            "512400.SS": 10,
            "159995.SZ": 10,
            "515880.SS": 10,
            "159930.SZ": 10,
            "512880.SS": 10,
            "512170.SS": 10,
        },
    ),
)

BTC_COMPARISON_5 = _btc_config(
    "btc_supertrend_satellite_5",
    0.05,
    StrategyMode.COMPARISON,
    "BTC SuperTrend Satellite 5%",
)

BTC_COMPARISON_10 = _btc_config(
    "btc_supertrend_satellite_10",
    0.10,
    StrategyMode.COMPARISON,
    "BTC SuperTrend Satellite 10%",
)

_STRATEGIES = (
    BTC_OFFICIAL,
    THEME_ALPHA,
    BTC_COMPARISON_5,
    BTC_COMPARISON_10,
)
_BY_ID = {strategy.strategy_id: strategy for strategy in _STRATEGIES}


def list_strategies() -> tuple[StrategyConfig, ...]:
    return _STRATEGIES


def list_paper_strategies() -> tuple[StrategyConfig, ...]:
    return tuple(
        strategy for strategy in _STRATEGIES if strategy.mode is StrategyMode.PAPER
    )


def get_strategy(strategy_id: str) -> StrategyConfig:
    try:
        return _BY_ID[strategy_id]
    except KeyError as exc:
        raise UnknownStrategyError(strategy_id) from exc


def require_paper_strategy(strategy_id: str) -> StrategyConfig:
    strategy = get_strategy(strategy_id)
    if strategy.mode is not StrategyMode.PAPER:
        raise ComparisonStrategyError(
            f"{strategy_id} is comparison-only and cannot create a paper account"
        )
    return strategy
