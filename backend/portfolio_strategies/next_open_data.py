from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from collections.abc import Iterable
from zoneinfo import ZoneInfo

import pandas as pd

from .frozen_xquant import normalize_daily


REQUIRED_COLUMNS = ("Open", "High", "Low", "Close", "Volume")
SHANGHAI = ZoneInfo("Asia/Shanghai")
NEW_YORK = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def _completed_through(symbol: str, now: datetime) -> date:
    aware = now.replace(tzinfo=SHANGHAI) if now.tzinfo is None else now
    if symbol.endswith("-USD"):
        return aware.astimezone(UTC).date() - timedelta(days=1)
    if symbol.endswith((".SS", ".SZ")):
        local = aware.astimezone(SHANGHAI)
        return local.date() if local.time() >= time(15, 10) else local.date() - timedelta(days=1)
    if symbol.endswith(".HK"):
        local = aware.astimezone(SHANGHAI)
        return local.date() if local.time() >= time(16, 20) else local.date() - timedelta(days=1)
    local = aware.astimezone(NEW_YORK)
    cutoff = time(18, 10) if symbol == "GC=F" else time(16, 10)
    return local.date() if local.time() >= cutoff else local.date() - timedelta(days=1)


def load_next_open_frames(
    data_dir: Path | str,
    symbols: Iterable[str],
    *,
    through_date: date | None = None,
    as_of: datetime | None = None,
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """Load each symbol on its own calendar without cross-market alignment."""
    root = Path(data_dir)
    frames: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    for symbol in dict.fromkeys(symbols):
        path = root / f"{symbol}.parquet"
        if not path.exists():
            errors[symbol] = "missing_parquet"
            continue
        try:
            frame = normalize_daily(pd.read_parquet(path))
        except Exception as exc:
            errors[symbol] = f"read_error:{type(exc).__name__}"
            continue
        missing = [column for column in REQUIRED_COLUMNS if column not in frame]
        if missing:
            errors[symbol] = "missing_columns:" + ",".join(missing)
            continue
        cutoff = through_date
        if as_of is not None:
            completed = _completed_through(symbol, as_of)
            cutoff = min(cutoff, completed) if cutoff is not None else completed
        if cutoff is not None:
            frame = frame.loc[:pd.Timestamp(cutoff)]
        if frame.empty:
            errors[symbol] = "no_completed_rows"
            continue
        frames[symbol] = frame
    return frames, errors
