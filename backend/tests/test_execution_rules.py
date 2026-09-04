from __future__ import annotations

import pandas as pd

from portfolio_strategies.execution_rules import (
    market_fill_price,
    next_valid_open,
    preexisting_long_stop_fill,
)


def test_next_valid_open_skips_missing_and_nonpositive_values():
    frame = pd.DataFrame(
        {"Open": [None, 0.0, 103.0], "Close": [100.0, 101.0, 104.0]},
        index=pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]),
    )

    result = next_valid_open(frame, after="2025-01-01")

    assert result == (pd.Timestamp("2025-01-06"), 103.0)


def test_market_and_stop_fills_apply_one_shared_adverse_price_rule():
    assert market_fill_price(100.0, side="BUY", slippage_bps=10) == 100.1
    assert market_fill_price(100.0, side="SELL", slippage_bps=10) == 99.9
    assert preexisting_long_stop_fill(
        open_price=90.0, stop_price=95.0, slippage_bps=10,
    ) == 89.91
    assert preexisting_long_stop_fill(
        open_price=100.0, stop_price=95.0, slippage_bps=10,
    ) == 94.905
