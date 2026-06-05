#!/usr/bin/env python3
"""Audit RS rotation sensitivity to same-day versus next-open execution."""

from __future__ import annotations

import argparse
import json
import importlib.util
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

BACKTEST_PATH = BACKEND_DIR / "backtest.py"
ROBUSTNESS_PATH = ROOT / "scripts" / "research_rs_rotation_robustness.py"
DATA_DIR = BACKEND_DIR / "data"

_BACKTEST_SPEC = importlib.util.spec_from_file_location("backtest", BACKTEST_PATH)
backtest = importlib.util.module_from_spec(_BACKTEST_SPEC)
_BACKTEST_SPEC.loader.exec_module(backtest)

_ROBUSTNESS_SPEC = importlib.util.spec_from_file_location("research_rs_rotation_robustness", ROBUSTNESS_PATH)
robustness = importlib.util.module_from_spec(_ROBUSTNESS_SPEC)
_ROBUSTNESS_SPEC.loader.exec_module(robustness)


def _date_str(value) -> str:
    return pd.Timestamp(value).date().isoformat()


def _price_on_date(df: Optional[pd.DataFrame], as_of, column: str) -> Optional[float]:
    if df is None or df.empty:
        return None
    ts = pd.Timestamp(as_of)
    if ts not in df.index:
        return None
    value = df.loc[ts].get(column)
    if isinstance(value, pd.Series):
        value = value.iloc[-1]
    return None if pd.isna(value) else float(value)


def _close_on_or_before(df: Optional[pd.DataFrame], as_of) -> Optional[float]:
    if df is None or df.empty or "Close" not in df.columns:
        return None
    window = df[df.index <= pd.Timestamp(as_of)]
    if window.empty:
        return None
    value = window.iloc[-1].get("Close")
    return None if pd.isna(value) else float(value)


def simulate_rs_rotation_next_open(
    daily_frames_by_symbol: Dict[str, pd.DataFrame],
    top_n: int = 5,
    rebalance_days: int = 20,
    lookback_bars: int = 60,
    start: Optional[str] = None,
    end: Optional[str] = None,
    fee_bps: float = 5.0,
    slippage_bps: float = 5.0,
    min_history_bars: int = 250,
    min_avg_volume: float = 1e8,
    volume_lookback: int = 60,
    per_class_filters: Optional[Dict[str, Tuple[pd.DataFrame, str]]] = None,
) -> Dict[str, object]:
    all_dates = set()
    for df in daily_frames_by_symbol.values():
        if df is not None and not df.empty:
            all_dates.update(df.index)
    dates = sorted(all_dates)
    if start:
        dates = [date for date in dates if date >= pd.Timestamp(start)]
    if end:
        dates = [date for date in dates if date <= pd.Timestamp(end)]
    if not dates:
        return {"mode": "rs_rotation_next_open", "totalReturnPct": 0.0, "maxDrawdownPct": 0.0, "equityCurve": []}

    fee_factor = fee_bps / 10_000
    slip_factor = slippage_bps / 10_000
    monthly_cache: Dict[int, pd.DataFrame] = {}
    portfolio_cash = 1.0
    holdings: Dict[str, Dict[str, object]] = {}
    peak = 1.0
    max_drawdown = 0.0
    equity_curve = []
    last_signal_idx = -rebalance_days
    pending_target_symbols: Optional[List[str]] = None
    pending_signal_date = None

    def _portfolio_value_close(as_of) -> float:
        total = portfolio_cash
        for sym, pos in holdings.items():
            price = _close_on_or_before(daily_frames_by_symbol.get(sym), as_of) or float(pos["cost_price"])
            total += float(pos["shares"]) * price
        return total

    def _portfolio_value_open(as_of) -> float:
        total = portfolio_cash
        for sym, pos in holdings.items():
            price = _price_on_date(daily_frames_by_symbol.get(sym), as_of, "Open")
            if price is None:
                price = _close_on_or_before(daily_frames_by_symbol.get(sym), as_of) or float(pos["cost_price"])
            total += float(pos["shares"]) * price
        return total

    def _execute_rebalance(target_symbols: List[str], exec_date) -> None:
        nonlocal portfolio_cash, holdings
        target_set = set(target_symbols)
        for sym in list(set(holdings.keys()) - target_set):
            pos = holdings.pop(sym)
            price = _price_on_date(daily_frames_by_symbol.get(sym), exec_date, "Open")
            if price is None:
                price = _close_on_or_before(daily_frames_by_symbol.get(sym), exec_date) or float(pos["cost_price"])
            portfolio_cash += float(pos["shares"]) * price * (1 - slip_factor) * (1 - fee_factor)

        current_equity = _portfolio_value_open(exec_date)
        desired_values = {symbol: current_equity / top_n for symbol in target_symbols}

        for sym in list(holdings.keys()):
            price = _price_on_date(daily_frames_by_symbol.get(sym), exec_date, "Open")
            if price is None:
                price = _close_on_or_before(daily_frames_by_symbol.get(sym), exec_date) or float(holdings[sym]["cost_price"])
            current_value = float(holdings[sym]["shares"]) * price
            desired = desired_values.get(sym, 0.0)
            if current_value > desired:
                sell_value = current_value - desired
                shares_to_sell = sell_value / price if price > 0 else 0.0
                holdings[sym]["shares"] = float(holdings[sym]["shares"]) - shares_to_sell
                portfolio_cash += shares_to_sell * price * (1 - slip_factor) * (1 - fee_factor)
                if float(holdings[sym]["shares"]) <= 1e-12:
                    holdings.pop(sym)

        for sym, desired in desired_values.items():
            price = _price_on_date(daily_frames_by_symbol.get(sym), exec_date, "Open")
            if price is None or price <= 0:
                price = _close_on_or_before(daily_frames_by_symbol.get(sym), exec_date)
            if price is None or price <= 0:
                continue
            current_value = float(holdings.get(sym, {}).get("shares", 0.0)) * price
            buy_value = max(0.0, desired - current_value)
            if buy_value <= 0:
                continue
            net_cost = min(buy_value * (1 + fee_factor), portfolio_cash)
            shares = (net_cost / (1 + fee_factor)) / (price * (1 + slip_factor))
            portfolio_cash -= net_cost
            if sym in holdings:
                holdings[sym]["shares"] = float(holdings[sym]["shares"]) + shares
            else:
                holdings[sym] = {"shares": shares, "cost_price": price * (1 + slip_factor), "entry_date": exec_date}

    for idx, date in enumerate(dates):
        execution_date = None
        if pending_target_symbols is not None and pending_signal_date is not None and date > pending_signal_date:
            _execute_rebalance(pending_target_symbols, date)
            execution_date = date
            pending_target_symbols = None
            pending_signal_date = None

        equity = _portfolio_value_close(date)
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak * 100 if peak else 0.0
        max_drawdown = max(max_drawdown, drawdown)
        equity_curve.append(
            {
                "date": _date_str(date),
                "equity": equity,
                "drawdownPct": drawdown,
                "openPositions": len(holdings),
                "holdings": sorted(holdings.keys()),
                "executionDate": _date_str(execution_date) if execution_date is not None else None,
            }
        )

        if idx - last_signal_idx >= rebalance_days and idx < len(dates) - 1:
            last_signal_idx = idx
            pending_target_symbols = [
                symbol
                for symbol in backtest._rs_rank_symbols(
                    daily_frames_by_symbol,
                    date,
                    top_n,
                    lookback_bars,
                    min_history_bars,
                    min_avg_volume,
                    volume_lookback,
                    0.0,
                    per_class_filters,
                    None,
                    "none",
                    None,
                    monthly_cache,
                    None,
                )
                if symbol != backtest._RS_CASH_SYMBOL
            ]
            pending_signal_date = date

    total_return_pct = (equity_curve[-1]["equity"] - 1) * 100 if equity_curve else 0.0
    return {
        "mode": "rs_rotation_next_open",
        "topN": top_n,
        "rebalanceDays": rebalance_days,
        "lookbackBars": lookback_bars,
        "startDate": _date_str(dates[0]),
        "endDate": _date_str(dates[-1]),
        "totalReturnPct": total_return_pct,
        "maxDrawdownPct": max_drawdown,
        "equityCurve": equity_curve,
    }


def _stats(portfolio: Dict[str, object]) -> Dict[str, object]:
    total_return = float(portfolio.get("totalReturnPct") or 0.0)
    max_drawdown = float(portfolio.get("maxDrawdownPct") or 0.0)
    return {
        "totalReturnPct": total_return,
        "maxDrawdownPct": max_drawdown,
        "returnDrawdownRatio": total_return / max_drawdown if max_drawdown else None,
        "startDate": portfolio.get("startDate"),
        "endDate": portfolio.get("endDate"),
    }


def build_lookahead_audit(start: str = "2015-01-01", end: str = "2026-06-05", data_dir: Path = DATA_DIR) -> Dict[str, object]:
    universes = robustness.build_static_universes()
    filters = robustness.build_filter_specs()
    variants = {}
    for name in ["a_share_broad", "a_share_core_current", "us_available"]:
        symbols = universes[name] if name in universes else [s for s in universes["us_requested"] if robustness._load_frame(s, data_dir) is not None]
        frames, missing = robustness._load_frames(symbols, data_dir)
        filter_spec = filters[name]
        per_class_filters = robustness._resolve_filter_frames(filter_spec, data_dir)
        same_day = backtest.simulate_rs_rotation_portfolio(
            frames,
            top_n=min(5, max(1, len(frames))),
            rebalance_days=20,
            lookback_bars=60,
            start=start,
            end=end,
            fee_bps=5.0,
            slippage_bps=5.0,
            min_history_bars=0,
            min_avg_volume=float(filter_spec.get("minAvgVolume") or 0.0),
            per_class_filters=per_class_filters,
        )
        next_open = simulate_rs_rotation_next_open(
            frames,
            top_n=min(5, max(1, len(frames))),
            rebalance_days=20,
            lookback_bars=60,
            start=start,
            end=end,
            fee_bps=5.0,
            slippage_bps=5.0,
            min_history_bars=0,
            min_avg_volume=float(filter_spec.get("minAvgVolume") or 0.0),
            per_class_filters=per_class_filters,
        )
        same_stats = _stats(same_day)
        next_stats = _stats(next_open)
        variants[name] = {
            "missingSymbols": missing,
            "sameDayClose": same_stats,
            "nextOpen": next_stats,
            "impact": {
                "returnPctDiff": next_stats["totalReturnPct"] - same_stats["totalReturnPct"],
                "maxDrawdownPctDiff": next_stats["maxDrawdownPct"] - same_stats["maxDrawdownPct"],
                "ratioDiff": (
                    next_stats["returnDrawdownRatio"] - same_stats["returnDrawdownRatio"]
                    if next_stats["returnDrawdownRatio"] is not None and same_stats["returnDrawdownRatio"] is not None
                    else None
                ),
            },
        }
    return {
        "params": {
            "start": start,
            "end": end,
            "dataDir": str(data_dir),
            "sameDayCloseDefinition": "rank/filter with data <= signal day and rebalance at same-day close",
            "nextOpenDefinition": "rank/filter with data <= signal day and rebalance at next trading day's open",
        },
        "variants": variants,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit RS rotation same-day close versus next-open execution.")
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default="2026-06-05")
    parser.add_argument("--data-dir", default=str(DATA_DIR))
    parser.add_argument(
        "--output",
        default=str(BACKEND_DIR / "backtest_results" / "rs_rotation_lookahead_audit_2026-06-05.json"),
    )
    args = parser.parse_args()
    payload = build_lookahead_audit(start=args.start, end=args.end, data_dir=Path(args.data_dir))
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(json.dumps({"output": str(output_path), "variants": payload["variants"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
