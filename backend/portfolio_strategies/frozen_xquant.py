from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd


FIXTURE_PATH = Path(__file__).with_name("fixtures") / "xquant_frozen_v1.json"


def load_frozen_spec() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class FrozenUniverse:
    universe_id: str
    universe_version: str
    source_hash: str
    market_by_symbol: Mapping[str, str]
    reference_symbol_by_market: Mapping[str, str]
    min_history_sessions: int
    liquidity_lookback_sessions: int
    max_suspension_rate: float
    min_data_completeness: float
    liquidity_floors: Mapping[str, float]
    market_caps: Mapping[str, int]
    turnover_multipliers: Mapping[str, float]
    excluded_symbols: frozenset[str]

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(self.market_by_symbol)


def frozen_universe() -> FrozenUniverse:
    spec = load_frozen_spec()
    rules = spec["universeRules"]
    return FrozenUniverse(
        universe_id=spec["universeId"],
        universe_version=spec["universeVersion"],
        source_hash=spec["sourceHashes"][
            "outputs/scan-v2-all-bull-flip-long-sample/universe_membership_history.csv"
        ],
        market_by_symbol=dict(spec["marketBySymbol"]),
        reference_symbol_by_market=dict(spec["referenceSymbolByMarket"]),
        min_history_sessions=int(rules["minHistorySessions"]),
        liquidity_lookback_sessions=int(rules["liquidityLookbackSessions"]),
        max_suspension_rate=float(rules["maxSuspensionRate"]),
        min_data_completeness=float(rules["minDataCompleteness"]),
        liquidity_floors={k: float(v) for k, v in rules["liquidityFloors"].items()},
        market_caps={k: int(v) for k, v in rules["marketCaps"].items()},
        turnover_multipliers={
            k: float(v) for k, v in rules["turnoverMultipliers"].items()
        },
        excluded_symbols=frozenset(rules["excludedSymbols"]),
    )


def frozen_membership_snapshot(effective_date: date) -> dict[str, Any] | None:
    snapshot = load_frozen_spec().get("frozenMembershipSnapshots", {}).get(
        effective_date.isoformat()
    )
    return dict(snapshot) if snapshot is not None else None


def normalize_daily(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.sort_index().copy()
    index = pd.DatetimeIndex(result.index)
    if index.tz is not None:
        index = index.tz_localize(None)
    result.index = index.normalize()
    return result[~result.index.duplicated(keep="last")]


def _complete_session_mask(frame: pd.DataFrame) -> pd.Series:
    required = ["Open", "High", "Low", "Close", "Volume"]
    numeric = frame.reindex(columns=required).apply(pd.to_numeric, errors="coerce")
    finite = pd.DataFrame(
        np.isfinite(numeric.to_numpy()),
        index=numeric.index,
        columns=numeric.columns,
    )
    return finite.all(axis=1) & numeric[["Open", "High", "Low", "Close"]].gt(0).all(axis=1)


def _official_trading_status_mask(frame: pd.DataFrame) -> pd.Series | None:
    candidates = (
        "isTrading", "is_trading", "isTradable", "is_tradable",
        "tradable", "tradeable", "tradeStatus", "trade_status",
    )
    column = next((name for name in candidates if name in frame.columns), None)
    if column is None:
        return None
    status = frame[column]
    if pd.api.types.is_bool_dtype(status):
        return status.fillna(False).astype(bool)
    if pd.api.types.is_numeric_dtype(status):
        return pd.to_numeric(status, errors="coerce").fillna(0).gt(0)
    normalized = status.astype("string").str.strip().str.lower()
    return normalized.isin({
        "1", "true", "trading", "trade", "normal", "active",
        "交易", "正常", "正常交易",
    }).fillna(False)


def _tradable_session_mask(frame: pd.DataFrame) -> pd.Series:
    complete = _complete_session_mask(frame)
    volume = (
        pd.to_numeric(frame["Volume"], errors="coerce")
        if "Volume" in frame
        else pd.Series(np.nan, index=frame.index, dtype=float)
    )
    result = complete & volume.gt(0)
    official = _official_trading_status_mask(frame)
    return result & official if official is not None else result


def symbol_calendars(
    prices: Mapping[str, pd.DataFrame],
    universe: FrozenUniverse,
) -> dict[str, pd.DatetimeIndex]:
    references = {
        market: normalize_daily(prices[symbol]).index
        for market, symbol in universe.reference_symbol_by_market.items()
        if symbol in prices
    }
    result: dict[str, pd.DatetimeIndex] = {}
    for symbol, raw in prices.items():
        market = universe.market_by_symbol[symbol]
        if symbol.endswith((".SS", ".SZ")):
            calendar = references.get("a_share")
        elif symbol.endswith(".HK"):
            calendar = references.get("hong_kong")
        elif market == "crypto":
            calendar = references.get("crypto")
        elif symbol == "GC=F":
            calendar = normalize_daily(raw).index
        else:
            calendar = references.get("us")
        result[symbol] = pd.DatetimeIndex(
            calendar if calendar is not None else normalize_daily(raw).index
        )
    return result


def next_non_crypto_effective_date(
    prices: Mapping[str, pd.DataFrame],
    universe: FrozenUniverse,
    snapshot_date: date | pd.Timestamp,
) -> date:
    dates: set[pd.Timestamp] = set()
    snapshot = pd.Timestamp(snapshot_date).normalize()
    for symbol, raw in prices.items():
        if universe.market_by_symbol[symbol] == "crypto":
            continue
        dates.update(normalize_daily(raw).index[normalize_daily(raw).index > snapshot])
    if not dates:
        raise ValueError(f"No non-crypto session after {snapshot.date()}")
    return min(dates).date()


def evaluate_universe_snapshot(
    prices: Mapping[str, pd.DataFrame],
    *,
    snapshot_date: date | pd.Timestamp,
    effective_date: date | pd.Timestamp,
    universe: FrozenUniverse | None = None,
) -> pd.DataFrame:
    """Port of the frozen xquant monthly PIT selection contract."""
    universe = universe or frozen_universe()
    snapshot = pd.Timestamp(snapshot_date).normalize()
    effective = pd.Timestamp(effective_date).normalize()
    calendars = symbol_calendars(prices, universe)
    rows: list[dict[str, Any]] = []

    for symbol in universe.symbols:
        raw = prices.get(symbol)
        if raw is None:
            rows.append({
                "snapshotDate": snapshot,
                "effectiveDate": effective,
                "symbol": symbol,
                "market": universe.market_by_symbol[symbol],
                "historySessions": 0,
                "expectedLookbackSessions": 0,
                "completeLookbackSessions": 0,
                "observedLookbackSessions": 0,
                "medianTradedValue": np.nan,
                "liquidityFloor": universe.liquidity_floors.get(
                    universe.market_by_symbol[symbol], np.inf
                ),
                "suspensionRate": 1.0,
                "dataCompleteness": 0.0,
                "qualified": False,
                "failureReasons": "missing_source_data",
            })
            continue
        market = universe.market_by_symbol[symbol]
        history = normalize_daily(raw).loc[:snapshot]
        valid_history = history.loc[_tradable_session_mask(history)]
        calendar = calendars[symbol]
        calendar = calendar[calendar <= snapshot]
        trailing_calendar = calendar[-universe.liquidity_lookback_sessions:]
        trailing = history.reindex(trailing_calendar)
        expected_sessions = len(trailing_calendar)
        complete_sessions = int(_complete_session_mask(trailing).sum())
        observed_sessions = int(_tradable_session_mask(trailing).sum())
        suspension_rate = (
            1.0 - observed_sessions / expected_sessions
            if expected_sessions else 1.0
        )
        completeness = (
            complete_sessions / expected_sessions if expected_sessions else 0.0
        )
        turnover = (
            pd.to_numeric(trailing.get("Close"), errors="coerce")
            * pd.to_numeric(trailing.get("Volume"), errors="coerce")
            * universe.turnover_multipliers.get(symbol, 1.0)
        ).where(_tradable_session_mask(trailing))
        median_turnover = float(turnover.median()) if turnover.notna().any() else np.nan
        floor = float(universe.liquidity_floors.get(market, np.inf))
        reasons: list[str] = []
        if symbol in universe.excluded_symbols:
            reasons.append("excluded_non_tradable")
        if len(valid_history) < universe.min_history_sessions:
            reasons.append("insufficient_history")
        if expected_sessions < universe.liquidity_lookback_sessions:
            reasons.append("insufficient_calendar_history")
        if not np.isfinite(median_turnover) or median_turnover < floor:
            reasons.append("below_liquidity_floor")
        if suspension_rate > universe.max_suspension_rate:
            reasons.append("excess_suspension_rate")
        if completeness < universe.min_data_completeness:
            reasons.append("incomplete_data")
        rows.append({
            "snapshotDate": snapshot,
            "effectiveDate": effective,
            "symbol": symbol,
            "market": market,
            "historySessions": len(valid_history),
            "expectedLookbackSessions": expected_sessions,
            "completeLookbackSessions": complete_sessions,
            "observedLookbackSessions": observed_sessions,
            "medianTradedValue": median_turnover,
            "liquidityFloor": floor,
            "suspensionRate": suspension_rate,
            "dataCompleteness": completeness,
            "qualified": not reasons,
            "failureReasons": "|".join(reasons),
        })

    result = pd.DataFrame(rows)
    result["liquidityRank"] = np.nan
    result["selected"] = False
    for market, group in result[result["qualified"]].groupby("market"):
        ranked = group.sort_values(
            ["medianTradedValue", "symbol"], ascending=[False, True]
        )
        result.loc[ranked.index, "liquidityRank"] = np.arange(1, len(ranked) + 1)
        cap = int(universe.market_caps.get(market, 0))
        result.loc[ranked.index[:cap], "selected"] = True
    return result.sort_values(
        ["market", "liquidityRank", "symbol"], na_position="last"
    ).reset_index(drop=True)
