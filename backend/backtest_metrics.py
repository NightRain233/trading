"""Pure backtest metrics shared by API and research callers."""

from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional

import pandas as pd

from portfolio_strategies.execution_rules import market_fill_price
from strategy_versions import DEFAULT_STRATEGY_VERSION_ID

def _price_with_bps(price: float, bps: float, direction: str) -> float:
    return market_fill_price(
        price, side="BUY" if direction == "buy" else "SELL", slippage_bps=bps,
    )

def summarize_trades(
    trades: List[Dict[str, object]],
    strategy_version: str = DEFAULT_STRATEGY_VERSION_ID,
) -> Dict[str, object]:
    trade_count = len(trades)
    if trade_count == 0:
        return {
            "strategyVersion": strategy_version,
            "tradeCount": 0,
            "winRate": 0.0,
            "averageReturnPct": 0.0,
            "maxDrawdownPct": 0.0,
            "averageHoldingDays": 0.0,
            "exitReasonCounts": {},
        }

    returns = [float(trade["returnPct"]) for trade in trades]
    wins = [ret for ret in returns if ret > 0]
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for ret in returns:
        equity *= 1 + ret / 100
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak * 100
        max_drawdown = max(max_drawdown, drawdown)

    holding_days = [int(trade["holdingDays"]) for trade in trades]
    exit_counts = Counter(str(trade["exitReason"]) for trade in trades)

    return {
        "strategyVersion": strategy_version,
        "tradeCount": trade_count,
        "winRate": len(wins) / trade_count,
        "averageReturnPct": sum(returns) / trade_count,
        "maxDrawdownPct": max_drawdown,
        "averageHoldingDays": sum(holding_days) / trade_count,
        "exitReasonCounts": dict(exit_counts),
    }

def _window_daily_frame(
    df_daily: pd.DataFrame,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> pd.DataFrame:
    if df_daily is None or df_daily.empty:
        return pd.DataFrame()
    window = df_daily.sort_index().copy()
    if start:
        window = window[window.index >= pd.Timestamp(start)]
    if end:
        window = window[window.index <= pd.Timestamp(end)]
    return window

def _buy_and_hold_return_pct(
    df_daily: pd.DataFrame,
    start: Optional[str] = None,
    end: Optional[str] = None,
    fee_bps: float = 5.0,
    slippage_bps: float = 5.0,
) -> Optional[float]:
    window = _window_daily_frame(df_daily, start=start, end=end)
    if window.empty or "Close" not in window.columns:
        return None
    window = window.dropna(subset=["Close"])
    if window.empty:
        return None

    entry_source = "Open" if "Open" in window.columns and pd.notna(window.iloc[0].get("Open")) else "Close"
    raw_entry = float(window.iloc[0][entry_source])
    raw_exit = float(window.iloc[-1]["Close"])
    if raw_entry <= 0:
        return None

    entry_price = _price_with_bps(raw_entry, slippage_bps, "buy")
    exit_price = _price_with_bps(raw_exit, slippage_bps, "sell")
    gross_return_pct = ((exit_price - entry_price) / entry_price) * 100
    return gross_return_pct - (fee_bps * 2 / 100)

def summarize_buy_and_hold_benchmark(
    daily_frames_by_symbol: Dict[str, pd.DataFrame],
    start: Optional[str] = None,
    end: Optional[str] = None,
    fee_bps: float = 5.0,
    slippage_bps: float = 5.0,
) -> Dict[str, object]:
    rows = []
    for symbol, df_daily in sorted(daily_frames_by_symbol.items()):
        return_pct = _buy_and_hold_return_pct(
            df_daily,
            start=start,
            end=end,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
        if return_pct is None:
            continue
        rows.append({"symbol": symbol.upper(), "returnPct": return_pct})

    if not rows:
        return {
            "symbolCount": 0,
            "equalWeightReturnPct": 0.0,
            "bestSymbol": None,
            "worstSymbol": None,
            "symbols": [],
        }

    sorted_rows = sorted(rows, key=lambda row: float(row["returnPct"]), reverse=True)
    return {
        "symbolCount": len(sorted_rows),
        "equalWeightReturnPct": sum(float(row["returnPct"]) for row in sorted_rows) / len(sorted_rows),
        "bestSymbol": sorted_rows[0],
        "worstSymbol": sorted_rows[-1],
        "symbols": sorted_rows,
    }
