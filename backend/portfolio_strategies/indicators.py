from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd


class InsufficientDataError(ValueError):
    """Raised when an indicator cannot be calculated without inventing data."""


def true_range(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
) -> pd.Series:
    previous_close = close.shift(1)
    ranges = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def supertrend(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    *,
    atr_window: int = 10,
    multiplier: float = 3.0,
) -> pd.DataFrame:
    """Calculate the xquant-validated SMA-ATR SuperTrend state machine."""
    atr = true_range(high, low, close).rolling(atr_window).mean()
    midpoint = (high + low) / 2.0
    basic_upper = midpoint + multiplier * atr
    basic_lower = midpoint - multiplier * atr
    final_upper = pd.Series(index=close.index, dtype=float)
    final_lower = pd.Series(index=close.index, dtype=float)
    line = pd.Series(index=close.index, dtype=float)
    direction = pd.Series(False, index=close.index, dtype=bool)

    for position in range(len(close)):
        if pd.isna(atr.iloc[position]):
            continue
        if position == 0 or pd.isna(final_upper.iloc[position - 1]):
            final_upper.iloc[position] = basic_upper.iloc[position]
            final_lower.iloc[position] = basic_lower.iloc[position]
            line.iloc[position] = final_upper.iloc[position]
            continue

        previous_close = close.iloc[position - 1]
        previous_upper = final_upper.iloc[position - 1]
        previous_lower = final_lower.iloc[position - 1]
        final_upper.iloc[position] = (
            basic_upper.iloc[position]
            if basic_upper.iloc[position] < previous_upper
            or previous_close > previous_upper
            else previous_upper
        )
        final_lower.iloc[position] = (
            basic_lower.iloc[position]
            if basic_lower.iloc[position] > previous_lower
            or previous_close < previous_lower
            else previous_lower
        )

        if line.iloc[position - 1] == previous_upper:
            line.iloc[position] = (
                final_lower.iloc[position]
                if close.iloc[position] > final_upper.iloc[position]
                else final_upper.iloc[position]
            )
        else:
            line.iloc[position] = (
                final_upper.iloc[position]
                if close.iloc[position] < final_lower.iloc[position]
                else final_lower.iloc[position]
            )
        direction.iloc[position] = close.iloc[position] > line.iloc[position]

    return pd.DataFrame(
        {
            "line": line,
            "direction": direction.fillna(False),
            "upper": final_upper,
            "lower": final_lower,
        },
        index=close.index,
    )


def inverse_volatility_weights(
    returns: pd.DataFrame,
    symbols: Sequence[str],
    *,
    window: int,
    cap: float | None = None,
) -> dict[str, float]:
    ordered_symbols = list(dict.fromkeys(symbols))
    if not ordered_symbols:
        raise InsufficientDataError("No eligible symbols")
    if len(returns) < window:
        raise InsufficientDataError(
            f"Need {window} return rows, received {len(returns)}"
        )
    missing = [symbol for symbol in ordered_symbols if symbol not in returns]
    if missing:
        raise InsufficientDataError(f"Missing return columns: {missing}")

    history = returns[ordered_symbols].iloc[-window:]
    if history.isna().any().any():
        raise InsufficientDataError("Return history contains missing values")
    volatility = history.std(ddof=1)
    valid = np.isfinite(volatility) & (volatility > 0)
    if not bool(valid.all()):
        raise InsufficientDataError("Return history contains invalid volatility")

    inverse = 1.0 / volatility
    weights = inverse / inverse.sum()
    if cap is None:
        return {symbol: float(weights[symbol]) for symbol in ordered_symbols}

    if cap <= 0 or cap * len(ordered_symbols) < 1.0 - 1e-12:
        raise ValueError("Cap cannot support a fully invested allocation")

    capped = weights.astype(float).copy()
    for _ in range(len(capped) + 1):
        over = capped > cap + 1e-12
        if not bool(over.any()):
            break
        excess = float((capped[over] - cap).sum())
        capped.loc[over] = cap
        under = capped < cap - 1e-12
        if excess <= 1e-12 or not bool(under.any()):
            break
        base = capped[under].clip(lower=0.0)
        capacity = (cap - capped[under]).clip(lower=0.0)
        proportions = (
            base / base.sum()
            if float(base.sum()) > 1e-12
            else capacity / capacity.sum()
        )
        addition = np.minimum(excess * proportions, capacity)
        capped.loc[addition.index] += addition

    total = float(capped.sum())
    if abs(total - 1.0) > 1e-10:
        raise InsufficientDataError("Unable to redistribute capped weights")
    return {symbol: float(capped[symbol]) for symbol in ordered_symbols}


def select_low_vol_trend(
    close: pd.DataFrame,
    returns: pd.DataFrame,
    date: pd.Timestamp,
    universe: Sequence[str],
    *,
    ma_window: int = 60,
    momentum_window: int = 63,
    volatility_window: int = 60,
    top_n: int = 3,
) -> list[str]:
    try:
        location = close.index.get_loc(date)
    except KeyError as exc:
        raise InsufficientDataError(f"Unknown signal date: {date}") from exc
    if not isinstance(location, (int, np.integer)):
        raise InsufficientDataError("Signal date is not unique")

    warmup = max(ma_window, momentum_window, volatility_window)
    if location < warmup:
        return []

    required_prices = max(ma_window, momentum_window + 1)
    valid: list[str] = []
    for symbol in universe:
        if symbol not in close or symbol not in returns:
            continue
        price_history = close[symbol].iloc[
            location - required_prices + 1 : location + 1
        ]
        return_history = returns[symbol].iloc[
            location - volatility_window + 1 : location + 1
        ]
        if (
            len(price_history) == required_prices
            and len(return_history) == volatility_window
            and price_history.notna().all()
            and return_history.notna().all()
        ):
            valid.append(symbol)
    if not valid:
        return []

    price = close.iloc[location][valid]
    moving_average = close.iloc[
        location - ma_window + 1 : location + 1
    ][valid].mean()
    momentum = price / close.iloc[location - momentum_window][valid] - 1.0
    volatility = returns.iloc[
        location - volatility_window + 1 : location + 1
    ][valid].std(ddof=1)
    eligible = [
        symbol
        for symbol in valid
        if price[symbol] > moving_average[symbol]
        and momentum[symbol] > 0
        and np.isfinite(volatility[symbol])
    ]
    ranked = sorted(eligible, key=lambda symbol: (volatility[symbol], symbol))
    return ranked[:top_n]
