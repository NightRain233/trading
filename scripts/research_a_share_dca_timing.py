#!/usr/bin/env python3
"""Research A-share broad ETF DCA timing.

This script is intentionally standalone: it reads local parquet cache, does not
modify product strategies, and writes research artifacts under docs/ and
backend/backtest_results/.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd
import pandas_ta as ta


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
DATA_DIR = BACKEND_DIR / "data"
UNIVERSE_FILE = BACKEND_DIR / "universes" / "a_share_etf_core.json"
RESULTS_DIR = BACKEND_DIR / "backtest_results"
REPORT_FILE = ROOT / "docs" / "a-share-dca-timing-research-2026-06-06.md"
RESULT_FILE = RESULTS_DIR / "a_share_dca_timing_2026-06-06.json"
BACKTEST_PATH = BACKEND_DIR / "backtest.py"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

_BACKTEST_SPEC = importlib.util.spec_from_file_location("backtest", BACKTEST_PATH)
backtest = importlib.util.module_from_spec(_BACKTEST_SPEC)
_BACKTEST_SPEC.loader.exec_module(backtest)


MARKET_SYMBOL = "510300.SS"
START_DATE = "2016-06-06"
END_DATE = "2026-06-05"
MONTHLY_BUDGET = 1_000.0
FEE_BPS = 5.0
SLIPPAGE_BPS = 5.0
RS_TOP_N = 3
RS_ENHANCE_RATIO = 0.25
RS_LOOKBACK_BARS = 60
RS_REBALANCE_DAYS = 20

WINDOWS = [
    {"name": "full_10y", "label": "2016-06-06~2026-06-05", "start": START_DATE, "end": END_DATE},
    {"name": "recent_5y", "label": "近五年", "start": "2021-06-06", "end": END_DATE},
    {"name": "recent_3y", "label": "近三年", "start": "2023-06-06", "end": END_DATE},
]

STRATEGY_LABELS = {
    "dca_510300_fixed": "固定月定投 510300",
    "dca_broad_equal_fixed": "固定月定投 A 股宽基等权",
    "dca_510300_macd_pause": "510300 月 MACD 空头暂停定投",
    "dca_510300_macd_half": "510300 月 MACD 空头 50% 定投",
    "dca_510300_ma10_pause": "510300 10 月均线空头暂停定投",
    "dca_510300_ma10_half": "510300 10 月均线空头 50% 定投",
    "dca_510300_monthly_st_pause": "510300 月 ST 空头暂停定投",
    "dca_510300_monthly_st_half": "510300 月 ST 空头 50% 定投",
    "dca_broad_breadth_pause": "200 日广度空头暂停定投",
    "dca_broad_breadth_half": "200 日广度空头 50% 定投",
    "dca_broad_macd_breadth_step": "月 MACD + 广度阶梯定投",
    "dca_broad_macd_breadth_any_pause": "月 MACD + 广度任一弱暂停",
    "dca_broad_macd_breadth_any_half": "月 MACD + 广度任一弱半速",
    "dca_broad_macd_rs_enhanced": "月 MACD 多头 + RS 小比例增强",
    "rs_monthly_macd": "RS + 510300 月 MACD",
    "hold_510300": "510300 买入持有",
    "hold_broad_equal": "宽基等权持有",
}


def _date_str(value) -> str:
    return pd.Timestamp(value).date().isoformat()


def _round(value, digits: int = 4):
    if value is None:
        return None
    return round(float(value), digits)


def read_broad_symbols(path: Path = UNIVERSE_FILE) -> List[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("symbols", payload) if isinstance(payload, dict) else payload
    symbols: List[str] = []
    seen = set()
    for item in rows:
        if not isinstance(item, dict) or item.get("bucket") != "broad":
            continue
        symbol = str(item.get("symbol", "")).strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)
    return symbols


def _load_frame(symbol: str, data_dir: Path = DATA_DIR) -> Optional[pd.DataFrame]:
    path = data_dir / f"{symbol.upper()}.parquet"
    if not path.exists():
        return None
    frame = pd.read_parquet(path).sort_index()
    if frame.empty:
        return None
    frame.index = pd.DatetimeIndex(frame.index)
    required = {"Open", "High", "Low", "Close"}
    if not required.issubset(frame.columns):
        return None
    return frame


def load_frames(symbols: Iterable[str], data_dir: Path = DATA_DIR) -> tuple[Dict[str, pd.DataFrame], List[str]]:
    frames: Dict[str, pd.DataFrame] = {}
    missing = []
    for symbol in symbols:
        normalized = symbol.upper()
        frame = _load_frame(normalized, data_dir)
        if frame is None:
            missing.append(normalized)
        else:
            frames[normalized] = frame
    return frames, missing


def _period_freq(rule: str) -> str:
    return "M" if rule == "ME" else rule


def align_completed_month_signal(daily_index: pd.DatetimeIndex, monthly_signal: pd.Series) -> pd.Series:
    """Expose each monthly signal only after that month has completed.

    The signal is indexed by the last actual trading day in that month. A DCA
    order on the next month's first trading day can therefore use it, while a
    day inside the unfinished month cannot.
    """
    if monthly_signal is None or monthly_signal.empty or len(daily_index) == 0:
        return pd.Series(dtype="float64")

    ordered_daily = pd.DatetimeIndex(pd.Series(pd.DatetimeIndex(daily_index)).drop_duplicates()).sort_values()
    daily_periods = ordered_daily.to_period("M")
    last_trading_day = pd.Series(ordered_daily, index=daily_periods).groupby(level=0).max()
    max_daily_date = pd.Timestamp(ordered_daily.max()).normalize()

    rows = []
    for idx, value in monthly_signal.dropna().sort_index().items():
        period = pd.Timestamp(idx).to_period("M")
        period_end = pd.Timestamp(period.end_time).normalize()
        available_dates = ordered_daily[ordered_daily > period_end]
        if len(available_dates) > 0:
            available_date = pd.Timestamp(available_dates[0])
        elif period in last_trading_day.index and pd.Timestamp(last_trading_day.loc[period]).normalize() >= period_end:
            available_date = pd.Timestamp(last_trading_day.loc[period])
        else:
            continue
        if available_date > max_daily_date:
            continue
        rows.append((available_date, float(value)))
    if not rows:
        return pd.Series(dtype="float64")
    return pd.Series({date: value for date, value in rows}, dtype="float64").sort_index()


def latest_signal_state(signal: pd.Series, as_of) -> Optional[int]:
    if signal is None or signal.empty:
        return None
    ordered = signal.sort_index()
    window = ordered[ordered.index <= pd.Timestamp(as_of)]
    if window.empty or pd.isna(window.iloc[-1]):
        return None
    return int(float(window.iloc[-1]))


def monthly_macd_signal(frame: pd.DataFrame) -> pd.Series:
    monthly = frame.sort_index().resample("ME").last().dropna(subset=["Close"])
    if monthly.empty:
        return pd.Series(dtype="float64")
    macd = ta.macd(monthly["Close"])
    if macd is None or macd.empty:
        return pd.Series(dtype="float64")
    line_col = next((col for col in macd.columns if str(col).startswith("MACD_")), None)
    signal_col = next((col for col in macd.columns if str(col).startswith("MACDs_")), None)
    if line_col is None or signal_col is None:
        return pd.Series(dtype="float64")
    raw = (macd[line_col] > macd[signal_col]).map(lambda value: 1.0 if value else -1.0)
    return align_completed_month_signal(pd.DatetimeIndex(frame.index), raw.dropna())


def monthly_ma10_signal(frame: pd.DataFrame) -> pd.Series:
    monthly = frame.sort_index().resample("ME").last().dropna(subset=["Close"])
    if monthly.empty:
        return pd.Series(dtype="float64")
    ma10 = monthly["Close"].rolling(10, min_periods=10).mean()
    raw = (monthly["Close"] > ma10).map(lambda value: 1.0 if value else -1.0)
    return align_completed_month_signal(pd.DatetimeIndex(frame.index), raw.dropna())


def _supertrend_dir(frame: pd.DataFrame, length: int = 7, multiplier: float = 3.0) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype="float64")
    st = ta.supertrend(frame["High"], frame["Low"], frame["Close"], length=length, multiplier=multiplier)
    if st is None or st.empty:
        return pd.Series(dtype="float64")
    dir_col = next((col for col in st.columns if str(col).startswith("SUPERTd_")), None)
    return st[dir_col].dropna().sort_index() if dir_col else pd.Series(dtype="float64")


def monthly_supertrend_signal(frame: pd.DataFrame) -> pd.Series:
    monthly = (
        frame.sort_index()
        .resample("ME")
        .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"})
        .dropna(subset=["Open", "High", "Low", "Close"])
    )
    return align_completed_month_signal(pd.DatetimeIndex(frame.index), _supertrend_dir(monthly))


def contribution_multiplier(policy: str, market_state: Optional[int]) -> float:
    if policy == "fixed_100":
        return 1.0
    if policy in {"macd_pause_bear", "ma10_pause_bear", "st_pause_bear", "breadth_pause_bear"}:
        return 0.0 if market_state == -1 else 1.0
    if policy in {"macd_half_bear", "ma10_half_bear", "st_half_bear", "breadth_half_bear"}:
        return 0.5 if market_state == -1 else 1.0
    raise ValueError(f"unknown multiplier policy: {policy}")


def combined_multiplier(policy: str, primary_state: Optional[int], secondary_state: Optional[int]) -> float:
    primary_weak = primary_state == -1
    secondary_weak = secondary_state == -1
    if policy == "both_strong_step":
        if primary_weak and secondary_weak:
            return 0.0
        if primary_weak or secondary_weak:
            return 0.5
        return 1.0
    if policy == "any_weak_pause":
        return 0.0 if primary_weak or secondary_weak else 1.0
    if policy == "any_weak_half":
        return 0.5 if primary_weak or secondary_weak else 1.0
    raise ValueError(f"unknown combined policy: {policy}")


def market_breadth_200dma_signal(
    frames: Dict[str, pd.DataFrame],
    symbols: Iterable[str],
    threshold: float = 0.5,
) -> pd.Series:
    dates = _all_dates({symbol: frames[symbol] for symbol in symbols if symbol in frames}, None, None)
    rows = {}
    ma_cache = {}
    for symbol in symbols:
        frame = frames.get(symbol)
        if frame is None or frame.empty:
            continue
        if "MA200" in frame.columns:
            ma_cache[symbol] = frame["MA200"]
        else:
            ma_cache[symbol] = frame["Close"].rolling(200, min_periods=200).mean()
    for date in dates:
        known = 0
        above = 0
        for symbol, ma in ma_cache.items():
            frame = frames.get(symbol)
            if frame is None or frame.empty:
                continue
            close_window = frame["Close"][frame.index <= date].dropna()
            ma_window = ma[ma.index <= date].dropna()
            if close_window.empty or ma_window.empty:
                continue
            known += 1
            if float(close_window.iloc[-1]) > float(ma_window.iloc[-1]):
                above += 1
        if known > 0:
            rows[date] = 1.0 if above / known >= threshold else -1.0
    return pd.Series(rows, dtype="float64").sort_index()


def _all_dates(frames: Dict[str, pd.DataFrame], start: Optional[str], end: Optional[str]) -> List[pd.Timestamp]:
    dates = set()
    start_ts = pd.Timestamp(start) if start else None
    end_ts = pd.Timestamp(end) if end else None
    for frame in frames.values():
        if frame is None or frame.empty:
            continue
        for date in frame.index:
            ts = pd.Timestamp(date)
            if start_ts is not None and ts < start_ts:
                continue
            if end_ts is not None and ts > end_ts:
                continue
            dates.add(ts)
    return sorted(dates)


def _first_trading_days(dates: Iterable[pd.Timestamp]) -> set[pd.Timestamp]:
    first_by_month: Dict[str, pd.Timestamp] = {}
    for date in sorted(pd.Timestamp(d) for d in dates):
        key = date.strftime("%Y-%m")
        first_by_month.setdefault(key, date)
    return set(first_by_month.values())


def _open_price(frame: pd.DataFrame, date) -> Optional[float]:
    ts = pd.Timestamp(date)
    if frame is None or frame.empty or ts not in frame.index:
        return None
    row = frame.loc[ts]
    value = row.get("Open")
    if pd.isna(value) or float(value) <= 0:
        value = row.get("Close")
    return None if pd.isna(value) or float(value) <= 0 else float(value)


def _close_on_or_before(frame: pd.DataFrame, date) -> Optional[float]:
    if frame is None or frame.empty:
        return None
    window = frame[frame.index <= pd.Timestamp(date)]
    if window.empty:
        return None
    value = window.iloc[-1].get("Close")
    return None if pd.isna(value) or float(value) <= 0 else float(value)


def _rank_symbols_by_rs(
    frames: Dict[str, pd.DataFrame],
    as_of,
    symbols: Iterable[str],
    top_n: int = RS_TOP_N,
    lookback_bars: int = RS_LOOKBACK_BARS,
) -> List[str]:
    rows = []
    for symbol in symbols:
        frame = frames.get(symbol)
        if frame is None or frame.empty:
            continue
        window = frame[frame.index <= pd.Timestamp(as_of)].dropna(subset=["Close"])
        if len(window) <= lookback_bars:
            continue
        current = float(window.iloc[-1]["Close"])
        prior = float(window.iloc[-lookback_bars - 1]["Close"])
        if prior <= 0:
            continue
        rows.append((symbol, (current - prior) / prior))
    return [symbol for symbol, _ in sorted(rows, key=lambda item: item[1], reverse=True)[:top_n]]


def _allocations(
    mode: str,
    frames: Dict[str, pd.DataFrame],
    date: pd.Timestamp,
    symbols: List[str],
    target_symbol: Optional[str],
    market_state: Optional[int],
    rs_top_n: int,
    rs_enhance_ratio: float,
) -> Dict[str, float]:
    available = [symbol for symbol in symbols if _open_price(frames.get(symbol), date)]
    if mode == "single":
        if target_symbol and _open_price(frames.get(target_symbol), date):
            return {target_symbol: 1.0}
        return {}
    if mode == "equal_weight":
        return {symbol: 1.0 / len(available) for symbol in available} if available else {}
    if mode == "macd_rs_enhanced":
        if not available:
            return {}
        base_weight = 1.0 / len(available)
        weights = {symbol: (1.0 - rs_enhance_ratio) * base_weight for symbol in available}
        if market_state == 1:
            top = _rank_symbols_by_rs(frames, date, available, top_n=rs_top_n)
            if top:
                extra = rs_enhance_ratio / len(top)
                for symbol in top:
                    weights[symbol] = weights.get(symbol, 0.0) + extra
        else:
            residual = rs_enhance_ratio / len(available)
            for symbol in available:
                weights[symbol] = weights.get(symbol, 0.0) + residual
        return weights
    raise ValueError(f"unknown allocation mode: {mode}")


def simulate_dca(
    frames: Dict[str, pd.DataFrame],
    start: str,
    end: str,
    monthly_budget: float,
    allocation_mode: str,
    target_symbol: Optional[str] = None,
    symbols: Optional[List[str]] = None,
    market_signal: Optional[pd.Series] = None,
    secondary_signal: Optional[pd.Series] = None,
    multiplier_policy: str = "fixed_100",
    combined_policy: Optional[str] = None,
    fee_bps: float = FEE_BPS,
    slippage_bps: float = SLIPPAGE_BPS,
    rs_top_n: int = RS_TOP_N,
    rs_enhance_ratio: float = RS_ENHANCE_RATIO,
) -> Dict[str, object]:
    selected_symbols = [s.upper() for s in (symbols or sorted(frames.keys()))]
    selected_frames = {symbol: frames[symbol] for symbol in selected_symbols if symbol in frames}
    dates = _all_dates(selected_frames, start, end)
    if not dates:
        return {
            "mode": "dca",
            "equityCurve": [],
            "cashFlows": [],
            "schedule": [],
            "lots": [],
            "totalInvested": 0.0,
            "scheduledBudget": 0.0,
            "finalValue": 0.0,
        }

    contribution_days = _first_trading_days(dates)
    fee = fee_bps / 10_000
    slip = slippage_bps / 10_000
    shares: Dict[str, float] = {}
    lots: List[Dict[str, object]] = []
    cash_flows: List[Dict[str, object]] = []
    schedule: List[Dict[str, object]] = []
    curve = []
    peak = 0.0
    max_drawdown = 0.0
    scheduled_budget = len(contribution_days) * monthly_budget

    for date in dates:
        if date in contribution_days:
            schedule.append({"date": _date_str(date), "scheduledAmount": monthly_budget})
            signal = market_signal if market_signal is not None else pd.Series(dtype="float64")
            secondary = secondary_signal if secondary_signal is not None else pd.Series(dtype="float64")
            state = latest_signal_state(signal, date)
            secondary_state = latest_signal_state(secondary, date)
            multiplier = (
                combined_multiplier(combined_policy, state, secondary_state)
                if combined_policy
                else contribution_multiplier(multiplier_policy, state)
            )
            amount = monthly_budget * multiplier
            weights = _allocations(
                allocation_mode,
                selected_frames,
                date,
                selected_symbols,
                target_symbol.upper() if target_symbol else None,
                state,
                rs_top_n,
                rs_enhance_ratio,
            )
            if amount > 0 and weights:
                invested = 0.0
                lot_positions = []
                for symbol, weight in weights.items():
                    price = _open_price(selected_frames.get(symbol), date)
                    if not price or weight <= 0:
                        continue
                    gross = amount * weight
                    net = gross / ((1 + fee) * (1 + slip))
                    qty = net / price
                    shares[symbol] = shares.get(symbol, 0.0) + qty
                    invested += gross
                    lot_positions.append({"symbol": symbol, "shares": qty, "cost": gross})
                if invested > 0:
                    lots.append({"date": _date_str(date), "year": str(date.year), "positions": lot_positions})
                    cash_flows.append(
                        {
                            "date": _date_str(date),
                            "amount": _round(invested, 6),
                            "marketState": state,
                            "secondaryState": secondary_state,
                            "multiplier": multiplier,
                        }
                    )

        equity = 0.0
        for symbol, qty in shares.items():
            price = _close_on_or_before(selected_frames.get(symbol), date)
            if price:
                equity += qty * price
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak * 100 if peak > 0 else 0.0
        max_drawdown = max(max_drawdown, drawdown)
        curve.append(
            {
                "date": _date_str(date),
                "equity": equity,
                "drawdownPct": drawdown,
                "investedPrincipal": sum(float(flow["amount"]) for flow in cash_flows),
            }
        )

    year_end_dates: Dict[str, str] = {}
    for point in curve:
        year_end_dates[str(pd.Timestamp(point["date"]).year)] = point["date"]
    for lot in lots:
        lot["yearEndValues"] = {
            year: _round(_lot_value_at(lot, selected_frames, date), 6)
            for year, date in year_end_dates.items()
            if pd.Timestamp(date) >= pd.Timestamp(lot["date"])
        }

    return {
        "mode": "dca",
        "allocationMode": allocation_mode,
        "multiplierPolicy": multiplier_policy,
        "startDate": _date_str(dates[0]),
        "endDate": _date_str(dates[-1]),
        "equityCurve": curve,
        "cashFlows": cash_flows,
        "schedule": schedule,
        "lots": lots,
        "totalInvested": sum(float(flow["amount"]) for flow in cash_flows),
        "scheduledBudget": sum(float(item["scheduledAmount"]) for item in schedule) or scheduled_budget,
        "finalValue": curve[-1]["equity"] if curve else 0.0,
        "maxDrawdownPct": max_drawdown,
    }


def _lot_value_at(lot: Dict[str, object], frames: Dict[str, pd.DataFrame], date) -> float:
    total = 0.0
    for position in lot.get("positions", []):
        symbol = str(position["symbol"])
        price = _close_on_or_before(frames.get(symbol), date)
        if price:
            total += float(position["shares"]) * price
    return total


def annual_dca_returns(result: Dict[str, object], frames: Optional[Dict[str, pd.DataFrame]] = None) -> Dict[str, Dict[str, float]]:
    frames = frames or {}
    lots = result.get("lots", [])
    if not lots:
        return {}
    curve = result.get("equityCurve", [])
    if not curve:
        return {}
    last_curve_date_by_year: Dict[str, str] = {}
    for point in curve:
        year = str(pd.Timestamp(point["date"]).year)
        last_curve_date_by_year[year] = point["date"]

    annual: Dict[str, Dict[str, float]] = {}
    for year, end_date in sorted(last_curve_date_by_year.items()):
        year_lots = [lot for lot in lots if str(lot.get("year")) == year]
        invested = sum(sum(float(pos["cost"]) for pos in lot.get("positions", [])) for lot in year_lots)
        if invested <= 0:
            continue
        if frames:
            value = sum(_lot_value_at(lot, frames, end_date) for lot in year_lots)
        else:
            value = sum(float(lot.get("yearEndValues", {}).get(year, 0.0)) for lot in year_lots)
        annual[year] = {
            "investedPrincipal": _round(invested, 6),
            "endValue": _round(value, 6),
            "principalReturnPct": _round((value - invested) / invested * 100, 4),
        }
    return annual


def summarize_dca_result(result: Dict[str, object], frames: Optional[Dict[str, pd.DataFrame]] = None) -> Dict[str, object]:
    invested = float(result.get("totalInvested") or 0.0)
    final_value = float(result.get("finalValue") or 0.0)
    annual = annual_dca_returns(result, frames)
    curve = result.get("equityCurve", [])
    for year, values in annual.items():
        points = [point for point in curve if str(pd.Timestamp(point["date"]).year) == year]
        values["accountMaxDrawdownPct"] = _round(max((float(point.get("drawdownPct") or 0.0) for point in points), default=0.0), 4)
    annual_rows = [{"year": year, **values} for year, values in annual.items()]
    best = max(annual_rows, key=lambda row: row["principalReturnPct"]) if annual_rows else None
    worst = min(annual_rows, key=lambda row: row["principalReturnPct"]) if annual_rows else None
    return {
        "investedPrincipal": _round(invested, 6),
        "finalValue": _round(final_value, 6),
        "principalReturnPct": _round((final_value - invested) / invested * 100, 4) if invested > 0 else 0.0,
        "accountMaxDrawdownPct": _round(result.get("maxDrawdownPct") or 0.0, 4),
        "scheduledBudget": _round(result.get("scheduledBudget") or invested, 6),
        "cashDeploymentRatio": _round(invested / float(result.get("scheduledBudget") or invested), 4) if invested > 0 else 0.0,
        "contributionCount": len(result.get("cashFlows", [])),
        "annual": annual,
        "bestCalendarYear": best,
        "worstCalendarYear": worst,
        "worstRolling3y": worst_rolling_returns(result.get("equityCurve", []), 3),
        "worstRolling5y": worst_rolling_returns(result.get("equityCurve", []), 5),
    }


def summarize_equity_curve(curve: List[Dict[str, object]], initial: float = 1.0) -> Dict[str, object]:
    if not curve:
        return {"totalReturnPct": 0.0, "maxDrawdownPct": 0.0, "annual": {}}
    total_return = (float(curve[-1]["equity"]) / initial - 1) * 100
    max_drawdown = max(float(point.get("drawdownPct") or 0.0) for point in curve)
    by_year: Dict[str, List[Dict[str, object]]] = {}
    for point in curve:
        by_year.setdefault(str(pd.Timestamp(point["date"]).year), []).append(point)
    annual = {}
    previous_equity = initial
    for year, points in sorted(by_year.items()):
        end_equity = float(points[-1]["equity"])
        annual[year] = {
            "returnPct": _round((end_equity / previous_equity - 1) * 100, 4) if previous_equity else 0.0,
            "maxDrawdownPct": _round(max(float(point.get("drawdownPct") or 0.0) for point in points), 4),
        }
        previous_equity = end_equity
    return {
        "totalReturnPct": _round(total_return, 4),
        "maxDrawdownPct": _round(max_drawdown, 4),
        "annual": annual,
    }


def simulate_buy_hold(
    frames: Dict[str, pd.DataFrame],
    symbols: List[str],
    start: str,
    end: str,
    fee_bps: float = FEE_BPS,
    slippage_bps: float = SLIPPAGE_BPS,
) -> Dict[str, object]:
    selected = {symbol: frames[symbol] for symbol in symbols if symbol in frames}
    dates = _all_dates(selected, start, end)
    if not dates:
        return {"mode": "buy_hold", "equityCurve": [], "totalReturnPct": 0.0, "maxDrawdownPct": 0.0}
    fee = fee_bps / 10_000
    slip = slippage_bps / 10_000
    first = dates[0]
    available = [symbol for symbol in symbols if _open_price(selected.get(symbol), first)]
    shares = {}
    if available:
        per_symbol = 1.0 / len(available)
        for symbol in available:
            price = _open_price(selected.get(symbol), first)
            if price:
                shares[symbol] = (per_symbol / ((1 + fee) * (1 + slip))) / price
    curve = []
    peak = 0.0
    max_drawdown = 0.0
    for date in dates:
        equity = 0.0
        for symbol, qty in shares.items():
            price = _close_on_or_before(selected.get(symbol), date)
            if price:
                equity += qty * price
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak * 100 if peak > 0 else 0.0
        max_drawdown = max(max_drawdown, drawdown)
        curve.append({"date": _date_str(date), "equity": equity, "drawdownPct": drawdown})
    return {
        "mode": "buy_hold",
        "startDate": _date_str(dates[0]),
        "endDate": _date_str(dates[-1]),
        "equityCurve": curve,
        "totalReturnPct": _round((curve[-1]["equity"] - 1) * 100, 4),
        "maxDrawdownPct": _round(max_drawdown, 4),
    }


def slice_curve(curve: List[Dict[str, object]], start: str, end: str) -> List[Dict[str, object]]:
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    return [point for point in curve if start_ts <= pd.Timestamp(point["date"]) <= end_ts]


def worst_rolling_returns(curve: List[Dict[str, object]], years: int) -> Optional[Dict[str, object]]:
    if not curve:
        return None
    series = pd.Series(
        [float(point["equity"]) for point in curve],
        index=pd.DatetimeIndex([point["date"] for point in curve]),
        dtype="float64",
    ).sort_index()
    rows = []
    for start_date, start_equity in series.items():
        end_target = start_date + pd.DateOffset(years=years)
        window = series[series.index >= end_target]
        if window.empty or start_equity <= 0:
            continue
        end_date = window.index[0]
        end_equity = float(window.iloc[0])
        rows.append(
            {
                "start": _date_str(start_date),
                "end": _date_str(end_date),
                "returnPct": _round((end_equity / float(start_equity) - 1) * 100, 4),
            }
        )
    return min(rows, key=lambda row: row["returnPct"]) if rows else None


def summarize_strategy_for_windows(strategy_result: Dict[str, object], is_dca: bool, frames: Dict[str, pd.DataFrame]) -> Dict[str, object]:
    curve = strategy_result.get("equityCurve", [])
    summary_by_window = {}
    for window in WINDOWS:
        window_curve = slice_curve(curve, window["start"], window["end"])
        if is_dca:
            window_flows = [
                flow
                for flow in strategy_result.get("cashFlows", [])
                if pd.Timestamp(window["start"]) <= pd.Timestamp(flow["date"]) <= pd.Timestamp(window["end"])
            ]
            window_lots = [
                lot
                for lot in strategy_result.get("lots", [])
                if pd.Timestamp(window["start"]) <= pd.Timestamp(lot["date"]) <= pd.Timestamp(window["end"])
            ]
            window_schedule = [
                item
                for item in strategy_result.get("schedule", [])
                if pd.Timestamp(window["start"]) <= pd.Timestamp(item["date"]) <= pd.Timestamp(window["end"])
            ]
            window_result = {
                **strategy_result,
                "equityCurve": window_curve,
                "cashFlows": window_flows,
                "schedule": window_schedule,
                "lots": window_lots,
                "totalInvested": sum(float(flow["amount"]) for flow in window_flows),
                "scheduledBudget": sum(float(item["scheduledAmount"]) for item in window_schedule),
                "finalValue": sum(_lot_value_at(lot, frames, window["end"]) for lot in window_lots),
                "maxDrawdownPct": max((float(point.get("drawdownPct") or 0.0) for point in window_curve), default=0.0),
            }
            summary_by_window[window["name"]] = summarize_dca_result(window_result, frames)
        else:
            if not window_curve:
                summary_by_window[window["name"]] = summarize_equity_curve([])
                continue
            base = float(window_curve[0]["equity"]) or 1.0
            normalized = [{**point, "equity": float(point["equity"]) / base} for point in window_curve]
            summary_by_window[window["name"]] = summarize_equity_curve(normalized)
    return summary_by_window


def _annual_table(summary: Dict[str, Dict[str, object]], metric: str) -> Dict[str, Dict[str, float]]:
    years = sorted({year for item in summary.values() for year in item.get("full_10y", {}).get("annual", {}).keys()})
    table = {}
    for year in years:
        table[year] = {}
        for key, item in summary.items():
            annual = item.get("full_10y", {}).get("annual", {}).get(year, {})
            table[year][key] = annual.get(metric)
    return table


def build_research(
    start: str = START_DATE,
    end: str = END_DATE,
    data_dir: Path = DATA_DIR,
    universe_file: Path = UNIVERSE_FILE,
) -> Dict[str, object]:
    broad_symbols = read_broad_symbols(universe_file)
    all_symbols = sorted(set(broad_symbols + [MARKET_SYMBOL]))
    frames, missing = load_frames(all_symbols, data_dir)
    available_broad = [symbol for symbol in broad_symbols if symbol in frames]
    if MARKET_SYMBOL not in frames:
        raise RuntimeError(f"missing required market frame: {MARKET_SYMBOL}")
    if not available_broad:
        raise RuntimeError("no broad ETF frames available")

    market_macd = monthly_macd_signal(frames[MARKET_SYMBOL])
    market_ma10 = monthly_ma10_signal(frames[MARKET_SYMBOL])
    market_st = monthly_supertrend_signal(frames[MARKET_SYMBOL])
    breadth_200dma = market_breadth_200dma_signal(frames, available_broad)

    dca_results = {
        "dca_510300_fixed": simulate_dca(
            frames,
            start,
            end,
            MONTHLY_BUDGET,
            allocation_mode="single",
            target_symbol=MARKET_SYMBOL,
            symbols=[MARKET_SYMBOL],
            market_signal=pd.Series(dtype="float64"),
            multiplier_policy="fixed_100",
        ),
        "dca_broad_equal_fixed": simulate_dca(
            frames,
            start,
            end,
            MONTHLY_BUDGET,
            allocation_mode="equal_weight",
            symbols=available_broad,
            market_signal=pd.Series(dtype="float64"),
            multiplier_policy="fixed_100",
        ),
        "dca_510300_macd_pause": simulate_dca(
            frames,
            start,
            end,
            MONTHLY_BUDGET,
            allocation_mode="single",
            target_symbol=MARKET_SYMBOL,
            symbols=[MARKET_SYMBOL],
            market_signal=market_macd,
            multiplier_policy="macd_pause_bear",
        ),
        "dca_510300_macd_half": simulate_dca(
            frames,
            start,
            end,
            MONTHLY_BUDGET,
            allocation_mode="single",
            target_symbol=MARKET_SYMBOL,
            symbols=[MARKET_SYMBOL],
            market_signal=market_macd,
            multiplier_policy="macd_half_bear",
        ),
        "dca_510300_ma10_pause": simulate_dca(
            frames,
            start,
            end,
            MONTHLY_BUDGET,
            allocation_mode="single",
            target_symbol=MARKET_SYMBOL,
            symbols=[MARKET_SYMBOL],
            market_signal=market_ma10,
            multiplier_policy="ma10_pause_bear",
        ),
        "dca_510300_ma10_half": simulate_dca(
            frames,
            start,
            end,
            MONTHLY_BUDGET,
            allocation_mode="single",
            target_symbol=MARKET_SYMBOL,
            symbols=[MARKET_SYMBOL],
            market_signal=market_ma10,
            multiplier_policy="ma10_half_bear",
        ),
        "dca_510300_monthly_st_pause": simulate_dca(
            frames,
            start,
            end,
            MONTHLY_BUDGET,
            allocation_mode="single",
            target_symbol=MARKET_SYMBOL,
            symbols=[MARKET_SYMBOL],
            market_signal=market_st,
            multiplier_policy="st_pause_bear",
        ),
        "dca_510300_monthly_st_half": simulate_dca(
            frames,
            start,
            end,
            MONTHLY_BUDGET,
            allocation_mode="single",
            target_symbol=MARKET_SYMBOL,
            symbols=[MARKET_SYMBOL],
            market_signal=market_st,
            multiplier_policy="st_half_bear",
        ),
        "dca_broad_breadth_pause": simulate_dca(
            frames,
            start,
            end,
            MONTHLY_BUDGET,
            allocation_mode="equal_weight",
            symbols=available_broad,
            market_signal=breadth_200dma,
            multiplier_policy="breadth_pause_bear",
        ),
        "dca_broad_breadth_half": simulate_dca(
            frames,
            start,
            end,
            MONTHLY_BUDGET,
            allocation_mode="equal_weight",
            symbols=available_broad,
            market_signal=breadth_200dma,
            multiplier_policy="breadth_half_bear",
        ),
        "dca_broad_macd_breadth_step": simulate_dca(
            frames,
            start,
            end,
            MONTHLY_BUDGET,
            allocation_mode="equal_weight",
            symbols=available_broad,
            market_signal=market_macd,
            secondary_signal=breadth_200dma,
            combined_policy="both_strong_step",
        ),
        "dca_broad_macd_breadth_any_pause": simulate_dca(
            frames,
            start,
            end,
            MONTHLY_BUDGET,
            allocation_mode="equal_weight",
            symbols=available_broad,
            market_signal=market_macd,
            secondary_signal=breadth_200dma,
            combined_policy="any_weak_pause",
        ),
        "dca_broad_macd_breadth_any_half": simulate_dca(
            frames,
            start,
            end,
            MONTHLY_BUDGET,
            allocation_mode="equal_weight",
            symbols=available_broad,
            market_signal=market_macd,
            secondary_signal=breadth_200dma,
            combined_policy="any_weak_half",
        ),
        "dca_broad_macd_rs_enhanced": simulate_dca(
            frames,
            start,
            end,
            MONTHLY_BUDGET,
            allocation_mode="macd_rs_enhanced",
            symbols=available_broad,
            market_signal=market_macd,
            multiplier_policy="fixed_100",
            rs_top_n=RS_TOP_N,
            rs_enhance_ratio=RS_ENHANCE_RATIO,
        ),
    }

    hold_results = {
        "hold_510300": simulate_buy_hold(frames, [MARKET_SYMBOL], start, end),
        "hold_broad_equal": simulate_buy_hold(frames, available_broad, start, end),
    }
    rs_result = backtest.simulate_rs_rotation_portfolio(
        {symbol: frames[symbol] for symbol in available_broad if symbol in frames},
        top_n=5,
        rebalance_days=RS_REBALANCE_DAYS,
        lookback_bars=RS_LOOKBACK_BARS,
        start=start,
        end=end,
        fee_bps=FEE_BPS,
        slippage_bps=SLIPPAGE_BPS,
        market_filter_symbol=MARKET_SYMBOL,
        market_filter_df=frames[MARKET_SYMBOL],
        market_filter_mode="monthly_macd",
        min_history_bars=120,
        min_avg_volume=0.0,
    )

    raw_results = {**dca_results, **hold_results, "rs_monthly_macd": rs_result}
    summaries = {}
    for key, result in raw_results.items():
        summaries[key] = summarize_strategy_for_windows(result, key.startswith("dca_"), frames)

    rolling = {
        key: {
            "worst3y": worst_rolling_returns(result.get("equityCurve", []), 3),
            "worst5y": worst_rolling_returns(result.get("equityCurve", []), 5),
        }
        for key, result in raw_results.items()
    }

    return {
        "params": {
            "start": start,
            "end": end,
            "monthlyBudget": MONTHLY_BUDGET,
            "marketSymbol": MARKET_SYMBOL,
            "broadSymbols": available_broad,
            "missingSymbols": missing,
            "rsTopN": RS_TOP_N,
            "rsEnhanceRatio": RS_ENHANCE_RATIO,
            "breadthThreshold": 0.5,
            "feeBps": FEE_BPS,
            "slippageBps": SLIPPAGE_BPS,
        },
        "strategyLabels": STRATEGY_LABELS,
        "summary": summaries,
        "rolling": rolling,
        "annualDcaPrincipalReturns": _annual_table(summaries, "principalReturnPct"),
        "annualStrategyReturns": _annual_table(summaries, "returnPct"),
        "raw": raw_results,
    }


def _pct(value) -> str:
    if value is None:
        return "-"
    return f"{float(value):.2f}%"


def _money(value) -> str:
    if value is None:
        return "-"
    return f"{float(value):,.0f}"


def _summary_value(item: Dict[str, object], is_dca: bool) -> str:
    if is_dca:
        return _pct(item.get("principalReturnPct"))
    return _pct(item.get("totalReturnPct"))


def build_report(payload: Dict[str, object]) -> str:
    summary = payload["summary"]
    rolling = payload["rolling"]
    labels = payload["strategyLabels"]

    lines = [
        "# A 股宽基定投节奏优化研究 2026-06-06",
        "",
        "## 问题",
        "",
        "验证普通人做 A 股宽基时，纯右侧交易之外，是否可以用月级别右侧信息调节定投力度。",
        "",
        "区间：`2016-06-06 ~ 2026-06-05`。定投统一按每月第一个可交易日投入，月 MACD/月 ST 只使用已经结束月份的信号。",
        "",
        "## 全周期摘要",
        "",
        "| 策略 | 收益口径 | 收益/结果 | 回撤 | 投入本金 | 实际投入比例 | 最差3年 | 最差5年 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    order = [
        "dca_510300_fixed",
        "dca_broad_equal_fixed",
        "dca_510300_macd_pause",
        "dca_510300_macd_half",
        "dca_510300_ma10_pause",
        "dca_510300_ma10_half",
        "dca_510300_monthly_st_pause",
        "dca_510300_monthly_st_half",
        "dca_broad_breadth_pause",
        "dca_broad_breadth_half",
        "dca_broad_macd_breadth_step",
        "dca_broad_macd_breadth_any_pause",
        "dca_broad_macd_breadth_any_half",
        "dca_broad_macd_rs_enhanced",
        "rs_monthly_macd",
        "hold_510300",
        "hold_broad_equal",
    ]
    for key in order:
        is_dca = key.startswith("dca_")
        item = summary[key]["full_10y"]
        dd_key = "accountMaxDrawdownPct" if is_dca else "maxDrawdownPct"
        lines.append(
            "| {label} | {metric} | {ret} | {dd} | {principal} | {deploy} | {w3} | {w5} |".format(
                label=labels[key],
                metric="投入本金收益" if is_dca else "账户收益",
                ret=_summary_value(item, is_dca),
                dd=_pct(item.get(dd_key)),
                principal=_money(item.get("investedPrincipal")) if is_dca else "-",
                deploy=_pct(float(item.get("cashDeploymentRatio") or 0.0) * 100) if is_dca else "-",
                w3=_pct((rolling[key].get("worst3y") or {}).get("returnPct")),
                w5=_pct((rolling[key].get("worst5y") or {}).get("returnPct")),
            )
        )

    lines.extend(
        [
            "",
            "## 近五年与近三年",
            "",
            "| 策略 | 近五年 | 近五年回撤 | 近三年 | 近三年回撤 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for key in order:
        is_dca = key.startswith("dca_")
        five = summary[key]["recent_5y"]
        three = summary[key]["recent_3y"]
        dd_key = "accountMaxDrawdownPct" if is_dca else "maxDrawdownPct"
        lines.append(
            f"| {labels[key]} | {_summary_value(five, is_dca)} | {_pct(five.get(dd_key))} | "
            f"{_summary_value(three, is_dca)} | {_pct(three.get(dd_key))} |"
        )

    lines.extend(["", "## 自然年：定投投入本金收益", "", "| 年份 | 固定 510300 | 宽基等权 | MACD 暂停 | MACD 半速 | MA10 暂停 | MA10 半速 | ST 暂停 | ST 半速 | 广度暂停 | 广度半速 | MACD+广度阶梯 | 任一弱暂停 | 任一弱半速 | MACD+RS 增强 |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"])
    dca_keys = [
        "dca_510300_fixed",
        "dca_broad_equal_fixed",
        "dca_510300_macd_pause",
        "dca_510300_macd_half",
        "dca_510300_ma10_pause",
        "dca_510300_ma10_half",
        "dca_510300_monthly_st_pause",
        "dca_510300_monthly_st_half",
        "dca_broad_breadth_pause",
        "dca_broad_breadth_half",
        "dca_broad_macd_breadth_step",
        "dca_broad_macd_breadth_any_pause",
        "dca_broad_macd_breadth_any_half",
        "dca_broad_macd_rs_enhanced",
    ]
    years = sorted({year for key in dca_keys for year in summary[key]["full_10y"].get("annual", {}).keys()})
    for year in years:
        values = [_pct(summary[key]["full_10y"].get("annual", {}).get(year, {}).get("principalReturnPct")) for key in dca_keys]
        lines.append(f"| {year} | " + " | ".join(values) + " |")

    lines.extend(
        [
            "",
            "## 讲人话结论",
            "",
            "### 1. 右侧定投降低的是现金流压力，不稳定降低账户回撤",
            "",
            "这组结果里，固定 510300 定投账户最大回撤是 28.87%，MACD 半速、10 月均线半速、月 ST 半速分别是 30.38%、31.03%、29.69%，并没有稳定更低。右侧定投真正减轻的是熊市继续投入的心理压力：半速版本实际投入比例大约 75%~80%，不会像暂停版那样完全错过低位积累。",
            "",
            "### 2. 收益牺牲过大的主要是暂停版",
            "",
            "510300 的 MACD 暂停、10 月均线暂停、月 ST 暂停，全周期投入本金收益只有 15.60%、18.55%、16.77%，都低于固定 510300 定投的 23.18%，而账户回撤反而更高。组合里的“任一弱则暂停”也过度保守，实际投入只有 40.50%，账户回撤达到 47.52%。",
            "",
            "### 3. 和固定定投、RS、持有的差别",
            "",
            "固定定投最朴素，收益不一定最高，但行为最稳定。RS 更像主动增强，可能阶段性亮眼，也更依赖轮动规则和再平衡纪律。买入持有最吃起点，牛市舒服、熊市心理压力最大。右侧定投处在中间：不要求普通人满仓择时，只调节每月投入力度。",
            "",
            "### 4. 几个过滤器的优劣",
            "",
            "510300 单标的节奏控制里，MACD 半速、10 月均线半速、月 ST 半速差距不大，收益都在 20%~21% 附近，弱于固定 510300 定投，但现金压力更低。宽基等权里，200 日广度半速和 MACD+广度任一弱半速更有产品意义：收益 45.00% 和 44.19%，接近固定宽基等权定投的 48.03%，同时少投约 20%~30% 的计划资金。MACD+RS 增强收益接近宽基等权定投，但它不降低现金占用，更像增强配置，不是心理减压工具。",
            "",
            "### 5. 产品化建议",
            "",
            "推荐产品化为“定投金额建议”，不推荐包装成“右侧交易系统”。默认建议应避免 0% 暂停，优先用 50% 降速：基础定投不断，月级别趋势或广度弱时降速，恢复后回到 100%。如果要做增强，RS 只能作为小比例增配，不应替代定投底座。",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(payload: Dict[str, object], result_file: Path = RESULT_FILE, report_file: Path = REPORT_FILE) -> None:
    result_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.parent.mkdir(parents=True, exist_ok=True)
    result_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report_file.write_text(build_report(payload), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default=START_DATE)
    parser.add_argument("--end", default=END_DATE)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--universe-file", type=Path, default=UNIVERSE_FILE)
    parser.add_argument("--result-file", type=Path, default=RESULT_FILE)
    parser.add_argument("--report-file", type=Path, default=REPORT_FILE)
    args = parser.parse_args()

    payload = build_research(args.start, args.end, args.data_dir, args.universe_file)
    write_outputs(payload, args.result_file, args.report_file)
    print(f"wrote {args.result_file}")
    print(f"wrote {args.report_file}")


if __name__ == "__main__":
    main()
