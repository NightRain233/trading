#!/usr/bin/env python3
"""Research robustness of RS rotation across universes and time windows."""

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
DATA_DIR = BACKEND_DIR / "data"
_BACKTEST_SPEC = importlib.util.spec_from_file_location("backtest", BACKTEST_PATH)
backtest = importlib.util.module_from_spec(_BACKTEST_SPEC)
_BACKTEST_SPEC.loader.exec_module(backtest)


A_SHARE_BROAD = [
    "510050.SS",
    "510300.SS",
    "510500.SS",
    "512100.SS",
    "159915.SZ",
    "588000.SS",
]

A_SHARE_BROAD_EXTENDED = A_SHARE_BROAD + [
    "159552.SZ",
]

A_SHARE_STYLE = [
    "510880.SS",
    "512890.SS",
    "512040.SS",
    "159201.SZ",
]

A_SHARE_SECTOR_THEME = [
    "512880.SS",
    "512000.SS",
    "512010.SS",
    "512170.SS",
    "512760.SS",
    "512660.SS",
    "512720.SS",
    "515880.SS",
    "515790.SS",
    "513010.SS",
    "513120.SS",
    "513910.SS",
    "515070.SS",
    "159326.SZ",
    "159869.SZ",
    "159967.SZ",
]

US_CORE_REQUESTED = [
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

GLOBAL_EXTRA_REQUESTED = [
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
    "BTC-USD",
    "GC=F",
]


def _unique(symbols: List[str]) -> List[str]:
    result = []
    for symbol in symbols:
        normalized = symbol.upper()
        if normalized not in result:
            result.append(normalized)
    return result


def build_static_universes() -> Dict[str, List[str]]:
    current_core = _unique(A_SHARE_BROAD_EXTENDED + A_SHARE_STYLE + A_SHARE_SECTOR_THEME + ["588080.SS"])
    return {
        "a_share_broad": _unique(A_SHARE_BROAD),
        "a_share_broad_extended": _unique(A_SHARE_BROAD_EXTENDED),
        "a_share_broad_style": _unique(A_SHARE_BROAD + A_SHARE_STYLE),
        "a_share_core_current": current_core,
        "us_requested": _unique(US_CORE_REQUESTED),
        "global_requested": _unique(current_core + GLOBAL_EXTRA_REQUESTED),
    }


def build_filter_specs() -> Dict[str, Dict[str, object]]:
    a_share_filter = {"perClassFilters": {"a_share": ("510300.SS", "monthly_macd")}, "minAvgVolume": 1e8}
    return {
        "a_share_broad": a_share_filter,
        "a_share_broad_extended": a_share_filter,
        "a_share_broad_style": a_share_filter,
        "a_share_core_current": a_share_filter,
        "us_available": {"perClassFilters": {"us": ("SPY", "monthly_macd"), "commodity": ("GC=F", "monthly_macd")}, "minAvgVolume": 0.0},
        "global_available": {
            "perClassFilters": {
                "a_share": ("510300.SS", "monthly_macd"),
                "us": ("SPY", "monthly_macd"),
                "crypto": ("BTC-USD", "monthly_macd"),
                "commodity": ("GC=F", "monthly_macd"),
            },
            "minAvgVolume": 0.0,
        },
    }


def _date_str(value) -> str:
    return pd.Timestamp(value).date().isoformat()


def _load_frame(symbol: str, data_dir: Path = DATA_DIR) -> Optional[pd.DataFrame]:
    path = data_dir / f"{symbol.upper()}.parquet"
    if not path.exists():
        return None
    frame = pd.read_parquet(path).sort_index()
    return frame if not frame.empty else None


def _load_frames(symbols: List[str], data_dir: Path) -> Tuple[Dict[str, pd.DataFrame], List[str]]:
    frames: Dict[str, pd.DataFrame] = {}
    missing: List[str] = []
    for symbol in symbols:
        frame = _load_frame(symbol, data_dir)
        if frame is None:
            missing.append(symbol)
        else:
            frames[symbol] = frame
    return frames, missing


def _resolve_filter_frames(
    filter_spec: Dict[str, object],
    data_dir: Path,
) -> Dict[str, Tuple[pd.DataFrame, str]]:
    resolved = {}
    for asset_class, spec in dict(filter_spec.get("perClassFilters") or {}).items():
        symbol, mode = spec
        frame = _load_frame(str(symbol), data_dir)
        if frame is not None:
            resolved[asset_class] = (frame, str(mode))
    return resolved


def _portfolio_stats(portfolio: Dict[str, object]) -> Dict[str, object]:
    total_return = float(portfolio.get("totalReturnPct") or 0.0)
    max_drawdown = float(portfolio.get("maxDrawdownPct") or 0.0)
    return {
        "totalReturnPct": total_return,
        "maxDrawdownPct": max_drawdown,
        "returnDrawdownRatio": total_return / max_drawdown if max_drawdown else None,
        "startDate": portfolio.get("startDate"),
        "endDate": portfolio.get("endDate"),
    }


def annual_stats(curve: List[Dict[str, object]]) -> List[Dict[str, object]]:
    by_year: Dict[str, List[Dict[str, object]]] = {}
    for point in curve:
        year = str(pd.Timestamp(point["date"]).year)
        by_year.setdefault(year, []).append(point)
    rows = []
    previous_equity = None
    for year, points in sorted(by_year.items()):
        start_equity = previous_equity if previous_equity is not None else float(points[0]["equity"])
        end_equity = float(points[-1]["equity"])
        rows.append(
            {
                "year": year,
                "returnPct": (end_equity / start_equity - 1) * 100 if start_equity else 0.0,
                "maxDrawdownPct": max(float(point.get("drawdownPct") or 0.0) for point in points),
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
        rows.append(
            {
                "startYear": window[0]["year"],
                "endYear": window[-1]["year"],
                "returnPct": (end_equity / start_equity - 1) * 100 if start_equity else 0.0,
                "maxDrawdownPct": max(float(row["maxDrawdownPct"]) for row in window),
                "returnDrawdownRatio": ((end_equity / start_equity - 1) * 100) / max(float(row["maxDrawdownPct"]) for row in window)
                if max(float(row["maxDrawdownPct"]) for row in window)
                else None,
            }
        )
    return rows


def _concentration_stats(annual: List[Dict[str, object]]) -> Dict[str, object]:
    if not annual:
        return {"positiveYearCount": 0, "yearCount": 0, "bestYearContributionPct": None, "worstYear": None}
    positive_returns = [max(0.0, float(row["returnPct"])) for row in annual]
    total_positive = sum(positive_returns)
    best_positive = max(positive_returns) if positive_returns else 0.0
    worst = min(annual, key=lambda row: float(row["returnPct"]))
    return {
        "positiveYearCount": sum(1 for row in annual if float(row["returnPct"]) > 0),
        "yearCount": len(annual),
        "bestYearContributionPct": best_positive / total_positive if total_positive else None,
        "worstYear": {"year": worst["year"], "returnPct": worst["returnPct"]},
    }


def _run_variant(
    name: str,
    symbols: List[str],
    filter_spec: Dict[str, object],
    data_dir: Path,
    start: str,
    end: str,
    top_n: int,
) -> Dict[str, object]:
    frames, missing = _load_frames(symbols, data_dir)
    per_class_filters = _resolve_filter_frames(filter_spec, data_dir)
    portfolio = backtest.simulate_rs_rotation_portfolio(
        frames,
        top_n=min(top_n, max(1, len(frames))),
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
    curve = portfolio.get("equityCurve") or []
    annual = annual_stats(curve)
    rolling3 = rolling_year_stats(curve, 3)
    rolling5 = rolling_year_stats(curve, 5)
    return {
        "name": name,
        "requestedSymbols": symbols,
        "usedSymbols": sorted(frames.keys()),
        "missingSymbols": missing,
        "symbolCount": len(frames),
        "topN": min(top_n, max(1, len(frames))) if frames else top_n,
        "filterSpec": filter_spec,
        "summary": _portfolio_stats(portfolio),
        "annual": annual,
        "rolling3Year": rolling3,
        "rolling5Year": rolling5,
        "concentration": _concentration_stats(annual),
        "portfolio": portfolio,
    }


def build_rs_rotation_robustness_research(
    start: str = "2015-01-01",
    end: str = "2026-06-05",
    data_dir: Path = DATA_DIR,
) -> Dict[str, object]:
    universes = build_static_universes()
    filters = build_filter_specs()
    variants = {}
    for name in ["a_share_broad", "a_share_broad_extended", "a_share_broad_style", "a_share_core_current"]:
        variants[name] = _run_variant(name, universes[name], filters[name], data_dir, start, end, top_n=5)

    available_us_symbols = [symbol for symbol in universes["us_requested"] if _load_frame(symbol, data_dir) is not None]
    variants["us_available"] = _run_variant(
        "us_available",
        available_us_symbols,
        filters["us_available"],
        data_dir,
        start,
        end,
        top_n=5,
    )

    available_global_symbols = [symbol for symbol in universes["global_requested"] if _load_frame(symbol, data_dir) is not None]
    variants["global_available"] = _run_variant(
        "global_available",
        available_global_symbols,
        filters["global_available"],
        data_dir,
        start,
        end,
        top_n=5,
    )

    return {
        "params": {
            "start": start,
            "end": end,
            "dataDir": str(data_dir),
            "rebalanceDays": 20,
            "lookbackBars": 60,
            "feeBps": 5.0,
            "slippageBps": 5.0,
            "researchCaveat": "Static universe comparisons test selection sensitivity but do not reconstruct full historical ETF membership.",
        },
        "universeDefinitions": universes,
        "filterSpecs": filters,
        "variants": variants,
        "summary": {name: variant["summary"] for name, variant in variants.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Research RS rotation robustness across universes.")
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default="2026-06-05")
    parser.add_argument("--data-dir", default=str(DATA_DIR))
    parser.add_argument(
        "--output",
        default=str(BACKEND_DIR / "backtest_results" / "rs_rotation_robustness_2026-06-05.json"),
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_rs_rotation_robustness_research(
        start=args.start,
        end=args.end,
        data_dir=Path(args.data_dir),
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    compact = {"output": str(output_path), "params": payload["params"], "summary": payload["summary"]}
    print(json.dumps(payload if args.json else compact, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
