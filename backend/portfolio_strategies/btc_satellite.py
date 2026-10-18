from __future__ import annotations

from datetime import date
import math
from collections.abc import Mapping

import pandas as pd

from .indicators import InsufficientDataError, inverse_volatility_weights, supertrend
from .market_data import PortfolioMarketData
from .models import (
    CalculationState,
    StrategyCalculation,
    StrategyConfig,
    StrategyObservation,
    TargetWeight,
)
from .schedules import schedule_status, signal_dates


CORE_SYMBOLS = ("510300.SS", "513100.SS", "518880.SS")
BTC_SYMBOL = "BTC-USD"
CASH_SYMBOL = "CASH"


def build_btc_target_weights(
    core_weights: Mapping[str, float],
    *,
    cap: float,
    btc_on: bool,
) -> dict[str, float]:
    if not 0.0 <= cap <= 1.0:
        raise ValueError("BTC cap must be between zero and one")
    values = {symbol: float(core_weights.get(symbol, 0.0)) for symbol in CORE_SYMBOLS}
    if any(not math.isfinite(weight) or weight < 0.0 for weight in values.values()):
        raise ValueError("Core weights must be finite and nonnegative")
    total = sum(values.values())
    if total <= 0.0:
        raise InsufficientDataError("Core weights must contain positive exposure")

    core_scale = 1.0 - cap
    target = {
        symbol: values[symbol] / total * core_scale
        for symbol in CORE_SYMBOLS
    }
    target[BTC_SYMBOL] = cap if btc_on else 0.0
    target[CASH_SYMBOL] = 0.0 if btc_on else cap
    return target


def _target_items(target: Mapping[str, float], btc_on: bool) -> tuple[TargetWeight, ...]:
    items = []
    for symbol in (*CORE_SYMBOLS, BTC_SYMBOL, CASH_SYMBOL):
        if symbol in CORE_SYMBOLS:
            sleeve = "core"
            reason = "Inverse-volatility core allocation"
        elif symbol == BTC_SYMBOL:
            sleeve = "satellite"
            reason = (
                "BTC SuperTrend is on"
                if btc_on
                else "BTC SuperTrend is off; satellite held as cash"
            )
        else:
            sleeve = "cash"
            reason = (
                "No satellite cash while BTC SuperTrend is on"
                if btc_on
                else "BTC satellite allocation held as cash"
            )
        items.append(TargetWeight(symbol, float(target[symbol]), sleeve, reason))
    return tuple(items)


def calculate_btc_satellite(
    config: StrategyConfig,
    market_data: PortfolioMarketData,
    as_of_date: date,
) -> StrategyCalculation:
    if not config.strategy_id.startswith("btc_supertrend_satellite"):
        raise ValueError(f"Not a BTC satellite strategy: {config.strategy_id}")
    if market_data.blocked:
        raise InsufficientDataError("Blocked market data cannot produce a target")

    as_of = pd.Timestamp(as_of_date)
    sessions = pd.DatetimeIndex(market_data.sessions)
    sessions = sessions[sessions <= as_of]
    if sessions.empty:
        raise InsufficientDataError("No completed session is available as of date")

    status = schedule_status(config, as_of_date, sessions)
    if status.missing_signal_session:
        raise InsufficientDataError("A required formal signal session is missing")
    if status.last_signal_date is None:
        raise InsufficientDataError("No formal signal date is available")

    latest_date = sessions[-1]
    signal_timestamp = pd.Timestamp(status.last_signal_date)
    close = market_data.close.loc[:latest_date]
    high = market_data.high.loc[:latest_date]
    low = market_data.low.loc[:latest_date]
    required = (*CORE_SYMBOLS, BTC_SYMBOL)
    missing = [symbol for symbol in required if symbol not in close]
    if missing:
        raise InsufficientDataError(f"Missing strategy columns: {missing}")

    trend = supertrend(
        high[BTC_SYMBOL],
        low[BTC_SYMBOL],
        close[BTC_SYMBOL],
        atr_window=int(config.params["supertrend_atr_window"]),
        multiplier=float(config.params["supertrend_multiplier"]),
    )
    latest_line = float(trend.at[latest_date, "line"])
    formal_line = float(trend.at[signal_timestamp, "line"])
    if not math.isfinite(latest_line) or not math.isfinite(formal_line):
        raise InsufficientDataError("BTC SuperTrend has not completed warmup")
    latest_on = bool(trend.at[latest_date, "direction"])
    formal_on = bool(trend.at[signal_timestamp, "direction"])

    returns = close[list(CORE_SYMBOLS)].pct_change(fill_method=None)
    core_weights = inverse_volatility_weights(
        returns.loc[:signal_timestamp],
        CORE_SYMBOLS,
        window=int(config.params["risk_parity_window"]),
    )
    target = build_btc_target_weights(
        core_weights,
        cap=float(config.params["btc_cap"]),
        btc_on=formal_on,
    )

    state = CalculationState.READY if status.due else CalculationState.NOT_DUE
    observation = StrategyObservation(
        as_of_date=latest_date.date(),
        state=state.value,
        reason=(
            "Formal strategy check is due"
            if status.due
            else "Latest observation; target remains from last formal check"
        ),
        values={
            "btc_close": float(close.at[latest_date, BTC_SYMBOL]),
            "supertrend_line": latest_line,
            "supertrend_on": latest_on,
            "formal_btc_close": float(close.at[signal_timestamp, BTC_SYMBOL]),
            "formal_supertrend_line": formal_line,
            "formal_supertrend_on": formal_on,
        },
    )
    return StrategyCalculation(
        strategy_id=config.strategy_id,
        strategy_version=config.version,
        state=state,
        market_data_date=latest_date.date(),
        signal_date=status.last_signal_date,
        observation=observation,
        target_weights=_target_items(target, formal_on),
        diagnostics=market_data.diagnostics,
    )


def btc_trend_history(
    config: StrategyConfig,
    market_data: PortfolioMarketData,
    *,
    sessions: int = 250,
) -> list[dict]:
    """Recent BTC closes with the strategy's own SuperTrend line and switch.

    ``formalOn`` is the switch decided at the latest formal check on or before
    each day, i.e. what the satellite was told to hold; ``check`` marks the
    check days themselves.
    """
    if BTC_SYMBOL not in market_data.close or market_data.close.empty:
        return []
    close = market_data.close[BTC_SYMBOL]
    trend = supertrend(
        market_data.high[BTC_SYMBOL],
        market_data.low[BTC_SYMBOL],
        close,
        atr_window=int(config.params["supertrend_atr_window"]),
        multiplier=float(config.params["supertrend_multiplier"]),
    )
    index = pd.DatetimeIndex(close.index)
    checks = signal_dates(config, index[0].date(), index[-1].date())
    points: list[dict] = []
    formal_on: bool | None = None
    for position, day in enumerate(index):
        line = float(trend["line"].iloc[position])
        value = float(close.iloc[position])
        if not math.isfinite(line) or not math.isfinite(value):
            continue
        on = bool(trend["direction"].iloc[position])
        is_check = day.normalize() in checks
        if is_check:
            formal_on = on
        points.append({
            "date": day.date().isoformat(),
            "close": value,
            "line": line,
            "on": on,
            "check": is_check,
            "formalOn": formal_on,
        })
    return points[-sessions:]
