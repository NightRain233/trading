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
    
    # Trend Logic
    trend = "NEUTRAL"
    if ema20 > ema50 and price > ema50:
        trend = "LONG"
    elif ema20 < ema50 and price < ema50:
        trend = "SHORT"
        
    # Strength
    strength = "STRONG" if adx > 25 else "WEAK"
    
    signal = "WAIT"
    if trend == "LONG" and adx > 25:
        signal = "ENTRY_Long"
    elif trend == "SHORT" and adx > 25:
        signal = "ENTRY_Short"
        
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
        "trendStrength": strength,
        "signal": signal,
        "candles": candles
    }
