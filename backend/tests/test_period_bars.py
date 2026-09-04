from __future__ import annotations

import pandas as pd

from portfolio_strategies.period_bars import completed_bars


def test_completed_monthly_bars_drop_partial_month_and_recompute_indicators():
    frame = pd.DataFrame(
        {
            "Open": [100.0, 101.0, 110.0, 120.0],
            "High": [102.0, 103.0, 112.0, 122.0],
            "Low": [99.0, 100.0, 109.0, 119.0],
            "Close": [101.0, 102.0, 111.0, 121.0],
            "Volume": [10.0, 20.0, 30.0, 40.0],
            "MACD_DIF": [999.0, 999.0, 999.0, 999.0],
            "MACD_DEA": [-999.0, -999.0, -999.0, -999.0],
        },
        index=pd.to_datetime([
            "2025-01-02", "2025-01-31", "2025-02-03", "2025-02-14",
        ]),
    )

    monthly = completed_bars(frame, timeframe="1M", known_at="2025-02-14")

    assert list(monthly.index) == [pd.Timestamp("2025-01-31")]
    assert monthly.iloc[0]["Open"] == 100.0
    assert monthly.iloc[0]["High"] == 103.0
    assert monthly.iloc[0]["Low"] == 99.0
    assert monthly.iloc[0]["Close"] == 102.0
    assert monthly.iloc[0]["Volume"] == 30.0
    assert monthly.iloc[0]["MACD_DIF"] == 0.0
    assert monthly.iloc[0]["MACD_DEA"] == 0.0
    assert monthly.iloc[0]["period_end"] == pd.Timestamp("2025-01-31")
    assert monthly.iloc[0]["available_at"] == pd.Timestamp("2025-01-31")
    assert monthly.iloc[0]["source_last_session"] == pd.Timestamp("2025-01-31")


def test_completed_monthly_bar_becomes_available_after_period_end():
    frame = pd.DataFrame(
        {"Close": [100.0, 200.0]},
        index=pd.to_datetime(["2025-01-31", "2025-02-28"]),
    )

    during_february = completed_bars(
        frame, timeframe="1M", known_at="2025-02-28",
    )
    after_february = completed_bars(
        frame, timeframe="1M", known_at="2025-03-01",
    )

    assert list(during_february.index) == [pd.Timestamp("2025-01-31")]
    assert list(after_february.index) == [
        pd.Timestamp("2025-01-31"), pd.Timestamp("2025-02-28"),
    ]
