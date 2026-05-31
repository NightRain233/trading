import argparse
import json
import os
from collections import Counter
from typing import Dict, List, Optional

import pandas_ta as ta

import pandas as pd

from analysis import DATA_DIR
from analysis import _evaluate_resonance_exit_no_position
from analysis import _evaluate_resonance_strategy_v2
from strategy_versions import DEFAULT_STRATEGY_VERSION_ID
from strategy_versions import get_strategy_version


SUPER_TREND_ENTRY_SIGNAL_MODES = {
    "daily_bull_flip",
    "support_test",
    "high_priority_alerts",
    "weekly_bull_daily_bull_flip",
    "weekly_bull_support_test",
}
SUPER_TREND_BASELINE_ENTRY_SIGNAL_MODE = "weekly_bull_daily_bull_flip"
SUPER_TREND_SUPPORT_TEST_MAX_DISTANCE_PCT = 1.5
SUPER_TREND_SUPPORT_TEST_MAX_DISTANCE_ATR = 0.5


def evaluate_weekly_bb_breakout(df_weekly: pd.DataFrame, lookback: int = 8) -> Dict[str, object]:
    """
    周线BB(20,2)突破策略信号。
    入场：收盘突破上轨 + 近lookback周有过挤压（带宽收窄）+ 收盘在MA30之上。
    离场信号：收盘回到上轨内且上轨走平，或跌破MA30。
    """
    required = {"Close", "BOLL_Upper", "BOLL_Lower", "BOLL_Mid", "MA30"}
    if df_weekly is None or df_weekly.empty or not required.issubset(df_weekly.columns):
        return {"buySignal": False}
    w = df_weekly.dropna(subset=list(required))
    if len(w) < max(20, lookback + 1):
        return {"buySignal": False}

    last = w.iloc[-1]
    close = float(last["Close"])
    upper = float(last["BOLL_Upper"])
    lower = float(last["BOLL_Lower"])
    ma30 = float(last["MA30"])

    # 趋势过滤：收盘在MA30之上
    if close <= ma30:
        return {"buySignal": False}

    # 突破上轨
    if close <= upper:
        return {"buySignal": False}

    # 近lookback周内有挤压（带宽低于近期均值的80%）
    recent = w.iloc[-(lookback + 1):-1]
    bw = (recent["BOLL_Upper"] - recent["BOLL_Lower"]) / recent["BOLL_Mid"].replace(0, float("nan"))
    bw_mean = bw.mean()
    current_bw = (upper - lower) / float(last["BOLL_Mid"]) if float(last["BOLL_Mid"]) != 0 else 0
    had_squeeze = bw.min() < bw_mean * 0.8 if not bw.empty else False

    if not had_squeeze:
        return {"buySignal": False}

    return {
        "buySignal": True,
        "stopPrice": float(ma30),
        "targetPrice": None,
        "strategyVersion": "weekly_bb_breakout_ma30",
        "poolType": "weeklyBBBreakout",
    }


def evaluate_weekly_bb_pullback(
    df_weekly: pd.DataFrame,
    df_daily: Optional[pd.DataFrame] = None,
    breakout_lookback: int = 8,
    pullback_tolerance_pct: float = 3.0,
    daily_pullback_lookback: int = 10,
    daily_pullback_tolerance_pct: float = 1.0,
) -> Dict[str, object]:
    """
    周线BB突破后的回踩确认入场。
    资格：最近breakout_lookback周出现过上轨突破，当前仍在MA30上方。
    触发：周线回踩周BB中轨/MA20附近后收回，或日线回踩EMA20后收回。
    """
    required_weekly = {"Close", "Low", "BOLL_Upper", "BOLL_Lower", "BOLL_Mid", "MA30"}
    if df_weekly is None or df_weekly.empty or not required_weekly.issubset(df_weekly.columns):
        return {"buySignal": False}
    w = df_weekly.dropna(subset=list(required_weekly))
    if len(w) < breakout_lookback + 1:
        return {"buySignal": False}

    last = w.iloc[-1]
    close = float(last["Close"])
    low = float(last["Low"])
    mid = float(last["BOLL_Mid"])
    ma30 = float(last["MA30"])
    if mid <= 0 or close <= ma30:
        return {"buySignal": False}

    recent = w.iloc[-(breakout_lookback + 1):-1]
    had_prior_breakout = bool(
        ((recent["Close"] > recent["BOLL_Upper"]) & (recent["Close"] > recent["MA30"])).any()
    )
    if not had_prior_breakout:
        return {"buySignal": False}

    pullback_limit = mid * (1 + pullback_tolerance_pct / 100)
    touched_mid_zone = low <= pullback_limit
    reclaimed_mid = close >= mid
    weekly_pullback_confirmed = touched_mid_zone and reclaimed_mid
    daily_pullback_confirmed = False

    if df_daily is not None:
        required_daily = {"Close", "EMA20", "MA30"}
        if df_daily.empty or not required_daily.issubset(df_daily.columns):
            return {"buySignal": False}
        d = df_daily.dropna(subset=list(required_daily))
        if d.empty:
            return {"buySignal": False}
        latest_daily = d.iloc[-1]
        daily_close = float(latest_daily["Close"])
        if daily_close <= float(latest_daily["EMA20"]) or daily_close <= float(latest_daily["MA30"]):
            return {"buySignal": False}
        recent_daily = d.tail(daily_pullback_lookback)
        daily_pullback_limit = recent_daily["EMA20"] * (1 + daily_pullback_tolerance_pct / 100)
        daily_pullback_confirmed = bool((recent_daily["Low"] <= daily_pullback_limit).any())
    elif not weekly_pullback_confirmed:
        return {"buySignal": False}

    if not (weekly_pullback_confirmed or daily_pullback_confirmed):
        return {"buySignal": False}

    return {
        "buySignal": True,
        "stopPrice": float(ma30),
        "targetPrice": None,
        "strategyVersion": "weekly_bb_breakout_ma30",
        "poolType": "weeklyBBPullback",
        "entryType": "weeklyPullback" if weekly_pullback_confirmed else "dailyPullback",
    }


def evaluate_weekly_bb_pullback_atr_stop(
    df_weekly: pd.DataFrame,
    df_daily: Optional[pd.DataFrame] = None,
    atr_stop_multiplier: float = 1.5,
    breakout_lookback: int = 8,
    pullback_tolerance_pct: float = 3.0,
    daily_pullback_lookback: int = 10,
    daily_pullback_tolerance_pct: float = 1.0,
) -> Dict[str, object]:
    """Pullback-only variant: same as evaluate_weekly_bb_pullback but stop = entry - atr_stop_multiplier * ATR."""
    sig = evaluate_weekly_bb_pullback(
        df_weekly, df_daily,
        breakout_lookback=breakout_lookback,
        pullback_tolerance_pct=pullback_tolerance_pct,
        daily_pullback_lookback=daily_pullback_lookback,
        daily_pullback_tolerance_pct=daily_pullback_tolerance_pct,
    )
    if not sig.get("buySignal"):
        return sig
    # ATR stop: use daily ATR if available, else fall back to MA30
    atr_stop = None
    if df_daily is not None and not df_daily.empty and "ATR" in df_daily.columns and "Close" in df_daily.columns:
        d = df_daily.dropna(subset=["ATR", "Close"])
        if not d.empty:
            close = float(d.iloc[-1]["Close"])
            atr = float(d.iloc[-1]["ATR"])
            if atr > 0:
                atr_stop = close - atr_stop_multiplier * atr
    return {
        **sig,
        "stopPrice": atr_stop if atr_stop is not None else sig.get("stopPrice"),
        "strategyVersion": "weekly_bb_pullback_atr_stop",
        "poolType": "weeklyBBPullback",
    }


def evaluate_weekly_bb_exit(df_weekly: pd.DataFrame) -> Dict[str, object]:
    """离场：收盘回到上轨内且上轨走平（斜率<=0），或跌破MA30。"""
    required = {"Close", "BOLL_Upper", "MA30"}
    if df_weekly is None or df_weekly.empty or not required.issubset(df_weekly.columns):
        return {"exitSignal": False}
    w = df_weekly.dropna(subset=list(required))
    if len(w) < 2:
        return {"exitSignal": False}
    last = w.iloc[-1]
    prev = w.iloc[-2]
    close = float(last["Close"])
    upper = float(last["BOLL_Upper"])
    ma30 = float(last["MA30"])

    if close < ma30:
        return {"exitSignal": True, "exitReason": "below_ma30"}
    upper_slope = float(last["BOLL_Upper"]) - float(prev["BOLL_Upper"])
    if close < upper and upper_slope <= 0:
        return {"exitSignal": True, "exitReason": "bb_upper_flat_reentry"}
    return {"exitSignal": False}


def replay_weekly_bb_markers(df_weekly: pd.DataFrame) -> List[Dict[str, object]]:
    markers = []
    in_position = False
    for i in range(1, len(df_weekly)):
        prefix = df_weekly.iloc[: i + 1]
        ts = pd.Timestamp(df_weekly.index[i]).date().isoformat()
        last = prefix.iloc[-1]
        close = float(last["Close"]) if pd.notna(last.get("Close")) else None
        if close is None:
            continue
        if not in_position:
            sig = evaluate_weekly_bb_breakout(prefix)
            if sig.get("buySignal"):
                markers.append({"time": ts, "type": "buy_breakout", "price": close})
                in_position = True
                continue
            sig = evaluate_weekly_bb_pullback(prefix)
            if sig.get("buySignal"):
                markers.append({"time": ts, "type": "buy_pullback", "price": close})
                in_position = True
        else:
            exit_sig = evaluate_weekly_bb_exit(prefix)
            if exit_sig.get("exitSignal"):
                reason = exit_sig.get("exitReason", "")
                markers.append({"time": ts, "type": "sell_ma30" if reason == "below_ma30" else "sell_bb_flat", "price": close})
                in_position = False
    return markers


def run_supertrend_backtest(
    symbol: str,
    df_daily: pd.DataFrame,
    length: int = 7,
    multiplier: float = 3.0,
    fee_bps: float = 5.0,
    slippage_bps: float = 5.0,
    start: Optional[str] = None,
    end: Optional[str] = None,
    filter_weekly_df: Optional[pd.DataFrame] = None,
    min_adx_for_entry: Optional[float] = None,
    entry_signal_mode: str = SUPER_TREND_BASELINE_ENTRY_SIGNAL_MODE,
) -> List[Dict[str, object]]:
    if entry_signal_mode not in SUPER_TREND_ENTRY_SIGNAL_MODES:
        raise ValueError(f"Unsupported SuperTrend entry signal mode: {entry_signal_mode}")
    if df_daily is None or df_daily.empty:
        return []
    daily = df_daily.sort_index().copy()
    st = ta.supertrend(daily["High"], daily["Low"], daily["Close"], length=length, multiplier=multiplier)
    if st is None or st.empty:
        return []
    dir_col = [c for c in st.columns if c.startswith("SUPERTd_")]
    val_col = [c for c in st.columns if c.startswith("SUPERT_") and not c.startswith("SUPERTd_") and not c.startswith("SUPERTs_") and not c.startswith("SUPERTl_") and not c.startswith("SUPERTu_")]
    if not dir_col or not val_col:
        return []
    daily["_st_dir"] = st[dir_col[0]]
    daily["_st_val"] = st[val_col[0]]

    # 周线 SuperTrend 方向（用于共振过滤）
    weekly_dir: Optional[pd.Series] = None
    if filter_weekly_df is not None and not filter_weekly_df.empty:
        wst = ta.supertrend(filter_weekly_df["High"], filter_weekly_df["Low"], filter_weekly_df["Close"], length=length, multiplier=multiplier)
        if wst is not None and not wst.empty:
            wdir_col = [c for c in wst.columns if c.startswith("SUPERTd_")]
            if wdir_col:
                weekly_dir = wst[wdir_col[0]].sort_index()

    def _weekly_bullish(date) -> bool:
        if weekly_dir is None:
            return True
        w = weekly_dir[weekly_dir.index <= date]
        return not w.empty and float(w.iloc[-1]) == 1

    def _daily_bull_flip(prev, row) -> bool:
        return float(prev["_st_dir"]) == -1 and float(row["_st_dir"]) == 1

    def _daily_support_test(row) -> bool:
        if float(row["_st_dir"]) != 1:
            return False
        if pd.isna(row.get("_st_val")) or pd.isna(row.get("Close")):
            return False
        close = float(row["Close"])
        st_val = float(row["_st_val"])
        if close <= 0 or close < st_val:
            return False
        distance_pct = abs(close - st_val) / close * 100
        if distance_pct <= SUPER_TREND_SUPPORT_TEST_MAX_DISTANCE_PCT:
            return True
        atr = row.get("ATR")
        if atr is None or pd.isna(atr) or float(atr) <= 0:
            return False
        return abs(close - st_val) / float(atr) <= SUPER_TREND_SUPPORT_TEST_MAX_DISTANCE_ATR

    def _entry_mode_allows(prev, row, date) -> bool:
        daily_flip = _daily_bull_flip(prev, row)
        support_test = _daily_support_test(row)
        weekly_bull = _weekly_bullish(date)
        if entry_signal_mode == "daily_bull_flip":
            return daily_flip
        if entry_signal_mode == "support_test":
            return support_test
        if entry_signal_mode == "high_priority_alerts":
            return weekly_bull and (daily_flip or support_test)
        if entry_signal_mode == "weekly_bull_daily_bull_flip":
            return weekly_bull and daily_flip
        if entry_signal_mode == "weekly_bull_support_test":
            return weekly_bull and support_test
        return False

    def _adx_allows_entry(row) -> bool:
        if min_adx_for_entry is None:
            return True
        if "ADX" not in row or pd.isna(row.get("ADX")):
            return False
        return float(row["ADX"]) >= float(min_adx_for_entry)

    start_ts = pd.Timestamp(start) if start else None
    end_ts = pd.Timestamp(end) if end else None
    trades: List[Dict[str, object]] = []
    in_position = False
    entry_idx = None
    entry_price = None
    stop_price = None
    entry_adx = None
    strategy_version = f"supertrend_adx_{min_adx_for_entry:g}" if min_adx_for_entry is not None else "supertrend"
    if entry_signal_mode != SUPER_TREND_BASELINE_ENTRY_SIGNAL_MODE:
        strategy_version = f"{strategy_version}_{entry_signal_mode}"

    for idx in range(1, len(daily)):
        row = daily.iloc[idx]
        prev = daily.iloc[idx - 1]
        date = daily.index[idx]

        if in_position:
            # 止损：当日 low 触及 supertrend 线
            cur_stop = float(row["_st_val"]) if pd.notna(row["_st_val"]) else stop_price
            if float(row["Low"]) <= cur_stop or float(row["_st_dir"]) == -1:
                exit_price = _price_with_bps(min(float(row["Open"]), cur_stop), slippage_bps, "sell")
                gross = (exit_price - entry_price) / entry_price * 100
                trades.append({
                    "symbol": symbol.upper(),
                    "assetClass": classify_asset(symbol),
                    "entryDate": _date_str(daily.index[entry_idx]),
                    "exitDate": _date_str(date),
                    "entryPrice": entry_price,
                    "exitPrice": exit_price,
                    "stopPrice": cur_stop,
                    "returnPct": gross - fee_bps * 2 / 100,
                    "holdingDays": idx - entry_idx + 1,
                    "exitReason": "st_flip" if float(row["_st_dir"]) == -1 else "stop",
                    "strategyVersion": strategy_version,
                    "poolType": "supertrend",
                    "entryAdx": entry_adx,
                    "entrySignalMode": entry_signal_mode,
                })
                in_position = False
        else:
            # 买入模式只筛选入场触发；出场逻辑在所有精简层中保持一致。
            if _entry_mode_allows(prev, row, date) and _adx_allows_entry(row):
                entry_date = date
                if start_ts and entry_date < start_ts:
                    continue
                if end_ts and entry_date > end_ts:
                    break
                raw_entry = float(row["Open"]) if pd.notna(row.get("Open")) else float(row["Close"])
                entry_price = _price_with_bps(raw_entry, slippage_bps, "buy")
                stop_price = float(row["_st_val"]) if pd.notna(row["_st_val"]) else raw_entry * 0.95
                entry_adx = float(row["ADX"]) if "ADX" in row and pd.notna(row.get("ADX")) else None
                entry_idx = idx
                in_position = True

    return trades


def build_supertrend_history_review(
    symbol: str,
    df_daily: pd.DataFrame,
    length: int = 7,
    multiplier: float = 3.0,
    fee_bps: float = 5.0,
    slippage_bps: float = 5.0,
    start: Optional[str] = None,
    end: Optional[str] = None,
    filter_weekly_df: Optional[pd.DataFrame] = None,
    min_adx_for_entry: Optional[float] = None,
) -> Dict[str, object]:
    if df_daily is None or df_daily.empty:
        return {
            "symbol": symbol.upper(),
            "strategy": "supertrend",
            "start": start,
            "end": end,
            "candles": [],
            "supertrend": [],
            "markers": [],
            "trades": [],
            "summary": {
                "tradeCount": 0,
                "winRate": 0.0,
                "averageReturnPct": 0.0,
                "totalReturnPct": 0.0,
                "averageHoldingDays": 0.0,
                "exitReasonCounts": {},
            },
        }

    daily = df_daily.sort_index().copy()
    st = ta.supertrend(daily["High"], daily["Low"], daily["Close"], length=length, multiplier=multiplier)
    if st is None or st.empty:
        return build_supertrend_history_review(
            symbol,
            pd.DataFrame(),
            length=length,
            multiplier=multiplier,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            start=start,
            end=end,
        )
    dir_col = [c for c in st.columns if c.startswith("SUPERTd_")]
    val_col = [
        c for c in st.columns
        if c.startswith("SUPERT_")
        and not c.startswith("SUPERTd_")
        and not c.startswith("SUPERTs_")
        and not c.startswith("SUPERTl_")
        and not c.startswith("SUPERTu_")
    ]
    if not dir_col or not val_col:
        return build_supertrend_history_review(
            symbol,
            pd.DataFrame(),
            length=length,
            multiplier=multiplier,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            start=start,
            end=end,
        )

    daily["_st_dir"] = st[dir_col[0]]
    daily["_st_val"] = st[val_col[0]]

    weekly_dir: Optional[pd.Series] = None
    if filter_weekly_df is not None and not filter_weekly_df.empty:
        weekly = filter_weekly_df.sort_index()
        wst = ta.supertrend(weekly["High"], weekly["Low"], weekly["Close"], length=length, multiplier=multiplier)
        if wst is not None and not wst.empty:
            wdir_col = [c for c in wst.columns if c.startswith("SUPERTd_")]
            if wdir_col:
                weekly_dir = wst[wdir_col[0]].sort_index()

    def _weekly_bullish(date) -> bool:
        if weekly_dir is None:
            return True
        w = weekly_dir[weekly_dir.index <= date]
        return not w.empty and float(w.iloc[-1]) == 1

    def _adx_allows_entry(row) -> bool:
        if min_adx_for_entry is None:
            return True
        if "ADX" not in row or pd.isna(row.get("ADX")):
            return False
        return float(row["ADX"]) >= float(min_adx_for_entry)

    def _row_price(row, col: str, fallback_col: str = "Close") -> float:
        if col in row and pd.notna(row.get(col)):
            return float(row[col])
        return float(row[fallback_col])

    start_ts = pd.Timestamp(start) if start else None
    end_ts = pd.Timestamp(end) if end else None
    trades: List[Dict[str, object]] = []
    markers: List[Dict[str, object]] = []
    in_position = False
    entry_idx: Optional[int] = None
    entry_price: Optional[float] = None
    stop_price: Optional[float] = None
    entry_adx: Optional[float] = None

    for idx in range(1, len(daily)):
        row = daily.iloc[idx]
        prev = daily.iloc[idx - 1]
        date = daily.index[idx]

        if in_position and entry_idx is not None and entry_price is not None:
            cur_stop = float(row["_st_val"]) if pd.notna(row.get("_st_val")) else stop_price
            if cur_stop is not None and (float(row["Low"]) <= cur_stop or float(row["_st_dir"]) == -1):
                raw_exit = min(_row_price(row, "Open"), float(cur_stop))
                exit_price = _price_with_bps(raw_exit, slippage_bps, "sell")
                gross = (exit_price - entry_price) / entry_price * 100
                trade_index = len(trades) + 1
                reason = "st_flip" if float(row["_st_dir"]) == -1 else "stop"
                trades.append({
                    "tradeIndex": trade_index,
                    "symbol": symbol.upper(),
                    "strategy": "supertrend",
                    "entryDate": _date_str(daily.index[entry_idx]),
                    "exitDate": _date_str(date),
                    "entryPrice": entry_price,
                    "exitPrice": exit_price,
                    "stopPrice": cur_stop,
                    "returnPct": gross - fee_bps * 2 / 100,
                    "holdingDays": idx - entry_idx + 1,
                    "exitReason": reason,
                    "entryAdx": entry_adx,
                })
                markers.append({
                    "time": _date_str(date),
                    "type": "sell",
                    "position": "aboveBar",
                    "color": "#ef4444",
                    "shape": "arrowDown",
                    "text": f"卖出 {exit_price:.2f}",
                    "tradeIndex": trade_index,
                    "price": exit_price,
                    "exitReason": reason,
                })
                in_position = False
                entry_idx = None
                entry_price = None
                stop_price = None
                entry_adx = None
        else:
            if (
                float(prev["_st_dir"]) == -1
                and float(row["_st_dir"]) == 1
                and _weekly_bullish(date)
                and _adx_allows_entry(row)
            ):
                if start_ts is not None and date < start_ts:
                    continue
                if end_ts is not None and date > end_ts:
                    break
                raw_entry = _row_price(row, "Open")
                entry_price = _price_with_bps(raw_entry, slippage_bps, "buy")
                stop_price = float(row["_st_val"]) if pd.notna(row.get("_st_val")) else raw_entry * 0.95
                entry_adx = float(row["ADX"]) if "ADX" in row and pd.notna(row.get("ADX")) else None
                entry_idx = idx
                in_position = True
                markers.append({
                    "time": _date_str(date),
                    "type": "buy",
                    "position": "belowBar",
                    "color": "#10b981",
                    "shape": "arrowUp",
                    "text": f"买入 {entry_price:.2f}",
                    "tradeIndex": len(trades) + 1,
                    "price": entry_price,
                })

    chart_window = daily
    if start_ts is not None:
        chart_window = chart_window[chart_window.index >= start_ts]
    if end_ts is not None:
        chart_window = chart_window[chart_window.index <= end_ts]

    candles = []
    supertrend_points = []
    for ts, row in chart_window.iterrows():
        if pd.isna(row.get("Close")):
            continue
        close = float(row["Close"])
        candles.append({
            "time": _date_str(ts),
            "open": _row_price(row, "Open"),
            "high": _row_price(row, "High"),
            "low": _row_price(row, "Low"),
            "close": close,
            "volume": float(row["Volume"]) if "Volume" in row and pd.notna(row.get("Volume")) else 0.0,
        })
        if pd.notna(row.get("_st_val")) and pd.notna(row.get("_st_dir")):
            supertrend_points.append({
                "time": _date_str(ts),
                "value": float(row["_st_val"]),
                "direction": int(row["_st_dir"]),
            })

    returns = [float(trade["returnPct"]) for trade in trades]
    holding_days = [int(trade["holdingDays"]) for trade in trades]
    total_equity = 1.0
    for ret in returns:
        total_equity *= 1 + ret / 100
    summary = {
        "tradeCount": len(trades),
        "winRate": (sum(1 for ret in returns if ret > 0) / len(returns)) if returns else 0.0,
        "averageReturnPct": (sum(returns) / len(returns)) if returns else 0.0,
        "totalReturnPct": (total_equity - 1) * 100 if returns else 0.0,
        "averageHoldingDays": (sum(holding_days) / len(holding_days)) if holding_days else 0.0,
        "exitReasonCounts": dict(Counter(str(trade["exitReason"]) for trade in trades)),
    }

    return {
        "symbol": symbol.upper(),
        "strategy": "supertrend",
        "start": start,
        "end": end,
        "candles": candles,
        "supertrend": supertrend_points,
        "markers": markers,
        "trades": trades,
        "summary": summary,
    }


def _date_str(value) -> str:
    return pd.Timestamp(value).date().isoformat()


def _normalize_symbol_list(raw_symbols) -> List[str]:
    symbols = []
    for item in raw_symbols or []:
        symbol = item.get("symbol") if isinstance(item, dict) else item
        if not isinstance(symbol, str):
            continue
        normalized = symbol.strip().upper()
        if normalized and normalized not in symbols:
            symbols.append(normalized)
    return symbols


def load_universe_symbols(path: str) -> List[str]:
    with open(path, "r") as f:
        payload = json.load(f)
    if isinstance(payload, list):
        return _normalize_symbol_list(payload)
    if isinstance(payload, dict):
        return _normalize_symbol_list(payload.get("symbols", []))
    raise ValueError("Universe file must contain a JSON list or an object with a symbols list")


def _weekly_until(df_weekly: pd.DataFrame, as_of) -> pd.DataFrame:
    if df_weekly is None or df_weekly.empty:
        return df_weekly
    return df_weekly[df_weekly.index <= as_of]


def _price_with_bps(price: float, bps: float, direction: str) -> float:
    multiplier = 1 + (bps / 10_000) if direction == "buy" else 1 - (bps / 10_000)
    return float(price) * multiplier


def classify_asset(symbol: str) -> str:
    normalized = symbol.upper()
    if normalized.endswith("-USD"):
        return "crypto"
    if normalized in {"GC=F", "CL=F", "SI=F"} or normalized.endswith("=F"):
        return "commodity"
    if normalized in {"SPY", "QQQ", "DIA", "IWM"}:
        return "etf"
    if normalized.endswith(".SS") or normalized.endswith(".SZ"):
        numeric = normalized.split(".", 1)[0]
        if numeric.startswith(("15", "51", "56", "58")):
            return "etf"
        if numeric.startswith(("000", "399")):
            return "index"
        return "stock"
    return "stock"


def _market_regime_allows_entry(
    market_regime_daily: Optional[pd.DataFrame],
    signal_date,
    market_filter: str,
) -> bool:
    if market_filter == "none":
        return True
    if market_regime_daily is None or market_regime_daily.empty:
        return True

    market_window = market_regime_daily.sort_index()
    market_window = market_window[market_window.index <= signal_date]
    if market_window.empty:
        return True

    if market_filter == "monthly_macd":
        monthly = market_window.resample("ME").last()
        if monthly.empty or "MACD_DIF" not in monthly.columns or "MACD_DEA" not in monthly.columns:
            return True
        return float(monthly.iloc[-1]["MACD_DIF"]) > float(monthly.iloc[-1]["MACD_DEA"])

    if market_filter != "bullish_ema":
        raise ValueError(f"Unknown market filter: {market_filter}")

    required_cols = {"Close", "EMA20", "EMA50"}
    if not required_cols.issubset(market_regime_daily.columns):
        return True

    row = market_window.iloc[-1]
    return float(row["Close"]) > float(row["EMA20"]) and float(row["EMA20"]) > float(row["EMA50"])


def _market_regime_snapshot(
    market_regime_daily: Optional[pd.DataFrame],
    as_of,
) -> Dict[str, object]:
    if market_regime_daily is None or market_regime_daily.empty:
        return {"marketRegime": "unknown"}

    required_cols = {"Close", "EMA20", "EMA50"}
    if not required_cols.issubset(market_regime_daily.columns):
        return {"marketRegime": "unknown"}

    market_window = market_regime_daily.sort_index()
    market_window = market_window[market_window.index <= as_of]
    if market_window.empty:
        return {"marketRegime": "unknown"}

    row = market_window.iloc[-1]
    close = float(row["Close"])
    ema20 = float(row["EMA20"])
    ema50 = float(row["EMA50"])

    if close > ema20 > ema50:
        regime = "bullish_ema"
    elif ema20 > ema50 and close <= ema20:
        regime = "bullish_trend_pullback"
    elif close > ema20 and ema20 <= ema50:
        regime = "rebound_below_trend"
    else:
        regime = "bearish_ema"

    return {
        "marketRegime": regime,
        "marketCloseVsEma20Pct": ((close - ema20) / ema20) * 100 if ema20 else 0.0,
        "marketEma20VsEma50Pct": ((ema20 - ema50) / ema50) * 100 if ema50 else 0.0,
    }


def resolve_market_settings(
    cli_market_filter: str,
    cli_market_symbol: Optional[str],
    version,
) -> tuple[str, str]:
    market_filter = cli_market_filter if cli_market_filter != "none" else version.market_filter
    market_symbol = cli_market_symbol or version.market_symbol or "SPY"
    return market_filter, market_symbol


def _pick_exit(
    df_daily: pd.DataFrame,
    df_weekly: pd.DataFrame,
    entry_idx: int,
    stop_price: Optional[float],
    target_price: Optional[float],
    max_hold_days: int,
    slippage_bps: float,
    exit_mode: str = "fixed_target",
    is_weekly_bb: bool = False,
) -> Dict[str, object]:
    last_allowed_idx = min(len(df_daily) - 1, entry_idx + max_hold_days - 1)

    for idx in range(entry_idx, last_allowed_idx + 1):
        row = df_daily.iloc[idx]
        low = float(row["Low"])
        high = float(row["High"])

        if stop_price is not None and low <= float(stop_price):
            return {
                "exitIdx": idx,
                "exitPrice": _price_with_bps(float(stop_price), slippage_bps, "sell"),
                "exitReason": "stop",
            }

        if exit_mode == "fixed_target" and target_price is not None and high >= float(target_price):
            return {
                "exitIdx": idx,
                "exitPrice": _price_with_bps(float(target_price), slippage_bps, "sell"),
                "exitReason": "target",
            }

        weekly_window = _weekly_until(df_weekly, df_daily.index[idx])
        if is_weekly_bb:
            bb_exit = evaluate_weekly_bb_exit(weekly_window)
            if bb_exit.get("exitSignal"):
                return {
                    "exitIdx": idx,
                    "exitPrice": _price_with_bps(float(row["Close"]), slippage_bps, "sell"),
                    "exitReason": bb_exit.get("exitReason", "bb_exit"),
                }
        else:
            exit_signal = _evaluate_resonance_exit_no_position(df_daily.iloc[: idx + 1], weekly_window)
            if exit_signal.get("exitLevel") == "hard":
                return {
                    "exitIdx": idx,
                    "exitPrice": _price_with_bps(float(row["Close"]), slippage_bps, "sell"),
                    "exitReason": "hard_exit",
                }
            if exit_mode == "warn_exit" and exit_signal.get("exitLevel") == "warn":
                return {
                    "exitIdx": idx,
                    "exitPrice": _price_with_bps(float(row["Close"]), slippage_bps, "sell"),
                    "exitReason": "warn_exit",
                }

    final_row = df_daily.iloc[last_allowed_idx]
    reason = "max_hold" if last_allowed_idx < len(df_daily) - 1 else "end_of_data"
    return {
        "exitIdx": last_allowed_idx,
        "exitPrice": _price_with_bps(float(final_row["Close"]), slippage_bps, "sell"),
        "exitReason": reason,
    }


def run_backtest_for_symbol(
    symbol: str,
    df_daily: pd.DataFrame,
    df_weekly: pd.DataFrame,
    strategy_version: str = DEFAULT_STRATEGY_VERSION_ID,
    max_hold_days: int = 30,
    cooldown_bars: int = 3,
    fee_bps: float = 5.0,
    slippage_bps: float = 5.0,
    market_regime_daily: Optional[pd.DataFrame] = None,
    market_filter: str = "none",
    entry_market_filter: str = "none",
    entry_market_min_close_vs_ema20_pct: float = 0.0,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> List[Dict[str, object]]:
    """
    Run a long-only resonance backtest for one symbol.

    Assumptions:
    - Signal is evaluated after the signal bar closes.
    - Entry occurs at the next bar open.
    - Only one position per symbol at a time.
    - Stop checks before target when both are touched in the same bar.
    """
    if df_daily is None or df_daily.empty or df_weekly is None or df_weekly.empty:
        return []

    version = get_strategy_version(strategy_version)
    daily = df_daily.sort_index().copy()
    weekly = df_weekly.sort_index().copy()
    trades: List[Dict[str, object]] = []
    signal_idx = 20
    start_ts = pd.Timestamp(start) if start else None
    end_ts = pd.Timestamp(end) if end else None

    is_weekly_bb = getattr(version, "signal_type", "resonance") == "weekly_bb_breakout"
    is_weekly_bb_pullback_atr = getattr(version, "signal_type", "resonance") == "weekly_bb_pullback_atr"

    while signal_idx < len(daily) - 1:
        signal_date = daily.index[signal_idx]
        weekly_window = _weekly_until(weekly, signal_date)
        daily_window = daily.iloc[: signal_idx + 1]
        if is_weekly_bb_pullback_atr:
            signal = evaluate_weekly_bb_pullback_atr_stop(weekly_window, daily_window, atr_stop_multiplier=version.atr_stop_multiplier)
        elif is_weekly_bb:
            signal = evaluate_weekly_bb_breakout(weekly_window)
            if not signal.get("buySignal"):
                signal = evaluate_weekly_bb_pullback(weekly_window, daily_window)
        else:
            signal = _evaluate_resonance_strategy_v2(
                daily_window,
                weekly_window,
                strategy_version=strategy_version,
            )

        if not signal.get("buySignal"):
            signal_idx += 1
            continue
        if not _market_regime_allows_entry(market_regime_daily, signal_date, market_filter):
            signal_idx += 1
            continue

        entry_idx = signal_idx + 1
        entry_date = daily.index[entry_idx]
        if start_ts is not None and entry_date < start_ts:
            signal_idx += 1
            continue
        if end_ts is not None and entry_date > end_ts:
            break
        if not _market_regime_allows_entry(market_regime_daily, entry_date, entry_market_filter):
            signal_idx += 1
            continue
        market_entry_snapshot = _market_regime_snapshot(market_regime_daily, entry_date)
        entry_close_vs_ema20 = market_entry_snapshot.get("marketCloseVsEma20Pct")
        if (
            entry_market_min_close_vs_ema20_pct > 0
            and (
                entry_close_vs_ema20 is None
                or float(entry_close_vs_ema20) < entry_market_min_close_vs_ema20_pct
            )
        ):
            signal_idx += 1
            continue

        entry_row = daily.iloc[entry_idx]
        raw_entry_price = float(entry_row["Open"]) if "Open" in daily.columns else float(entry_row["Close"])
        entry_price = _price_with_bps(raw_entry_price, slippage_bps, "buy")
        exit_info = _pick_exit(
            daily,
            weekly,
            entry_idx=entry_idx,
            stop_price=signal.get("stopPrice"),
            target_price=signal.get("targetPrice"),
            max_hold_days=max_hold_days,
            slippage_bps=slippage_bps,
            exit_mode=version.exit_mode,
            is_weekly_bb=is_weekly_bb or is_weekly_bb_pullback_atr,
        )

        exit_idx = int(exit_info["exitIdx"])
        exit_price = float(exit_info["exitPrice"])
        gross_return_pct = ((exit_price - entry_price) / entry_price) * 100
        net_return_pct = gross_return_pct - (fee_bps * 2 / 100)
        market_signal_snapshot = _market_regime_snapshot(market_regime_daily, signal_date)
        market_exit_snapshot = _market_regime_snapshot(market_regime_daily, daily.index[exit_idx])

        trades.append(
            {
                "symbol": symbol.upper(),
                "assetClass": classify_asset(symbol),
                "strategyVersion": signal.get("strategyVersion", strategy_version),
                "poolType": signal.get("poolType"),
                "entryScore": signal.get("entryScore"),
                "riskLevel": signal.get("riskLevel"),
                "signalDate": _date_str(signal_date),
                "entryDate": _date_str(entry_date),
                "exitDate": _date_str(daily.index[exit_idx]),
                "entryPrice": entry_price,
                "exitPrice": exit_price,
                "stopPrice": signal.get("stopPrice"),
                "targetPrice": signal.get("targetPrice"),
                "returnPct": net_return_pct,
                "holdingDays": exit_idx - entry_idx + 1,
                "exitReason": exit_info["exitReason"],
                "marketRegimeAtSignal": market_signal_snapshot["marketRegime"],
                "marketRegimeAtEntry": market_entry_snapshot["marketRegime"],
                "marketRegimeAtExit": market_exit_snapshot["marketRegime"],
                "marketCloseVsEma20PctAtSignal": market_signal_snapshot.get("marketCloseVsEma20Pct"),
                "marketEma20VsEma50PctAtSignal": market_signal_snapshot.get("marketEma20VsEma50Pct"),
                "marketCloseVsEma20PctAtEntry": market_entry_snapshot.get("marketCloseVsEma20Pct"),
                "marketEma20VsEma50PctAtEntry": market_entry_snapshot.get("marketEma20VsEma50Pct"),
            }
        )

        signal_idx = max(exit_idx + 1, signal_idx + cooldown_bars + 1)

    return trades


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


def simulate_closed_trade_portfolio(
    trades: List[Dict[str, object]],
    max_positions: int = 5,
) -> Dict[str, object]:
    if max_positions <= 0:
        raise ValueError("max_positions must be greater than 0")

    sorted_trades = sorted(
        trades,
        key=lambda trade: (
            pd.Timestamp(trade.get("entryDate") or trade.get("signalDate") or "1900-01-01"),
            str(trade.get("symbol") or ""),
        ),
    )
    open_trades: List[Dict[str, object]] = []
    accepted_trades = []
    skipped_trades = []
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    equity_points = [{"date": None, "equity": equity, "drawdownPct": 0.0}]

    def close_finished(before_date) -> None:
        nonlocal equity, peak, max_drawdown
        still_open = []
        for open_trade in open_trades:
            exit_date = pd.Timestamp(open_trade.get("exitDate") or open_trade.get("entryDate"))
            if exit_date < before_date:
                slot_return = float(open_trade.get("returnPct") or 0.0) / max_positions
                equity *= 1 + slot_return / 100
                peak = max(peak, equity)
                drawdown = (peak - equity) / peak * 100 if peak else 0.0
                max_drawdown = max(max_drawdown, drawdown)
                equity_points.append(
                    {
                        "date": _date_str(exit_date),
                        "equity": equity,
                        "drawdownPct": drawdown,
                    }
                )
            else:
                still_open.append(open_trade)
        open_trades[:] = still_open

    for trade in sorted_trades:
        entry_date = pd.Timestamp(trade.get("entryDate") or trade.get("signalDate"))
        close_finished(entry_date)
        if len(open_trades) >= max_positions:
            skipped_trades.append(trade)
            continue
        open_trades.append(trade)
        accepted_trades.append(trade)

    close_finished(pd.Timestamp.max)
    total_return_pct = (equity - 1) * 100
    first_date = accepted_trades[0].get("entryDate") if accepted_trades else None
    last_date = accepted_trades[-1].get("exitDate") if accepted_trades else None

    return {
        "mode": "closed_trade_equal_slot",
        "maxPositions": max_positions,
        "acceptedTradeCount": len(accepted_trades),
        "skippedTradeCount": len(skipped_trades),
        "totalReturnPct": total_return_pct,
        "maxDrawdownPct": max_drawdown,
        "startDate": first_date,
        "endDate": last_date,
        "equityCurve": equity_points,
    }


def _close_on_or_before(df_daily: pd.DataFrame, as_of) -> Optional[float]:
    if df_daily is None or df_daily.empty or "Close" not in df_daily.columns:
        return None
    window = df_daily.sort_index()
    window = window[window.index <= pd.Timestamp(as_of)]
    if window.empty:
        return None
    close = window.iloc[-1].get("Close")
    if pd.isna(close):
        return None
    return float(close)


def _select_portfolio_trades(
    trades: List[Dict[str, object]],
    max_positions: int,
) -> tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    if max_positions <= 0:
        raise ValueError("max_positions must be greater than 0")

    sorted_trades = sorted(
        trades,
        key=lambda trade: (
            pd.Timestamp(trade.get("entryDate") or trade.get("signalDate") or "1900-01-01"),
            str(trade.get("symbol") or ""),
        ),
    )
    open_trades: List[Dict[str, object]] = []
    accepted_trades = []
    skipped_trades = []

    for trade in sorted_trades:
        entry_date = pd.Timestamp(trade.get("entryDate") or trade.get("signalDate"))
        open_trades = [
            open_trade
            for open_trade in open_trades
            if pd.Timestamp(open_trade.get("exitDate") or open_trade.get("entryDate")) >= entry_date
        ]
        if len(open_trades) >= max_positions:
            skipped_trades.append(trade)
            continue
        open_trades.append(trade)
        accepted_trades.append(trade)

    return accepted_trades, skipped_trades


def simulate_mark_to_market_portfolio(
    trades: List[Dict[str, object]],
    daily_frames_by_symbol: Dict[str, pd.DataFrame],
    max_positions: int = 5,
    curve_start: Optional[str] = None,
    curve_end: Optional[str] = None,
) -> Dict[str, object]:
    accepted_trades, skipped_trades = _select_portfolio_trades(trades, max_positions=max_positions)
    if not accepted_trades:
        return {
            "mode": "daily_mark_to_market_equal_slot",
            "maxPositions": max_positions,
            "acceptedTradeCount": 0,
            "skippedTradeCount": len(skipped_trades),
            "totalReturnPct": 0.0,
            "maxDrawdownPct": 0.0,
            "startDate": curve_start,
            "endDate": curve_end,
            "equityCurve": [],
        }

    trade_start = min(pd.Timestamp(trade.get("entryDate")) for trade in accepted_trades)
    trade_end = max(pd.Timestamp(trade.get("exitDate") or trade.get("entryDate")) for trade in accepted_trades)
    start_date = pd.Timestamp(curve_start) if curve_start else trade_start
    end_date = pd.Timestamp(curve_end) if curve_end else trade_end
    date_values = set(pd.date_range(start_date, end_date, freq="B"))
    for trade in accepted_trades:
        date_values.add(pd.Timestamp(trade.get("entryDate")))
        date_values.add(pd.Timestamp(trade.get("exitDate") or trade.get("entryDate")))
    dates = sorted(d for d in date_values if start_date <= d <= end_date)

    entries_by_date: Dict[str, List[Dict[str, object]]] = {}
    exits_by_date: Dict[str, List[Dict[str, object]]] = {}
    for trade in accepted_trades:
        entries_by_date.setdefault(_date_str(trade.get("entryDate")), []).append(trade)
        exits_by_date.setdefault(_date_str(trade.get("exitDate") or trade.get("entryDate")), []).append(trade)

    cash = 1.0
    open_positions: List[Dict[str, object]] = []
    peak = 1.0
    max_drawdown = 0.0
    equity_curve = []

    def mark_open_positions(as_of) -> float:
        total = 0.0
        for position in open_positions:
            symbol = str(position["symbol"]).upper()
            close = _close_on_or_before(daily_frames_by_symbol.get(symbol), as_of)
            if close is None:
                close = float(position["entryPrice"])
            total += float(position["allocation"]) * (close / float(position["entryPrice"]))
        return total

    for date in dates:
        date_key = _date_str(date)
        current_equity = cash + mark_open_positions(date)
        for trade in entries_by_date.get(date_key, []):
            if len(open_positions) >= max_positions:
                continue
            allocation = min(cash, current_equity / max_positions)
            if allocation <= 0:
                continue
            cash -= allocation
            open_positions.append(
                {
                    "symbol": str(trade.get("symbol") or "").upper(),
                    "entryPrice": float(trade.get("entryPrice") or 0.0),
                    "allocation": allocation,
                    "trade": trade,
                }
            )

        remaining_positions = []
        for position in open_positions:
            trade = position["trade"]
            if _date_str(trade.get("exitDate") or trade.get("entryDate")) == date_key:
                cash += float(position["allocation"]) * (1 + float(trade.get("returnPct") or 0.0) / 100)
            else:
                remaining_positions.append(position)
        open_positions = remaining_positions

        equity = cash + mark_open_positions(date)
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak * 100 if peak else 0.0
        max_drawdown = max(max_drawdown, drawdown)
        equity_curve.append(
            {
                "date": date_key,
                "equity": equity,
                "drawdownPct": drawdown,
                "openPositions": len(open_positions),
                "cash": cash,
            }
        )

    total_return_pct = (equity_curve[-1]["equity"] - 1) * 100 if equity_curve else 0.0
    return {
        "mode": "daily_mark_to_market_equal_slot",
        "maxPositions": max_positions,
        "acceptedTradeCount": len(accepted_trades),
        "skippedTradeCount": len(skipped_trades),
        "totalReturnPct": total_return_pct,
        "maxDrawdownPct": max_drawdown,
        "startDate": _date_str(start_date),
        "endDate": _date_str(end_date),
        "equityCurve": equity_curve,
    }


_RS_CASH_SYMBOL = "__CASH__"

# Supported market filter modes for RS rotation
# "monthly_macd": DIF > DEA on monthly-resampled bars (recommended for A-share)
# "weekly_macd":  DIF > DEA on weekly bars
# "ema20_slope":  EMA20 rising over last 11 bars
# "close_above_ema50": Close > EMA50
# "bullish_ema":  Close > EMA20 > EMA50
# "none":         always bullish (no filter)


def _rs_asset_class(symbol: str) -> str:
    """Map a symbol to its asset class for per-class market filters."""
    s = symbol.upper()
    if s.endswith(".SS") or s.endswith(".SZ"):
        return "a_share"
    if s.endswith("-USD"):
        return "crypto"
    if s.endswith("=F"):
        return "commodity"
    if s in ("SPY", "QQQ", "DIA", "IWM") or "." not in s:
        return "us"
    return "us"


def _rs_market_is_bullish(
    fdf: Optional[pd.DataFrame],
    mode: str,
    as_of,
    monthly_cache: Dict[int, pd.DataFrame],
    weekly_df: Optional[pd.DataFrame] = None,
) -> bool:
    """Return True if the market filter allows entry at as_of."""
    if mode == "none" or fdf is None or fdf.empty:
        return True
    if mode == "monthly_macd":
        fid = id(fdf)
        if fid not in monthly_cache:
            monthly_cache[fid] = fdf.resample("ME").last()
        src = monthly_cache[fid]
        w = src[src.index <= pd.Timestamp(as_of)]
        if w.empty or "MACD_DIF" not in w.columns or "MACD_DEA" not in w.columns:
            return True
        return float(w.iloc[-1]["MACD_DIF"]) > float(w.iloc[-1]["MACD_DEA"])
    if mode == "weekly_macd":
        src = weekly_df if weekly_df is not None else fdf.resample("W").last()
        w = src[src.index <= pd.Timestamp(as_of)]
        if w.empty or "MACD_DIF" not in w.columns or "MACD_DEA" not in w.columns:
            return True
        return float(w.iloc[-1]["MACD_DIF"]) > float(w.iloc[-1]["MACD_DEA"])
    w = fdf[fdf.index <= as_of]
    if w.empty or "EMA20" not in w.columns:
        return True
    if mode == "ema20_slope":
        return len(w) >= 11 and float(w.iloc[-1]["EMA20"]) > float(w.iloc[-11]["EMA20"])
    if mode == "close_above_ema50":
        return "EMA50" in w.columns and float(w.iloc[-1]["Close"]) > float(w.iloc[-1]["EMA50"])
    if "EMA50" not in w.columns:
        return True
    # default: bullish_ema — Close > EMA20 > EMA50
    return float(w.iloc[-1]["Close"]) > float(w.iloc[-1]["EMA20"]) and float(w.iloc[-1]["EMA20"]) > float(w.iloc[-1]["EMA50"])


def _rs_rank_symbols(
    daily_frames_by_symbol: Dict[str, pd.DataFrame],
    as_of,
    top_n: int,
    lookback_bars: int,
    min_history_bars: int,
    min_avg_volume: float,
    volume_lookback: int,
    daily_cash_yield: float,
    per_class_filters: Optional[Dict[str, tuple]],
    legacy_market_df: Optional[pd.DataFrame],
    legacy_market_mode: str,
    max_slots_per_class: Optional[Dict[str, int]],
    monthly_cache: Dict[int, pd.DataFrame],
    weekly_df: Optional[pd.DataFrame],
) -> List[str]:
    """Rank symbols by lookback_bars momentum and return top_n after filters."""
    scores = []
    if daily_cash_yield > 0:
        scores.append((_RS_CASH_SYMBOL, daily_cash_yield * lookback_bars))

    for symbol, df in daily_frames_by_symbol.items():
        if df is None or df.empty or "Close" not in df.columns:
            continue

        # Market regime filter
        if per_class_filters is not None:
            cls = _rs_asset_class(symbol)
            if cls in per_class_filters:
                fdf, mode = per_class_filters[cls]
                if not _rs_market_is_bullish(fdf, mode, as_of, monthly_cache, weekly_df):
                    continue
        else:
            if not _rs_market_is_bullish(legacy_market_df, legacy_market_mode, as_of, monthly_cache, weekly_df):
                continue

        window = df[df.index <= as_of].dropna(subset=["Close"])
        if len(window) < min_history_bars:
            continue
        if min_avg_volume > 0 and "Volume" in window.columns:
            avg_vol = window["Volume"].tail(volume_lookback).mean()
            if pd.isna(avg_vol) or float(avg_vol) < min_avg_volume:
                continue
        if len(window) <= lookback_bars:
            continue

        cur = float(window.iloc[-1]["Close"])
        prior = float(window.iloc[-lookback_bars - 1]["Close"])
        if prior > 0:
            scores.append((symbol.upper(), (cur - prior) / prior))

    scores.sort(key=lambda x: x[1], reverse=True)

    if not max_slots_per_class:
        return [s for s, _ in scores[:top_n]]

    result: List[str] = []
    class_counts: Dict[str, int] = {}
    for sym, _ in scores:
        if len(result) >= top_n:
            break
        cls = _rs_asset_class(sym)
        if class_counts.get(cls, 0) >= max_slots_per_class.get(cls, top_n):
            continue
        result.append(sym)
        class_counts[cls] = class_counts.get(cls, 0) + 1
    return result


def simulate_rs_rotation_portfolio(
    daily_frames_by_symbol: Dict[str, pd.DataFrame],
    top_n: int = 5,
    rebalance_days: int = 20,
    lookback_bars: int = 60,
    start: Optional[str] = None,
    end: Optional[str] = None,
    fee_bps: float = 5.0,
    slippage_bps: float = 5.0,
    market_filter_symbol: Optional[str] = None,
    market_filter_df: Optional[pd.DataFrame] = None,
    market_filter_mode: str = "ema20_slope",
    market_filter_weekly_df: Optional[pd.DataFrame] = None,
    min_history_bars: int = 250,
    min_avg_volume: float = 1e8,
    volume_lookback: int = 60,
    per_class_filters: Optional[Dict[str, tuple]] = None,
    max_slots_per_class: Optional[Dict[str, int]] = None,
    cash_yield_annual: float = 0.0,
) -> Dict[str, object]:
    """
    Simulate a momentum-based rotation portfolio.

    Rebalances every rebalance_days trading days, holding the top_n symbols
    ranked by lookback_bars price return. Market filters (monthly_macd, etc.)
    gate entry per asset class via per_class_filters, or globally via
    market_filter_df + market_filter_mode.

    per_class_filters keys: "a_share" (.SS/.SZ), "us", "crypto" (-USD), "commodity" (=F)
    """
    daily_cash_yield = (1 + cash_yield_annual) ** (1 / 252) - 1

    all_dates: set = set()
    for df in daily_frames_by_symbol.values():
        if df is not None and not df.empty:
            all_dates.update(df.index)
    if not all_dates:
        return {"mode": "rs_rotation", "totalReturnPct": 0.0, "maxDrawdownPct": 0.0, "equityCurve": []}

    dates = sorted(all_dates)
    if start:
        dates = [d for d in dates if d >= pd.Timestamp(start)]
    if end:
        dates = [d for d in dates if d <= pd.Timestamp(end)]
    if not dates:
        return {"mode": "rs_rotation", "totalReturnPct": 0.0, "maxDrawdownPct": 0.0, "equityCurve": []}

    legacy_market_df = (
        market_filter_df
        if market_filter_df is not None
        else daily_frames_by_symbol.get((market_filter_symbol or "").upper()) if market_filter_symbol else None
    )
    monthly_cache: Dict[int, pd.DataFrame] = {}

    fee_factor = fee_bps / 10_000
    slip_factor = slippage_bps / 10_000

    def _cash_accrued_price(as_of, entry_date) -> float:
        days = max(0, (pd.Timestamp(as_of) - pd.Timestamp(entry_date)).days)
        return (1 + daily_cash_yield) ** days

    portfolio_cash = 1.0
    holdings: Dict[str, Dict] = {}
    peak = 1.0
    max_drawdown = 0.0
    equity_curve = []
    last_rebalance_idx = -rebalance_days

    def _portfolio_value(as_of) -> float:
        total = portfolio_cash
        for sym, pos in holdings.items():
            if sym == _RS_CASH_SYMBOL:
                price = _cash_accrued_price(as_of, pos["entry_date"])
            else:
                price = _close_on_or_before(daily_frames_by_symbol.get(sym), as_of) or pos["cost_price"]
            total += pos["shares"] * price
        return total

    for idx, date in enumerate(dates):
        for sym, pos in holdings.items():
            if sym == _RS_CASH_SYMBOL:
                pos["cost_price"] = _cash_accrued_price(date, pos["entry_date"])

        if idx - last_rebalance_idx >= rebalance_days:
            last_rebalance_idx = idx
            target_symbols = set(_rs_rank_symbols(
                daily_frames_by_symbol, date, top_n, lookback_bars,
                min_history_bars, min_avg_volume, volume_lookback,
                daily_cash_yield, per_class_filters, legacy_market_df,
                market_filter_mode, max_slots_per_class, monthly_cache,
                market_filter_weekly_df,
            ))

            for sym in list(set(holdings.keys()) - target_symbols):
                pos = holdings.pop(sym)
                if sym == _RS_CASH_SYMBOL:
                    portfolio_cash += pos["shares"] * pos["cost_price"]
                else:
                    price = _close_on_or_before(daily_frames_by_symbol.get(sym), date) or pos["cost_price"]
                    portfolio_cash += pos["shares"] * price * (1 - slip_factor) * (1 - fee_factor)

            new_buys = list(target_symbols - set(holdings.keys()))[: top_n - len(holdings)]
            if new_buys:
                per_slot = _portfolio_value(date) / top_n
                for sym in new_buys:
                    if sym == _RS_CASH_SYMBOL:
                        cost = min(portfolio_cash, per_slot)
                        if cost <= 0:
                            continue
                        portfolio_cash -= cost
                        holdings[sym] = {"shares": cost, "cost_price": 1.0, "entry_date": date}
                    else:
                        price = _close_on_or_before(daily_frames_by_symbol.get(sym), date)
                        if not price or price <= 0:
                            continue
                        cost = min(portfolio_cash, per_slot)
                        if cost <= 0:
                            continue
                        net_cost = min(cost * (1 + fee_factor), portfolio_cash)
                        shares = (net_cost / (1 + fee_factor)) / (price * (1 + slip_factor))
                        portfolio_cash -= net_cost
                        holdings[sym] = {"shares": shares, "cost_price": price * (1 + slip_factor), "entry_date": date}

        equity = _portfolio_value(date)
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak * 100 if peak else 0.0
        max_drawdown = max(max_drawdown, drawdown)
        equity_curve.append({
            "date": _date_str(date),
            "equity": equity,
            "drawdownPct": drawdown,
            "openPositions": len(holdings),
            "holdings": sorted(holdings.keys()),
        })

    total_return_pct = (equity_curve[-1]["equity"] - 1) * 100 if equity_curve else 0.0
    return {
        "mode": "rs_rotation",
        "topN": top_n,
        "rebalanceDays": rebalance_days,
        "lookbackBars": lookback_bars,
        "marketFilter": market_filter_symbol,
        "startDate": _date_str(dates[0]),
        "endDate": _date_str(dates[-1]),
        "totalReturnPct": total_return_pct,
        "maxDrawdownPct": max_drawdown,
        "equityCurve": equity_curve,
    }


def _relative_strength_bucket(rank: Optional[int], universe_size: Optional[int]) -> str:
    if not rank or not universe_size:
        return "unknown"
    percentile = rank / universe_size
    if percentile <= 0.2:
        return "top20"
    if percentile <= 0.5:
        return "top50"
    if percentile <= 0.8:
        return "middle"
    return "bottom20"


def annotate_relative_strength(
    trades: List[Dict[str, object]],
    daily_frames_by_symbol: Dict[str, pd.DataFrame],
    lookback_bars: int = 60,
) -> List[Dict[str, object]]:
    rankings_by_date: Dict[str, Dict[str, Dict[str, object]]] = {}

    for trade in trades:
        entry_date = trade.get("entryDate")
        if not entry_date:
            continue
        date_key = _date_str(entry_date)
        if date_key in rankings_by_date:
            continue

        scores = []
        for symbol, df_daily in daily_frames_by_symbol.items():
            if df_daily is None or df_daily.empty or "Close" not in df_daily.columns:
                continue
            window = df_daily.sort_index()
            window = window[window.index <= pd.Timestamp(entry_date)].dropna(subset=["Close"])
            if len(window) <= lookback_bars:
                continue
            current_close = float(window.iloc[-1]["Close"])
            prior_close = float(window.iloc[-lookback_bars - 1]["Close"])
            if prior_close <= 0:
                continue
            scores.append(
                {
                    "symbol": symbol.upper(),
                    "relativeStrengthPct": ((current_close - prior_close) / prior_close) * 100,
                }
            )

        ranked_scores = sorted(scores, key=lambda row: float(row["relativeStrengthPct"]), reverse=True)
        universe_size = len(ranked_scores)
        rankings_by_date[date_key] = {
            row["symbol"]: {
                **row,
                "relativeStrengthRank": idx + 1,
                "relativeStrengthUniverseSize": universe_size,
                "relativeStrengthBucket": _relative_strength_bucket(idx + 1, universe_size),
            }
            for idx, row in enumerate(ranked_scores)
        }

    annotated = []
    for trade in trades:
        next_trade = dict(trade)
        symbol = str(next_trade.get("symbol") or "").upper()
        entry_date = next_trade.get("entryDate")
        ranking = rankings_by_date.get(_date_str(entry_date), {}).get(symbol) if entry_date else None
        if ranking:
            next_trade.update(ranking)
        else:
            next_trade.setdefault("relativeStrengthPct", None)
            next_trade.setdefault("relativeStrengthRank", None)
            next_trade.setdefault("relativeStrengthUniverseSize", None)
            next_trade.setdefault("relativeStrengthBucket", "unknown")
        annotated.append(next_trade)
    return annotated


def _summarize_grouped(
    trades: List[Dict[str, object]],
    key: str,
    strategy_version: str,
) -> Dict[str, Dict[str, object]]:
    grouped: Dict[str, List[Dict[str, object]]] = {}
    for trade in trades:
        value = str(trade.get(key) or "unknown")
        grouped.setdefault(value, []).append(trade)
    return {
        value: summarize_trades(group_trades, strategy_version=strategy_version)
        for value, group_trades in sorted(grouped.items())
    }


def _filter_trades(
    trades: List[Dict[str, object]],
    asset_class_filter: Optional[str] = None,
    pool_type_filter: Optional[str] = None,
    relative_strength_bucket_filter: Optional[str] = None,
) -> List[Dict[str, object]]:
    relative_strength_buckets = None
    if relative_strength_bucket_filter:
        relative_strength_buckets = {
            bucket.strip()
            for bucket in relative_strength_bucket_filter.split(",")
            if bucket.strip()
        }

    filtered = []
    for trade in trades:
        if asset_class_filter and trade.get("assetClass") != asset_class_filter:
            continue
        if pool_type_filter and trade.get("poolType") != pool_type_filter:
            continue
        if relative_strength_buckets and trade.get("relativeStrengthBucket") not in relative_strength_buckets:
            continue
        filtered.append(trade)
    return filtered


def _trade_year(trade: Dict[str, object]) -> str:
    date_value = trade.get("entryDate") or trade.get("signalDate") or trade.get("exitDate")
    if not date_value:
        return "unknown"
    return str(date_value)[:4]


def _symbol_contribution(
    trades: List[Dict[str, object]],
    strategy_version: str,
) -> List[Dict[str, object]]:
    grouped: Dict[str, List[Dict[str, object]]] = {}
    for trade in trades:
        grouped.setdefault(str(trade.get("symbol") or "UNKNOWN"), []).append(trade)

    rows = []
    for symbol, symbol_trades in grouped.items():
        summary = summarize_trades(symbol_trades, strategy_version=strategy_version)
        rows.append(
            {
                "symbol": symbol,
                "tradeCount": summary["tradeCount"],
                "winRate": summary["winRate"],
                "averageReturnPct": summary["averageReturnPct"],
                "totalReturnPct": sum(float(trade["returnPct"]) for trade in symbol_trades),
                "maxDrawdownPct": summary["maxDrawdownPct"],
                "exitReasonCounts": summary["exitReasonCounts"],
            }
        )
    return sorted(rows, key=lambda row: row["totalReturnPct"], reverse=True)


def _entry_score_bucket(score) -> str:
    if score is None:
        return "unknown"
    try:
        numeric_score = float(score)
    except (TypeError, ValueError):
        return "unknown"
    if numeric_score > 10:
        if numeric_score >= 90:
            return "90-100"
        if numeric_score >= 70:
            return "70-89"
        if numeric_score >= 50:
            return "50-69"
        return "0-49"
    if numeric_score >= 9:
        return "9-10"
    if numeric_score >= 7:
        return "7-8"
    if numeric_score >= 5:
        return "5-6"
    return "0-4"


def _loss_summary(trades: List[Dict[str, object]]) -> Dict[str, object]:
    loss_trades = [trade for trade in trades if float(trade.get("returnPct") or 0) < 0]
    if not loss_trades:
        return {
            "lossTradeCount": 0,
            "averageLossPct": 0.0,
            "totalLossPct": 0.0,
            "worstReturnPct": 0.0,
        }

    losses = [float(trade["returnPct"]) for trade in loss_trades]
    return {
        "lossTradeCount": len(loss_trades),
        "averageLossPct": sum(losses) / len(losses),
        "totalLossPct": sum(losses),
        "worstReturnPct": min(losses),
    }


def _worst_trades(trades: List[Dict[str, object]], limit: int = 10) -> List[Dict[str, object]]:
    rows = []
    for trade in sorted(trades, key=lambda item: float(item.get("returnPct") or 0))[:limit]:
        rows.append(
            {
                "symbol": trade.get("symbol"),
                "entryDate": trade.get("entryDate"),
                "exitDate": trade.get("exitDate"),
                "returnPct": trade.get("returnPct"),
                "exitReason": trade.get("exitReason"),
                "holdingDays": trade.get("holdingDays"),
                "poolType": trade.get("poolType"),
                "entryScore": trade.get("entryScore"),
                "riskLevel": trade.get("riskLevel"),
            }
        )
    return rows


def _diagnostics(
    trades: List[Dict[str, object]],
    strategy_version: str,
) -> Dict[str, object]:
    scored_trades = [
        {**trade, "entryScoreBucket": _entry_score_bucket(trade.get("entryScore"))}
        for trade in trades
    ]
    return {
        "lossSummary": _loss_summary(trades),
        "worstTrades": _worst_trades(trades),
        "byEntryScoreBucket": _summarize_grouped(scored_trades, "entryScoreBucket", strategy_version),
        "byRelativeStrengthBucket": _summarize_grouped(trades, "relativeStrengthBucket", strategy_version),
        "byRiskLevel": _summarize_grouped(trades, "riskLevel", strategy_version),
        "byExitReason": _summarize_grouped(trades, "exitReason", strategy_version),
        "byMarketRegimeAtExit": _summarize_grouped(trades, "marketRegimeAtExit", strategy_version),
    }


def _diagnostics_by_year(
    trades: List[Dict[str, object]],
    strategy_version: str,
) -> Dict[str, Dict[str, object]]:
    grouped: Dict[str, List[Dict[str, object]]] = {}
    for trade in trades:
        grouped.setdefault(_trade_year(trade), []).append(trade)
    return {
        year: _diagnostics(year_trades, strategy_version=strategy_version)
        for year, year_trades in sorted(grouped.items())
    }


def summarize_backtest_report(
    trades: List[Dict[str, object]],
    strategy_version: str = DEFAULT_STRATEGY_VERSION_ID,
    asset_class_filter: Optional[str] = None,
    pool_type_filter: Optional[str] = None,
    relative_strength_bucket_filter: Optional[str] = None,
    portfolio_max_positions: int = 5,
    benchmark_daily_frames: Optional[Dict[str, pd.DataFrame]] = None,
    benchmark_start: Optional[str] = None,
    benchmark_end: Optional[str] = None,
    fee_bps: float = 5.0,
    slippage_bps: float = 5.0,
    rs_market_filter_symbol: Optional[str] = None,
    market_regime_daily: Optional[pd.DataFrame] = None,
) -> Dict[str, object]:
    normalized_trades = []
    for trade in trades:
        next_trade = dict(trade)
        next_trade.setdefault("assetClass", classify_asset(str(next_trade.get("symbol", ""))))
        normalized_trades.append(next_trade)
    if benchmark_daily_frames is not None:
        normalized_trades = annotate_relative_strength(normalized_trades, benchmark_daily_frames)
    filtered_trades = _filter_trades(
        normalized_trades,
        asset_class_filter=asset_class_filter,
        pool_type_filter=pool_type_filter,
        relative_strength_bucket_filter=relative_strength_bucket_filter,
    )

    report = {
        "summary": summarize_trades(filtered_trades, strategy_version=strategy_version),
        "byPoolType": _summarize_grouped(filtered_trades, "poolType", strategy_version),
        "byAssetClass": _summarize_grouped(filtered_trades, "assetClass", strategy_version),
        "byYear": _summarize_grouped(
            [{**trade, "year": _trade_year(trade)} for trade in filtered_trades],
            "year",
            strategy_version,
        ),
        "symbolContribution": _symbol_contribution(filtered_trades, strategy_version),
        "diagnostics": _diagnostics(filtered_trades, strategy_version),
        "diagnosticsByYear": _diagnostics_by_year(filtered_trades, strategy_version),
        "filters": {
            "assetClass": asset_class_filter,
            "poolType": pool_type_filter,
            "relativeStrengthBucket": relative_strength_bucket_filter,
        },
        "portfolio": simulate_closed_trade_portfolio(
            filtered_trades,
            max_positions=portfolio_max_positions,
        ),
    }
    if benchmark_daily_frames is not None:
        report["benchmark"] = summarize_buy_and_hold_benchmark(
            benchmark_daily_frames,
            start=benchmark_start,
            end=benchmark_end,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
        report["markToMarketPortfolio"] = simulate_mark_to_market_portfolio(
            filtered_trades,
            benchmark_daily_frames,
            max_positions=portfolio_max_positions,
            curve_start=benchmark_start,
            curve_end=benchmark_end,
        )
        report["rsRotationPortfolio"] = simulate_rs_rotation_portfolio(
            benchmark_daily_frames,
            top_n=portfolio_max_positions,
            start=benchmark_start,
            end=benchmark_end,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            market_filter_symbol=rs_market_filter_symbol,
            market_filter_df=market_regime_daily,
        )
    return report


def _load_symbol_frames(symbol: str, data_dir: str) -> Optional[tuple[pd.DataFrame, pd.DataFrame]]:
    daily_path = os.path.join(data_dir, f"{symbol.upper()}.parquet")
    weekly_path = os.path.join(data_dir, f"{symbol.upper()}_weekly.parquet")
    if not os.path.exists(daily_path) or not os.path.exists(weekly_path):
        return None
    return pd.read_parquet(daily_path), pd.read_parquet(weekly_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run resonance strategy backtests from cached parquet data.")
    parser.add_argument("--symbols", nargs="+")
    parser.add_argument("--universe-file")
    parser.add_argument("--strategy-version", default=DEFAULT_STRATEGY_VERSION_ID)
    parser.add_argument("--data-dir", default=DATA_DIR)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--max-hold-days", type=int, default=30)
    parser.add_argument("--cooldown-bars", type=int, default=3)
    parser.add_argument("--fee-bps", type=float, default=5.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--market-filter", choices=["none", "bullish_ema"], default="none")
    parser.add_argument("--market-symbol", default=None)
    parser.add_argument("--entry-market-filter", choices=["none", "bullish_ema"], default=None)
    parser.add_argument("--entry-market-min-close-vs-ema20-pct", type=float, default=None)
    parser.add_argument("--asset-class-filter", default=None)
    parser.add_argument("--pool-type-filter", default=None)
    parser.add_argument("--relative-strength-bucket-filter", default=None)
    parser.add_argument("--portfolio-max-positions", type=int, default=5)
    args = parser.parse_args()
    version = get_strategy_version(args.strategy_version)
    market_filter, market_symbol = resolve_market_settings(
        cli_market_filter=args.market_filter,
        cli_market_symbol=args.market_symbol,
        version=version,
    )
    asset_class_filter = args.asset_class_filter or version.asset_class_filter
    pool_type_filter = args.pool_type_filter or version.pool_type_filter
    relative_strength_bucket_filter = (
        args.relative_strength_bucket_filter or version.relative_strength_bucket_filter
    )
    entry_market_filter = args.entry_market_filter or version.entry_market_filter
    entry_market_min_close_vs_ema20_pct = (
        args.entry_market_min_close_vs_ema20_pct
        if args.entry_market_min_close_vs_ema20_pct is not None
        else version.entry_market_min_close_vs_ema20_pct
    )
    symbols = _normalize_symbol_list(args.symbols)
    if args.universe_file:
        symbols.extend(symbol for symbol in load_universe_symbols(args.universe_file) if symbol not in symbols)
    if not symbols:
        parser.error("Provide --symbols and/or --universe-file")

    all_trades: List[Dict[str, object]] = []
    missing_symbols = []
    benchmark_daily_frames: Dict[str, pd.DataFrame] = {}
    market_regime_daily = None
    uses_market_context = (
        market_filter != "none"
        or entry_market_filter != "none"
        or entry_market_min_close_vs_ema20_pct > 0
    )
    if uses_market_context:
        market_frames = _load_symbol_frames(market_symbol, args.data_dir)
        if market_frames is not None:
            market_regime_daily = market_frames[0]

    for symbol in symbols:
        frames = _load_symbol_frames(symbol, args.data_dir)
        if frames is None:
            missing_symbols.append(symbol.upper())
            continue
        daily, weekly = frames
        if not asset_class_filter or classify_asset(symbol) == asset_class_filter:
            benchmark_daily_frames[symbol.upper()] = daily
        all_trades.extend(
            run_backtest_for_symbol(
                symbol,
                daily,
                weekly,
                strategy_version=args.strategy_version,
                max_hold_days=args.max_hold_days,
                cooldown_bars=args.cooldown_bars,
                fee_bps=args.fee_bps,
                slippage_bps=args.slippage_bps,
                market_regime_daily=market_regime_daily,
                market_filter=market_filter,
                entry_market_filter=entry_market_filter,
                entry_market_min_close_vs_ema20_pct=entry_market_min_close_vs_ema20_pct,
                start=args.start,
                end=args.end,
            )
        )

    if benchmark_daily_frames:
        all_trades = annotate_relative_strength(all_trades, benchmark_daily_frames)

    report = summarize_backtest_report(
        all_trades,
        strategy_version=args.strategy_version,
        asset_class_filter=asset_class_filter,
        pool_type_filter=pool_type_filter,
        relative_strength_bucket_filter=relative_strength_bucket_filter,
        portfolio_max_positions=args.portfolio_max_positions,
        benchmark_daily_frames=benchmark_daily_frames,
        benchmark_start=args.start,
        benchmark_end=args.end,
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
        rs_market_filter_symbol=market_symbol if uses_market_context else None,
        market_regime_daily=market_regime_daily if uses_market_context else None,
    )
    market_benchmark = None
    if uses_market_context and market_regime_daily is not None:
        market_benchmark = summarize_buy_and_hold_benchmark(
            {market_symbol: market_regime_daily},
            start=args.start,
            end=args.end,
            fee_bps=args.fee_bps,
            slippage_bps=args.slippage_bps,
        )
    output = {
        **report,
        "marketBenchmark": market_benchmark,
        "trades": all_trades,
        "missingSymbols": missing_symbols,
        "marketFilter": market_filter,
        "entryMarketFilter": entry_market_filter,
        "entryMarketMinCloseVsEma20Pct": entry_market_min_close_vs_ema20_pct,
        "marketSymbol": market_symbol if uses_market_context else None,
        "symbols": symbols,
        "start": args.start,
        "end": args.end,
        "benchmarkSymbolCount": report.get("benchmark", {}).get("symbolCount"),
        "portfolioMaxPositions": args.portfolio_max_positions,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


RS_ROTATION_PRESETS: Dict[str, Dict] = {
    "rs_rotation_a_share": {
        "id": "rs_rotation_a_share",
        "label": "RS轮动 · A股月MACD",
        "universe_file": "universes/a_share_etf_core.json",
        "extra_symbols": [],
        "min_avg_volume": 1e8,
        "per_class_filters": {"a_share": ("510300.SS", "monthly_macd")},
    },
    "rs_rotation_global": {
        "id": "rs_rotation_global",
        "label": "RS轮动 · 全球各自月MACD",
        "universe_file": "universes/a_share_etf_core.json",
        "extra_symbols": ["SPY", "QQQ", "GC=F", "BTC-USD"],
        "min_avg_volume": 0.0,
        "per_class_filters": {
            "a_share":   ("510300.SS", "monthly_macd"),
            "us":        ("SPY",       "monthly_macd"),
            "crypto":    ("BTC-USD",   "monthly_macd"),
            "commodity": ("GC=F",      "monthly_macd"),
        },
    },
}


def list_rs_rotation_presets() -> List[Dict]:
    return [{"id": v["id"], "label": v["label"]} for v in RS_ROTATION_PRESETS.values()]


if __name__ == "__main__":
    main()
