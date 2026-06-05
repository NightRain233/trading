import importlib.util
from pathlib import Path

import pandas as pd


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "research_rs_drawdown_protection.py"
SPEC = importlib.util.spec_from_file_location("research_rs_drawdown_protection", SCRIPT_PATH)
research_rs_drawdown_protection = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(research_rs_drawdown_protection)


def _price_frame(values):
    index = pd.date_range("2024-01-01", periods=len(values), freq="D")
    close = pd.Series(values, index=index)
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + 1,
            "Low": close - 1,
            "Close": close,
            "Volume": [1_000_000_000] * len(index),
        },
        index=index,
    )


def test_drawdown_protection_triggers_only_after_threshold_and_recovers():
    state = research_rs_drawdown_protection.DrawdownProtectionState(
        trigger_drawdown_pct=10.0,
        recover_drawdown_pct=4.0,
        protected_exposure=0.6,
    )

    exposures = [state.update(equity) for equity in [1.0, 0.95, 0.90, 0.93, 0.96, 1.01]]

    assert exposures == [1.0, 1.0, 0.6, 0.6, 1.0, 1.0]
    assert state.activation_count == 1
    assert state.protected_day_count == 2


def test_drawdown_protection_uses_full_exposure_when_never_triggered():
    state = research_rs_drawdown_protection.DrawdownProtectionState(
        trigger_drawdown_pct=10.0,
        recover_drawdown_pct=4.0,
        protected_exposure=0.6,
    )

    exposures = [state.update(equity) for equity in [1.0, 0.98, 0.97, 0.99]]

    assert exposures == [1.0, 1.0, 1.0, 1.0]
    assert state.activation_count == 0
    assert state.protected_day_count == 0


def test_simulation_leaves_cash_only_after_drawdown_trigger(monkeypatch):
    frames = {
        "AAA": _price_frame([100, 100, 100, 80, 80, 130, 130, 130]),
        "BBB": _price_frame([100, 100, 100, 80, 80, 130, 130, 130]),
    }

    monkeypatch.setattr(
        research_rs_drawdown_protection.backtest,
        "_rs_rank_symbols",
        lambda *args, **kwargs: ["AAA", "BBB"],
    )

    result = research_rs_drawdown_protection.simulate_rs_rotation_with_drawdown_protection(
        frames,
        top_n=2,
        rebalance_days=1,
        lookback_bars=1,
        min_history_bars=0,
        min_avg_volume=0,
        trigger_drawdown_pct=10.0,
        recover_drawdown_pct=4.0,
        protected_exposure=0.5,
    )

    targets = [point["targetExposure"] for point in result["equityCurve"]]
    assert targets[:3] == [1.0, 1.0, 1.0]
    assert targets[3] == 0.5
    assert targets[5] == 1.0
    assert result["protectionActivationCount"] == 1
    assert result["protectedDayCount"] > 0


def test_simulation_can_recover_from_shadow_strategy_equity(monkeypatch):
    frames = {
        "AAA": _price_frame([100, 100, 100, 80, 80, 100, 100, 100]),
        "BBB": _price_frame([100, 100, 100, 80, 80, 100, 100, 100]),
    }
    signal_equity = {
        pd.Timestamp("2024-01-01"): 1.0,
        pd.Timestamp("2024-01-02"): 1.0,
        pd.Timestamp("2024-01-03"): 1.0,
        pd.Timestamp("2024-01-04"): 0.8,
        pd.Timestamp("2024-01-05"): 0.8,
        pd.Timestamp("2024-01-06"): 1.0,
        pd.Timestamp("2024-01-07"): 1.0,
        pd.Timestamp("2024-01-08"): 1.0,
    }

    monkeypatch.setattr(
        research_rs_drawdown_protection.backtest,
        "_rs_rank_symbols",
        lambda *args, **kwargs: ["AAA", "BBB"],
    )

    result = research_rs_drawdown_protection.simulate_rs_rotation_with_drawdown_protection(
        frames,
        top_n=2,
        rebalance_days=1,
        lookback_bars=1,
        min_history_bars=0,
        min_avg_volume=0,
        trigger_drawdown_pct=10.0,
        recover_drawdown_pct=4.0,
        protected_exposure=0.5,
        protection_signal_equity_by_date=signal_equity,
    )

    targets = [point["targetExposure"] for point in result["equityCurve"]]
    assert targets[3] == 0.5
    assert targets[5] == 1.0


def test_market_confirmation_blocks_drawdown_trigger_until_market_is_weak(monkeypatch):
    frames = {
        "AAA": _price_frame([100, 100, 100, 80, 80, 80]),
        "BBB": _price_frame([100, 100, 100, 80, 80, 80]),
    }
    signal_equity = {
        pd.Timestamp("2024-01-01"): 1.0,
        pd.Timestamp("2024-01-02"): 1.0,
        pd.Timestamp("2024-01-03"): 1.0,
        pd.Timestamp("2024-01-04"): 0.8,
        pd.Timestamp("2024-01-05"): 0.8,
        pd.Timestamp("2024-01-06"): 0.8,
    }
    market_weakness = {
        pd.Timestamp("2024-01-04"): False,
        pd.Timestamp("2024-01-05"): True,
        pd.Timestamp("2024-01-06"): True,
    }

    monkeypatch.setattr(
        research_rs_drawdown_protection.backtest,
        "_rs_rank_symbols",
        lambda *args, **kwargs: ["AAA", "BBB"],
    )

    result = research_rs_drawdown_protection.simulate_rs_rotation_with_drawdown_protection(
        frames,
        top_n=2,
        rebalance_days=1,
        lookback_bars=1,
        min_history_bars=0,
        min_avg_volume=0,
        trigger_drawdown_pct=10.0,
        recover_drawdown_pct=4.0,
        protected_exposure=0.5,
        protection_signal_equity_by_date=signal_equity,
        market_weakness_by_date=market_weakness,
    )

    targets = [point["targetExposure"] for point in result["equityCurve"]]
    assert targets[3] == 1.0
    assert targets[4] == 0.5
