#!/usr/bin/env python3
"""Research a CNY-denominated multi-asset balanced portfolio."""

from __future__ import annotations

import argparse
import copy
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
        selected_us = set(select_relative_strength(frames, us, as_of, lookback=rs_lookback, top_n=1))
        eligible = [symbol for symbol in eligible if symbol not in us or symbol in selected_us]

    vol_by_symbol = {}
    for symbol in eligible:
        volatility = annualized_volatility(frames[symbol]["Close"], as_of, volatility_lookback)
        if volatility is not None:
            vol_by_symbol[symbol] = volatility
    raw = inverse_volatility_weights(vol_by_symbol)
    caps = dict(category_caps)
    caps["crypto"] = float(btc_cap)
    risk_weights = apply_weight_caps(raw, metadata, caps)

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
        "riskWeightTotal": sum(risk_weights.values()),
        "bondAllocated": bool(bond_eligible),
    }
    return weights, diagnostics


def next_common_trading_date(
    frames: Dict[str, pd.DataFrame],
    symbols: Iterable[str],
    after_date,
) -> Optional[pd.Timestamp]:
    required = [symbol for symbol in symbols if symbol != "__CASH__" and symbol in frames]
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
    common = None
    for symbol in required:
        dates = set(pd.DatetimeIndex(frames[symbol].index)[pd.DatetimeIndex(frames[symbol].index) > cutoff])
        common = dates if common is None else common.intersection(dates)
        if not common:
            return None
    return min(pd.Timestamp(date) for date in common) if common else None


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
    for signal_month in month_ends:
        if signal_month >= last_date:
            continue
        target, diagnostics = target_weight_fn(pd.Timestamp(signal_month))
        target_symbols = {symbol for symbol, weight in target.items() if symbol != "__CASH__" and weight > 0}
        execution_date = next_common_trading_date(
            frames,
            held_symbols | target_symbols,
            signal_month,
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
        equity, stale_symbols = portfolio_value_cny(state, frames, date)
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
    peak_equity = float(frame.iloc[0]["equity"])
    peak_date = pd.Timestamp(frame.index[0])
    drawdown_start = None
    longest_recovery = 0
    max_drawdown = 0.0
    for date, row in frame.iterrows():
        equity = float(row["equity"])
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
    rows = []
    for start_date, start_row in frame.iterrows():
        target = pd.Timestamp(start_date) + pd.DateOffset(years=years)
        available = frame[frame.index >= target]
        if available.empty:
            continue
        end_date = pd.Timestamp(available.index[0])
        window = frame.loc[start_date:end_date]
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


def summarize_equity_curve(curve: List[Dict[str, object]]) -> Dict[str, object]:
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
        }
    start_date = pd.Timestamp(frame.index[0])
    end_date = pd.Timestamp(frame.index[-1])
    history_years = max(0.0, (end_date - start_date).days / 365.25)
    start_equity = float(frame.iloc[0]["equity"])
    end_equity = float(frame.iloc[-1]["equity"])
    total_return = end_equity / start_equity - 1 if start_equity else 0.0
    cagr = (end_equity / start_equity) ** (1 / history_years) - 1 if history_years > 0 and start_equity > 0 else None
    returns = frame["equity"].pct_change(fill_method=None).dropna()
    volatility = float(returns.std(ddof=1) * math.sqrt(252)) if len(returns) > 1 else None
    annual_return = float(returns.mean() * 252) if not returns.empty else None
    sharpe = annual_return / volatility if annual_return is not None and volatility and volatility > 0 else None
    downside = returns[returns < 0]
    downside_vol = float(downside.std(ddof=1) * math.sqrt(252)) if len(downside) > 1 else None
    sortino = annual_return / downside_vol if annual_return is not None and downside_vol and downside_vol > 0 else None
    recovery = drawdown_recovery_stats(curve)
    max_drawdown = recovery["maxDrawdownPct"]
    calmar = (cagr * 100) / max_drawdown if cagr is not None and max_drawdown and max_drawdown > 0 else None
    rolling3 = rolling_window_stats(curve, 3)
    rolling5 = rolling_window_stats(curve, 5)
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
) -> Dict[str, object]:
    principal = sum(float(row.get("amount", 0.0)) for row in contributions)
    profit = float(ending_value) - principal
    return {
        "principal": principal,
        "endingValue": float(ending_value),
        "profit": profit,
        "principalReturnPct": profit / principal * 100 if principal else None,
        "timeWeightedReturnPct": time_weighted_return_pct,
        "moneyWeightedReturnPct": None,
        "contributionCount": len(contributions),
    }


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
    first_dates = frame.groupby(frame.index.to_period("M")).head(1)
    units = 0.0
    contributions = []
    for date, row in first_dates.iterrows():
        nav = float(row["equity"])
        if nav <= 0:
            continue
        units += float(monthly_contribution) / nav
        contributions.append(
            {
                "date": pd.Timestamp(date).date().isoformat(),
                "amount": float(monthly_contribution),
            }
        )
    ending_value = units * float(frame.iloc[-1]["equity"])
    time_weighted = summarize_equity_curve(curve).get("totalReturnPct")
    return summarize_dca(contributions, ending_value, time_weighted)


def simulate_static_allocation_benchmark(
    frames: Dict[str, pd.DataFrame],
    asset_metadata: Dict[str, Dict[str, object]],
    start: Optional[str],
    end: Optional[str],
    fee_bps: float = 5.0,
    slippage_bps: float = 5.0,
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
    )
    result["summary"] = summarize_equity_curve(result["equityCurve"])
    return result


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
    config = load_config(config_path)
    assets = expand_assets(config, config_path.parent)
    frames, missing, fx_frame = load_all_frames(assets, str(config["fxSymbol"]), Path(args.data_dir))
    payload = {
        "coverage": coverage_audit(frames),
        "missingSymbols": missing,
        "fxAvailable": fx_frame is not None,
    }
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
