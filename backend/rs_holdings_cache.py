"""Small disk cache for the read-only RS holdings endpoint."""

import json
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd


def is_valid(payload: dict, *, today: date | None = None) -> bool:
    cached_date = payload.get("cached_date")
    if not cached_date:
        return False
    try:
        cached = datetime.fromisoformat(cached_date).date()
    except (TypeError, ValueError):
        return False
    current = today or date.today()
    if cached > current:
        return False
    calendar = xcals.get_calendar("XSHG")
    sessions = calendar.sessions_in_range(
        calendar.first_session, pd.Timestamp(current)
    )
    latest_session = sessions[-1].date() if len(sessions) else current
    return cached >= latest_session


def load(path: str | os.PathLike[str]) -> dict | None:
    cache_path = Path(path)
    if not cache_path.exists():
        return None
    try:
        with cache_path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload.get("data") if isinstance(payload, dict) and is_valid(payload) else None
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def save(path: str | os.PathLike[str], data: dict) -> None:
    cache_path = Path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "cached_date": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "data": data,
    }
    with cache_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
