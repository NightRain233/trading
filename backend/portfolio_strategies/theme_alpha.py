from __future__ import annotations

from datetime import date
import math
from collections.abc import Mapping, Sequence

import pandas as pd

from .indicators import (
    InsufficientDataError,
    inverse_volatility_weights,
    select_low_vol_trend,
)
from .market_data import PortfolioMarketData
from .models import (
    CalculationState,
    StrategyCalculation,
    StrategyConfig,
    StrategyObservation,
    TargetWeight,
)
from .schedules import schedule_status


CORE_SYMBOLS = ("510300.SS", "513100.SS", "518880.SS")
DEFENDED_CORE_SYMBOLS = ("510300.SS", "513100.SS")
CASH_SYMBOL = "CASH"


def apply_core_defense(
    core_weights: Mapping[str, float],
    risk_on: Mapping[str, bool],
) -> dict[str, float]:
    defended = {
        symbol: float(core_weights.get(symbol, 0.0))
        for symbol in (*CORE_SYMBOLS, CASH_SYMBOL)
    }
    for symbol in DEFENDED_CORE_SYMBOLS:
        if not bool(risk_on.get(symbol, False)):
            defended[CASH_SYMBOL] += defended[symbol]
            defended[symbol] = 0.0
    return defended


def combine_sleeve_weights(
    core_weights: Mapping[str, float],
    lvt_weights: Mapping[str, float],
    *,
    symbols: Sequence[str],
    core_allocation: float,
    lvt_allocation: float,
) -> dict[str, float]:
    if not math.isclose(core_allocation + lvt_allocation, 1.0, abs_tol=1e-12):
        raise ValueError("Sleeve allocations must sum to one")
    ordered = list(dict.fromkeys(symbols))
    combined = {
        symbol: (
            core_allocation * float(core_weights.get(symbol, 0.0))
            + lvt_allocation * float(lvt_weights.get(symbol, 0.0))
        )
        for symbol in ordered
    }
    combined[CASH_SYMBOL] = (
        core_allocation * float(core_weights.get(CASH_SYMBOL, 0.0))
        + lvt_allocation * float(lvt_weights.get(CASH_SYMBOL, 0.0))
    )
    values = tuple(combined.values())
    if any(not math.isfinite(weight) or weight < 0.0 for weight in values):
        raise ValueError("Combined weights must be finite and nonnegative")
    if not math.isclose(sum(values), 1.0, abs_tol=1e-10):
        raise ValueError("Combined weights must sum to one")
    return combined


def _core_risk_state(
    close: pd.DataFrame,
    signal_timestamp: pd.Timestamp,
    window: int,
) -> dict[str, bool]:
    location = close.index.get_loc(signal_timestamp)
    if not isinstance(location, int):
        location = int(location)
    if location < window - 1:
        raise InsufficientDataError("Core defense has not completed warmup")
    return {
        symbol: bool(
            close.at[signal_timestamp, symbol]
            > close[symbol].iloc[location - window + 1 : location + 1].mean()
        )
        for symbol in DEFENDED_CORE_SYMBOLS
    }


def _lvt_weights(
    returns: pd.DataFrame,
    selected: Sequence[str],
    *,
    window: int,
    cap: float,
) -> dict[str, float]:
    if not selected:
        return {CASH_SYMBOL: 1.0}
    if cap * len(selected) >= 1.0 - 1e-12:
        allocated = inverse_volatility_weights(
            returns,
            selected,
            window=window,
            cap=cap,
        )
    else:
        raw = inverse_volatility_weights(returns, selected, window=window)
        allocated = {
            symbol: min(weight, cap)
            for symbol, weight in raw.items()
        }
    allocated[CASH_SYMBOL] = max(0.0, 1.0 - sum(allocated.values()))
    return allocated


def _sleeve_items(
    weights: Mapping[str, float],
    symbols: Sequence[str],
    *,
    sleeve: str,
    selected: Sequence[str] = (),
    risk_on: Mapping[str, bool] | None = None,
) -> tuple[TargetWeight, ...]:
    selected_set = set(selected)
    risk_on = risk_on or {}
    items = []
    for symbol in (*symbols, CASH_SYMBOL):
        if sleeve == "core":
            if symbol in DEFENDED_CORE_SYMBOLS and not risk_on.get(symbol, False):
                reason = "Core defense moved this allocation to cash"
            elif symbol == CASH_SYMBOL:
                reason = "Cash created by independent core defense"
            else:
                reason = "Inverse-volatility core allocation"
        elif symbol == CASH_SYMBOL:
            reason = "Unallocated LVT sleeve held as cash"
        elif symbol in selected_set:
            reason = "Selected by MA, momentum, and low-volatility ranking"
        else:
            reason = "Not selected for the LVT sleeve"
        items.append(
            TargetWeight(symbol, float(weights.get(symbol, 0.0)), sleeve, reason)
        )
    return tuple(items)


def calculate_theme_alpha(
    config: StrategyConfig,
    market_data: PortfolioMarketData,
    as_of_date: date,
) -> StrategyCalculation:
    if config.strategy_id != "theme_alpha":
        raise ValueError(f"Not Theme Alpha: {config.strategy_id}")
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
    close = market_data.close.loc[:latest_date, list(config.symbols)]
    returns = close.pct_change(fill_method=None)

    core = inverse_volatility_weights(
        returns.loc[:signal_timestamp],
        CORE_SYMBOLS,
        window=int(config.params["risk_parity_window"]),
    )
    core_with_cash = {**core, CASH_SYMBOL: 0.0}
    core_risk_on = _core_risk_state(
        close,
        signal_timestamp,
        int(config.params["defense_ma_window"]),
    )
    defended_core = apply_core_defense(core_with_cash, core_risk_on)

    lvt_symbols = tuple(
        asset.symbol
        for asset in config.assets
        if asset.sleeve in {"lvt", "core_lvt"}
    )
    selected_lvt = select_low_vol_trend(
        close,
        returns,
        signal_timestamp,
        lvt_symbols,
        ma_window=int(config.params["ma_window"]),
        momentum_window=int(config.params["momentum_window"]),
        volatility_window=int(config.params["volatility_window"]),
        top_n=int(config.params["top_n"]),
    )
    selected_weights = _lvt_weights(
        returns.loc[:signal_timestamp],
        selected_lvt,
        window=int(config.params["risk_parity_window"]),
        cap=float(config.params["single_asset_cap"]),
    )
    lvt = {
        symbol: float(selected_weights.get(symbol, 0.0))
        for symbol in lvt_symbols
    }
    lvt[CASH_SYMBOL] = float(selected_weights[CASH_SYMBOL])

    target = combine_sleeve_weights(
        defended_core,
        lvt,
        symbols=config.symbols,
        core_allocation=float(config.params["core_allocation"]),
        lvt_allocation=float(config.params["lvt_allocation"]),
    )
    core_items = _sleeve_items(
        defended_core,
        CORE_SYMBOLS,
        sleeve="core",
        risk_on=core_risk_on,
    )
    lvt_items = _sleeve_items(
        lvt,
        lvt_symbols,
        sleeve="lvt",
        selected=selected_lvt,
    )
    target_items = tuple(
        TargetWeight(
            symbol,
            float(weight),
            "cash" if symbol == CASH_SYMBOL else config.asset(symbol).sleeve,
            "Combined Core80 and LVT20 target",
        )
        for symbol, weight in target.items()
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
            "selected_lvt": tuple(selected_lvt),
            "core_risk_on": core_risk_on,
        },
    )
    return StrategyCalculation(
        strategy_id=config.strategy_id,
        strategy_version=config.version,
        state=state,
        market_data_date=latest_date.date(),
        signal_date=status.last_signal_date,
        observation=observation,
        target_weights=target_items,
        sleeve_weights={"core": core_items, "lvt": lvt_items},
        diagnostics=market_data.diagnostics,
    )
