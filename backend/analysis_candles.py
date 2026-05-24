import pandas as pd

from analysis_constants import CHART_DAYS, MINI_CHART_DAYS


def _make_json_safe(value):
    import math, numbers
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


def _sanitize_candle_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    clean_df = df.copy()
    for col in [c for c in clean_df.columns if c != 'time']:
        clean_df[col] = pd.to_numeric(clean_df[col], errors='coerce')
    clean_df = clean_df.replace([float('inf'), float('-inf')], pd.NA)
    if 'time' in clean_df.columns:
        time_dt = pd.to_datetime(clean_df['time'], errors='coerce')
        clean_df = clean_df[time_dt.notna()].copy()
        clean_df['time'] = time_dt[time_dt.notna()].dt.strftime('%Y-%m-%d')
    required_cols = [c for c in ['time', 'open', 'high', 'low', 'close'] if c in clean_df.columns]
    if required_cols:
        clean_df = clean_df.dropna(subset=required_cols)
    if 'time' in clean_df.columns:
        clean_df = clean_df[clean_df['time'].notna() & (clean_df['time'] != '')]
    return clean_df


def _ensure_time_ascending(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or 'time' not in df.columns:
        return df
    return (
        df.drop_duplicates(subset=['time'], keep='last')
        .sort_values('time', ascending=True)
        .reset_index(drop=True)
    )


def _to_json_safe_records(df: pd.DataFrame) -> list:
    if df is None or df.empty:
        return []
    safe_df = df.replace([float('inf'), float('-inf')], pd.NA)
    safe_df = safe_df.astype(object).where(pd.notna(safe_df), None)
    return safe_df.to_dict('records')


def _build_candles(df: pd.DataFrame, rsi_period: int = 14, num_days: int = CHART_DAYS) -> list:
    chart_df = df.tail(num_days).copy().reset_index()
    date_col = chart_df.columns[0]
    chart_df['time'] = pd.to_datetime(chart_df[date_col]).dt.strftime('%Y-%m-%d')

    cols = {
        'time': 'time', 'Open': 'open', 'High': 'high', 'Low': 'low',
        'Close': 'close', 'Volume': 'volume', 'EMA20': 'ema20', 'EMA50': 'ema50',
    }
    optional_cols = {
        f'RSI_{rsi_period}': 'rsi',
        'BOLL_Upper': 'boll_upper', 'BOLL_Mid': 'boll_mid', 'BOLL_Lower': 'boll_lower',
        'K': 'k', 'D': 'd', 'J': 'j',
        'MACD_DIF': 'macd_dif', 'MACD_DEA': 'macd_dea', 'MACD_Hist': 'macd_hist',
        'ATR': 'atr',
        'ST_Val': 'st_val', 'ST_Dir': 'st_dir',
    }
    for src, dst in optional_cols.items():
        if src in chart_df.columns:
            cols[src] = dst

    existing = {k: v for k, v in cols.items() if k in chart_df.columns}
    result_df = chart_df[list(existing.keys())].rename(columns=existing)
    result_df = _ensure_time_ascending(_sanitize_candle_df(result_df))
    return _to_json_safe_records(result_df)


def _build_mini_candles(df: pd.DataFrame, num_days: int = MINI_CHART_DAYS) -> list:
    chart_df = df.tail(num_days).copy().reset_index()
    date_col = chart_df.columns[0]
    chart_df['time'] = pd.to_datetime(chart_df[date_col]).dt.strftime('%Y-%m-%d')

    cols = {'time': 'time', 'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'}
    optional_cols = {
        'EMA5': 'ema5', 'EMA10': 'ema10', 'EMA20': 'ema20', 'EMA50': 'ema50',
        'MA30': 'ma30',
        'BOLL_Upper': 'boll_upper', 'BOLL_Lower': 'boll_lower',
        'MACD_DIF': 'macd_dif', 'MACD_DEA': 'macd_dea', 'MACD_Hist': 'macd_hist',
    }
    for src, dst in optional_cols.items():
        if src in chart_df.columns:
            cols[src] = dst

    existing = {k: v for k, v in cols.items() if k in chart_df.columns}
    result_df = chart_df[list(existing.keys())].rename(columns=existing)
    result_df = _ensure_time_ascending(_sanitize_candle_df(result_df))
    return _to_json_safe_records(result_df)
