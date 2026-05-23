import logging
import os
import time
import threading
from collections import defaultdict, OrderedDict
from datetime import timezone
from typing import Optional, Dict, List
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

import pandas as pd

from analysis_constants import (
    DATA_DIR, CACHE_DURATION_SECONDS, ALLOW_STALE_SECONDS, REFRESH_MIN_INTERVAL_SECONDS,
)

logger = logging.getLogger(__name__)

symbol_locks = defaultdict(threading.Lock)
global_download_lock = threading.Lock()
# pandas_ta 调用 numba 时有并发冲突，需要全局锁
ta_calculation_lock = threading.Lock()

_MEMORY_CACHE_MAX = 200
_memory_cache: OrderedDict = OrderedDict()
_memory_cache_lock = threading.Lock()

_refresh_state_lock = threading.Lock()
_refresh_inflight_symbols = set()
_last_refresh_requested_at: Dict[str, float] = {}
_refresh_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="swr-refresh")


def get_symbol_lock(symbol: str) -> threading.Lock:
    return symbol_locks[symbol.upper()]


def _cache_put(symbol: str, entry: dict) -> None:
    with _memory_cache_lock:
        _memory_cache.pop(symbol, None)
        _memory_cache[symbol] = entry
        if len(_memory_cache) > _MEMORY_CACHE_MAX:
            _memory_cache.popitem(last=False)
    return symbol_locks[symbol.upper()]


def _normalize_symbols(symbols: List[str]) -> List[str]:
    return sorted({s.strip().upper() for s in symbols if isinstance(s, str) and s.strip()})


def _to_unix_timestamp(value) -> Optional[float]:
    if value is None:
        return None
    ts = pd.Timestamp(value)
    dt = ts.to_pydatetime()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.timestamp()


def _get_latest_data_timestamp(df: Optional[pd.DataFrame]) -> Optional[float]:
    if df is None or df.empty:
        return None
    return _to_unix_timestamp(df.index[-1])


def _max_timestamp(current: Optional[float], candidate: Optional[float]) -> Optional[float]:
    if candidate is None:
        return current
    if current is None:
        return candidate
    return max(current, candidate)


def _extract_ohlcv(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return None
    cols = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in df.columns]
    return df[cols].copy() if cols else None


def _drop_incomplete_ohlcv_rows(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return df
    clean_df = df.copy()
    required = [c for c in ("Open", "High", "Low", "Close") if c in clean_df.columns]
    if required:
        clean_df = clean_df.dropna(subset=required)
    return clean_df


def _market_data_changed(previous_df: Optional[pd.DataFrame], candidate_df: Optional[pd.DataFrame]) -> bool:
    prev = _extract_ohlcv(previous_df)
    nxt = _extract_ohlcv(candidate_df)
    if prev is None:
        return nxt is not None and not nxt.empty
    if nxt is None:
        return False
    return not prev.equals(nxt)


def _pick_refreshable_symbols(symbols: List[str], min_interval_seconds: int) -> List[str]:
    now = time.time()
    refreshable = []
    with _refresh_state_lock:
        for symbol in symbols:
            if symbol in _refresh_inflight_symbols:
                continue
            if now - _last_refresh_requested_at.get(symbol, 0) < min_interval_seconds:
                continue
            _last_refresh_requested_at[symbol] = now
            _refresh_inflight_symbols.add(symbol)
            refreshable.append(symbol)
    return refreshable


def _release_refresh_symbols(symbols: List[str]) -> None:
    with _refresh_state_lock:
        for symbol in symbols:
            _refresh_inflight_symbols.discard(symbol)


def _refresh_worker(symbols: List[str], reason: str) -> None:
    try:
        from analysis import batch_fetch_and_update
        logger.info(f"==> [异步刷新] 开始 {len(symbols)} 只, reason={reason}")
        batch_fetch_and_update(symbols)
        logger.info(f"==> [异步刷新] 完成 {len(symbols)} 只, reason={reason}")
    except Exception as e:
        logger.error(f"==> [异步刷新] 失败 reason={reason}: {e}")
    finally:
        _release_refresh_symbols(symbols)


def refresh_symbols_async(
    symbols: List[str],
    reason: str = "api",
    min_interval_seconds: int = REFRESH_MIN_INTERVAL_SECONDS,
) -> bool:
    normalized = _normalize_symbols(symbols)
    if not normalized:
        return False
    refreshable = _pick_refreshable_symbols(normalized, min_interval_seconds)
    if not refreshable:
        return False
    _refresh_executor.submit(_refresh_worker, refreshable, reason)
    return True


def refresh_symbols_sync_with_timeout(
    symbols: List[str],
    timeout_seconds: float = 5.0,
    reason: str = "cold_start",
    min_interval_seconds: int = REFRESH_MIN_INTERVAL_SECONDS,
) -> bool:
    normalized = _normalize_symbols(symbols)
    if not normalized:
        return False
    refreshable = _pick_refreshable_symbols(normalized, min_interval_seconds)
    if not refreshable:
        return False
    future = _refresh_executor.submit(_refresh_worker, refreshable, reason)
    try:
        future.result(timeout=timeout_seconds)
        return True
    except FutureTimeoutError:
        logger.warning(f"==> [冷启动刷新] 超时 {timeout_seconds:.1f}s, 继续后台: {refreshable}")
        return False
    except Exception as e:
        logger.error(f"==> [冷启动刷新] 失败: {e}")
        return False


def get_cached_batch_summaries(symbols: List[str]) -> dict:
    normalized = _normalize_symbols(symbols)
    now_ts = time.time()

    results: Dict[str, dict] = {}
    fresh_symbols: List[str] = []
    stale_symbols: List[str] = []
    very_stale_symbols: List[str] = []
    missing_symbols: List[str] = []
    latest_mtime: Optional[float] = None
    latest_data_ts: Optional[float] = None

    mem_hits = []
    disk_needed = []

    for symbol in normalized:
        with _memory_cache_lock:
            entry = _memory_cache.get(symbol)
        if entry:
            summary = entry.get("summary")
            timestamp = entry.get("timestamp")
            data_timestamp = entry.get("data_timestamp") or _get_latest_data_timestamp(entry.get("df"))
            if summary and timestamp is not None:
                mem_hits.append((symbol, summary, float(timestamp), data_timestamp))
                continue
        disk_needed.append(symbol)

    def _load_from_disk(symbol):
        file_path = os.path.join(DATA_DIR, f"{symbol}.parquet")
        weekly_file_path = os.path.join(DATA_DIR, f"{symbol}_weekly.parquet")
        from analysis_data import _load_local_data
        df_local, _ = _load_local_data(file_path, symbol)
        if df_local is None or df_local.empty:
            return symbol, None
        if "EMA20" not in df_local.columns or "EMA5" not in df_local.columns:
            return symbol, None
        df_weekly, _ = _load_local_data(weekly_file_path, symbol)
        if df_weekly is None or df_weekly.empty or "MACD_W" not in df_weekly.columns:
            return symbol, None
        from analysis import analyze_stock_summary
        summary = analyze_stock_summary(symbol, df_local, df_weekly)
        if not summary:
            return symbol, None
        file_mod_time = os.path.getmtime(file_path) if os.path.exists(file_path) else now_ts
        data_timestamp = _get_latest_data_timestamp(df_local)
        _cache_put(symbol, {
            "df": df_local, "df_weekly": df_weekly, "summary": summary,
            "timestamp": float(file_mod_time), "data_timestamp": data_timestamp,
        })
        return symbol, (summary, float(file_mod_time), data_timestamp)

    with ThreadPoolExecutor(max_workers=min(8, len(disk_needed) or 1)) as ex:
        disk_results = list(ex.map(_load_from_disk, disk_needed))

    def _classify(symbol, timestamp, data_timestamp):
        nonlocal latest_mtime, latest_data_ts
        latest_mtime = _max_timestamp(latest_mtime, timestamp)
        latest_data_ts = _max_timestamp(latest_data_ts, data_timestamp)
        age = now_ts - timestamp
        if age < CACHE_DURATION_SECONDS:
            fresh_symbols.append(symbol)
        else:
            stale_symbols.append(symbol)
            if age > ALLOW_STALE_SECONDS:
                very_stale_symbols.append(symbol)

    for symbol, summary, timestamp, data_timestamp in mem_hits:
        results[symbol] = summary
        _classify(symbol, timestamp, data_timestamp)

    for symbol, payload in disk_results:
        if payload is None:
            missing_symbols.append(symbol)
        else:
            summary, file_mod_time, data_timestamp = payload
            results[symbol] = summary
            _classify(symbol, file_mod_time, data_timestamp)

    return {
        "results": results,
        "fresh_symbols": fresh_symbols,
        "stale_symbols": stale_symbols,
        "very_stale_symbols": very_stale_symbols,
        "missing_symbols": missing_symbols,
        "latest_mtime": latest_mtime,
        "latest_data_ts": latest_data_ts,
    }
