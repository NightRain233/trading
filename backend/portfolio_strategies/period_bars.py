from __future__ import annotations

from typing import Literal

import pandas as pd


Timeframe = Literal["1W", "1M"]


def _rule(timeframe: Timeframe) -> str:
    if timeframe == "1W":
        return "W-FRI"
    if timeframe == "1M":
        return "ME"
    raise ValueError(f"Unsupported timeframe: {timeframe}")


def completed_bars(
    daily: pd.DataFrame,
    *,
    timeframe: Timeframe,
    known_at,
) -> pd.DataFrame:
    """Aggregate completed periods, then calculate indicators on period OHLC."""
    if daily is None or daily.empty or "Close" not in daily.columns:
        return pd.DataFrame()

    source = daily.sort_index().copy()
    source.index = pd.to_datetime(source.index)
    aggregation = {
        column: method
        for column, method in (
            ("Open", "first"),
            ("High", "max"),
            ("Low", "min"),
            ("Close", "last"),
            ("Volume", "sum"),
        )
        if column in source.columns
    }
    rule = _rule(timeframe)
    periods = source.resample(rule).agg(aggregation).dropna(subset=["Close"])
    source_sessions = pd.Series(source.index, index=source.index).resample(rule).max()
    periods["period_end"] = periods.index
    periods["available_at"] = periods.index
    periods["source_last_session"] = source_sessions.reindex(periods.index).values

    close = periods["Close"].astype(float)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    periods["MACD_DIF"] = ema12 - ema26
    periods["MACD_DEA"] = periods["MACD_DIF"].ewm(span=9, adjust=False).mean()
    for window in (5, 10, 20, 30, 50):
        periods[f"MA{window}"] = close.rolling(window).mean()
    periods["EMA20"] = close.ewm(span=20, adjust=False).mean()
    periods["EMA50"] = close.ewm(span=50, adjust=False).mean()
    boll_mid = close.rolling(20).mean()
    boll_std = close.rolling(20).std(ddof=0)
    periods["BOLL_Mid"] = boll_mid
    periods["BOLL_Upper"] = boll_mid + 2 * boll_std
    periods["BOLL_Lower"] = boll_mid - 2 * boll_std

    known_timestamp = pd.Timestamp(known_at)
    if known_timestamp.tzinfo is not None:
        known_timestamp = known_timestamp.tz_localize(None)
    return periods[periods["available_at"] < known_timestamp.normalize()].copy()
