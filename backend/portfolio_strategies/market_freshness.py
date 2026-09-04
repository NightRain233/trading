from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any

import exchange_calendars as xcals
import pandas as pd


def venue_for_symbol(symbol: str) -> str | None:
    normalized = str(symbol or "").upper()
    if normalized.endswith((".SS", ".SZ")):
        return "XSHG"
    if normalized.endswith(".HK") or normalized == "^HSI":
        return "XHKG"
    if normalized.endswith("-USD"):
        return "24/7"
    if normalized.endswith("=F"):
        return "CMES"
    if normalized:
        return "XNYS"
    return None


@lru_cache(maxsize=None)
def _calendar(venue: str):
    return xcals.get_calendar(venue)


def _utc_timestamp(value) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _completed_sessions(venue: str, known_at) -> pd.DatetimeIndex:
    calendar = _calendar(venue)
    reference = _utc_timestamp(known_at)
    local_date = reference.tz_convert(calendar.tz).date()
    sessions = calendar.sessions_in_range(
        pd.Timestamp(local_date - timedelta(days=45)), pd.Timestamp(local_date),
    )
    return pd.DatetimeIndex([
        pd.Timestamp(session).tz_localize(None).normalize()
        for session in sessions
        if calendar.session_close(session) <= reference
    ])


def _base_result(symbol: str, venue: str | None, freshness_state: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "venue": venue,
        "expectedLastCompletedSession": None,
        "actualLastCompletedSession": None,
        "missingExpectedSessions": [],
        "closedByCalendarSessions": [],
        "freshnessStatus": freshness_state,
    }


def assess_freshness(
    symbol: str,
    frame: pd.DataFrame | None,
    *,
    known_at: datetime | pd.Timestamp | str,
    source_error: str | None = None,
    lifecycle_status: str | None = None,
) -> dict[str, Any]:
    venue = venue_for_symbol(symbol)
    if venue is None:
        return _base_result(symbol, None, "CALENDAR_UNKNOWN")
    if lifecycle_status in {"DELISTED", "LIQUIDATED", "MERGED"}:
        return _base_result(symbol, venue, "DELISTED")
    if source_error is not None:
        return {
            **_base_result(symbol, venue, "SOURCE_STALE"),
            "sourceError": source_error,
        }
    try:
        expected = _completed_sessions(venue, known_at)
    except Exception:
        return _base_result(symbol, venue, "CALENDAR_UNKNOWN")
    expected_last = expected[-1] if not expected.empty else None

    source = frame.copy() if frame is not None else pd.DataFrame()
    if not source.empty:
        index = pd.DatetimeIndex(source.index)
        if index.tz is not None:
            index = index.tz_localize(None)
        source.index = index.normalize()
        source = source[~source.index.duplicated(keep="last")].sort_index()
    required = [column for column in ("Open", "High", "Low", "Close") if column in source]
    valid = source.dropna(subset=required) if required else pd.DataFrame(index=source.index)
    actual_dates = (
        valid.index[valid.index <= expected_last]
        if expected_last is not None else valid.index
    )
    actual_last = actual_dates[-1] if not actual_dates.empty else None
    observed_start = source.index.min() if not source.empty else None
    missing = [
        session for session in expected[-20:]
        if session not in actual_dates
        and (observed_start is None or session >= observed_start)
    ]

    freshness_state = "OK"
    if expected_last is None:
        freshness_state = "EXPECTED_CLOSED"
    elif expected_last in source.index and "Volume" in source:
        volume = pd.to_numeric(source.loc[[expected_last], "Volume"], errors="coerce")
        if not volume.empty and float(volume.iloc[-1]) == 0.0:
            freshness_state = "SUSPENDED"
            missing = [session for session in missing if session != expected_last]
    if freshness_state == "OK" and expected_last not in actual_dates:
        provisional = source.index[source.index > expected_last]
        freshness_state = (
            "PROVISIONAL_ONLY" if not provisional.empty else "EXPECTED_OPEN_MISSING"
        )
    elif freshness_state == "OK" and missing:
        freshness_state = "DATA_GAP"

    reference = _utc_timestamp(known_at)
    local_end = pd.Timestamp(reference.tz_convert(_calendar(venue).tz).date())
    start_date = actual_last + pd.Timedelta(days=1) if actual_last is not None else local_end
    expected_set = set(expected)
    closed_dates = [
        day.date().isoformat()
        for day in pd.date_range(start_date, local_end, freq="D")
        if day not in expected_set
    ]
    return {
        "symbol": symbol,
        "venue": venue,
        "expectedLastCompletedSession": (
            expected_last.date().isoformat() if expected_last is not None else None
        ),
        "actualLastCompletedSession": (
            actual_last.date().isoformat() if actual_last is not None else None
        ),
        "missingExpectedSessions": [value.date().isoformat() for value in missing],
        "closedByCalendarSessions": closed_dates,
        "freshnessStatus": freshness_state,
    }
