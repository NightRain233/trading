from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from analysis_divergence import (
    build_macd_divergence_summary,
    filter_completed_weekly_bars,
)


def _daily_frame(kind: str = "bearish", periods: int = 19) -> pd.DataFrame:
    index = pd.bdate_range("2026-01-05", periods=periods)
    frame = pd.DataFrame(
        {
            "Open": 100.0,
            "High": 101.0,
            "Low": 99.0,
            "Close": 100.0,
            "Volume": 1000.0,
            "MACD_DIF": 0.0,
            "MACD_Hist": 0.0,
            "ATR": 1.0,
        },
        index=index,
    )
    if kind == "bearish":
        frame.iloc[5, frame.columns.get_loc("High")] = 110.0
        frame.iloc[15, frame.columns.get_loc("High")] = 112.0
        frame.iloc[5, frame.columns.get_loc("MACD_DIF")] = 2.0
        frame.iloc[15, frame.columns.get_loc("MACD_DIF")] = 1.0
        frame.iloc[5, frame.columns.get_loc("MACD_Hist")] = 1.2
        frame.iloc[15, frame.columns.get_loc("MACD_Hist")] = 0.4
    else:
        frame.iloc[5, frame.columns.get_loc("Low")] = 90.0
        frame.iloc[15, frame.columns.get_loc("Low")] = 88.0
        frame.iloc[5, frame.columns.get_loc("MACD_DIF")] = -2.0
        frame.iloc[15, frame.columns.get_loc("MACD_DIF")] = -1.0
        frame.iloc[5, frame.columns.get_loc("MACD_Hist")] = -1.2
        frame.iloc[15, frame.columns.get_loc("MACD_Hist")] = -0.4
    return frame


def test_daily_bearish_divergence_activates_only_on_right_confirmation_bar():
    frame = _daily_frame("bearish")

    before_confirmation = build_macd_divergence_summary(
        "TEST", frame.iloc[:-1], None
    )
    confirmed = build_macd_divergence_summary("TEST", frame, None)

    assert before_confirmation["daily"]["confirmed"] is None
    assert before_confirmation["daily"]["candidate"]["type"] == "bearish"
    signal = confirmed["daily"]["confirmed"]
    assert confirmed["daily"]["candidate"] is None
    assert signal["type"] == "bearish"
    assert signal["status"] == "confirmed"
    assert signal["firstPivotDate"] == frame.index[5].date().isoformat()
    assert signal["secondPivotDate"] == frame.index[15].date().isoformat()
    assert signal["confirmedAt"] == frame.index[18].date().isoformat()
    assert signal["priceChangePct"] > 0
    assert signal["difChangeNormalizedPct"] < 0
    assert signal["histogramConfirms"] is True
    assert signal["decisionRole"] == "risk_warning_only"


def test_daily_bullish_divergence_is_wait_for_confirmation_not_buy_permission():
    frame = _daily_frame("bullish")

    signal = build_macd_divergence_summary("TEST", frame, None)["daily"][
        "confirmed"
    ]

    assert signal["type"] == "bullish"
    assert signal["priceChangePct"] < 0
    assert signal["difChangeNormalizedPct"] > 0
    assert signal["decisionRole"] == "wait_for_trend_confirmation"


def test_incomplete_daily_session_cannot_confirm_divergence():
    frame = _daily_frame("bearish")
    frame.index = pd.bdate_range("2026-07-08", periods=len(frame))
    session_date = frame.index[-1].date().isoformat()

    before_close = build_macd_divergence_summary(
        "SPY",
        frame,
        None,
        now=datetime(2026, 8, 3, 15, 0, tzinfo=ZoneInfo("America/New_York")),
    )["daily"]
    after_close = build_macd_divergence_summary(
        "SPY",
        frame,
        None,
        now=datetime(2026, 8, 3, 16, 10, tzinfo=ZoneInfo("America/New_York")),
    )["daily"]

    assert session_date == "2026-08-03"
    assert before_close["asOf"] == "2026-07-31"
    assert before_close["confirmed"] is None
    assert before_close["candidate"]["type"] == "bearish"
    assert after_close["asOf"] == session_date
    assert after_close["confirmed"]["type"] == "bearish"


def test_confirmed_history_does_not_change_when_future_bars_are_appended():
    frame = _daily_frame("bearish")
    original = build_macd_divergence_summary("TEST", frame, None)["daily"][
        "confirmed"
    ]
    future_index = pd.bdate_range(frame.index[-1] + pd.Timedelta(days=1), periods=3)
    future = pd.DataFrame(
        {
            "Open": 100.0,
            "High": 101.0,
            "Low": 99.0,
            "Close": 100.0,
            "Volume": 1000.0,
            "MACD_DIF": 0.0,
            "MACD_Hist": 0.0,
            "ATR": 1.0,
        },
        index=future_index,
    )

    appended = build_macd_divergence_summary(
        "TEST", pd.concat([frame, future]), None
    )["daily"]["confirmed"]

    for key in (
        "type",
        "firstPivotDate",
        "secondPivotDate",
        "confirmedAt",
        "priceChangePct",
        "difChangeNormalizedPct",
    ):
        assert appended[key] == original[key]


def test_completed_week_filter_excludes_current_exchange_week_until_friday_close():
    weekly_index = pd.date_range("2026-01-04", periods=15, freq="W-SUN")
    weekly = pd.DataFrame({"Close": range(15)}, index=weekly_index)
    current_week_label = weekly_index[-1]

    thursday = current_week_label - pd.Timedelta(days=3)
    friday = current_week_label - pd.Timedelta(days=2)

    on_thursday = filter_completed_weekly_bars("510300.SS", weekly, thursday)
    on_friday = filter_completed_weekly_bars("510300.SS", weekly, friday)

    assert current_week_label not in on_thursday.index
    assert current_week_label in on_friday.index


def test_completed_week_filter_uses_sunday_close_for_crypto():
    weekly_index = pd.date_range("2026-01-04", periods=4, freq="W-SUN")
    weekly = pd.DataFrame({"Close": range(4)}, index=weekly_index)

    saturday = weekly_index[-1] - pd.Timedelta(days=1)
    sunday = weekly_index[-1]

    assert weekly_index[-1] not in filter_completed_weekly_bars(
        "BTC-USD", weekly, saturday
    ).index
    assert weekly_index[-1] in filter_completed_weekly_bars(
        "BTC-USD", weekly, sunday
    ).index


def test_weekly_divergence_cannot_confirm_from_a_provisional_exchange_week():
    weekly_index = pd.date_range("2026-01-04", periods=15, freq="W-SUN")
    weekly = pd.DataFrame(
        {
            "Open": 100.0,
            "High": 101.0,
            "Low": 99.0,
            "Close": 100.0,
            "Volume": 1000.0,
            "MACD_DIF": 0.0,
            "MACD_Hist": 0.0,
            "ATR": 2.0,
        },
        index=weekly_index,
    )
    weekly.iloc[5, weekly.columns.get_loc("High")] = 110.0
    weekly.iloc[12, weekly.columns.get_loc("High")] = 114.0
    weekly.iloc[5, weekly.columns.get_loc("MACD_DIF")] = 2.0
    weekly.iloc[12, weekly.columns.get_loc("MACD_DIF")] = 1.0
    weekly.iloc[5, weekly.columns.get_loc("MACD_Hist")] = 1.2
    weekly.iloc[12, weekly.columns.get_loc("MACD_Hist")] = 0.4

    thursday = weekly_index[-1] - pd.Timedelta(days=3)
    friday = weekly_index[-1] - pd.Timedelta(days=2)
    daily_thursday = _daily_frame().iloc[:1].copy()
    daily_thursday.index = pd.DatetimeIndex([thursday])
    daily_friday = daily_thursday.copy()
    daily_friday.index = pd.DatetimeIndex([friday])

    provisional = build_macd_divergence_summary(
        "510300.SS", daily_thursday, weekly
    )["weekly"]
    completed = build_macd_divergence_summary(
        "510300.SS", daily_friday, weekly
    )["weekly"]

    assert provisional["confirmed"] is None
    assert provisional["candidate"]["missingRightBars"] == 1
    assert completed["confirmed"]["type"] == "bearish"
    assert completed["confirmed"]["confirmedAt"] == weekly_index[-1].date().isoformat()
