#!/usr/bin/env python3
"""Backfill long-range daily and weekly parquet market data caches."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import analysis  # noqa: E402


DEFAULT_UNIVERSE_FILES = [
    BACKEND_DIR / "universes" / "a_share_etf_core.json",
    BACKEND_DIR / "universes" / "etf_core.json",
]
DEFAULT_DATA_DIR = BACKEND_DIR / "data"


def _unique(symbols: Iterable[str]) -> List[str]:
    result = []
    for symbol in symbols:
        normalized = str(symbol).strip().upper()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def load_symbols_from_universe_files(paths: Iterable[Path]) -> List[str]:
    symbols: List[str] = []
    for path in paths:
        payload = json.loads(Path(path).read_text())
        raw_symbols = payload.get("symbols", payload) if isinstance(payload, dict) else payload
        for item in raw_symbols:
            symbol = item.get("symbol") if isinstance(item, dict) else item
            if isinstance(symbol, str):
                symbols.append(symbol)
    return _unique(symbols)


def _load_local_ohlcv(path: Path) -> Optional[pd.DataFrame]:
    if not path.exists():
        return None
    frame = pd.read_parquet(path)
    if frame.empty:
        return None
    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.to_datetime(frame.index)
    if frame.index.tz is not None:
        frame.index = frame.index.tz_localize(None)
    return analysis._extract_ohlcv(frame).sort_index()


def _normalize_downloaded(frame: Optional[pd.DataFrame], symbol: str) -> Optional[pd.DataFrame]:
    if frame is None or frame.empty:
        return None
    frame = analysis._normalize_downloaded_ohlcv_columns(frame.copy(), symbol)
    if frame.index.tz is not None:
        frame.index = frame.index.tz_localize(None)
    frame = analysis._extract_ohlcv(frame)
    frame = analysis._drop_incomplete_ohlcv_rows(frame)
    return frame.sort_index() if frame is not None and not frame.empty else None


def _download_yfinance(symbol: str, start: str, end: str) -> Optional[pd.DataFrame]:
    with analysis.global_download_lock:
        raw = analysis.yf.download(
            symbol,
            start=pd.Timestamp(start),
            end=pd.Timestamp(end) + pd.Timedelta(days=1),
            interval="1d",
            progress=False,
            auto_adjust=False,
            threads=False,
        )
    return _normalize_downloaded(raw, symbol)


def _download_eastmoney_if_applicable(symbol: str, start: str, end: str) -> Optional[pd.DataFrame]:
    if not analysis._is_a_share_symbol(symbol):
        return None
    return analysis._fetch_eastmoney_daily(
        symbol,
        pd.Timestamp(start).to_pydatetime(),
        (pd.Timestamp(end) + pd.Timedelta(days=1)).to_pydatetime(),
    )


def _merge_full_history(*frames: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    valid = [frame for frame in frames if frame is not None and not frame.empty]
    if not valid:
        return None
    merged = pd.concat(valid).sort_index()
    merged = merged[~merged.index.duplicated(keep="last")]
    merged = analysis._drop_incomplete_ohlcv_rows(merged)
    return merged.sort_index() if merged is not None and not merged.empty else None


def backfill_symbol(
    symbol: str,
    start: str,
    end: str,
    data_dir: Path = DEFAULT_DATA_DIR,
    sleep_seconds: float = 0.0,
) -> Dict[str, object]:
    symbol = symbol.upper()
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    daily_path = data_dir / f"{symbol}.parquet"
    weekly_path = data_dir / f"{symbol}_weekly.parquet"

    local = _load_local_ohlcv(daily_path)
    yfinance_frame = _download_yfinance(symbol, start, end)
    eastmoney_frame = _download_eastmoney_if_applicable(symbol, start, end)
    merged = _merge_full_history(local, yfinance_frame, eastmoney_frame)

    if sleep_seconds > 0:
        time.sleep(sleep_seconds)

    if merged is None or merged.empty:
        return {
            "symbol": symbol,
            "status": "missing",
            "rows": 0,
            "startDate": None,
            "endDate": None,
            "usedEastmoney": eastmoney_frame is not None and not eastmoney_frame.empty,
            "usedYfinance": yfinance_frame is not None and not yfinance_frame.empty,
        }

    daily = analysis._calculate_daily_indicators(merged.copy())
    weekly = analysis._calculate_weekly_indicators(daily.copy())
    daily.to_parquet(daily_path)
    weekly.to_parquet(weekly_path)

    return {
        "symbol": symbol,
        "status": "updated",
        "rows": int(len(daily)),
        "weeklyRows": int(len(weekly)),
        "startDate": daily.index.min().date().isoformat(),
        "endDate": daily.index.max().date().isoformat(),
        "usedEastmoney": eastmoney_frame is not None and not eastmoney_frame.empty,
        "usedYfinance": yfinance_frame is not None and not yfinance_frame.empty,
    }


def backfill_symbols(
    symbols: Iterable[str],
    start: str,
    end: str,
    data_dir: Path = DEFAULT_DATA_DIR,
    sleep_seconds: float = 0.0,
) -> Dict[str, object]:
    results = []
    for symbol in _unique(symbols):
        try:
            result = backfill_symbol(symbol, start=start, end=end, data_dir=data_dir, sleep_seconds=sleep_seconds)
        except Exception as exc:
            result = {"symbol": symbol.upper(), "status": "error", "error": str(exc)}
        print(json.dumps(result, ensure_ascii=False), flush=True)
        results.append(result)
    return {
        "params": {
            "start": start,
            "end": end,
            "dataDir": str(data_dir),
            "symbolCount": len(results),
        },
        "summary": {
            "updated": sum(1 for row in results if row.get("status") == "updated"),
            "missing": sum(1 for row in results if row.get("status") == "missing"),
            "error": sum(1 for row in results if row.get("status") == "error"),
            "earliestStartDate": min((row["startDate"] for row in results if row.get("startDate")), default=None),
        },
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill long-range market data parquet caches.")
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default=pd.Timestamp.today().date().isoformat())
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--universe-file", action="append", default=[])
    parser.add_argument("--symbols", nargs="*", default=[])
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    parser.add_argument(
        "--output",
        default=str(BACKEND_DIR / "backtest_results" / "historical_data_backfill_2026-06-05.json"),
    )
    args = parser.parse_args()

    universe_files = [Path(path) for path in args.universe_file] if args.universe_file else DEFAULT_UNIVERSE_FILES
    symbols = _unique(args.symbols + load_symbols_from_universe_files(universe_files))
    payload = backfill_symbols(
        symbols,
        start=args.start,
        end=args.end,
        data_dir=Path(args.data_dir),
        sleep_seconds=args.sleep_seconds,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(json.dumps({"output": str(output_path), **payload["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
