import argparse
import json
from pathlib import Path
from typing import Iterable

import pandas as pd

from analysis import (
    _memory_cache,
    _memory_cache_lock,
    batch_fetch_and_update,
)
from analysis_constants import DATA_DIR
from analysis_data import (
    _has_current_data_source,
    _has_valid_price_history,
    _invalidate_data_source_metadata,
    _is_a_share_symbol,
)


def _watchlist_symbols(watchlist_path: Path) -> set[str]:
    if not watchlist_path.exists():
        return set()
    try:
        payload = json.loads(watchlist_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return set()

    groups = payload.get("groups", []) if isinstance(payload, dict) else payload
    if not isinstance(groups, list):
        return set()

    symbols = set()
    for group in groups:
        if not isinstance(group, dict):
            continue
        for item in group.get("symbols", []):
            symbol = item.get("symbol") if isinstance(item, dict) else item
            if isinstance(symbol, str) and _is_a_share_symbol(symbol):
                symbols.add(symbol.upper())
    return symbols


def discover_a_share_symbols(
    data_dir: Path,
    watchlist_path: Path,
) -> list[str]:
    symbols = _watchlist_symbols(watchlist_path)
    if data_dir.exists():
        for path in data_dir.glob("*.parquet"):
            if path.stem.endswith("_weekly"):
                continue
            if _is_a_share_symbol(path.stem):
                symbols.add(path.stem.upper())
    return sorted(symbols)


def _verify_refreshed_symbol(data_dir: Path, symbol: str) -> bool:
    file_path = data_dir / f"{symbol}.parquet"
    weekly_path = data_dir / f"{symbol}_weekly.parquet"
    if not file_path.exists() or not weekly_path.exists():
        return False
    if not _has_current_data_source(str(file_path), symbol):
        return False
    try:
        df = pd.read_parquet(file_path)
        df_weekly = pd.read_parquet(weekly_path)
    except Exception:
        return False
    daily_indicators = {"EMA20", "EMA50", "ADX", "MACD_DIF", "ATR"}
    weekly_indicators = {"EMA20", "MACD_W", "RSI_14", "ATR"}
    return (
        df.index.is_monotonic_increasing
        and _has_valid_price_history(df, symbol)
        and daily_indicators.issubset(df.columns)
        and df_weekly.index.is_monotonic_increasing
        and weekly_indicators.issubset(df_weekly.columns)
    )


def run_migration(
    symbols: Iterable[str],
    *,
    data_dir: Path,
    force: bool,
) -> dict:
    normalized = sorted({
        symbol.upper()
        for symbol in symbols
        if _is_a_share_symbol(symbol)
    })

    if force:
        for symbol in normalized:
            _invalidate_data_source_metadata(
                str(data_dir / f"{symbol}.parquet")
            )

    with _memory_cache_lock:
        for symbol in normalized:
            _memory_cache.pop(symbol, None)

    if normalized:
        batch_fetch_and_update(normalized)

    refreshed = [
        symbol
        for symbol in normalized
        if _verify_refreshed_symbol(data_dir, symbol)
    ]
    refreshed_set = set(refreshed)
    failed = [
        symbol for symbol in normalized if symbol not in refreshed_set
    ]
    return {
        "requested": len(normalized),
        "refreshed": refreshed,
        "failed": failed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh persisted A-share data from TickFlow.",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=Path(DATA_DIR))
    parser.add_argument(
        "--watchlist",
        type=Path,
        default=Path("watchlist.json"),
    )
    parser.add_argument("symbols", nargs="*")
    args = parser.parse_args()

    symbols = (
        args.symbols
        if args.symbols
        else discover_a_share_symbols(args.data_dir, args.watchlist)
    )
    report = run_migration(
        symbols,
        data_dir=args.data_dir,
        force=args.force,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
