import yfinance as yf
import pandas as pd
import pandas_ta as ta
from datetime import datetime, timedelta
import time
import pickle
import os

import threading


from collections import defaultdict

# Fine-grained locks: one lock per symbol for indicator calculation
symbol_locks = defaultdict(threading.Lock)
# Global lock for yfinance downloads to prevent thread-safety issues with shared sessions
global_download_lock = threading.Lock()

def get_symbol_lock(symbol: str):
    return symbol_locks[symbol.upper()]

DATA_DIR = "data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

CACHE_DURATION_SECONDS = 60 * 60  # 1 hour

def fetch_stock_data(symbol: str):
    symbol = symbol.upper()
    file_path = os.path.join(DATA_DIR, f"{symbol}.parquet")
    now = datetime.now()
    
    # 使用 symbol-specific lock 确保只有一个线程计算指标
    # 原因：这是由于 yfinance 库内部在进行大规模并发下载时，共享了底层的网络会话和状态
    # 所以需要加锁来避免一个请求的结果被错误地返回给了另一个
    with get_symbol_lock(symbol):
        df_local = None
        last_update = None
        
        # 1. Try to load local data
        if os.path.exists(file_path):
            try:
                df_local = pd.read_parquet(file_path)
                if not df_local.empty:
                    if not isinstance(df_local.index, pd.DatetimeIndex):
                        df_local.index = pd.to_datetime(df_local.index)
                    # Strip timezone if present
                    if df_local.index.tz is not None:
                        df_local.index = df_local.index.tz_localize(None)
                    last_update = df_local.index[-1]
            except Exception as e:
                print(f"Error reading parquet for {symbol}: {e}")
                df_local = None

        # 2. Check if we need to fetch new data
        needs_fetch = True
        if df_local is not None and last_update is not None:
            file_mod_time = os.path.getmtime(file_path)
            if time.time() - file_mod_time < CACHE_DURATION_SECONDS:
                needs_fetch = False
        
        if needs_fetch:
            try:
                # yf.download is not thread-safe and can return mixed data for different tickers
                # We use a global lock around the fetch and use Ticker.history for single symbols
                with global_download_lock:
                    ticker = yf.Ticker(symbol)
                    
                    if df_local is not None and last_update is not None:
                        # Fetch from last_update
                        # ticker.history handles dates gracefully
                        new_df = ticker.history(start=last_update, end=now, interval="1d")
                    else:
                        fetch_start = now - timedelta(days=730)
                        new_df = ticker.history(start=fetch_start, end=now, interval="1d")
                
                if not new_df.empty:
                    # Strip timezone for consistency with now()
                    if new_df.index.tz is not None:
                        new_df.index = new_df.index.tz_localize(None)
                        
                    # history result has plain index, but let's be safe
                    if isinstance(new_df.columns, pd.MultiIndex):
                        new_df.columns = new_df.columns.get_level_values(0)
                    
                    # history returns adjusted prices by default
                    if df_local is not None:
                        df = pd.concat([df_local, new_df])
                        df = df[~df.index.duplicated(keep='last')]
                    else:
                        df = new_df
                    
                    earliest_allowed = now - timedelta(days=730)
                    df = df[df.index >= earliest_allowed]
                    
                    # Ensure basic columns are present (history uses Title Case)
                    # Check if 'Close' exists, else error
                    if 'Close' not in df.columns:
                         # Sometimes it might be 'Close' but within a MultiIndex we didn't flatten?
                         # Just in case, try to rename if they match
                         pass

                    df.to_parquet(file_path)
                else:
                    df = df_local
            except Exception as e:
                print(f"Error fetching {symbol}: {e}")
                df = df_local
        else:
            df = df_local

        if df is None or df.empty:
            return None

        # 3. Calculate Indicators (Always recalculate to ensure freshness/correctness)
        # Daily Indicators
        df['EMA20'] = ta.ema(df['Close'], length=20)
        df['EMA50'] = ta.ema(df['Close'], length=50)
        
        adx_df = ta.adx(df['High'], df['Low'], df['Close'], length=14)
        if adx_df is not None and not adx_df.empty:
            df = df.join(adx_df)
            df['ADX'] = df['ADX_14']
        else:
            df['ADX'] = 0
            
        df['RSI_7'] = ta.rsi(df['Close'], length=7)
        df['RSI_14'] = ta.rsi(df['Close'], length=14)
        df['RSI_21'] = ta.rsi(df['Close'], length=21)
        
        for p in [7, 14, 21]:
            if f'RSI_{p}' not in df.columns or df[f'RSI_{p}'].isnull().all():
                df[f'RSI_{p}'] = 50

        # 4. Weekly Indicators
        # Resample to weekly (W-FRI or just W)
        df_weekly = df.resample('W').agg({
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum'
        })
        
        df_weekly['MA5_W'] = ta.sma(df_weekly['Close'], length=5)
        macd_w = ta.macd(df_weekly['Close'], fast=12, slow=26, signal=9)
        if macd_w is not None and not macd_w.empty:
            df_weekly = df_weekly.join(macd_w)
            df_weekly['MACD_W'] = df_weekly['MACD_12_26_9']
            df_weekly['MACD_Signal_W'] = df_weekly['MACDs_12_26_9']
            df_weekly['MACD_Hist_W'] = df_weekly['MACDh_12_26_9']
        else:
            df_weekly['MACD_W'] = 0
            df_weekly['MACD_Signal_W'] = 0
            df_weekly['MACD_Hist_W'] = 0

        return df.copy(), df_weekly.copy()

def analyze_stock(symbol: str):
    data = fetch_stock_data(symbol)
    if data is None:
        return None
    
    df, df_weekly = data
    if df is None or len(df) < 50:
        return None
        
    last_row = df.iloc[-1]
    
    price = float(last_row['Close'])
    ema20 = float(last_row['EMA20'])
    ema50 = float(last_row['EMA50'])
    adx = float(last_row['ADX']) if 'ADX' in last_row else 0
    
    # Dynamic RSI Selection Logic
    if adx > 30:
        rsi_period = 21
    elif adx < 20:
        rsi_period = 7
    else:
        rsi_period = 14
        
    rsi_key = f'RSI_{rsi_period}'
    rsi = float(last_row[rsi_key]) if rsi_key in last_row else 50
    
    # Trend Analysis
    trend = "震荡"
    if ema20 > ema50 * 1.001:
        if price > ema20: trend = "强势多头"
        elif price > ema50: trend = "回调多头"
        else: trend = "潜在转空"
    elif ema20 < ema50 * 0.999:
        if price < ema20: trend = "强势空头"
        elif price < ema50: trend = "反弹空头"
        else: trend = "潜在转多"
    
    # Signal Analysis
    signal = "WAIT"
    if adx > 25:
        if trend in ["强势多头", "强势空头"]: signal = "强烈信号"
        elif trend in ["回调多头", "反弹空头"]: signal = "谨慎信号"
        else: signal = "观望"
    else:
        signal = "观望"
    
    # RSI Status
    is_uptrend = trend in ["强势多头", "回调多头"]
    is_downtrend = trend in ["强势空头", "反弹空头"]
    if adx > 25:
        if is_uptrend: rsi_overbought, rsi_oversold = 75, 45
        elif is_downtrend: rsi_overbought, rsi_oversold = 60, 25
        else: rsi_overbought, rsi_oversold = 70, 30
    else:
        rsi_overbought, rsi_oversold = 70, 30
    
    if rsi >= rsi_overbought: rsi_status = "超买"
    elif rsi <= rsi_oversold: rsi_status = "超卖"
    else: rsi_status = "中性"
        
    change_percent = ((price - df.iloc[-2]['Close']) / df.iloc[-2]['Close']) * 100
    
    # Weekly Analysis
    weekly_status = {}
    if df_weekly is not None and not df_weekly.empty:
        last_w = df_weekly.iloc[-1]
        w_macd = float(last_w['MACD_W'])
        w_signal = float(last_w['MACD_Signal_W'])
        w_ma5 = float(last_w['MA5_W'])
        
        if w_macd > w_signal:
            weekly_macd_status = "周线牛市" if w_macd > 0 else "周线反弹"
        else:
            weekly_macd_status = "周线回调" if w_macd > 0 else "周线熊市"
            
        weekly_price_vs_ma5 = "线上" if price > w_ma5 else "线下"
        
        weekly_status = {
            "weeklyMA5": w_ma5,
            "weeklyMacdStatus": weekly_macd_status,
            "weeklyPriceVsMA5": weekly_price_vs_ma5,
            "weeklyMacdHist": float(last_w['MACD_Hist_W'])
        }

    # Candle data for chart (Last 100 days)
    candles = []
    chart_df = df.tail(100)
    for index, row in chart_df.iterrows():
        candles.append({
            "time": index.strftime('%Y-%m-%d'),
            "open": float(row['Open']),
            "high": float(row['High']),
            "low": float(row['Low']),
            "close": float(row['Close'])
        })

    return {
        "symbol": symbol,
        "name": symbol, 
        "price": price,
        "changePercent": change_percent,
        "ema20": ema20,
        "ema50": ema50,
        "adx": adx,
        "rsi": rsi,
        "rsiPeriod": rsi_period,
        "rsiStatus": rsi_status,
        "rsiOverbought": rsi_overbought,
        "rsiOversold": rsi_oversold,
        "trend": trend,
        "signal": signal,
        "candles": candles,
        **weekly_status
    }
