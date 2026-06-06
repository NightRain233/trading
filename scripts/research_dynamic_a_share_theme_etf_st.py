#!/usr/bin/env python3
"""Strict no-lookahead research for dynamic A-share ETF universes.

The local parquet cache is not a historical all-market ETF master. Results
from this script therefore describe only the symbols present in that cache.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd
import pandas_ta as ta


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
DATA_DIR = BACKEND_DIR / "data"
UNIVERSE_FILE = BACKEND_DIR / "universes" / "a_share_etf_core.json"
OUTPUT_FILE = (
    BACKEND_DIR
    / "backtest_results"
    / "dynamic_a_share_theme_etf_st_2026-06-06.json"
)
REPORT_FILE = ROOT / "docs" / "dynamic-a-share-theme-etf-st-research-2026-06-06.md"

MIN_HISTORY_BARS = 250
LIQUIDITY_LOOKBACK = 60
MIN_AVG_AMOUNT = 20_000_000.0
ST_LENGTH = 7
ST_MULTIPLIER = 3.0
RS_LOOKBACK_BARS = 60
RS_REBALANCE_DAYS = 20
FEE_BPS = 5.0
SLIPPAGE_BPS = 5.0
MARKET_SYMBOL = "510300.SS"

ETF_PATTERN = re.compile(r"^(15|51|56|58)\d{4}\.(SS|SZ)$")

WINDOWS = [
    {"name": "full", "label": "全周期", "start": "2015-01-01", "end": "2026-06-05"},
    {"name": "past_10y", "label": "过去十年", "start": "2016-06-06", "end": "2026-06-05"},
    {"name": "recent_5y", "label": "近五年", "start": "2021-06-06", "end": "2026-06-05"},
    {"name": "recent_3y", "label": "近三年", "start": "2023-06-06", "end": "2026-06-05"},
]

STRATEGY_LABELS = {
    "equal_weight": "动态池等权",
    "daily_st_equal_weight": "动态池日线 ST(7,3) 等权",
    "weekly_daily_st_equal_weight": "动态池周线+日线 ST(7,3) 等权",
    "rs_top3": "动态池 RS top3",
    "rs_top5": "动态池 RS top5",
    "weekly_daily_st_rs_top3": "周/日 ST 准入后 RS top3",
    "weekly_daily_st_rs_top5": "周/日 ST 准入后 RS top5",
    "broad_rs_top5_monthly_macd": "A 股宽基 RS top5 + 510300 月 MACD",
}

THEME_STRATEGIES = [
    "equal_weight",
    "daily_st_equal_weight",
    "weekly_daily_st_equal_weight",
    "rs_top3",
    "rs_top5",
    "weekly_daily_st_rs_top3",
    "weekly_daily_st_rs_top5",
]

ALL_LOCAL_STRATEGIES = [
    "equal_weight",
    "daily_st_equal_weight",
    "weekly_daily_st_equal_weight",
    "rs_top5",
    "weekly_daily_st_rs_top5",
]


def _date_str(value) -> str:
    return pd.Timestamp(value).date().isoformat()


def is_a_share_etf_symbol(symbol: str) -> bool:
    return bool(ETF_PATTERN.fullmatch(str(symbol).strip().upper()))


def scan_local_a_share_etfs(data_dir: Path = DATA_DIR) -> List[str]:
    symbols = []
    for path in Path(data_dir).glob("*.parquet"):
        if path.stem.endswith("_weekly"):
            continue
        symbol = path.stem.upper()
        if is_a_share_etf_symbol(symbol):
            symbols.append(symbol)
    return sorted(set(symbols))


def read_metadata_rows(path: Path = UNIVERSE_FILE) -> List[Dict[str, str]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    raw_rows = payload.get("symbols", payload) if isinstance(payload, dict) else payload
    rows = []
    for item in raw_rows:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        if not is_a_share_etf_symbol(symbol):
            continue
        rows.append(
            {
                "symbol": symbol,
                "name": str(item.get("name") or ""),
                "bucket": str(item.get("bucket") or ""),
            }
        )
    return rows


def build_metadata_groups(rows: Iterable[Dict[str, object]]) -> Dict[str, List[str]]:
    broad = []
    theme = []
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        bucket = str(row.get("bucket") or "").strip().lower()
        if not symbol:
            continue
        if bucket == "broad":
            broad.append(symbol)
        elif bucket:
            theme.append(symbol)
    return {
        "broad": sorted(set(broad)),
        "theme_proxy": sorted(set(theme)),
    }


def load_frame(symbol: str, data_dir: Path = DATA_DIR) -> Optional[pd.DataFrame]:
    path = Path(data_dir) / f"{symbol.upper()}.parquet"
    if not path.exists():
        return None
    frame = pd.read_parquet(path).sort_index()
    required = {"Open", "High", "Low", "Close", "Volume"}
    if frame.empty or not required.issubset(frame.columns):
        return None
    frame = frame.loc[:, list(dict.fromkeys([*frame.columns]))].copy()
    frame.index = pd.DatetimeIndex(frame.index).tz_localize(None)
    return frame[~frame.index.duplicated(keep="last")].sort_index()


def load_frames(
    symbols: Iterable[str],
    data_dir: Path = DATA_DIR,
) -> tuple[Dict[str, pd.DataFrame], List[str]]:
    frames = {}
    missing = []
    for symbol in sorted(set(symbols)):
        frame = load_frame(symbol, data_dir)
        if frame is None:
            missing.append(symbol)
        else:
            frames[symbol] = frame
    return frames, missing


def build_symbol_eligibility(
    frame: pd.DataFrame,
    min_history_bars: int = MIN_HISTORY_BARS,
    liquidity_lookback: int = LIQUIDITY_LOOKBACK,
    min_avg_amount: float = MIN_AVG_AMOUNT,
) -> pd.DataFrame:
    source = frame.sort_index()
    amount = source["Close"].astype(float) * source["Volume"].astype(float)
    history_bars = pd.Series(range(1, len(source) + 1), index=source.index, dtype="int64")
    avg_amount = amount.rolling(
        liquidity_lookback,
        min_periods=liquidity_lookback,
    ).mean()
    enough_history = history_bars >= min_history_bars
    enough_liquidity = avg_amount >= min_avg_amount
    eligible = enough_history & enough_liquidity
    reason = pd.Series("eligible", index=source.index, dtype="object")
    reason.loc[~enough_history] = "insufficient_history"
    reason.loc[enough_history & ~enough_liquidity] = "insufficient_liquidity"
    return pd.DataFrame(
        {
            "historyBars": history_bars,
            "avgAmount": avg_amount,
            "eligible": eligible.astype(bool),
            "reason": reason,
        },
        index=source.index,
    )


def is_symbol_eligible(eligibility: pd.DataFrame, as_of) -> bool:
    if eligibility is None or eligibility.empty:
        return False
    ts = pd.Timestamp(as_of)
    if ts not in eligibility.index:
        return False
    return bool(eligibility.loc[ts, "eligible"])


def eligible_symbols_on(
    eligibility_by_symbol: Dict[str, pd.DataFrame],
    pool_symbols: Iterable[str],
    as_of,
) -> List[str]:
    return sorted(
        symbol
        for symbol in pool_symbols
        if is_symbol_eligible(eligibility_by_symbol.get(symbol), as_of)
    )


def latest_signal_state(signal: pd.Series, as_of) -> Optional[int]:
    if signal is None or signal.empty or as_of is None:
        return None
    ordered = signal.dropna().sort_index()
    window = ordered[ordered.index <= pd.Timestamp(as_of)]
    if window.empty:
        return None
    return int(float(window.iloc[-1]))


def _resample_ohlcv(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    return (
        frame.sort_index()
        .resample(rule)
        .agg(
            {
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            }
        )
        .dropna(subset=["Open", "High", "Low", "Close"])
    )


def _supertrend_dir(frame: pd.DataFrame) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype="float64")
    st = ta.supertrend(
        frame["High"],
        frame["Low"],
        frame["Close"],
        length=ST_LENGTH,
        multiplier=ST_MULTIPLIER,
    )
    if st is None or st.empty:
        return pd.Series(dtype="float64")
    column = next(
        (name for name in st.columns if str(name).startswith("SUPERTd_")),
        None,
    )
    return (
        st[column].dropna().astype(float).sort_index()
        if column is not None
        else pd.Series(dtype="float64")
    )


def align_completed_period_signal(
    daily_index: pd.DatetimeIndex,
    period_signal: pd.Series,
    rule: str,
) -> pd.Series:
    if period_signal is None or period_signal.empty or len(daily_index) == 0:
        return pd.Series(dtype="float64")
    daily = pd.DatetimeIndex(daily_index).tz_localize(None).drop_duplicates().sort_values()
    max_date = pd.Timestamp(daily.max()).normalize()
    rows = []
    for timestamp, value in period_signal.dropna().sort_index().items():
        signal_date = pd.Timestamp(timestamp).tz_localize(None).normalize()
        if rule.startswith("W"):
            if signal_date > max_date or signal_date not in daily:
                continue
            rows.append((signal_date, float(value)))
            continue
        period = signal_date.to_period("M")
        period_end = pd.Timestamp(period.end_time).normalize()
        if period_end > max_date:
            continue
        candidates = daily[daily.to_period("M") == period]
        if len(candidates):
            rows.append((pd.Timestamp(candidates.max()), float(value)))
    if not rows:
        return pd.Series(dtype="float64")
    return pd.Series(dict(rows), dtype="float64").sort_index()


def build_signals(
    frames: Dict[str, pd.DataFrame],
) -> tuple[Dict[str, pd.Series], Dict[str, pd.Series]]:
    daily = {}
    weekly = {}
    for symbol, frame in frames.items():
        daily[symbol] = _supertrend_dir(frame)
        raw_weekly = _supertrend_dir(_resample_ohlcv(frame, "W-FRI"))
        weekly[symbol] = align_completed_period_signal(
            pd.DatetimeIndex(frame.index),
            raw_weekly,
            "W-FRI",
        )
    return daily, weekly


def build_monthly_macd_signal(frame: pd.DataFrame) -> pd.Series:
    monthly = frame["Close"].sort_index().resample("ME").last().dropna()
    fast = monthly.ewm(span=12, adjust=False).mean()
    slow = monthly.ewm(span=26, adjust=False).mean()
    dif = fast - slow
    dea = dif.ewm(span=9, adjust=False).mean()
    raw = (dif > dea).map(lambda value: 1.0 if value else -1.0)
    return align_completed_period_signal(pd.DatetimeIndex(frame.index), raw, "ME")


def _price_at(frame: pd.DataFrame, date, field: str) -> Optional[float]:
    ts = pd.Timestamp(date)
    if ts not in frame.index or field not in frame.columns:
        return None
    value = frame.loc[ts, field]
    if isinstance(value, pd.Series):
        value = value.iloc[-1]
    if pd.isna(value) or float(value) <= 0:
        return None
    return float(value)


def _close_on_or_before(frame: pd.DataFrame, as_of) -> Optional[float]:
    window = frame[frame.index <= pd.Timestamp(as_of)]["Close"].dropna()
    if window.empty or float(window.iloc[-1]) <= 0:
        return None
    return float(window.iloc[-1])


def rank_dynamic_candidates(
    frames: Dict[str, pd.DataFrame],
    candidates: Iterable[str],
    as_of,
    lookback_bars: int = RS_LOOKBACK_BARS,
    top_n: int = 5,
    daily_signals: Optional[Dict[str, pd.Series]] = None,
    weekly_signals: Optional[Dict[str, pd.Series]] = None,
    require_daily_st: bool = False,
    require_weekly_st: bool = False,
) -> List[str]:
    scores = []
    as_of_ts = pd.Timestamp(as_of)
    for symbol in sorted(set(candidates)):
        if require_daily_st and latest_signal_state(
            (daily_signals or {}).get(symbol, pd.Series(dtype="float64")),
            as_of_ts,
        ) != 1:
            continue
        if require_weekly_st and latest_signal_state(
            (weekly_signals or {}).get(symbol, pd.Series(dtype="float64")),
            as_of_ts,
        ) != 1:
            continue
        frame = frames.get(symbol)
        if frame is None:
            continue
        history = frame[frame.index <= as_of_ts]["Close"].dropna()
        if len(history) <= lookback_bars:
            continue
        current = float(history.iloc[-1])
        prior = float(history.iloc[-lookback_bars - 1])
        if prior > 0:
            scores.append((symbol, current / prior - 1.0))
    scores.sort(key=lambda item: (-item[1], item[0]))
    return [symbol for symbol, _score in scores[:top_n]]


def _target_symbols(
    strategy: str,
    frames: Dict[str, pd.DataFrame],
    dynamic_pool: List[str],
    signal_as_of,
    daily_signals: Dict[str, pd.Series],
    weekly_signals: Dict[str, pd.Series],
    market_monthly_macd_signal: pd.Series,
) -> List[str]:
    if strategy == "equal_weight":
        return dynamic_pool
    if strategy == "daily_st_equal_weight":
        return [
            symbol
            for symbol in dynamic_pool
            if latest_signal_state(daily_signals.get(symbol), signal_as_of) == 1
        ]
    if strategy == "weekly_daily_st_equal_weight":
        return [
            symbol
            for symbol in dynamic_pool
            if latest_signal_state(daily_signals.get(symbol), signal_as_of) == 1
            and latest_signal_state(weekly_signals.get(symbol), signal_as_of) == 1
        ]
    if strategy == "broad_rs_top5_monthly_macd":
        if latest_signal_state(market_monthly_macd_signal, signal_as_of) != 1:
            return []
        return rank_dynamic_candidates(
            frames,
            dynamic_pool,
            signal_as_of,
            top_n=5,
        )
    match = re.fullmatch(r"(weekly_daily_st_)?rs_top(3|5)", strategy)
    if match:
        gated = bool(match.group(1))
        return rank_dynamic_candidates(
            frames,
            dynamic_pool,
            signal_as_of,
            top_n=int(match.group(2)),
            daily_signals=daily_signals,
            weekly_signals=weekly_signals,
            require_daily_st=gated,
            require_weekly_st=gated,
        )
    raise ValueError(f"Unsupported strategy: {strategy}")


def _is_rs_strategy(strategy: str) -> bool:
    return strategy.startswith("rs_top") or "_rs_top" in strategy or strategy.startswith("broad_rs")


def simulate_dynamic_portfolio(
    frames: Dict[str, pd.DataFrame],
    eligibility: Dict[str, pd.DataFrame],
    pool_symbols: Iterable[str],
    strategy: str,
    daily_signals: Dict[str, pd.Series],
    weekly_signals: Dict[str, pd.Series],
    market_monthly_macd_signal: Optional[pd.Series] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    fee_bps: float = FEE_BPS,
    slippage_bps: float = SLIPPAGE_BPS,
    rebalance_days: int = RS_REBALANCE_DAYS,
    static_backcast: bool = False,
) -> Dict[str, object]:
    pool = sorted(set(pool_symbols) & set(frames))
    dates = sorted({pd.Timestamp(date) for symbol in pool for date in frames[symbol].index})
    if start:
        dates = [date for date in dates if date >= pd.Timestamp(start)]
    if end:
        dates = [date for date in dates if date <= pd.Timestamp(end)]
    if not dates:
        return {
            "strategy": strategy,
            "totalReturnPct": 0.0,
            "maxDrawdownPct": 0.0,
            "equityCurve": [],
            "trades": [],
        }

    fee = fee_bps / 10_000
    slip = slippage_bps / 10_000
    cash = 1.0
    holdings: Dict[str, Dict[str, float]] = {}
    realized: Dict[str, float] = {}
    trades = []
    curve = []
    peak = 1.0
    max_drawdown = 0.0
    gross_traded = 0.0
    transaction_cost = 0.0
    previous_date: Optional[pd.Timestamp] = None
    rs_targets: List[str] = []
    last_rs_rebalance = -rebalance_days
    monthly_macd = market_monthly_macd_signal
    if monthly_macd is None:
        monthly_macd = pd.Series(dtype="float64")
    last_targets: List[str] = []

    def mark_price(symbol: str, date) -> Optional[float]:
        return _price_at(frames[symbol], date, "Close") or _close_on_or_before(
            frames[symbol],
            date,
        )

    def trade_price(symbol: str, date) -> Optional[float]:
        return _price_at(frames[symbol], date, "Open")

    def portfolio_value(date, at_open: bool = False) -> float:
        total = cash
        for symbol, position in holdings.items():
            price = trade_price(symbol, date) if at_open else mark_price(symbol, date)
            if price is None and previous_date is not None:
                price = mark_price(symbol, previous_date)
            if price is not None:
                total += position["shares"] * price
        return total

    def rebalance(date: pd.Timestamp, targets: List[str]) -> None:
        nonlocal cash, gross_traded, transaction_cost
        executable_targets = [
            symbol for symbol in targets if trade_price(symbol, date) is not None
        ]
        equity = portfolio_value(date, at_open=True)
        weight = 1.0 / len(executable_targets) if executable_targets else 0.0
        target_set = set(executable_targets)

        for symbol in list(holdings):
            price = trade_price(symbol, date)
            if price is None:
                continue
            position = holdings[symbol]
            current_value = position["shares"] * price
            desired_value = equity * weight if symbol in target_set else 0.0
            sell_value = max(0.0, current_value - desired_value)
            if sell_value <= 1e-12:
                continue
            shares = min(position["shares"], sell_value / price)
            fraction = shares / position["shares"]
            removed_cost = position["costBasis"] * fraction
            gross = shares * price
            proceeds = gross * (1 - slip) * (1 - fee)
            cost = gross - proceeds
            cash += proceeds
            gross_traded += gross
            transaction_cost += cost
            realized[symbol] = realized.get(symbol, 0.0) + proceeds - removed_cost
            position["shares"] -= shares
            position["costBasis"] -= removed_cost
            trades.append(
                {
                    "date": _date_str(date),
                    "symbol": symbol,
                    "side": "sell",
                    "rawPrice": price,
                    "grossNotional": gross,
                    "cost": cost,
                }
            )
            if position["shares"] <= 1e-12:
                holdings.pop(symbol, None)

        equity = portfolio_value(date, at_open=True)
        for symbol in executable_targets:
            price = trade_price(symbol, date)
            current_value = holdings.get(symbol, {}).get("shares", 0.0) * price
            desired_value = equity * weight
            gross = max(0.0, desired_value - current_value)
            if gross <= 1e-12:
                continue
            cash_needed = gross * (1 + slip) * (1 + fee)
            if cash_needed > cash:
                gross = cash / ((1 + slip) * (1 + fee))
                cash_needed = cash
            if gross <= 1e-12:
                continue
            shares = gross / price
            position = holdings.setdefault(
                symbol,
                {"shares": 0.0, "costBasis": 0.0},
            )
            position["shares"] += shares
            position["costBasis"] += cash_needed
            cash -= cash_needed
            gross_traded += gross
            transaction_cost += cash_needed - gross
            trades.append(
                {
                    "date": _date_str(date),
                    "symbol": symbol,
                    "side": "buy",
                    "rawPrice": price,
                    "grossNotional": gross,
                    "cost": cash_needed - gross,
                }
            )

    for idx, date in enumerate(dates):
        eligible = []
        if previous_date is not None:
            if static_backcast:
                eligible = [
                    symbol
                    for symbol in pool
                    if previous_date in frames[symbol].index
                ]
            else:
                eligible = eligible_symbols_on(eligibility, pool, previous_date)

            if _is_rs_strategy(strategy):
                allowed = set(eligible)
                if strategy.startswith("weekly_daily_st_"):
                    allowed = {
                        symbol
                        for symbol in allowed
                        if latest_signal_state(daily_signals.get(symbol), previous_date) == 1
                        and latest_signal_state(weekly_signals.get(symbol), previous_date) == 1
                    }
                if strategy == "broad_rs_top5_monthly_macd" and latest_signal_state(
                    monthly_macd,
                    previous_date,
                ) != 1:
                    allowed = set()
                if idx - last_rs_rebalance >= rebalance_days:
                    last_rs_rebalance = idx
                    rs_targets = _target_symbols(
                        strategy,
                        frames,
                        sorted(allowed),
                        previous_date,
                        daily_signals,
                        weekly_signals,
                        monthly_macd,
                    )
                else:
                    rs_targets = [symbol for symbol in rs_targets if symbol in allowed]
                targets = rs_targets
            else:
                targets = _target_symbols(
                    strategy,
                    frames,
                    eligible,
                    previous_date,
                    daily_signals,
                    weekly_signals,
                    monthly_macd,
                )
            normalized_targets = sorted(targets)
            if normalized_targets != sorted(last_targets):
                rebalance(date, normalized_targets)
                last_targets = normalized_targets

        close_equity = cash
        invested = 0.0
        marked = []
        for symbol, position in holdings.items():
            price = mark_price(symbol, date)
            if price is None:
                continue
            value = position["shares"] * price
            close_equity += value
            invested += value
            marked.append(symbol)
        peak = max(peak, close_equity)
        drawdown = (peak - close_equity) / peak * 100 if peak else 0.0
        max_drawdown = max(max_drawdown, drawdown)
        curve.append(
            {
                "date": _date_str(date),
                "equity": close_equity,
                "drawdownPct": drawdown,
                "investableCount": len(eligible),
                "openPositions": len(marked),
                "holdings": sorted(marked),
                "exposure": invested / close_equity if close_equity else 0.0,
            }
        )
        previous_date = date

    contributions = dict(realized)
    for symbol, position in holdings.items():
        price = mark_price(symbol, dates[-1])
        if price is not None:
            contributions[symbol] = contributions.get(symbol, 0.0) + (
                position["shares"] * price - position["costBasis"]
            )
    contributor_rows = [
        {"symbol": symbol, "contributionPct": value * 100}
        for symbol, value in sorted(
            contributions.items(),
            key=lambda item: item[1],
            reverse=True,
        )
    ]
    positive_total = sum(max(0.0, value) for value in contributions.values())
    top3_positive = sum(
        max(0.0, row["contributionPct"] / 100)
        for row in contributor_rows[:3]
    )
    avg_equity = (
        sum(float(point["equity"]) for point in curve) / len(curve)
        if curve
        else 1.0
    )
    total_return = (float(curve[-1]["equity"]) - 1.0) * 100
    return {
        "strategy": strategy,
        "execution": "signals through prior close; rebalance at next trading-day open",
        "startDate": curve[0]["date"],
        "endDate": curve[-1]["date"],
        "totalReturnPct": total_return,
        "maxDrawdownPct": max_drawdown,
        "returnDrawdownRatio": total_return / max_drawdown if max_drawdown else None,
        "averagePositionCount": sum(point["openPositions"] for point in curve) / len(curve),
        "averageInvestableCount": sum(point["investableCount"] for point in curve) / len(curve),
        "averageExposure": sum(point["exposure"] for point in curve) / len(curve),
        "turnoverMultiple": gross_traded / avg_equity if avg_equity else None,
        "transactionCostPctOfInitial": transaction_cost * 100,
        "tradeCount": len(trades),
        "topContributors": contributor_rows[:15],
        "top3PositiveContributionShare": (
            top3_positive / positive_total if positive_total > 0 else None
        ),
        "equityCurve": curve,
        "trades": trades,
    }


def _curve_window(
    portfolio: Dict[str, object],
    start: str,
    end: str,
) -> Dict[str, object]:
    curve = [
        point
        for point in portfolio.get("equityCurve", [])
        if pd.Timestamp(start) <= pd.Timestamp(point["date"]) <= pd.Timestamp(end)
    ]
    if not curve:
        return {
            "startDate": None,
            "endDate": None,
            "totalReturnPct": 0.0,
            "maxDrawdownPct": 0.0,
            "returnDrawdownRatio": None,
            "averagePositionCount": 0.0,
            "averageInvestableCount": 0.0,
            "averageExposure": 0.0,
            "tradeCount": 0,
            "transactionCostPctOfWindowStart": 0.0,
        }
    start_equity = float(curve[0]["equity"])
    end_equity = float(curve[-1]["equity"])
    peak = start_equity
    max_dd = 0.0
    for point in curve:
        equity = float(point["equity"])
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100 if peak else 0.0)
    trades = [
        trade
        for trade in portfolio.get("trades", [])
        if pd.Timestamp(start) <= pd.Timestamp(trade["date"]) <= pd.Timestamp(end)
    ]
    transaction_cost = sum(float(trade["cost"]) for trade in trades)
    total_return = (end_equity / start_equity - 1) * 100 if start_equity else 0.0
    return {
        "startDate": curve[0]["date"],
        "endDate": curve[-1]["date"],
        "totalReturnPct": total_return,
        "maxDrawdownPct": max_dd,
        "returnDrawdownRatio": total_return / max_dd if max_dd else None,
        "averagePositionCount": sum(point["openPositions"] for point in curve) / len(curve),
        "averageInvestableCount": sum(point["investableCount"] for point in curve) / len(curve),
        "averageExposure": sum(point["exposure"] for point in curve) / len(curve),
        "tradeCount": len(trades),
        "transactionCostPctOfWindowStart": (
            transaction_cost / start_equity * 100 if start_equity else 0.0
        ),
    }


def annual_stats(portfolio: Dict[str, object]) -> List[Dict[str, object]]:
    curve = portfolio.get("equityCurve", [])
    if not curve:
        return []
    years = sorted({pd.Timestamp(point["date"]).year for point in curve})
    rows = []
    for year in years:
        rows.append(
            {
                "year": year,
                **_curve_window(
                    portfolio,
                    f"{year}-01-01",
                    f"{year}-12-31",
                ),
            }
        )
    return rows


def worst_rolling_years(
    portfolio: Dict[str, object],
    years: int,
) -> Optional[Dict[str, object]]:
    curve = portfolio.get("equityCurve", [])
    if not curve:
        return None
    points = pd.DataFrame(curve)
    points["date"] = pd.to_datetime(points["date"])
    points = points.set_index("date").sort_index()
    candidates = []
    for end_date, end_row in points.iterrows():
        target_start = end_date - pd.DateOffset(years=years)
        prior = points[points.index <= target_start]
        if prior.empty:
            continue
        start_date = prior.index[-1]
        start_equity = float(prior.iloc[-1]["equity"])
        window = points[(points.index >= start_date) & (points.index <= end_date)]
        end_equity = float(end_row["equity"])
        peak = start_equity
        max_dd = 0.0
        for equity in window["equity"].astype(float):
            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) / peak * 100 if peak else 0.0)
        candidates.append(
            {
                "startDate": _date_str(start_date),
                "endDate": _date_str(end_date),
                "returnPct": (end_equity / start_equity - 1) * 100,
                "maxDrawdownPct": max_dd,
            }
        )
    return min(candidates, key=lambda row: row["returnPct"]) if candidates else None


def build_investable_count_report(
    eligibility: Dict[str, pd.DataFrame],
    pool_symbols: Iterable[str],
    all_dates: Iterable[pd.Timestamp],
) -> Dict[str, object]:
    daily = []
    for date in all_dates:
        symbols = eligible_symbols_on(eligibility, pool_symbols, date)
        daily.append(
            {
                "date": _date_str(date),
                "count": len(symbols),
                "symbols": symbols,
            }
        )
    by_year = {}
    for row in daily:
        by_year.setdefault(str(pd.Timestamp(row["date"]).year), []).append(row["count"])
    return {
        "daily": daily,
        "annual": [
            {
                "year": int(year),
                "minCount": min(counts),
                "maxCount": max(counts),
                "averageCount": sum(counts) / len(counts),
                "yearEndCount": counts[-1],
            }
            for year, counts in sorted(by_year.items())
        ],
    }


def build_symbol_lifecycle(
    frames: Dict[str, pd.DataFrame],
    eligibility: Dict[str, pd.DataFrame],
    pool_symbols: Iterable[str],
    global_end,
) -> List[Dict[str, object]]:
    rows = []
    for symbol in sorted(set(pool_symbols) & set(frames)):
        frame = frames[symbol]
        table = eligibility[symbol]
        eligible_rows = table[table["eligible"]]
        transitions = []
        previous = False
        for date, row in table.iterrows():
            current = bool(row["eligible"])
            if current and not previous:
                transitions.append(
                    {
                        "date": _date_str(date),
                        "event": "enter",
                        "reason": "history_and_liquidity_pass",
                    }
                )
            elif previous and not current:
                transitions.append(
                    {
                        "date": _date_str(date),
                        "event": "exit",
                        "reason": str(row["reason"]),
                    }
                )
            previous = current
        if frame.index.max() < pd.Timestamp(global_end):
            transitions.append(
                {
                    "date": _date_str(frame.index.max()),
                    "event": "data_end",
                    "reason": "local_parquet_ends_before_research_end",
                }
            )
        rows.append(
            {
                "symbol": symbol,
                "firstDataDate": _date_str(frame.index.min()),
                "lastDataDate": _date_str(frame.index.max()),
                "firstEligibleDate": (
                    _date_str(eligible_rows.index.min())
                    if not eligible_rows.empty
                    else None
                ),
                "everEligible": not eligible_rows.empty,
                "neverEligibleReason": (
                    None
                    if not eligible_rows.empty
                    else str(table.iloc[-1]["reason"])
                ),
                "events": transitions,
            }
        )
    return rows


def _portfolio_package(portfolio: Dict[str, object]) -> Dict[str, object]:
    return {
        "summary": {
            key: portfolio.get(key)
            for key in [
                "startDate",
                "endDate",
                "totalReturnPct",
                "maxDrawdownPct",
                "returnDrawdownRatio",
                "averagePositionCount",
                "averageInvestableCount",
                "averageExposure",
                "turnoverMultiple",
                "transactionCostPctOfInitial",
                "tradeCount",
                "top3PositiveContributionShare",
            ]
        },
        "windows": {
            window["name"]: {
                "label": window["label"],
                **_curve_window(portfolio, window["start"], window["end"]),
            }
            for window in WINDOWS
        },
        "annual": annual_stats(portfolio),
        "worstRolling3Year": worst_rolling_years(portfolio, 3),
        "worstRolling5Year": worst_rolling_years(portfolio, 5),
        "topContributors": portfolio.get("topContributors", []),
        "portfolio": portfolio,
    }


def _run_pool_strategies(
    frames: Dict[str, pd.DataFrame],
    eligibility: Dict[str, pd.DataFrame],
    symbols: List[str],
    strategies: List[str],
    daily_signals: Dict[str, pd.Series],
    weekly_signals: Dict[str, pd.Series],
    market_monthly_macd_signal: pd.Series,
    static_backcast: bool = False,
) -> Dict[str, object]:
    portfolios = {}
    for strategy in strategies:
        portfolio = simulate_dynamic_portfolio(
            frames=frames,
            eligibility=eligibility,
            pool_symbols=symbols,
            strategy=strategy,
            daily_signals=daily_signals,
            weekly_signals=weekly_signals,
            market_monthly_macd_signal=market_monthly_macd_signal,
            start=WINDOWS[0]["start"],
            end=WINDOWS[0]["end"],
            static_backcast=static_backcast,
        )
        portfolios[strategy] = _portfolio_package(portfolio)
    return portfolios


def _data_audit(
    frames: Dict[str, pd.DataFrame],
    local_symbols: List[str],
    metadata_groups: Dict[str, List[str]],
    missing_metadata: List[str],
) -> Dict[str, object]:
    counts_by_start_year = {}
    symbols = []
    for symbol, frame in sorted(frames.items()):
        year = str(frame.index.min().year)
        counts_by_start_year[year] = counts_by_start_year.get(year, 0) + 1
        symbols.append(
            {
                "symbol": symbol,
                "rows": len(frame),
                "firstDate": _date_str(frame.index.min()),
                "lastDate": _date_str(frame.index.max()),
                "hasOhlcv": {"Open", "High", "Low", "Close", "Volume"}.issubset(frame.columns),
            }
        )
    return {
        "localEtfCount": len(local_symbols),
        "metadataThemeProxyCount": len(metadata_groups["theme_proxy"]),
        "metadataBroadCount": len(metadata_groups["broad"]),
        "missingMetadataSymbols": missing_metadata,
        "countsByFirstDataYear": counts_by_start_year,
        "symbols": symbols,
        "coverageConclusion": (
            "Local cache is a small current research/watchlist-derived sample, "
            "not a historical all-market ETF master. Historical universe breadth, "
            "delisted funds, and ETFs never cached locally are absent."
        ),
        "survivorshipRisk": "high",
    }


def build_research(
    data_dir: Path = DATA_DIR,
    universe_file: Path = UNIVERSE_FILE,
) -> Dict[str, object]:
    local_symbols = scan_local_a_share_etfs(data_dir)
    frames, missing_files = load_frames(local_symbols, data_dir)
    metadata_rows = read_metadata_rows(universe_file)
    metadata_groups = build_metadata_groups(metadata_rows)
    missing_metadata = sorted(set(local_symbols) - {row["symbol"] for row in metadata_rows})
    theme_symbols = sorted(set(metadata_groups["theme_proxy"]) & set(frames))
    broad_symbols = sorted(set(metadata_groups["broad"]) & set(frames))
    all_local_symbols = sorted(frames)
    if MARKET_SYMBOL not in frames:
        raise RuntimeError(f"Missing required market frame {MARKET_SYMBOL}")
    if not theme_symbols:
        raise RuntimeError("No metadata-classified theme proxy symbols with local data")

    eligibility = {
        symbol: build_symbol_eligibility(frame)
        for symbol, frame in frames.items()
    }
    daily_signals, weekly_signals = build_signals(frames)
    market_monthly_macd = build_monthly_macd_signal(frames[MARKET_SYMBOL])
    all_dates = sorted({date for frame in frames.values() for date in frame.index})
    research_end = min(pd.Timestamp(WINDOWS[0]["end"]), max(all_dates))

    theme_dynamic = _run_pool_strategies(
        frames,
        eligibility,
        theme_symbols,
        THEME_STRATEGIES,
        daily_signals,
        weekly_signals,
        market_monthly_macd,
    )
    all_local_dynamic = _run_pool_strategies(
        frames,
        eligibility,
        all_local_symbols,
        ALL_LOCAL_STRATEGIES,
        daily_signals,
        weekly_signals,
        market_monthly_macd,
    )
    broad_dynamic = _run_pool_strategies(
        frames,
        eligibility,
        broad_symbols,
        [
            "equal_weight",
            "daily_st_equal_weight",
            "weekly_daily_st_equal_weight",
            "broad_rs_top5_monthly_macd",
        ],
        daily_signals,
        weekly_signals,
        market_monthly_macd,
    )
    theme_static = _run_pool_strategies(
        frames,
        eligibility,
        theme_symbols,
        ["equal_weight", "weekly_daily_st_equal_weight"],
        daily_signals,
        weekly_signals,
        market_monthly_macd,
        static_backcast=True,
    )

    static_difference = {}
    for strategy in ["equal_weight", "weekly_daily_st_equal_weight"]:
        static_difference[strategy] = {}
        for window in WINDOWS:
            name = window["name"]
            dynamic_return = theme_dynamic[strategy]["windows"][name]["totalReturnPct"]
            static_return = theme_static[strategy]["windows"][name]["totalReturnPct"]
            static_difference[strategy][name] = {
                "dynamicReturnPct": dynamic_return,
                "staticBackcastReturnPct": static_return,
                "dynamicMinusStaticPctPoints": dynamic_return - static_return,
            }

    return {
        "generatedAt": "2026-06-06",
        "params": {
            "minHistoryBars": MIN_HISTORY_BARS,
            "liquidityLookback": LIQUIDITY_LOOKBACK,
            "minAverageAmountCny": MIN_AVG_AMOUNT,
            "supertrend": {"length": ST_LENGTH, "multiplier": ST_MULTIPLIER},
            "relativeStrength": {
                "lookbackBars": RS_LOOKBACK_BARS,
                "rebalanceDays": RS_REBALANCE_DAYS,
                "topN": [3, 5],
            },
            "costs": {"feeBpsPerSide": FEE_BPS, "slippageBpsPerSide": SLIPPAGE_BPS},
            "execution": "daily/weekly/monthly close-confirmed; next trading-day open",
            "classification": (
                "Repository metadata only: bucket=broad is broad; every other "
                "non-empty bucket is theme_proxy. No return fields are read."
            ),
            "windows": WINDOWS,
        },
        "dataAudit": _data_audit(
            frames,
            local_symbols,
            metadata_groups,
            missing_metadata,
        ),
        "pools": {
            "theme_proxy_dynamic": {
                "symbols": theme_symbols,
                "classificationCaveat": (
                    "Current repository metadata and current cached membership; "
                    "not a historical all-market theme ETF classification."
                ),
                "investableCounts": build_investable_count_report(
                    eligibility,
                    theme_symbols,
                    [date for date in all_dates if date <= research_end],
                ),
                "symbolLifecycle": build_symbol_lifecycle(
                    frames,
                    eligibility,
                    theme_symbols,
                    research_end,
                ),
                "strategies": theme_dynamic,
            },
            "all_local_dynamic": {
                "symbols": all_local_symbols,
                "investableCounts": build_investable_count_report(
                    eligibility,
                    all_local_symbols,
                    [date for date in all_dates if date <= research_end],
                ),
                "symbolLifecycle": build_symbol_lifecycle(
                    frames,
                    eligibility,
                    all_local_symbols,
                    research_end,
                ),
                "strategies": all_local_dynamic,
            },
            "broad_fixed_dynamic": {
                "symbols": broad_symbols,
                "strategies": broad_dynamic,
            },
            "theme_proxy_current_static_backcast": {
                "symbols": theme_symbols,
                "strategies": theme_static,
            },
        },
        "dynamicVsStatic": static_difference,
        "unclassifiedLocalSymbols": missing_metadata,
        "missingFiles": missing_files,
        "evidence": {
            "themeAdvantage": "low",
            "reason": (
                "The dynamic eligibility rules are causal, but the available symbol "
                "master is a small current cache with high survivorship and selection bias."
            ),
        },
    }


def _fmt_pct(value) -> str:
    return "n/a" if value is None else f"{float(value):.2f}%"


def _fmt_num(value) -> str:
    return "n/a" if value is None else f"{float(value):.2f}"


def _strategy_table(strategies: Dict[str, object], window: str) -> str:
    lines = [
        "| 策略 | 收益 | 最大回撤 | 收益/回撤 | 平均持仓 | 成本 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for key, package in strategies.items():
        row = package["windows"][window]
        lines.append(
            f"| {STRATEGY_LABELS.get(key, key)} | "
            f"{_fmt_pct(row['totalReturnPct'])} | "
            f"{_fmt_pct(row['maxDrawdownPct'])} | "
            f"{_fmt_num(row['returnDrawdownRatio'])} | "
            f"{_fmt_num(row['averagePositionCount'])} | "
            f"{_fmt_pct(row['transactionCostPctOfWindowStart'])} |"
        )
    return "\n".join(lines)


def _year_table(strategies: Dict[str, object]) -> str:
    keys = [
        "equal_weight",
        "daily_st_equal_weight",
        "weekly_daily_st_equal_weight",
        "rs_top5",
        "weekly_daily_st_rs_top5",
    ]
    by_strategy = {
        key: {row["year"]: row for row in strategies[key]["annual"]}
        for key in keys
    }
    years = sorted(set().union(*(set(rows) for rows in by_strategy.values())))
    lines = [
        "| 年份 | 等权 | 日 ST | 周+日 ST | RS5 | ST 后 RS5 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for year in years:
        values = [
            _fmt_pct(by_strategy[key].get(year, {}).get("totalReturnPct"))
            for key in keys
        ]
        lines.append(f"| {year} | " + " | ".join(values) + " |")
    return "\n".join(lines)


def write_report(payload: Dict[str, object], path: Path = REPORT_FILE) -> None:
    audit = payload["dataAudit"]
    theme = payload["pools"]["theme_proxy_dynamic"]
    all_local = payload["pools"]["all_local_dynamic"]
    broad = payload["pools"]["broad_fixed_dynamic"]
    static_diff = payload["dynamicVsStatic"]
    strategies = theme["strategies"]
    best_full = max(
        strategies,
        key=lambda key: float(
            strategies[key]["windows"]["full"]["returnDrawdownRatio"]
            if strategies[key]["windows"]["full"]["returnDrawdownRatio"] is not None
            else -math.inf
        ),
    )
    wd = strategies["weekly_daily_st_equal_weight"]["windows"]
    eq = strategies["equal_weight"]["windows"]
    advantage_windows = [
        name
        for name in wd
        if wd[name]["returnDrawdownRatio"] is not None
        and eq[name]["returnDrawdownRatio"] is not None
        and wd[name]["returnDrawdownRatio"] > eq[name]["returnDrawdownRatio"]
    ]
    top = strategies[best_full]["topContributors"][:5]
    top_text = "、".join(
        f"{row['symbol']} ({row['contributionPct']:.1f}%)"
        for row in top
    ) or "无"
    broad_row = broad["strategies"]["broad_rs_top5_monthly_macd"]["windows"]["full"]
    broad_weekly_daily = broad["strategies"]["weekly_daily_st_equal_weight"]["windows"]["full"]
    broad_weekly_daily_5y = broad["strategies"]["weekly_daily_st_equal_weight"]["windows"]["recent_5y"]
    all_row = all_local["strategies"]["weekly_daily_st_equal_weight"]["windows"]["full"]

    lines = [
        "# 无后验动态 A 股主题 ETF 池 SuperTrend 研究 2026-06-06",
        "",
        "## 结论先行",
        "",
        (
            "**动态准入规则本身没有使用未来数据，但本地标的主表不完整，因此不能把本研究称为历史全市场无幸存者偏差验证。**"
        ),
        "",
        (
            f"在当前缓存的主题代理组中，周线+日线 ST 的收益/回撤优于动态等权的窗口为 "
            f"{len(advantage_windows)}/{len(wd)}（{', '.join(advantage_windows) or '无'}）。"
        ),
        (
            f"全周期收益/回撤最高的是 `{STRATEGY_LABELS[best_full]}`；"
            f"其主要正贡献标的是：{top_text}。"
        ),
        (
            "这不足以证明“ST 适合主题 ETF、不适合宽基”。主题池来自 2026 年当前缓存和当前元数据，"
            "缺少历史全市场 ETF 名单、退市/清盘 ETF、未进入 watchlist 的失败产品及历史分类快照。"
        ),
        (
            f"同口径宽基周+日 ST 全周期为 {_fmt_pct(broad_weekly_daily['totalReturnPct'])}、"
            f"近五年为 {_fmt_pct(broad_weekly_daily_5y['totalReturnPct'])}；"
            "样本内差异存在，但不能排除当前主题缓存成员的选择偏差。"
        ),
        "",
        "## 预先固定口径",
        "",
        "- 标的代码：`.SS/.SZ` 且前缀为 `15/51/56/58`。",
        f"- 最短历史：{MIN_HISTORY_BARS} 个交易日。",
        f"- 流动性：过去 {LIQUIDITY_LOOKBACK} 日平均成交额 `Close×Volume >= {MIN_AVG_AMOUNT:,.0f}` 元。",
        f"- ST：`SuperTrend({ST_LENGTH},{ST_MULTIPLIER:g})`，日/周收盘确认，下一交易日开盘执行。",
        f"- RS：{RS_LOOKBACK_BARS} 日收益，top3/top5，每 {RS_REBALANCE_DAYS} 个组合交易日再平衡。",
        f"- 成本：单边手续费 {FEE_BPS:g} bps + 滑点 {SLIPPAGE_BPS:g} bps。",
        "- 周线：仅接受数据中真实存在的周五收盘信号；缺失周五时保守跳过该周新信号。",
        "- 分类：只读取仓库元数据 `bucket`；`broad` 为宽基，其余非空 bucket 为主题代理。",
        "- 未运行参数搜索，也未根据本次收益结果重新挑选阈值或标的。",
        "",
        "## 数据覆盖审计",
        "",
        f"- 本地 ETF parquet：{audit['localEtfCount']} 只。",
        f"- 当前元数据主题代理：{audit['metadataThemeProxyCount']} 只；宽基：{audit['metadataBroadCount']} 只。",
        f"- 无元数据本地标的：{', '.join(audit['missingMetadataSymbols']) or '无'}。",
        f"- 幸存者/选择偏差：**{audit['survivorshipRisk']}**。",
        f"- 结论：{audit['coverageConclusion']}",
        "",
    ]
    for window in WINDOWS:
        lines.extend(
            [
                f"## 主题代理动态池：{window['label']}",
                "",
                _strategy_table(strategies, window["name"]),
                "",
            ]
        )
    lines.extend(
        [
            "## 自然年",
            "",
            _year_table(strategies),
            "",
            "## 最差滚动窗口",
            "",
            "| 策略 | 最差滚动 3 年 | 收益 | 最差滚动 5 年 | 收益 |",
            "|---|---|---:|---|---:|",
        ]
    )
    for key in THEME_STRATEGIES:
        rolling3 = strategies[key]["worstRolling3Year"]
        rolling5 = strategies[key]["worstRolling5Year"]
        lines.append(
            f"| {STRATEGY_LABELS[key]} | "
            f"{rolling3['startDate']}~{rolling3['endDate']} | {_fmt_pct(rolling3['returnPct'])} | "
            f"{rolling5['startDate']}~{rolling5['endDate']} | {_fmt_pct(rolling5['returnPct'])} |"
        )
    lines.extend(
        [
            "",
            "## 动态池与当前静态池回填差异",
            "",
            "| 策略 | 窗口 | 动态收益 | 当前静态成员回填 | 动态-静态 |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for strategy, windows in static_diff.items():
        for name, row in windows.items():
            lines.append(
                f"| {STRATEGY_LABELS[strategy]} | {name} | "
                f"{_fmt_pct(row['dynamicReturnPct'])} | "
                f"{_fmt_pct(row['staticBackcastReturnPct'])} | "
                f"{_fmt_pct(row['dynamicMinusStaticPctPoints'])} |"
            )
    lines.extend(
        [
            "",
            "## 对照与集中度",
            "",
            (
                f"- 全本地动态池周+日 ST：收益 {_fmt_pct(all_row['totalReturnPct'])}，"
                f"最大回撤 {_fmt_pct(all_row['maxDrawdownPct'])}。"
            ),
            (
                f"- 固定宽基元数据池 RS top5 + 510300 月 MACD：收益 "
                f"{_fmt_pct(broad_row['totalReturnPct'])}，最大回撤 {_fmt_pct(broad_row['maxDrawdownPct'])}。"
            ),
            (
                f"- 同口径宽基动态池周+日 ST：收益 "
                f"{_fmt_pct(broad_weekly_daily['totalReturnPct'])}，最大回撤 "
                f"{_fmt_pct(broad_weekly_daily['maxDrawdownPct'])}。"
            ),
            (
                f"- 主题代理最佳全周期策略前三大正贡献集中度："
                f"{_fmt_pct(strategies[best_full]['summary']['top3PositiveContributionShare'] * 100 if strategies[best_full]['summary']['top3PositiveContributionShare'] is not None else None)}。"
            ),
            "",
            "每日/年度可投资数量、每只标的进入日期、退出与数据缺失原因、完整交易、成本和贡献明细均在 JSON 中。",
            "",
            "## 证据强度与产品化边界",
            "",
            "- **可产品化：中等证据。** 250 日历史、60 日成交额、完成周期信号、次日开盘执行这些防后验与可交易性规则可作为研究/产品基础设施。",
            "- **可产品化：低到中等证据。** ST 可作为当前观察池的风险准入或对照信号，但不能据此替换默认策略。",
            "- **仅研究：低证据。** “主题 ETF 的 ST 结构性优于宽基”尚未证明。",
            "- **仅研究：低证据。** 当前缓存主题池的收益水平不可外推到历史全市场或未来实盘。",
            "",
        ]
    )
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Research SuperTrend in causal dynamic local A-share ETF pools."
    )
    parser.add_argument("--data-dir", default=str(DATA_DIR))
    parser.add_argument("--universe-file", default=str(UNIVERSE_FILE))
    parser.add_argument("--output", default=str(OUTPUT_FILE))
    parser.add_argument("--report", default=str(REPORT_FILE))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_research(
        data_dir=Path(args.data_dir),
        universe_file=Path(args.universe_file),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_report(payload, Path(args.report))
    compact = {
        "output": str(output),
        "report": str(Path(args.report)),
        "dataAudit": payload["dataAudit"],
        "themeFull": {
            key: package["windows"]["full"]
            for key, package in payload["pools"]["theme_proxy_dynamic"]["strategies"].items()
        },
    }
    print(json.dumps(payload if args.json else compact, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
