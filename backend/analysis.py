import yfinance as yf
import pandas as pd
import pandas_ta as ta
from datetime import datetime, timedelta
import time

# Metrics cache: {symbol: (data, timestamp)}
CACHE = {}
CACHE_DURATION_SECONDS = 60*60 # 1 hour

def fetch_stock_data(symbol: str):
    now = time.time()
    
    # Check cache
    if symbol in CACHE:
        data, timestamp = CACHE[symbol]
        if now - timestamp < CACHE_DURATION_SECONDS:
            return data

    # Fetch 6 months of data to ensure enough for EMA50 + ADX
    end_date = datetime.now()
    start_date = end_date - timedelta(days=200)
    
    try:
        df = yf.download(symbol, start=start_date, end=end_date, interval="1d", progress=False)
        
        if df.empty:
            return None

        # Fix MultiIndex columns if present (yfinance update)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # Calculate Indicators
        # EMA
        df['EMA20'] = ta.ema(df['Close'], length=20)
        df['EMA50'] = ta.ema(df['Close'], length=50)
        
        # ADX (requires High, Low, Close)
        adx_df = ta.adx(df['High'], df['Low'], df['Close'], length=14)
        # pandas_ta returns columns like ADX_14, DMP_14, DMN_14. We just need ADX_14
        if not adx_df.empty:
             df = df.join(adx_df)
             # Rename for consistency if needed, but usually it's ADX_14
             df['ADX'] = df['ADX_14']
        else:
            df['ADX'] = 0
            
        # Update Cache
        CACHE[symbol] = (df, now)
        return df
        
    except Exception as e:
        print(f"Error downloading {symbol}: {e}")
        return None

def analyze_stock(symbol: str):
    df = fetch_stock_data(symbol)
    if df is None or len(df) < 50:
        return None
        
    last_row = df.iloc[-1]
    
    price = float(last_row['Close'])
    ema20 = float(last_row['EMA20'])
    ema50 = float(last_row['EMA50'])
    adx = float(last_row['ADX']) if 'ADX' in last_row else 0
    
    # 第一层：趋势方向过滤（改进版）
    trend = "震荡"
    
    if ema20 > ema50 * 1.001:  # 加入小幅缓冲，多头环境
        if price > ema20:  # 强势多头
            trend = "强势多头"
        elif price > ema50:  # 回调中多头
            trend = "回调多头"
        else:  # 价格跌破EMA50，潜在转空
            trend = "潜在转空"
            
    elif ema20 < ema50 * 0.999:  # 空头环境
        if price < ema20:  # 强势空头
            trend = "强势空头"
        elif price < ema50:  # 反弹中空头
            trend = "反弹空头"
        else:  # 价格突破EMA50，潜在转多
            trend = "潜在转多"
    else:
        # EMA20和EMA50接近，震荡区间
        trend = "震荡"
    
    # 第二层：ADX + 趋势强度过滤
    signal = "WAIT"
    if adx > 25:
        if trend in ["强势多头", "强势空头"]:
            signal = "强烈信号"
        elif trend in ["回调多头", "反弹空头"]:
            signal = "谨慎信号"
        else:
            signal = "观望"
    else:
        signal = "观望"
        
    change_percent = ((price - df.iloc[-2]['Close']) / df.iloc[-2]['Close']) * 100
    
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
        "trend": trend,
        "signal": signal,
        "candles": candles
    }
