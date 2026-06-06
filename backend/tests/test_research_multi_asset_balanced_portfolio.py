import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "research_multi_asset_balanced_portfolio.py"
UNIVERSE_PATH = ROOT / "backend" / "universes" / "multi_asset_balanced.json"


def load_research_module():
    spec = importlib.util.spec_from_file_location(
        "research_multi_asset_balanced_portfolio",
        SCRIPT_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_balanced_universe_declares_assets_currency_and_caps():
    payload = json.loads(UNIVERSE_PATH.read_text(encoding="utf-8"))
    by_symbol = {row["symbol"]: row for row in payload["assets"]}

    assert by_symbol["SPY"]["currency"] == "USD"
    assert by_symbol["QQQ"]["assetClass"] == "us_equity"
    assert by_symbol["GLD"]["assetClass"] == "gold"
    assert by_symbol["511010.SS"]["assetClass"] == "a_bond"
    assert by_symbol["BTC-USD"]["maxWeight"] == 0.05
    assert payload["fxSymbol"] == "CNY=X"


def test_load_universe_adds_only_a_share_broad_assets(tmp_path):
    module = load_research_module()
    a_share_path = tmp_path / "a_share.json"
    a_share_path.write_text(
        json.dumps(
            {
                "symbols": [
                    {"symbol": "510300.SS", "name": "沪深300ETF", "bucket": "broad"},
                    {"symbol": "512760.SS", "name": "芯片ETF", "bucket": "sector"},
                ]
            }
        ),
        encoding="utf-8",
    )
    config = {
        "assets": [],
        "aShareUniverseFile": a_share_path.name,
        "aShareBucket": "broad",
    }

    assets = module.expand_assets(config, a_share_path.parent)

    assert [row["symbol"] for row in assets] == ["510300.SS"]
    assert assets[0]["assetClass"] == "a_share_equity"
    assert assets[0]["currency"] == "CNY"
    assert assets[0]["maxWeight"] == 0.25


def test_normalize_ohlc_to_cny_multiplies_usd_prices_by_known_fx():
    module = load_research_module()
    dates = pd.to_datetime(["2025-01-02", "2025-01-03"])
    asset = pd.DataFrame(
        {
            "Open": [10.0, 11.0],
            "High": [11.0, 12.0],
            "Low": [9.0, 10.0],
            "Close": [10.5, 11.5],
        },
        index=dates,
    )
    fx = pd.DataFrame(
        {
            "Open": [7.0, 7.1],
            "High": [7.0, 7.1],
            "Low": [7.0, 7.1],
            "Close": [7.0, 7.1],
        },
        index=dates,
    )

    converted = module.normalize_ohlc_to_cny(asset, "USD", fx)

    assert converted.loc[dates[0], "Open"] == 70.0
    assert converted.loc[dates[1], "Close"] == pytest.approx(81.65)


def test_fx_alignment_never_backfills_future_rates():
    module = load_research_module()
    dates = pd.to_datetime(["2025-01-02", "2025-01-03"])
    asset = pd.DataFrame({"Close": [10.0, 11.0]}, index=dates)
    fx = pd.DataFrame(
        {"Close": [7.0]},
        index=pd.to_datetime(["2025-01-03"]),
    )

    converted = module.normalize_ohlc_to_cny(asset, "USD", fx)

    assert pd.isna(converted.loc[pd.Timestamp("2025-01-02"), "Close"])
    assert converted.loc[pd.Timestamp("2025-01-03"), "Close"] == 77.0


def test_monthly_trend_signals_use_only_completed_months():
    module = load_research_module()
    index = pd.date_range("2024-01-02", "2025-02-14", freq="B")
    close = pd.Series(range(100, 100 + len(index)), index=index, dtype="float64")
    frame = pd.DataFrame({"Close": close})

    signals = module.build_monthly_trend_signals(
        frame,
        mode="ma10",
        as_of=pd.Timestamp("2025-02-14"),
    )

    assert signals.index.max() <= pd.Timestamp("2025-01-31")
    assert pd.Timestamp("2025-02-28") not in signals.index


def test_combined_trend_requires_ma10_and_positive_12_month_momentum():
    module = load_research_module()
    monthly = pd.Series(
        [100, 102, 104, 106, 108, 110, 112, 114, 116, 118, 120, 122, 121],
        index=pd.date_range("2024-01-31", periods=13, freq="ME"),
        dtype="float64",
    )

    result = module.evaluate_monthly_trend(monthly, mode="ma10_and_mom12")

    assert bool(result.iloc[-1]) is True


def test_combined_trend_rejects_positive_ma_when_twelve_month_momentum_is_negative():
    module = load_research_module()
    monthly = pd.Series(
        [130, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 120],
        index=pd.date_range("2024-01-31", periods=13, freq="ME"),
        dtype="float64",
    )

    result = module.evaluate_monthly_trend(monthly, mode="ma10_and_mom12")

    assert bool(result.iloc[-1]) is False


def test_inverse_volatility_gives_less_weight_to_high_volatility_asset():
    module = load_research_module()

    weights = module.inverse_volatility_weights({"LOW": 0.10, "HIGH": 0.40})

    assert weights["LOW"] == pytest.approx(0.8)
    assert weights["HIGH"] == pytest.approx(0.2)


def test_apply_caps_redistributes_without_breaking_category_or_symbol_caps():
    module = load_research_module()
    assets = {
        "SPY": {"assetClass": "us_equity", "maxWeight": 0.25},
        "QQQ": {"assetClass": "us_equity", "maxWeight": 0.25},
        "GLD": {"assetClass": "gold", "maxWeight": 0.25},
    }
    raw = {"SPY": 0.45, "QQQ": 0.35, "GLD": 0.20}
    category_caps = {"us_equity": 0.40, "gold": 0.25}

    capped = module.apply_weight_caps(raw, assets, category_caps)

    assert capped["SPY"] <= 0.25
    assert capped["QQQ"] <= 0.25
    assert capped["SPY"] + capped["QQQ"] <= 0.40
    assert capped["GLD"] <= 0.25
    assert sum(capped.values()) <= 1.0


def test_crypto_cap_override_supports_zero_five_and_ten_percent():
    module = load_research_module()
    assets = {"BTC-USD": {"assetClass": "crypto", "maxWeight": 0.05}}

    assert module.with_btc_cap(assets, 0.0)["BTC-USD"]["maxWeight"] == 0.0
    assert module.with_btc_cap(assets, 0.05)["BTC-USD"]["maxWeight"] == 0.05
    assert module.with_btc_cap(assets, 0.10)["BTC-USD"]["maxWeight"] == 0.10
    assert assets["BTC-USD"]["maxWeight"] == 0.05


def test_a_share_rs_selects_only_assets_with_sufficient_history():
    module = load_research_module()
    date = pd.Timestamp("2025-06-30")
    frames = {
        "A": pd.DataFrame(
            {"Close": range(100, 221)},
            index=pd.date_range("2025-01-01", periods=121, freq="B"),
        ),
        "B": pd.DataFrame(
            {"Close": range(100, 161)},
            index=pd.date_range("2025-04-01", periods=61, freq="B"),
        ),
    }

    selected = module.select_relative_strength(
        frames,
        ["A", "B"],
        date,
        lookback=120,
        top_n=1,
    )

    assert selected == ["A"]


def test_rebalance_executes_at_next_common_open_after_completed_month():
    module = load_research_module()
    dates_a = pd.to_datetime(["2025-01-30", "2025-02-03", "2025-02-04"])
    dates_b = pd.to_datetime(["2025-01-31", "2025-02-04", "2025-02-05"])
    frames = {
        "A": pd.DataFrame(
            {"Open": [100.0, 110.0, 111.0], "Close": [101.0, 110.0, 111.0]},
            index=dates_a,
        ),
        "B": pd.DataFrame(
            {"Open": [200.0, 220.0, 221.0], "Close": [201.0, 220.0, 221.0]},
            index=dates_b,
        ),
    }

    execution_date = module.next_common_trading_date(
        frames,
        ["A", "B"],
        pd.Timestamp("2025-01-31"),
    )

    assert execution_date == pd.Timestamp("2025-02-04")


def test_drift_threshold_suppresses_small_trades():
    module = load_research_module()

    assert module.should_trade({"A": 0.48, "__CASH__": 0.52}, {"A": 0.50, "__CASH__": 0.50}, 0.05) is False
    assert module.should_trade({"A": 0.40, "__CASH__": 0.60}, {"A": 0.50, "__CASH__": 0.50}, 0.05) is True


def test_rebalance_at_open_uses_open_and_never_creates_negative_cash():
    module = load_research_module()
    date = pd.Timestamp("2025-02-03")
    frames = {
        "A": pd.DataFrame(
            {"Open": [100.0], "Close": [120.0]},
            index=[date],
        )
    }
    state = {"cash": 1.0, "shares": {}, "lastPrices": {}, "costPaid": 0.0}

    result = module.rebalance_at_open(
        state,
        target_weights={"A": 1.0},
        frames=frames,
        date=date,
        fee_bps=5.0,
        slippage_bps=5.0,
    )

    assert result["cash"] >= 0
    assert result["shares"]["A"] < 0.01
    assert result["lastPrices"]["A"] == pytest.approx(100.05)


def test_trade_costs_reduce_final_equity():
    module = load_research_module()

    no_cost = module.simulate_monthly_portfolio_for_test(fee_bps=0, slippage_bps=0)
    with_cost = module.simulate_monthly_portfolio_for_test(fee_bps=5, slippage_bps=5)

    assert with_cost["equityCurve"][-1]["equity"] < no_cost["equityCurve"][-1]["equity"]


def test_equity_summary_calculates_drawdown_and_recovery():
    module = load_research_module()
    curve = [
        {"date": "2020-01-01", "equity": 1.0},
        {"date": "2020-06-01", "equity": 1.2},
        {"date": "2020-09-01", "equity": 0.9},
        {"date": "2021-01-01", "equity": 1.2},
        {"date": "2025-01-01", "equity": 1.6},
    ]

    summary = module.summarize_equity_curve(curve)

    assert summary["maxDrawdownPct"] == pytest.approx(25.0)
    assert summary["longestRecoveryDays"] >= 122
    assert summary["historyYears"] >= 5.0


def test_product_gate_rejects_drawdown_above_twenty_percent():
    module = load_research_module()
    verdict = module.evaluate_product_gate(
        {
            "cagrPct": 10.0,
            "maxDrawdownPct": 20.01,
            "worstRolling3YearReturnPct": 5.0,
            "longestRecoveryDays": 500,
            "historyYears": 10.0,
        }
    )

    assert verdict["eligible"] is False
    assert "hard_drawdown_limit" in verdict["failedGates"]


def test_product_gate_rejects_history_shorter_than_five_years():
    module = load_research_module()
    verdict = module.evaluate_product_gate(
        {
            "cagrPct": 10.0,
            "maxDrawdownPct": 12.0,
            "worstRolling3YearReturnPct": 4.0,
            "longestRecoveryDays": 300,
            "historyYears": 4.9,
        }
    )

    assert verdict["eligible"] is False
    assert "minimum_history" in verdict["failedGates"]


def test_dca_principal_is_not_counted_as_strategy_return():
    module = load_research_module()
    result = module.summarize_dca(
        contributions=[
            {"date": "2025-01-01", "amount": 1000},
            {"date": "2025-02-01", "amount": 1000},
        ],
        ending_value=2100,
        time_weighted_return_pct=5.0,
    )

    assert result["principal"] == 2000
    assert result["profit"] == 100
    assert result["principalReturnPct"] == pytest.approx(5.0)
    assert result["timeWeightedReturnPct"] == 5.0


def test_rolling_window_stats_identify_worst_three_year_period():
    module = load_research_module()
    curve = [
        {"date": "2020-01-01", "equity": 1.0},
        {"date": "2021-01-01", "equity": 1.1},
        {"date": "2022-01-01", "equity": 0.9},
        {"date": "2023-01-01", "equity": 0.8},
        {"date": "2024-01-01", "equity": 1.2},
        {"date": "2025-01-01", "equity": 1.5},
    ]

    rows = module.rolling_window_stats(curve, years=3)

    assert rows
    assert min(row["returnPct"] for row in rows) < 0


def test_variant_matrix_reports_every_predeclared_parameter_combination():
    module = load_research_module()
    variants = module.build_variant_specs()

    keys = {row["id"] for row in variants}
    assert "static_risk_budget_vol60_btc0" in keys
    assert "trend_ma10_vol60_btc5" in keys
    assert "trend_mom12_vol120_btc10" in keys
    assert "trend_combined_vol120_btc5" in keys
    assert "trend_combined_vol120_btc5_rs_top1" in keys
    assert {row["trendMode"] for row in variants if row["strategy"] != "static_risk_budget"} >= {
        "ma10",
        "mom12",
        "ma10_and_mom12",
    }
    assert {row["volatilityLookback"] for row in variants} == {60, 120}
    assert {row["btcCap"] for row in variants} == {0.0, 0.05, 0.10}
    assert {row["driftThreshold"] for row in variants} == {0.0, 0.05}
    assert len(keys) == len(variants)
