#!/usr/bin/env python3
"""Compare US ETF RS rotation against simple beta benchmarks."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
DATA_DIR = BACKEND_DIR / "data"
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


US_POOL = [
    "SPY",
    "QQQ",
    "DIA",
    "IWM",
    "XLK",
    "XLF",
    "XLE",
    "XLV",
    "XLI",
    "XLY",
    "XLP",
    "XLU",
    "XLB",
    "XLRE",
    "SMH",
    "SOXX",
    "TLT",
    "GC=F",
]


def _date_str(value) -> str:
    return pd.Timestamp(value).date().isoformat()


def _load_frame(symbol: str, data_dir: Path = DATA_DIR) -> Optional[pd.DataFrame]:
    path = data_dir / f"{symbol.upper()}.parquet"
    if not path.exists():
        return None
    frame = pd.read_parquet(path).sort_index()
    return frame if not frame.empty and "Close" in frame.columns else None


def load_frames(symbols: Iterable[str], data_dir: Path = DATA_DIR) -> Tuple[Dict[str, pd.DataFrame], List[str]]:
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


def _close_on_or_before(frame: pd.DataFrame, date: pd.Timestamp) -> Optional[float]:
    if frame is None or frame.empty:
        return None
    window = frame[frame.index <= date].dropna(subset=["Close"])
    if window.empty:
        return None
    close = float(window.iloc[-1]["Close"])
    return close if close > 0 else None


def _all_dates(frames: Dict[str, pd.DataFrame], start: str, end: str) -> List[pd.Timestamp]:
    dates = set()
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    for frame in frames.values():
        for date in frame.index:
            if start_ts <= date <= end_ts:
                dates.add(pd.Timestamp(date))
    return sorted(dates)


def _summary_from_curve(curve: List[Dict[str, object]], mode: str) -> Dict[str, object]:
    if not curve:
        return {
            "mode": mode,
            "totalReturnPct": 0.0,
            "maxDrawdownPct": 0.0,
            "returnDrawdownRatio": None,
            "startDate": None,
            "endDate": None,
        }
    total_return = (float(curve[-1]["equity"]) - 1.0) * 100
    max_drawdown = max(float(point.get("drawdownPct") or 0.0) for point in curve)
    return {
        "mode": mode,
        "totalReturnPct": total_return,
        "maxDrawdownPct": max_drawdown,
        "returnDrawdownRatio": total_return / max_drawdown if max_drawdown else None,
        "startDate": curve[0]["date"],
        "endDate": curve[-1]["date"],
    }


def simulate_buy_hold(
    symbol: str,
    frame: pd.DataFrame,
    start: str,
    end: str,
    fee_bps: float = 5.0,
    slippage_bps: float = 5.0,
) -> Dict[str, object]:
    dates = _all_dates({symbol: frame}, start, end)
    if not dates:
        return {"mode": "buy_hold", "symbol": symbol, "equityCurve": [], **_summary_from_curve([], "buy_hold")}

    fee = fee_bps / 10_000
    slip = slippage_bps / 10_000
    first_close = _close_on_or_before(frame, dates[0])
    if not first_close:
        return {"mode": "buy_hold", "symbol": symbol, "equityCurve": [], **_summary_from_curve([], "buy_hold")}
    shares = (1.0 * (1 - fee)) / (first_close * (1 + slip))
    peak = 1.0
    curve = []
    for date in dates:
        close = _close_on_or_before(frame, date)
        if not close:
            continue
        equity = shares * close
        peak = max(peak, equity)
        curve.append(
            {
                "date": _date_str(date),
                "equity": equity,
                "drawdownPct": (peak - equity) / peak * 100 if peak else 0.0,
                "holdings": [symbol.upper()],
            }
        )
    return {
        **_summary_from_curve(curve, "buy_hold"),
        "symbol": symbol.upper(),
        "feeBps": fee_bps,
        "slippageBps": slippage_bps,
        "equityCurve": curve,
    }


WeightProvider = Callable[[pd.Timestamp, List[str]], Dict[str, float]]


def fixed_weight_provider(weights: Dict[str, float]) -> WeightProvider:
    normalized = {symbol.upper(): float(weight) for symbol, weight in weights.items()}

    def _provider(_date: pd.Timestamp, available_symbols: List[str]) -> Dict[str, float]:
        raw = {symbol: normalized[symbol] for symbol in available_symbols if symbol in normalized}
        total = sum(raw.values())
        return {symbol: weight / total for symbol, weight in raw.items()} if total else {}

    return _provider


def equal_weight_provider(_date: pd.Timestamp, available_symbols: List[str]) -> Dict[str, float]:
    if not available_symbols:
        return {}
    weight = 1.0 / len(available_symbols)
    return {symbol: weight for symbol in available_symbols}


def simulate_rebalanced_portfolio(
    frames: Dict[str, pd.DataFrame],
    start: str,
    end: str,
    weight_provider: WeightProvider,
    rebalance_days: int = 20,
    fee_bps: float = 5.0,
    slippage_bps: float = 5.0,
    mode: str = "weighted_rebalance",
) -> Dict[str, object]:
    dates = _all_dates(frames, start, end)
    if not dates:
        return {"mode": mode, "equityCurve": [], **_summary_from_curve([], mode)}

    fee = fee_bps / 10_000
    slip = slippage_bps / 10_000
    cash = 1.0
    shares_by_symbol: Dict[str, float] = {}
    peak = 1.0
    curve = []
    last_rebalance_idx = -rebalance_days
    used_symbols = set()

    def _value(date: pd.Timestamp) -> float:
        total = cash
        for symbol, shares in shares_by_symbol.items():
            close = _close_on_or_before(frames[symbol], date)
            if close:
                total += shares * close
        return total

    for idx, date in enumerate(dates):
        if idx - last_rebalance_idx >= rebalance_days:
            last_rebalance_idx = idx
            available = [symbol for symbol, frame in sorted(frames.items()) if _close_on_or_before(frame, date)]
            target_weights = weight_provider(date, available)
            target_weights = {symbol: weight for symbol, weight in target_weights.items() if symbol in frames and weight > 0}
            total_weight = sum(target_weights.values())
            target_weights = {symbol: weight / total_weight for symbol, weight in target_weights.items()} if total_weight else {}
            equity = _value(date)

            for symbol in list(shares_by_symbol.keys()):
                close = _close_on_or_before(frames[symbol], date)
                if not close:
                    continue
                current_value = shares_by_symbol[symbol] * close
                target_value = equity * target_weights.get(symbol, 0.0)
                if current_value <= target_value:
                    continue
                sell_value = current_value - target_value
                shares_sold = min(shares_by_symbol[symbol], sell_value / close)
                shares_by_symbol[symbol] -= shares_sold
                if shares_by_symbol[symbol] <= 1e-12:
                    shares_by_symbol.pop(symbol, None)
                cash += shares_sold * close * (1 - slip) * (1 - fee)

            equity = _value(date)
            for symbol, weight in sorted(target_weights.items()):
                close = _close_on_or_before(frames[symbol], date)
                if not close:
                    continue
                current_value = shares_by_symbol.get(symbol, 0.0) * close
                target_value = equity * weight
                buy_value = target_value - current_value
                if buy_value <= 0:
                    continue
                gross_cash_needed = buy_value * (1 + slip) * (1 + fee)
                if gross_cash_needed > cash:
                    buy_value = cash / ((1 + slip) * (1 + fee))
                    gross_cash_needed = cash
                if buy_value <= 0:
                    continue
                shares_by_symbol[symbol] = shares_by_symbol.get(symbol, 0.0) + buy_value / close
                cash -= gross_cash_needed
                used_symbols.add(symbol)

        equity = _value(date)
        peak = max(peak, equity)
        curve.append(
            {
                "date": _date_str(date),
                "equity": equity,
                "drawdownPct": (peak - equity) / peak * 100 if peak else 0.0,
                "holdings": sorted(shares_by_symbol.keys()),
            }
        )

    return {
        **_summary_from_curve(curve, mode),
        "rebalanceDays": rebalance_days,
        "feeBps": fee_bps,
        "slippageBps": slippage_bps,
        "usedSymbols": sorted(used_symbols),
        "equityCurve": curve,
    }


def build_benchmark_specs() -> List[Dict[str, object]]:
    return [
        {"name": "spy_buy_hold", "type": "buy_hold", "symbols": ["SPY"]},
        {"name": "qqq_buy_hold", "type": "buy_hold", "symbols": ["QQQ"]},
        {
            "name": "spy_ief_60_40",
            "type": "fixed_weight",
            "symbols": ["SPY", "IEF"],
            "weights": {"SPY": 0.6, "IEF": 0.4},
        },
        {
            "name": "spy_tlt_60_40",
            "type": "fixed_weight",
            "symbols": ["SPY", "TLT"],
            "weights": {"SPY": 0.6, "TLT": 0.4},
        },
        {"name": "equal_weight_us_pool", "type": "equal_weight", "symbols": US_POOL},
    ]


def _with_windows(portfolio: Dict[str, object]) -> Dict[str, object]:
    curve = portfolio.get("equityCurve") or []
    annual = robustness.annual_stats(curve)
    return {
        **portfolio,
        "annual": annual,
        "rolling3Year": robustness.rolling_year_stats(curve, 3),
        "rolling5Year": robustness.rolling_year_stats(curve, 5),
        "concentration": robustness._concentration_stats(annual),
    }


def build_us_rs_benchmark_comparison(
    start: str = "2015-01-01",
    end: str = "2026-06-05",
    data_dir: Path = DATA_DIR,
) -> Dict[str, object]:
    frames, missing_pool = load_frames(US_POOL, data_dir)
    per_class_filters = robustness._resolve_filter_frames(
        {"perClassFilters": {"us": ("SPY", "monthly_macd"), "commodity": ("GC=F", "monthly_macd")}},
        data_dir,
    )
    rs_rotation = backtest.simulate_rs_rotation_portfolio(
        frames,
        top_n=min(5, max(1, len(frames))),
        rebalance_days=20,
        lookback_bars=60,
        start=start,
        end=end,
        fee_bps=5.0,
        slippage_bps=5.0,
        min_history_bars=0,
        min_avg_volume=0.0,
        per_class_filters=per_class_filters,
    )

    benchmarks = {}
    skipped = {}
    for spec in build_benchmark_specs():
        name = str(spec["name"])
        required = [str(symbol).upper() for symbol in spec["symbols"]]
        spec_frames, missing = load_frames(required, data_dir)
        if missing:
            skipped[name] = {"reason": "missing_data", "missingSymbols": missing, "spec": spec}
            continue
        if spec["type"] == "buy_hold":
            symbol = required[0]
            benchmarks[name] = _with_windows(simulate_buy_hold(symbol, spec_frames[symbol], start, end))
        elif spec["type"] == "fixed_weight":
            benchmarks[name] = _with_windows(
                simulate_rebalanced_portfolio(
                    spec_frames,
                    start,
                    end,
                    fixed_weight_provider(dict(spec["weights"])),
                    mode=name,
                )
            )
        elif spec["type"] == "equal_weight":
            benchmarks[name] = _with_windows(
                simulate_rebalanced_portfolio(
                    spec_frames,
                    start,
                    end,
                    equal_weight_provider,
                    mode=name,
                )
            )

    summary = {"rs_us_rotation": robustness._portfolio_stats(rs_rotation)}
    summary.update({name: robustness._portfolio_stats(portfolio) for name, portfolio in benchmarks.items()})
    return {
        "params": {
            "start": start,
            "end": end,
            "dataDir": str(data_dir),
            "rs": {"topN": 5, "rebalanceDays": 20, "lookbackBars": 60, "feeBps": 5.0, "slippageBps": 5.0},
            "benchmarks": {"rebalanceDays": 20, "feeBps": 5.0, "slippageBps": 5.0},
            "caveat": "Local data currently starts at 2015 for US ETFs, so this does not cover 2000 or 2008 bear markets.",
        },
        "universe": {"requestedSymbols": US_POOL, "usedSymbols": sorted(frames.keys()), "missingSymbols": missing_pool},
        "summary": summary,
        "rsRotation": _with_windows(rs_rotation),
        "benchmarks": benchmarks,
        "skippedBenchmarks": skipped,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare US RS rotation against beta benchmarks.")
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default="2026-06-05")
    parser.add_argument("--data-dir", default=str(DATA_DIR))
    parser.add_argument(
        "--output",
        default=str(BACKEND_DIR / "backtest_results" / "us_rs_benchmark_comparison_2026-06-05.json"),
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_us_rs_benchmark_comparison(start=args.start, end=args.end, data_dir=Path(args.data_dir))
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    compact = {
        "output": str(output_path),
        "params": payload["params"],
        "summary": payload["summary"],
        "skippedBenchmarks": payload["skippedBenchmarks"],
    }
    print(json.dumps(payload if args.json else compact, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
