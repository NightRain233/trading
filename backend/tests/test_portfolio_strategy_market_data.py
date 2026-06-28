from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from portfolio_strategies.market_data import (
    build_portfolio_market_data,
    filter_completed_rows,
    load_strategy_market_data,
    refresh_strategy_universe,
)
from portfolio_strategies.registry import get_strategy
from portfolio_strategies.schedules import xshg_sessions


SHANGHAI = ZoneInfo("Asia/Shanghai")
UTC = ZoneInfo("UTC")


def _frame(index: pd.DatetimeIndex, start: float = 100.0) -> pd.DataFrame:
    values = pd.Series(range(len(index)), index=index, dtype=float) + start
    return pd.DataFrame(
        {
            "Open": values - 0.5,
            "High": values + 1.0,
            "Low": values - 1.0,
            "Close": values,
            "Volume": 1_000_000.0,
        },
        index=index,
    )


def _theme_frames(sessions: pd.DatetimeIndex) -> dict[str, pd.DataFrame]:
    config = get_strategy("theme_alpha")
    return {
        symbol: _frame(sessions, 100.0 + position * 10)
        for position, symbol in enumerate(config.symbols)
    }


def test_a_share_same_day_row_is_incomplete_before_market_cutoff():
    asset = get_strategy("theme_alpha").asset("510300.SS")
    frame = _frame(pd.to_datetime(["2026-06-25", "2026-06-26"]))

    completed = filter_completed_rows(
        asset,
        frame,
        datetime(2026, 6, 26, 14, 59, tzinfo=SHANGHAI),
    )

    assert completed.index.max() == pd.Timestamp("2026-06-25")


def test_a_share_same_day_row_is_complete_after_market_cutoff():
    asset = get_strategy("theme_alpha").asset("510300.SS")
    frame = _frame(pd.to_datetime(["2026-06-25", "2026-06-26"]))

    completed = filter_completed_rows(
        asset,
        frame,
        datetime(2026, 6, 26, 15, 10, tzinfo=SHANGHAI),
    )

    assert completed.index.max() == pd.Timestamp("2026-06-26")


def test_btc_current_utc_daily_bar_is_incomplete():
    asset = get_strategy("btc_supertrend_satellite").asset("BTC-USD")
    frame = _frame(pd.to_datetime(["2026-06-25", "2026-06-26"]))

    completed = filter_completed_rows(
        asset,
        frame,
        datetime(2026, 6, 26, 23, 59, tzinfo=UTC),
    )

    assert completed.index.max() == pd.Timestamp("2026-06-25")


def test_market_data_uses_latest_complete_common_etf_session():
    config = get_strategy("theme_alpha")
    sessions = xshg_sessions("2025-08-01", "2026-06-26")
    frames = _theme_frames(sessions)

    market = build_portfolio_market_data(
        config,
        frames,
        datetime(2026, 6, 26, 15, 10, tzinfo=SHANGHAI),
    )

    assert market.market_data_date.isoformat() == "2026-06-26"
    assert market.sessions[-1] == pd.Timestamp("2026-06-26")
    assert market.blocked is False
    assert list(market.close.columns) == list(config.symbols)


def test_missing_latest_close_blocks_instead_of_falling_back_silently():
    config = get_strategy("theme_alpha")
    sessions = xshg_sessions("2025-08-01", "2026-06-26")
    frames = _theme_frames(sessions)
    frames["159930.SZ"] = frames["159930.SZ"].iloc[:-1]

    market = build_portfolio_market_data(
        config,
        frames,
        datetime(2026, 6, 26, 15, 10, tzinfo=SHANGHAI),
    )

    assert market.blocked is True
    assert any(
        diagnostic.code == "BLOCKED_SESSION_MISMATCH"
        and diagnostic.symbol == "159930.SZ"
        for diagnostic in market.diagnostics
    )


def test_recent_unexplained_asset_gap_blocks_calculation():
    config = get_strategy("theme_alpha")
    sessions = xshg_sessions("2025-08-01", "2026-06-26")
    frames = _theme_frames(sessions)
    missing_session = sessions[-5]
    frames["512400.SS"] = frames["512400.SS"].drop(missing_session)

    market = build_portfolio_market_data(
        config,
        frames,
        datetime(2026, 6, 26, 15, 10, tzinfo=SHANGHAI),
    )

    assert any(
        diagnostic.code == "BLOCKED_MISSING_SESSION"
        and diagnostic.symbol == "512400.SS"
        for diagnostic in market.diagnostics
    )


def test_theme_alpha_requires_ma200_history():
    config = get_strategy("theme_alpha")
    sessions = xshg_sessions("2025-09-01", "2026-06-26")[-199:]
    frames = _theme_frames(sessions)

    market = build_portfolio_market_data(
        config,
        frames,
        datetime(2026, 6, 26, 15, 10, tzinfo=SHANGHAI),
    )

    assert any(
        diagnostic.code == "BLOCKED_INSUFFICIENT_HISTORY"
        for diagnostic in market.diagnostics
    )


def test_stale_latest_exchange_session_is_reported():
    config = get_strategy("theme_alpha")
    sessions = xshg_sessions("2025-08-01", "2026-06-25")
    frames = _theme_frames(sessions)

    market = build_portfolio_market_data(
        config,
        frames,
        datetime(2026, 6, 26, 15, 10, tzinfo=SHANGHAI),
    )

    assert any(
        diagnostic.code == "BLOCKED_STALE_DATA"
        for diagnostic in market.diagnostics
    )


def test_market_data_build_does_not_mutate_source_frames():
    config = get_strategy("theme_alpha")
    sessions = xshg_sessions("2025-08-01", "2026-06-26")
    frames = _theme_frames(sessions)
    original = frames["510300.SS"].copy(deep=True)

    build_portfolio_market_data(
        config,
        frames,
        datetime(2026, 6, 26, 15, 10, tzinfo=SHANGHAI),
    )

    pd.testing.assert_frame_equal(frames["510300.SS"], original)


def test_load_market_data_reports_missing_parquet(tmp_path):
    config = get_strategy("theme_alpha")

    market = load_strategy_market_data(
        config,
        Path(tmp_path),
        datetime(2026, 6, 26, 15, 10, tzinfo=SHANGHAI),
    )

    assert market.blocked is True
    assert {
        diagnostic.symbol
        for diagnostic in market.diagnostics
        if diagnostic.code == "BLOCKED_MISSING_DATA"
    } == set(config.symbols)


def test_refresh_uses_fixed_strategy_universe():
    config = get_strategy("btc_supertrend_satellite")
    calls = []

    result = refresh_strategy_universe(
        config,
        timeout_seconds=7.5,
        refresh_fn=lambda symbols, timeout_seconds, **kwargs: calls.append(
            (symbols, timeout_seconds, kwargs)
        )
        or True,
    )

    assert result.completed is True
    assert result.symbols == config.symbols
    assert calls == [
        (
            list(config.symbols),
            7.5,
            {"reason": "portfolio_strategy", "min_interval_seconds": 0},
        )
    ]

