from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from .event_ledger import payload_hash
from .frozen_xquant import FrozenUniverse, frozen_universe, normalize_daily
from .indicators import inverse_volatility_weights, supertrend
from .models import StrategyConfig


CORE_SYMBOLS = ("510300.SS", "513100.SS", "518880.SS")
CASH_SYMBOL = "CASH"


@dataclass(frozen=True)
class FrozenDecision:
    run_type: str
    market_data_date: date
    signal_date: date
    universe_version: str | None
    config_hash: str
    input_hash: str
    data_quality_status: str
    payload: Mapping[str, Any]
    items: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class CoreOpenRebalance:
    open_weights: Mapping[str, float]
    turnover: float
    gross_nav: float
    cost: float
    target_quantities: Mapping[str, float]


def calculate_core_open_rebalance(
    quantities: Mapping[str, float],
    cash: float,
    opens: Mapping[str, float],
    target_weights: Mapping[str, float],
    *,
    cost_bps: float,
) -> CoreOpenRebalance:
    target_total = sum(float(target_weights[symbol]) for symbol in CORE_SYMBOLS)
    if target_total <= 0:
        raise ValueError("Core target weights must be positive")
    target = {
        symbol: float(target_weights[symbol]) / target_total for symbol in CORE_SYMBOLS
    }
    values = {
        symbol: float(quantities.get(symbol, 0.0)) * float(opens[symbol])
        for symbol in CORE_SYMBOLS
    }
    gross_nav = sum(values.values()) + float(cash)
    if gross_nav <= 0:
        raise ValueError("Core gross NAV must be positive")
    open_weights = {symbol: value / gross_nav for symbol, value in values.items()}
    open_weights[CASH_SYMBOL] = float(cash) / gross_nav
    turnover = 0.5 * sum(
        abs(
            ({**target, CASH_SYMBOL: 0.0}).get(symbol, 0.0)
            - open_weights.get(symbol, 0.0)
        )
        for symbol in (*CORE_SYMBOLS, CASH_SYMBOL)
    )
    cost = gross_nav * turnover * float(cost_bps) / 10_000.0
    net_nav = gross_nav - cost
    return CoreOpenRebalance(
        open_weights=open_weights,
        turnover=turnover,
        gross_nav=gross_nav,
        cost=cost,
        target_quantities={
            symbol: net_nav * target[symbol] / float(opens[symbol])
            for symbol in CORE_SYMBOLS
        },
    )


def strategy_config_hash(config: StrategyConfig) -> str:
    return payload_hash({
        "strategyId": config.strategy_id,
        "strategyVersion": config.version,
        "execution": config.execution,
        "params": dict(config.params),
        "costs": {
            "baseBps": config.costs.base_bps,
            "slippageBps": config.costs.slippage_bps,
            "assetExtraBps": dict(config.costs.asset_extra_bps),
        },
    })


def valid_open(value: object) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0.0


def core_common_sessions(
    prices: Mapping[str, pd.DataFrame],
    *,
    require_valid_open: bool = False,
) -> pd.DatetimeIndex:
    frames = {symbol: normalize_daily(prices[symbol]) for symbol in CORE_SYMBOLS}
    common = pd.DatetimeIndex(sorted(set.intersection(*(
        set(frame.index) for frame in frames.values()
    ))))
    valid = pd.Series(True, index=common)
    for symbol, frame in frames.items():
        close = pd.to_numeric(frame.reindex(common)["Close"], errors="coerce")
        valid &= close.notna() & np.isfinite(close) & close.gt(0)
        if require_valid_open:
            open_ = pd.to_numeric(frame.reindex(common)["Open"], errors="coerce")
            valid &= open_.notna() & np.isfinite(open_) & open_.gt(0)
    return common[valid.to_numpy()]


def next_valid_open_date(
    frame: pd.DataFrame,
    after: date | pd.Timestamp,
) -> date | None:
    normalized = normalize_daily(frame)
    later = normalized.index[normalized.index > pd.Timestamp(after).normalize()]
    if later.empty or "Open" not in normalized:
        return None
    opens = pd.to_numeric(normalized.loc[later, "Open"], errors="coerce")
    valid = opens.notna() & np.isfinite(opens) & opens.gt(0)
    return opens.index[valid][0].date() if valid.any() else None


def next_core_valid_open_date(
    prices: Mapping[str, pd.DataFrame],
    after: date | pd.Timestamp,
) -> date | None:
    sessions = core_common_sessions(prices, require_valid_open=True)
    later = sessions[sessions > pd.Timestamp(after).normalize()]
    return later[0].date() if not later.empty else None


def core_signal_due(
    prices: Mapping[str, pd.DataFrame],
    signal_date: date,
    *,
    anchor_signal_date: date,
    every: int = 10,
) -> bool:
    if every <= 0:
        raise ValueError("every must be positive")
    sessions = core_common_sessions(prices)
    signal = pd.Timestamp(signal_date).normalize()
    anchor = pd.Timestamp(anchor_signal_date).normalize()
    if signal not in sessions or anchor not in sessions:
        return False
    signal_position = int(sessions.get_loc(signal))
    anchor_position = int(sessions.get_loc(anchor))
    return (signal_position - anchor_position) % every == 0


def calculate_risk_parity_decision(
    config: StrategyConfig,
    prices: Mapping[str, pd.DataFrame],
    *,
    signal_date: date,
) -> FrozenDecision:
    signal = pd.Timestamp(signal_date).normalize()
    sessions = core_common_sessions(prices)
    if signal not in sessions:
        raise ValueError("RiskParity signal date is not a common core session")
    close = pd.DataFrame({
        symbol: normalize_daily(prices[symbol]).reindex(sessions)["Close"]
        for symbol in CORE_SYMBOLS
    })
    returns = close.pct_change(fill_method=None)
    location = int(sessions.get_loc(signal))
    window = int(config.params["risk_parity_window"])
    history = returns.iloc[location - window + 1:location + 1]
    target = inverse_volatility_weights(
        history,
        CORE_SYMBOLS,
        window=window,
    )
    core_scale = float(config.params.get("core_allocation", 1.0))
    target = {symbol: weight * core_scale for symbol, weight in target.items()}
    payload = {
        "window": window,
        "commonSessions": [value.date().isoformat() for value in history.index],
        "closes": {
            symbol: [float(value) for value in close.loc[history.index, symbol]]
            for symbol in CORE_SYMBOLS
        },
        "targetWeights": target,
        "coreScale": core_scale,
    }
    items = tuple({
        "symbol": symbol,
        "event_type": "CORE_REBALANCE",
        "market": "a_share",
        "sleeve": "core",
        "eligible": True,
        "target_weight": float(weight),
        "priority": 0.0,
        "reason": "20-session inverse-volatility target",
        "payload": {"targetWeight": float(weight)},
    } for symbol, weight in target.items())
    return FrozenDecision(
        run_type="CORE_REBALANCE",
        market_data_date=signal.date(),
        signal_date=signal.date(),
        universe_version=None,
        config_hash=strategy_config_hash(config),
        input_hash=payload_hash(payload),
        data_quality_status="OK",
        payload=payload,
        items=items,
    )


def _decision_field(item: Mapping[str, Any], key: str) -> Any:
    decision = item.get("decision")
    if isinstance(decision, Mapping) and key in decision:
        return decision.get(key)
    return item.get(key)


def _has_data_gap(item: Mapping[str, Any]) -> bool:
    if bool(item.get("dataGap")):
        return True
    integrity = item.get("dataIntegrity")
    return bool(isinstance(integrity, Mapping) and (
        integrity.get("hasGap") or integrity.get("hasRecentGap")
    ))


def policy_eligible_bull_flip(item: Mapping[str, Any]) -> bool:
    return bool(
        item.get("state") == "bull_flip"
        and _decision_field(item, "setup") == "breakout"
        and not bool(item.get("dataStale"))
        and not _has_data_gap(item)
    )


def market_ma_state(
    frame: pd.DataFrame,
    signal_date: date | pd.Timestamp,
    *,
    window: int = 200,
) -> dict[str, Any]:
    normalized = normalize_daily(frame)
    signal = pd.Timestamp(signal_date).normalize()
    available = normalized.index[normalized.index <= signal]
    if available.empty:
        return {
            "referenceDate": None,
            "referenceClose": None,
            "referenceMa": None,
            "riskOn": False,
            "gateReason": "insufficient_reference_history",
        }
    reference_date = available[-1]
    close = pd.to_numeric(normalized["Close"], errors="coerce")
    ma = close.rolling(window, min_periods=window).mean()
    reference_close = close.at[reference_date]
    reference_ma = ma.at[reference_date]
    has_history = bool(
        pd.notna(reference_close)
        and pd.notna(reference_ma)
        and np.isfinite(reference_close)
        and np.isfinite(reference_ma)
    )
    risk_on = bool(has_history and reference_close > reference_ma)
    return {
        "referenceDate": reference_date.date().isoformat(),
        "referenceClose": float(reference_close) if pd.notna(reference_close) else None,
        "referenceMa": float(reference_ma) if pd.notna(reference_ma) else None,
        "riskOn": risk_on,
        "gateReason": (
            "market_above_ma" if risk_on
            else "insufficient_reference_history" if not has_history
            else "market_at_or_below_ma"
        ),
    }


def calculate_bull_decision(
    config: StrategyConfig,
    decision_items: Sequence[Mapping[str, Any]],
    prices: Mapping[str, pd.DataFrame],
    selected_membership: Mapping[str, Mapping[str, Any]],
    *,
    signal_date: date,
    held_symbols: Sequence[str] = (),
    pending_exit_symbols: Sequence[str] = (),
    universe: FrozenUniverse | None = None,
    run_type: str = "BULL_DAILY",
) -> FrozenDecision:
    universe = universe or frozen_universe()
    held = set(held_symbols)
    pending_exits = set(pending_exit_symbols)
    by_symbol = {str(item["symbol"]): item for item in decision_items}
    output: list[dict[str, Any]] = []
    ma_filter = bool(config.params["ma200_entry_filter"])
    ma_window = int(config.params["ma_window"])

    for symbol, membership in selected_membership.items():
        item = by_symbol.get(symbol)
        if (
            item is None
            or str(item.get("decisionAsOf") or "") != signal_date.isoformat()
            or not policy_eligible_bull_flip(item)
        ):
            continue
        market = universe.market_by_symbol[symbol]
        reference_symbol = universe.reference_symbol_by_market.get(market)
        ma = {
            "referenceDate": None,
            "referenceClose": None,
            "referenceMa": None,
            "riskOn": True,
            "gateReason": "ma_filter_disabled",
        }
        if ma_filter:
            reference = prices.get(str(reference_symbol))
            ma = (
                market_ma_state(reference, signal_date, window=ma_window)
                if reference is not None
                else {
                    "referenceDate": None,
                    "referenceClose": None,
                    "referenceMa": None,
                    "riskOn": False,
                    "gateReason": "missing_reference_data",
                }
            )
        eligible = bool(ma["riskOn"] and symbol not in held)
        reason = (
            "policy eligible bull flip and market above MA200"
            if eligible and ma_filter
            else "policy eligible bull flip"
            if eligible
            else "already held"
            if symbol in held
            else str(ma["gateReason"])
        )
        try:
            score = float(_decision_field(item, "readinessScore") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        if not math.isfinite(score):
            score = 0.0
        output.append({
            "symbol": symbol,
            "event_type": "BULL_FLIP_ENTRY",
            "market": market,
            "sleeve": "satellite",
            "eligible": eligible,
            "target_weight": float(config.params["max_satellite_position_weight"]),
            "priority": score,
            "reason": reason,
            "payload": {
                "state": item.get("state"),
                "setup": _decision_field(item, "setup"),
                "permission": _decision_field(item, "permission"),
                "readinessScore": score,
                "universeEffectiveDate": membership.get("effectiveDate"),
                "universeLiquidityRank": membership.get("liquidityRank"),
                "referenceSymbol": reference_symbol,
                "maWindow": ma_window if ma_filter else None,
                **ma,
            },
        })

    # Existing positions exit on the first complete ST 7/3 bearish state.  The
    # MA gate is intentionally not consulted for exits.
    for symbol in sorted(held):
        if symbol in pending_exits:
            continue
        frame = prices.get(symbol)
        if frame is None:
            continue
        normalized = normalize_daily(frame)
        timestamp = pd.Timestamp(signal_date).normalize()
        if timestamp not in normalized.index:
            continue
        trend = supertrend(
            normalized["High"],
            normalized["Low"],
            normalized["Close"],
            atr_window=int(config.params["supertrend_atr_window"]),
            multiplier=float(config.params["supertrend_multiplier"]),
        )
        if bool(trend.at[timestamp, "direction"]):
            continue
        output.append({
            "symbol": symbol,
            "event_type": "ST_BEAR_EXIT",
            "market": universe.market_by_symbol[symbol],
            "sleeve": "satellite",
            "eligible": True,
            "target_weight": 0.0,
            "priority": 1_000_000_000.0,
            "reason": "first complete ST 7/3 bearish close while held",
            "payload": {
                "supertrendDirection": -1,
                "maGateApplied": False,
            },
        })

    output.sort(key=lambda row: (-float(row["priority"]), row["symbol"]))
    payload = {
        "signalDate": signal_date.isoformat(),
        "policyVersion": config.params["policy_version"],
        "universeVersion": config.params["universe_version"],
        "ma200EntryFilter": ma_filter,
        "decisionInputs": [{
            "symbol": item.get("symbol"),
            "decisionAsOf": item.get("decisionAsOf"),
            "state": item.get("state"),
            "setup": _decision_field(item, "setup"),
            "permission": _decision_field(item, "permission"),
            "dataStale": bool(item.get("dataStale")),
            "dataGap": _has_data_gap(item),
        } for item in sorted(decision_items, key=lambda value: str(value.get("symbol")))],
        "items": output,
    }
    return FrozenDecision(
        run_type=run_type,
        market_data_date=signal_date,
        signal_date=signal_date,
        universe_version=str(config.params["universe_version"]),
        config_hash=strategy_config_hash(config),
        input_hash=payload_hash(payload),
        data_quality_status="OK",
        payload=payload,
        items=tuple(output),
    )


def bearish_signal_dates(
    frame: pd.DataFrame,
    *,
    after_date: date,
    through_date: date,
    atr_window: int,
    multiplier: float,
) -> tuple[date, ...]:
    """Return completed bearish ST dates strictly after a symbol cursor."""
    normalized = normalize_daily(frame)
    window = normalized.loc[
        (normalized.index > pd.Timestamp(after_date))
        & (normalized.index <= pd.Timestamp(through_date))
    ]
    if window.empty:
        return ()
    trend = supertrend(
        normalized["High"],
        normalized["Low"],
        normalized["Close"],
        atr_window=atr_window,
        multiplier=multiplier,
    )
    return tuple(
        timestamp.date()
        for timestamp in window.index
        if not bool(trend.at[timestamp, "direction"])
    )
