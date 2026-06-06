#!/usr/bin/env python3
"""Research A-share theme ETF ST portfolios with monthly filters.

Offline-only research script. It reads local parquet cache, keeps the product
strategy untouched, and writes a JSON payload plus a markdown report.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
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
REPORT_FILE = ROOT / "docs" / "a-share-theme-etf-st-monthly-filters-2026-06-06.md"
BACKTEST_PATH = BACKEND_DIR / "backtest.py"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

_BACKTEST_SPEC = importlib.util.spec_from_file_location("backtest", BACKTEST_PATH)
backtest = importlib.util.module_from_spec(_BACKTEST_SPEC)
_BACKTEST_SPEC.loader.exec_module(backtest)


ST_LENGTH = 7
ST_MULTIPLIER = 3.0
FEE_BPS = 5.0
SLIPPAGE_BPS = 5.0
RS_TOP_N = 5
RS_REBALANCE_DAYS = 20
RS_LOOKBACK_BARS = 60
MIN_AVG_VOLUME = 1e8
VOLUME_LOOKBACK = 60
MARKET_SYMBOL = "510300.SS"

STRATEGIES = [
    "rs_monthly_macd_baseline",
    "weekly_daily_st_equal_weight",
    "market_monthly_macd_weekly_daily_st",
    "market_monthly_st_weekly_daily_st",
    "symbol_monthly_st_weekly_daily_st",
]

STRATEGY_LABELS = {
    "rs_monthly_macd_baseline": "RS 轮动 + 510300 月 MACD",
    "weekly_daily_st_equal_weight": "原始周线+日线 ST 等权",
    "market_monthly_macd_weekly_daily_st": "510300 月 MACD + 周/日 ST",
    "market_monthly_st_weekly_daily_st": "510300 月 ST + 周/日 ST",
    "symbol_monthly_st_weekly_daily_st": "标的月 ST + 周/日 ST",
}

WINDOWS = [
    {"name": "full_2015_2026", "label": "2015-2026 全周期", "start": "2015-01-01", "end": "2026-06-05"},
    {"name": "past_10y", "label": "过去十年", "start": "2016-06-06", "end": "2026-06-05"},
    {"name": "recent_5y", "label": "近五年", "start": "2021-06-06", "end": "2026-06-05"},
    {"name": "recent_3y", "label": "近三年", "start": "2023-06-06", "end": "2026-06-05"},
]


def _date_str(value) -> str:
    return pd.Timestamp(value).date().isoformat()


def _period_freq(rule: str) -> str:
    return "M" if rule == "ME" else rule


def _read_universe_rows(path: Path = UNIVERSE_FILE) -> List[Dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_symbols = payload.get("symbols", payload) if isinstance(payload, dict) else payload
    rows: List[Dict[str, str]] = []
    seen = set()
    for item in raw_symbols:
        symbol = item.get("symbol") if isinstance(item, dict) else item
        if not isinstance(symbol, str):
            continue
        normalized = symbol.strip().upper()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        rows.append(
            {
                "symbol": normalized,
                "name": str(item.get("name", "")) if isinstance(item, dict) else "",
                "bucket": str(item.get("bucket", "")) if isinstance(item, dict) else "",
            }
        )
    return rows


def build_static_universes(path: Path = UNIVERSE_FILE) -> Dict[str, List[str]]:
    rows = _read_universe_rows(path)
    broad = [
        row["symbol"]
        for row in rows
        if row["bucket"] == "broad" and row["symbol"] not in {"159552.SZ", "588080.SS"}
    ]
    core = [row["symbol"] for row in rows]
    return {
        "a_share_broad": broad,
        "a_share_core_current": core,
    }


def scan_local_a_share_etf_symbols(data_dir: Path = DATA_DIR) -> List[str]:
    pattern = re.compile(r"^(15|51|56|58)\d{4}\.(SS|SZ)\.parquet$")
    symbols = []
    for path in Path(data_dir).glob("*.parquet"):
        if pattern.match(path.name):
            symbols.append(path.name.removesuffix(".parquet").upper())
    return sorted(set(symbols))


def build_universes(data_dir: Path = DATA_DIR, universe_file: Path = UNIVERSE_FILE) -> Dict[str, List[str]]:
    universes = build_static_universes(universe_file)
    universes["a_share_all_local_etf"] = scan_local_a_share_etf_symbols(data_dir)
    return universes


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
    missing: List[str] = []
    for symbol in symbols:
        normalized = symbol.upper()
        frame = _load_frame(normalized, data_dir)
        if frame is None:
            missing.append(normalized)
        else:
            frames[normalized] = frame
    return frames, missing


def _resample_ohlcv(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    aggregations = {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
    if "Volume" in frame.columns:
        aggregations["Volume"] = "sum"
    return frame.sort_index().resample(rule).agg(aggregations).dropna(subset=["Open", "High", "Low", "Close"])


def _supertrend_dir(
    frame: pd.DataFrame,
    st_length: int = ST_LENGTH,
    st_multiplier: float = ST_MULTIPLIER,
) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype="float64")
    source = frame.sort_index()
    st = ta.supertrend(
        source["High"],
        source["Low"],
        source["Close"],
        length=st_length,
        multiplier=st_multiplier,
    )
    if st is None or st.empty:
        return pd.Series(dtype="float64")
    dir_col = next((column for column in st.columns if str(column).startswith("SUPERTd_")), None)
    if dir_col is None:
        return pd.Series(dtype="float64")
    return st[dir_col].dropna().sort_index()


def align_completed_period_signal(
    daily_index: pd.DatetimeIndex,
    period_signal: pd.Series,
    rule: str,
) -> pd.Series:
    """Index period signals by the last actual trading day in that period.

    A weekly signal ending Friday is available after Friday close. A monthly
    signal is available after the last cached trading day of that month. The
    simulator then uses this signal on the next trading day's open.
    """
    if period_signal is None or period_signal.empty or len(daily_index) == 0:
        return pd.Series(dtype="float64")

    ordered_daily = pd.DatetimeIndex(pd.Series(pd.DatetimeIndex(daily_index)).drop_duplicates()).sort_values()
    daily_periods = ordered_daily.to_period(_period_freq(rule))
    availability = pd.Series(ordered_daily, index=daily_periods).groupby(level=0).max()
    max_daily_date = pd.Timestamp(ordered_daily.max()).normalize()

    rows = []
    for idx, value in period_signal.dropna().sort_index().items():
        period = pd.Timestamp(idx).to_period(_period_freq(rule))
        if period not in availability.index:
            continue
        period_end = pd.Timestamp(period.end_time).normalize()
        if period_end > max_daily_date:
            continue
        rows.append((pd.Timestamp(availability.loc[period]), float(value)))
    if not rows:
        return pd.Series(dtype="float64")
    aligned = pd.Series({date: value for date, value in rows}, dtype="float64").sort_index()
    return aligned


def _period_supertrend_signal(frame: pd.DataFrame, rule: str) -> pd.Series:
    period_frame = _resample_ohlcv(frame, rule)
    raw = _supertrend_dir(period_frame)
    return align_completed_period_signal(pd.DatetimeIndex(frame.index), raw, rule)


def _monthly_macd_signal(frame: pd.DataFrame) -> pd.Series:
    monthly = frame.sort_index().resample("ME").last().dropna(subset=["Close"])
    if monthly.empty:
        return pd.Series(dtype="float64")

    if {"MACD_DIF", "MACD_DEA"}.issubset(monthly.columns):
        raw = (monthly["MACD_DIF"] > monthly["MACD_DEA"]).map(lambda value: 1.0 if value else -1.0)
    else:
        macd = ta.macd(monthly["Close"])
        if macd is None or macd.empty:
            return pd.Series(dtype="float64")
        line_col = next((column for column in macd.columns if str(column).startswith("MACD_")), None)
        signal_col = next((column for column in macd.columns if str(column).startswith("MACDs_")), None)
        if line_col is None or signal_col is None:
            return pd.Series(dtype="float64")
        raw = (macd[line_col] > macd[signal_col]).map(lambda value: 1.0 if value else -1.0)
    return align_completed_period_signal(pd.DatetimeIndex(frame.index), raw.dropna(), "ME")


def latest_signal_state(signal: pd.Series, as_of) -> Optional[int]:
    if signal is None or signal.empty or as_of is None:
        return None
    window = signal.sort_index()[signal.sort_index().index <= pd.Timestamp(as_of)]
    if window.empty or pd.isna(window.iloc[-1]):
        return None
    return int(float(window.iloc[-1]))


def _price_at(frame: pd.DataFrame, date, field: str) -> Optional[float]:
    ts = pd.Timestamp(date)
    if frame is None or frame.empty or field not in frame.columns or ts not in frame.index:
        return None
    value = frame.loc[ts, field]
    if isinstance(value, pd.Series):
        value = value.iloc[-1]
    return None if pd.isna(value) or float(value) <= 0 else float(value)


def _close_on_or_before(frame: pd.DataFrame, as_of) -> Optional[float]:
    if frame is None or frame.empty or "Close" not in frame.columns:
        return None
    window = frame[frame.index <= pd.Timestamp(as_of)].dropna(subset=["Close"])
    if window.empty:
        return None
    value = float(window.iloc[-1]["Close"])
    return value if value > 0 else None


def _trade_price(frame: pd.DataFrame, date) -> Optional[float]:
    return _price_at(frame, date, "Open") or _price_at(frame, date, "Close")


def _tradable_symbols(frames: Dict[str, pd.DataFrame], date) -> List[str]:
    return [symbol for symbol, frame in frames.items() if _trade_price(frame, date) is not None]


def eligible_symbols_for_strategy(
    strategy: str,
    date: pd.Timestamp,
    signal_as_of: pd.Timestamp,
    frames: Dict[str, pd.DataFrame],
    daily_signals: Dict[str, pd.Series],
    weekly_signals: Dict[str, pd.Series],
    symbol_monthly_st_signals: Dict[str, pd.Series],
    market_monthly_macd_signal: pd.Series,
    market_monthly_st_signal: pd.Series,
) -> List[str]:
    if strategy not in STRATEGIES or strategy == "rs_monthly_macd_baseline":
        raise ValueError(f"Unsupported ST strategy: {strategy}")

    if strategy == "market_monthly_macd_weekly_daily_st":
        if latest_signal_state(market_monthly_macd_signal, signal_as_of) != 1:
            return []
    if strategy == "market_monthly_st_weekly_daily_st":
        if latest_signal_state(market_monthly_st_signal, signal_as_of) != 1:
            return []

    eligible = []
    for symbol in sorted(_tradable_symbols(frames, date)):
        if latest_signal_state(daily_signals.get(symbol, pd.Series(dtype="float64")), signal_as_of) != 1:
            continue
        if latest_signal_state(weekly_signals.get(symbol, pd.Series(dtype="float64")), signal_as_of) != 1:
            continue
        if strategy == "symbol_monthly_st_weekly_daily_st":
            if latest_signal_state(symbol_monthly_st_signals.get(symbol, pd.Series(dtype="float64")), signal_as_of) != 1:
                continue
        eligible.append(symbol)
    return eligible


def _all_dates(frames: Dict[str, pd.DataFrame], start: Optional[str], end: Optional[str]) -> List[pd.Timestamp]:
    dates = sorted({pd.Timestamp(date) for frame in frames.values() for date in frame.index})
    if start:
        dates = [date for date in dates if date >= pd.Timestamp(start)]
    if end:
        dates = [date for date in dates if date <= pd.Timestamp(end)]
    return dates


def simulate_filtered_st_equal_weight(
    frames: Dict[str, pd.DataFrame],
    daily_signals: Dict[str, pd.Series],
    weekly_signals: Dict[str, pd.Series],
    symbol_monthly_st_signals: Dict[str, pd.Series],
    market_monthly_macd_signal: pd.Series,
    market_monthly_st_signal: pd.Series,
    strategy: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    fee_bps: float = FEE_BPS,
    slippage_bps: float = SLIPPAGE_BPS,
) -> Dict[str, object]:
    dates = _all_dates(frames, start, end)
    if not dates:
        return {"strategy": strategy, "totalReturnPct": 0.0, "maxDrawdownPct": 0.0, "equityCurve": []}

    fee = fee_bps / 10_000
    slip = slippage_bps / 10_000
    cash = 1.0
    holdings: Dict[str, Dict[str, float]] = {}
    realized_by_symbol: Dict[str, float] = {}
    peak = 1.0
    max_drawdown = 0.0
    turnover_count = 0
    curve: List[Dict[str, object]] = []
    previous_date: Optional[pd.Timestamp] = None

    def price_for_mark(symbol: str, date) -> Optional[float]:
        return _price_at(frames[symbol], date, "Close") or _close_on_or_before(frames[symbol], date)

    def portfolio_value(date: pd.Timestamp, use_trade_price: bool = False) -> float:
        total = cash
        for symbol, position in holdings.items():
            price = _trade_price(frames[symbol], date) if use_trade_price else price_for_mark(symbol, date)
            if price is None and previous_date is not None:
                price = price_for_mark(symbol, previous_date)
            if price is None:
                price = 0.0
            total += position["shares"] * price
        return total

    def rebalance(date: pd.Timestamp, targets: List[str]) -> None:
        nonlocal cash, turnover_count
        target_set = set(targets)
        equity = portfolio_value(date, use_trade_price=True)
        target_weight = 1.0 / len(targets) if targets else 0.0

        for symbol in list(holdings.keys()):
            price = _trade_price(frames[symbol], date)
            if price is None:
                continue
            position = holdings[symbol]
            current_value = position["shares"] * price
            target_value = equity * target_weight if symbol in target_set else 0.0
            if current_value <= target_value + 1e-12:
                continue
            shares_to_sell = min(position["shares"], (current_value - target_value) / price)
            if shares_to_sell <= 1e-12:
                continue
            fraction = shares_to_sell / position["shares"]
            removed_cost = position["cost_basis"] * fraction
            proceeds = shares_to_sell * price * (1 - slip) * (1 - fee)
            realized_by_symbol[symbol] = realized_by_symbol.get(symbol, 0.0) + proceeds - removed_cost
            cash += proceeds
            position["shares"] -= shares_to_sell
            position["cost_basis"] -= removed_cost
            if position["shares"] <= 1e-12:
                holdings.pop(symbol, None)
            turnover_count += 1

        equity = portfolio_value(date, use_trade_price=True)
        for symbol in targets:
            price = _trade_price(frames[symbol], date)
            if price is None:
                continue
            current_value = holdings.get(symbol, {}).get("shares", 0.0) * price
            target_value = equity * target_weight
            buy_value = target_value - current_value
            if buy_value <= 1e-12:
                continue
            gross_cash_needed = buy_value * (1 + slip) * (1 + fee)
            if gross_cash_needed > cash:
                buy_value = cash / ((1 + slip) * (1 + fee))
                gross_cash_needed = cash
            if buy_value <= 1e-12:
                continue
            shares = buy_value / price
            position = holdings.setdefault(symbol, {"shares": 0.0, "cost_basis": 0.0})
            position["shares"] += shares
            position["cost_basis"] += gross_cash_needed
            cash -= gross_cash_needed
            turnover_count += 1

    for date in dates:
        eligible_count = 0
        if previous_date is not None:
            targets = eligible_symbols_for_strategy(
                strategy=strategy,
                date=date,
                signal_as_of=previous_date,
                frames=frames,
                daily_signals=daily_signals,
                weekly_signals=weekly_signals,
                symbol_monthly_st_signals=symbol_monthly_st_signals,
                market_monthly_macd_signal=market_monthly_macd_signal,
                market_monthly_st_signal=market_monthly_st_signal,
            )
            eligible_count = len(targets)
            rebalance(date, targets)

        close_equity = cash
        invested_value = 0.0
        marked_holdings = []
        for symbol, position in list(holdings.items()):
            price = price_for_mark(symbol, date)
            if price is None:
                continue
            value = position["shares"] * price
            close_equity += value
            invested_value += value
            marked_holdings.append(symbol)

        peak = max(peak, close_equity)
        drawdown = (peak - close_equity) / peak * 100 if peak else 0.0
        max_drawdown = max(max_drawdown, drawdown)
        curve.append(
            {
                "date": _date_str(date),
                "equity": close_equity,
                "drawdownPct": drawdown,
                "actualExposure": invested_value / close_equity if close_equity else 0.0,
                "cashWeight": cash / close_equity if close_equity else 0.0,
                "openPositions": len(marked_holdings),
                "holdings": sorted(marked_holdings),
                "eligibleCount": eligible_count,
            }
        )
        previous_date = date

    total_return = (float(curve[-1]["equity"]) - 1.0) * 100 if curve else 0.0
    contribution_rows = []
    for symbol, pnl in realized_by_symbol.items():
        contribution_rows.append({"symbol": symbol, "contributionPct": pnl * 100})
    for symbol, position in holdings.items():
        price = price_for_mark(symbol, dates[-1])
        if price is None:
            continue
        unrealized = position["shares"] * price - position["cost_basis"]
        contribution_rows.append({"symbol": symbol, "contributionPct": unrealized * 100})
    by_symbol: Dict[str, float] = {}
    for row in contribution_rows:
        by_symbol[row["symbol"]] = by_symbol.get(row["symbol"], 0.0) + float(row["contributionPct"])
    top_contributors = [
        {"symbol": symbol, "contributionPct": value}
        for symbol, value in sorted(by_symbol.items(), key=lambda item: item[1], reverse=True)[:15]
    ]

    return {
        "strategy": strategy,
        "executionMode": "close_confirm_next_trading_day_open",
        "periodSignals": "weekly/monthly signals use only completed periods, then trade next open",
        "startDate": curve[0]["date"] if curve else None,
        "endDate": curve[-1]["date"] if curve else None,
        "totalReturnPct": total_return,
        "maxDrawdownPct": max_drawdown,
        "returnDrawdownRatio": total_return / max_drawdown if max_drawdown else None,
        "averageExposure": sum(float(point["actualExposure"]) for point in curve) / len(curve) if curve else 0.0,
        "averagePositionCount": sum(int(point["openPositions"]) for point in curve) / len(curve) if curve else 0.0,
        "averageEligibleCount": sum(int(point["eligibleCount"]) for point in curve) / len(curve) if curve else 0.0,
        "turnoverCount": turnover_count,
        "topContributors": top_contributors,
        "equityCurve": curve,
    }


def annual_stats(curve: List[Dict[str, object]]) -> List[Dict[str, object]]:
    by_year: Dict[str, List[Dict[str, object]]] = {}
    for point in curve:
        by_year.setdefault(str(pd.Timestamp(point["date"]).year), []).append(point)

    rows = []
    previous_equity = None
    for year, points in sorted(by_year.items()):
        start_equity = previous_equity if previous_equity is not None else float(points[0]["equity"])
        end_equity = float(points[-1]["equity"])
        peak = start_equity
        max_drawdown = 0.0
        for point in points:
            equity = float(point["equity"])
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, (peak - equity) / peak * 100 if peak else 0.0)
        rows.append(
            {
                "year": year,
                "returnPct": (end_equity / start_equity - 1) * 100 if start_equity else 0.0,
                "maxDrawdownPct": max_drawdown,
                "endEquity": end_equity,
            }
        )
        previous_equity = end_equity
    return rows


def rolling_year_stats(curve: List[Dict[str, object]], years: int) -> List[Dict[str, object]]:
    annual = annual_stats(curve)
    rows = []
    for idx in range(0, len(annual) - years + 1):
        window = annual[idx : idx + years]
        start_equity = 1.0 if idx == 0 else float(annual[idx - 1]["endEquity"])
        end_equity = float(window[-1]["endEquity"])
        max_dd = max(float(row["maxDrawdownPct"]) for row in window)
        ret = (end_equity / start_equity - 1) * 100 if start_equity else 0.0
        rows.append(
            {
                "startYear": window[0]["year"],
                "endYear": window[-1]["year"],
                "returnPct": ret,
                "maxDrawdownPct": max_dd,
                "returnDrawdownRatio": ret / max_dd if max_dd else None,
            }
        )
    return rows


def _worst_rolling(rows: List[Dict[str, object]]) -> Optional[Dict[str, object]]:
    return min(rows, key=lambda row: float(row["returnPct"])) if rows else None


def _portfolio_summary(portfolio: Dict[str, object]) -> Dict[str, object]:
    total_return = float(portfolio.get("totalReturnPct") or 0.0)
    max_drawdown = float(portfolio.get("maxDrawdownPct") or 0.0)
    curve = portfolio.get("equityCurve") or []
    return {
        "totalReturnPct": total_return,
        "maxDrawdownPct": max_drawdown,
        "returnDrawdownRatio": total_return / max_drawdown if max_drawdown else None,
        "averagePositionCount": float(portfolio.get("averagePositionCount") or 0.0),
        "averageExposure": float(portfolio.get("averageExposure") or 0.0),
        "turnoverCount": int(portfolio.get("turnoverCount") or 0),
        "startDate": portfolio.get("startDate") or (curve[0]["date"] if curve else None),
        "endDate": portfolio.get("endDate") or (curve[-1]["date"] if curve else None),
    }


def _decorate_portfolio(portfolio: Dict[str, object]) -> Dict[str, object]:
    curve = portfolio.get("equityCurve") or []
    rolling3 = rolling_year_stats(curve, 3)
    rolling5 = rolling_year_stats(curve, 5)
    return {
        "summary": _portfolio_summary(portfolio),
        "annual": annual_stats(curve),
        "rolling3Year": rolling3,
        "rolling5Year": rolling5,
        "worstRolling3Year": _worst_rolling(rolling3),
        "worstRolling5Year": _worst_rolling(rolling5),
        "topContributors": portfolio.get("topContributors", []),
        "portfolio": portfolio,
    }


def _build_signals(frames: Dict[str, pd.DataFrame], market_frame: pd.DataFrame) -> Dict[str, object]:
    daily_signals = {symbol: _supertrend_dir(frame) for symbol, frame in frames.items()}
    weekly_signals = {symbol: _period_supertrend_signal(frame, "W-FRI") for symbol, frame in frames.items()}
    symbol_monthly = {symbol: _period_supertrend_signal(frame, "ME") for symbol, frame in frames.items()}
    return {
        "daily": daily_signals,
        "weekly": weekly_signals,
        "symbolMonthlySt": symbol_monthly,
        "marketMonthlyMacd": _monthly_macd_signal(market_frame),
        "marketMonthlySt": _period_supertrend_signal(market_frame, "ME"),
    }


def _run_rs_baseline(
    frames: Dict[str, pd.DataFrame],
    market_frame: pd.DataFrame,
    start: str,
    end: str,
) -> Dict[str, object]:
    portfolio = backtest.simulate_rs_rotation_portfolio(
        frames,
        top_n=min(RS_TOP_N, max(1, len(frames))),
        rebalance_days=RS_REBALANCE_DAYS,
        lookback_bars=RS_LOOKBACK_BARS,
        start=start,
        end=end,
        fee_bps=FEE_BPS,
        slippage_bps=SLIPPAGE_BPS,
        market_filter_df=market_frame,
        market_filter_mode="monthly_macd",
        min_history_bars=0,
        min_avg_volume=MIN_AVG_VOLUME,
        volume_lookback=VOLUME_LOOKBACK,
    )
    curve = portfolio.get("equityCurve") or []
    portfolio["startDate"] = portfolio.get("startDate") or (curve[0]["date"] if curve else None)
    portfolio["endDate"] = portfolio.get("endDate") or (curve[-1]["date"] if curve else None)
    portfolio["averagePositionCount"] = (
        sum(int(point.get("openPositions") or 0) for point in curve) / len(curve) if curve else 0.0
    )
    portfolio["averageExposure"] = (
        sum(min(1.0, int(point.get("openPositions") or 0) / RS_TOP_N) for point in curve) / len(curve)
        if curve
        else 0.0
    )
    previous = set()
    turnover = 0
    for point in curve:
        current = set(point.get("holdings") or [])
        turnover += len(previous - current) + len(current - previous)
        previous = current
    portfolio["turnoverCount"] = turnover
    return portfolio


def _run_pool(
    name: str,
    symbols: List[str],
    data_dir: Path,
    market_frame: pd.DataFrame,
    windows: List[Dict[str, str]],
) -> Dict[str, object]:
    frames, missing = load_frames(symbols, data_dir)
    if not frames:
        raise RuntimeError(f"No cached parquet data for pool {name}")
    signals = _build_signals(frames, market_frame)

    window_payloads = {}
    for window in windows:
        portfolios: Dict[str, Dict[str, object]] = {}
        portfolios["rs_monthly_macd_baseline"] = _run_rs_baseline(
            frames,
            market_frame,
            start=window["start"],
            end=window["end"],
        )
        for strategy in STRATEGIES:
            if strategy == "rs_monthly_macd_baseline":
                continue
            portfolios[strategy] = simulate_filtered_st_equal_weight(
                frames,
                daily_signals=signals["daily"],
                weekly_signals=signals["weekly"],
                symbol_monthly_st_signals=signals["symbolMonthlySt"],
                market_monthly_macd_signal=signals["marketMonthlyMacd"],
                market_monthly_st_signal=signals["marketMonthlySt"],
                strategy=strategy,
                start=window["start"],
                end=window["end"],
                fee_bps=FEE_BPS,
                slippage_bps=SLIPPAGE_BPS,
            )
        window_payloads[window["name"]] = {
            "window": dict(window),
            "strategies": {key: _decorate_portfolio(portfolios[key]) for key in STRATEGIES},
            "summary": {key: _portfolio_summary(portfolios[key]) for key in STRATEGIES},
        }

    return {
        "name": name,
        "requestedSymbols": symbols,
        "usedSymbols": sorted(frames.keys()),
        "missingSymbols": missing,
        "symbolCount": len(frames),
        "windows": window_payloads,
    }


def build_research(
    data_dir: Path = DATA_DIR,
    universe_file: Path = UNIVERSE_FILE,
    windows: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, object]:
    market_frame = _load_frame(MARKET_SYMBOL, data_dir)
    if market_frame is None:
        raise RuntimeError(f"Missing required market filter data: {MARKET_SYMBOL}")

    selected_windows = windows or WINDOWS
    universes = build_universes(data_dir=data_dir, universe_file=universe_file)
    pools = {
        name: _run_pool(name, symbols, data_dir, market_frame, selected_windows)
        for name, symbols in universes.items()
    }
    return {
        "params": {
            "dataDir": str(data_dir),
            "universeFile": str(universe_file),
            "marketSymbol": MARKET_SYMBOL,
            "strategies": STRATEGIES,
            "strategyLabels": STRATEGY_LABELS,
            "windows": selected_windows,
            "supertrend": {"length": ST_LENGTH, "multiplier": ST_MULTIPLIER},
            "rsRotation": {
                "topN": RS_TOP_N,
                "rebalanceDays": RS_REBALANCE_DAYS,
                "lookbackBars": RS_LOOKBACK_BARS,
                "minAvgVolume": MIN_AVG_VOLUME,
            },
            "costs": {"feeBps": FEE_BPS, "slippageBps": SLIPPAGE_BPS},
            "lookaheadControl": [
                "Daily signals are evaluated after close and traded on the next trading day's open.",
                "Weekly and monthly signals are mapped to the last actual trading day of the completed period.",
                "A period signal can only affect the next trading day after that availability date.",
            ],
        },
        "pools": pools,
    }


def _fmt_pct(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{float(value):.2f}%"


def _fmt_num(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{float(value):.2f}"


def _summary_table(summary: Dict[str, Dict[str, object]]) -> str:
    lines = [
        "| 策略 | 收益 | 最大回撤 | 收益/回撤 | 平均持仓数 | 换手次数 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for key in STRATEGIES:
        row = summary[key]
        lines.append(
            "| {label} | {ret} | {dd} | {ratio} | {avg_pos} | {turnover} |".format(
                label=STRATEGY_LABELS[key],
                ret=_fmt_pct(row.get("totalReturnPct")),
                dd=_fmt_pct(row.get("maxDrawdownPct")),
                ratio=_fmt_num(row.get("returnDrawdownRatio")),
                avg_pos=_fmt_num(row.get("averagePositionCount")),
                turnover=int(row.get("turnoverCount") or 0),
            )
        )
    return "\n".join(lines)


def _annual_table(strategy_payload: Dict[str, object]) -> str:
    lines = ["| 年份 | 收益 | 最大回撤 |", "|---|---:|---:|"]
    for row in strategy_payload.get("annual", []):
        lines.append(f"| {row['year']} | {_fmt_pct(row.get('returnPct'))} | {_fmt_pct(row.get('maxDrawdownPct'))} |")
    return "\n".join(lines)


def _best_st(summary: Dict[str, Dict[str, object]]) -> str:
    candidates = [key for key in STRATEGIES if key != "rs_monthly_macd_baseline"]
    return max(candidates, key=lambda key: float(summary[key].get("returnDrawdownRatio") or -999999))


def write_report(payload: Dict[str, object], report_file: Path = REPORT_FILE) -> None:
    pools = payload["pools"]
    lines = [
        "# A 股主题 ETF ST 趋势策略：月级别过滤与扩池稳健性",
        "",
        "## 口径",
        "",
        "- 数据：只读本地 `backend/data/*.parquet`，不联网下载。",
        "- 执行：所有信号收盘确认，下一交易日开盘调仓，收盘计净值。",
        "- 防未来函数：周线和月线信号只在该周期最后一个本地交易日收盘后可用。",
        "- 注：本报告按实际周期完成日发布信号；这比旧的周线 `W` 标签研究少一交易日延迟，更贴近“收盘确认、下一交易日开盘”的本轮要求。",
        "- 成本：单边手续费 5 bps，单边滑点 5 bps。",
        "- 比较池：A 股宽基池、当前核心池、本地全部 A 股 ETF 池。",
        "- 重要限制：当前核心池和本地全池都不是无后验历史可投资池，扩池结果主要用于检验方向稳健性。",
        "",
    ]

    for pool_name, pool in pools.items():
        lines.extend(
            [
                f"## {pool_name}",
                "",
                f"- 请求标的：{len(pool['requestedSymbols'])} 个",
                f"- 使用标的：{pool['symbolCount']} 个",
                f"- 缺失标的：{', '.join(pool['missingSymbols']) if pool['missingSymbols'] else '无'}",
                "",
            ]
        )
        for window_name, window_payload in pool["windows"].items():
            label = window_payload["window"]["label"]
            lines.extend([f"### {label}", "", _summary_table(window_payload["summary"]), ""])

        full = pool["windows"]["full_2015_2026"]
        best_key = _best_st(full["summary"])
        best_payload = full["strategies"][best_key]
        worst3 = best_payload.get("worstRolling3Year")
        worst5 = best_payload.get("worstRolling5Year")
        lines.extend(
            [
                f"### {pool_name} 全周期最佳 ST 变体年度表现",
                "",
                f"最佳 ST 变体：`{STRATEGY_LABELS[best_key]}`。",
                "",
                _annual_table(best_payload),
                "",
                "滚动窗口：",
                "",
                f"- 最差 3 年：{worst3['startYear']}-{worst3['endYear']}，收益 {_fmt_pct(worst3['returnPct'])}，回撤 {_fmt_pct(worst3['maxDrawdownPct'])}" if worst3 else "- 最差 3 年：n/a",
                f"- 最差 5 年：{worst5['startYear']}-{worst5['endYear']}，收益 {_fmt_pct(worst5['returnPct'])}，回撤 {_fmt_pct(worst5['maxDrawdownPct'])}" if worst5 else "- 最差 5 年：n/a",
                "",
            ]
        )
        contributors = best_payload.get("topContributors") or []
        if contributors:
            total_positive = sum(max(0.0, float(row["contributionPct"])) for row in contributors)
            top5_positive = sum(max(0.0, float(row["contributionPct"])) for row in contributors[:5])
            share = top5_positive / total_positive * 100 if total_positive else 0.0
            lines.extend(
                [
                    "贡献集中度：",
                    "",
                    f"- Top5 正贡献占已列示正贡献约 `{share:.1f}%`。",
                    "- Top 贡献 ETF：" + ", ".join(
                        f"{row['symbol']}({_fmt_pct(row['contributionPct'])})" for row in contributors[:8]
                    ),
                    "",
                ]
            )

    broad_full = pools["a_share_broad"]["windows"]["full_2015_2026"]["summary"]
    core_full = pools["a_share_core_current"]["windows"]["full_2015_2026"]["summary"]
    all_full = pools["a_share_all_local_etf"]["windows"]["full_2015_2026"]["summary"]
    broad_best = _best_st(broad_full)
    core_best = _best_st(core_full)
    all_best = _best_st(all_full)

    lines.extend(
        [
            "## 结论",
            "",
            "这个方向不适合作为当前 A 股默认主策略。",
            "",
            "原因很朴素：在更干净的宽基池里，ST 月过滤后的收益/回撤仍然没有稳定压过 "
            "`A 股 ETF RS 轮动 + 510300 月 MACD`。默认策略应该优先选择更能跨市场状态存活的方案。",
            "",
            "它更适合作为 `主题趋势雷达`，也可以作为核心主题池的增强策略候选。",
            "",
            f"- 宽基池全周期最佳 ST：`{STRATEGY_LABELS[broad_best]}`，收益/回撤 {_fmt_num(broad_full[broad_best].get('returnDrawdownRatio'))}。",
            f"- 当前核心池全周期最佳 ST：`{STRATEGY_LABELS[core_best]}`，收益/回撤 {_fmt_num(core_full[core_best].get('returnDrawdownRatio'))}。",
            f"- 本地全池全周期最佳 ST：`{STRATEGY_LABELS[all_best]}`，收益/回撤 {_fmt_num(all_full[all_best].get('returnDrawdownRatio'))}。",
            "",
            "产品定位建议：",
            "",
            "| 用途 | 判断 |",
            "|---|---|",
            "| 默认策略 | 不建议 |",
            "| 主题趋势雷达 | 建议继续 |",
            "| 核心主题池增强 | 可以继续小仓位研究 |",
            "| 替代 RS + 月 MACD | 不建议 |",
            "| 放弃方向 | 不必放弃，但要承认它依赖主题池质量 |",
            "",
        ]
    )

    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Research A-share theme ETF ST strategies with monthly filters.")
    parser.add_argument("--data-dir", default=str(DATA_DIR))
    parser.add_argument("--universe-file", default=str(UNIVERSE_FILE))
    parser.add_argument(
        "--output",
        default=str(RESULTS_DIR / "a_share_theme_etf_st_monthly_filters_2026-06-06.json"),
    )
    parser.add_argument("--report", default=str(REPORT_FILE))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_research(data_dir=Path(args.data_dir), universe_file=Path(args.universe_file))
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(payload, Path(args.report))

    compact = {
        "output": str(output_path),
        "report": str(Path(args.report)),
        "params": payload["params"],
        "summary": {
            pool_name: {
                window_name: window_payload["summary"]
                for window_name, window_payload in pool["windows"].items()
            }
            for pool_name, pool in payload["pools"].items()
        },
    }
    print(json.dumps(payload if args.json else compact, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
