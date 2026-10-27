"""Weinstein stage view for the watchlist: stage, 30-week MA, relative strength,
Bollinger state and volume ratio, computed from the cached weekly frame.

Stage 2 = close above a rising 30-week SMA, stage 4 = close below a falling
SMA. A close below a still-rising SMA reads as stage 3 (the advance is
loosening) and a close above a still-falling SMA as stage 1 (the decline is
repairing). A flat SMA (|4-week change| < 0.4%) is stage 1 after a decline
and stage 3 after an advance. A close within 2% of the SMA keeps the previous
stage (Weinstein: ignore minor penetrations), so a price hugging the line does
not flip the stage every week. These are viewing aids: the frozen research
(xquant ``weinstein-summary-2026-10-18``) found the mechanical rules do not
beat buy-and-hold on A-shares.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from analysis_constants import DATA_DIR
from analysis_divergence import filter_completed_weekly_bars, is_daily_session_complete

MA_WEEKS = 30
SLOPE_LAG_WEEKS = 4
FLAT_SLOPE = 0.004
STAGE_BAND = 0.02
RS_WEEKS = 26
SQUEEZE_LOOKBACK = 8
SQUEEZE_RATIO = 0.8
VOLUME_LOOKBACK = 10

STAGE_LABELS = {1: "筑底", 2: "上涨", 3: "做顶", 4: "下跌"}


# A-share listed ETFs that track another market or a commodity: comparing them
# with CSI 300 says nothing about the asset, so they get their home benchmark or none.
_CROSS_MARKET_BENCHMARKS: dict[str, Optional[str]] = {
    # gold, silver, soybean meal
    **dict.fromkeys(("518880.SS", "518800.SS", "159934.SZ", "159937.SZ", "161226.SZ", "159985.SZ"), None),
    # US, Japan, Germany
    **dict.fromkeys(("513100.SS", "513300.SS", "159941.SZ", "513500.SS", "513520.SS", "513030.SS"), None),
    # Hong Kong
    **dict.fromkeys(("513120.SS", "513910.SS", "513180.SS", "513010.SS", "513130.SS", "513060.SS",
                     "513050.SS", "159920.SZ"), "2800.HK"),
}


def benchmark_for(symbol: str) -> Optional[str]:
    """Market benchmark used for relative strength; None when there is none."""
    upper = symbol.upper()
    if upper in _CROSS_MARKET_BENCHMARKS:
        return _CROSS_MARKET_BENCHMARKS[upper]
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
        near = abs(c / m - 1) <= STAGE_BAND
        if abs(s) < FLAT_SLOPE:
            stage = 3 if prev in (2, 3) else 1
        elif s > 0:
            # below a still-rising average: the advance is loosening
            stage = prev if near and prev in (2, 3) else (2 if c > m else 3)
        else:
            # above a still-falling average: the decline is repairing
            stage = prev if near and prev in (1, 4) else (4 if c < m else 1)
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


def _completed_week_cutoff(symbol: str, now: Optional[datetime] = None) -> Optional[pd.Timestamp]:
    """Latest Sunday week label whose sessions have all closed in the symbol's market."""
    today = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("Asia/Shanghai")).date()
    for back in range(4):
        session = pd.Timestamp(today) - pd.Timedelta(days=back)
        if is_daily_session_complete(symbol, session, now=now):
            break
    else:
        return None
    this_week = session + pd.Timedelta(days=(6 - session.weekday()) % 7)
    probe = pd.DataFrame({"Close": [0.0, 0.0]}, index=[this_week - pd.Timedelta(days=7), this_week])
    kept = filter_completed_weekly_bars(symbol, probe, session)
    return pd.Timestamp(kept.index[-1]) if not kept.empty else None


def completion_key(now: Optional[datetime] = None) -> tuple:
    """Changes whenever a market's current week closes; used to key cached scans."""
    return tuple(_completed_week_cutoff(s, now) for s in ("000300.SS", "SPY", "BTC-USD", "2800.HK", "GC=F"))


def _row_view(symbol: str, frame: pd.DataFrame, pos: int) -> Optional[dict]:
    """Stage view for the weekly row at ``pos`` using only rows up to it."""
    row = frame.iloc[pos]
    stage = _finite(row.get("Stage"))
    if stage is None:
        return None
    stage = int(stage)
    stages = frame["Stage"].to_numpy()[: pos + 1]
    weeks_in_stage = 0
    for value in reversed(stages):
        if value != stage:
            break
        weeks_in_stage += 1

    ma30 = _finite(row.get("MA30"))
    close = _finite(row.get("Close"))
    lag = frame["MA30"].iloc[pos - SLOPE_LAG_WEEKS] if pos >= SLOPE_LAG_WEEKS else np.nan
    slope = _finite(ma30 / lag - 1) if ma30 and _finite(lag) else None

    bb_state = "none"
    upper, lower, mid = (_finite(row.get(k)) for k in ("BOLL_Upper", "BOLL_Lower", "BOLL_Mid"))
    if upper is not None and lower is not None and mid:
        width = ((frame["BOLL_Upper"] - frame["BOLL_Lower"]) / frame["BOLL_Mid"]).iloc[: pos + 1]
        recent = width.iloc[-1 - SQUEEZE_LOOKBACK:-1]
        squeezed = bool(len(recent) and (recent < SQUEEZE_RATIO * recent.mean()).any())
        if close is not None and close > upper:
            bb_state = "squeeze_breakout" if squeezed else "above_upper"
        elif _finite(width.iloc[-1]) is not None and len(recent) and width.iloc[-1] < SQUEEZE_RATIO * recent.mean():
            bb_state = "squeeze"

    volume_ratio = None
    if "Volume" in frame.columns and pos >= VOLUME_LOOKBACK:
        prior = frame["Volume"].iloc[pos - VOLUME_LOOKBACK:pos].astype(float).mean()
        volume_ratio = _finite(float(row["Volume"]) / prior) if prior else None

    previous = _finite(stages[-2]) if len(stages) > 1 else None
    view = {
        "stage": stage,
        "stageLabel": STAGE_LABELS[stage],
        "weeksInStage": weeks_in_stage,
        "previousStage": int(previous) if previous is not None else None,
        "close": close,
        "ma30": ma30,
        "ma30Distance": _finite(close / ma30 - 1) if close and ma30 else None,
        "ma30Slope": slope,
        "rs26": _finite(row.get("RS26")) if "RS26" in frame.columns else None,
        "rsBenchmark": benchmark_for(symbol),
        "bbState": bb_state,
        "bandPosition": _finite((close - lower) / (upper - lower)) if close is not None and upper and lower is not None and upper > lower else None,
        "volumeRatio": volume_ratio,
        "weekLabel": pd.Timestamp(frame.index[pos]).strftime("%Y-%m-%d"),
    }
    view["rule"] = rule_state(view)
    return view


# Stage reached by a close above ("up") or below ("down") the line, by the
# direction of the 30-week average once that close is included.
_LEVEL_OUTCOMES = {(True, "up"): 2, (True, "down"): 3, (False, "up"): 1, (False, "down"): 4}


def stage_levels(closes: pd.Series, prev_stage: int, price: Optional[float],
                 weekly_move: Optional[float]) -> list[dict]:
    """Next weekly closes that would change the stage, measured from ``price``
    (the last closed week's close, so the distance does not drift intraday).

    ``closes`` are completed weekly closes; the next week's close is the unknown.
    Because the 30-week average includes that close, the line is solved exactly:
    a close ``x`` sits on the band line when ``x = k * (s29 + x) / 30`` with ``s29``
    the previous 29 closes and ``k`` 1 +/- 2%, i.e. ``x = k * s29 / (30 - k)``. The
    band only applies while the previous stage belongs to the average's direction
    (2/3 when rising, 1/4 when falling), mirroring ``stage_series``. A line whose
    close would leave the average flat, or turn its direction, is dropped: there
    the stage depends on the slope, not on a price.
    """
    closes = closes.astype(float)
    if not price or len(closes) < MA_WEEKS + SLOPE_LAG_WEEKS - 1:
        return []
    s29 = float(closes.iloc[-(MA_WEEKS - 1):].sum())
    lag = float(closes.rolling(MA_WEEKS).mean().iloc[-SLOPE_LAG_WEEKS])
    if not np.isfinite(lag) or lag <= 0:
        return []
    levels = []
    for side, sign in (("up", 1), ("down", -1)):
        for rising in (True, False):
            band = STAGE_BAND if prev_stage in ((2, 3) if rising else (1, 4)) else 0.0
            k = 1 + sign * band
            line = k * s29 / (MA_WEEKS - k)
            slope = (s29 + line) / MA_WEEKS / lag - 1
            if abs(slope) < FLAT_SLOPE or (slope > 0) != rising:
                continue
            becomes = _LEVEL_OUTCOMES[(rising, side)]
            if becomes != prev_stage:
                change = line / price - 1
                levels.append({
                    "side": "above" if side == "up" else "below",
                    "price": line,
                    "change": change,
                    "typicalMoves": abs(change) / weekly_move if weekly_move else None,
                    "becomes": becomes,
                    "ruleSource": "weinstein_weekly_close",
                })
            break
    return levels


def weinstein_summary(symbol: str, df_weekly: Optional[pd.DataFrame], now: Optional[datetime] = None) -> Optional[dict]:
    """Latest-week view fields for the watchlist row.

    Top-level fields describe the newest row, which may be a week still in
    progress (``weekComplete``). ``closed`` is the same view for the last week
    whose sessions have all closed: stage calls and rule states should use it.
    ``levels`` are the next weekly closes that would change the closed stage,
    solved against the 30-week average that close itself moves; ``change`` and
    ``typicalMoves`` are measured from the closed week's close, ``changeNow``
    from the latest close.
    """
    if df_weekly is None or len(df_weekly) < MA_WEEKS + SLOPE_LAG_WEEKS:
        return None
    frame = add_view_columns(symbol, df_weekly).dropna(subset=["Close"])
    view = _row_view(symbol, frame, len(frame) - 1)
    if view is None:
        return None
    cutoff = _completed_week_cutoff(symbol, now)
    labels = pd.DatetimeIndex(frame.index).tz_localize(None) if frame.index.tz is not None else pd.DatetimeIndex(frame.index)
    closed_count = int((labels <= cutoff).sum()) if cutoff is not None else len(frame) - 1
    complete = closed_count == len(frame)
    closed = view if complete else (_row_view(symbol, frame, closed_count - 1) if closed_count else None)

    closed_closes = frame["Close"].iloc[:closed_count].astype(float)
    weekly_move = _finite(closed_closes.pct_change().tail(20).std())
    view.pop("previousStage")
    return {
        **view,
        "weekComplete": complete,
        "closed": closed,
        "typicalWeeklyMove": weekly_move,
        "levels": _with_live_change(
            stage_levels(closed_closes, closed["stage"], closed["close"], weekly_move) if closed else [],
            view["close"],
        ),
    }


def _with_live_change(levels: list[dict], live_close: Optional[float]) -> list[dict]:
    """Add the drifting distance from the latest (possibly intraday) close."""
    for level in levels:
        level["changeNow"] = level["price"] / live_close - 1 if live_close else None
    return levels


def live_session(symbol: str, as_of, now: Optional[datetime] = None) -> dict:
    """Date of the newest daily bar and whether its session has closed."""
    if as_of is None:
        return {"asOf": None, "sessionComplete": None}
    return {
        "asOf": pd.Timestamp(as_of).strftime("%Y-%m-%d"),
        "sessionComplete": is_daily_session_complete(symbol, as_of, now=now),
    }


def rule_state(view: Optional[dict]) -> dict:
    """What the plain Weinstein rule says now (mirrors frontend ruleState).

    Buy on a fresh stage 2 (first 4 weeks) with non-negative relative strength;
    sell when the stage turns 3 with the close below the 30-week average.
    """
    if not view:
        return {"key": "wait", "label": "数据不足"}
    below = view.get("ma30Distance") is not None and view["ma30Distance"] < 0
    stage = view.get("stage")
    if stage == 2:
        rs = view.get("rs26")
        if view.get("weeksInStage", 99) <= 4 and (rs is None or rs > 0):
            return {"key": "entry", "label": "新进第二阶段"}
        return {"key": "hold", "label": "持有"}
    if stage == 3:
        return {"key": "exit", "label": "跌破 30 周线"} if below else {"key": "caution", "label": "涨势松动"}
    if stage == 4:
        return {"key": "out", "label": "不持有"}
    return {"key": "wait", "label": "观望"}


def weinstein_scan_item(symbol: str, df_weekly: Optional[pd.DataFrame], weeks: int = 52,
                        now: Optional[datetime] = None) -> Optional[dict]:
    """Summary plus last-week stage and a short weekly history for the scan page."""
    summary = weinstein_summary(symbol, df_weekly, now=now)
    if summary is None:
        return None
    frame = add_view_columns(symbol, df_weekly).dropna(subset=["Close"])
    stages = frame["Stage"].to_numpy()
    previous = _finite(stages[-2]) if len(stages) > 1 else None
    history = []
    for ts, row in frame.tail(weeks).iterrows():
        history.append({
            "time": pd.Timestamp(ts).date().isoformat(),
            "close": float(row["Close"]),
            "ma30": _finite(row.get("MA30")),
            "stage": int(row["Stage"]) if _finite(row.get("Stage")) is not None else None,
        })
    return {
        **summary,
        "previousStage": int(previous) if previous is not None else None,
        "close": _finite(frame["Close"].iloc[-1]),
        "history": history,
    }
