#!/usr/bin/env python3
"""Research A-share ETF weekly+daily SuperTrend equal-weight portfolios."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd
import pandas_ta as ta


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
DATA_DIR = BACKEND_DIR / "data"
UNIVERSE_FILE = BACKEND_DIR / "universes" / "a_share_etf_core.json"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

BACKTEST_PATH = BACKEND_DIR / "backtest.py"
ROBUSTNESS_PATH = ROOT / "scripts" / "research_rs_rotation_robustness.py"

_BACKTEST_SPEC = importlib.util.spec_from_file_location("backtest", BACKTEST_PATH)
backtest = importlib.util.module_from_spec(_BACKTEST_SPEC)
_BACKTEST_SPEC.loader.exec_module(backtest)

_ROBUSTNESS_SPEC = importlib.util.spec_from_file_location("research_rs_rotation_robustness", ROBUSTNESS_PATH)
robustness = importlib.util.module_from_spec(_ROBUSTNESS_SPEC)
_ROBUSTNESS_SPEC.loader.exec_module(robustness)


def _date_str(value) -> str:
    return pd.Timestamp(value).date().isoformat()


def _read_universe(path: Path = UNIVERSE_FILE) -> List[Dict[str, str]]:
    payload = json.loads(path.read_text())
    rows = []
    seen = set()
    for item in payload.get("symbols", []):
        symbol = str(item.get("symbol", "")).strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        rows.append(
            {
                "symbol": symbol,
                "name": str(item.get("name", "")),
                "bucket": str(item.get("bucket", "")),
            }
        )
    return rows


def build_universes(path: Path = UNIVERSE_FILE) -> Dict[str, List[str]]:
    rows = _read_universe(path)
    broad = [
        row["symbol"]
        for row in rows
        if row["bucket"] == "broad" and row["symbol"] not in {"159552.SZ", "588080.SS"}
    ]
    core = [row["symbol"] for row in rows]
    return {"a_share_broad": broad, "a_share_core": core}


def _load_frame(symbol: str, data_dir: Path = DATA_DIR) -> Optional[pd.DataFrame]:
    path = data_dir / f"{symbol.upper()}.parquet"
    if not path.exists():
        return None
    frame = pd.read_parquet(path).sort_index()
    required = {"Open", "High", "Low", "Close"}
    if frame.empty or not required.issubset(frame.columns):
        return None
    return frame


def load_frames(symbols: Iterable[str], data_dir: Path = DATA_DIR) -> Tuple[Dict[str, pd.DataFrame], List[str]]:
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


def _weekly_frame(daily: pd.DataFrame) -> pd.DataFrame:
    return (
        daily.sort_index()
        .resample("W")
        .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
        .dropna(subset=["Open", "High", "Low", "Close"])
    )


def _supertrend_dir(frame: pd.DataFrame, length: int = 7, multiplier: float = 3.0) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype="float64")
    st = ta.supertrend(frame["High"], frame["Low"], frame["Close"], length=length, multiplier=multiplier)
    if st is None or st.empty:
        return pd.Series(dtype="float64")
    dir_col = next((column for column in st.columns if str(column).startswith("SUPERTd_")), None)
    return st[dir_col].sort_index() if dir_col else pd.Series(dtype="float64")


def _latest_dir(series: pd.Series, as_of) -> Optional[int]:
    if series is None or series.empty:
        return None
    window = series[series.index <= pd.Timestamp(as_of)]
    if window.empty or pd.isna(window.iloc[-1]):
        return None
    return int(float(window.iloc[-1]))


def _trade_price(frame: pd.DataFrame, date) -> Optional[float]:
    row = frame.loc[pd.Timestamp(date)] if pd.Timestamp(date) in frame.index else None
    if row is None:
        return None
    value = row.get("Open")
    if pd.isna(value) or float(value) <= 0:
        value = row.get("Close")
    return None if pd.isna(value) or float(value) <= 0 else float(value)


def _close_on_or_before(frame: pd.DataFrame, date) -> Optional[float]:
    window = frame[frame.index <= pd.Timestamp(date)]
    if window.empty:
        return None
    value = window.iloc[-1].get("Close")
    return None if pd.isna(value) or float(value) <= 0 else float(value)


def _all_dates(frames: Dict[str, pd.DataFrame], start: Optional[str], end: Optional[str]) -> List[pd.Timestamp]:
    dates = set()
    start_ts = pd.Timestamp(start) if start else None
    end_ts = pd.Timestamp(end) if end else None
    for frame in frames.values():
        for date in frame.index:
            ts = pd.Timestamp(date)
            if start_ts is not None and ts < start_ts:
                continue
            if end_ts is not None and ts > end_ts:
                continue
            dates.add(ts)
    return sorted(dates)


def _eligible_symbols(
    date: pd.Timestamp,
    daily_dirs: Dict[str, pd.Series],
    weekly_dirs: Dict[str, pd.Series],
) -> List[str]:
    eligible = []
    for symbol in sorted(daily_dirs.keys()):
        if _latest_dir(daily_dirs[symbol], date) == 1 and _latest_dir(weekly_dirs[symbol], date) == 1:
            eligible.append(symbol)
    return eligible


def simulate_weekly_daily_st_equal_weight(
    frames: Dict[str, pd.DataFrame],
    start: Optional[str] = None,
    end: Optional[str] = None,
    fee_bps: float = 5.0,
    slippage_bps: float = 5.0,
    st_length: int = 7,
    st_multiplier: float = 3.0,
) -> Dict[str, object]:
    dates = _all_dates(frames, start, end)
    if not dates:
        return {"mode": "weekly_daily_st_equal_weight", "totalReturnPct": 0.0, "maxDrawdownPct": 0.0, "equityCurve": []}

    daily_dirs = {symbol: _supertrend_dir(frame, st_length, st_multiplier) for symbol, frame in frames.items()}
    weekly_dirs = {
        symbol: _supertrend_dir(_weekly_frame(frame), st_length, st_multiplier)
        for symbol, frame in frames.items()
    }

    fee = fee_bps / 10_000
    slip = slippage_bps / 10_000
    cash = 1.0
    shares_by_symbol: Dict[str, float] = {}
    pending_targets: Optional[List[str]] = None
    peak = 1.0
    max_drawdown = 0.0
    curve = []
    turnover_count = 0

    def _portfolio_value(date: pd.Timestamp, use_trade_price: bool = False) -> float:
        total = cash
        for symbol, shares in shares_by_symbol.items():
            price = _trade_price(frames[symbol], date) if use_trade_price else _close_on_or_before(frames[symbol], date)
            if price:
                total += shares * price
        return total

    def _rebalance(date: pd.Timestamp, targets: List[str]) -> None:
        nonlocal cash, turnover_count
        target_set = set(targets)
        equity = _portfolio_value(date, use_trade_price=True)
        target_weight = 1.0 / len(targets) if targets else 0.0

        for symbol in list(shares_by_symbol.keys()):
            price = _trade_price(frames[symbol], date)
            if not price:
                continue
            current_value = shares_by_symbol[symbol] * price
            target_value = equity * target_weight if symbol in target_set else 0.0
            if current_value <= target_value:
                continue
            sell_value = current_value - target_value
            shares_sold = min(shares_by_symbol[symbol], sell_value / price)
            if shares_sold <= 0:
                continue
            shares_by_symbol[symbol] -= shares_sold
            if shares_by_symbol[symbol] <= 1e-12:
                shares_by_symbol.pop(symbol, None)
            cash += shares_sold * price * (1 - slip) * (1 - fee)
            turnover_count += 1

        equity = _portfolio_value(date, use_trade_price=True)
        for symbol in targets:
            price = _trade_price(frames[symbol], date)
            if not price:
                continue
            current_value = shares_by_symbol.get(symbol, 0.0) * price
            target_value = equity * target_weight
            buy_value = target_value - current_value
            if buy_value <= 0:
                continue
            gross_cash_needed = buy_value * (1 + slip) * (1 + fee)
            if gross_cash_needed > cash:
                buy_value = cash / ((1 + slip) * (1 + fee))
                gross_cash_needed = cash
            if buy_value <= 0:
                continue
            shares_by_symbol[symbol] = shares_by_symbol.get(symbol, 0.0) + buy_value / price
            cash -= gross_cash_needed
            turnover_count += 1

    for date in dates:
        if pending_targets is not None:
            _rebalance(date, pending_targets)

        equity = _portfolio_value(date)
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak * 100 if peak else 0.0
        max_drawdown = max(max_drawdown, drawdown)
        curve.append(
            {
                "date": _date_str(date),
                "equity": equity,
                "drawdownPct": drawdown,
                "openPositions": len(shares_by_symbol),
                "holdings": sorted(shares_by_symbol.keys()),
                "eligibleCount": len(pending_targets or []),
            }
        )

        pending_targets = _eligible_symbols(date, daily_dirs, weekly_dirs)

    total_return = (curve[-1]["equity"] - 1.0) * 100 if curve else 0.0
    return {
        "mode": "weekly_daily_st_equal_weight",
        "stLength": st_length,
        "stMultiplier": st_multiplier,
        "executionMode": "close_confirm_next_open",
        "rebalanceMode": "daily_equal_weight_all_eligible",
        "startDate": _date_str(dates[0]),
        "endDate": _date_str(dates[-1]),
        "totalReturnPct": total_return,
        "maxDrawdownPct": max_drawdown,
        "averagePositionCount": sum(point["openPositions"] for point in curve) / len(curve) if curve else 0.0,
        "averageEligibleCount": sum(point["eligibleCount"] for point in curve) / len(curve) if curve else 0.0,
        "turnoverCount": turnover_count,
        "equityCurve": curve,
    }


def _run_rs_baseline(
    frames: Dict[str, pd.DataFrame],
    data_dir: Path,
    start: str,
    end: str,
    top_n: int = 5,
) -> Dict[str, object]:
    market = _load_frame("510300.SS", data_dir)
    per_class_filters = {"a_share": (market, "monthly_macd")} if market is not None else None
    return backtest.simulate_rs_rotation_portfolio(
        frames,
        top_n=min(top_n, max(1, len(frames))),
        rebalance_days=20,
        lookback_bars=60,
        start=start,
        end=end,
        fee_bps=5.0,
        slippage_bps=5.0,
        min_history_bars=0,
        min_avg_volume=1e8,
        per_class_filters=per_class_filters,
    )


def _with_windows(portfolio: Dict[str, object]) -> Dict[str, object]:
    curve = portfolio.get("equityCurve") or []
    annual = robustness.annual_stats(curve)
    return {
        **portfolio,
        "summary": robustness._portfolio_stats(portfolio),
        "annual": annual,
        "rolling3Year": robustness.rolling_year_stats(curve, 3),
        "rolling5Year": robustness.rolling_year_stats(curve, 5),
    }


def build_research(
    start: str = "2015-01-01",
    end: str = "2026-06-06",
    data_dir: Path = DATA_DIR,
    universe_file: Path = UNIVERSE_FILE,
) -> Dict[str, object]:
    universes = build_universes(universe_file)
    variants = {}
    for name, symbols in universes.items():
        frames, missing = load_frames(symbols, data_dir)
        st_equal_weight = simulate_weekly_daily_st_equal_weight(frames, start=start, end=end)
        rs_baseline = _run_rs_baseline(frames, data_dir, start, end)
        variants[name] = {
            "name": name,
            "requestedSymbols": symbols,
            "usedSymbols": sorted(frames.keys()),
            "missingSymbols": missing,
            "symbolCount": len(frames),
            "weeklyDailyStEqualWeight": _with_windows(st_equal_weight),
            "rsMonthlyMacdBaseline": _with_windows(rs_baseline),
        }

    return {
        "params": {
            "start": start,
            "end": end,
            "dataDir": str(data_dir),
            "universeFile": str(universe_file),
            "st": {"length": 7, "multiplier": 3.0},
            "costs": {"feeBps": 5.0, "slippageBps": 5.0},
            "execution": "Signals are confirmed at close and executed at next available trading day's open.",
        },
        "variants": variants,
        "summary": {
            name: {
                "weeklyDailyStEqualWeight": variant["weeklyDailyStEqualWeight"]["summary"],
                "rsMonthlyMacdBaseline": variant["rsMonthlyMacdBaseline"]["summary"],
            }
            for name, variant in variants.items()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Research A-share weekly+daily ST equal-weight portfolios.")
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default="2026-06-06")
    parser.add_argument("--data-dir", default=str(DATA_DIR))
    parser.add_argument("--universe-file", default=str(UNIVERSE_FILE))
    parser.add_argument(
        "--output",
        default=str(BACKEND_DIR / "backtest_results" / "a_share_weekly_daily_st_equal_weight_2026-06-06.json"),
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_research(
        start=args.start,
        end=args.end,
        data_dir=Path(args.data_dir),
        universe_file=Path(args.universe_file),
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    compact = {"output": str(output_path), "params": payload["params"], "summary": payload["summary"]}
    print(json.dumps(payload if args.json else compact, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
