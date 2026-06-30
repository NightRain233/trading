import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import numpy as np
import pandas as pd
import pandas_ta as ta
import requests
import yfinance as yf

from analysis_constants import (
    DATA_DIR, DATA_RETENTION_DAYS, CACHE_DURATION_SECONDS,
    TICKFLOW_FETCH_ENABLED, TICKFLOW_BASE_URL, TICKFLOW_API_KEY,
    TICKFLOW_MIN_INTERVAL_SECONDS, TICKFLOW_CIRCUIT_COOLDOWN_SECONDS,
    TICKFLOW_INCREMENTAL_OVERLAP_DAYS,
    YAHOO_FETCH_ENABLED, YAHOO_MIN_INTERVAL_SECONDS,
    YAHOO_CIRCUIT_COOLDOWN_SECONDS,
    EMA_FAST_5, EMA_FAST_10, EMA_SHORT_PERIOD, EMA_LONG_PERIOD,
    ADX_PERIOD, RSI_PERIODS, MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    BOLL_PERIOD, BOLL_STD, KDJ_PERIOD, KDJ_SIGNAL_K, KDJ_SIGNAL_D, ATR_PERIOD,
    ST_LENGTH, ST_MULTIPLIER,
)
from analysis_cache import (
    get_symbol_lock, global_download_lock, ta_calculation_lock,
    _drop_incomplete_ohlcv_rows,
)
from data_source_guard import (
    MarketDataUnavailableError,
    ProviderBlockingError,
    ProviderConfig,
    ProviderError,
    ProviderGuard,
)

logger = logging.getLogger(__name__)

A_SHARE_DATA_SOURCE_VERSION = "tickflow-forward-additive-v1"
TICKFLOW_OVERLAP_ATOL = 5e-4
PRICE_JUMP_THRESHOLD = 0.40
PROVIDER_STATE_DIR = os.path.join(DATA_DIR, ".provider-state")

tickflow_guard = ProviderGuard(
    "tickflow",
    ProviderConfig(
        enabled=TICKFLOW_FETCH_ENABLED,
        min_interval_seconds=TICKFLOW_MIN_INTERVAL_SECONDS,
        duplicate_window_seconds=5 * 60,
        max_retries=1,
        backoff_seconds=1.0,
        failure_threshold=3,
        circuit_cooldown_seconds=TICKFLOW_CIRCUIT_COOLDOWN_SECONDS,
    ),
    state_dir=PROVIDER_STATE_DIR,
)
yahoo_guard = ProviderGuard(
    "yahoo",
    ProviderConfig(
        enabled=YAHOO_FETCH_ENABLED,
        min_interval_seconds=YAHOO_MIN_INTERVAL_SECONDS,
        duplicate_window_seconds=5 * 60,
        max_retries=1,
        backoff_seconds=1.0,
        failure_threshold=3,
        circuit_cooldown_seconds=YAHOO_CIRCUIT_COOLDOWN_SECONDS,
    ),
    state_dir=PROVIDER_STATE_DIR,
)


def get_data_source_status() -> dict:
    return {
        "tickflow": tickflow_guard.status(),
        "yahoo": yahoo_guard.status(),
    }


def _find_col(columns, prefix: str, exclude_prefixes=()) -> str | None:
    for c in columns:
        if c.startswith(prefix) and not any(c.startswith(e) for e in exclude_prefixes):
            return c
    return None


def _is_a_share_symbol(symbol: str) -> bool:
    normalized = symbol.upper()
    code = normalized.split(".", 1)[0]
    return (
        normalized.endswith((".SS", ".SZ"))
        and code.isdigit()
        and len(code) == 6
    )


def _tickflow_symbol(symbol: str) -> Optional[str]:
    normalized = symbol.upper()
    if normalized.endswith(".SS"):
        return f"{normalized[:-3]}.SH"
    if normalized.endswith(".SZ"):
        return normalized
    return None


def _to_tickflow_ms(value: datetime) -> int:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("Asia/Shanghai")
    else:
        timestamp = timestamp.tz_convert("Asia/Shanghai")
    return int(timestamp.timestamp() * 1000)


def _tickflow_timestamp(value: int) -> pd.Timestamp:
    return (
        pd.to_datetime(value, unit="ms", utc=True)
        .tz_convert("Asia/Shanghai")
        .tz_localize(None)
        .normalize()
    )


def _parse_tickflow_payload(payload: dict) -> pd.DataFrame:
    data = payload.get("data") or {}
    required = ("timestamp", "open", "high", "low", "close", "volume")
    lengths = {len(data.get(name) or []) for name in required}
    if lengths == {0}:
        return pd.DataFrame(
            columns=["Open", "High", "Low", "Close", "Volume"],
            index=pd.DatetimeIndex([], name="Date"),
        )
    if len(lengths) != 1 or 0 in lengths:
        raise ValueError(
            "TickFlow payload columns have inconsistent lengths"
        )

    frame = pd.DataFrame(
        {
            "Date": [
                _tickflow_timestamp(value)
                for value in data["timestamp"]
            ],
            "Open": data["open"],
            "High": data["high"],
            "Low": data["low"],
            "Close": data["close"],
            "Volume": np.asarray(data["volume"], dtype=float) * 100,
        }
    )
    normalized = frame.set_index("Date").sort_index()
    return _drop_incomplete_ohlcv_rows(normalized)


def _request_tickflow_payload(
    path: str,
    params: dict,
    *,
    request_key: str,
) -> dict:
    headers = (
        {"x-api-key": TICKFLOW_API_KEY}
        if TICKFLOW_API_KEY
        else {}
    )

    def request() -> dict:
        with requests.Session() as session:
            try:
                response = session.get(
                    f"{TICKFLOW_BASE_URL}{path}",
                    params=params,
                    headers=headers,
                    timeout=8,
                )
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                status_code = getattr(
                    getattr(exc, "response", None),
                    "status_code",
                    None,
                )
                if status_code in {403, 429}:
                    raise ProviderBlockingError(
                        str(exc),
                        provider="tickflow",
                        key=request_key,
                        category=f"http_{status_code}",
                    ) from exc
                raise

    return tickflow_guard.call(request_key, request)


def _fetch_tickflow_daily(
    symbol: str,
    start: datetime,
    end: datetime,
    *,
    request_key: Optional[str] = None,
) -> Optional[pd.DataFrame]:
    provider_symbol = _tickflow_symbol(symbol)
    if provider_symbol is None:
        return None

    params = {
        "symbol": provider_symbol,
        "period": "1d",
        "adjust": "forward_additive",
        "start_time": _to_tickflow_ms(start),
        "end_time": _to_tickflow_ms(end),
    }
    payload = _request_tickflow_payload(
        "/v1/klines",
        params,
        request_key=request_key or symbol.upper(),
    )
    return _parse_tickflow_payload(payload)


def _fetch_tickflow_daily_batch(
    symbols: list[str],
    start: datetime,
    end: datetime,
    *,
    request_key: Optional[str] = None,
) -> dict[str, pd.DataFrame]:
    provider_to_internal = {
        provider_symbol: symbol.upper()
        for symbol in symbols
        if (provider_symbol := _tickflow_symbol(symbol)) is not None
    }
    if not provider_to_internal:
        return {}

    provider_symbols = sorted(provider_to_internal)
    params = {
        "symbols": ",".join(provider_symbols),
        "period": "1d",
        "adjust": "forward_additive",
        "start_time": _to_tickflow_ms(start),
        "end_time": _to_tickflow_ms(end),
    }
    key = request_key or (
        f"batch:{','.join(provider_symbols)}:"
        f"{params['start_time']}:{params['end_time']}"
    )
    payload = _request_tickflow_payload(
        "/v1/klines/batch",
        params,
        request_key=key,
    )

    response_data = payload.get("data") or {}
    result: dict[str, pd.DataFrame] = {}
    for provider_symbol, internal_symbol in provider_to_internal.items():
        symbol_payload = response_data.get(provider_symbol)
        if not isinstance(symbol_payload, dict):
            continue
        result[internal_symbol] = _parse_tickflow_payload(
            {"data": symbol_payload}
        )
    return result


def _has_valid_price_history(
    df: Optional[pd.DataFrame],
    symbol: str,
) -> bool:
    if df is None or df.empty:
        logger.warning(f"{symbol}: 行情为空，拒绝写入缓存")
        return False

    required = ["Open", "High", "Low", "Close", "Volume"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        logger.warning(f"{symbol}: 行情缺少字段 {missing}，拒绝写入缓存")
        return False

    prices = df[["Open", "High", "Low", "Close"]]
    if prices.isna().any().any() or (prices <= 0).any().any():
        logger.warning(f"{symbol}: 行情包含空值或非正价格，拒绝写入缓存")
        return False

    invalid_ohlc = (
        (df["High"] < df[["Open", "Close", "Low"]].max(axis=1))
        | (df["Low"] > df[["Open", "Close", "High"]].min(axis=1))
    )
    if invalid_ohlc.any():
        logger.warning(f"{symbol}: OHLC 关系异常，拒绝写入缓存")
        return False

    ordered_close = df.sort_index()["Close"]
    jumps = ordered_close.pct_change().abs()
    suspicious = jumps[jumps > PRICE_JUMP_THRESHOLD]
    if not suspicious.empty:
        details = ", ".join(
            f"{pd.Timestamp(index).date()}={value * 100:.1f}%"
            for index, value in suspicious.items()
        )
        logger.warning(f"{symbol}: 检测到异常价格跳变 {details}，拒绝写入缓存")
        return False
    return True


def _source_metadata_path(file_path: str) -> str:
    return f"{file_path}.source.json"


def _read_data_source_metadata(file_path: str, symbol: str) -> dict:
    if not _is_a_share_symbol(symbol):
        return {}
    try:
        with open(_source_metadata_path(file_path), encoding="utf-8") as handle:
            metadata = json.load(handle)
        if not isinstance(metadata, dict):
            return {}
        if metadata.get("symbol") != symbol.upper():
            return {}
        return metadata
    except (OSError, TypeError, ValueError):
        return {}


def _has_current_data_source(file_path: str, symbol: str) -> bool:
    if not _is_a_share_symbol(symbol):
        return True
    metadata = _read_data_source_metadata(file_path, symbol)
    return metadata.get("sourceVersion") == A_SHARE_DATA_SOURCE_VERSION


def _normalize_metadata_timestamp(value: datetime | str | None) -> str:
    if value is None:
        timestamp = datetime.now(timezone.utc)
    else:
        timestamp = pd.Timestamp(value).to_pydatetime()
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        else:
            timestamp = timestamp.astimezone(timezone.utc)
    return timestamp.isoformat()


def _write_data_source_metadata(
    file_path: str,
    symbol: str,
    *,
    last_full_refresh_at: datetime | str | None = None,
    last_incremental_refresh_at: datetime | str | None = None,
    full_refresh_required: bool = False,
) -> None:
    if not _is_a_share_symbol(symbol):
        return
    payload = {
        "symbol": symbol.upper(),
        "sourceVersion": A_SHARE_DATA_SOURCE_VERSION,
        "fullRefreshRequired": full_refresh_required,
        "lastFullRefreshAt": _normalize_metadata_timestamp(
            last_full_refresh_at
        ),
        "lastIncrementalRefreshAt": _normalize_metadata_timestamp(
            last_incremental_refresh_at
        ),
    }
    _atomic_write_source_metadata(file_path, payload)


def _atomic_write_source_metadata(file_path: str, payload: dict) -> None:
    metadata_path = _source_metadata_path(file_path)
    temporary_path = f"{metadata_path}.tmp"
    with open(temporary_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
    os.replace(temporary_path, metadata_path)


def _mark_full_refresh_required(
    file_path: str,
    symbol: str,
    *,
    reason: str,
    detected_at: datetime,
) -> None:
    metadata = _read_data_source_metadata(file_path, symbol)
    metadata.update(
        {
            "symbol": symbol.upper(),
            "sourceVersion": A_SHARE_DATA_SOURCE_VERSION,
            "fullRefreshRequired": True,
            "fullRefreshReason": reason,
            "fullRefreshDetectedAt": _normalize_metadata_timestamp(
                detected_at
            ),
        }
    )
    _atomic_write_source_metadata(file_path, metadata)


def _invalidate_data_source_metadata(file_path: str) -> None:
    try:
        os.remove(_source_metadata_path(file_path))
    except FileNotFoundError:
        pass


def _a_share_needs_initial_full_refresh(
    file_path: str,
    symbol: str,
) -> bool:
    metadata = _read_data_source_metadata(file_path, symbol)
    return metadata.get("sourceVersion") != A_SHARE_DATA_SOURCE_VERSION


def _load_local_data(file_path: str, symbol: str) -> Tuple[Optional[pd.DataFrame], Optional[datetime]]:
    if not os.path.exists(file_path):
        return None, None
    try:
        df = pd.read_parquet(file_path)
        if df.empty:
            return None, None
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        df = _drop_incomplete_ohlcv_rows(df)
        if df is None or df.empty:
            return None, None
        df = df.sort_index()
        return df, df.index[-1]
    except Exception as e:
        logger.error(f"读取 {symbol} 的 Parquet 文件失败: {e}")
        return None, None


@dataclass(frozen=True)
class AShareRefreshResult:
    frame: pd.DataFrame
    full_refresh: bool
    last_full_refresh_at: str
    last_incremental_refresh_at: str


class AShareFullRefreshRequiredError(ProviderError):
    pass


def _extract_ohlcv_base(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return None
    required = ["Open", "High", "Low", "Close", "Volume"]
    if any(column not in df.columns for column in required):
        return None
    return df[required].copy()


def _has_adjustment_rebase(
    local: Optional[pd.DataFrame],
    downloaded: Optional[pd.DataFrame],
) -> bool:
    local_ohlcv = _extract_ohlcv_base(local)
    downloaded_ohlcv = _extract_ohlcv_base(downloaded)
    if local_ohlcv is None or downloaded_ohlcv is None:
        return False
    common = local_ohlcv.index.intersection(downloaded_ohlcv.index).sort_values()
    if len(common) <= 1:
        return False
    completed_common = common[:-1]
    columns = ["Open", "High", "Low", "Close"]
    left = local_ohlcv.loc[completed_common, columns].to_numpy(dtype=float)
    right = downloaded_ohlcv.loc[completed_common, columns].to_numpy(
        dtype=float
    )
    return not bool(
        np.isclose(
            left,
            right,
            rtol=1e-8,
            atol=TICKFLOW_OVERLAP_ATOL,
        ).all()
    )


def _build_a_share_refresh_result(
    symbol: str,
    *,
    downloaded: pd.DataFrame,
    df_local: Optional[pd.DataFrame],
    file_path: str,
    now: datetime,
    full_refresh: bool,
) -> Optional[AShareRefreshResult]:
    if not _has_valid_price_history(downloaded, symbol):
        return None

    metadata = _read_data_source_metadata(file_path, symbol)
    if not full_refresh and metadata.get("fullRefreshRequired") is True:
        raise AShareFullRefreshRequiredError(
            f"{symbol} requires a manual full TickFlow refresh",
            provider="tickflow",
            key=symbol,
            category="full_refresh_required",
        )

    refresh_timestamp = _normalize_metadata_timestamp(now)
    if full_refresh:
        return AShareRefreshResult(
            frame=downloaded,
            full_refresh=True,
            last_full_refresh_at=refresh_timestamp,
            last_incremental_refresh_at=refresh_timestamp,
        )

    if _has_adjustment_rebase(df_local, downloaded):
        _mark_full_refresh_required(
            file_path,
            symbol,
            reason="overlap_changed",
            detected_at=now,
        )
        raise AShareFullRefreshRequiredError(
            f"{symbol} TickFlow overlap changed; manual full refresh required",
            provider="tickflow",
            key=symbol,
            category="full_refresh_required",
        )

    merged = _merge_and_clean_data(
        _extract_ohlcv_base(df_local),
        downloaded,
        now,
    )
    if not _has_valid_price_history(merged, symbol):
        return None
    last_full_refresh_at = metadata.get("lastFullRefreshAt")
    if not last_full_refresh_at:
        return None
    return AShareRefreshResult(
        frame=merged,
        full_refresh=False,
        last_full_refresh_at=str(last_full_refresh_at),
        last_incremental_refresh_at=refresh_timestamp,
    )


def _fetch_a_share_refresh(
    symbol: str,
    df_local: Optional[pd.DataFrame],
    last_update: Optional[datetime],
    file_path: str,
    now: datetime,
) -> Optional[AShareRefreshResult]:
    fetch_end = now + timedelta(days=1)
    metadata = _read_data_source_metadata(file_path, symbol)
    if metadata.get("fullRefreshRequired") is True:
        raise AShareFullRefreshRequiredError(
            f"{symbol} requires a manual full TickFlow refresh",
            provider="tickflow",
            key=symbol,
            category="full_refresh_required",
        )

    needs_full = (
        df_local is None
        or last_update is None
        or _a_share_needs_initial_full_refresh(file_path, symbol)
    )

    if needs_full:
        fetch_start = now - timedelta(days=DATA_RETENTION_DAYS)
        full_df = _fetch_tickflow_daily(
            symbol,
            fetch_start,
            fetch_end,
            request_key=(
                f"{symbol}:full:{fetch_start:%Y%m%d}:{fetch_end:%Y%m%d}"
            ),
        )
        return _build_a_share_refresh_result(
            symbol,
            downloaded=full_df,
            df_local=df_local,
            file_path=file_path,
            now=now,
            full_refresh=True,
        )

    incremental_start = pd.Timestamp(last_update).to_pydatetime() - timedelta(
        days=TICKFLOW_INCREMENTAL_OVERLAP_DAYS
    )
    incremental_df = _fetch_tickflow_daily(
        symbol,
        incremental_start,
        fetch_end,
        request_key=(
            f"{symbol}:incremental:"
            f"{incremental_start:%Y%m%d}:{fetch_end:%Y%m%d}"
        ),
    )
    return _build_a_share_refresh_result(
        symbol,
        downloaded=incremental_df,
        df_local=df_local,
        file_path=file_path,
        now=now,
        full_refresh=False,
    )


def _fetch_new_data(
    symbol: str,
    last_update: Optional[datetime],
    now: datetime,
    *,
    df_local: Optional[pd.DataFrame] = None,
    file_path: Optional[str] = None,
) -> Optional[pd.DataFrame | AShareRefreshResult]:
    if _is_a_share_symbol(symbol):
        return _fetch_a_share_refresh(
            symbol,
            df_local,
            last_update,
            file_path or os.path.join(DATA_DIR, f"{symbol}.parquet"),
            now,
        )

    def download_yahoo_history() -> pd.DataFrame:
        with global_download_lock:
            ticker = yf.Ticker(symbol)
            if last_update is not None:
                return ticker.history(
                    start=last_update,
                    end=now,
                    interval="1d",
                )
            fetch_start = now - timedelta(days=DATA_RETENTION_DAYS)
            return ticker.history(
                start=fetch_start,
                end=now,
                interval="1d",
            )

    new_df = yahoo_guard.call(symbol, download_yahoo_history)

    if new_df.empty:
        return None
    if new_df.index.tz is not None:
        new_df.index = new_df.index.tz_localize(None)
    if isinstance(new_df.columns, pd.MultiIndex):
        new_df.columns = new_df.columns.get_level_values(0)
    return _drop_incomplete_ohlcv_rows(new_df)


def _merge_and_clean_data(df_local: Optional[pd.DataFrame], new_df: pd.DataFrame, now: datetime) -> pd.DataFrame:
    if df_local is not None:
        df = pd.concat([df_local, new_df])
        df = df[~df.index.duplicated(keep='last')]
    else:
        df = new_df
    df = _drop_incomplete_ohlcv_rows(df)
    earliest_allowed = now - timedelta(days=DATA_RETENTION_DAYS)
    return df[df.index >= earliest_allowed].sort_index()


def _detect_unadjusted_splits(df: pd.DataFrame, symbol: str) -> None:
    """检测日线跌幅>40%且次日未反弹的异常点，可能是未复权的份额折算/拆分。"""
    daily_ret = df['Close'].pct_change()
    for idx in daily_ret[daily_ret < -0.40].index:
        next_day = idx + pd.Timedelta(days=1)
        for offset in range(1, 5):
            check_date = idx + pd.Timedelta(days=offset)
            if check_date in df.index:
                recovery = (df.loc[check_date, 'Close'] - df.loc[idx, 'Close']) / df.loc[idx, 'Close']
                break
        else:
            recovery = 0.0
        if recovery < 0.05:
            logger.warning(
                f"{symbol}: 检测到疑似未复权事件 {idx.date()}，单日跌幅 {daily_ret[idx]*100:.1f}%，"
                f"次交易日反弹仅 {recovery*100:.1f}%。可能是 ETF 份额折算/拆分，Yahoo Finance 未记录。"
                f"需手工确认并修复 parquet 数据。"
            )


def _calculate_daily_indicators(df: pd.DataFrame) -> pd.DataFrame:
    with ta_calculation_lock:
        df['EMA5'] = ta.ema(df['Close'], length=EMA_FAST_5)
        df['EMA10'] = ta.ema(df['Close'], length=EMA_FAST_10)
        df['EMA20'] = ta.ema(df['Close'], length=EMA_SHORT_PERIOD)
        df['EMA50'] = ta.ema(df['Close'], length=EMA_LONG_PERIOD)
        df['MA30'] = ta.sma(df['Close'], length=30)

        adx_df = ta.adx(df['High'], df['Low'], df['Close'], length=ADX_PERIOD)
        adx_col = _find_col(adx_df.columns if adx_df is not None and not adx_df.empty else [], 'ADX_')
        df['ADX'] = adx_df[adx_col] if adx_col else 0

        for period in RSI_PERIODS:
            col = f'RSI_{period}'
            df[col] = ta.rsi(df['Close'], length=period)
            if col not in df.columns or df[col].isnull().all():
                df[col] = 50

        bbands = ta.bbands(df['Close'], length=BOLL_PERIOD, std=BOLL_STD)
        if bbands is not None and not bbands.empty:
            upper, mid, lower = _find_col(bbands.columns, 'BBU_'), _find_col(bbands.columns, 'BBM_'), _find_col(bbands.columns, 'BBL_')
            if upper and mid and lower:
                df['BOLL_Upper'] = bbands[upper]
                df['BOLL_Mid'] = bbands[mid]
                df['BOLL_Lower'] = bbands[lower]
            else:
                df['BOLL_Upper'] = df['BOLL_Mid'] = df['BOLL_Lower'] = None
        else:
            df['BOLL_Upper'] = df['BOLL_Mid'] = df['BOLL_Lower'] = None

        stoch = ta.stoch(df['High'], df['Low'], df['Close'], k=KDJ_PERIOD, d=KDJ_SIGNAL_K, smooth_k=KDJ_SIGNAL_D)
        if stoch is not None and not stoch.empty:
            k_col, d_col = _find_col(stoch.columns, 'STOCHk_'), _find_col(stoch.columns, 'STOCHd_')
            if k_col and d_col:
                df['K'] = stoch[k_col]
                df['D'] = stoch[d_col]
                df['J'] = 3 * df['K'] - 2 * df['D']
            else:
                df['K'] = df['D'] = df['J'] = 50
        else:
            df['K'] = df['D'] = df['J'] = 50

        macd_df = ta.macd(df['Close'], fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL)
        if macd_df is not None and not macd_df.empty:
            dif = _find_col(macd_df.columns, 'MACD_', exclude_prefixes=('MACDs_', 'MACDh_'))
            dea = _find_col(macd_df.columns, 'MACDs_')
            hist = _find_col(macd_df.columns, 'MACDh_')
            if dif and dea and hist:
                df['MACD_DIF'] = macd_df[dif]
                df['MACD_DEA'] = macd_df[dea]
                df['MACD_Hist'] = macd_df[hist]
            else:
                df['MACD_DIF'] = df['MACD_DEA'] = df['MACD_Hist'] = 0
        else:
            df['MACD_DIF'] = df['MACD_DEA'] = df['MACD_Hist'] = 0

        df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=ATR_PERIOD)
        if 'ATR' not in df.columns or df['ATR'].isnull().all():
            df['ATR'] = 0

        st = ta.supertrend(df['High'], df['Low'], df['Close'], length=ST_LENGTH, multiplier=ST_MULTIPLIER)
        if st is not None and not st.empty:
            val_col = next((c for c in st.columns if c.startswith('SUPERT_') and not any(c.startswith(p) for p in ('SUPERTd_', 'SUPERTs_', 'SUPERTl_', 'SUPERTu_'))), None)
            dir_col = next((c for c in st.columns if c.startswith('SUPERTd_')), None)
            df['ST_Val'] = st[val_col] if val_col else None
            df['ST_Dir'] = st[dir_col] if dir_col else None
        else:
            df['ST_Val'] = df['ST_Dir'] = None

        return df


def _calculate_weekly_indicators(df: pd.DataFrame) -> pd.DataFrame:
    with ta_calculation_lock:
        df_weekly = df.resample('W').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna(subset=['Open', 'High', 'Low', 'Close'])

        df_weekly['MA5_W'] = ta.sma(df_weekly['Close'], length=5)
        df_weekly['EMA5'] = ta.ema(df_weekly['Close'], length=EMA_FAST_5)
        df_weekly['EMA10'] = ta.ema(df_weekly['Close'], length=EMA_FAST_10)
        df_weekly['EMA20'] = ta.ema(df_weekly['Close'], length=EMA_SHORT_PERIOD)
        df_weekly['EMA50'] = ta.ema(df_weekly['Close'], length=EMA_LONG_PERIOD)
        df_weekly['MA30'] = ta.sma(df_weekly['Close'], length=30)

        macd_w = ta.macd(df_weekly['Close'], fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL)
        if macd_w is not None and not macd_w.empty:
            dif = _find_col(macd_w.columns, 'MACD_', exclude_prefixes=('MACDs_', 'MACDh_'))
            dea = _find_col(macd_w.columns, 'MACDs_')
            hist = _find_col(macd_w.columns, 'MACDh_')
            if dif and dea and hist:
                df_weekly['MACD_W'] = macd_w[dif]
                df_weekly['MACD_Signal_W'] = macd_w[dea]
                df_weekly['MACD_Hist_W'] = macd_w[hist]
                df_weekly['MACD_DIF'] = df_weekly['MACD_W']
                df_weekly['MACD_DEA'] = df_weekly['MACD_Signal_W']
                df_weekly['MACD_Hist'] = df_weekly['MACD_Hist_W']
            else:
                df_weekly['MACD_W'] = df_weekly['MACD_Signal_W'] = df_weekly['MACD_Hist_W'] = 0
                df_weekly['MACD_DIF'] = df_weekly['MACD_DEA'] = df_weekly['MACD_Hist'] = 0
        else:
            df_weekly['MACD_W'] = df_weekly['MACD_Signal_W'] = df_weekly['MACD_Hist_W'] = 0
            df_weekly['MACD_DIF'] = df_weekly['MACD_DEA'] = df_weekly['MACD_Hist'] = 0

        bbands = ta.bbands(df_weekly['Close'], length=BOLL_PERIOD, std=BOLL_STD)
        if bbands is not None and not bbands.empty:
            upper, mid, lower = _find_col(bbands.columns, 'BBU_'), _find_col(bbands.columns, 'BBM_'), _find_col(bbands.columns, 'BBL_')
            if upper and mid and lower:
                df_weekly['BOLL_Upper'] = bbands[upper]
                df_weekly['BOLL_Mid'] = bbands[mid]
                df_weekly['BOLL_Lower'] = bbands[lower]
            else:
                df_weekly['BOLL_Upper'] = df_weekly['BOLL_Mid'] = df_weekly['BOLL_Lower'] = None
        else:
            df_weekly['BOLL_Upper'] = df_weekly['BOLL_Mid'] = df_weekly['BOLL_Lower'] = None

        stoch = ta.stoch(df_weekly['High'], df_weekly['Low'], df_weekly['Close'],
                         k=KDJ_PERIOD, d=KDJ_SIGNAL_K, smooth_k=KDJ_SIGNAL_D)
        if stoch is not None and not stoch.empty:
            k_col, d_col = _find_col(stoch.columns, 'STOCHk_'), _find_col(stoch.columns, 'STOCHd_')
            if k_col and d_col:
                df_weekly['K'] = stoch[k_col]
                df_weekly['D'] = stoch[d_col]
                df_weekly['J'] = 3 * df_weekly['K'] - 2 * df_weekly['D']
            else:
                df_weekly['K'] = df_weekly['D'] = df_weekly['J'] = 50
        else:
            df_weekly['K'] = df_weekly['D'] = df_weekly['J'] = 50

        df_weekly['RSI_14'] = ta.rsi(df_weekly['Close'], length=14)
        if df_weekly['RSI_14'].isnull().all():
            df_weekly['RSI_14'] = 50

        df_weekly['ATR'] = ta.atr(df_weekly['High'], df_weekly['Low'], df_weekly['Close'], length=ATR_PERIOD)
        if df_weekly['ATR'].isnull().all():
            df_weekly['ATR'] = 0

        return df_weekly


def fetch_stock_data(symbol: str) -> Optional[Tuple[pd.DataFrame, pd.DataFrame]]:
    symbol = symbol.upper()
    file_path = os.path.join(DATA_DIR, f"{symbol}.parquet")
    now = datetime.now()
    is_a_share = _is_a_share_symbol(symbol)
    source_refreshed = False
    last_full_refresh_at = None
    provider_error: Optional[ProviderError] = None

    with get_symbol_lock(symbol):
        df_local, last_update = _load_local_data(file_path, symbol)

        needs_fetch = True
        if df_local is not None and last_update is not None:
            source_is_current = _has_current_data_source(file_path, symbol)
            if (
                time.time() - os.path.getmtime(file_path) < CACHE_DURATION_SECONDS
                and source_is_current
            ):
                needs_fetch = False

        if not needs_fetch and df_local is not None and 'EMA20' in df_local.columns and 'EMA5' in df_local.columns:
            return df_local.copy(), _calculate_weekly_indicators(df_local.copy())

        df = df_local
        if needs_fetch:
            try:
                fetch_result = _fetch_new_data(
                    symbol,
                    last_update,
                    now,
                    df_local=df_local,
                    file_path=file_path,
                )
                if fetch_result is not None:
                    if is_a_share:
                        if isinstance(fetch_result, AShareRefreshResult):
                            new_df = fetch_result.frame
                            last_full_refresh_at = (
                                fetch_result.last_full_refresh_at
                            )
                        else:
                            # Compatibility for callers/tests that inject a
                            # complete canonical A-share frame.
                            new_df = fetch_result
                            last_full_refresh_at = now
                        df = _merge_and_clean_data(None, new_df, now)
                        source_refreshed = True
                    else:
                        new_df = fetch_result
                        if df is not None:
                            ohlcv_cols = [c for c in df.columns if c in ('Open', 'High', 'Low', 'Close', 'Volume')]
                            df = df[ohlcv_cols]
                        df = _merge_and_clean_data(df, new_df, now)
                    _detect_unadjusted_splits(df, symbol)
                    logger.info(f"获取 {symbol} 新数据成功, {new_df.shape[0]} 条新数据, {df.shape[0]} 条总数据")
            except ProviderError as e:
                provider_error = e
                logger.warning(f"获取 {symbol} 数据源不可用: {e}")
                refreshed_local, _ = _load_local_data(file_path, symbol)
                stale_candidate = (
                    refreshed_local
                    if refreshed_local is not None
                    else df_local
                )
                if (
                    stale_candidate is not None
                    and 'EMA20' in stale_candidate.columns
                    and 'EMA5' in stale_candidate.columns
                ):
                    return (
                        stale_candidate.copy(),
                        _calculate_weekly_indicators(
                            stale_candidate.copy()
                        ),
                    )
            except Exception as e:
                logger.error(f"获取 {symbol} 数据失败: {e}")

            if (
                is_a_share
                and not source_refreshed
                and df_local is not None
                and 'EMA20' in df_local.columns
                and 'EMA5' in df_local.columns
            ):
                return df_local.copy(), _calculate_weekly_indicators(df_local.copy())

        if df is None or df.empty:
            if provider_error is not None:
                raise MarketDataUnavailableError(
                    (
                        f"{provider_error.provider or 'market data'} "
                        f"is unavailable: {provider_error}"
                    ),
                    provider=provider_error.provider,
                    key=symbol,
                    category=provider_error.category,
                    retry_after=provider_error.retry_after,
                ) from provider_error
            return None
        df = df.copy()

    df = _calculate_daily_indicators(df)
    with get_symbol_lock(symbol):
        df.to_parquet(file_path)
        if source_refreshed:
            _write_data_source_metadata(
                file_path,
                symbol,
                last_full_refresh_at=last_full_refresh_at,
            )
    return df, _calculate_weekly_indicators(df)
