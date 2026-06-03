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
import requests
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


def _normalize_downloaded_ohlcv_columns(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if df is None or df.empty or not isinstance(df.columns, pd.MultiIndex):
        return df

    normalized_symbol = symbol.upper()
    for level in range(df.columns.nlevels):
        level_values = list(df.columns.get_level_values(level))
        upper_values = [str(value).upper() for value in level_values]
        if normalized_symbol in upper_values:
            raw_symbol = level_values[upper_values.index(normalized_symbol)]
            df = df.xs(raw_symbol, axis=1, level=level)
            break

    if isinstance(df.columns, pd.MultiIndex):
        ohlcv_columns = {"Open", "High", "Low", "Close", "Volume", "Adj Close"}
        for level in range(df.columns.nlevels):
            level_values = set(df.columns.get_level_values(level))
            if level_values & ohlcv_columns:
                df = df.copy()
                df.columns = df.columns.get_level_values(level)
                break

    return df


def _is_a_share_symbol(symbol: str) -> bool:
    normalized = symbol.upper()
    return (
        (normalized.endswith(".SS") or normalized.endswith(".SZ"))
        and normalized.split(".", 1)[0].isdigit()
        and len(normalized.split(".", 1)[0]) == 6
    )


def _eastmoney_secid(symbol: str) -> Optional[str]:
    normalized = symbol.upper()
    code = normalized.split(".", 1)[0]
    if normalized.endswith(".SS"):
        return f"1.{code}"
    if normalized.endswith(".SZ"):
        return f"0.{code}"
    return None


def _has_business_day_gap(df: Optional[pd.DataFrame]) -> bool:
    if df is None or df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return False
    dates = pd.DatetimeIndex(df.index).tz_localize(None).normalize().unique().sort_values()
    if len(dates) < 2:
        return False
    expected_dates = pd.bdate_range(dates[0], dates[-1])
    return bool(expected_dates.difference(dates).size)


def _first_missing_business_date(df: Optional[pd.DataFrame]) -> Optional[pd.Timestamp]:
    if df is None or df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return None
    dates = pd.DatetimeIndex(df.index).tz_localize(None).normalize().unique().sort_values()
    if len(dates) < 2:
        return None
    expected_dates = pd.bdate_range(dates[0], dates[-1])
    missing_dates = expected_dates.difference(dates)
    if missing_dates.empty:
        return None
    return missing_dates[0]


def _latest_expected_business_date(start: datetime, end: datetime) -> Optional[pd.Timestamp]:
    expected_end = pd.Timestamp(end).normalize() - pd.Timedelta(days=1)
    expected_start = pd.Timestamp(start).normalize()
    expected_dates = pd.bdate_range(expected_start, expected_end)
    if expected_dates.empty:
        return None
    return expected_dates[-1]


def _fetch_eastmoney_daily(symbol: str, start: datetime, end: datetime) -> Optional[pd.DataFrame]:
    secid = _eastmoney_secid(symbol)
    if not secid:
        return None

    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "1",
        "beg": pd.Timestamp(start).strftime("%Y%m%d"),
        "end": pd.Timestamp(end).strftime("%Y%m%d"),
    }
    payload = None
    errors = []
    for trust_env in (False, True):
        with requests.Session() as session:
            session.trust_env = trust_env
            try:
                response = session.get("https://push2his.eastmoney.com/api/qt/stock/kline/get", params=params, timeout=8)
                response.raise_for_status()
                payload = response.json()
                break
            except Exception as exc:
                errors.append(exc)
    if payload is None:
        logger.warning(f"Eastmoney 日线兜底下载失败 {symbol}: {errors[-1] if errors else 'unknown error'}")
        return None

    rows = (payload.get("data") or {}).get("klines") or []
    records = []
    for raw_row in rows:
        parts = str(raw_row).split(",")
        if len(parts) < 6:
            continue
        try:
            volume_lots = float(parts[5])
            records.append({
                "Date": pd.to_datetime(parts[0]),
                "Open": float(parts[1]),
                "Close": float(parts[2]),
                "High": float(parts[3]),
                "Low": float(parts[4]),
                "Volume": volume_lots * 100,
            })
        except (TypeError, ValueError):
            continue

    if not records:
        return None

    df = pd.DataFrame.from_records(records).set_index("Date").sort_index()
    return _drop_incomplete_ohlcv_rows(df)


def _patch_a_share_daily_gaps(symbol: str, df: Optional[pd.DataFrame], start: datetime, end: datetime) -> Optional[pd.DataFrame]:
    if not _is_a_share_symbol(symbol):
        return df

    latest_expected_date = _latest_expected_business_date(start, end)
    if df is not None and not df.empty:
        latest_df_date = pd.DatetimeIndex(df.index).tz_localize(None).normalize().max()
        has_latest_expected = latest_expected_date is None or latest_df_date >= latest_expected_date
    else:
        has_latest_expected = False

    if df is not None and not df.empty and not _has_business_day_gap(df) and has_latest_expected:
        return df

    fallback_df = _fetch_eastmoney_daily(symbol, start, end)
    if fallback_df is None or fallback_df.empty:
        return df
    if df is None or df.empty:
        return fallback_df

    existing_dates = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
    fallback_dates = pd.DatetimeIndex(fallback_df.index).tz_localize(None).normalize()
    missing_rows = fallback_df[~fallback_dates.isin(existing_dates)]
    if missing_rows.empty:
        return df

    patched = pd.concat([df, missing_rows]).sort_index()
    logger.info(f"Eastmoney 日线兜底补齐 {symbol}: {len(missing_rows)} 根")
    return patched


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
    for sym, df_local, last_update in symbols_to_fetch:
        if df_local is None or last_update is None:
            has_new_symbol = True
            break
        effective_update = last_update
        if _is_a_share_symbol(sym):
            first_gap = _first_missing_business_date(df_local)
            if first_gap is not None:
                effective_update = min(pd.Timestamp(last_update), first_gap).to_pydatetime()
        if earliest_update is None or effective_update < earliest_update:
            earliest_update = effective_update

    fetch_start = (now - timedelta(days=DATA_RETENTION_DAYS)) if (has_new_symbol or earliest_update is None) else earliest_update

    downloaded_data: Dict[str, pd.DataFrame] = {}
    with global_download_lock:
        try:
            start_time = time.time()
            logger.info(f"开始下载 {len(fetch_symbols)} 只股票: {fetch_symbols}")
            fetch_end = now + timedelta(days=1)
            raw = yf.download(fetch_symbols, start=fetch_start, end=fetch_end, interval="1d", group_by="ticker", threads=True)
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
            new_df = _normalize_downloaded_ohlcv_columns(new_df, symbol)
            base_ohlcv = _extract_ohlcv(df_local)
            merged_df = _merge_and_clean_data(base_ohlcv, new_df, now)
            merged_df = _patch_a_share_daily_gaps(symbol, merged_df, fetch_start, fetch_end)
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
