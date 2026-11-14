"""The single SuperTrend calculation contract used by trading and research.

The project uses a simple, causal SuperTrend with a simple moving average ATR.
Keeping the implementation here avoids depending on a library's default ATR
mode (which is often Wilder/RMA) changing the frozen strategy semantics.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


_SPEC = json.loads(Path(__file__).with_name("supertrend_contract.json").read_text())
CONTRACT_VERSION = str(_SPEC["version"])
DEFAULT_LENGTH = int(_SPEC["primary"]["length"])
DEFAULT_MULTIPLIER = float(_SPEC["primary"]["multiplier"])


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    previous_close = close.shift(1)
    return pd.concat(
        [high - low, (high - previous_close).abs(), (low - previous_close).abs()],
        axis=1,
    ).max(axis=1)


def calculate_supertrend(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    *,
    length: int = DEFAULT_LENGTH,
    multiplier: float = DEFAULT_MULTIPLIER,
    **_: Any,
) -> pd.DataFrame:
    """Return pandas-ta-compatible SuperTrend columns using SMA ATR.

    The first ``length - 1`` rows are unavailable. Signals are causal: the
    current line only uses the current and preceding OHLC values.
    """
    if length < 1:
        raise ValueError("SuperTrend length must be positive")
    if multiplier <= 0:
        raise ValueError("SuperTrend multiplier must be positive")
    if not (len(high) == len(low) == len(close)):
        raise ValueError("SuperTrend inputs must have equal length")

    atr = true_range(high, low, close).rolling(length, min_periods=length).mean()
    midpoint = (high + low) / 2.0
    basic_upper = midpoint + multiplier * atr
    basic_lower = midpoint - multiplier * atr

    size = len(close)
    final_upper = np.full(size, np.nan)
    final_lower = np.full(size, np.nan)
    line = np.full(size, np.nan)
    direction = np.full(size, np.nan)
    atr_values = atr.to_numpy(dtype=float)
    closes = close.to_numpy(dtype=float)
    upper = basic_upper.to_numpy(dtype=float)
    lower = basic_lower.to_numpy(dtype=float)

    for position in range(size):
        if np.isnan(atr_values[position]):
            continue
        if position == 0 or np.isnan(final_upper[position - 1]):
            final_upper[position] = upper[position]
            final_lower[position] = lower[position]
            line[position] = final_upper[position]
        else:
            previous_close = closes[position - 1]
            previous_upper = final_upper[position - 1]
            previous_lower = final_lower[position - 1]
            final_upper[position] = (
                upper[position]
                if upper[position] < previous_upper or previous_close > previous_upper
                else previous_upper
            )
            final_lower[position] = (
                lower[position]
                if lower[position] > previous_lower or previous_close < previous_lower
                else previous_lower
            )
            if line[position - 1] == previous_upper:
                line[position] = (
                    final_lower[position]
                    if closes[position] > final_upper[position]
                    else final_upper[position]
                )
            else:
                line[position] = (
                    final_upper[position]
                    if closes[position] < final_lower[position]
                    else final_lower[position]
                )
        direction[position] = 1.0 if closes[position] > line[position] else -1.0

    suffix = f"{length}_{multiplier:g}"
    result = pd.DataFrame(
        {
            f"SUPERT_{suffix}": line,
            f"SUPERTd_{suffix}": direction,
            f"SUPERTl_{suffix}": np.where(direction == 1, line, np.nan),
            f"SUPERTs_{suffix}": np.where(direction == -1, line, np.nan),
            f"SUPERTu_{suffix}": final_upper,
            f"SUPERTlwr_{suffix}": final_lower,
        },
        index=close.index,
    )
    return result
