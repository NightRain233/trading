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


def test_constant_fx_counterfactual_uses_local_usd_prices_and_cny_domestic_prices():
    module = load_research_module()
    dates = pd.to_datetime(["2025-01-02", "2025-01-03"])
    raw_frames = {
        "SPY": pd.DataFrame({"Close": [10.0, 11.0]}, index=dates),
        "510300.SS": pd.DataFrame({"Close": [4.0, 4.1]}, index=dates),
    }
    cny_frames = {
        "SPY": pd.DataFrame({"Close": [70.0, 78.1]}, index=dates),
        "510300.SS": pd.DataFrame({"Close": [4.0, 4.1]}, index=dates),
    }
    metadata = {
        "SPY": {"currency": "USD"},
        "510300.SS": {"currency": "CNY"},
    }

    counterfactual = module.build_constant_fx_counterfactual_frames(
        raw_frames,
        cny_frames,
        metadata,
    )

    assert counterfactual["SPY"].equals(raw_frames["SPY"])
    assert counterfactual["510300.SS"].equals(cny_frames["510300.SS"])


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
    assert summary["longestLosingStreakDays"] >= 92
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


def test_dca_reports_annualized_money_weighted_return_when_dates_are_known():
    module = load_research_module()
    result = module.summarize_dca(
        contributions=[{"date": "2024-01-01", "amount": 1000}],
        ending_value=1100,
        time_weighted_return_pct=10.0,
        ending_date="2025-01-01",
    )

    assert result["moneyWeightedReturnPct"] == pytest.approx(9.98, abs=0.01)


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


def test_static_allocation_benchmark_keeps_rolling_metrics(monkeypatch):
    module = load_research_module()
    dates = pd.date_range("2018-01-31", periods=97, freq="ME")
    curve = [
        {"date": date.date().isoformat(), "equity": 1.0 + index * 0.01}
        for index, date in enumerate(dates)
    ]

    monkeypatch.setattr(
        module,
        "simulate_monthly_portfolio",
        lambda *args, **kwargs: {
            "equityCurve": curve,
            "rebalances": [],
            "costPaid": 0.0,
        },
    )

    result = module.simulate_static_allocation_benchmark(
        frames={},
        asset_metadata={},
        start=None,
        end=None,
    )

    assert result["summary"]["worstRolling3YearReturnPct"] is not None
    assert result["summary"]["worstRolling5YearReturnPct"] is not None


def test_static_weight_grid_is_deterministic_complete_and_sums_to_one():
    module = load_research_module()

    first = module.build_static_weight_grid()
    second = module.build_static_weight_grid()
    core = [row for row in first if row["neighborhood"] == "core"]

    assert first == second
    assert len(first) == 85
    assert len(core) == 19
    assert len({row["id"] for row in first}) == 85
    assert all(sum(row["weights"].values()) == pytest.approx(1.0) for row in first)
    assert all(sum(row["offsets"].values()) == pytest.approx(0.0) for row in first)
    assert sum(row["isBaseline"] for row in first) == 1


def test_static_category_targets_split_a_share_and_us_weights_equally():
    module = load_research_module()
    date = pd.Timestamp("2025-01-31")
    frames = {
        symbol: pd.DataFrame({"Close": [1.0]}, index=[date])
        for symbol in ("A1", "A2", "SPY", "QQQ", "GLD", "511010.SS")
    }
    metadata = {
        "A1": {"assetClass": "a_share_equity"},
        "A2": {"assetClass": "a_share_equity"},
        "SPY": {"assetClass": "us_equity"},
        "QQQ": {"assetClass": "us_equity"},
        "GLD": {"assetClass": "gold"},
        "511010.SS": {"assetClass": "a_bond"},
    }

    weights = module.build_static_category_target_weights(
        frames,
        metadata,
        as_of=date,
        category_weights={
            "a_share_equity": 0.30,
            "us_equity": 0.20,
            "gold": 0.10,
            "a_bond": 0.40,
        },
    )

    assert weights == pytest.approx(
        {
            "A1": 0.15,
            "A2": 0.15,
            "SPY": 0.10,
            "QQQ": 0.10,
            "GLD": 0.10,
            "511010.SS": 0.40,
        }
    )


def test_static_weight_stability_requires_core_unanimity_and_broad_eighty_percent():
    module = load_research_module()
    grid = module.build_static_weight_grid()
    broad_only = [row for row in grid if row["neighborhood"] == "broad"]
    target_ids = {row["id"] for row in grid if row["neighborhood"] == "core"}
    target_ids.update(row["id"] for row in broad_only[: 68 - len(target_ids)])
    points = [
        {
            **row,
            "summary": {
                "cagrPct": 10.0 if row["id"] in target_ids else 7.9,
                "maxDrawdownPct": 14.0,
            },
        }
        for row in grid
    ]

    result = module.summarize_static_weight_stability(points)

    assert result["core"]["pointCount"] == 19
    assert result["core"]["targetPassRate"] == pytest.approx(1.0)
    assert result["core"]["pass"] is True
    assert result["broad"]["pointCount"] == 85
    assert result["broad"]["targetPassRate"] == pytest.approx(0.8)
    assert result["broad"]["pass"] is True
    assert result["pass"] is True


def test_static_weight_stability_fails_for_one_core_miss_or_one_hard_drawdown_miss():
    module = load_research_module()
    grid = module.build_static_weight_grid()
    passing = [
        {
            **row,
            "summary": {"cagrPct": 10.0, "maxDrawdownPct": 14.0},
        }
        for row in grid
    ]
    core_miss = [dict(row, summary=dict(row["summary"])) for row in passing]
    core_index = next(index for index, row in enumerate(core_miss) if row["neighborhood"] == "core")
    core_miss[core_index]["summary"]["cagrPct"] = 7.9
    hard_miss = [dict(row, summary=dict(row["summary"])) for row in passing]
    hard_miss[-1]["summary"]["maxDrawdownPct"] = 20.01

    assert module.summarize_static_weight_stability(core_miss)["pass"] is False
    hard_result = module.summarize_static_weight_stability(hard_miss)
    assert hard_result["broad"]["hardDrawdownPassRate"] < 1.0
    assert hard_result["broad"]["pass"] is False
    assert hard_result["pass"] is False


def test_asset_correlation_matrix_uses_cny_return_series():
    module = load_research_module()
    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    frames = {
        "A": pd.DataFrame({"Close": [1, 2, 3, 4, 5]}, index=dates),
        "B": pd.DataFrame({"Close": [2, 4, 6, 8, 10]}, index=dates),
    }

    matrix = module.asset_correlation_matrix(frames, "2025-01-01", "2025-01-05")

    assert matrix["A"]["B"] == pytest.approx(1.0)
    assert matrix["B"]["A"] == pytest.approx(1.0)


def test_recommendation_surfaces_headline_matching_static_benchmark_without_promoting_it():
    module = load_research_module()
    variant = {
        "id": "trend_near_miss",
        "spec": {
            "strategy": "trend_risk_budget",
            "trendMode": "mom12",
            "btcCap": 0.05,
            "volatilityLookback": 120,
            "driftThreshold": 0.05,
            "rsTopN": None,
            "usRsTilt": False,
        },
        "summary": {"cagrPct": 13.0, "maxDrawdownPct": 19.0, "calmar": 0.68},
        "gate": {
            "eligible": True,
            "targetReturnMet": False,
            "targetDrawdownMet": False,
            "hardDrawdownMet": True,
        },
    }
    benchmark = {
        "id": "static_stock_bond_gold_cny",
        "gate": {
            "eligible": True,
            "targetReturnMet": True,
            "targetDrawdownMet": True,
        },
    }

    recommendation, stability = module._recommend_candidate([variant], [benchmark])

    assert recommendation["status"] == "no_target_default"
    assert recommendation["researchLeadId"] == "static_stock_bond_gold_cny"
    assert "基准" in recommendation["reason"]
    assert stability["pass"] is True


def test_recommendation_promotes_static_benchmark_only_after_weight_stability_passes():
    module = load_research_module()
    benchmark = {
        "id": "static_stock_bond_gold_cny",
        "gate": {
            "eligible": True,
            "targetReturnMet": True,
            "targetDrawdownMet": True,
        },
    }

    recommendation, stability = module._recommend_candidate(
        [],
        [benchmark],
        static_weight_stability={"pass": True},
    )

    assert recommendation["status"] == "eligible_static_default"
    assert recommendation["candidateId"] == "static_stock_bond_gold_cny"
    assert recommendation["researchLeadId"] == "static_stock_bond_gold_cny"
    assert stability["pass"] is True


def test_render_report_includes_failed_candidates_and_coverage_limitations():
    module = load_research_module()
    markdown = module.render_markdown_report(
        {
            "coverage": {
                "commonStartDate": "2015-01-01",
                "commonEndDate": "2026-06-05",
                "missingStressPeriods": ["2008"],
                "bySymbol": {},
            },
            "assumptions": {},
            "variants": [
                {
                    "id": "bad",
                    "summary": {"cagrPct": 9.0, "maxDrawdownPct": 25.0},
                    "gate": {"eligible": False, "failedGates": ["hard_drawdown_limit"]},
                    "annual": [],
                    "rolling3": [],
                    "rolling5": [],
                    "costPaid": 0.0,
                    "rebalanceCount": 0,
                }
            ],
            "benchmarks": [],
            "recommendation": {"status": "no_eligible_default", "candidateId": None},
            "stability": {},
            "btcSensitivity": [],
        }
    )

    assert "2008" in markdown
    assert "bad" in markdown
    assert "当前没有合格默认策略" in markdown


def test_render_report_includes_static_weight_stability_grid_and_verdict():
    module = load_research_module()
    markdown = module.render_markdown_report(
        {
            "coverage": {
                "commonStartDate": "2015-01-01",
                "commonEndDate": "2026-06-05",
                "missingStressPeriods": ["2008"],
                "bySymbol": {},
            },
            "variants": [],
            "benchmarks": [],
            "recommendation": {
                "status": "eligible_static_default",
                "candidateId": "static_stock_bond_gold_cny",
                "reason": "静态权重稳定性通过。",
            },
            "stability": {},
            "btcSensitivity": [],
            "staticWeightStability": {
                "pass": True,
                "baselineWeights": {
                    "a_share_equity": 0.20,
                    "us_equity": 0.30,
                    "gold": 0.20,
                    "a_bond": 0.30,
                },
                "core": {
                    "pointCount": 19,
                    "targetPassCount": 19,
                    "targetPassRate": 1.0,
                    "hardDrawdownPassCount": 19,
                    "hardDrawdownPassRate": 1.0,
                    "cagrRangePct": [9.0, 11.5],
                    "drawdownRangePct": [10.0, 14.5],
                    "pass": True,
                },
                "broad": {
                    "pointCount": 85,
                    "targetPassCount": 68,
                    "targetPassRate": 0.8,
                    "hardDrawdownPassCount": 85,
                    "hardDrawdownPassRate": 1.0,
                    "cagrRangePct": [8.0, 12.0],
                    "drawdownRangePct": [9.0, 19.0],
                    "pass": True,
                },
                "points": [
                    {
                        "id": "static_w20_30_20_30",
                        "weights": {
                            "a_share_equity": 0.20,
                            "us_equity": 0.30,
                            "gold": 0.20,
                            "a_bond": 0.30,
                        },
                        "neighborhood": "core",
                        "summary": {
                            "cagrPct": 11.0,
                            "maxDrawdownPct": 12.8,
                            "calmar": 0.86,
                        },
                        "targetPass": True,
                        "hardDrawdownPass": True,
                    }
                ],
            },
        }
    )

    assert "## 静态股债金权重稳定性" in markdown
    assert "核心邻域 CAGR 范围 9.00%～11.50%，最大回撤范围 10.00%～14.50%" in markdown
    assert "广义邻域 CAGR 范围 8.00%～12.00%，最大回撤范围 9.00%～19.00%" in markdown
    assert "| 核心邻域 | 19 | 19 | 100.00% | 19 | 100.00% | 通过 |" in markdown
    assert "| 广义邻域 | 85 | 68 | 80.00% | 85 | 100.00% | 通过 |" in markdown
    assert "| `static_w20_30_20_30` | 核心 | 20.00% | 30.00% | 20.00% | 30.00% | 11.00% | 12.80% | 0.86 | 通过 |" in markdown


def test_render_report_prints_annual_rolling_cost_and_dca_results():
    module = load_research_module()
    markdown = module.render_markdown_report(
        {
            "coverage": {
                "commonStartDate": "2015-01-01",
                "commonEndDate": "2026-06-05",
                "missingStressPeriods": ["2008"],
                "bySymbol": {
                    "SPY": {
                        "startDate": "2000-01-03",
                        "endDate": "2026-06-05",
                        "rows": 6646,
                    }
                },
            },
            "variants": [
                {
                    "id": "candidate",
                    "summary": {
                        "cagrPct": 10.0,
                        "maxDrawdownPct": 14.0,
                        "calmar": 0.71,
                        "worstRolling3YearReturnPct": 4.0,
                        "worstRolling5YearReturnPct": 8.0,
                        "longestRecoveryDays": 300,
                    },
                    "gate": {"eligible": True, "targetDrawdownMet": True},
                    "annual": [{"year": "2025", "returnPct": 9.5, "maxDrawdownPct": 6.0}],
                    "windows": {
                        "recent3Year": {"cagrPct": 8.5, "maxDrawdownPct": 9.0},
                        "recent5Year": {"cagrPct": 9.0, "maxDrawdownPct": 10.0},
                        "recent10Year": {"cagrPct": 9.5, "maxDrawdownPct": 12.0},
                    },
                    "stressPeriods": [
                        {
                            "period": "2020",
                            "available": True,
                            "totalReturnPct": 7.0,
                            "maxDrawdownPct": 8.0,
                        }
                    ],
                    "contributions": {
                        "categoryContribution": {
                            "us_equity": {
                                "returnContribution": 0.12,
                                "riskContribution": 0.4,
                                "drawdownContribution": -0.03,
                            }
                        }
                    },
                    "dca": {
                        "principal": 12000,
                        "endingValue": 13200,
                        "principalReturnPct": 10.0,
                        "moneyWeightedReturnPct": 8.2,
                        "timeWeightedReturnPct": 15.0,
                        "accountMaxDrawdownPct": 7.0,
                    },
                    "costPaid": 0.01,
                    "rebalanceCount": 12,
                    "turnover": {"totalTurnover": 1.5},
                }
            ],
            "benchmarks": [],
            "recommendation": {
                "status": "eligible_default",
                "candidateId": "candidate",
                "reason": "达标。",
            },
            "stability": {"candidateId": "candidate", "pass": True},
            "btcSensitivity": [],
            "currencyContribution": {
                "SPY": {
                    "localReturnPct": 100.0,
                    "cnyReturnPct": 110.0,
                    "currencyEffectPctPoints": 10.0,
                }
            },
            "assetCorrelations": {
                "SPY": {"SPY": 1.0, "GLD": 0.2},
                "GLD": {"SPY": 0.2, "GLD": 1.0},
            },
            "costSensitivity": [
                {
                    "feeBps": 10,
                    "slippageBps": 10,
                    "cagrPct": 9.8,
                    "maxDrawdownPct": 14.2,
                }
            ],
            "fxSensitivity": [
                {
                    "mode": "actual_cny_fx",
                    "cagrPct": 10.0,
                    "maxDrawdownPct": 14.0,
                },
                {
                    "mode": "constant_fx_local_returns",
                    "cagrPct": 9.0,
                    "maxDrawdownPct": 13.5,
                },
            ],
        }
    )

    assert "| 2025 | 9.50% | 6.00% |" in markdown
    assert "| `candidate` | 4.00% | 8.00% | 300 |" in markdown
    assert "| `candidate` | 1.50 | 12 | 1.00% |" in markdown
    assert "| `candidate` | 12000.00 | 13200.00 | 10.00% | 8.20% | 15.00% | 7.00% |" in markdown
    assert "| 10.00 | 10.00 | 9.80% | 14.20% |" in markdown
    assert "| SPY | 2000-01-03 | 2026-06-05 | 6646 |" in markdown
    assert "| `candidate` | 2020 | 7.00% | 8.00% |" in markdown
    assert "| SPY | 100.00% | 110.00% | 10.00% |" in markdown
    assert "| SPY | GLD | 0.20 |" in markdown
    assert "| `candidate` | us_equity | 12.00% | 40.00% | -3.00% |" in markdown
    assert "| constant_fx_local_returns | 9.00% | 13.50% |" in markdown
