#!/usr/bin/env python3
"""Incrementally refresh every cached daily/weekly parquet and report freshness.

This is the one entry point for "update the local data" (``make update-data``).
It reuses the backend's own refresh path (``analysis.batch_fetch_and_update``),
bounds it with a timeout, prints a freshness table, and always terminates with
``os._exit``: pyarrow's thread pool can deadlock at normal interpreter exit on
macOS, which leaves callers waiting forever after the work is done.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
DEFAULT_DATA_DIR = BACKEND_DIR / "data"


def list_cached_symbols(data_dir: Path) -> List[str]:
    return sorted(
        path.name[: -len(".parquet")]
        for path in Path(data_dir).glob("*.parquet")
        if not path.name.endswith("_weekly.parquet")
    )


def market_group(symbol: str) -> str:
    symbol = symbol.upper()
    if symbol.endswith((".SS", ".SZ")):
        return "a_share"
    if symbol.endswith("-USD"):
        return "crypto"
    if symbol.endswith(".HK") or symbol == "^HSI":
        return "hk"
    return "us"


def find_stale(
    last_dates: Dict[str, Optional[date]],
    today: date,
    max_age_days: int = 5,
) -> Dict[str, str]:
    """Return {symbol: reason} for symbols behind their market peers or too old.

    Comparing against peers in the same market absorbs weekends and holidays;
    the age limit catches a whole market (data source) failing at once.
    """
    newest: Dict[str, date] = {}
    for symbol, last in last_dates.items():
        if last is not None:
            group = market_group(symbol)
            newest[group] = max(newest.get(group, last), last)

    stale: Dict[str, str] = {}
    cutoff = today - timedelta(days=max_age_days)
    for symbol, last in sorted(last_dates.items()):
        if last is None:
            stale[symbol] = "unreadable"
        elif last < newest[market_group(symbol)]:
            stale[symbol] = f"{last} < peers {newest[market_group(symbol)]}"
        elif last < cutoff:
            stale[symbol] = f"{last} older than {max_age_days} days"
    return stale


def read_last_dates(symbols: Iterable[str], data_dir: Path) -> Dict[str, Optional[date]]:
    import pandas as pd

    result: Dict[str, Optional[date]] = {}
    for symbol in symbols:
        try:
            frame = pd.read_parquet(Path(data_dir) / f"{symbol}.parquet")
            result[symbol] = pd.Timestamp(frame.index[-1]).date()
        except Exception:
            result[symbol] = None
    return result


def refresh_with_timeout(symbols: List[str], timeout_seconds: float) -> Optional[str]:
    """Run the backend refresh in a daemon thread; return an error text or None."""
    outcome: Dict[str, str] = {}

    def worker() -> None:
        try:
            if str(BACKEND_DIR) not in sys.path:
                sys.path.insert(0, str(BACKEND_DIR))
            import analysis

            analysis.batch_fetch_and_update(symbols)
        except Exception as exc:  # reported, then the freshness check decides
            outcome["error"] = f"{type(exc).__name__}: {exc}"

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout_seconds)
    if thread.is_alive():
        return f"refresh still running after {timeout_seconds:.0f}s, gave up waiting"
    return outcome.get("error")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--symbols", nargs="*", default=[], help="default: every cached symbol")
    parser.add_argument("--timeout", type=float, default=300.0, help="seconds to wait for the refresh")
    parser.add_argument("--max-age-days", type=int, default=5)
    parser.add_argument("--check-only", action="store_true", help="skip the refresh, only report")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    symbols = [s.upper() for s in args.symbols] or list_cached_symbols(data_dir)
    print(f"symbols: {len(symbols)}", flush=True)

    error = None
    if not args.check_only:
        error = refresh_with_timeout(symbols, args.timeout)
        if error:
            print(f"refresh error: {error}", flush=True)

    last_dates = read_last_dates(symbols, data_dir)
    stale = find_stale(last_dates, date.today(), args.max_age_days)
    newest = max((d for d in last_dates.values() if d), default=None)
    print(f"newest bar: {newest}  stale: {len(stale)}", flush=True)
    for symbol, reason in stale.items():
        print(f"  STALE {symbol}: {reason}", flush=True)
    return 1 if (error or stale) else 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
