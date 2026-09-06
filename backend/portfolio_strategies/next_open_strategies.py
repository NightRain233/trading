from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import math
import os
from pathlib import Path
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from .event_ledger import payload_hash
from .execution_rules import next_valid_open, opening_allowed, Side
from .frozen_xquant import FrozenUniverse, frozen_universe, normalize_daily
from .indicators import inverse_volatility_weights, supertrend
from .market_freshness import assess_freshness
from .models import StrategyConfig
from .signal_contracts import signal_contract_hash


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
    signal_contract_version: str | None = None
    signal_code_commit_sha: str | None = None
    signal_code_hash: str | None = None
    price_snapshot_hash: str | None = None


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
            valid &= opening_allowed(frame.reindex(common))
    return common[valid.to_numpy()]


def next_valid_open_date(
    frame: pd.DataFrame,
    after: date | pd.Timestamp,
    *,
    side: Side | None = None,
) -> date | None:
    normalized = normalize_daily(frame)
    result = next_valid_open(normalized, after=pd.Timestamp(after).normalize(), side=side)
    return result[0].date() if result else None


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


def _signal_code_hash() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _signal_code_commit_sha() -> str:
    return os.getenv("TRADING_BUILD_SHA", "unavailable")


def _clean_number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _price_snapshot_hash(
    symbol_frame: pd.DataFrame,
    reference_frame: pd.DataFrame | None,
    signal_date: date,
) -> str:
    signal = pd.Timestamp(signal_date).normalize()
    symbol_data = normalize_daily(symbol_frame).loc[:signal].tail(2)
    reference_data = (
        normalize_daily(reference_frame).loc[:signal].tail(200)
        if reference_frame is not None else pd.DataFrame()
    )

    def rows(frame: pd.DataFrame, columns: Sequence[str]) -> list[dict[str, Any]]:
        return [{
            "date": timestamp.date().isoformat(),
            **{column: _clean_number(row.get(column)) for column in columns},
        } for timestamp, row in frame.iterrows()]

    return payload_hash({
        "symbol": rows(symbol_data, ("Open", "High", "Low", "Close", "Volume")),
        "reference": rows(reference_data, ("Close",)),
    })


def _supertrend_direction_on(
    frame: pd.DataFrame,
    signal_date: date,
    *,
    atr_window: int,
    multiplier: float,
) -> tuple[bool | None, bool | None]:
    normalized = normalize_daily(frame)
    timestamp = pd.Timestamp(signal_date).normalize()
    if timestamp not in normalized.index:
        return None, None
    required = normalized.loc[:timestamp, ["High", "Low", "Close"]].apply(
        pd.to_numeric, errors="coerce",
    )
    if len(required) < 2 or required.iloc[-2:].isna().any().any():
        return None, None
    trend = supertrend(
        required["High"], required["Low"], required["Close"],
        atr_window=atr_window, multiplier=multiplier,
    )
    location = int(required.index.get_loc(timestamp))
    if location < 1:
        return None, None
    return bool(trend.iloc[location - 1]["direction"]), bool(
        trend.iloc[location]["direction"]
    )


def market_ma_state(
    frame: pd.DataFrame,
    signal_date: date | pd.Timestamp,
    *,
    window: int = 200,
    reference_symbol: str = "SPY",
    known_at: datetime | pd.Timestamp | str | None = None,
) -> dict[str, Any]:
    normalized = normalize_daily(frame)
    signal = pd.Timestamp(signal_date).normalize()
    freshness = assess_freshness(
        reference_symbol,
        normalized,
        known_at=known_at if known_at is not None else signal + pd.Timedelta(days=1),
    )
    available = normalized.index[normalized.index <= signal]
    if available.empty:
        return {
            "referenceDate": None,
            "expectedReferenceDate": freshness["expectedLastCompletedSession"],
            "missingExpectedSessions": freshness["missingExpectedSessions"],
            "freshnessStatus": freshness["freshnessStatus"],
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
    freshness_ok = freshness["freshnessStatus"] in {"OK", "EXPECTED_CLOSED"}
    risk_on = bool(has_history and reference_close > reference_ma and freshness_ok)
    return {
        "referenceDate": reference_date.date().isoformat(),
        "expectedReferenceDate": freshness["expectedLastCompletedSession"],
        "missingExpectedSessions": freshness["missingExpectedSessions"],
        "freshnessStatus": freshness["freshnessStatus"],
        "referenceClose": float(reference_close) if pd.notna(reference_close) else None,
        "referenceMa": float(reference_ma) if pd.notna(reference_ma) else None,
        "riskOn": risk_on,
        "gateReason": (
            "market_above_ma" if risk_on
            else "ma200_data_blocked" if not freshness_ok
            else "insufficient_reference_history" if not has_history
            else "market_at_or_below_ma"
        ),
    }


def calculate_bull_decision(
    config: StrategyConfig,
    prices: Mapping[str, pd.DataFrame],
    selected_membership: Mapping[str, Mapping[str, Any]],
    *,
    symbol: str,
    signal_date: date,
    held_symbols: Sequence[str] = (),
    pending_exit_symbols: Sequence[str] = (),
    universe: FrozenUniverse | None = None,
    run_type: str = "BULL_DAILY",
) -> FrozenDecision:
    universe = universe or frozen_universe()
    held = set(held_symbols)
    pending_exits = set(pending_exit_symbols)
    output: list[dict[str, Any]] = []
    ma_filter = bool(config.params["ma200_entry_filter"])
    ma_window = int(config.params["ma_window"])
    frame = prices.get(symbol)
    if frame is None or universe.market_by_symbol.get(symbol) is None:
        raise ValueError(f"Missing frozen contract data for {symbol}")
    market = universe.market_by_symbol[symbol]
    asset = config.asset(symbol)
    currency_aggregable = bool(
        asset.quote_currency == config.base_currency
        and asset.investable_instrument is not None
    )
    reference_symbol = universe.reference_symbol_by_market.get(market)
    reference = prices.get(str(reference_symbol))
    previous_direction, current_direction = _supertrend_direction_on(
        frame, signal_date,
        atr_window=int(config.params["supertrend_atr_window"]),
        multiplier=float(config.params["supertrend_multiplier"]),
    )
    data_quality_status = (
        "OK" if previous_direction is not None and current_direction is not None
        else "INVALID_SYMBOL_BAR"
    )
    membership = selected_membership.get(symbol)
    ma = {
        "referenceDate": None,
        "referenceClose": None,
        "referenceMa": None,
        "riskOn": True,
        "gateReason": "ma_filter_disabled",
    }
    if ma_filter:
        ma = (
            market_ma_state(
                reference,
                signal_date,
                window=ma_window,
                reference_symbol=str(reference_symbol),
            )
            if reference is not None
            else {
                "referenceDate": None,
                "expectedReferenceDate": None,
                "missingExpectedSessions": [],
                "freshnessStatus": "SOURCE_STALE",
                "referenceClose": None,
                "referenceMa": None,
                "riskOn": False,
                "gateReason": "missing_reference_data",
            }
        )
    if symbol in held and symbol not in pending_exits and current_direction is False:
        output.append({
            "symbol": symbol,
            "event_type": "ST_BEAR_EXIT",
            "market": market,
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
    elif previous_direction is False and current_direction is True:
        if (
            data_quality_status == "OK"
            and ma_filter
            and ma.get("freshnessStatus") not in {"OK", "EXPECTED_CLOSED"}
        ):
            data_quality_status = "MA200_DATA_BLOCKED"
        elif data_quality_status == "OK" and not currency_aggregable:
            data_quality_status = "FX_DATA_BLOCKED"
        liquidity_rank = _clean_number(
            membership.get("liquidityRank") if membership else None
        )
        eligible = bool(
            membership is not None
            and ma["riskOn"]
            and currency_aggregable
            and symbol not in held
            and data_quality_status == "OK"
        )
        reason = (
            "frozen bull flip and market above MA200" if eligible and ma_filter
            else "frozen bull flip" if eligible
            else "already held" if symbol in held
            else "pit_universe_blocked" if membership is None
            else str(ma["gateReason"]) if data_quality_status == "MA200_DATA_BLOCKED"
            else "fx_data_required" if data_quality_status == "FX_DATA_BLOCKED"
            else str(ma["gateReason"])
        )
        output.append({
            "symbol": symbol,
            "event_type": "BULL_FLIP_ENTRY",
            "market": market,
            "sleeve": "satellite",
            "eligible": eligible,
            "target_weight": float(config.params["max_satellite_position_weight"]),
            "priority": 1_000_000.0 - liquidity_rank if liquidity_rank is not None else 0.0,
            "reason": reason,
            "payload": {
                "supertrendPreviousDirection": -1,
                "supertrendDirection": 1,
                "universeEffectiveDate": membership.get("effectiveDate") if membership else None,
                "universeLiquidityRank": liquidity_rank,
                "referenceSymbol": reference_symbol,
                "quoteCurrency": asset.quote_currency,
                "baseCurrency": config.base_currency,
                "fxPair": asset.fx_pair,
                "syntheticProxy": asset.synthetic_proxy,
                "investableInstrument": asset.investable_instrument,
                "maWindow": ma_window if ma_filter else None,
                **ma,
            },
        })

    output.sort(key=lambda row: (-float(row["priority"]), row["symbol"]))
    price_snapshot_hash = _price_snapshot_hash(frame, reference, signal_date)
    payload = {
        "signalDate": signal_date.isoformat(),
        "signalContractVersion": config.params["signal_contract_version"],
        "signalContractHash": signal_contract_hash(
            str(config.params["signal_contract_version"]),
        ),
        "signalCodeCommitSha": _signal_code_commit_sha(),
        "signalCodeHash": _signal_code_hash(),
        "priceSnapshotHash": price_snapshot_hash,
        "universeVersion": config.params["universe_version"],
        "universeScope": universe.universe_scope,
        "ma200EntryFilter": ma_filter,
        "symbol": symbol,
        "supertrendPreviousDirection": previous_direction,
        "supertrendDirection": current_direction,
        "universeSelected": membership is not None,
        "marketGate": ma,
        "items": output,
    }
    return FrozenDecision(
        run_type=run_type,
        market_data_date=signal_date,
        signal_date=signal_date,
        universe_version=str(config.params["universe_version"]),
        config_hash=strategy_config_hash(config),
        input_hash=payload_hash(payload),
        data_quality_status=data_quality_status,
        payload=payload,
        items=tuple(output),
        signal_contract_version=str(config.params["signal_contract_version"]),
        signal_code_commit_sha=str(payload["signalCodeCommitSha"]),
        signal_code_hash=str(payload["signalCodeHash"]),
        price_snapshot_hash=price_snapshot_hash,
    )
