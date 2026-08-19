from datetime import datetime
import importlib.util
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "replay_unified_decisions.py"
SPEC = importlib.util.spec_from_file_location("replay_unified_decisions", SCRIPT)
replay_unified_decisions = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(replay_unified_decisions)


def test_item_as_of_never_passes_future_daily_rows_to_production_builder(monkeypatch):
    daily = pd.DataFrame(
        {"Close": [10.0, 11.0, 12.0]},
        index=pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07"]),
    )
    weekly = pd.DataFrame(
        {"Close": [10.0, 12.0]},
        index=pd.to_datetime(["2026-01-04", "2026-01-11"]),
    )
    captured = {}

    def fake_builder(symbol, daily_frame, weekly_frame, **kwargs):
        captured["dailyMax"] = daily_frame.index.max()
        captured["weeklyMax"] = weekly_frame.index.max()
        captured["now"] = kwargs["now"]
        return {"symbol": symbol}

    monkeypatch.setattr(replay_unified_decisions.main, "_build_supertrend_scan_item", fake_builder)
    as_of = pd.Timestamp("2026-01-06")
    clock = replay_unified_decisions._evaluation_clock("510300.SS", as_of)

    item = replay_unified_decisions._item_as_of(
        "510300.SS",
        {"510300.SS": (daily, weekly)},
        as_of,
        clock,
    )

    assert item == {"symbol": "510300.SS"}
    assert captured["dailyMax"] == as_of
    assert captured["weeklyMax"] == pd.Timestamp("2026-01-11")
    assert captured["now"] == clock


def test_evaluation_clock_uses_target_trading_venue():
    date = pd.Timestamp("2026-01-06")
    china = replay_unified_decisions._evaluation_clock("510300.SS", date)
    us = replay_unified_decisions._evaluation_clock("SPY", date)
    crypto = replay_unified_decisions._evaluation_clock("BTC-USD", date)

    assert isinstance(china, datetime)
    assert china.tzinfo is not None and china.hour == 15
    assert us.tzinfo is not None and us.hour == 16
    assert crypto.date().isoformat() == "2026-01-07"
