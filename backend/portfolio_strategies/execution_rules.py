from __future__ import annotations

from typing import Literal
import math

import numpy as np
import pandas as pd


Side = Literal["BUY", "SELL"]


def _opening_checks(side: Side | None):
    checks = [("OpenTradable", True, "OPEN_NOT_TRADABLE"),
              ("OpenSuspended", False, "OPEN_SUSPENDED")]
    if side in (None, "BUY"):
        checks.append(("BuyOpenAllowed", True, "BUY_OPEN_BLOCKED"))
    if side in (None, "SELL"):
        checks.append(("SellOpenAllowed", True, "SELL_OPEN_BLOCKED"))
    return checks


def opening_allowed(frame: pd.DataFrame, *, side: Side | None = None) -> pd.Series:
    """Vectorized opening contract for long history and common-session queries."""
    if "Open" not in frame:
        return pd.Series(False, index=frame.index)
    prices = pd.to_numeric(frame["Open"], errors="coerce")
    allowed = prices.notna() & np.isfinite(prices) & prices.gt(0)
    for column, expected, _reason in _opening_checks(side):
        if column in frame:
            allowed &= frame[column].notna() & frame[column].eq(expected).fillna(False)
    return allowed


def opening_block_reason(row, *, side: Side | None = None) -> str | None:
    """Use only execution-session opening facts, never that day's H/L/C/Volume.

    Optional boolean columns must be supplied from an opening-time status feed.
    Missing columns preserve the legacy positive-Open assumption. A present but
    missing status is unknown and blocks execution. No price-limit percentages
    are guessed from the symbol or a full-day candle.
    """
    try:
        price = float(row.get("Open"))
    except (TypeError, ValueError):
        return "INVALID_OPEN"
    if not math.isfinite(price) or price <= 0:
        return "INVALID_OPEN"
    for column, expected, reason in _opening_checks(side):
        if column not in row:
            continue
        value = row[column]
        if pd.isna(value) or value not in (True, False, 0, 1):
            return "OPEN_STATUS_UNKNOWN"
        if bool(value) != expected:
            return reason
    return None


def market_fill_price(
    open_price: float,
    *,
    side: Side,
    slippage_bps: float,
) -> float:
    multiplier = 1.0 + slippage_bps / 10_000.0
    if side == "SELL":
        multiplier = 1.0 - slippage_bps / 10_000.0
    return float(open_price) * multiplier


def preexisting_long_stop_fill(
    *,
    open_price: float,
    stop_price: float,
    slippage_bps: float,
) -> float:
    return market_fill_price(
        min(float(open_price), float(stop_price)),
        side="SELL",
        slippage_bps=slippage_bps,
    )


def next_valid_open(
    frame: pd.DataFrame,
    *,
    after,
    side: Side | None = None,
) -> tuple[pd.Timestamp, float] | None:
    if frame is None or frame.empty or "Open" not in frame.columns:
        return None
    ordered = frame.sort_index()
    candidates = ordered.loc[ordered.index > pd.Timestamp(after)]
    candidates = candidates.loc[opening_allowed(candidates, side=side)]
    if candidates.empty:
        return None
    return pd.Timestamp(candidates.index[0]), float(candidates.iloc[0]["Open"])
