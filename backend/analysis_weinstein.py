"""Weinstein stage view for the watchlist: stage, 30-week MA, relative strength,
Bollinger state and volume ratio, computed from the cached weekly frame.

Stage 2 = close above a rising 30-week SMA, stage 4 = close below a falling
SMA. A close below a still-rising SMA reads as stage 3 (the advance is
loosening) and a close above a still-falling SMA as stage 1 (the decline is
repairing). A flat SMA (|4-week change| < 0.4%) is stage 1 after a decline
and stage 3 after an advance. These are viewing aids: the frozen research
(xquant ``weinstein-summary-2026-10-18``) found the mechanical rules do not
beat buy-and-hold on A-shares.
"""
from __future__ import annotations

import os
from typing import Optional

import numpy as np
import pandas as pd

from analysis_constants import DATA_DIR

MA_WEEKS = 30
SLOPE_LAG_WEEKS = 4
FLAT_SLOPE = 0.004
RS_WEEKS = 26
SQUEEZE_LOOKBACK = 8
SQUEEZE_RATIO = 0.8
VOLUME_LOOKBACK = 10

STAGE_LABELS = {1: "筑底", 2: "上涨", 3: "做顶", 4: "下跌"}


def benchmark_for(symbol: str) -> Optional[str]:
    """Market benchmark used for relative strength; None when there is none."""
    upper = symbol.upper()
    if upper.endswith((".SS", ".SZ")):
        return "000300.SS"
    if upper.endswith(".HK"):
        return "2800.HK"
    if upper.endswith("-USD") or upper.startswith("^") or "=" in upper:
        return None
    return "SPY"


def stage_series(close: pd.Series, ma30: pd.Series) -> pd.Series:
    """Stage per week; NaN until the average and its 4-week change exist."""
    slope = ma30 / ma30.shift(SLOPE_LAG_WEEKS) - 1
    stages = []
    prev = 1
    for c, m, s in zip(close.to_numpy(), ma30.to_numpy(), slope.to_numpy()):
        if not np.isfinite(m) or not np.isfinite(s):
            stages.append(np.nan)
            continue
        if abs(s) < FLAT_SLOPE:
            stage = 3 if prev in (2, 3) else 1
        elif s > 0:
            # below a still-rising average: the advance is loosening
            stage = 2 if c > m else 3
        else:
            # above a still-falling average: the decline is repairing
            stage = 4 if c < m else 1
        stages.append(stage)
        prev = stage
    return pd.Series(stages, index=close.index, dtype=float)


_BENCH_CACHE: dict[str, tuple[float, pd.Series]] = {}


def _benchmark_weekly_close(benchmark: str) -> Optional[pd.Series]:
    """Weekly closes from the cached parquet, reloaded only when the file changes."""
    path = os.path.join(DATA_DIR, f"{benchmark}_weekly.parquet")
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    cached = _BENCH_CACHE.get(benchmark)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        frame = pd.read_parquet(path, columns=["Close"])
    except Exception:
        return None
    close = _naive(frame["Close"].astype(float))
    _BENCH_CACHE[benchmark] = (mtime, close)
    return close


def _naive(series: pd.Series) -> pd.Series:
    index = pd.DatetimeIndex(series.index)
    if index.tz is not None:
        series = series.copy()
        series.index = index.tz_localize(None)
    return series


def relative_strength(close: pd.Series, bench_close: Optional[pd.Series]) -> Optional[pd.Series]:
    """26-week return minus the benchmark's 26-week return, aligned by week label."""
    if bench_close is None or bench_close.empty:
        return None
    own = _naive(close)
    bench = bench_close.reindex(own.index).ffill()
    rs = own / own.shift(RS_WEEKS) - (bench / bench.shift(RS_WEEKS))
    return rs


def add_view_columns(symbol: str, df_weekly: pd.DataFrame) -> pd.DataFrame:
    """Copy of the weekly frame with MA30 (if missing), Stage and RS26 columns."""
    frame = df_weekly.copy()
    close = frame["Close"].astype(float)
    if "MA30" not in frame.columns:
        frame["MA30"] = close.rolling(MA_WEEKS).mean()
    frame["Stage"] = stage_series(close, frame["MA30"].astype(float))
    benchmark = benchmark_for(symbol)
    if benchmark is not None:
        if benchmark == symbol.upper():
            frame["RS26"] = 0.0
        else:
            rs = relative_strength(close, _benchmark_weekly_close(benchmark))
            if rs is not None:
                frame["RS26"] = rs.to_numpy()
    return frame


def _finite(value) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def weinstein_summary(symbol: str, df_weekly: Optional[pd.DataFrame]) -> Optional[dict]:
    """Latest-week view fields for the watchlist row."""
    if df_weekly is None or len(df_weekly) < MA_WEEKS + SLOPE_LAG_WEEKS:
        return None
    frame = add_view_columns(symbol, df_weekly)
    last = frame.iloc[-1]
    stage = _finite(last.get("Stage"))
    if stage is None:
        return None
    stage = int(stage)
    weeks_in_stage = 0
    for value in reversed(frame["Stage"].to_numpy()):
        if value != stage:
            break
        weeks_in_stage += 1

    ma30 = _finite(last.get("MA30"))
    close = _finite(last.get("Close"))
    lag = frame["MA30"].iloc[-1 - SLOPE_LAG_WEEKS] if len(frame) > SLOPE_LAG_WEEKS else np.nan
    slope = _finite(ma30 / lag - 1) if ma30 and _finite(lag) else None

    bb_state = "none"
    upper, lower, mid = (_finite(last.get(k)) for k in ("BOLL_Upper", "BOLL_Lower", "BOLL_Mid"))
    if upper is not None and lower is not None and mid:
        width = (frame["BOLL_Upper"] - frame["BOLL_Lower"]) / frame["BOLL_Mid"]
        recent = width.iloc[-1 - SQUEEZE_LOOKBACK:-1]
        squeezed = bool(len(recent) and (recent < SQUEEZE_RATIO * recent.mean()).any())
        if close is not None and close > upper:
            bb_state = "squeeze_breakout" if squeezed else "above_upper"
        elif _finite(width.iloc[-1]) is not None and len(recent) and width.iloc[-1] < SQUEEZE_RATIO * recent.mean():
            bb_state = "squeeze"

    volume_ratio = None
    if "Volume" in frame.columns and len(frame) > VOLUME_LOOKBACK:
        prior = frame["Volume"].iloc[-1 - VOLUME_LOOKBACK:-1].astype(float).mean()
        volume_ratio = _finite(float(last["Volume"]) / prior) if prior else None

    rs = _finite(last.get("RS26")) if "RS26" in frame.columns else None
    week_label = pd.Timestamp(frame.index[-1])
    return {
        "stage": stage,
        "stageLabel": STAGE_LABELS[stage],
        "weeksInStage": weeks_in_stage,
        "ma30": ma30,
        "ma30Distance": _finite(close / ma30 - 1) if close and ma30 else None,
        "ma30Slope": slope,
        "rs26": rs,
        "rsBenchmark": benchmark_for(symbol),
        "bbState": bb_state,
        "volumeRatio": volume_ratio,
        "weekLabel": week_label.strftime("%Y-%m-%d"),
    }
