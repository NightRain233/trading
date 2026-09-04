from __future__ import annotations

from typing import Literal

import pandas as pd


Side = Literal["BUY", "SELL"]


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
) -> tuple[pd.Timestamp, float] | None:
    if frame is None or frame.empty or "Open" not in frame.columns:
        return None
    ordered = frame.sort_index()
    candidates = pd.to_numeric(
        ordered.loc[ordered.index > pd.Timestamp(after), "Open"], errors="coerce",
    ).dropna()
    candidates = candidates[candidates > 0]
    if candidates.empty:
        return None
    return pd.Timestamp(candidates.index[0]), float(candidates.iloc[0])
