import importlib.util
import json
import tempfile
from pathlib import Path

import pandas as pd
import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "backfill_historical_data.py"
SPEC = importlib.util.spec_from_file_location("backfill_historical_data", SCRIPT_PATH)
backfill_historical_data = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backfill_historical_data)


def _ohlcv(values, start="2015-01-01"):
    index = pd.date_range(start, periods=len(values), freq="D")
    close = pd.Series(values, index=index)
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + 1,
            "Low": close - 1,
            "Close": close,
            "Volume": [1000] * len(index),
        },
        index=index,
    )


def test_load_universe_symbols_supports_dict_and_list_files():
    with tempfile.TemporaryDirectory() as tmpdir:
        dict_path = Path(tmpdir) / "dict.json"
        list_path = Path(tmpdir) / "list.json"
        dict_path.write_text(json.dumps({"symbols": [{"symbol": "spy"}, {"symbol": "QQQ"}]}))
        list_path.write_text(json.dumps(["510300.SS", {"symbol": "510500.SS"}]))

        symbols = backfill_historical_data.load_symbols_from_universe_files([dict_path, list_path])

    assert symbols == ["SPY", "QQQ", "510300.SS", "510500.SS"]


def test_backfill_symbol_keeps_history_before_retention_window(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        local = _ohlcv([20, 21], start="2026-01-01")
        local.to_parquet(data_dir / "SPY.parquet")
        downloaded = _ohlcv([10, 11], start="2015-01-01")

        monkeypatch.setattr(backfill_historical_data.analysis.yf, "download", lambda *args, **kwargs: downloaded)
        monkeypatch.setattr(backfill_historical_data.analysis, "_calculate_daily_indicators", lambda df: df)
        monkeypatch.setattr(backfill_historical_data.analysis, "_calculate_weekly_indicators", lambda df: df.tail(1))

        result = backfill_historical_data.backfill_symbol(
            "SPY",
            start="2015-01-01",
            end="2026-06-05",
            data_dir=data_dir,
        )

        stored = pd.read_parquet(data_dir / "SPY.parquet")
        weekly = pd.read_parquet(data_dir / "SPY_weekly.parquet")

    assert result["status"] == "updated"
    assert stored.index.min() == pd.Timestamp("2015-01-01")
    assert stored.index.max() == pd.Timestamp("2026-01-02")
    assert not weekly.empty


def test_backfill_a_share_uses_tickflow_without_yfinance(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        tickflow = _ohlcv([10, 11], start="2015-01-01")

        monkeypatch.setattr(
            backfill_historical_data.analysis.yf,
            "download",
            lambda *args, **kwargs: pytest.fail(
                "Yahoo must not fetch A-share history"
            ),
        )
        monkeypatch.setattr(
            backfill_historical_data.analysis,
            "_fetch_tickflow_daily",
            lambda *args, **kwargs: tickflow,
        )
        monkeypatch.setattr(backfill_historical_data.analysis, "_calculate_daily_indicators", lambda df: df)
        monkeypatch.setattr(backfill_historical_data.analysis, "_calculate_weekly_indicators", lambda df: df.tail(1))

        result = backfill_historical_data.backfill_symbol(
            "510300.SS",
            start="2015-01-01",
            end="2026-06-05",
            data_dir=data_dir,
        )

        stored = pd.read_parquet(data_dir / "510300.SS.parquet")

    assert result["status"] == "updated"
    assert result["usedTickFlow"] is True
    assert stored.index.min() == pd.Timestamp("2015-01-01")
    assert len(stored) == 2
