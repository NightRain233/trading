from datetime import date

import pandas as pd

from portfolio_strategies.registry import get_strategy
from portfolio_strategies.schedules import (
    bimonthly_signal_dates,
    every_n_session_dates,
    schedule_status,
    xshg_sessions,
)


def test_xshg_sessions_are_timezone_naive_normalized_dates():
    sessions = xshg_sessions(date(2026, 6, 1), date(2026, 6, 5))

    assert sessions.tolist() == list(pd.to_datetime([
        "2026-06-01",
        "2026-06-02",
        "2026-06-03",
        "2026-06-04",
        "2026-06-05",
    ]))
    assert sessions.tz is None
    assert all(timestamp == timestamp.normalize() for timestamp in sessions)


def test_btc_every_ten_session_schedule_uses_frozen_xquant_reference():
    sessions = xshg_sessions(date(2026, 6, 1), date(2026, 7, 15))

    signal_dates = every_n_session_dates(
        date(2026, 6, 15),
        sessions,
        every=10,
    )

    assert pd.Timestamp("2026-06-15") in signal_dates
    assert pd.Timestamp("2026-06-30") in signal_dates
    assert pd.Timestamp("2026-07-14") in signal_dates


def test_btc_schedule_phase_does_not_depend_on_observed_frame_start():
    full_sessions = xshg_sessions(date(2026, 6, 1), date(2026, 7, 15))
    later_sessions = full_sessions[full_sessions >= pd.Timestamp("2026-06-23")]

    full = every_n_session_dates(date(2026, 6, 15), full_sessions, every=10)
    later = every_n_session_dates(date(2026, 6, 15), later_sessions, every=10)

    assert later == {
        signal_date for signal_date in full if signal_date >= later_sessions[0]
    }


def test_bimonthly_schedule_shifts_to_next_exchange_session():
    sessions = xshg_sessions(date(2026, 1, 1), date(2026, 1, 31))

    assert bimonthly_signal_dates(sessions) == {
        pd.Timestamp("2026-01-12"),
        pd.Timestamp("2026-01-26"),
    }


def test_calendar_anchor_does_not_shift_into_next_month():
    sessions = xshg_sessions(date(2026, 1, 1), date(2026, 2, 5))

    assert bimonthly_signal_dates(sessions, signal_days=(31,)) == set()


def test_schedule_status_reports_next_date_and_remaining_sessions():
    config = get_strategy("btc_supertrend_satellite")
    observed = xshg_sessions(date(2026, 6, 1), date(2026, 6, 26))

    status = schedule_status(config, date(2026, 6, 26), observed)

    assert status.due is False
    assert status.last_signal_date == date(2026, 6, 15)
    assert status.next_signal_date == date(2026, 6, 30)
    assert status.sessions_until_next == 2
    assert status.missing_signal_session is False


def test_missing_observed_signal_session_is_reported_not_reanchored():
    config = get_strategy("btc_supertrend_satellite")
    observed = xshg_sessions(date(2026, 6, 1), date(2026, 6, 30))
    observed = observed[observed != pd.Timestamp("2026-06-30")]

    status = schedule_status(config, date(2026, 6, 30), observed)

    assert status.due is False
    assert status.last_signal_date == date(2026, 6, 15)
    assert status.next_signal_date == date(2026, 6, 30)
    assert status.missing_signal_session is True


def test_theme_schedule_is_due_on_shifted_signal_session():
    config = get_strategy("theme_alpha")
    observed = xshg_sessions(date(2026, 1, 1), date(2026, 1, 12))

    status = schedule_status(config, date(2026, 1, 12), observed)

    assert status.due is True
    assert status.last_signal_date == date(2026, 1, 12)
    assert status.next_signal_date == date(2026, 1, 26)

