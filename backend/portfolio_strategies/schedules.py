from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from collections.abc import Sequence

import exchange_calendars as xcals
import pandas as pd

from .models import StrategyConfig


@dataclass(frozen=True)
class ScheduleStatus:
    due: bool
    last_signal_date: date | None
    next_signal_date: date | None
    sessions_until_next: int | None
    missing_signal_session: bool


def _normalize_sessions(sessions: Sequence[pd.Timestamp]) -> pd.DatetimeIndex:
    normalized = pd.DatetimeIndex(sessions)
    if normalized.tz is not None:
        normalized = normalized.tz_localize(None)
    return normalized.normalize().unique().sort_values()


def xshg_sessions(start: date | str, end: date | str) -> pd.DatetimeIndex:
    calendar = xcals.get_calendar("XSHG")
    sessions = calendar.sessions_in_range(pd.Timestamp(start), pd.Timestamp(end))
    return _normalize_sessions(sessions)


def every_n_session_dates(
    reference_date: date | str,
    sessions: Sequence[pd.Timestamp],
    *,
    every: int = 10,
) -> set[pd.Timestamp]:
    if every <= 0:
        raise ValueError("every must be positive")
    observed = _normalize_sessions(sessions)
    if observed.empty:
        return set()

    reference = pd.Timestamp(reference_date).normalize()
    calendar_sessions = xshg_sessions(
        min(reference, observed[0]).date(),
        max(reference, observed[-1]).date(),
    )
    try:
        reference_position = int(calendar_sessions.get_loc(reference))
    except KeyError as exc:
        raise ValueError(f"Reference date is not an XSHG session: {reference.date()}") from exc

    observed_set = set(observed)
    return {
        session
        for position, session in enumerate(calendar_sessions)
        if (position - reference_position) % every == 0
        and session in observed_set
    }


def bimonthly_signal_dates(
    sessions: Sequence[pd.Timestamp],
    *,
    signal_days: Sequence[int] = (10, 25),
) -> set[pd.Timestamp]:
    normalized = _normalize_sessions(sessions)
    if normalized.empty:
        return set()

    dates: set[pd.Timestamp] = set()
    months = pd.period_range(
        normalized.min().to_period("M"),
        normalized.max().to_period("M"),
        freq="M",
    )
    for month in months:
        month_sessions = normalized[normalized.to_period("M") == month]
        for day in signal_days:
            if day < 1 or day > month.days_in_month:
                continue
            anchor = pd.Timestamp(month.year, month.month, day)
            candidates = month_sessions[month_sessions >= anchor]
            if not candidates.empty:
                dates.add(candidates[0])
    return dates


def _expected_signal_dates(
    config: StrategyConfig,
    start: date,
    end: date,
) -> set[pd.Timestamp]:
    calendar_sessions = xshg_sessions(start, end)
    if config.strategy_id.startswith("btc_supertrend_satellite"):
        return every_n_session_dates(
            str(config.params["schedule_reference_date"]),
            calendar_sessions,
            every=int(config.params["rebalance_sessions"]),
        )
    return bimonthly_signal_dates(
        calendar_sessions,
        signal_days=tuple(config.params["signal_days"]),
    )


def schedule_status(
    config: StrategyConfig,
    as_of_date: date,
    observed_sessions: Sequence[pd.Timestamp],
) -> ScheduleStatus:
    observed = _normalize_sessions(observed_sessions)
    as_of = pd.Timestamp(as_of_date).normalize()
    if observed.empty:
        return ScheduleStatus(False, None, None, None, False)

    start = min(observed[0].date(), as_of_date)
    horizon = as_of_date + timedelta(days=60)
    expected = sorted(_expected_signal_dates(config, start, horizon))
    observed_set = set(observed)

    missed = [
        signal_date
        for signal_date in expected
        if observed[0] <= signal_date <= as_of and signal_date not in observed_set
    ]
    due = as_of in expected and as_of in observed_set
    observed_formal = [
        signal_date
        for signal_date in expected
        if signal_date <= as_of and signal_date in observed_set
    ]
    last_signal = observed_formal[-1].date() if observed_formal else None

    if missed:
        next_signal = missed[0]
    else:
        next_signal = next(
            (signal_date for signal_date in expected if signal_date > as_of),
            None,
        )

    sessions_until_next = None
    if next_signal is not None:
        future_sessions = xshg_sessions(
            (as_of + pd.Timedelta(days=1)).date(),
            next_signal.date(),
        )
        sessions_until_next = len(future_sessions)

    return ScheduleStatus(
        due=due,
        last_signal_date=last_signal,
        next_signal_date=next_signal.date() if next_signal is not None else None,
        sessions_until_next=sessions_until_next,
        missing_signal_session=bool(missed),
    )
