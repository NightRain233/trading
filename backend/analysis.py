"""
股票技术分析模块

提供股票数据获取、技术指标计算和趋势分析功能。
"""

import logging
import os
import time
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional, Tuple

import pandas as pd
import pandas_ta as ta
import yfinance as yf

# ============================================
# 配置常量
# ============================================

DATA_DIR = "data"
CACHE_DURATION_SECONDS = 60 * 60  # 缓存有效期：1小时
DATA_RETENTION_DAYS = 730         # 数据保留天数：2年

# 技术指标参数
EMA_FAST_5 = 5
EMA_FAST_10 = 10
EMA_SHORT_PERIOD = 20
EMA_LONG_PERIOD = 50
ADX_PERIOD = 14
RSI_PERIODS = (7, 14, 21)

# MACD 参数
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# 布林线参数
BOLL_PERIOD = 20
BOLL_STD = 2

# KDJ 参数
KDJ_PERIOD = 9
KDJ_SIGNAL_K = 3
KDJ_SIGNAL_D = 3

# ATR 参数
ATR_PERIOD = 14

# RSI 阈值配置 (超买, 超卖)
RSI_THRESHOLDS = {
    "uptrend_strong": (75, 45),    # 上升趋势，ADX > 25
    "downtrend_strong": (60, 25),  # 下降趋势，ADX > 25
    "default": (70, 30),           # 默认/震荡
}

# K线图显示天数
CHART_DAYS = 100

# 迷你 K 线图显示天数
MINI_CHART_DAYS = 30

# ============================================
# 线程锁管理
# ============================================

# 细粒度锁：每个股票代码一个锁，用于指标计算
symbol_locks = defaultdict(threading.Lock)
# 全局锁：用于 yfinance 下载，避免共享会话导致的线程安全问题
global_download_lock = threading.Lock()

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 确保数据目录存在
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)


def get_symbol_lock(symbol: str) -> threading.Lock:
    """获取指定股票代码的线程锁"""
    return symbol_locks[symbol.upper()]


# ============================================
# 数据获取与缓存
# ============================================

def _load_local_data(file_path: str, symbol: str) -> Tuple[Optional[pd.DataFrame], Optional[datetime]]:
    """
    从本地 Parquet 文件加载数据

    Args:
        file_path: 文件路径
        symbol: 股票代码

    Returns:
        (DataFrame, 最后更新时间) 或 (None, None)
    """
    if not os.path.exists(file_path):
        return None, None

    try:
        df = pd.read_parquet(file_path)
        if df.empty:
            return None, None

        # 确保索引是 DatetimeIndex
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)

        # 移除时区信息，保持一致性
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        last_update = df.index[-1]
        return df, last_update

    except Exception as e:
        logger.error(f"读取 {symbol} 的 Parquet 文件失败: {e}")
        return None, None


def _fetch_new_data(symbol: str, last_update: Optional[datetime], now: datetime) -> Optional[pd.DataFrame]:
    """
    从 yfinance 获取新数据

    Args:
        symbol: 股票代码
        last_update: 上次更新时间（用于增量获取）
        now: 当前时间

    Returns:
        新获取的 DataFrame 或 None
    """
    with global_download_lock:
        ticker = yf.Ticker(symbol)

        if last_update is not None:
            # 增量获取：从上次更新时间开始
            new_df = ticker.history(start=last_update, end=now, interval="1d")
        else:
            # 全量获取：获取近两年数据
            fetch_start = now - timedelta(days=DATA_RETENTION_DAYS)
            new_df = ticker.history(start=fetch_start, end=now, interval="1d")

    if new_df.empty:
        return None

    # 移除时区信息
    if new_df.index.tz is not None:
        new_df.index = new_df.index.tz_localize(None)

    # 处理可能的 MultiIndex 列
    if isinstance(new_df.columns, pd.MultiIndex):
        new_df.columns = new_df.columns.get_level_values(0)

    return new_df


def _merge_and_clean_data(df_local: Optional[pd.DataFrame], new_df: pd.DataFrame, now: datetime) -> pd.DataFrame:
    """
    合并本地数据和新数据，并清理过期数据

    Args:
        df_local: 本地数据
        new_df: 新获取的数据
        now: 当前时间

    Returns:
        合并后的 DataFrame
    """
    if df_local is not None:
        df = pd.concat([df_local, new_df])
        df = df[~df.index.duplicated(keep='last')]
    else:
        df = new_df

    # 只保留指定天数内的数据
    earliest_allowed = now - timedelta(days=DATA_RETENTION_DAYS)
    df = df[df.index >= earliest_allowed]

    return df


def _calculate_daily_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    计算日线技术指标

    计算 EMA20、EMA50、ADX、RSI(7/14/21)、BOLL、KDJ、MACD、ATR

    Args:
        df: 日线数据

    Returns:
        添加了指标的 DataFrame
    """
    # EMA 指标
    df['EMA5'] = ta.ema(df['Close'], length=EMA_FAST_5)
    df['EMA10'] = ta.ema(df['Close'], length=EMA_FAST_10)
    df['EMA20'] = ta.ema(df['Close'], length=EMA_SHORT_PERIOD)
    df['EMA50'] = ta.ema(df['Close'], length=EMA_LONG_PERIOD)

    # ADX 指标
    adx_df = ta.adx(df['High'], df['Low'], df['Close'], length=ADX_PERIOD)
    if adx_df is not None and not adx_df.empty:
        # 使用前缀搜索 ADX 列
        adx_col = next((c for c in adx_df.columns if c.startswith('ADX_')), None)
        if adx_col:
            df['ADX'] = adx_df[adx_col]
        else:
            df['ADX'] = 0
    else:
        df['ADX'] = 0

    # RSI 指标（多周期）
    for period in RSI_PERIODS:
        col_name = f'RSI_{period}'
        df[col_name] = ta.rsi(df['Close'], length=period)
        # 如果 RSI 计算失败，设置默认值
        if col_name not in df.columns or df[col_name].isnull().all():
            df[col_name] = 50

    # 布林线 (BOLL)
    bbands = ta.bbands(df['Close'], length=BOLL_PERIOD, std=BOLL_STD)
    if bbands is not None and not bbands.empty:
        # 使用列名前缀搜索，提高鲁棒性（不同版本的 pandas-ta 可能使用不同的小数格式）
        upper_col = next((c for c in bbands.columns if c.startswith('BBU_')), None)
        mid_col = next((c for c in bbands.columns if c.startswith('BBM_')), None)
        lower_col = next((c for c in bbands.columns if c.startswith('BBL_')), None)
        
        if upper_col and mid_col and lower_col:
            df['BOLL_Upper'] = bbands[upper_col]
            df['BOLL_Mid'] = bbands[mid_col]
            df['BOLL_Lower'] = bbands[lower_col]
        else:
            df['BOLL_Upper'] = df['BOLL_Mid'] = df['BOLL_Lower'] = None
    else:
        df['BOLL_Upper'] = df['BOLL_Mid'] = df['BOLL_Lower'] = None

    # KDJ 指标
    stoch = ta.stoch(df['High'], df['Low'], df['Close'], k=KDJ_PERIOD, d=KDJ_SIGNAL_K, smooth_k=KDJ_SIGNAL_D)
    if stoch is not None and not stoch.empty:
        # 寻找 STOCHk 和 STOCHd 列
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

    # MACD 指标
    macd_df = ta.macd(df['Close'], fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL)
    if macd_df is not None and not macd_df.empty:
        # 寻找 MACD 主线、信号线和柱状图列
        dif_col = next((c for c in macd_df.columns if c.startswith('MACD_') and not c.startswith('MACDs_') and not c.startswith('MACDh_')), None)
        dea_col = next((c for c in macd_df.columns if c.startswith('MACDs_')), None)
        hist_col = next((c for c in macd_df.columns if c.startswith('MACDh_')), None)
        
        if dif_col and dea_col and hist_col:
            df['MACD_DIF'] = macd_df[dif_col]
            df['MACD_DEA'] = macd_df[dea_col]
            df['MACD_Hist'] = macd_df[hist_col]
        else:
            df['MACD_DIF'] = df['MACD_DEA'] = df['MACD_Hist'] = 0
    else:
        df['MACD_DIF'] = df['MACD_DEA'] = df['MACD_Hist'] = 0

    # ATR 指标
    df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=ATR_PERIOD)
    if 'ATR' not in df.columns or df['ATR'].isnull().all():
        df['ATR'] = 0

    return df


def _calculate_weekly_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    计算周线技术指标

    计算周线 MA5, EMA, MACD, BOLL, KDJ, RSI, ATR

    Args:
        df: 日线数据

    Returns:
        周线 DataFrame（包含指标）
    """
    # 重采样为周线
    df_weekly = df.resample('W').agg({
        'Open': 'first',
        'High': 'max',
        'Low': 'min',
        'Close': 'last',
        'Volume': 'sum'
    }).dropna(subset=['Open', 'High', 'Low', 'Close'])

    # 周线 5 日均线
    df_weekly['MA5_W'] = ta.sma(df_weekly['Close'], length=5)

    # EMA 指标
    df_weekly['EMA20'] = ta.ema(df_weekly['Close'], length=EMA_SHORT_PERIOD)
    df_weekly['EMA50'] = ta.ema(df_weekly['Close'], length=EMA_LONG_PERIOD)

    # 周线 MACD
    macd_w = ta.macd(df_weekly['Close'], fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL)
    if macd_w is not None and not macd_w.empty:
        dif_col = next((c for c in macd_w.columns if c.startswith('MACD_') and not c.startswith('MACDs_') and not c.startswith('MACDh_')), None)
        dea_col = next((c for c in macd_w.columns if c.startswith('MACDs_')), None)
        hist_col = next((c for c in macd_w.columns if c.startswith('MACDh_')), None)
        
        if dif_col and dea_col and hist_col:
            df_weekly['MACD_W'] = macd_w[dif_col]
            df_weekly['MACD_Signal_W'] = macd_w[dea_col]
            df_weekly['MACD_Hist_W'] = macd_w[hist_col]
            # 同时保存为通用名
            df_weekly['MACD_DIF'] = df_weekly['MACD_W']
            df_weekly['MACD_DEA'] = df_weekly['MACD_Signal_W']
            df_weekly['MACD_Hist'] = df_weekly['MACD_Hist_W']
        else:
            df_weekly['MACD_W'] = df_weekly['MACD_Signal_W'] = df_weekly['MACD_Hist_W'] = 0
            df_weekly['MACD_DIF'] = df_weekly['MACD_DEA'] = df_weekly['MACD_Hist'] = 0
    else:
        df_weekly['MACD_W'] = df_weekly['MACD_Signal_W'] = df_weekly['MACD_Hist_W'] = 0
        df_weekly['MACD_DIF'] = df_weekly['MACD_DEA'] = df_weekly['MACD_Hist'] = 0

    # 布林线 (BOLL)
    bbands = ta.bbands(df_weekly['Close'], length=BOLL_PERIOD, std=BOLL_STD)
    if bbands is not None and not bbands.empty:
        upper_col = next((c for c in bbands.columns if c.startswith('BBU_')), None)
        mid_col = next((c for c in bbands.columns if c.startswith('BBM_')), None)
        lower_col = next((c for c in bbands.columns if c.startswith('BBL_')), None)
        
        if upper_col and mid_col and lower_col:
            df_weekly['BOLL_Upper'] = bbands[upper_col]
            df_weekly['BOLL_Mid'] = bbands[mid_col]
            df_weekly['BOLL_Lower'] = bbands[lower_col]
        else:
            df_weekly['BOLL_Upper'] = df_weekly['BOLL_Mid'] = df_weekly['BOLL_Lower'] = None
    else:
        df_weekly['BOLL_Upper'] = df_weekly['BOLL_Mid'] = df_weekly['BOLL_Lower'] = None

    # KDJ 指标
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

    # RSI 指标（使用默认周期 14）
    df_weekly['RSI_14'] = ta.rsi(df_weekly['Close'], length=14)
    if df_weekly['RSI_14'].isnull().all():
        df_weekly['RSI_14'] = 50

    # ATR 指标
    df_weekly['ATR'] = ta.atr(df_weekly['High'], df_weekly['Low'], df_weekly['Close'], length=ATR_PERIOD)
    if df_weekly['ATR'].isnull().all():
        df_weekly['ATR'] = 0

    return df_weekly


def fetch_stock_data(symbol: str) -> Optional[Tuple[pd.DataFrame, pd.DataFrame]]:
    """
    获取股票数据并计算技术指标

    优先使用本地缓存，缓存过期则增量获取新数据。
    指标计算结果会保存到 Parquet，缓存有效且含指标时跳过重算。

    Args:
        symbol: 股票代码

    Returns:
        (日线 DataFrame, 周线 DataFrame) 或 None
    """
    symbol = symbol.upper()
    file_path = os.path.join(DATA_DIR, f"{symbol}.parquet")
    now = datetime.now()

    # ========================================
    # 第一阶段：数据 I/O（需要锁保护）
    # ========================================
    with get_symbol_lock(symbol):
        # 1. 加载本地数据
        df_local, last_update = _load_local_data(file_path, symbol)

        # 2. 判断是否需要获取新数据
        needs_fetch = True
        if df_local is not None and last_update is not None:
            file_mod_time = os.path.getmtime(file_path)
            if time.time() - file_mod_time < CACHE_DURATION_SECONDS:
                needs_fetch = False

        # 3. 缓存有效且已含指标列 → 直接返回，跳过指标计算
        if not needs_fetch and df_local is not None and 'EMA20' in df_local.columns and 'EMA5' in df_local.columns:
            df = df_local.copy()
            df_weekly = _calculate_weekly_indicators(df)
            return df, df_weekly

        # 4. 获取并合并新数据
        df = df_local
        if needs_fetch:
            start_time = datetime.now()
            logger.info(f"开始获取 {symbol} 新数据")
            try:
                new_df = _fetch_new_data(symbol, last_update, now)
                if new_df is not None:
                    # 合并前去掉旧的指标列，只保留 OHLCV
                    if df is not None:
                        ohlcv_cols = [c for c in df.columns if c in ('Open', 'High', 'Low', 'Close', 'Volume')]
                        df = df[ohlcv_cols]
                    df = _merge_and_clean_data(df, new_df, now)
                    logger.info(f"获取 {symbol} 新数据成功, {new_df.shape[0]} 条新数据, {df.shape[0]} 条总数据，耗时 {(datetime.now() - start_time).total_seconds():.2f}s")
            except Exception as e:
                logger.error(f"获取 {symbol} 数据失败: {e}")

        if df is None or df.empty:
            return None
        df = df.copy()

    # ========================================
    # 第二阶段：指标计算 + 保存（无需锁，可并行）
    # ========================================
    df = _calculate_daily_indicators(df)

    # 将含指标的完整 DataFrame 保存回 Parquet
    with get_symbol_lock(symbol):
        df.to_parquet(file_path)

    df_weekly = _calculate_weekly_indicators(df)

    return df, df_weekly


# ============================================
# 趋势与信号分析
# ============================================

def _get_dynamic_rsi(adx: float, last_row: pd.Series) -> Tuple[int, float]:
    """
    根据 ADX 动态选择 RSI 周期

    - ADX > 30: 使用 RSI(21)，强趋势需要更长周期
    - ADX < 20: 使用 RSI(7)，弱趋势需要更短周期
    - 其他: 使用 RSI(14)，默认周期

    Args:
        adx: ADX 值
        last_row: 最新一行数据

    Returns:
        (RSI周期, RSI值)
    """
    if adx > 30:
        period = 21
    elif adx < 20:
        period = 7
    else:
        period = 14

    rsi_key = f'RSI_{period}'
    rsi = float(last_row[rsi_key]) if rsi_key in last_row else 50

    return period, rsi


def _analyze_trend(price: float, ema20: float, ema50: float) -> str:
    """
    分析价格趋势

    基于价格与 EMA20、EMA50 的关系判断趋势。

    Args:
        price: 当前价格
        ema20: 20日EMA
        ema50: 50日EMA

    Returns:
        趋势描述字符串
    """
    if ema20 > ema50 * 1.001:
        # EMA20 > EMA50，整体偏多
        if price > ema20:
            return "强势多头"
        elif price > ema50:
            return "回调多头"
        else:
            return "潜在转空"
    elif ema20 < ema50 * 0.999:
        # EMA20 < EMA50，整体偏空
        if price < ema20:
            return "强势空头"
        elif price < ema50:
            return "反弹空头"
        else:
            return "潜在转多"
    else:
        return "震荡"


def _get_signal(adx: float, trend: str) -> str:
    """
    根据 ADX 和趋势生成交易信号

    Args:
        adx: ADX 值
        trend: 趋势描述

    Returns:
        信号描述字符串
    """
    if adx <= 25:
        return "观望"

    if trend in ("强势多头", "强势空头"):
        return "强烈信号"
    elif trend in ("回调多头", "反弹空头"):
        return "谨慎信号"
    else:
        return "观望"


def _get_rsi_status(rsi: float, adx: float, trend: str) -> Tuple[str, int, int]:
    """
    计算 RSI 状态和动态阈值

    根据趋势和 ADX 调整超买超卖阈值：
    - 上升趋势 + 强ADX: 阈值上移
    - 下降趋势 + 强ADX: 阈值下移
    - 其他情况: 使用默认阈值

    Args:
        rsi: RSI 值
        adx: ADX 值
        trend: 趋势描述

    Returns:
        (RSI状态, 超买阈值, 超卖阈值)
    """
    is_uptrend = trend in ("强势多头", "回调多头")
    is_downtrend = trend in ("强势空头", "反弹空头")

    # 根据趋势和 ADX 选择阈值
    if adx > 25:
        if is_uptrend:
            overbought, oversold = RSI_THRESHOLDS["uptrend_strong"]
        elif is_downtrend:
            overbought, oversold = RSI_THRESHOLDS["downtrend_strong"]
        else:
            overbought, oversold = RSI_THRESHOLDS["default"]
    else:
        overbought, oversold = RSI_THRESHOLDS["default"]

    # 判断 RSI 状态
    if rsi >= overbought:
        status = "超买"
    elif rsi <= oversold:
        status = "超卖"
    else:
        status = "中性"

    return status, overbought, oversold


def _get_weekly_status(price: float, df_weekly: pd.DataFrame) -> dict:
    """
    计算周线指标状态

    Args:
        price: 当前价格
        df_weekly: 周线数据

    Returns:
        周线状态字典
    """
    if df_weekly is None or df_weekly.empty:
        return {}

    last_w = df_weekly.iloc[-1]
    w_macd = float(last_w['MACD_W'])
    w_signal = float(last_w['MACD_Signal_W'])
    w_ma5 = float(last_w['MA5_W'])

    # MACD 状态判断
    if w_macd > w_signal:
        macd_status = "周线牛市" if w_macd > 0 else "周线反弹"
    else:
        macd_status = "周线回调" if w_macd > 0 else "周线熊市"

    # 价格与周线 MA5 关系
    price_vs_ma5 = "线上" if price > w_ma5 else "线下"

    return {
        "weeklyMA5": w_ma5,
        "weeklyMacdStatus": macd_status,
        "weeklyPriceVsMA5": price_vs_ma5,
        "weeklyMacdHist": float(last_w['MACD_Hist_W'])
    }


def _build_candles(df: pd.DataFrame, rsi_period: int = 14, num_days: int = CHART_DAYS) -> list:
    """
    构建 K 线图数据，包含成交量和各项指标

    Args:
        df: 数据（日线或周线）
        rsi_period: 选定的 RSI 周期
        num_days: 显示的数据条数

    Returns:
        详情数据列表
    """
    chart_df = df.tail(num_days).copy()
    chart_df = chart_df.reset_index()

    # 获取日期列名
    date_col = chart_df.columns[0]
    chart_df['time'] = pd.to_datetime(chart_df[date_col]).dt.strftime('%Y-%m-%d')

    # 基础列映射
    cols = {
        'time': 'time',
        'Open': 'open',
        'High': 'high',
        'Low': 'low',
        'Close': 'close',
        'Volume': 'volume',
        'EMA20': 'ema20',
        'EMA50': 'ema50',
    }
    
    # 添加可选列（存在则映射）
    optional_cols = {
        f'RSI_{rsi_period}': 'rsi',
        'BOLL_Upper': 'boll_upper',
        'BOLL_Mid': 'boll_mid',
        'BOLL_Lower': 'boll_lower',
        'K': 'k',
        'D': 'd',
        'J': 'j',
        'MACD_DIF': 'macd_dif',
        'MACD_DEA': 'macd_dea',
        'MACD_Hist': 'macd_hist',
        'ATR': 'atr',
    }
    
    for src, dst in optional_cols.items():
        if src in chart_df.columns:
            cols[src] = dst
    
    # 过滤存在的列
    existing_cols = {k: v for k, v in cols.items() if k in chart_df.columns}
    result_df = chart_df[list(existing_cols.keys())].rename(columns=existing_cols)
    return result_df.to_dict('records')



def _build_mini_candles(df: pd.DataFrame, num_days: int = MINI_CHART_DAYS) -> list:
    """
    构建迷你 K 线图数据（精简字段，用于列表页缩略图）

    Args:
        df: 含指标的日线 DataFrame
        num_days: 显示天数

    Returns:
        精简 K 线数据列表
    """
    chart_df = df.tail(num_days).copy()
    chart_df = chart_df.reset_index()

    date_col = chart_df.columns[0]
    chart_df['time'] = pd.to_datetime(chart_df[date_col]).dt.strftime('%Y-%m-%d')

    cols = {
        'time': 'time',
        'Open': 'open',
        'High': 'high',
        'Low': 'low',
        'Close': 'close',
    }

    optional_cols = {
        'EMA5': 'ema5',
        'EMA10': 'ema10',
        'EMA20': 'ema20',
        'EMA50': 'ema50',
    }

    for src, dst in optional_cols.items():
        if src in chart_df.columns:
            cols[src] = dst

    existing_cols = {k: v for k, v in cols.items() if k in chart_df.columns}
    result_df = chart_df[list(existing_cols.keys())].rename(columns=existing_cols)
    return result_df.to_dict('records')


# ============================================
# 主分析函数
# ============================================

def analyze_stock(symbol: str) -> Optional[dict]:
    """
    对股票进行综合技术分析

    包括：趋势分析、信号判断、RSI状态、周线分析、K线数据。

    Args:
        symbol: 股票代码

    Returns:
        分析结果字典，或 None（如果数据不足）
    """
    data = fetch_stock_data(symbol)
    if data is None:
        return None

    df, df_weekly = data
    if df is None or len(df) < EMA_LONG_PERIOD:
        return None

    last_row = df.iloc[-1]

    # 提取基础数据
    price = float(last_row['Close'])
    ema20 = float(last_row['EMA20'])
    ema50 = float(last_row['EMA50'])
    adx = float(last_row['ADX']) if 'ADX' in last_row else 0

    # 计算各项指标
    rsi_period, rsi = _get_dynamic_rsi(adx, last_row)
    trend = _analyze_trend(price, ema20, ema50)
    signal = _get_signal(adx, trend)
    rsi_status, rsi_overbought, rsi_oversold = _get_rsi_status(rsi, adx, trend)

    # 计算日涨跌幅
    prev_close = float(df.iloc[-2]['Close'])
    change_percent = ((price - prev_close) / prev_close) * 100

    # 周线分析
    weekly_status = _get_weekly_status(price, df_weekly)

    # K线数据 (日线和周线)
    candles = _build_candles(df, rsi_period)
    weekly_candles = _build_candles(df_weekly, rsi_period=14)

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
        "weekly_candles": weekly_candles,
        **weekly_status
    }


# ============================================
# 批量获取与摘要分析
# ============================================

def batch_fetch_and_update(symbols: list) -> dict:
    """
    批量获取股票数据并计算指标

    对缓存过期的 symbols 使用 yf.download 一次性下载，
    缓存有效且含指标的直接从 Parquet 读取。

    Args:
        symbols: 股票代码列表

    Returns:
        {symbol: (df, df_weekly)} 字典
    """
    symbols = [s.upper() for s in symbols]
    now = datetime.now()
    results = {}
    symbols_to_fetch = []

    # 1. 筛选：哪些需要下载，哪些可以直接用缓存
    for symbol in symbols:
        file_path = os.path.join(DATA_DIR, f"{symbol}.parquet")
        df_local, last_update = _load_local_data(file_path, symbol)

        cache_valid = False
        if df_local is not None and last_update is not None:
            if os.path.exists(file_path):
                file_mod_time = os.path.getmtime(file_path)
                if time.time() - file_mod_time < CACHE_DURATION_SECONDS:
                    cache_valid = True

        if cache_valid and df_local is not None and 'EMA20' in df_local.columns and 'EMA5' in df_local.columns:
            # 缓存有效且含指标，直接使用
            df_weekly = _calculate_weekly_indicators(df_local)
            results[symbol] = (df_local, df_weekly)
        else:
            symbols_to_fetch.append((symbol, df_local, last_update))

    if not symbols_to_fetch:
        return results

    # 2. 确定批量下载的起始日期（增量拉取）
    #    有本地数据的用最早的 last_update 做增量；全新 symbol 才拉全量
    fetch_symbols = [s for s, _, _ in symbols_to_fetch]
    logger.info(f"批量下载 {len(fetch_symbols)} 只股票: {fetch_symbols}")

    earliest_update = None
    has_new_symbol = False
    for _, df_local, last_update in symbols_to_fetch:
        if df_local is None or last_update is None:
            has_new_symbol = True
            break
        if earliest_update is None or last_update < earliest_update:
            earliest_update = last_update

    if has_new_symbol or earliest_update is None:
        fetch_start = now - timedelta(days=DATA_RETENTION_DAYS)
    else:
        fetch_start = earliest_update
        logger.info(f"增量下载，起始日期: {fetch_start.strftime('%Y-%m-%d')}")

    downloaded_data = {}
    with global_download_lock:
        try:
            start_time = time.time()
            logger.info(f"开始下载 {len(fetch_symbols)} 只股票: {fetch_symbols}")
            raw = yf.download(
                fetch_symbols,
                start=fetch_start,
                end=now,
                interval="1d",
                group_by="ticker",
                threads=True,
            )
            end_time = time.time()
            logger.info(f"下载完成，耗时: {end_time - start_time:.2f} 秒")
            if raw is not None and not raw.empty:
                if len(fetch_symbols) == 1:
                    downloaded_data[fetch_symbols[0]] = raw
                else:
                    for sym in fetch_symbols:
                        try:
                            sym_df = raw[sym].dropna(how='all')
                            if not sym_df.empty:
                                downloaded_data[sym] = sym_df
                        except (KeyError, Exception):
                            pass
        except Exception as e:
            logger.error(f"批量下载失败: {e}")

    # 3. 逐个合并、计算指标、保存
    for symbol, df_local, last_update in symbols_to_fetch:
        file_path = os.path.join(DATA_DIR, f"{symbol}.parquet")
        df = df_local

        if symbol in downloaded_data:
            new_df = downloaded_data[symbol]
            # 移除时区信息
            if hasattr(new_df.index, 'tz') and new_df.index.tz is not None:
                new_df.index = new_df.index.tz_localize(None)
            # 处理 MultiIndex 列
            if isinstance(new_df.columns, pd.MultiIndex):
                new_df.columns = new_df.columns.get_level_values(0)

            # 合并前去掉旧的指标列
            if df is not None:
                ohlcv_cols = [c for c in df.columns if c in ('Open', 'High', 'Low', 'Close', 'Volume')]
                df = df[ohlcv_cols]
            df = _merge_and_clean_data(df, new_df, now)

        if df is None or df.empty:
            continue

        df = _calculate_daily_indicators(df)

        with get_symbol_lock(symbol):
            df.to_parquet(file_path)

        df_weekly = _calculate_weekly_indicators(df)
        results[symbol] = (df, df_weekly)

    return results


def analyze_stock_summary(symbol: str, df: pd.DataFrame, df_weekly: pd.DataFrame) -> Optional[dict]:
    """
    生成列表页所需的股票摘要数据（不含 candles）

    Args:
        symbol: 股票代码
        df: 含指标的日线 DataFrame
        df_weekly: 含指标的周线 DataFrame

    Returns:
        摘要字典，或 None
    """
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
        "candles": [],
        "weekly_candles": [],
        **weekly_status
    }
