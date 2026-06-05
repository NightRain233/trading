#!/usr/bin/env python3
"""Research pure SuperTrend portfolio strategies for A-share ETFs.

This script is offline-only: it reads the local universe and parquet cache,
then writes a research JSON payload. It does not fetch data or mutate backend
strategy code.
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
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

DATA_DIR = BACKEND_DIR / "data"
UNIVERSE_FILE = BACKEND_DIR / "universes" / "a_share_etf_core.json"
RESULTS_DIR = BACKEND_DIR / "backtest_results"
REPORT_FILE = ROOT / "docs" / "a-share-etf-pure-st-portfolio-2026-06-06.md"
BACKTEST_PATH = BACKEND_DIR / "backtest.py"

ST_LENGTH = 7
ST_MULTIPLIER = 3.0
FEE_BPS = 5.0
SLIPPAGE_BPS = 5.0
RS_TOP_N = 5
RS_LOOKBACK_BARS = 60
RS_REBALANCE_DAYS = 20
MIN_AVG_VOLUME = 1e8
VOLUME_LOOKBACK = 60

_BACKTEST_SPEC = importlib.util.spec_from_file_location("backtest", BACKTEST_PATH)
backtest = importlib.util.module_from_spec(_BACKTEST_SPEC)
_BACKTEST_SPEC.loader.exec_module(backtest)


def _date_str(value) -> str:
    return pd.Timestamp(value).date().isoformat()


def _load_universe_symbols(path: Path = UNIVERSE_FILE) -> List[str]:
    payload = json.loads(path.read_text())
    raw_symbols = payload.get("symbols", payload) if isinstance(payload, dict) else payload
    symbols: List[str] = []
    for item in raw_symbols:
        symbol = item.get("symbol") if isinstance(item, dict) else item
        if not isinstance(symbol, str):
            continue
        normalized = symbol.strip().upper()
        if normalized and normalized not in symbols:
            symbols.append(normalized)
    return symbols


def _load_frame(symbol: str, data_dir: Path = DATA_DIR) -> Optional[pd.DataFrame]:
    path = data_dir / f"{symbol.upper()}.parquet"
    if not path.exists():
        return None
    frame = pd.read_parquet(path).sort_index()
    if frame.empty:
        return None
    frame.index = pd.DatetimeIndex(frame.index)
    return frame


def _load_weekly_frame(symbol: str, daily: pd.DataFrame, data_dir: Path = DATA_DIR) -> pd.DataFrame:
    path = data_dir / f"{symbol.upper()}_weekly.parquet"
    if path.exists():
        weekly = pd.read_parquet(path).sort_index()
        if not weekly.empty:
            weekly.index = pd.DatetimeIndex(weekly.index)
            return weekly
    return (
        daily.resample("W")
        .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
        .dropna(subset=["Open", "High", "Low", "Close"])
    )


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
    return st[dir_col].sort_index() if dir_col else pd.Series(dtype="float64")


def _latest_signal_state(signal: pd.Series, as_of) -> Optional[int]:
    if signal is None or signal.empty:
        return None
    ordered = signal.sort_index()
    window = ordered[ordered.index <= pd.Timestamp(as_of)]
    if window.empty or pd.isna(window.iloc[-1]):
        return None
    return int(float(window.iloc[-1]))


def _equal_weights(symbols: Iterable[str]) -> Dict[str, float]:
    ordered = list(dict.fromkeys(symbols))
    if not ordered:
        return {}
    weight = 1.0 / len(ordered)
    return {symbol: weight for symbol in ordered}


def _price_at(df: pd.DataFrame, date, field: str = "Close") -> Optional[float]:
    if df is None or df.empty or field not in df.columns:
        return None
    ts = pd.Timestamp(date)
    if ts not in df.index:
        return None
    value = df.loc[ts, field]
    if isinstance(value, pd.Series):
        value = value.iloc[-1]
    return None if pd.isna(value) else float(value)


def _close_on_or_before(df: pd.DataFrame, as_of) -> Optional[float]:
    if df is None or df.empty or "Close" not in df.columns:
        return None
    window = df[df.index <= pd.Timestamp(as_of)].dropna(subset=["Close"])
    if window.empty:
        return None
    return float(window.iloc[-1]["Close"])


def _tradable_symbols(frames: Dict[str, pd.DataFrame], date) -> List[str]:
    return [
        symbol
        for symbol, frame in frames.items()
        if _price_at(frame, date, "Open") is not None or _price_at(frame, date, "Close") is not None
    ]


def _rank_by_relative_strength(
    frames: Dict[str, pd.DataFrame],
    candidates: Iterable[str],
    as_of,
    top_n: int = RS_TOP_N,
    lookback_bars: int = RS_LOOKBACK_BARS,
    min_history_bars: int = 0,
    min_avg_volume: float = MIN_AVG_VOLUME,
    volume_lookback: int = VOLUME_LOOKBACK,
) -> List[str]:
    scores: List[tuple[str, float]] = []
    as_of_ts = pd.Timestamp(as_of)
    for symbol in candidates:
        frame = frames.get(symbol)
        if frame is None or frame.empty:
            continue
        window = frame[frame.index <= as_of_ts].dropna(subset=["Close"])
        if len(window) < min_history_bars or len(window) <= lookback_bars:
            continue
        if min_avg_volume > 0 and "Volume" in window.columns:
            avg_volume = window["Volume"].tail(volume_lookback).mean()
            if pd.isna(avg_volume) or float(avg_volume) < min_avg_volume:
                continue
        current = float(window.iloc[-1]["Close"])
        prior = float(window.iloc[-lookback_bars - 1]["Close"])
        if prior > 0:
            scores.append((symbol, (current - prior) / prior))
    scores.sort(key=lambda item: item[1], reverse=True)
    return [symbol for symbol, _score in scores[:top_n]]


def _target_symbols_for_strategy(
    strategy: str,
    frames: Dict[str, pd.DataFrame],
    daily_signals: Dict[str, pd.Series],
    weekly_signals: Dict[str, pd.Series],
    date,
    signal_as_of,
    top_n: int,
    lookback_bars: int,
    min_avg_volume: float,
) -> List[str]:
    tradable = _tradable_symbols(frames, date)
    if strategy == "equal_weight_buy_hold":
        return tradable

    daily_bulls = [
        symbol
        for symbol in tradable
        if _latest_signal_state(daily_signals.get(symbol, pd.Series(dtype="float64")), signal_as_of) == 1
    ]
    if strategy == "daily_st_equal_weight":
        return daily_bulls

    if strategy == "weekly_daily_st_equal_weight":
        return [
            symbol
            for symbol in daily_bulls
            if _latest_signal_state(weekly_signals.get(symbol, pd.Series(dtype="float64")), signal_as_of) == 1
        ]

    if strategy == "daily_st_top5_rs":
        return _rank_by_relative_strength(
            frames,
            daily_bulls,
            signal_as_of,
            top_n=top_n,
            lookback_bars=lookback_bars,
            min_history_bars=0,
            min_avg_volume=min_avg_volume,
        )

    raise ValueError(f"Unsupported strategy: {strategy}")


def _annual_stats(equity_curve: List[Dict[str, object]]) -> List[Dict[str, object]]:
    by_year: Dict[str, List[Dict[str, object]]] = {}
    for point in equity_curve:
        by_year.setdefault(str(pd.Timestamp(point["date"]).year), []).append(point)

    rows: List[Dict[str, object]] = []
    for year, points in sorted(by_year.items()):
        start_equity = float(points[0]["equity"])
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
                "averageExposure": sum(float(point.get("actualExposure") or 0.0) for point in points) / len(points),
            }
        )
    return rows


def simulate_weighted_portfolio(
    frames: Dict[str, pd.DataFrame],
    daily_signals: Dict[str, pd.Series],
    weekly_signals: Dict[str, pd.Series],
    strategy: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    fee_bps: float = FEE_BPS,
    slippage_bps: float = SLIPPAGE_BPS,
    top_n: int = RS_TOP_N,
    lookback_bars: int = RS_LOOKBACK_BARS,
    min_avg_volume: float = MIN_AVG_VOLUME,
) -> Dict[str, object]:
    dates = sorted({date for frame in frames.values() for date in frame.index})
    if start:
        dates = [date for date in dates if date >= pd.Timestamp(start)]
    if end:
        dates = [date for date in dates if date <= pd.Timestamp(end)]
    if not dates:
        return {
            "strategy": strategy,
            "totalReturnPct": 0.0,
            "maxDrawdownPct": 0.0,
            "returnDrawdownRatio": None,
            "averageExposure": 0.0,
            "equityCurve": [],
            "annual": [],
        }

    fee_factor = fee_bps / 10_000
    slip_factor = slippage_bps / 10_000
    cash = 1.0
    holdings: Dict[str, float] = {}
    peak = 1.0
    max_drawdown = 0.0
    equity_curve: List[Dict[str, object]] = []
    previous_date = dates[0] - pd.Timedelta(days=1)

    def price_for_trade(symbol: str, date) -> Optional[float]:
        frame = frames[symbol]
        return _price_at(frame, date, "Open") or _price_at(frame, date, "Close")

    def price_for_mark(symbol: str, date) -> Optional[float]:
        frame = frames[symbol]
        return _price_at(frame, date, "Close") or _close_on_or_before(frame, date)

    for date in dates:
        open_equity = cash
        open_prices: Dict[str, float] = {}
        for symbol, shares in holdings.items():
            price = price_for_trade(symbol, date) or price_for_mark(symbol, previous_date)
            if price is None:
                price = 0.0
            open_prices[symbol] = price
            open_equity += shares * price

        target_symbols = _target_symbols_for_strategy(
            strategy,
            frames,
            daily_signals,
            weekly_signals,
            date,
            previous_date,
            top_n,
            lookback_bars,
            min_avg_volume,
        )
        target_weights = _equal_weights(target_symbols)

        for symbol in target_symbols:
            price = price_for_trade(symbol, date)
            if price is not None:
                open_prices[symbol] = price

        for symbol in list(holdings.keys()):
            price = open_prices.get(symbol) or price_for_trade(symbol, date)
            if price is None or price <= 0:
                continue
            current_value = holdings[symbol] * price
            desired_value = open_equity * target_weights.get(symbol, 0.0)
            if current_value <= desired_value + 1e-12:
                continue
            shares_to_sell = min(holdings[symbol], (current_value - desired_value) / price)
            cash += shares_to_sell * price * (1 - slip_factor) * (1 - fee_factor)
            holdings[symbol] -= shares_to_sell
            if holdings[symbol] <= 1e-12:
                holdings.pop(symbol, None)

        buy_orders: List[tuple[str, float, float]] = []
        for symbol, target_weight in target_weights.items():
            price = open_prices.get(symbol)
            if price is None or price <= 0:
                continue
            current_value = holdings.get(symbol, 0.0) * price
            desired_value = open_equity * target_weight
            buy_value = max(0.0, desired_value - current_value)
            if buy_value > 1e-12:
                buy_orders.append((symbol, price, buy_value))

        total_cash_needed = sum(buy_value * (1 + fee_factor) for _symbol, _price, buy_value in buy_orders)
        scale = min(1.0, cash / total_cash_needed) if total_cash_needed > 0 else 1.0
        for symbol, price, buy_value in buy_orders:
            scaled_value = buy_value * scale
            cash_cost = scaled_value * (1 + fee_factor)
            if cash_cost <= 0 or cash <= 0:
                continue
            cash_cost = min(cash, cash_cost)
            gross_value = cash_cost / (1 + fee_factor)
            shares = gross_value / (price * (1 + slip_factor))
            cash -= cash_cost
            holdings[symbol] = holdings.get(symbol, 0.0) + shares

        close_equity = cash
        invested_value = 0.0
        marked_holdings: List[str] = []
        for symbol, shares in list(holdings.items()):
            price = price_for_mark(symbol, date)
            if price is None:
                continue
            value = shares * price
            close_equity += value
            invested_value += value
            marked_holdings.append(symbol)

        peak = max(peak, close_equity)
        drawdown = (peak - close_equity) / peak * 100 if peak else 0.0
        max_drawdown = max(max_drawdown, drawdown)
        equity_curve.append(
            {
                "date": _date_str(date),
                "equity": close_equity,
                "drawdownPct": drawdown,
                "actualExposure": invested_value / close_equity if close_equity else 0.0,
                "cashWeight": cash / close_equity if close_equity else 0.0,
                "openPositions": len(marked_holdings),
                "holdings": sorted(marked_holdings),
            }
        )
        previous_date = date

    total_return = (float(equity_curve[-1]["equity"]) - 1) * 100 if equity_curve else 0.0
    average_exposure = (
        sum(float(point["actualExposure"]) for point in equity_curve) / len(equity_curve)
        if equity_curve
        else 0.0
    )
    return {
        "strategy": strategy,
        "startDate": equity_curve[0]["date"] if equity_curve else None,
        "endDate": equity_curve[-1]["date"] if equity_curve else None,
        "totalReturnPct": total_return,
        "maxDrawdownPct": max_drawdown,
        "returnDrawdownRatio": total_return / max_drawdown if max_drawdown else None,
        "averageExposure": average_exposure,
        "equityCurve": equity_curve,
        "annual": _annual_stats(equity_curve),
    }


def _portfolio_stats(portfolio: Dict[str, object]) -> Dict[str, object]:
    total_return = float(portfolio.get("totalReturnPct") or 0.0)
    max_drawdown = float(portfolio.get("maxDrawdownPct") or 0.0)
    curve = portfolio.get("equityCurve") or []
    avg_exposure = portfolio.get("averageExposure")
    if avg_exposure is None and curve:
        avg_exposure = sum(float(point.get("actualExposure", 0.0) or 0.0) for point in curve) / len(curve)
    return {
        "totalReturnPct": total_return,
        "maxDrawdownPct": max_drawdown,
        "returnDrawdownRatio": total_return / max_drawdown if max_drawdown else None,
        "averageExposure": float(avg_exposure or 0.0),
        "startDate": portfolio.get("startDate"),
        "endDate": portfolio.get("endDate"),
    }


def _point_exposure(point: Dict[str, object], top_n: int = RS_TOP_N) -> float:
    if "actualExposure" in point and point.get("actualExposure") is not None:
        return float(point.get("actualExposure") or 0.0)
    open_positions = int(point.get("openPositions") or 0)
    return min(1.0, open_positions / top_n) if top_n > 0 else 0.0


def _annual_from_rs_portfolio(portfolio: Dict[str, object]) -> List[Dict[str, object]]:
    curve = portfolio.get("equityCurve") or []
    normalized = []
    for point in curve:
        normalized.append(
            {
                "date": point["date"],
                "equity": point["equity"],
                "drawdownPct": point.get("drawdownPct", 0.0),
                "actualExposure": _point_exposure(point),
            }
        )
    return _annual_stats(normalized)


def _format_pct(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}%"


def _format_ratio(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"


def _markdown_table(summary: Dict[str, Dict[str, object]], labels: Dict[str, str]) -> str:
    lines = [
        "| 策略 | 收益 | 最大回撤 | 收益/回撤 | 平均仓位 |",
        "|---|---:|---:|---:|---:|",
    ]
    for key, label in labels.items():
        stats = summary[key]
        lines.append(
            "| {label} | {ret} | {dd} | {ratio} | {exp} |".format(
                label=label,
                ret=_format_pct(stats.get("totalReturnPct")),
                dd=_format_pct(stats.get("maxDrawdownPct")),
                ratio=_format_ratio(stats.get("returnDrawdownRatio")),
                exp=_format_pct(float(stats.get("averageExposure") or 0.0) * 100),
            )
        )
    return "\n".join(lines)


def _annual_markdown_table(annual: Dict[str, List[Dict[str, object]]]) -> str:
    baseline = {row["year"]: row for row in annual["rs_monthly_macd_baseline"]}
    weekly_daily = {row["year"]: row for row in annual["weekly_daily_st_equal_weight"]}
    daily = {row["year"]: row for row in annual["daily_st_equal_weight"]}
    years = sorted(set(baseline) | set(weekly_daily) | set(daily))
    lines = [
        "| 年份 | RS+月MACD收益 | RS+月MACD回撤 | 周+日ST收益 | 周+日ST回撤 | 日ST收益 | 日ST回撤 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for year in years:
        base_row = baseline.get(year, {})
        weekly_row = weekly_daily.get(year, {})
        daily_row = daily.get(year, {})
        lines.append(
            "| {year} | {base_ret} | {base_dd} | {weekly_ret} | {weekly_dd} | {daily_ret} | {daily_dd} |".format(
                year=year,
                base_ret=_format_pct(base_row.get("returnPct")),
                base_dd=_format_pct(base_row.get("maxDrawdownPct")),
                weekly_ret=_format_pct(weekly_row.get("returnPct")),
                weekly_dd=_format_pct(weekly_row.get("maxDrawdownPct")),
                daily_ret=_format_pct(daily_row.get("returnPct")),
                daily_dd=_format_pct(daily_row.get("maxDrawdownPct")),
            )
        )
    return "\n".join(lines)


def _write_report(payload: Dict[str, object], report_file: Path = REPORT_FILE) -> None:
    summary = payload["summary"]
    labels = {
        "rs_monthly_macd_baseline": "RS 轮动 + 510300 月 MACD",
        "equal_weight_buy_hold": "A 股 ETF 等权参考",
        "daily_st_equal_weight": "纯日线 ST 等权",
        "weekly_daily_st_equal_weight": "周线+日线 ST 等权",
        "daily_st_top5_rs": "日线 ST 内 RS top5",
    }
    baseline = summary["rs_monthly_macd_baseline"]
    best_pure = max(
        ["daily_st_equal_weight", "weekly_daily_st_equal_weight", "daily_st_top5_rs"],
        key=lambda key: float(summary[key].get("returnDrawdownRatio") or -999),
    )
    best = summary[best_pure]
    conclusion = (
        "纯 ST 组合没有超过本次重算的 RS + 月 MACD 基准。"
        if float(best.get("returnDrawdownRatio") or 0.0) < float(baseline.get("returnDrawdownRatio") or 0.0)
        else "周线+日线 ST 组合在本次重算口径下超过了 RS + 月 MACD 基准。"
    )
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(
        "\n".join(
            [
                "# A 股 ETF 纯 SuperTrend 组合策略研究 2026-06-06",
                "",
                "## 口径",
                "",
                f"- 样本：`{payload['params']['universeFile']}`",
                f"- 本地可用 ETF：{payload['params']['symbolCount']} 个",
                f"- 区间：{payload['params']['start']} 到 {payload['params']['end']}",
                "- SuperTrend：`ST(7,3)`",
                "- 成本：单边手续费 5 bps，单边滑点 5 bps",
                "- 执行：收盘确认 ST 状态，下一组合交易日开盘调仓，收盘计净值。",
                "- 等权参考为每日按当日可交易 ETF 维护等权，主要用于观察全池暴露，不代表固定初始成分长期持有。",
                "",
                "## 全周期结果",
                "",
                _markdown_table(summary, labels),
                "",
                "## 年度表现",
                "",
                _annual_markdown_table(payload["annual"]),
                "",
                "## 结论",
                "",
                conclusion,
                "",
                (
                    f"本轮最佳纯 ST 变体是 `{best_pure}`：收益 {_format_pct(best.get('totalReturnPct'))}，"
                    f"回撤 {_format_pct(best.get('maxDrawdownPct'))}，收益/回撤 "
                    f"{_format_ratio(best.get('returnDrawdownRatio'))}。"
                ),
                (
                    "对照基准 `RS 轮动 + 510300 月 MACD`："
                    f"收益 {_format_pct(baseline.get('totalReturnPct'))}，"
                    f"回撤 {_format_pct(baseline.get('maxDrawdownPct'))}，"
                    f"收益/回撤 {_format_ratio(baseline.get('returnDrawdownRatio'))}。"
                ),
                "",
                "注意：已有报告中的旧 baseline 约为收益 47%、回撤 24%、收益/回撤约 2.0。"
                "本次当前缓存重算的 baseline 明显更弱，因此结论应理解为：周线+日线 ST 值得继续做公平复核，"
                "但还不能直接替代 RS + 月 MACD 默认策略。",
                "",
            ]
        ),
        encoding="utf-8",
    )


def build_research(
    start: str = "2021-05-06",
    end: str = "2026-06-05",
    universe_file: Path = UNIVERSE_FILE,
    data_dir: Path = DATA_DIR,
) -> Dict[str, object]:
    symbols = _load_universe_symbols(universe_file)
    frames = {
        symbol: frame
        for symbol in symbols
        if (frame := _load_frame(symbol, data_dir)) is not None
    }
    if not frames:
        raise RuntimeError(f"No cached parquet data found for {universe_file}")

    daily_signals: Dict[str, pd.Series] = {}
    weekly_signals: Dict[str, pd.Series] = {}
    for symbol, frame in frames.items():
        daily_signals[symbol] = _supertrend_dir(frame)
        weekly_signals[symbol] = _supertrend_dir(_load_weekly_frame(symbol, frame, data_dir))

    strategies = [
        "equal_weight_buy_hold",
        "daily_st_equal_weight",
        "weekly_daily_st_equal_weight",
        "daily_st_top5_rs",
    ]
    portfolios = {
        strategy: simulate_weighted_portfolio(
            frames,
            daily_signals=daily_signals,
            weekly_signals=weekly_signals,
            strategy=strategy,
            start=start,
            end=end,
            fee_bps=FEE_BPS,
            slippage_bps=SLIPPAGE_BPS,
            top_n=RS_TOP_N,
            lookback_bars=RS_LOOKBACK_BARS,
            min_avg_volume=MIN_AVG_VOLUME,
        )
        for strategy in strategies
    }

    market_df = frames.get("510300.SS")
    if market_df is None:
        raise RuntimeError("Missing 510300.SS parquet required for monthly MACD baseline")
    baseline = backtest.simulate_rs_rotation_portfolio(
        frames,
        top_n=RS_TOP_N,
        rebalance_days=RS_REBALANCE_DAYS,
        lookback_bars=RS_LOOKBACK_BARS,
        start=start,
        end=end,
        fee_bps=FEE_BPS,
        slippage_bps=SLIPPAGE_BPS,
        market_filter_df=market_df,
        market_filter_mode="monthly_macd",
        min_history_bars=0,
        min_avg_volume=MIN_AVG_VOLUME,
        volume_lookback=VOLUME_LOOKBACK,
    )
    baseline["startDate"] = baseline.get("startDate") or (baseline.get("equityCurve") or [{}])[0].get("date")
    baseline["endDate"] = baseline.get("endDate") or (baseline.get("equityCurve") or [{}])[-1].get("date")
    baseline["averageExposure"] = (
        sum(_point_exposure(point) for point in baseline.get("equityCurve", []))
        / len(baseline.get("equityCurve", []))
        if baseline.get("equityCurve")
        else 0.0
    )
    baseline["annual"] = _annual_from_rs_portfolio(baseline)
    portfolios["rs_monthly_macd_baseline"] = baseline

    ordered_keys = [
        "rs_monthly_macd_baseline",
        "equal_weight_buy_hold",
        "daily_st_equal_weight",
        "weekly_daily_st_equal_weight",
        "daily_st_top5_rs",
    ]
    summary = {key: _portfolio_stats(portfolios[key]) for key in ordered_keys}
    return {
        "params": {
            "start": start,
            "end": end,
            "universeFile": str(universe_file),
            "dataDir": str(data_dir),
            "symbolCount": len(frames),
            "stLength": ST_LENGTH,
            "stMultiplier": ST_MULTIPLIER,
            "feeBps": FEE_BPS,
            "slippageBps": SLIPPAGE_BPS,
            "rsTopN": RS_TOP_N,
            "rsLookbackBars": RS_LOOKBACK_BARS,
            "rsRebalanceDays": RS_REBALANCE_DAYS,
            "minAvgVolume": MIN_AVG_VOLUME,
            "knownBaselineReference": {
                "totalReturnPct": 47.0,
                "maxDrawdownPct": 24.0,
                "returnDrawdownRatio": 2.0,
            },
        },
        "summary": summary,
        "annual": {key: portfolios[key].get("annual", []) for key in ordered_keys},
        "portfolios": portfolios,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Research pure ST A-share ETF portfolio strategies.")
    parser.add_argument("--start", default="2021-05-06")
    parser.add_argument("--end", default="2026-06-05")
    parser.add_argument("--universe-file", default=str(UNIVERSE_FILE))
    parser.add_argument("--data-dir", default=str(DATA_DIR))
    parser.add_argument(
        "--output",
        default=str(RESULTS_DIR / "a_share_etf_pure_st_portfolio_2026-06-06.json"),
    )
    parser.add_argument("--report", default=str(REPORT_FILE))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_research(
        start=args.start,
        end=args.end,
        universe_file=Path(args.universe_file),
        data_dir=Path(args.data_dir),
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_report(payload, Path(args.report))

    compact = {
        "output": str(output_path),
        "report": str(Path(args.report)),
        "params": payload["params"],
        "summary": payload["summary"],
    }
    print(json.dumps(payload if args.json else compact, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
