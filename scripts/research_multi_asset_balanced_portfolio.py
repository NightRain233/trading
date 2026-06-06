#!/usr/bin/env python3
"""Research a CNY-denominated multi-asset balanced portfolio."""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import math
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
DEFAULT_CONFIG = BACKEND_DIR / "universes" / "multi_asset_balanced.json"
DEFAULT_DATA_DIR = BACKEND_DIR / "data"


def load_config(path: Path) -> Dict[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def expand_assets(config: Dict[str, object], universe_dir: Path) -> List[Dict[str, object]]:
    assets = [dict(row) for row in config.get("assets", [])]
    seen = {str(row.get("symbol", "")).upper() for row in assets}
    filename = config.get("aShareUniverseFile")
    if not filename:
        return assets

    path = Path(universe_dir) / str(filename)
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("symbols", payload) if isinstance(payload, dict) else payload
    required_bucket = str(config.get("aShareBucket", "broad"))
    for row in rows:
        if not isinstance(row, dict) or str(row.get("bucket")) != required_bucket:
            continue
        symbol = str(row.get("symbol", "")).strip().upper()
        if not symbol or symbol in seen:
            continue
        assets.append(
            {
                "symbol": symbol,
                "name": str(row.get("name") or symbol),
                "assetClass": "a_share_equity",
                "currency": "CNY",
                "maxWeight": 0.25,
            }
        )
        seen.add(symbol)
    return assets


def _normalize_index(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result.index = pd.DatetimeIndex(pd.to_datetime(result.index))
    if result.index.tz is not None:
        result.index = result.index.tz_localize(None)
    return result.sort_index().loc[lambda value: ~value.index.duplicated(keep="last")]


def load_frame(symbol: str, data_dir: Path = DEFAULT_DATA_DIR) -> Optional[pd.DataFrame]:
    path = Path(data_dir) / f"{symbol.upper()}.parquet"
    if not path.exists():
        return None
    frame = _normalize_index(pd.read_parquet(path))
    if frame.empty or not {"Open", "Close"}.issubset(frame.columns):
        return None
    columns = [column for column in ("Open", "High", "Low", "Close", "Volume") if column in frame.columns]
    return frame[columns].copy()


def load_all_frames(
    assets: Iterable[Dict[str, object]],
    fx_symbol: str,
    data_dir: Path = DEFAULT_DATA_DIR,
) -> Tuple[Dict[str, pd.DataFrame], List[str], Optional[pd.DataFrame]]:
    frames: Dict[str, pd.DataFrame] = {}
    missing: List[str] = []
    for asset in assets:
        symbol = str(asset["symbol"]).upper()
        frame = load_frame(symbol, data_dir)
        if frame is None:
            missing.append(symbol)
        else:
            frames[symbol] = frame
    fx_frame = load_frame(fx_symbol, data_dir)
    if fx_frame is None:
        missing.append(fx_symbol.upper())
    return frames, missing, fx_frame


def normalize_ohlc_to_cny(
    frame: pd.DataFrame,
    currency: str,
    fx_frame: Optional[pd.DataFrame],
) -> pd.DataFrame:
    asset = _normalize_index(frame)
    if str(currency).upper() == "CNY":
        return asset
    if str(currency).upper() != "USD":
        raise ValueError(f"Unsupported asset currency: {currency}")
    if fx_frame is None or fx_frame.empty:
        return asset.assign(**{column: float("nan") for column in asset.columns if column != "Volume"})

    fx = _normalize_index(fx_frame).reindex(asset.index).ffill()
    result = asset.copy()
    for column in ("Open", "High", "Low", "Close"):
        if column not in result.columns:
            continue
        fx_column = column if column in fx.columns else "Close"
        result[column] = result[column].astype(float) * fx[fx_column].astype(float)
    return result


def build_constant_fx_counterfactual_frames(
    raw_frames: Dict[str, pd.DataFrame],
    cny_frames: Dict[str, pd.DataFrame],
    asset_metadata: Dict[str, Dict[str, object]],
) -> Dict[str, pd.DataFrame]:
    return {
        symbol: (
            raw_frames[symbol].copy()
            if str(asset_metadata.get(symbol, {}).get("currency", "CNY")).upper() == "USD"
            and symbol in raw_frames
            else frame.copy()
        )
        for symbol, frame in cny_frames.items()
    }


def coverage_audit(frames: Dict[str, pd.DataFrame]) -> Dict[str, object]:
    by_symbol: Dict[str, Dict[str, object]] = {}
    starts = []
    ends = []
    for symbol, frame in frames.items():
        valid = frame.dropna(subset=["Close"])
        if valid.empty:
            by_symbol[symbol] = {"rows": 0, "startDate": None, "endDate": None}
            continue
        start = pd.Timestamp(valid.index.min())
        end = pd.Timestamp(valid.index.max())
        starts.append(start)
        ends.append(end)
        by_symbol[symbol] = {
            "rows": int(len(valid)),
            "startDate": start.date().isoformat(),
            "endDate": end.date().isoformat(),
        }
    return {
        "bySymbol": by_symbol,
        "commonStartDate": max(starts).date().isoformat() if starts else None,
        "commonEndDate": min(ends).date().isoformat() if ends else None,
    }


def completed_monthly_close(
    frame: pd.DataFrame,
    as_of=None,
) -> pd.Series:
    if frame is None or frame.empty or "Close" not in frame.columns:
        return pd.Series(dtype="float64")
    cutoff = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp(frame.index.max())
    daily = _normalize_index(frame)
    daily = daily[daily.index <= cutoff].dropna(subset=["Close"])
    if daily.empty:
        return pd.Series(dtype="float64")
    monthly = daily["Close"].resample("ME").last().dropna().astype(float)
    return monthly[monthly.index.normalize() <= cutoff.normalize()]


def evaluate_monthly_trend(
    monthly_close: pd.Series,
    mode: str,
) -> pd.Series:
    close = monthly_close.dropna().astype(float).sort_index()
    ma10 = close > close.rolling(10, min_periods=10).mean()
    mom12 = close.pct_change(12, fill_method=None) > 0
    if mode == "ma10":
        return ma10
    if mode == "mom12":
        return mom12
    if mode == "ma10_and_mom12":
        return ma10 & mom12
    raise ValueError(f"Unknown trend mode: {mode}")


def build_monthly_trend_signals(
    frame: pd.DataFrame,
    mode: str,
    as_of=None,
) -> pd.Series:
    monthly = completed_monthly_close(frame, as_of=as_of)
    return evaluate_monthly_trend(monthly, mode).dropna()


def latest_completed_signal(
    signals: pd.Series,
    signal_month,
) -> Optional[bool]:
    if signals is None or signals.empty:
        return None
    cutoff = pd.Timestamp(signal_month)
    window = signals[signals.index <= cutoff]
    return bool(window.iloc[-1]) if not window.empty else None


def annualized_volatility(
    close: pd.Series,
    as_of,
    lookback: int,
) -> Optional[float]:
    values = close.loc[: pd.Timestamp(as_of)].dropna().astype(float).tail(lookback + 1)
    if len(values) < lookback + 1:
        return None
    volatility = values.pct_change(fill_method=None).dropna().std(ddof=1) * math.sqrt(252)
    if pd.isna(volatility) or float(volatility) <= 0:
        return None
    return float(volatility)


def inverse_volatility_weights(
    vol_by_symbol: Dict[str, float],
) -> Dict[str, float]:
    inverse = {
        symbol: 1.0 / float(volatility)
        for symbol, volatility in vol_by_symbol.items()
        if volatility is not None and float(volatility) > 0
    }
    total = sum(inverse.values())
    return {symbol: value / total for symbol, value in inverse.items()} if total else {}


def _category_total(
    weights: Dict[str, float],
    asset_metadata: Dict[str, Dict[str, object]],
    asset_class: str,
) -> float:
    return sum(
        weight
        for symbol, weight in weights.items()
        if str(asset_metadata.get(symbol, {}).get("assetClass")) == asset_class
    )


def apply_weight_caps(
    raw_weights: Dict[str, float],
    asset_metadata: Dict[str, Dict[str, object]],
    category_caps: Dict[str, float],
) -> Dict[str, float]:
    positive = {symbol: max(0.0, float(value)) for symbol, value in raw_weights.items() if float(value) > 0}
    raw_total = sum(positive.values())
    if raw_total <= 0:
        return {}
    desired = {symbol: value / raw_total for symbol, value in positive.items()}
    weights = dict(desired)

    for _ in range(20):
        previous = dict(weights)
        for symbol in weights:
            symbol_cap = float(asset_metadata.get(symbol, {}).get("maxWeight", 1.0))
            weights[symbol] = min(weights[symbol], symbol_cap)

        for asset_class, cap in category_caps.items():
            members = [
                symbol
                for symbol in weights
                if str(asset_metadata.get(symbol, {}).get("assetClass")) == asset_class
            ]
            class_total = sum(weights[symbol] for symbol in members)
            if members and class_total > float(cap):
                scale = float(cap) / class_total
                for symbol in members:
                    weights[symbol] *= scale

        residual = max(0.0, 1.0 - sum(weights.values()))
        if residual <= 1e-12:
            break
        candidates = []
        for symbol in weights:
            metadata = asset_metadata.get(symbol, {})
            asset_class = str(metadata.get("assetClass"))
            symbol_capacity = float(metadata.get("maxWeight", 1.0)) - weights[symbol]
            category_capacity = float(category_caps.get(asset_class, 1.0)) - _category_total(
                weights,
                asset_metadata,
                asset_class,
            )
            capacity = max(0.0, min(symbol_capacity, category_capacity))
            if capacity > 1e-12:
                candidates.append((symbol, capacity))
        if not candidates:
            break

        score_total = sum(desired[symbol] for symbol, _ in candidates)
        for symbol, capacity in candidates:
            share = residual * desired[symbol] / score_total if score_total else residual / len(candidates)
            weights[symbol] += min(capacity, share)
        if all(abs(weights[symbol] - previous.get(symbol, 0.0)) <= 1e-12 for symbol in weights):
            break
    return {symbol: float(value) for symbol, value in weights.items() if value > 1e-12}


def with_btc_cap(
    asset_metadata: Dict[str, Dict[str, object]],
    btc_cap: float,
) -> Dict[str, Dict[str, object]]:
    result = copy.deepcopy(asset_metadata)
    if "BTC-USD" in result:
        result["BTC-USD"]["maxWeight"] = float(btc_cap)
    return result


def select_relative_strength(
    frames: Dict[str, pd.DataFrame],
    symbols: Iterable[str],
    as_of,
    lookback: int,
    top_n: int,
) -> List[str]:
    scores = []
    cutoff = pd.Timestamp(as_of)
    for symbol in symbols:
        frame = frames.get(symbol)
        if frame is None or frame.empty or "Close" not in frame.columns:
            continue
        close = frame.loc[:cutoff, "Close"].dropna().astype(float)
        if len(close) < lookback + 1:
            continue
        prior = float(close.iloc[-lookback - 1])
        current = float(close.iloc[-1])
        if prior > 0:
            scores.append((symbol, current / prior - 1.0))
    scores.sort(key=lambda row: row[1], reverse=True)
    return [symbol for symbol, _ in scores[:top_n]]


def build_research_cache(
    frames: Dict[str, pd.DataFrame],
    end,
) -> Dict[str, object]:
    trend = {mode: {} for mode in ("ma10", "mom12", "ma10_and_mom12")}
    volatility = {lookback: {} for lookback in (60, 120)}
    relative_strength = {lookback: {} for lookback in (60, 120)}
    for symbol, frame in frames.items():
        close = frame["Close"].dropna().astype(float).sort_index()
        for mode in trend:
            trend[mode][symbol] = build_monthly_trend_signals(frame, mode, as_of=end)
        daily_returns = close.pct_change(fill_method=None)
        for lookback in volatility:
            volatility[lookback][symbol] = daily_returns.rolling(
                lookback,
                min_periods=lookback,
            ).std(ddof=1) * math.sqrt(252)
            relative_strength[lookback][symbol] = close.pct_change(
                lookback,
                fill_method=None,
            )
    return {
        "trend": trend,
        "volatility": volatility,
        "relativeStrength": relative_strength,
    }


def _cached_relative_strength(
    cache: Dict[str, object],
    symbols: Iterable[str],
    as_of,
    lookback: int,
    top_n: int,
) -> List[str]:
    scores = []
    score_map = dict(cache.get("relativeStrength", {})).get(lookback, {})
    for symbol in symbols:
        series = score_map.get(symbol)
        if series is None:
            continue
        window = series.loc[: pd.Timestamp(as_of)].dropna()
        if not window.empty:
            scores.append((symbol, float(window.iloc[-1])))
    scores.sort(key=lambda row: row[1], reverse=True)
    return [symbol for symbol, _ in scores[:top_n]]


def build_target_weights(
    frames: Dict[str, pd.DataFrame],
    asset_metadata: Dict[str, Dict[str, object]],
    category_caps: Dict[str, float],
    as_of,
    variant: str,
    trend_mode: str,
    volatility_lookback: int,
    btc_cap: float,
    rs_top_n: Optional[int] = None,
    rs_lookback: int = 120,
    us_rs_tilt: bool = False,
    bond_symbol: str = "511010.SS",
    cash_symbol: str = "__CASH__",
    research_cache: Optional[Dict[str, object]] = None,
) -> Tuple[Dict[str, float], Dict[str, object]]:
    metadata = with_btc_cap(asset_metadata, btc_cap)
    risk_symbols = [
        symbol
        for symbol, row in metadata.items()
        if str(row.get("assetClass")) != "a_bond"
    ]
    trend_states: Dict[str, bool] = {}
    for symbol in risk_symbols + [bond_symbol]:
        frame = frames.get(symbol)
        if frame is None:
            trend_states[symbol] = False
            continue
        if research_cache is not None:
            signal = (
                dict(research_cache.get("trend", {}))
                .get(trend_mode, {})
                .get(symbol, pd.Series(dtype="bool"))
            )
        else:
            signal = build_monthly_trend_signals(frame, trend_mode, as_of=as_of)
        state = latest_completed_signal(signal, as_of)
        trend_states[symbol] = bool(state) if state is not None else False

    eligible = [
        symbol
        for symbol in risk_symbols
        if symbol in frames and (variant == "static_risk_budget" or trend_states.get(symbol, False))
    ]
    if rs_top_n:
        a_share = [
            symbol
            for symbol in eligible
            if str(metadata[symbol].get("assetClass")) == "a_share_equity"
        ]
        if research_cache is not None:
            selected = set(_cached_relative_strength(research_cache, a_share, as_of, rs_lookback, rs_top_n))
        else:
            selected = set(
                select_relative_strength(frames, a_share, as_of, lookback=rs_lookback, top_n=rs_top_n)
            )
        eligible = [symbol for symbol in eligible if symbol not in a_share or symbol in selected]
    if us_rs_tilt:
        us = [
            symbol
            for symbol in eligible
            if str(metadata[symbol].get("assetClass")) == "us_equity"
        ]
        if research_cache is not None:
            selected_us = set(_cached_relative_strength(research_cache, us, as_of, rs_lookback, 1))
        else:
            selected_us = set(select_relative_strength(frames, us, as_of, lookback=rs_lookback, top_n=1))
        eligible = [symbol for symbol in eligible if symbol not in us or symbol in selected_us]

    vol_by_symbol = {}
    for symbol in eligible:
        if research_cache is not None:
            series = (
                dict(research_cache.get("volatility", {}))
                .get(volatility_lookback, {})
                .get(symbol)
            )
            window = series.loc[: pd.Timestamp(as_of)].dropna() if series is not None else pd.Series(dtype="float64")
            volatility = float(window.iloc[-1]) if not window.empty else None
        else:
            volatility = annualized_volatility(frames[symbol]["Close"], as_of, volatility_lookback)
        if volatility is not None:
            vol_by_symbol[symbol] = volatility
    raw = inverse_volatility_weights(vol_by_symbol)
    caps = dict(category_caps)
    caps["crypto"] = float(btc_cap)
    risk_weights = apply_weight_caps(raw, metadata, caps)
    cap_hits = [
        symbol
        for symbol, raw_weight in raw.items()
        if float(risk_weights.get(symbol, 0.0)) + 1e-9 < float(raw_weight)
    ]

    weights = dict(risk_weights)
    residual = max(0.0, 1.0 - sum(weights.values()))
    bond_eligible = (
        bond_symbol in frames
        and (variant == "static_risk_budget" or trend_states.get(bond_symbol, False))
    )
    if bond_eligible:
        weights[bond_symbol] = weights.get(bond_symbol, 0.0) + residual
        residual = 0.0
    if residual > 0:
        weights[cash_symbol] = residual
    diagnostics = {
        "eligibleRiskAssets": eligible,
        "trendStates": trend_states,
        "volatility": vol_by_symbol,
        "rawRiskWeights": raw,
        "cappedRiskWeights": risk_weights,
        "capHits": cap_hits,
        "riskWeightTotal": sum(risk_weights.values()),
        "bondAllocated": bool(bond_eligible),
    }
    return weights, diagnostics


def next_common_trading_date(
    frames: Dict[str, pd.DataFrame],
    symbols: Iterable[str],
    after_date,
    calendar_cache: Optional[Dict[Tuple[str, ...], pd.DatetimeIndex]] = None,
) -> Optional[pd.Timestamp]:
    required = sorted(symbol for symbol in symbols if symbol != "__CASH__" and symbol in frames)
    cutoff = pd.Timestamp(after_date)
    if not required:
        future_dates = sorted(
            {
                pd.Timestamp(date)
                for frame in frames.values()
                for date in frame.index
                if pd.Timestamp(date) > cutoff
            }
        )
        return future_dates[0] if future_dates else None
    key = tuple(required)
    common = calendar_cache.get(key) if calendar_cache is not None else None
    if common is None:
        common = pd.DatetimeIndex(frames[required[0]].index)
        for symbol in required[1:]:
            common = common.intersection(pd.DatetimeIndex(frames[symbol].index))
        common = common.sort_values()
        if calendar_cache is not None:
            calendar_cache[key] = common
    position = int(common.searchsorted(cutoff, side="right"))
    return pd.Timestamp(common[position]) if position < len(common) else None


def price_on(
    frame: Optional[pd.DataFrame],
    date,
    field: str,
) -> Optional[float]:
    if frame is None or frame.empty or field not in frame.columns:
        return None
    timestamp = pd.Timestamp(date)
    if timestamp not in frame.index:
        return None
    value = frame.loc[timestamp, field]
    if isinstance(value, pd.Series):
        value = value.iloc[-1]
    return float(value) if pd.notna(value) else None


def _latest_price(
    frame: Optional[pd.DataFrame],
    date,
    field: str = "Close",
    stale_limit_days: int = 7,
) -> Tuple[Optional[float], bool]:
    if frame is None or frame.empty or field not in frame.columns:
        return None, True
    timestamp = pd.Timestamp(date)
    window = frame.loc[:timestamp, field].dropna()
    if window.empty:
        return None, True
    price_date = pd.Timestamp(window.index[-1])
    stale = (timestamp.normalize() - price_date.normalize()).days > stale_limit_days
    return float(window.iloc[-1]), stale


def portfolio_value_cny(
    state: Dict[str, object],
    frames: Dict[str, pd.DataFrame],
    date,
    field: str = "Close",
    stale_limit_days: int = 7,
) -> Tuple[float, List[str]]:
    total = float(state.get("cash", 0.0))
    stale_symbols: List[str] = []
    for symbol, shares in dict(state.get("shares", {})).items():
        if float(shares) == 0:
            continue
        price, stale = _latest_price(frames.get(symbol), date, field, stale_limit_days)
        if price is None:
            price = float(dict(state.get("lastPrices", {})).get(symbol, 0.0))
            stale = True
        total += float(shares) * price
        if stale:
            stale_symbols.append(symbol)
    return total, sorted(stale_symbols)


def current_weights(
    state: Dict[str, object],
    frames: Dict[str, pd.DataFrame],
    date,
    field: str = "Close",
) -> Dict[str, float]:
    total, _ = portfolio_value_cny(state, frames, date, field=field)
    if total <= 0:
        return {"__CASH__": 1.0}
    weights: Dict[str, float] = {}
    for symbol, shares in dict(state.get("shares", {})).items():
        price, _ = _latest_price(frames.get(symbol), date, field)
        if price is not None and float(shares) != 0:
            weights[symbol] = float(shares) * price / total
    weights["__CASH__"] = float(state.get("cash", 0.0)) / total
    return weights


def should_trade(
    current: Dict[str, float],
    target: Dict[str, float],
    drift_threshold: float,
) -> bool:
    symbols = set(current) | set(target)
    return any(
        abs(float(current.get(symbol, 0.0)) - float(target.get(symbol, 0.0))) > drift_threshold
        for symbol in symbols
    )


def rebalance_at_open(
    state: Dict[str, object],
    target_weights: Dict[str, float],
    frames: Dict[str, pd.DataFrame],
    date,
    fee_bps: float,
    slippage_bps: float,
) -> Dict[str, object]:
    result = {
        "cash": float(state.get("cash", 0.0)),
        "shares": dict(state.get("shares", {})),
        "lastPrices": dict(state.get("lastPrices", {})),
        "costPaid": float(state.get("costPaid", 0.0)),
        "trades": [],
    }
    timestamp = pd.Timestamp(date)
    fee_rate = float(fee_bps) / 10_000
    slip_rate = float(slippage_bps) / 10_000
    symbols = (set(result["shares"]) | set(target_weights)) - {"__CASH__"}
    opens = {symbol: price_on(frames.get(symbol), timestamp, "Open") for symbol in symbols}
    if any(price is None or price <= 0 for price in opens.values()):
        missing = sorted(symbol for symbol, price in opens.items() if price is None or price <= 0)
        raise ValueError(f"Missing execution open for {missing} on {timestamp.date()}")

    initial_value = result["cash"] + sum(
        float(result["shares"].get(symbol, 0.0)) * float(opens[symbol])
        for symbol in symbols
    )
    desired_values = {
        symbol: initial_value * max(0.0, float(target_weights.get(symbol, 0.0)))
        for symbol in symbols
    }

    for symbol in sorted(symbols):
        raw_open = float(opens[symbol])
        current_shares = float(result["shares"].get(symbol, 0.0))
        current_value = current_shares * raw_open
        desired_value = desired_values[symbol]
        if current_value <= desired_value + 1e-15:
            continue
        shares_to_sell = min(current_shares, (current_value - desired_value) / raw_open)
        execution_price = raw_open * (1 - slip_rate)
        gross = shares_to_sell * execution_price
        fee = gross * fee_rate
        result["cash"] += gross - fee
        result["shares"][symbol] = current_shares - shares_to_sell
        result["lastPrices"][symbol] = execution_price
        result["costPaid"] += fee + shares_to_sell * raw_open * slip_rate
        result["trades"].append(
            {
                "symbol": symbol,
                "side": "sell",
                "shares": shares_to_sell,
                "price": execution_price,
                "fee": fee,
            }
        )

    buy_requirements = []
    for symbol in sorted(symbols):
        raw_open = float(opens[symbol])
        current_value = float(result["shares"].get(symbol, 0.0)) * raw_open
        desired_value = desired_values[symbol]
        if desired_value > current_value + 1e-15:
            buy_requirements.append((symbol, desired_value - current_value))
    required_cash = sum(value * (1 + fee_rate) for _, value in buy_requirements)
    scale = min(1.0, result["cash"] / required_cash) if required_cash > 0 else 1.0
    for symbol, desired_purchase_value in buy_requirements:
        raw_open = float(opens[symbol])
        execution_price = raw_open * (1 + slip_rate)
        gross_budget = desired_purchase_value * scale
        shares_to_buy = gross_budget / execution_price
        fee = gross_budget * fee_rate
        cash_needed = gross_budget + fee
        if cash_needed > result["cash"]:
            cash_needed = result["cash"]
            gross_budget = cash_needed / (1 + fee_rate)
            fee = cash_needed - gross_budget
            shares_to_buy = gross_budget / execution_price
        result["cash"] -= cash_needed
        result["shares"][symbol] = float(result["shares"].get(symbol, 0.0)) + shares_to_buy
        result["lastPrices"][symbol] = execution_price
        result["costPaid"] += fee + shares_to_buy * raw_open * slip_rate
        result["trades"].append(
            {
                "symbol": symbol,
                "side": "buy",
                "shares": shares_to_buy,
                "price": execution_price,
                "fee": fee,
            }
        )

    result["cash"] = max(0.0, float(result["cash"]))
    result["shares"] = {
        symbol: float(shares)
        for symbol, shares in result["shares"].items()
        if float(shares) > 1e-15
    }
    return result


def simulate_monthly_portfolio(
    frames: Dict[str, pd.DataFrame],
    target_weight_fn,
    start: Optional[str] = None,
    end: Optional[str] = None,
    fee_bps: float = 5.0,
    slippage_bps: float = 5.0,
    drift_threshold: float = 0.0,
    initial_cash: float = 1.0,
    simulation_cache: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    if simulation_cache is not None:
        all_dates = list(simulation_cache["allDates"])
    else:
        all_dates = sorted(
            {
                pd.Timestamp(date)
                for frame in frames.values()
                for date in frame.index
                if (start is None or pd.Timestamp(date) >= pd.Timestamp(start))
                and (end is None or pd.Timestamp(date) <= pd.Timestamp(end))
            }
        )
    if not all_dates:
        return {"equityCurve": [], "rebalances": [], "costPaid": 0.0}

    first_date = all_dates[0]
    last_date = all_dates[-1]
    month_ends = pd.date_range(
        first_date.to_period("M").end_time.normalize(),
        last_date.to_period("M").end_time.normalize(),
        freq="ME",
    )
    schedule: Dict[pd.Timestamp, Dict[str, object]] = {}
    held_symbols: set[str] = set()
    calendar_cache = (
        simulation_cache.setdefault("calendarCache", {})
        if simulation_cache is not None
        else {}
    )
    for signal_month in month_ends:
        if signal_month >= last_date:
            continue
        target, diagnostics = target_weight_fn(pd.Timestamp(signal_month))
        target_symbols = {symbol for symbol, weight in target.items() if symbol != "__CASH__" and weight > 0}
        execution_date = next_common_trading_date(
            frames,
            held_symbols | target_symbols,
            signal_month,
            calendar_cache=calendar_cache,
        )
        if execution_date is None or execution_date > last_date:
            continue
        schedule[execution_date] = {
            "signalMonth": signal_month,
            "target": target,
            "diagnostics": diagnostics,
        }
        held_symbols = target_symbols

    state: Dict[str, object] = {
        "cash": float(initial_cash),
        "shares": {},
        "lastPrices": {},
        "costPaid": 0.0,
    }
    rebalances = []
    equity_curve = []
    peak = float(initial_cash)
    if simulation_cache is not None:
        aligned_close = simulation_cache["alignedClose"]
        stale_by_symbol = simulation_cache["staleBySymbol"]
    else:
        temporary_cache = build_simulation_cache(frames, start=start, end=end)
        aligned_close = temporary_cache["alignedClose"]
        stale_by_symbol = temporary_cache["staleBySymbol"]
    for date in all_dates:
        if date in schedule:
            order = schedule[date]
            before = current_weights(state, frames, date, field="Open")
            target = dict(order["target"])
            if should_trade(before, target, drift_threshold):
                state = rebalance_at_open(
                    state,
                    target,
                    frames,
                    date,
                    fee_bps=fee_bps,
                    slippage_bps=slippage_bps,
                )
                rebalances.append(
                    {
                        "signalMonth": pd.Timestamp(order["signalMonth"]).date().isoformat(),
                        "executionDate": date.date().isoformat(),
                        "priorWeights": before,
                        "targetWeights": target,
                        "trades": state.pop("trades", []),
                        "diagnostics": order["diagnostics"],
                    }
                )
        equity = float(state.get("cash", 0.0))
        stale_symbols = []
        for symbol, shares in dict(state.get("shares", {})).items():
            price = aligned_close.get(symbol, pd.Series(dtype="float64")).get(date)
            if price is None or pd.isna(price):
                price = float(dict(state.get("lastPrices", {})).get(symbol, 0.0))
                stale_symbols.append(symbol)
            else:
                if bool(stale_by_symbol[symbol].get(date, True)):
                    stale_symbols.append(symbol)
            equity += float(shares) * float(price)
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak * 100 if peak else 0.0
        equity_curve.append(
            {
                "date": date.date().isoformat(),
                "equity": equity,
                "drawdownPct": drawdown,
                "staleSymbols": stale_symbols,
            }
        )
    return {
        "equityCurve": equity_curve,
        "rebalances": rebalances,
        "costPaid": float(state.get("costPaid", 0.0)),
        "finalState": state,
    }


def build_simulation_cache(
    frames: Dict[str, pd.DataFrame],
    start: Optional[str],
    end: Optional[str],
) -> Dict[str, object]:
    all_dates = sorted(
        {
            pd.Timestamp(date)
            for frame in frames.values()
            for date in frame.index
            if (start is None or pd.Timestamp(date) >= pd.Timestamp(start))
            and (end is None or pd.Timestamp(date) <= pd.Timestamp(end))
        }
    )
    all_date_index = pd.DatetimeIndex(all_dates)
    aligned_close = {}
    stale_by_symbol = {}
    for symbol, frame in frames.items():
        close = frame["Close"].reindex(all_date_index).ffill()
        known_dates = pd.Series(pd.DatetimeIndex(frame.index), index=pd.DatetimeIndex(frame.index))
        last_known = known_dates.reindex(all_date_index).ffill()
        age_days = pd.Series(all_date_index, index=all_date_index) - last_known
        aligned_close[symbol] = close
        stale_by_symbol[symbol] = age_days.dt.days > 7
    return {
        "allDates": all_dates,
        "alignedClose": aligned_close,
        "staleBySymbol": stale_by_symbol,
        "calendarCache": {},
    }


def simulate_monthly_portfolio_for_test(
    fee_bps: float,
    slippage_bps: float,
) -> Dict[str, object]:
    dates = pd.to_datetime(["2025-01-31", "2025-02-03", "2025-02-28"])
    frames = {
        "A": pd.DataFrame(
            {
                "Open": [100.0, 100.0, 120.0],
                "Close": [100.0, 100.0, 120.0],
            },
            index=dates,
        )
    }

    def target_weight_fn(_signal_month):
        return {"A": 1.0}, {"source": "test"}

    return simulate_monthly_portfolio(
        frames,
        target_weight_fn,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
    )


def _curve_frame(curve: List[Dict[str, object]]) -> pd.DataFrame:
    if not curve:
        return pd.DataFrame(columns=["equity"])
    frame = pd.DataFrame(curve).copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["equity"] = pd.to_numeric(frame["equity"], errors="coerce")
    return frame.dropna(subset=["date", "equity"]).drop_duplicates("date", keep="last").set_index("date").sort_index()


def drawdown_recovery_stats(curve: List[Dict[str, object]]) -> Dict[str, object]:
    frame = _curve_frame(curve)
    if frame.empty:
        return {
            "maxDrawdownPct": None,
            "longestRecoveryDays": None,
            "unresolvedRecoveryDays": None,
        }
    dates = pd.DatetimeIndex(frame.index)
    equities = frame["equity"].to_numpy(dtype=float)
    peak_equity = float(equities[0])
    peak_date = pd.Timestamp(dates[0])
    drawdown_start = None
    longest_recovery = 0
    max_drawdown = 0.0
    for date, equity in zip(dates, equities):
        if equity >= peak_equity:
            if drawdown_start is not None:
                longest_recovery = max(longest_recovery, (pd.Timestamp(date) - drawdown_start).days)
                drawdown_start = None
            peak_equity = equity
            peak_date = pd.Timestamp(date)
        else:
            if drawdown_start is None:
                drawdown_start = peak_date
            max_drawdown = max(max_drawdown, (peak_equity - equity) / peak_equity * 100)
    unresolved = (pd.Timestamp(frame.index[-1]) - drawdown_start).days if drawdown_start is not None else 0
    longest_recovery = max(longest_recovery, unresolved)
    return {
        "maxDrawdownPct": max_drawdown,
        "longestRecoveryDays": int(longest_recovery),
        "unresolvedRecoveryDays": int(unresolved),
    }


def longest_losing_streak_days(curve: List[Dict[str, object]]) -> int:
    frame = _curve_frame(curve)
    if len(frame) < 2:
        return 0
    returns = frame["equity"].pct_change(fill_method=None)
    longest = 0
    streak_start = None
    for position in range(1, len(frame)):
        date = pd.Timestamp(frame.index[position])
        if float(returns.iloc[position]) < 0:
            if streak_start is None:
                streak_start = pd.Timestamp(frame.index[position - 1])
            longest = max(longest, (date - streak_start).days)
        else:
            streak_start = None
    return int(longest)


def annual_stats(curve: List[Dict[str, object]]) -> List[Dict[str, object]]:
    frame = _curve_frame(curve)
    if frame.empty:
        return []
    rows = []
    previous_equity = None
    for year, group in frame.groupby(frame.index.year):
        start_equity = float(previous_equity) if previous_equity is not None else float(group.iloc[0]["equity"])
        end_equity = float(group.iloc[-1]["equity"])
        peaks = group["equity"].cummax()
        drawdowns = (peaks - group["equity"]) / peaks * 100
        rows.append(
            {
                "year": str(year),
                "returnPct": (end_equity / start_equity - 1) * 100 if start_equity else 0.0,
                "maxDrawdownPct": float(drawdowns.max()) if not drawdowns.empty else 0.0,
                "endEquity": end_equity,
            }
        )
        previous_equity = end_equity
    return rows


def rolling_window_stats(
    curve: List[Dict[str, object]],
    years: int,
) -> List[Dict[str, object]]:
    frame = _curve_frame(curve)
    if frame.empty:
        return []
    frame = frame["equity"].resample("ME").last().dropna().to_frame()
    rows = []
    for start_date, start_row in frame.iterrows():
        target = pd.Timestamp(start_date) + pd.DateOffset(years=years)
        end_position = int(frame.index.searchsorted(target, side="left"))
        if end_position >= len(frame):
            continue
        end_date = pd.Timestamp(frame.index[end_position])
        start_position = int(frame.index.get_loc(start_date))
        window = frame.iloc[start_position : end_position + 1]
        start_equity = float(start_row["equity"])
        end_equity = float(window.iloc[-1]["equity"])
        peaks = window["equity"].cummax()
        drawdowns = (peaks - window["equity"]) / peaks * 100
        rows.append(
            {
                "startDate": pd.Timestamp(start_date).date().isoformat(),
                "endDate": end_date.date().isoformat(),
                "returnPct": (end_equity / start_equity - 1) * 100 if start_equity else 0.0,
                "maxDrawdownPct": float(drawdowns.max()) if not drawdowns.empty else 0.0,
            }
        )
    return rows


def summarize_equity_curve(
    curve: List[Dict[str, object]],
    include_rolling: bool = True,
) -> Dict[str, object]:
    frame = _curve_frame(curve)
    if frame.empty:
        return {
            "startDate": None,
            "endDate": None,
            "historyYears": 0.0,
            "totalReturnPct": None,
            "cagrPct": None,
            "annualVolatilityPct": None,
            "sharpe": None,
            "sortino": None,
            "calmar": None,
            "maxDrawdownPct": None,
            "longestRecoveryDays": None,
            "unresolvedRecoveryDays": None,
            "longestLosingStreakDays": 0,
        }
    start_date = pd.Timestamp(frame.index[0])
    end_date = pd.Timestamp(frame.index[-1])
    history_years = max(0.0, (end_date - start_date).days / 365.25)
    start_equity = float(frame.iloc[0]["equity"])
    end_equity = float(frame.iloc[-1]["equity"])
    total_return = end_equity / start_equity - 1 if start_equity else 0.0
    cagr = (end_equity / start_equity) ** (1 / history_years) - 1 if history_years > 0 and start_equity > 0 else None
    returns = frame["equity"].pct_change(fill_method=None).dropna()
    observations_per_year = len(frame) / history_years if history_years > 0 else 252
    annualization = 365 if observations_per_year > 300 else 252
    volatility = float(returns.std(ddof=1) * math.sqrt(annualization)) if len(returns) > 1 else None
    annual_return = float(returns.mean() * annualization) if not returns.empty else None
    sharpe = annual_return / volatility if annual_return is not None and volatility and volatility > 0 else None
    downside = returns[returns < 0]
    downside_vol = float(downside.std(ddof=1) * math.sqrt(annualization)) if len(downside) > 1 else None
    sortino = annual_return / downside_vol if annual_return is not None and downside_vol and downside_vol > 0 else None
    recovery = drawdown_recovery_stats(curve)
    max_drawdown = recovery["maxDrawdownPct"]
    calmar = (cagr * 100) / max_drawdown if cagr is not None and max_drawdown and max_drawdown > 0 else None
    rolling3 = rolling_window_stats(curve, 3) if include_rolling else []
    rolling5 = rolling_window_stats(curve, 5) if include_rolling else []
    return {
        "startDate": start_date.date().isoformat(),
        "endDate": end_date.date().isoformat(),
        "historyYears": history_years,
        "totalReturnPct": total_return * 100,
        "cagrPct": cagr * 100 if cagr is not None else None,
        "annualVolatilityPct": volatility * 100 if volatility is not None else None,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        **recovery,
        "longestLosingStreakDays": longest_losing_streak_days(curve),
        "worstRolling3YearReturnPct": min((row["returnPct"] for row in rolling3), default=None),
        "worstRolling5YearReturnPct": min((row["returnPct"] for row in rolling5), default=None),
    }


def risk_contribution_stats(
    returns: pd.DataFrame,
    weights: Dict[str, float],
) -> Dict[str, float]:
    symbols = [symbol for symbol in weights if symbol in returns.columns and weights[symbol] > 0]
    if not symbols:
        return {}
    covariance = returns[symbols].dropna().cov() * 252
    weight_vector = pd.Series({symbol: weights[symbol] for symbol in symbols}, dtype="float64")
    portfolio_variance = float(weight_vector.T @ covariance @ weight_vector)
    if portfolio_variance <= 0:
        return {symbol: 0.0 for symbol in symbols}
    marginal = covariance @ weight_vector
    contributions = weight_vector * marginal / portfolio_variance
    return {symbol: float(value) for symbol, value in contributions.items()}


def return_contribution_stats(
    asset_returns: Dict[str, float],
    weights: Dict[str, float],
) -> Dict[str, float]:
    return {
        symbol: float(weights.get(symbol, 0.0)) * float(asset_return)
        for symbol, asset_return in asset_returns.items()
        if symbol in weights
    }


def summarize_dca(
    contributions: List[Dict[str, object]],
    ending_value: float,
    time_weighted_return_pct: Optional[float],
    ending_date: Optional[str] = None,
) -> Dict[str, object]:
    principal = sum(float(row.get("amount", 0.0)) for row in contributions)
    profit = float(ending_value) - principal
    return {
        "principal": principal,
        "endingValue": float(ending_value),
        "profit": profit,
        "principalReturnPct": profit / principal * 100 if principal else None,
        "timeWeightedReturnPct": time_weighted_return_pct,
        "moneyWeightedReturnPct": money_weighted_return_pct(
            contributions,
            ending_value,
            ending_date,
        ),
        "contributionCount": len(contributions),
    }


def money_weighted_return_pct(
    contributions: List[Dict[str, object]],
    ending_value: float,
    ending_date: Optional[str],
) -> Optional[float]:
    if not contributions or not ending_date or ending_value <= 0:
        return None
    dated_flows = [
        (pd.Timestamp(row["date"]), -float(row.get("amount", 0.0)))
        for row in contributions
        if float(row.get("amount", 0.0)) > 0
    ]
    if not dated_flows:
        return None
    end = pd.Timestamp(ending_date)
    if end <= min(date for date, _ in dated_flows):
        return None
    dated_flows.append((end, float(ending_value)))
    origin = min(date for date, _ in dated_flows)

    def xnpv(rate: float) -> float:
        return sum(
            amount / ((1.0 + rate) ** ((date - origin).days / 365.25))
            for date, amount in dated_flows
        )

    lower = -0.9999
    upper = 1.0
    lower_value = xnpv(lower)
    upper_value = xnpv(upper)
    while lower_value * upper_value > 0 and upper < 1_000_000:
        upper *= 2
        upper_value = xnpv(upper)
    if lower_value * upper_value > 0:
        return None
    for _ in range(200):
        midpoint = (lower + upper) / 2
        midpoint_value = xnpv(midpoint)
        if abs(midpoint_value) < 1e-10:
            return midpoint * 100
        if lower_value * midpoint_value <= 0:
            upper = midpoint
        else:
            lower = midpoint
            lower_value = midpoint_value
    return ((lower + upper) / 2) * 100


def evaluate_product_gate(summary: Dict[str, object]) -> Dict[str, object]:
    cagr = summary.get("cagrPct")
    drawdown = summary.get("maxDrawdownPct")
    history_years = summary.get("historyYears")
    rolling3 = summary.get("worstRolling3YearReturnPct")
    recovery = summary.get("longestRecoveryDays")
    failed = []
    notes = []
    if cagr is None or float(cagr) < 8.0:
        failed.append("return_floor")
    elif float(cagr) > 12.0:
        notes.append("return_above_target_band")
    if drawdown is None or float(drawdown) > 20.0:
        failed.append("hard_drawdown_limit")
    if history_years is None or float(history_years) < 5.0:
        failed.append("minimum_history")
    if rolling3 is None:
        failed.append("rolling_three_year_data")
    if recovery is None:
        failed.append("recovery_data")
    return {
        "eligible": not failed,
        "targetReturnMet": cagr is not None and 8.0 <= float(cagr) <= 12.0,
        "targetDrawdownMet": drawdown is not None and float(drawdown) <= 15.0,
        "hardDrawdownMet": drawdown is not None and float(drawdown) <= 20.0,
        "failedGates": failed,
        "notes": notes,
    }


def build_variant_specs() -> List[Dict[str, object]]:
    variants: List[Dict[str, object]] = []

    def append_variant(
        base_id: str,
        strategy: str,
        trend_mode: str,
        volatility_lookback: int,
        btc_cap: float,
        drift_threshold: float,
        rs_top_n: Optional[int] = None,
        us_rs_tilt: bool = False,
    ) -> None:
        variant_id = base_id + ("_drift5" if drift_threshold == 0.05 else "")
        variants.append(
            {
                "id": variant_id,
                "strategy": strategy,
                "trendMode": trend_mode,
                "volatilityLookback": volatility_lookback,
                "btcCap": btc_cap,
                "driftThreshold": drift_threshold,
                "rsTopN": rs_top_n,
                "rsLookback": volatility_lookback,
                "usRsTilt": us_rs_tilt,
            }
        )

    for volatility_lookback in (60, 120):
        for btc_cap in (0.0, 0.05, 0.10):
            btc_label = int(round(btc_cap * 100))
            for drift_threshold in (0.0, 0.05):
                append_variant(
                    f"static_risk_budget_vol{volatility_lookback}_btc{btc_label}",
                    "static_risk_budget",
                    "ma10",
                    volatility_lookback,
                    btc_cap,
                    drift_threshold,
                )

    trend_labels = {
        "ma10": "ma10",
        "mom12": "mom12",
        "ma10_and_mom12": "combined",
    }
    for trend_mode, trend_label in trend_labels.items():
        for volatility_lookback in (60, 120):
            for btc_cap in (0.0, 0.05, 0.10):
                btc_label = int(round(btc_cap * 100))
                for drift_threshold in (0.0, 0.05):
                    append_variant(
                        f"trend_{trend_label}_vol{volatility_lookback}_btc{btc_label}",
                        "trend_risk_budget",
                        trend_mode,
                        volatility_lookback,
                        btc_cap,
                        drift_threshold,
                    )

    for volatility_lookback in (60, 120):
        for btc_cap in (0.0, 0.05, 0.10):
            btc_label = int(round(btc_cap * 100))
            for rs_top_n in (1, 2):
                for us_rs_tilt in (False, True):
                    tilt_suffix = "_us_tilt" if us_rs_tilt else ""
                    for drift_threshold in (0.0, 0.05):
                        append_variant(
                            f"trend_combined_vol{volatility_lookback}_btc{btc_label}_rs_top{rs_top_n}{tilt_suffix}",
                            "trend_risk_budget_rs",
                            "ma10_and_mom12",
                            volatility_lookback,
                            btc_cap,
                            drift_threshold,
                            rs_top_n=rs_top_n,
                            us_rs_tilt=us_rs_tilt,
                        )
    return variants


def simulate_buy_and_hold(
    frame: pd.DataFrame,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> Dict[str, object]:
    values = frame["Close"].dropna().astype(float)
    if start:
        values = values[values.index >= pd.Timestamp(start)]
    if end:
        values = values[values.index <= pd.Timestamp(end)]
    if values.empty:
        return {"equityCurve": [], "summary": summarize_equity_curve([])}
    base = float(values.iloc[0])
    curve = [
        {"date": pd.Timestamp(date).date().isoformat(), "equity": float(value) / base}
        for date, value in values.items()
    ]
    return {"equityCurve": curve, "summary": summarize_equity_curve(curve)}


def simulate_dca_from_equity_curve(
    curve: List[Dict[str, object]],
    monthly_contribution: float = 1_000.0,
) -> Dict[str, object]:
    frame = _curve_frame(curve)
    if frame.empty:
        return summarize_dca([], 0.0, None)
    first_dates = set(frame.groupby(frame.index.to_period("M")).head(1).index)
    units = 0.0
    contributions = []
    account_curve = []
    for date, nav in zip(frame.index, frame["equity"].to_numpy(dtype=float)):
        if nav <= 0:
            continue
        if date in first_dates:
            units += float(monthly_contribution) / nav
            contributions.append(
                {
                    "date": pd.Timestamp(date).date().isoformat(),
                    "amount": float(monthly_contribution),
                }
            )
        account_curve.append(
            {
                "date": pd.Timestamp(date).date().isoformat(),
                "equity": units * nav,
            }
        )
    ending_value = units * float(frame.iloc[-1]["equity"])
    time_weighted = summarize_equity_curve(curve, include_rolling=False).get("totalReturnPct")
    summary = summarize_dca(
        contributions,
        ending_value,
        time_weighted,
        ending_date=pd.Timestamp(frame.index[-1]).date().isoformat(),
    )
    account_summary = summarize_equity_curve(account_curve, include_rolling=False)
    summary["accountMaxDrawdownPct"] = account_summary.get("maxDrawdownPct")
    summary["accountCurve"] = account_curve
    return summary


def simulate_static_allocation_benchmark(
    frames: Dict[str, pd.DataFrame],
    asset_metadata: Dict[str, Dict[str, object]],
    start: Optional[str],
    end: Optional[str],
    fee_bps: float = 5.0,
    slippage_bps: float = 5.0,
    simulation_cache: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    a_share_symbols = [
        symbol
        for symbol, row in asset_metadata.items()
        if str(row.get("assetClass")) == "a_share_equity" and symbol in frames
    ]

    def target_weight_fn(as_of):
        available_a_share = [
            symbol
            for symbol in a_share_symbols
            if not frames[symbol].loc[: pd.Timestamp(as_of)].dropna(subset=["Close"]).empty
        ]
        weights: Dict[str, float] = {}
        if available_a_share:
            per_a_share = 0.20 / len(available_a_share)
            weights.update({symbol: per_a_share for symbol in available_a_share})
        for symbol, weight in (("SPY", 0.15), ("QQQ", 0.15), ("GLD", 0.20), ("511010.SS", 0.30)):
            if symbol in frames and not frames[symbol].loc[: pd.Timestamp(as_of)].dropna(subset=["Close"]).empty:
                weights[symbol] = weight
        residual = max(0.0, 1.0 - sum(weights.values()))
        if residual:
            weights["__CASH__"] = residual
        return weights, {"source": "static_20_30_20_30"}

    result = simulate_monthly_portfolio(
        frames,
        target_weight_fn,
        start=start,
        end=end,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        simulation_cache=simulation_cache,
    )
    result["summary"] = summarize_equity_curve(result["equityCurve"])
    return result


def _slice_curve(
    curve: List[Dict[str, object]],
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> List[Dict[str, object]]:
    result = []
    for point in curve:
        date = pd.Timestamp(point["date"])
        if start and date < pd.Timestamp(start):
            continue
        if end and date > pd.Timestamp(end):
            continue
        result.append(point)
    return result


def _window_summaries(
    curve: List[Dict[str, object]],
    end_date: str,
) -> Dict[str, Dict[str, object]]:
    end = pd.Timestamp(end_date)
    windows = {"full": summarize_equity_curve(curve, include_rolling=False)}
    for years in (3, 5, 10):
        start = (end - pd.DateOffset(years=years)).date().isoformat()
        windows[f"recent{years}Year"] = summarize_equity_curve(
            _slice_curve(curve, start=start, end=end_date),
            include_rolling=False,
        )
    windows["inSample"] = summarize_equity_curve(
        _slice_curve(curve, end="2020-12-31"),
        include_rolling=False,
    )
    windows["outOfSample"] = summarize_equity_curve(
        _slice_curve(curve, start="2021-01-01"),
        include_rolling=False,
    )
    return windows


def _average_target_weights(rebalances: List[Dict[str, object]]) -> Dict[str, float]:
    rows = [dict(row.get("targetWeights") or {}) for row in rebalances]
    if not rows:
        return {}
    symbols = sorted({symbol for row in rows for symbol in row})
    return {
        symbol: sum(float(row.get(symbol, 0.0)) for row in rows) / len(rows)
        for symbol in symbols
    }


def _asset_contributions(
    frames: Dict[str, pd.DataFrame],
    rebalances: List[Dict[str, object]],
    portfolio_curve: List[Dict[str, object]],
    asset_metadata: Dict[str, Dict[str, object]],
    start: str,
    end: str,
    contribution_cache: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    average_weights = _average_target_weights(rebalances)
    if contribution_cache is None:
        contribution_cache = build_contribution_cache(frames, start, end)
    returns_by_symbol = dict(contribution_cache["totalReturns"])
    returns_frame = contribution_cache["dailyReturns"]
    risk = risk_contribution_stats(returns_frame, average_weights)
    return_contribution = return_contribution_stats(returns_by_symbol, average_weights)
    by_category: Dict[str, Dict[str, float]] = {}
    for symbol in set(risk) | set(return_contribution):
        asset_class = str(asset_metadata.get(symbol, {}).get("assetClass", "cash"))
        row = by_category.setdefault(asset_class, {"riskContribution": 0.0, "returnContribution": 0.0})
        row["riskContribution"] += float(risk.get(symbol, 0.0))
        row["returnContribution"] += float(return_contribution.get(symbol, 0.0))

    curve_frame = _curve_frame(portfolio_curve)
    drawdown_contribution = {}
    drawdown_period = None
    if not curve_frame.empty:
        peaks = curve_frame["equity"].cummax()
        drawdown = (peaks - curve_frame["equity"]) / peaks
        trough_date = pd.Timestamp(drawdown.idxmax())
        peak_date = pd.Timestamp(curve_frame.loc[:trough_date, "equity"].idxmax())
        drawdown_period = {
            "peakDate": peak_date.date().isoformat(),
            "troughDate": trough_date.date().isoformat(),
        }
        for symbol, weight in average_weights.items():
            frame = frames.get(symbol)
            if frame is None or symbol == "__CASH__":
                continue
            close = frame.loc[peak_date:trough_date, "Close"].dropna().astype(float)
            if len(close) >= 2:
                contribution = float(weight) * float(close.iloc[-1] / close.iloc[0] - 1)
                drawdown_contribution[symbol] = contribution
                asset_class = str(asset_metadata.get(symbol, {}).get("assetClass", "cash"))
                category = by_category.setdefault(
                    asset_class,
                    {
                        "riskContribution": 0.0,
                        "returnContribution": 0.0,
                        "drawdownContribution": 0.0,
                    },
                )
                category["drawdownContribution"] = float(category.get("drawdownContribution", 0.0)) + contribution
    return {
        "methodology": {
            "returnContribution": "average target weight multiplied by full-period asset return; directional approximation only",
            "riskContribution": "average target weights with full-period daily covariance",
            "drawdownContribution": "average target weight multiplied by asset return during portfolio maximum-drawdown window",
        },
        "averageTargetWeights": average_weights,
        "assetRiskContribution": risk,
        "assetReturnContribution": return_contribution,
        "categoryContribution": by_category,
        "maxDrawdownPeriod": drawdown_period,
        "assetDrawdownContribution": drawdown_contribution,
    }


def build_contribution_cache(
    frames: Dict[str, pd.DataFrame],
    start: str,
    end: str,
) -> Dict[str, object]:
    returns_by_symbol = {}
    daily_returns = {}
    for symbol, frame in frames.items():
        close = frame.loc[pd.Timestamp(start) : pd.Timestamp(end), "Close"].dropna().astype(float)
        if len(close) < 2:
            continue
        returns_by_symbol[symbol] = float(close.iloc[-1] / close.iloc[0] - 1)
        daily_returns[symbol] = close.pct_change(fill_method=None)
    return {
        "totalReturns": returns_by_symbol,
        "dailyReturns": pd.DataFrame(daily_returns),
    }


def asset_correlation_matrix(
    frames: Dict[str, pd.DataFrame],
    start: str,
    end: str,
) -> Dict[str, Dict[str, Optional[float]]]:
    returns = {}
    for symbol, frame in frames.items():
        close = frame.loc[pd.Timestamp(start) : pd.Timestamp(end), "Close"].dropna().astype(float)
        if len(close) >= 2:
            returns[symbol] = close.pct_change(fill_method=None)
    if not returns:
        return {}
    matrix = pd.DataFrame(returns).corr(min_periods=2)
    return {
        symbol: {
            peer: (float(value) if pd.notna(value) else None)
            for peer, value in row.items()
        }
        for symbol, row in matrix.to_dict(orient="index").items()
    }


def _currency_contribution(
    raw_frames: Dict[str, pd.DataFrame],
    cny_frames: Dict[str, pd.DataFrame],
    asset_metadata: Dict[str, Dict[str, object]],
    start: str,
    end: str,
) -> Dict[str, Dict[str, Optional[float]]]:
    rows = {}
    for symbol, metadata in asset_metadata.items():
        if str(metadata.get("currency")) != "USD":
            continue
        raw = raw_frames.get(symbol)
        cny = cny_frames.get(symbol)
        if raw is None or cny is None:
            continue
        raw_close = raw.loc[pd.Timestamp(start) : pd.Timestamp(end), "Close"].dropna().astype(float)
        cny_close = cny.loc[pd.Timestamp(start) : pd.Timestamp(end), "Close"].dropna().astype(float)
        if len(raw_close) < 2 or len(cny_close) < 2:
            continue
        local_return = float(raw_close.iloc[-1] / raw_close.iloc[0] - 1) * 100
        cny_return = float(cny_close.iloc[-1] / cny_close.iloc[0] - 1) * 100
        rows[symbol] = {
            "localReturnPct": local_return,
            "cnyReturnPct": cny_return,
            "currencyEffectPctPoints": cny_return - local_return,
        }
    return rows


def _stress_periods(curve: List[Dict[str, object]]) -> List[Dict[str, object]]:
    periods = {
        "2008": ("2008-01-01", "2008-12-31"),
        "2015": ("2015-01-01", "2015-12-31"),
        "2018": ("2018-01-01", "2018-12-31"),
        "2020": ("2020-01-01", "2020-12-31"),
        "2022": ("2022-01-01", "2022-12-31"),
    }
    rows = []
    for label, (start, end) in periods.items():
        window = _slice_curve(curve, start, end)
        summary = summarize_equity_curve(window)
        rows.append(
            {
                "period": label,
                "available": bool(window),
                "totalReturnPct": summary.get("totalReturnPct"),
                "maxDrawdownPct": summary.get("maxDrawdownPct"),
            }
        )
    return rows


def _run_existing_global_rs(
    raw_frames: Dict[str, pd.DataFrame],
    data_dir: Path,
    a_share_symbols: List[str],
    start: str,
    end: str,
) -> Dict[str, object]:
    path = BACKEND_DIR / "backtest.py"
    spec = importlib.util.spec_from_file_location("balanced_research_backtest", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    symbols = a_share_symbols + ["SPY", "QQQ", "BTC-USD", "GC=F"]
    frames = dict(raw_frames)
    if "GC=F" not in frames:
        gold_futures = load_frame("GC=F", data_dir)
        if gold_futures is not None:
            frames["GC=F"] = gold_futures
    frames = {symbol: frames[symbol] for symbol in symbols if symbol in frames}
    filter_specs = {
        "a_share": ("510300.SS", "monthly_macd"),
        "us": ("SPY", "monthly_macd"),
        "crypto": ("BTC-USD", "monthly_macd"),
        "commodity": ("GC=F", "monthly_macd"),
    }
    filters = {
        asset_class: (frames[symbol], mode)
        for asset_class, (symbol, mode) in filter_specs.items()
        if symbol in frames
    }
    portfolio = module.simulate_rs_rotation_portfolio(
        frames,
        top_n=5,
        rebalance_days=20,
        lookback_bars=60,
        start=start,
        end=end,
        fee_bps=5.0,
        slippage_bps=5.0,
        min_history_bars=250,
        min_avg_volume=0.0,
        per_class_filters=filters,
    )
    curve = portfolio.get("equityCurve") or []
    return {
        "id": "existing_global_rs_monthly_macd",
        "label": "现有全球 RS + 各类别月 MACD",
        "accountingCurrency": "mixed_local_currency_not_directly_comparable",
        "summary": summarize_equity_curve(curve),
        "windows": _window_summaries(curve, end),
        "annual": annual_stats(curve),
        "rolling3": rolling_window_stats(curve, 3),
        "rolling5": rolling_window_stats(curve, 5),
        "stressPeriods": _stress_periods(curve),
        "equityCurve": curve,
        "caveat": "现有实现直接混合各市场本币价格，未按人民币汇率换算，只能作为旧策略参考。",
    }


def _variant_stability(
    variants: List[Dict[str, object]],
    candidate: Dict[str, object],
) -> Dict[str, object]:
    spec = candidate["spec"]
    neighbors = [
        row
        for row in variants
        if row["spec"]["strategy"] == spec["strategy"]
        and row["spec"]["trendMode"] == spec["trendMode"]
        and row["spec"]["btcCap"] == spec["btcCap"]
        and row["spec"].get("rsTopN") == spec.get("rsTopN")
        and row["spec"].get("usRsTilt") == spec.get("usRsTilt")
    ]
    cagrs = [float(row["summary"]["cagrPct"]) for row in neighbors if row["summary"].get("cagrPct") is not None]
    drawdowns = [
        float(row["summary"]["maxDrawdownPct"])
        for row in neighbors
        if row["summary"].get("maxDrawdownPct") is not None
    ]
    passes = bool(neighbors) and all(row["gate"]["hardDrawdownMet"] for row in neighbors) and all(
        row["summary"].get("cagrPct") is not None and float(row["summary"]["cagrPct"]) >= 6.0
        for row in neighbors
    )
    return {
        "candidateId": candidate["id"],
        "neighborIds": [row["id"] for row in neighbors],
        "neighborCount": len(neighbors),
        "cagrRangePct": [min(cagrs), max(cagrs)] if cagrs else None,
        "drawdownRangePct": [min(drawdowns), max(drawdowns)] if drawdowns else None,
        "pass": passes,
    }


def _recommend_candidate(
    variants: List[Dict[str, object]],
    benchmarks: Optional[List[Dict[str, object]]] = None,
) -> Tuple[Dict[str, object], Dict[str, object]]:
    benchmark_lead = next(
        (
            row
            for row in benchmarks or []
            if row.get("id") == "static_stock_bond_gold_cny"
            and row.get("gate", {}).get("targetReturnMet")
            and row.get("gate", {}).get("targetDrawdownMet")
        ),
        None,
    )
    default_family = [
        row
        for row in variants
        if row["spec"]["strategy"] == "trend_risk_budget"
        and row["spec"]["btcCap"] == 0.05
        and row["gate"]["eligible"]
    ]
    default_family.sort(
        key=lambda row: (
            bool(row["gate"]["targetDrawdownMet"]),
            float(row["summary"].get("calmar") or -999),
        ),
        reverse=True,
    )
    for candidate in default_family:
        stability = _variant_stability(variants, candidate)
        if candidate["gate"]["targetReturnMet"] and candidate["gate"]["targetDrawdownMet"] and stability["pass"]:
            return {
                "status": "eligible_default",
                "candidateId": candidate["id"],
                "reason": "达到收益和回撤目标，且相邻参数稳定。",
            }, stability
    if default_family:
        candidate = default_family[0]
        stability = _variant_stability(variants, candidate)
        reason_parts = ["趋势风险预算候选通过硬门槛"]
        if stability["pass"]:
            reason_parts.append("且相邻参数稳定")
        else:
            reason_parts.append("但相邻参数稳定性未通过")
        if not candidate["gate"]["targetReturnMet"]:
            reason_parts.append("年化收益未落在 8%～12% 目标带")
        if not candidate["gate"]["targetDrawdownMet"]:
            reason_parts.append("最大回撤未达到 15% 目标")
        reason = "，".join(reason_parts) + "。"
        if benchmark_lead is not None:
            reason += (
                "静态股债金基准命中表面收益与回撤目标，但它是固定权重基准，"
                "尚未完成权重稳定性验证，因此不提升为默认策略。"
            )
        return {
            "status": "no_target_default",
            "candidateId": candidate["id"],
            "researchLeadId": benchmark_lead.get("id") if benchmark_lead else candidate["id"],
            "reason": reason,
        }, stability
    return {
        "status": "no_eligible_default",
        "candidateId": None,
        "researchLeadId": benchmark_lead.get("id") if benchmark_lead else None,
        "reason": "没有趋势风险预算候选通过收益下限、20% 回撤硬上限、历史与滚动数据门槛。",
    }, {}


def _fmt(value, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "-"
    return f"{float(value):.{digits}f}{suffix}"


def render_markdown_report(payload: Dict[str, object]) -> str:
    coverage = dict(payload.get("coverage") or {})
    variants = list(payload.get("variants") or [])
    benchmarks = list(payload.get("benchmarks") or [])
    recommendation = dict(payload.get("recommendation") or {})
    missing_stress = coverage.get("missingStressPeriods") or []
    no_default = recommendation.get("status") != "eligible_default"
    lines = [
        "# 多资产趋势风险预算平衡组合研究 2026-06-06",
        "",
        "## 结论",
        "",
    ]
    if no_default:
        lines.extend(
            [
                "**当前没有合格默认策略。**",
                "",
                str(recommendation.get("reason") or "候选未通过预设产品门槛。"),
            ]
        )
    else:
        lines.extend(
            [
                f"默认候选：`{recommendation.get('candidateId')}`。",
                "",
                str(recommendation.get("reason") or ""),
            ]
        )
    lines.extend(
        [
            "",
            "## 数据覆盖与限制",
            "",
            f"- 共同研究区间：`{coverage.get('commonStartDate')}` ～ `{coverage.get('commonEndDate')}`。",
            f"- 无法覆盖的预设压力年份：{', '.join(missing_stress) if missing_stress else '无'}。",
            "- 美元资产已按当日已知 USD/CNY 汇率转换为人民币；旧全球 RS 基准仍是混合本币口径，不能直接公平比较。",
            "- A 股宽基按当时已有足够历史动态准入；当前本地 ETF 主表仍不等于完整历史全市场主表。",
            "",
            "## 固定假设",
            "",
            "- 只做多，不加杠杆，不做空。",
            "- 月末确认信号，下一个共同可交易日开盘执行。",
            "- 单边手续费 5 bps，单边滑点 5 bps。",
            "- A 股权益上限 30%，美股权益上限 40%，黄金上限 25%，BTC 测试 0%/5%/10%。",
            "- 未分配风险预算进入趋势合格 A债，否则持现金。",
            "",
            "## 全部候选",
            "",
            "| 候选 | CAGR | 最大回撤 | Calmar | 最差滚动3年 | 修复天数 | 调仓 | 成本 | 硬门槛 | 目标回撤 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    for row in variants:
        summary = row.get("summary") or {}
        gate = row.get("gate") or {}
        lines.append(
            f"| `{row.get('id')}` | {_fmt(summary.get('cagrPct'), suffix='%')} | "
            f"{_fmt(summary.get('maxDrawdownPct'), suffix='%')} | {_fmt(summary.get('calmar'))} | "
            f"{_fmt(summary.get('worstRolling3YearReturnPct'), suffix='%')} | "
            f"{_fmt(summary.get('longestRecoveryDays'), digits=0)} | {row.get('rebalanceCount', 0)} | "
            f"{_fmt(float(row.get('costPaid') or 0) * 100, suffix='%')} | "
            f"{'通过' if gate.get('eligible') else '失败'} | "
            f"{'达到' if gate.get('targetDrawdownMet') else '未达到'} |"
        )
    lines.extend(
        [
            "",
            "## 固定基准",
            "",
            "| 基准 | 收益/CAGR | 最大回撤 | 口径说明 |",
            "|---|---:|---:|---|",
        ]
    )
    for row in benchmarks:
        summary = row.get("summary") or {}
        gate = row.get("gate") or {}
        note = str(row.get("caveat") or row.get("accountingCurrency") or "CNY").rstrip("。；; ")
        gate_note = ""
        if gate:
            gate_note = (
                "；命中收益/回撤目标"
                if gate.get("targetReturnMet") and gate.get("targetDrawdownMet")
                else "；未同时命中收益/回撤目标"
            )
        lines.append(
            f"| `{row.get('id')}` | {_fmt(summary.get('cagrPct') or summary.get('principalReturnPct'), suffix='%')} | "
            f"{_fmt(summary.get('maxDrawdownPct') or summary.get('accountMaxDrawdownPct'), suffix='%')} | "
            f"{note}{gate_note} |"
        )
    lines.extend(
        [
            "",
            "## 逐标的数据覆盖",
            "",
            "| 标的 | 起始日期 | 结束日期 | 有效行数 |",
            "|---|---|---|---:|",
        ]
    )
    for symbol, row in sorted(dict(coverage.get("bySymbol") or {}).items()):
        lines.append(
            f"| {symbol} | {row.get('startDate') or '-'} | {row.get('endDate') or '-'} | "
            f"{row.get('rows', 0)} |"
        )
    lines.extend(
        [
            "",
            "## BTC 0% / 5% / 10% 敏感性",
            "",
            "| 组合族 | BTC上限 | CAGR | 最大回撤 |",
            "|---|---:|---:|---:|",
        ]
    )
    for row in payload.get("btcSensitivity") or []:
        lines.append(
            f"| `{row.get('family')}` | {_fmt(float(row.get('btcCap') or 0) * 100, suffix='%')} | "
            f"{_fmt(row.get('cagrPct'), suffix='%')} | {_fmt(row.get('maxDrawdownPct'), suffix='%')} |"
        )
    stability = payload.get("stability") or {}
    records_by_id = {
        str(row.get("id")): row
        for row in variants + benchmarks
        if row.get("id")
    }
    focus_ids = []
    for key in ("candidateId", "researchLeadId"):
        record_id = recommendation.get(key)
        if record_id and record_id not in focus_ids:
            focus_ids.append(record_id)
    focus_records = [
        records_by_id[record_id]
        for record_id in focus_ids
        if record_id in records_by_id
    ]
    lines.extend(
        [
            "",
            "## 参数稳定性",
            "",
            f"- 候选：`{stability.get('candidateId') or '-'}`。",
            f"- 相邻参数数量：{stability.get('neighborCount', 0)}。",
            f"- CAGR 范围：{stability.get('cagrRangePct') or '-'}。",
            f"- 最大回撤范围：{stability.get('drawdownRangePct') or '-'}。",
            f"- 稳定性门槛：{'通过' if stability.get('pass') else '未通过'}。",
            "",
            "## 年度、滚动窗口与压力期",
        ]
    )
    if not focus_records:
        lines.extend(["", "当前没有可展开的候选记录；完整结果保存在配套 JSON 中。"])
    for row in focus_records:
        lines.extend(
            [
                "",
                f"### `{row.get('id')}` 自然年",
                "",
                "| 年份 | 收益 | 年内最大回撤 |",
                "|---|---:|---:|",
            ]
        )
        for annual in row.get("annual") or []:
            lines.append(
                f"| {annual.get('year')} | {_fmt(annual.get('returnPct'), suffix='%')} | "
                f"{_fmt(annual.get('maxDrawdownPct'), suffix='%')} |"
            )
    lines.extend(
        [
            "",
            "| 方案 | 最差滚动3年 | 最差滚动5年 | 最长修复天数 |",
            "|---|---:|---:|---:|",
        ]
    )
    for row in focus_records:
        summary = row.get("summary") or {}
        lines.append(
            f"| `{row.get('id')}` | {_fmt(summary.get('worstRolling3YearReturnPct'), suffix='%')} | "
            f"{_fmt(summary.get('worstRolling5YearReturnPct'), suffix='%')} | "
            f"{_fmt(summary.get('longestRecoveryDays'), digits=0)} |"
        )
    lines.extend(
        [
            "",
            "| 方案 | 窗口 | CAGR | 最大回撤 |",
            "|---|---|---:|---:|",
        ]
    )
    for row in focus_records:
        windows = row.get("windows") or {}
        for key, label in (
            ("recent3Year", "最近3年"),
            ("recent5Year", "最近5年"),
            ("recent10Year", "最近10年"),
        ):
            summary = windows.get(key) or {}
            lines.append(
                f"| `{row.get('id')}` | {label} | {_fmt(summary.get('cagrPct'), suffix='%')} | "
                f"{_fmt(summary.get('maxDrawdownPct'), suffix='%')} |"
            )
    lines.extend(
        [
            "",
            "| 方案 | 压力期 | 收益 | 最大回撤 |",
            "|---|---|---:|---:|",
        ]
    )
    for row in focus_records:
        for stress in row.get("stressPeriods") or []:
            if not stress.get("available"):
                continue
            lines.append(
                f"| `{row.get('id')}` | {stress.get('period')} | "
                f"{_fmt(stress.get('totalReturnPct'), suffix='%')} | "
                f"{_fmt(stress.get('maxDrawdownPct'), suffix='%')} |"
            )
    lines.extend(
        [
            "",
            "## 回撤与修复",
            "",
            "| 方案 | 最大回撤 | 最长修复天数 | 未修复天数 | 最长连续亏损天数 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in focus_records:
        summary = row.get("summary") or {}
        lines.append(
            f"| `{row.get('id')}` | {_fmt(summary.get('maxDrawdownPct'), suffix='%')} | "
            f"{_fmt(summary.get('longestRecoveryDays'), digits=0)} | "
            f"{_fmt(summary.get('unresolvedRecoveryDays'), digits=0)} | "
            f"{_fmt(summary.get('longestLosingStreakDays'), digits=0)} |"
        )
    lines.extend(
        [
            "",
            "## 成本与换手",
            "",
            "| 方案 | 累计换手 | 调仓次数 | 估算累计成本/初始净值 |",
            "|---|---:|---:|---:|",
        ]
    )
    for row in focus_records:
        turnover = row.get("turnover") or {}
        lines.append(
            f"| `{row.get('id')}` | {_fmt(turnover.get('totalTurnover'))} | "
            f"{row.get('rebalanceCount', 0)} | {_fmt(float(row.get('costPaid') or 0) * 100, suffix='%')} |"
        )
    lines.extend(
        [
            "",
            "| 手续费 bps | 滑点 bps | CAGR | 最大回撤 |",
            "|---:|---:|---:|---:|",
        ]
    )
    for row in payload.get("costSensitivity") or []:
        lines.append(
            f"| {_fmt(row.get('feeBps'))} | {_fmt(row.get('slippageBps'))} | "
            f"{_fmt(row.get('cagrPct'), suffix='%')} | {_fmt(row.get('maxDrawdownPct'), suffix='%')} |"
        )
    lines.extend(
        [
            "",
            "## 存量资金与持续入金",
            "",
            "| 方案 | 投入本金 | 期末金额 | 本金收益 | 资金加权收益(XIRR) | 策略时间加权收益 | 入金账户回撤 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    dca_rows = [row for row in focus_records if row.get("dca")]
    dca_rows.extend(
        row
        for row in benchmarks
        if row.get("id") in {"spy_dca_cny", "qqq_dca_cny"}
        and row not in dca_rows
    )
    for row in dca_rows:
        dca = row.get("dca") or row.get("summary") or {}
        lines.append(
            f"| `{row.get('id')}` | {_fmt(dca.get('principal'))} | {_fmt(dca.get('endingValue'))} | "
            f"{_fmt(dca.get('principalReturnPct'), suffix='%')} | "
            f"{_fmt(dca.get('moneyWeightedReturnPct'), suffix='%')} | "
            f"{_fmt(dca.get('timeWeightedReturnPct'), suffix='%')} | "
            f"{_fmt(dca.get('accountMaxDrawdownPct'), suffix='%')} |"
        )
    lines.extend(
        [
            "",
            "定投入金不计入策略收益；本金收益、XIRR 与时间加权收益分别展示，不能与一次性满仓总收益直接排序。",
            "",
            "## 汇率贡献",
            "",
            "| 标的 | 本币收益 | 人民币收益 | 汇率贡献百分点 |",
            "|---|---:|---:|---:|",
        ]
    )
    for symbol, row in dict(payload.get("currencyContribution") or {}).items():
        lines.append(
            f"| {symbol} | {_fmt(row.get('localReturnPct'), suffix='%')} | "
            f"{_fmt(row.get('cnyReturnPct'), suffix='%')} | "
            f"{_fmt(row.get('currencyEffectPctPoints'), suffix='%')} |"
        )
    lines.extend(
        [
            "",
            "| 汇率情景 | CAGR | 最大回撤 |",
            "|---|---:|---:|",
        ]
    )
    for row in payload.get("fxSensitivity") or []:
        lines.append(
            f"| {row.get('mode')} | {_fmt(row.get('cagrPct'), suffix='%')} | "
            f"{_fmt(row.get('maxDrawdownPct'), suffix='%')} |"
        )
    lines.extend(
        [
            "",
            "恒定汇率情景只用于隔离历史 USD/CNY 路径影响，不代表可交易的人民币账户结果。",
            "",
            "## 关键资产相关性",
            "",
            "| 资产 A | 资产 B | 日收益相关系数 |",
            "|---|---|---:|",
        ]
    )
    emitted_pairs = set()
    for symbol, peers in dict(payload.get("assetCorrelations") or {}).items():
        for peer, value in dict(peers or {}).items():
            pair = frozenset((symbol, peer))
            if symbol == peer or pair in emitted_pairs or value is None:
                continue
            emitted_pairs.add(pair)
            lines.append(f"| {symbol} | {peer} | {_fmt(value)} |")
    lines.extend(
        [
            "",
            "## 类别贡献",
            "",
            "以下收益、风险与回撤贡献使用平均目标权重近似，只用于方向诊断，不是可加总的精确业绩归因。",
            "",
            "| 方案 | 类别 | 收益贡献 | 风险贡献 | 最大回撤期贡献 |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for row in focus_records:
        categories = dict(
            (row.get("contributions") or {}).get("categoryContribution") or {}
        )
        for category, contribution in sorted(categories.items()):
            lines.append(
                f"| `{row.get('id')}` | {category} | "
                f"{_fmt(float(contribution.get('returnContribution') or 0) * 100, suffix='%')} | "
                f"{_fmt(float(contribution.get('riskContribution') or 0) * 100, suffix='%')} | "
                f"{_fmt(float(contribution.get('drawdownContribution') or 0) * 100, suffix='%')} |"
            )
    lines.extend(
        [
            "",
            "## 产品化结论",
            "",
        ]
    )
    if no_default:
        lines.append("当前没有合格默认策略。现有结果只能作为下一轮研究依据，不能上线为收益承诺或默认配置。")
    else:
        lines.append("候选通过预设目标与稳定性门槛，仍需人工审阅后才能进入 API 和前端产品设计。")
    return "\n".join(lines) + "\n"


def _turnover_stats(rebalances: List[Dict[str, object]]) -> Dict[str, float]:
    total = 0.0
    for row in rebalances:
        prior = dict(row.get("priorWeights") or {})
        target = dict(row.get("targetWeights") or {})
        symbols = set(prior) | set(target)
        total += sum(abs(float(target.get(symbol, 0.0)) - float(prior.get(symbol, 0.0))) for symbol in symbols) / 2
    return {
        "totalTurnover": total,
        "averageTurnoverPerRebalance": total / len(rebalances) if rebalances else 0.0,
    }


def _json_default(value):
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def build_multi_asset_balanced_research(
    config_path: Path = DEFAULT_CONFIG,
    data_dir: Path = DEFAULT_DATA_DIR,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> Dict[str, object]:
    config_path = Path(config_path)
    data_dir = Path(data_dir)
    config = load_config(config_path)
    assets = expand_assets(config, config_path.parent)
    asset_metadata = {str(row["symbol"]).upper(): dict(row) for row in assets}
    raw_frames, missing, fx_frame = load_all_frames(assets, str(config["fxSymbol"]), data_dir)
    required = ["SPY", "QQQ", "GLD", "511010.SS", "BTC-USD"]
    missing_required = [symbol for symbol in required if symbol not in raw_frames]
    if fx_frame is None:
        missing_required.append(str(config["fxSymbol"]))
    if missing_required:
        raise RuntimeError(f"Missing fixed research data: {sorted(set(missing_required))}")

    cny_frames = {
        symbol: normalize_ohlc_to_cny(
            frame,
            str(asset_metadata[symbol].get("currency", "CNY")),
            fx_frame,
        ).dropna(subset=["Open", "Close"])
        for symbol, frame in raw_frames.items()
        if symbol in asset_metadata
    }
    a_share_symbols = [
        symbol
        for symbol, metadata in asset_metadata.items()
        if str(metadata.get("assetClass")) == "a_share_equity" and symbol in cny_frames
    ]
    if not a_share_symbols:
        raise RuntimeError("No A-share broad ETF data is available")
    a_share_anchor = min(
        a_share_symbols,
        key=lambda symbol: pd.Timestamp(cny_frames[symbol].dropna(subset=["Close"]).index.min()),
    )
    coverage_symbols = required + [a_share_anchor]
    starts = [pd.Timestamp(cny_frames[symbol].dropna(subset=["Close"]).index.min()) for symbol in coverage_symbols]
    ends = [pd.Timestamp(cny_frames[symbol].dropna(subset=["Close"]).index.max()) for symbol in coverage_symbols]
    starts.append(pd.Timestamp(fx_frame.dropna(subset=["Close"]).index.min()))
    ends.append(pd.Timestamp(fx_frame.dropna(subset=["Close"]).index.max()))
    common_start = max(starts)
    common_end = min(ends)
    if start:
        common_start = max(common_start, pd.Timestamp(start))
    if end:
        common_end = min(common_end, pd.Timestamp(end))
    if common_start >= common_end:
        raise RuntimeError(f"No common study period: {common_start} to {common_end}")
    start_date = common_start.date().isoformat()
    end_date = common_end.date().isoformat()

    audit = coverage_audit(cny_frames)
    audit["commonStartDate"] = start_date
    audit["commonEndDate"] = end_date
    stress_years = (2008, 2015, 2018, 2020, 2022)
    audit["missingStressPeriods"] = [
        str(year)
        for year in stress_years
        if pd.Timestamp(f"{year}-01-01") < common_start
        or pd.Timestamp(f"{year}-12-31") > common_end
    ]
    audit["fxSymbol"] = str(config["fxSymbol"])
    audit["fxStartDate"] = pd.Timestamp(fx_frame.dropna(subset=["Close"]).index.min()).date().isoformat()
    audit["fxEndDate"] = pd.Timestamp(fx_frame.dropna(subset=["Close"]).index.max()).date().isoformat()
    audit["missingSymbols"] = missing

    category_caps = {str(key): float(value) for key, value in dict(config["categoryCaps"]).items()}
    research_cache = build_research_cache(cny_frames, end=common_end)
    simulation_cache = build_simulation_cache(cny_frames, start=start_date, end=end_date)
    contribution_cache = build_contribution_cache(cny_frames, start_date, end_date)

    def simulate_variant_spec(
        spec: Dict[str, object],
        fee_bps: float = 5.0,
        slippage_bps: float = 5.0,
        analysis_frames: Optional[Dict[str, pd.DataFrame]] = None,
        analysis_research_cache: Optional[Dict[str, object]] = None,
        analysis_simulation_cache: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        active_frames = analysis_frames or cny_frames
        active_research_cache = analysis_research_cache or research_cache
        active_simulation_cache = analysis_simulation_cache or simulation_cache

        def target_weight_fn(as_of):
            return build_target_weights(
                active_frames,
                asset_metadata,
                category_caps,
                as_of=as_of,
                variant=str(spec["strategy"]),
                trend_mode=str(spec["trendMode"]),
                volatility_lookback=int(spec["volatilityLookback"]),
                btc_cap=float(spec["btcCap"]),
                rs_top_n=spec.get("rsTopN"),
                rs_lookback=int(spec.get("rsLookback") or 120),
                us_rs_tilt=bool(spec.get("usRsTilt")),
                research_cache=active_research_cache,
            )

        return simulate_monthly_portfolio(
            active_frames,
            target_weight_fn,
            start=start_date,
            end=end_date,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            drift_threshold=float(spec["driftThreshold"]),
            simulation_cache=active_simulation_cache,
        )

    variants = []
    for spec in build_variant_specs():
        simulation = simulate_variant_spec(spec)
        curve = simulation["equityCurve"]
        rolling3 = rolling_window_stats(curve, 3)
        rolling5 = rolling_window_stats(curve, 5)
        summary = summarize_equity_curve(curve, include_rolling=False)
        summary["worstRolling3YearReturnPct"] = min(
            (row["returnPct"] for row in rolling3),
            default=None,
        )
        summary["worstRolling5YearReturnPct"] = min(
            (row["returnPct"] for row in rolling5),
            default=None,
        )
        dca = simulate_dca_from_equity_curve(curve)
        dca.pop("accountCurve", None)
        rebalances = simulation["rebalances"]
        cap_trigger_count = sum(1 for row in rebalances if row.get("diagnostics", {}).get("capHits"))
        variant = {
            "id": spec["id"],
            "spec": spec,
            "summary": summary,
            "windows": _window_summaries(curve, end_date),
            "annual": annual_stats(curve),
            "rolling3": rolling3,
            "rolling5": rolling5,
            "stressPeriods": _stress_periods(curve),
            "gate": evaluate_product_gate(summary),
            "dca": dca,
            "costPaid": simulation["costPaid"],
            "rebalanceCount": len(rebalances),
            "turnover": _turnover_stats(rebalances),
            "capTriggerCount": cap_trigger_count,
            "capTriggerFrequency": cap_trigger_count / len(rebalances) if rebalances else 0.0,
            "contributions": _asset_contributions(
                cny_frames,
                rebalances,
                curve,
                asset_metadata,
                start_date,
                end_date,
                contribution_cache=contribution_cache,
            ),
            "rebalances": rebalances,
            "equityCurve": curve,
        }
        variants.append(variant)

    spy_hold = simulate_buy_and_hold(cny_frames["SPY"], start_date, end_date)
    qqq_hold = simulate_buy_and_hold(cny_frames["QQQ"], start_date, end_date)
    spy_dca = simulate_dca_from_equity_curve(spy_hold["equityCurve"])
    qqq_dca = simulate_dca_from_equity_curve(qqq_hold["equityCurve"])
    spy_dca.pop("accountCurve", None)
    qqq_dca.pop("accountCurve", None)
    static_allocation = simulate_static_allocation_benchmark(
        cny_frames,
        asset_metadata,
        start_date,
        end_date,
        simulation_cache=simulation_cache,
    )
    static_curve = static_allocation["equityCurve"]
    static_dca = simulate_dca_from_equity_curve(static_curve)
    static_dca.pop("accountCurve", None)
    static_rebalances = static_allocation["rebalances"]
    static_reference = next(
        row
        for row in variants
        if row["id"] == "static_risk_budget_vol120_btc0"
    )
    benchmarks = [
        {
            "id": "spy_buy_hold_cny",
            "label": "SPY 买入持有",
            "accountingCurrency": "CNY",
            "summary": spy_hold["summary"],
            "windows": _window_summaries(spy_hold["equityCurve"], end_date),
            "annual": annual_stats(spy_hold["equityCurve"]),
            "rolling3": rolling_window_stats(spy_hold["equityCurve"], 3),
            "rolling5": rolling_window_stats(spy_hold["equityCurve"], 5),
            "stressPeriods": _stress_periods(spy_hold["equityCurve"]),
            "equityCurve": spy_hold["equityCurve"],
        },
        {
            "id": "qqq_buy_hold_cny",
            "label": "QQQ 买入持有",
            "accountingCurrency": "CNY",
            "summary": qqq_hold["summary"],
            "windows": _window_summaries(qqq_hold["equityCurve"], end_date),
            "annual": annual_stats(qqq_hold["equityCurve"]),
            "rolling3": rolling_window_stats(qqq_hold["equityCurve"], 3),
            "rolling5": rolling_window_stats(qqq_hold["equityCurve"], 5),
            "stressPeriods": _stress_periods(qqq_hold["equityCurve"]),
            "equityCurve": qqq_hold["equityCurve"],
        },
        {
            "id": "spy_dca_cny",
            "label": "SPY 月定投",
            "accountingCurrency": "CNY_DCA",
            "summary": spy_dca,
            "caveat": "投入本金收益与时间加权策略收益分开，不和一次性满仓总收益直接比较。",
        },
        {
            "id": "qqq_dca_cny",
            "label": "QQQ 月定投",
            "accountingCurrency": "CNY_DCA",
            "summary": qqq_dca,
            "caveat": "投入本金收益与时间加权策略收益分开，不和一次性满仓总收益直接比较。",
        },
        {
            "id": "static_stock_bond_gold_cny",
            "label": "静态股债金组合",
            "accountingCurrency": "CNY",
            "summary": static_allocation["summary"],
            "windows": _window_summaries(static_curve, end_date),
            "annual": annual_stats(static_curve),
            "rolling3": rolling_window_stats(static_curve, 3),
            "rolling5": rolling_window_stats(static_curve, 5),
            "stressPeriods": _stress_periods(static_curve),
            "gate": evaluate_product_gate(static_allocation["summary"]),
            "dca": static_dca,
            "costPaid": static_allocation["costPaid"],
            "rebalanceCount": len(static_rebalances),
            "turnover": _turnover_stats(static_rebalances),
            "contributions": _asset_contributions(
                cny_frames,
                static_rebalances,
                static_curve,
                asset_metadata,
                start_date,
                end_date,
                contribution_cache=contribution_cache,
            ),
            "rebalances": static_rebalances,
            "equityCurve": static_curve,
        },
        {
            "id": "static_inverse_volatility_cny",
            "label": "静态逆波动风险预算",
            "accountingCurrency": "CNY",
            "summary": static_reference["summary"],
            "windows": static_reference["windows"],
            "annual": static_reference["annual"],
            "rolling3": static_reference["rolling3"],
            "rolling5": static_reference["rolling5"],
            "stressPeriods": static_reference["stressPeriods"],
            "gate": static_reference["gate"],
            "caveat": "引用完整实验矩阵中的 static_risk_budget_vol120_btc0。",
        },
        _run_existing_global_rs(raw_frames, data_dir, a_share_symbols, start_date, end_date),
    ]

    recommendation, stability = _recommend_candidate(variants, benchmarks)
    cost_sensitivity = []
    fx_sensitivity = []
    selected = next(
        (
            row
            for row in variants
            if row["id"] == recommendation.get("candidateId")
        ),
        None,
    )
    if selected is not None:
        for fee_bps, slippage_bps in ((0.0, 0.0), (5.0, 5.0), (10.0, 10.0)):
            if fee_bps == 5.0 and slippage_bps == 5.0:
                summary = selected["summary"]
                cost_paid = selected["costPaid"]
            else:
                sensitivity_run = simulate_variant_spec(
                    selected["spec"],
                    fee_bps=fee_bps,
                    slippage_bps=slippage_bps,
                )
                summary = summarize_equity_curve(
                    sensitivity_run["equityCurve"],
                    include_rolling=False,
                )
                cost_paid = sensitivity_run["costPaid"]
            cost_sensitivity.append(
                {
                    "candidateId": selected["id"],
                    "feeBps": fee_bps,
                    "slippageBps": slippage_bps,
                    "cagrPct": summary.get("cagrPct"),
                    "maxDrawdownPct": summary.get("maxDrawdownPct"),
                    "costPaid": cost_paid,
                }
            )
        fx_sensitivity.append(
            {
                "candidateId": selected["id"],
                "mode": "actual_cny_fx",
                "cagrPct": selected["summary"].get("cagrPct"),
                "maxDrawdownPct": selected["summary"].get("maxDrawdownPct"),
            }
        )
        constant_fx_frames = build_constant_fx_counterfactual_frames(
            raw_frames,
            cny_frames,
            asset_metadata,
        )
        constant_fx_research_cache = build_research_cache(
            constant_fx_frames,
            end=common_end,
        )
        constant_fx_simulation_cache = build_simulation_cache(
            constant_fx_frames,
            start=start_date,
            end=end_date,
        )
        constant_fx_run = simulate_variant_spec(
            selected["spec"],
            analysis_frames=constant_fx_frames,
            analysis_research_cache=constant_fx_research_cache,
            analysis_simulation_cache=constant_fx_simulation_cache,
        )
        constant_fx_summary = summarize_equity_curve(
            constant_fx_run["equityCurve"],
            include_rolling=False,
        )
        fx_sensitivity.append(
            {
                "candidateId": selected["id"],
                "mode": "constant_fx_local_returns",
                "cagrPct": constant_fx_summary.get("cagrPct"),
                "maxDrawdownPct": constant_fx_summary.get("maxDrawdownPct"),
                "caveat": "美元资产按本币收益运行，用于隔离历史 USD/CNY 路径影响，不是可交易人民币净值。",
            }
        )
    btc_sensitivity = [
        {
            "family": f"{row['spec']['strategy']}_{row['spec']['trendMode']}_vol{row['spec']['volatilityLookback']}",
            "btcCap": row["spec"]["btcCap"],
            "cagrPct": row["summary"].get("cagrPct"),
            "maxDrawdownPct": row["summary"].get("maxDrawdownPct"),
        }
        for row in variants
        if row["spec"]["strategy"] == "trend_risk_budget"
        and row["spec"]["driftThreshold"] == 0.0
    ]
    parameter_matrix = [
        {
            "id": row["id"],
            "trendMode": row["spec"]["trendMode"],
            "volatilityLookback": row["spec"]["volatilityLookback"],
            "driftThreshold": row["spec"]["driftThreshold"],
            "btcCap": row["spec"]["btcCap"],
            "cagrPct": row["summary"].get("cagrPct"),
            "maxDrawdownPct": row["summary"].get("maxDrawdownPct"),
            "eligible": row["gate"]["eligible"],
        }
        for row in variants
        if row["spec"]["strategy"] == "trend_risk_budget"
    ]
    return {
        "params": {
            "start": start_date,
            "end": end_date,
            "baseCurrency": "CNY",
            "feeBps": 5.0,
            "slippageBps": 5.0,
            "cashYieldAnnual": 0.0,
            "inSampleEnd": "2020-12-31",
            "outOfSampleStart": "2021-01-01",
        },
        "assumptions": {
            "trendModes": ["ma10", "mom12", "ma10_and_mom12"],
            "volatilityLookbacks": [60, 120],
            "btcCaps": [0.0, 0.05, 0.10],
            "driftThresholds": [0.0, 0.05],
            "categoryCaps": category_caps,
            "singleAssetCap": 0.25,
            "bondFallback": "511010.SS",
            "fxSymbol": str(config["fxSymbol"]),
        },
        "universe": {
            "assets": assets,
            "aShareAnchor": a_share_anchor,
        },
        "coverage": audit,
        "currencyContribution": _currency_contribution(
            raw_frames,
            cny_frames,
            asset_metadata,
            start_date,
            end_date,
        ),
        "assetCorrelations": asset_correlation_matrix(
            cny_frames,
            start_date,
            end_date,
        ),
        "variants": variants,
        "benchmarks": benchmarks,
        "btcSensitivity": btc_sensitivity,
        "costSensitivity": cost_sensitivity,
        "fxSensitivity": fx_sensitivity,
        "parameterMatrix": parameter_matrix,
        "stability": stability,
        "recommendation": recommendation,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--output")
    parser.add_argument("--report")
    args = parser.parse_args()

    config_path = Path(args.config)
    payload = build_multi_asset_balanced_research(
        config_path=config_path,
        data_dir=Path(args.data_dir),
        start=args.start,
        end=args.end,
    )
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                default=_json_default,
                allow_nan=False,
            ),
            encoding="utf-8",
        )
    if args.report:
        report = Path(args.report)
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(render_markdown_report(payload), encoding="utf-8")
    compact = {
        "output": args.output,
        "report": args.report,
        "coverage": payload["coverage"],
        "recommendation": payload["recommendation"],
        "variantCount": len(payload["variants"]),
    }
    print(
        json.dumps(
            compact,
            ensure_ascii=False,
            indent=2,
            default=_json_default,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
