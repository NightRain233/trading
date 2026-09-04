from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

from portfolio_strategies.market_freshness import assess_freshness
from portfolio_strategies.next_open_strategies import market_ma_state


SHANGHAI = ZoneInfo("Asia/Shanghai")
UTC = ZoneInfo("UTC")


def _frame(sessions: pd.DatetimeIndex, *, volume: float = 1_000_000.0) -> pd.DataFrame:
    values = pd.Series(range(len(sessions)), index=sessions, dtype=float) + 100.0
    return pd.DataFrame(
        {
            "Open": values, "High": values + 1, "Low": values - 1,
            "Close": values, "Volume": volume,
        },
        index=sessions,
    )


def test_cross_market_holiday_freshness_uses_each_symbols_own_calendar():
    xshg = xcals.get_calendar("XSHG").sessions_in_range("2026-09-01", "2026-09-30")
    cmes = xcals.get_calendar("CMES").sessions_in_range("2026-09-01", "2026-10-02")
    known_at = datetime(2026, 10, 5, 12, 0, tzinfo=SHANGHAI)

    etf = assess_freshness("518880.SS", _frame(xshg), known_at=known_at)
    future = assess_freshness("GC=F", _frame(cmes), known_at=known_at)

    assert etf["freshnessStatus"] == "OK"
    assert etf["expectedLastCompletedSession"] == "2026-09-30"
    assert "2026-10-01" in etf["closedByCalendarSessions"]
    assert future["freshnessStatus"] == "OK"
    assert future["expectedLastCompletedSession"] == "2026-10-02"


def test_stale_ma200_reference_blocks_new_entry():
    calendar = xcals.get_calendar("XNYS")
    sessions = calendar.sessions_in_range("2025-10-01", "2026-08-10")
    frame = _frame(sessions[:-1])

    result = market_ma_state(
        frame,
        pd.Timestamp("2026-08-10"),
        reference_symbol="SPY",
        known_at=datetime(2026, 8, 10, 23, 0, tzinfo=UTC),
        window=200,
    )

    assert result["expectedReferenceDate"] == "2026-08-10"
    assert result["referenceDate"] == "2026-08-07"
    assert result["freshnessStatus"] == "EXPECTED_OPEN_MISSING"
    assert result["missingExpectedSessions"] == ["2026-08-10"]
    assert result["riskOn"] is False
    assert result["gateReason"] == "ma200_data_blocked"


def test_suspended_session_has_distinct_freshness_reason():
    sessions = xcals.get_calendar("XSHG").sessions_in_range(
        "2026-08-07", "2026-08-10",
    )
    frame = _frame(sessions)
    frame.loc[sessions[-1], "Volume"] = 0.0

    result = assess_freshness(
        "510300.SS", frame,
        known_at=datetime(2026, 8, 10, 16, 0, tzinfo=SHANGHAI),
    )

    assert result["freshnessStatus"] == "SUSPENDED"
    assert result["missingExpectedSessions"] == []
