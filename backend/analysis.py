"""
股票技术分析模块（门面）

子模块：
  analysis_constants  — 配置常量
  analysis_cache      — 线程锁、内存缓存、异步刷新
  analysis_data       — 数据获取、指标计算
  analysis_strategy   — 共振策略信号
  analysis_candles    — K线构建
"""

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional, Dict
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import yfinance as yf

# re-exports — 保持所有现有 import 不变
from analysis_constants import (  # noqa: F401
    DATA_DIR, CACHE_DURATION_SECONDS, ALLOW_STALE_SECONDS, DATA_RETENTION_DAYS,
    REFRESH_MIN_INTERVAL_SECONDS, EMA_LONG_PERIOD,
    EMA_FAST_5, EMA_FAST_10, EMA_SHORT_PERIOD, EMA_LONG_PERIOD,
    CHART_DAYS, MINI_CHART_DAYS,
)
from analysis_cache import (  # noqa: F401
    get_symbol_lock, global_download_lock, ta_calculation_lock,
    symbol_locks, _memory_cache, _memory_cache_lock, _cache_put,
    _normalize_symbols, _extract_ohlcv, _drop_incomplete_ohlcv_rows,
    _market_data_changed, _get_latest_data_timestamp,
    get_cached_batch_summaries, refresh_symbols_async, refresh_symbols_sync_with_timeout,
)
from analysis_data import (  # noqa: F401
    _load_local_data, _fetch_new_data, _merge_and_clean_data,
    _calculate_daily_indicators, _calculate_weekly_indicators, fetch_stock_data,
)
from analysis_strategy import (  # noqa: F401
    _evaluate_resonance_strategy, _evaluate_resonance_strategy_v2,
    _evaluate_resonance_exit_no_position,
    _analyze_trend, _get_signal, _get_rsi_status, _get_dynamic_rsi, _get_weekly_status,
    _finite_float, _make_json_safe,
)
from analysis_candles import (  # noqa: F401
    _build_candles, _build_mini_candles,
    _sanitize_candle_df, _ensure_time_ascending, _to_json_safe_records,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ============================================
# 主分析函数
# ============================================

def _build_summary_dict(symbol: str, df: pd.DataFrame, df_weekly: pd.DataFrame) -> Optional[dict]:
    df = _drop_incomplete_ohlcv_rows(df)
    if df is None or len(df) < EMA_LONG_PERIOD:
        return None

    last_row = df.iloc[-1]
    price = float(last_row['Close'])
    ema20 = float(last_row['EMA20'])
    ema50 = float(last_row['EMA50'])
    adx = float(last_row['ADX']) if 'ADX' in last_row else 0

    rsi_period, rsi = _get_dynamic_rsi(adx, last_row)
    trend = _analyze_trend(price, ema20, ema50)
    signal = _get_signal(adx, trend)
    rsi_status, rsi_overbought, rsi_oversold = _get_rsi_status(rsi, adx, trend)

    prev_close = float(df.iloc[-2]['Close'])
    change_percent = ((price - prev_close) / prev_close) * 100

    weekly_status = _get_weekly_status(price, df_weekly)
    resonance = _evaluate_resonance_strategy(df, df_weekly)
    resonance_v2 = _evaluate_resonance_strategy_v2(df, df_weekly)
    resonance_exit = _evaluate_resonance_exit_no_position(df, df_weekly)

    return _make_json_safe({
        "symbol": symbol, "name": symbol,
        "price": price, "changePercent": change_percent,
        "ema20": ema20, "ema50": ema50, "adx": adx,
        "rsi": rsi, "rsiPeriod": rsi_period, "rsiStatus": rsi_status,
        "rsiOverbought": rsi_overbought, "rsiOversold": rsi_oversold,
        "trend": trend, "signal": signal,
        "resonanceInPool": resonance["inPool"],
        "resonanceBuySignal": resonance["buySignal"],
        "resonancePoolReason": resonance["poolReason"],
        "resonanceBuyReason": resonance["buyReason"],
        "resonanceStrategyVersion": resonance_v2["strategyVersion"],
        "resonancePoolType": resonance_v2["poolType"],
        "resonanceEntryScore": resonance_v2["entryScore"],
        "resonanceRiskScore": resonance_v2["riskScore"],
        "resonanceRiskLevel": resonance_v2["riskLevel"],
        "resonanceEntryPrice": resonance_v2["entryPrice"],
        "resonanceStopPrice": resonance_v2["stopPrice"],
        "resonanceRiskPercent": resonance_v2["riskPercent"],
        "resonanceTargetPrice": resonance_v2["targetPrice"],
        "resonanceRewardRiskRatio": resonance_v2["rewardRiskRatio"],
        "resonanceExitSignal": resonance_exit["exitSignal"],
        "resonanceExitLevel": resonance_exit["exitLevel"],
        "resonanceExitReason": resonance_exit["exitReason"],
        "_rsi_period": rsi_period,
        **weekly_status,
    })


def analyze_stock(symbol: str) -> Optional[dict]:
    data = fetch_stock_data(symbol)
    if data is None:
        return None

    df, df_weekly = data
    result = _build_summary_dict(symbol, df, df_weekly)
    if result is None:
        return None

    rsi_period = result.pop("_rsi_period", 14)
    result["candles"] = _build_candles(df, rsi_period)
    result["weekly_candles"] = _build_candles(df_weekly, rsi_period=14)
    return result


# ============================================
# 批量获取与摘要分析
# ============================================

def batch_fetch_and_update(symbols: list) -> dict:
    symbols = [s.upper() for s in symbols]
    now = datetime.now()
    results = {}
    symbols_to_fetch = []

    process_start_wall = time.time()
    count_mem_hit = count_disk_hit = count_to_fetch = 0

    def process_symbol_initial(symbol):
        with _memory_cache_lock:
            if symbol in _memory_cache:
                entry = _memory_cache[symbol]
                elapsed = time.time() - entry["timestamp"]
                if elapsed < CACHE_DURATION_SECONDS:
                    return symbol, (entry["df"], entry["df_weekly"], entry.get("summary")), 0, True, "mem_hit"
                if elapsed < ALLOW_STALE_SECONDS:
                    return symbol, (entry["df"], entry["df_weekly"], entry.get("summary")), 0, False, "mem_stale"

        t0 = time.time()
        file_path = os.path.join(DATA_DIR, f"{symbol}.parquet")
        weekly_file_path = os.path.join(DATA_DIR, f"{symbol}_weekly.parquet")
        df_local, last_update = _load_local_data(file_path, symbol)
        load_time = time.time() - t0

        if df_local is not None and last_update is not None and os.path.exists(file_path):
            file_mod_time = os.path.getmtime(file_path)
            elapsed = time.time() - file_mod_time
            is_fresh = elapsed < CACHE_DURATION_SECONDS
            is_stale_but_usable = elapsed < ALLOW_STALE_SECONDS
            has_indicators = 'EMA20' in df_local.columns and 'EMA5' in df_local.columns

            if has_indicators:
                df_weekly, _ = _load_local_data(weekly_file_path, symbol)
                if df_weekly is not None and 'MACD_W' in df_weekly.columns:
                    summary = analyze_stock_summary(symbol, df_local, df_weekly)
                    _cache_put(symbol, {
                        "df": df_local, "df_weekly": df_weekly, "summary": summary,
                        "timestamp": file_mod_time,
                        "data_timestamp": _get_latest_data_timestamp(df_local),
                    })
                    res_data = (df_local, df_weekly, summary)
                    if is_fresh:
                        return symbol, res_data, load_time, True, "disk_hit"
                    if is_stale_but_usable:
                        return symbol, res_data, load_time, False, "disk_stale"

        return symbol, None, load_time, False, "miss"

    with ThreadPoolExecutor(max_workers=10) as executor:
        for sym, res, lt, is_fresh, hit_type in executor.map(process_symbol_initial, symbols):
            if res:
                results[sym] = res
                if "mem" in hit_type: count_mem_hit += 1
                else: count_disk_hit += 1
            if not is_fresh:
                df_l, last_u = (res[0], res[0].index[-1]) if res else (None, None)
                symbols_to_fetch.append((sym, df_l, last_u))
                count_to_fetch += 1

    wall_time = time.time() - process_start_wall
    logger.info(f"==> [二级缓存] 内存命中: {count_mem_hit}, 硬盘命中: {count_disk_hit}, 需要更新: {count_to_fetch}, 耗时: {wall_time:.4f}s")

    if not symbols_to_fetch:
        return results

    fetch_symbols = [s for s, _, _ in symbols_to_fetch]
    earliest_update = None
    has_new_symbol = False
    for _, df_local, last_update in symbols_to_fetch:
        if df_local is None or last_update is None:
            has_new_symbol = True
            break
        if earliest_update is None or last_update < earliest_update:
            earliest_update = last_update

    fetch_start = (now - timedelta(days=DATA_RETENTION_DAYS)) if (has_new_symbol or earliest_update is None) else earliest_update

    downloaded_data: Dict[str, pd.DataFrame] = {}
    with global_download_lock:
        try:
            start_time = time.time()
            logger.info(f"开始下载 {len(fetch_symbols)} 只股票: {fetch_symbols}")
            raw = yf.download(fetch_symbols, start=fetch_start, end=now, interval="1d", group_by="ticker", threads=True)
            logger.info(f"下载完成，耗时: {time.time() - start_time:.2f}s")
            if raw is not None and not raw.empty:
                if len(fetch_symbols) == 1:
                    downloaded_data[fetch_symbols[0]] = raw
                else:
                    for sym in fetch_symbols:
                        try:
                            sym_df = raw[sym].dropna(how='all')
                            if not sym_df.empty:
                                downloaded_data[sym] = sym_df
                        except Exception:
                            pass
        except Exception as e:
            logger.error(f"批量下载失败: {e}")

    def process_new_symbol(item):
        symbol, df_local, _ = item
        file_path = os.path.join(DATA_DIR, f"{symbol}.parquet")
        weekly_file_path = os.path.join(DATA_DIR, f"{symbol}_weekly.parquet")
        merged_df = df_local
        market_data_changed = df_local is None or df_local.empty

        with _memory_cache_lock:
            cached_entry = _memory_cache.get(symbol)

        if symbol in downloaded_data:
            new_df = downloaded_data[symbol]
            if hasattr(new_df.index, 'tz') and new_df.index.tz is not None:
                new_df.index = new_df.index.tz_localize(None)
            if isinstance(new_df.columns, pd.MultiIndex):
                new_df.columns = new_df.columns.get_level_values(0)
            base_ohlcv = _extract_ohlcv(df_local)
            merged_df = _merge_and_clean_data(base_ohlcv, new_df, now)
            market_data_changed = _market_data_changed(df_local, merged_df)

        if (
            not market_data_changed and cached_entry
            and cached_entry.get("df") is not None
            and cached_entry.get("df_weekly") is not None
            and cached_entry.get("summary") is not None
        ):
            return symbol, (cached_entry["df"], cached_entry["df_weekly"], cached_entry["summary"])

        if merged_df is None or merged_df.empty:
            return None

        df = _calculate_daily_indicators(merged_df)
        with get_symbol_lock(symbol):
            df.to_parquet(file_path)

        df_weekly = _calculate_weekly_indicators(df)
        df_weekly.to_parquet(weekly_file_path)

        summary = analyze_stock_summary(symbol, df, df_weekly)
        _cache_put(symbol, {
            "df": df, "df_weekly": df_weekly, "summary": summary,
            "timestamp": time.time(),
            "data_timestamp": _get_latest_data_timestamp(df),
        })
        return symbol, (df, df_weekly, summary)

    process_start = time.time()
    with ThreadPoolExecutor(max_workers=5) as executor:
        for tr in executor.map(process_new_symbol, symbols_to_fetch):
            if tr:
                sym, res = tr
                results[sym] = res
    logger.info(f"==> [全量更新] 完成 {len(symbols_to_fetch)} 只: {time.time() - process_start:.4f}s")

    return results


def analyze_stock_summary(symbol: str, df: pd.DataFrame, df_weekly: pd.DataFrame) -> Optional[dict]:
    result = _build_summary_dict(symbol, df, df_weekly)
    if result is None:
        return None
    result.pop("_rsi_period", None)
    result["candles"] = []
    result["weekly_candles"] = []
    return result
