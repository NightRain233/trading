import importlib.util
from datetime import date
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "update_market_data.py"
SPEC = importlib.util.spec_from_file_location("update_market_data", SCRIPT_PATH)
update_market_data = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(update_market_data)


def test_list_cached_symbols_skips_weekly_and_sidecar_files(tmp_path):
    for name in ["SPY.parquet", "SPY_weekly.parquet", "510300.SS.parquet", "510300.SS.parquet.source.json"]:
        (tmp_path / name).write_bytes(b"")

    assert update_market_data.list_cached_symbols(tmp_path) == ["510300.SS", "SPY"]


def test_find_stale_compares_within_market_and_flags_old_or_unreadable():
    today = date(2026, 10, 27)
    last_dates = {
        "510300.SS": date(2026, 10, 27),
        "513100.SS": date(2026, 10, 24),  # behind A-share peers
        "BTC-USD": date(2026, 10, 27),
        "SPY": date(2026, 10, 26),  # US peers are allowed their own calendar
        "QQQ": date(2026, 10, 26),
        "2800.HK": date(2026, 10, 10),  # whole market too old
        "GC=F": None,
    }

    stale = update_market_data.find_stale(last_dates, today, max_age_days=5)

    assert set(stale) == {"513100.SS", "2800.HK", "GC=F"}
    assert stale["GC=F"] == "unreadable"
