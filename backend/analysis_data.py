import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple

import pandas as pd
import pandas_ta as ta
import requests
import yfinance as yf

from analysis_constants import (
    DATA_DIR, DATA_RETENTION_DAYS, CACHE_DURATION_SECONDS,
    EMA_FAST_5, EMA_FAST_10, EMA_SHORT_PERIOD, EMA_LONG_PERIOD,
    ADX_PERIOD, RSI_PERIODS, MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    BOLL_PERIOD, BOLL_STD, KDJ_PERIOD, KDJ_SIGNAL_K, KDJ_SIGNAL_D, ATR_PERIOD,
    ST_LENGTH, ST_MULTIPLIER,
)
from analysis_cache import (
    get_symbol_lock, global_download_lock, ta_calculation_lock,
    _drop_incomplete_ohlcv_rows,
)

logger = logging.getLogger(__name__)

A_SHARE_DATA_SOURCE_VERSION = "eastmoney-qfq-v1"
PRICE_JUMP_THRESHOLD = 0.40


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


def _eastmoney_secid(symbol: str) -> Optional[str]:
    normalized = symbol.upper()
    code = normalized.split(".", 1)[0]
    if normalized.endswith(".SS"):
        return f"1.{code}"
    if normalized.endswith(".SZ"):
        return f"0.{code}"
    return None


def _fetch_eastmoney_daily(
    symbol: str,
    start: datetime,
    end: datetime,
) -> Optional[pd.DataFrame]:
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
                response = session.get(
                    "https://push2his.eastmoney.com/api/qt/stock/kline/get",
                    params=params,
                    timeout=8,
                )
                response.raise_for_status()
                payload = response.json()
                break
            except Exception as exc:
                errors.append(exc)

    if payload is None:
        logger.warning(
            f"Eastmoney 日线下载失败 {symbol}: "
            f"{errors[-1] if errors else 'unknown error'}"
        )
        return None

    rows = (payload.get("data") or {}).get("klines") or []
    records = []
    for raw_row in rows:
        parts = str(raw_row).split(",")
        if len(parts) < 6:
            continue
        try:
            records.append({
                "Date": pd.to_datetime(parts[0]),
                "Open": float(parts[1]),
                "Close": float(parts[2]),
                "High": float(parts[3]),
                "Low": float(parts[4]),
                "Volume": float(parts[5]) * 100,
            })
        except (TypeError, ValueError):
            continue

    if not records:
        return None

    df = pd.DataFrame.from_records(records).set_index("Date").sort_index()
    return _drop_incomplete_ohlcv_rows(df)


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


def _has_current_data_source(file_path: str, symbol: str) -> bool:
    if not _is_a_share_symbol(symbol):
        return True
    try:
        with open(_source_metadata_path(file_path), encoding="utf-8") as handle:
            metadata = json.load(handle)
        return (
            metadata.get("symbol") == symbol.upper()
            and metadata.get("sourceVersion") == A_SHARE_DATA_SOURCE_VERSION
        )
    except (OSError, TypeError, ValueError):
        return False


def _write_data_source_metadata(file_path: str, symbol: str) -> None:
    if not _is_a_share_symbol(symbol):
        return
    metadata_path = _source_metadata_path(file_path)
    temporary_path = f"{metadata_path}.tmp"
    payload = {
        "symbol": symbol.upper(),
        "sourceVersion": A_SHARE_DATA_SOURCE_VERSION,
    }
    with open(temporary_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
    os.replace(temporary_path, metadata_path)


def _invalidate_data_source_metadata(file_path: str) -> None:
    try:
        os.remove(_source_metadata_path(file_path))
    except FileNotFoundError:
        pass


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


def _fetch_new_data(symbol: str, last_update: Optional[datetime], now: datetime) -> Optional[pd.DataFrame]:
    if _is_a_share_symbol(symbol):
        fetch_start = now - timedelta(days=DATA_RETENTION_DAYS)
        new_df = _fetch_eastmoney_daily(
            symbol,
            fetch_start,
            now + timedelta(days=1),
        )
        if not _has_valid_price_history(new_df, symbol):
            return None
        return new_df

    with global_download_lock:
        ticker = yf.Ticker(symbol)
        if last_update is not None:
            new_df = ticker.history(start=last_update, end=now, interval="1d")
        else:
            fetch_start = now - timedelta(days=DATA_RETENTION_DAYS)
            new_df = ticker.history(start=fetch_start, end=now, interval="1d")

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
                new_df = _fetch_new_data(symbol, last_update, now)
                if new_df is not None:
                    if is_a_share:
                        df = _merge_and_clean_data(None, new_df, now)
                        source_refreshed = True
                    else:
                        if df is not None:
                            ohlcv_cols = [c for c in df.columns if c in ('Open', 'High', 'Low', 'Close', 'Volume')]
                            df = df[ohlcv_cols]
                        df = _merge_and_clean_data(df, new_df, now)
                    _detect_unadjusted_splits(df, symbol)
                    logger.info(f"获取 {symbol} 新数据成功, {new_df.shape[0]} 条新数据, {df.shape[0]} 条总数据")
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
            return None
        df = df.copy()

    df = _calculate_daily_indicators(df)
    with get_symbol_lock(symbol):
        df.to_parquet(file_path)
        if source_refreshed:
            _write_data_source_metadata(file_path, symbol)
    return df, _calculate_weekly_indicators(df)
