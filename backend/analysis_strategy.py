import math
import numbers
from typing import Optional, Tuple

import pandas as pd
from strategy_versions import get_strategy_version

from analysis_constants import (
    RESONANCE_GOLDEN_CROSS_LOOKBACK,
    RESONANCE_PULLBACK_LOOKBACK,
    RESONANCE_VOLUME_MA_WINDOW,
    RESONANCE_VOLUME_SHRINK_RATIO,
    RSI_THRESHOLDS,
)


def _finite_float(value, default: Optional[float] = None) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


def _make_json_safe(value):
    if isinstance(value, dict):
        return {k: _make_json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_make_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_make_json_safe(v) for v in value]
    if isinstance(value, numbers.Integral) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, numbers.Real) and not isinstance(value, bool):
        return None if not math.isfinite(float(value)) else float(value)
    if pd.isna(value):
        return None
    return value


def _risk_level_from_percent(risk_percent: Optional[float]) -> str:
    if risk_percent is None:
        return "unknown"
    if risk_percent <= 2.5:
        return "low"
    if risk_percent <= 5.0:
        return "medium"
    return "high"


def _is_recent_ema20_50_golden_cross(
    df_daily: pd.DataFrame, lookback_bars: int = RESONANCE_GOLDEN_CROSS_LOOKBACK
) -> Tuple[bool, Optional[int]]:
    if (
        df_daily is None
        or df_daily.empty
        or "EMA20" not in df_daily.columns
        or "EMA50" not in df_daily.columns
        or len(df_daily) < 2
    ):
        return False, None

    cond = df_daily["EMA20"] > df_daily["EMA50"]
    if not bool(cond.iloc[-1]):
        return False, None

    golden_cross = cond & (~cond.shift(1, fill_value=False))
    cross_positions = [i for i, flag in enumerate(golden_cross.tolist()) if bool(flag)]
    if not cross_positions:
        return False, None

    bars_since = len(df_daily) - 1 - int(cross_positions[-1])
    return bars_since <= lookback_bars, bars_since


def _has_pullback_reclaim_signal(
    df_daily: pd.DataFrame,
    ema_col: str,
    lookback_bars: int = RESONANCE_PULLBACK_LOOKBACK,
    volume_ma_window: int = RESONANCE_VOLUME_MA_WINDOW,
    volume_shrink_ratio: float = RESONANCE_VOLUME_SHRINK_RATIO,
) -> Tuple[bool, str]:
    required_cols = {"Low", "Close", "Volume", "EMA20", ema_col}
    if df_daily is None or df_daily.empty or not required_cols.issubset(df_daily.columns):
        return False, ""
    if len(df_daily) < max(volume_ma_window, 2):
        return False, ""

    volume_ma = df_daily["Volume"].rolling(window=volume_ma_window).mean()
    start_idx = max(1, len(df_daily) - lookback_bars)

    for i in range(len(df_daily) - 1, start_idx - 1, -1):
        low = float(df_daily["Low"].iloc[i])
        close = float(df_daily["Close"].iloc[i])
        ema = float(df_daily[ema_col].iloc[i])
        ema_prev = float(df_daily[ema_col].iloc[i - 1])
        ema20 = float(df_daily["EMA20"].iloc[i])
        vol = float(df_daily["Volume"].iloc[i])
        vol_ma = volume_ma.iloc[i]

        if (
            low <= ema and close >= ema
            and low >= ema20
            and ema > ema_prev
            and pd.notna(vol_ma) and float(vol_ma) > 0 and vol <= float(vol_ma) * volume_shrink_ratio
        ):
            return True, f"{ema_col}回踩确认"

    return False, ""


def _evaluate_resonance_strategy(df_daily: pd.DataFrame, df_weekly: pd.DataFrame) -> dict:
    result = {"inPool": False, "buySignal": False, "poolReason": "", "buyReason": ""}

    if (
        df_daily is None or df_daily.empty
        or df_weekly is None or df_weekly.empty
        or "Close" not in df_daily.columns
        or "MACD_W" not in df_weekly.columns
        or "MACD_Signal_W" not in df_weekly.columns
        or "MA5_W" not in df_weekly.columns
    ):
        return result

    price = float(df_daily["Close"].iloc[-1])
    w_last = df_weekly.iloc[-1]
    weekly_ok = float(w_last["MACD_W"]) > float(w_last["MACD_Signal_W"]) and price > float(w_last["MA5_W"])
    cross_ok, bars_since_cross = _is_recent_ema20_50_golden_cross(df_daily)
    result["inPool"] = weekly_ok and cross_ok

    if result["inPool"]:
        result["poolReason"] = (
            f"周线过滤通过; 日线EMA20/50金叉距今{bars_since_cross}根K线"
            if bars_since_cross is not None
            else "周线过滤通过; 日线EMA20/50金叉有效"
        )
    elif not weekly_ok:
        result["poolReason"] = "周线过滤未通过"
    else:
        result["poolReason"] = "日线EMA20/50金叉超出窗口或不存在"

    if not result["inPool"]:
        return result

    pullback_ema5, reason_ema5 = _has_pullback_reclaim_signal(df_daily, "EMA5")
    pullback_ema10, reason_ema10 = _has_pullback_reclaim_signal(df_daily, "EMA10")
    result["buySignal"] = pullback_ema5 or pullback_ema10
    result["buyReason"] = (reason_ema5 or reason_ema10) if result["buySignal"] else "最近未出现有效回踩确认"
    return result


def _evaluate_resonance_strategy_v2(
    df_daily: pd.DataFrame,
    df_weekly: pd.DataFrame,
    strategy_version: Optional[str] = None,
) -> dict:
    version = get_strategy_version(strategy_version)
    result = {
        "strategyVersion": version.id,
        "inPool": False,
        "buySignal": False,
        "poolType": "none",
        "entryScore": 0,
        "riskScore": 0,
        "riskLevel": "unknown",
        "entryPrice": None,
        "stopPrice": None,
        "riskPercent": None,
        "targetPrice": None,
        "rewardRiskRatio": None,
    }

    required_daily = {"Close", "Low", "Volume", "EMA5", "EMA10", "EMA20", "EMA50"}
    required_weekly = {"MACD_W", "MACD_Signal_W", "MA5_W"}
    if (
        df_daily is None or df_daily.empty
        or df_weekly is None or df_weekly.empty
        or not required_daily.issubset(df_daily.columns)
        or not required_weekly.issubset(df_weekly.columns)
    ):
        return result

    last_d = df_daily.iloc[-1]
    prev_d = df_daily.iloc[-2] if len(df_daily) >= 2 else last_d
    last_w = df_weekly.iloc[-1]

    price = _finite_float(last_d["Close"])
    ema20 = _finite_float(last_d["EMA20"])
    ema50 = _finite_float(last_d["EMA50"])
    ema20_prev = _finite_float(prev_d["EMA20"])
    w_macd = _finite_float(last_w["MACD_W"])
    w_signal = _finite_float(last_w["MACD_Signal_W"])
    w_ma5 = _finite_float(last_w["MA5_W"])

    if None in (price, ema20, ema50, ema20_prev, w_macd, w_signal, w_ma5):
        return result

    weekly_ok = w_macd > w_signal and price > w_ma5
    cross_ok, bars_since_cross = _is_recent_ema20_50_golden_cross(df_daily)
    trend_intact = ema20 > ema50 and price > ema20 and ema20 >= ema20_prev
    established_ok = (
        weekly_ok and trend_intact
        and bars_since_cross is not None
        and bars_since_cross <= version.established_trend_lookback
    )

    if weekly_ok and cross_ok:
        result["inPool"] = True
        result["poolType"] = "earlyTrend"
    elif established_ok:
        result["inPool"] = True
        result["poolType"] = "establishedTrend"

    pullback_ema5, _ = _has_pullback_reclaim_signal(df_daily, "EMA5")
    pullback_ema10, _ = _has_pullback_reclaim_signal(df_daily, "EMA10")
    result["buySignal"] = bool(result["inPool"] and (pullback_ema5 or pullback_ema10))

    score = 0
    if weekly_ok: score += 35
    if result["poolType"] == "earlyTrend": score += 25
    elif result["poolType"] == "establishedTrend": score += 20
    if trend_intact: score += 15
    if pullback_ema5: score += 15
    elif pullback_ema10: score += 12
    if result["buySignal"]: score += 10
    result["entryScore"] = min(100, score)

    result["entryPrice"] = price
    atr = _finite_float(last_d["ATR"]) if "ATR" in df_daily.columns else None
    if atr is not None and atr > 0 and price > 0:
        stop_distance = atr * version.atr_stop_multiplier
        target_distance = atr * version.atr_target_multiplier
        stop_price = price - stop_distance
        target_price = price + target_distance if target_distance > 0 else None
        risk_percent = (stop_distance / price) * 100
        reward_risk = target_distance / stop_distance if stop_distance > 0 and target_distance > 0 else None

        result["stopPrice"] = stop_price
        result["targetPrice"] = target_price
        result["riskPercent"] = risk_percent
        result["rewardRiskRatio"] = reward_risk
        result["riskLevel"] = _risk_level_from_percent(risk_percent)
        result["riskScore"] = max(0, min(100, round(100 - risk_percent * 12)))

    return _make_json_safe(result)


def _evaluate_resonance_exit_no_position(df_daily: pd.DataFrame, df_weekly: pd.DataFrame) -> dict:
    result = {"exitSignal": False, "exitLevel": "none", "exitReason": ""}

    required_daily = {"Close", "EMA20", "EMA50", "MACD_DIF", "MACD_DEA"}
    required_weekly = {"MACD_W", "MACD_Signal_W", "MA5_W"}
    if (
        df_daily is None or df_daily.empty
        or df_weekly is None or df_weekly.empty
        or not required_daily.issubset(df_daily.columns)
        or not required_weekly.issubset(df_weekly.columns)
    ):
        return result

    last_d = df_daily.iloc[-1]
    last_w = df_weekly.iloc[-1]
    price = float(last_d["Close"])
    ema20 = float(last_d["EMA20"])
    ema50 = float(last_d["EMA50"])
    macd_dif = float(last_d["MACD_DIF"])
    macd_dea = float(last_d["MACD_DEA"])
    w_macd = float(last_w["MACD_W"])
    w_signal = float(last_w["MACD_Signal_W"])
    w_ma5 = float(last_w["MA5_W"])

    if price < ema50:
        return {"exitSignal": True, "exitLevel": "hard", "exitReason": "收盘跌破EMA50"}
    if w_macd <= w_signal:
        return {"exitSignal": True, "exitLevel": "hard", "exitReason": "周线MACD走弱"}
    if price < w_ma5:
        return {"exitSignal": True, "exitLevel": "hard", "exitReason": "价格跌破周MA5"}
    if price < ema20:
        return {"exitSignal": True, "exitLevel": "warn", "exitReason": "收盘跌破EMA20"}
    if macd_dif <= macd_dea:
        return {"exitSignal": True, "exitLevel": "warn", "exitReason": "日线MACD死叉"}
    return result


def _analyze_trend(price: float, ema20: float, ema50: float) -> str:
    if ema20 > ema50 * 1.001:
        if price > ema20: return "强势多头"
        elif price > ema50: return "回调多头"
        else: return "潜在转空"
    elif ema20 < ema50 * 0.999:
        if price < ema20: return "强势空头"
        elif price < ema50: return "反弹空头"
        else: return "潜在转多"
    return "震荡"


def _get_signal(adx: float, trend: str) -> str:
    if adx <= 25:
        return "观望"
    if trend in ("强势多头", "强势空头"):
        return "强烈信号"
    elif trend in ("回调多头", "反弹空头"):
        return "谨慎信号"
    return "观望"


def _get_rsi_status(rsi: float, adx: float, trend: str) -> Tuple[str, int, int]:
    is_uptrend = trend in ("强势多头", "回调多头")
    is_downtrend = trend in ("强势空头", "反弹空头")
    if adx > 25:
        if is_uptrend:
            overbought, oversold = RSI_THRESHOLDS["uptrend_strong"]
        elif is_downtrend:
            overbought, oversold = RSI_THRESHOLDS["downtrend_strong"]
        else:
            overbought, oversold = RSI_THRESHOLDS["default"]
    else:
        overbought, oversold = RSI_THRESHOLDS["default"]

    if rsi >= overbought: status = "超买"
    elif rsi <= oversold: status = "超卖"
    else: status = "中性"
    return status, overbought, oversold


def _get_dynamic_rsi(adx: float, last_row: pd.Series) -> Tuple[int, float]:
    if adx > 30: period = 21
    elif adx < 20: period = 7
    else: period = 14
    rsi_key = f'RSI_{period}'
    rsi = float(last_row[rsi_key]) if rsi_key in last_row else 50
    return period, rsi


def _get_weekly_status(price: float, df_weekly: pd.DataFrame) -> dict:
    if df_weekly is None or df_weekly.empty:
        return {}
    last_w = df_weekly.iloc[-1]
    w_macd = float(last_w['MACD_W'])
    w_signal = float(last_w['MACD_Signal_W'])
    w_ma5 = float(last_w['MA5_W'])

    if w_macd > w_signal:
        macd_status = "周线牛市" if w_macd > 0 else "周线反弹"
    else:
        macd_status = "周线回调" if w_macd > 0 else "周线熊市"

    return {
        "weeklyMA5": w_ma5,
        "weeklyMacdStatus": macd_status,
        "weeklyPriceVsMA5": "线上" if price > w_ma5 else "线下",
        "weeklyMacdHist": float(last_w['MACD_Hist_W']),
    }
