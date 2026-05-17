import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple

import pandas as pd
import pandas_ta as ta
import yfinance as yf

from analysis_constants import (
    DATA_DIR, DATA_RETENTION_DAYS, CACHE_DURATION_SECONDS,
    EMA_FAST_5, EMA_FAST_10, EMA_SHORT_PERIOD, EMA_LONG_PERIOD,
    ADX_PERIOD, RSI_PERIODS, MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    BOLL_PERIOD, BOLL_STD, KDJ_PERIOD, KDJ_SIGNAL_K, KDJ_SIGNAL_D, ATR_PERIOD,
)
from analysis_cache import (
    get_symbol_lock, global_download_lock, ta_calculation_lock,
    _drop_incomplete_ohlcv_rows,
)

logger = logging.getLogger(__name__)


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
        return df, df.index[-1]
    except Exception as e:
        logger.error(f"读取 {symbol} 的 Parquet 文件失败: {e}")
        return None, None


def _fetch_new_data(symbol: str, last_update: Optional[datetime], now: datetime) -> Optional[pd.DataFrame]:
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
    return df[df.index >= earliest_allowed]


def _calculate_daily_indicators(df: pd.DataFrame) -> pd.DataFrame:
    with ta_calculation_lock:
        df['EMA5'] = ta.ema(df['Close'], length=EMA_FAST_5)
        df['EMA10'] = ta.ema(df['Close'], length=EMA_FAST_10)
        df['EMA20'] = ta.ema(df['Close'], length=EMA_SHORT_PERIOD)
        df['EMA50'] = ta.ema(df['Close'], length=EMA_LONG_PERIOD)
        df['MA30'] = ta.sma(df['Close'], length=30)

        adx_df = ta.adx(df['High'], df['Low'], df['Close'], length=ADX_PERIOD)
        adx_col = next((c for c in (adx_df.columns if adx_df is not None and not adx_df.empty else []) if c.startswith('ADX_')), None)
        df['ADX'] = adx_df[adx_col] if adx_col else 0

        for period in RSI_PERIODS:
            col = f'RSI_{period}'
            df[col] = ta.rsi(df['Close'], length=period)
            if col not in df.columns or df[col].isnull().all():
                df[col] = 50

        bbands = ta.bbands(df['Close'], length=BOLL_PERIOD, std=BOLL_STD)
        if bbands is not None and not bbands.empty:
            upper = next((c for c in bbands.columns if c.startswith('BBU_')), None)
            mid = next((c for c in bbands.columns if c.startswith('BBM_')), None)
            lower = next((c for c in bbands.columns if c.startswith('BBL_')), None)
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
            k_col = next((c for c in stoch.columns if c.startswith('STOCHk_')), None)
            d_col = next((c for c in stoch.columns if c.startswith('STOCHd_')), None)
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
            dif = next((c for c in macd_df.columns if c.startswith('MACD_') and not c.startswith('MACDs_') and not c.startswith('MACDh_')), None)
            dea = next((c for c in macd_df.columns if c.startswith('MACDs_')), None)
            hist = next((c for c in macd_df.columns if c.startswith('MACDh_')), None)
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

        return df


def _calculate_weekly_indicators(df: pd.DataFrame) -> pd.DataFrame:
    with ta_calculation_lock:
        df_weekly = df.resample('W').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna(subset=['Open', 'High', 'Low', 'Close'])

        from analysis_constants import EMA_FAST_5, EMA_FAST_10, EMA_SHORT_PERIOD, EMA_LONG_PERIOD
        df_weekly['MA5_W'] = ta.sma(df_weekly['Close'], length=5)
        df_weekly['EMA5'] = ta.ema(df_weekly['Close'], length=EMA_FAST_5)
        df_weekly['EMA10'] = ta.ema(df_weekly['Close'], length=EMA_FAST_10)
        df_weekly['EMA20'] = ta.ema(df_weekly['Close'], length=EMA_SHORT_PERIOD)
        df_weekly['EMA50'] = ta.ema(df_weekly['Close'], length=EMA_LONG_PERIOD)
        df_weekly['MA30'] = ta.sma(df_weekly['Close'], length=30)

        macd_w = ta.macd(df_weekly['Close'], fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL)
        if macd_w is not None and not macd_w.empty:
            dif = next((c for c in macd_w.columns if c.startswith('MACD_') and not c.startswith('MACDs_') and not c.startswith('MACDh_')), None)
            dea = next((c for c in macd_w.columns if c.startswith('MACDs_')), None)
            hist = next((c for c in macd_w.columns if c.startswith('MACDh_')), None)
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
            upper = next((c for c in bbands.columns if c.startswith('BBU_')), None)
            mid = next((c for c in bbands.columns if c.startswith('BBM_')), None)
            lower = next((c for c in bbands.columns if c.startswith('BBL_')), None)
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
            k_col = next((c for c in stoch.columns if c.startswith('STOCHk_')), None)
            d_col = next((c for c in stoch.columns if c.startswith('STOCHd_')), None)
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

    with get_symbol_lock(symbol):
        df_local, last_update = _load_local_data(file_path, symbol)

        needs_fetch = True
        if df_local is not None and last_update is not None:
            if time.time() - os.path.getmtime(file_path) < CACHE_DURATION_SECONDS:
                needs_fetch = False

        if not needs_fetch and df_local is not None and 'EMA20' in df_local.columns and 'EMA5' in df_local.columns:
            return df_local.copy(), _calculate_weekly_indicators(df_local.copy())

        df = df_local
        if needs_fetch:
            try:
                new_df = _fetch_new_data(symbol, last_update, now)
                if new_df is not None:
                    if df is not None:
                        ohlcv_cols = [c for c in df.columns if c in ('Open', 'High', 'Low', 'Close', 'Volume')]
                        df = df[ohlcv_cols]
                    df = _merge_and_clean_data(df, new_df, now)
                    logger.info(f"获取 {symbol} 新数据成功, {new_df.shape[0]} 条新数据, {df.shape[0]} 条总数据")
            except Exception as e:
                logger.error(f"获取 {symbol} 数据失败: {e}")

        if df is None or df.empty:
            return None
        df = df.copy()

    df = _calculate_daily_indicators(df)
    with get_symbol_lock(symbol):
        df.to_parquet(file_path)
    return df, _calculate_weekly_indicators(df)
