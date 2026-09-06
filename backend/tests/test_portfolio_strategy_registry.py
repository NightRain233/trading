import pytest

from portfolio_strategies.models import StrategyMode
from portfolio_strategies.registry import (
    ComparisonStrategyError,
    PRIMARY_STRATEGY_IDS,
    get_strategy,
    list_paper_strategies,
    list_strategies,
    require_paper_strategy,
)


def test_long_sample_convergence_exposes_one_primary_strategy():
    assert PRIMARY_STRATEGY_IDS == ("core90_ma200_bull10",)


def test_registry_exposes_five_official_paper_strategies():
    strategies = list_paper_strategies()

    assert [strategy.strategy_id for strategy in strategies] == [
        "risk_parity_core_next_open",
        "core90_ma200_bull10",
        "theme_alpha",
        "btc_supertrend_satellite",
        "core90_raw_bull10",
    ]
    assert all(strategy.mode is StrategyMode.PAPER for strategy in strategies)


def test_btc_official_registry_configuration():
    config = get_strategy("btc_supertrend_satellite")

    assert config.version == "1.0.0"
    assert config.execution == "next_close"
    assert config.initial_nav == 100_000.0
    assert config.base_currency == "CNY"
    assert config.params["btc_cap"] == 0.075
    assert config.params["risk_parity_window"] == 20
    assert config.params["rebalance_sessions"] == 10
    assert config.params["supertrend_atr_window"] == 10
    assert config.params["supertrend_atr_mode"] == "sma"
    assert config.params["supertrend_multiplier"] == 3.0
    assert config.params["rebalance_threshold"] == 0.01
    assert config.costs.base_bps == 20
    assert config.costs.slippage_bps == 10
    assert config.symbols == (
        "510300.SS",
        "513100.SS",
        "518880.SS",
        "BTC-USD",
    )
    assert config.asset("BTC-USD").synthetic_proxy is True
    assert config.asset("BTC-USD").quote_currency == "USD"
    assert config.asset("BTC-USD").fx_pair == "USDCNY=X"
    assert config.asset("BTC-USD").investable_instrument is None


def test_domestic_cross_border_etf_is_cny_investable_not_a_foreign_proxy():
    asset = get_strategy("core90_ma200_bull10").asset("513100.SS")

    assert asset.quote_currency == "CNY"
    assert asset.synthetic_proxy is False
    assert asset.investable_instrument == "513100.SS"


def test_btc_comparison_caps_are_not_paper_accounts():
    configs = {strategy.strategy_id: strategy for strategy in list_strategies()}

    assert configs["btc_supertrend_satellite_5"].params["btc_cap"] == 0.05
    assert configs["btc_supertrend_satellite_10"].params["btc_cap"] == 0.10
    assert configs["btc_supertrend_satellite_5"].mode is StrategyMode.COMPARISON
    assert configs["btc_supertrend_satellite_10"].mode is StrategyMode.COMPARISON

    with pytest.raises(ComparisonStrategyError):
        require_paper_strategy("btc_supertrend_satellite_5")


def test_frozen_next_open_registry_configuration():
    risk_parity = get_strategy("risk_parity_core_next_open")
    bull = get_strategy("core90_ma200_bull10")
    raw = get_strategy("core90_raw_bull10")

    assert risk_parity.version == "1.0.0"
    assert risk_parity.execution == "next_open"
    assert risk_parity.params["risk_parity_window"] == 20
    assert risk_parity.params["rebalance_sessions"] == 10
    assert risk_parity.params["schedule_anchor_signal_date"] == "2026-07-01"
    assert risk_parity.params["one_way_cost_bps"] == 10.0
    assert bull.version == "2.1.0"
    assert bull.params["sleeve_execution_contract"] == "proportional_next_open_v1"
    assert bull.execution == "next_open"
    assert bull.params["core_allocation"] == 0.90
    assert bull.params["satellite_allocation"] == 0.10
    assert bull.params["supertrend_atr_window"] == 7
    assert bull.params["supertrend_multiplier"] == 3.0
    assert bull.params["ma_window"] == 200
    assert bull.params["signal_contract_version"] == "bull_flip_ma200_v1"
    assert "policy_version" not in bull.params
    assert raw.mode is StrategyMode.PAPER
    assert raw.params["signal_contract_version"] == "bull_flip_raw_v1"
    assert require_paper_strategy("core90_raw_bull10") is raw


def test_theme_alpha_registry_configuration():
    config = get_strategy("theme_alpha")

    assert config.version == "1.0.0"
    assert config.execution == "next_close"
    assert config.params["core_allocation"] == 0.80
    assert config.params["lvt_allocation"] == 0.20
    assert config.params["ma_window"] == 60
    assert config.params["momentum_window"] == 63
    assert config.params["volatility_window"] == 60
    assert config.params["top_n"] == 3
    assert config.params["risk_parity_window"] == 20
    assert config.params["single_asset_cap"] == 0.50
    assert config.params["defense_ma_window"] == 200
    assert config.params["rebalance_threshold"] == 0.02
    assert config.params["max_asset_trade"] == 0.15
    assert config.params["signal_days"] == (10, 25)
    assert config.costs.base_bps == 20
    assert config.costs.extra_bps("510300.SS") == 5
    assert config.costs.extra_bps("513100.SS") == 20
    assert config.costs.extra_bps("512400.SS") == 10
    assert len(config.symbols) == 11


def test_strategy_configuration_is_immutable():
    config = get_strategy("btc_supertrend_satellite")

    with pytest.raises(TypeError):
        config.params["btc_cap"] = 0.50
