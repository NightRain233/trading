import pandas as pd

from analysis_data import _calculate_weekly_indicators


def test_weekly_indicators_include_supertrend_fields():
    index = pd.date_range("2025-01-01", periods=280, freq="D")
    close = pd.Series(
        [100.0 + i * 0.15 + (i % 9) * 0.1 for i in range(len(index))],
        index=index,
    )
    daily = pd.DataFrame(
        {
            "Open": close - 0.2,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": 1000.0,
        },
        index=index,
    )

    weekly = _calculate_weekly_indicators(daily)

    assert "ST_Val" in weekly.columns
    assert "ST_Dir" in weekly.columns
    assert weekly["ST_Val"].notna().any()
    assert set(weekly["ST_Dir"].dropna().astype(int).unique()) <= {-1, 1}
