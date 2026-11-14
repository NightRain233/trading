import numpy as np
import pandas as pd
import pytest
import json
from pathlib import Path

from supertrend_contract import CONTRACT_VERSION, calculate_supertrend


def _prices(values: list[float]) -> pd.DataFrame:
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values)))
    return pd.DataFrame(
        {
            "High": close + 1,
            "Low": close - 1,
            "Close": close,
        }
    )


def test_contract_uses_sma_atr_and_declares_version():
    frame = _prices([10, 11, 12, 11, 13])
    result = calculate_supertrend(
        frame["High"], frame["Low"], frame["Close"], length=3, multiplier=2
    )

    assert CONTRACT_VERSION == "sma-atr-v1"
    line = result["SUPERT_3_2"]
    # The first three true ranges are all 2, so the SMA ATR is 2.
    assert line.iloc[2] == pytest.approx(12 + 2 * 2)
    assert result["SUPERTd_3_2"].iloc[:2].isna().all()


def test_frozen_json_matches_runtime_contract():
    spec = json.loads(Path(__file__).parents[1].joinpath("supertrend_contract.json").read_text())
    assert spec["version"] == CONTRACT_VERSION
    assert spec["atrMode"] == "SMA"
    assert spec["primary"]["length"] == 10
    assert spec["primary"]["multiplier"] == 3.0


def test_contract_has_no_future_leak():
    base = _prices([10, 11, 12, 11, 13, 14])
    changed = base.copy()
    changed.loc[changed.index[-1], ["High", "Low", "Close"]] = [100, 1, 50]
    first = calculate_supertrend(base["High"], base["Low"], base["Close"], length=3)
    second = calculate_supertrend(
        changed["High"], changed["Low"], changed["Close"], length=3
    )
    np.testing.assert_allclose(first.iloc[:-1], second.iloc[:-1], equal_nan=True)


def test_contract_rejects_invalid_parameters():
    frame = _prices([10, 11, 12])
    with pytest.raises(ValueError):
        calculate_supertrend(frame.High, frame.Low, frame.Close, length=0)
    with pytest.raises(ValueError):
        calculate_supertrend(frame.High, frame.Low, frame.Close, multiplier=0)
