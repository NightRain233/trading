"""Lookahead-safe ordinary MACD divergence detection.

Only confirmed price pivots can influence decisions. Candidate pivots are exposed
for display, but are explicitly non-actionable and may disappear as new bars arrive.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as datetime_time, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

from analysis_constants import (
    MACD_DIVERGENCE_DAILY_ATR_MULTIPLIER,
    MACD_DIVERGENCE_DAILY_DIF_ALIGNMENT,
    MACD_DIVERGENCE_DAILY_DIF_NORMALIZED,
    MACD_DIVERGENCE_DAILY_LEFT,
    MACD_DIVERGENCE_DAILY_MAX_GAP,
    MACD_DIVERGENCE_DAILY_MIN_GAP,
    MACD_DIVERGENCE_DAILY_PRICE_PCT,
    MACD_DIVERGENCE_DAILY_RIGHT,
    MACD_DIVERGENCE_DAILY_TTL,
    MACD_DIVERGENCE_WEEKLY_ATR_MULTIPLIER,
    MACD_DIVERGENCE_WEEKLY_DIF_ALIGNMENT,
    MACD_DIVERGENCE_WEEKLY_DIF_NORMALIZED,
    MACD_DIVERGENCE_WEEKLY_LEFT,
    MACD_DIVERGENCE_WEEKLY_MAX_GAP,
    MACD_DIVERGENCE_WEEKLY_MIN_GAP,
    MACD_DIVERGENCE_WEEKLY_PRICE_PCT,
    MACD_DIVERGENCE_WEEKLY_RIGHT,
    MACD_DIVERGENCE_WEEKLY_TTL,
)


@dataclass(frozen=True)
class DivergenceConfig:
    left: int
    right: int
    min_gap: int
    max_gap: int
    ttl: int
    min_price_pct: float
    atr_multiplier: float
    min_dif_normalized: float
    dif_alignment: int


DAILY_CONFIG = DivergenceConfig(
    left=MACD_DIVERGENCE_DAILY_LEFT,
    right=MACD_DIVERGENCE_DAILY_RIGHT,
    min_gap=MACD_DIVERGENCE_DAILY_MIN_GAP,
    max_gap=MACD_DIVERGENCE_DAILY_MAX_GAP,
    ttl=MACD_DIVERGENCE_DAILY_TTL,
    min_price_pct=MACD_DIVERGENCE_DAILY_PRICE_PCT,
    atr_multiplier=MACD_DIVERGENCE_DAILY_ATR_MULTIPLIER,
    min_dif_normalized=MACD_DIVERGENCE_DAILY_DIF_NORMALIZED,
    dif_alignment=MACD_DIVERGENCE_DAILY_DIF_ALIGNMENT,
)

WEEKLY_CONFIG = DivergenceConfig(
    left=MACD_DIVERGENCE_WEEKLY_LEFT,
    right=MACD_DIVERGENCE_WEEKLY_RIGHT,
    min_gap=MACD_DIVERGENCE_WEEKLY_MIN_GAP,
    max_gap=MACD_DIVERGENCE_WEEKLY_MAX_GAP,
    ttl=MACD_DIVERGENCE_WEEKLY_TTL,
    min_price_pct=MACD_DIVERGENCE_WEEKLY_PRICE_PCT,
    atr_multiplier=MACD_DIVERGENCE_WEEKLY_ATR_MULTIPLIER,
    min_dif_normalized=MACD_DIVERGENCE_WEEKLY_DIF_NORMALIZED,
    dif_alignment=MACD_DIVERGENCE_WEEKLY_DIF_ALIGNMENT,
)


def _iso_date(value) -> str:
    return pd.Timestamp(value).date().isoformat()


def _is_crypto_symbol(symbol: str) -> bool:
    normalized = symbol.upper()
    return normalized.endswith("-USD") and normalized not in {"GC=F", "CL=F"}


def is_daily_session_complete(
    symbol: str,
    as_of,
    now: Optional[datetime] = None,
) -> Optional[bool]:
    """Return whether ``as_of`` belongs to a completed market session."""
    if as_of is None:
        return None
    try:
        session_date = pd.Timestamp(as_of).date()
    except (TypeError, ValueError):
        return None

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo("Asia/Shanghai"))

    normalized = symbol.strip().upper()
    if _is_crypto_symbol(normalized):
        utc_now = current.astimezone(timezone.utc)
        return session_date < utc_now.date()

    if normalized.endswith((".SS", ".SZ")):
        local_now = current.astimezone(ZoneInfo("Asia/Shanghai"))
        close_cutoff = datetime_time(15, 10)
    else:
        local_now = current.astimezone(ZoneInfo("America/New_York"))
        close_cutoff = (
            datetime_time(17, 10)
            if normalized.endswith("=F")
            else datetime_time(16, 10)
        )

    if session_date < local_now.date():
        return True
    if session_date > local_now.date():
        return False
    return local_now.time().replace(tzinfo=None) >= close_cutoff


def filter_completed_daily_bars(
    symbol: str,
    daily: Optional[pd.DataFrame],
    now: Optional[datetime] = None,
) -> pd.DataFrame:
    """Exclude a trailing daily bar until its market session has closed."""
    if daily is None or daily.empty:
        return pd.DataFrame() if daily is None else daily.iloc[0:0].copy()

    result = daily.sort_index().copy()
    if is_daily_session_complete(symbol, result.index[-1], now=now) is False:
        result = result.iloc[:-1]
    return result


def filter_completed_weekly_bars(
    symbol: str,
    weekly: Optional[pd.DataFrame],
    as_of,
) -> pd.DataFrame:
    """Exclude a provisional current weekly bar.

    Production weekly parquet files use Sunday labels. Exchange-traded weeks are
    considered complete after Friday's completed daily bar; crypto weeks complete
    on Sunday. A Thursday holiday close is handled conservatively on the next bar.
    """
    if weekly is None or weekly.empty or as_of is None:
        return pd.DataFrame() if weekly is None else weekly.iloc[0:0].copy()

    result = weekly.sort_index().copy()
    index = pd.DatetimeIndex(result.index)
    if index.tz is not None:
        index = index.tz_localize(None)
        result.index = index
    as_of_ts = pd.Timestamp(as_of)
    if as_of_ts.tzinfo is not None:
        as_of_ts = as_of_ts.tz_localize(None)
    as_of_ts = as_of_ts.normalize()

    label_weekday = int(pd.Series(index.weekday).mode().iloc[0])
    if label_weekday == 4:  # W-FRI data
        days_since_friday = (as_of_ts.weekday() - 4) % 7
        cutoff = as_of_ts - pd.Timedelta(days=days_since_friday)
    elif _is_crypto_symbol(symbol):
        days_since_sunday = (as_of_ts.weekday() - 6) % 7
        cutoff = as_of_ts - pd.Timedelta(days=days_since_sunday)
    elif as_of_ts.weekday() >= 4:
        cutoff = as_of_ts + pd.Timedelta(days=6 - as_of_ts.weekday())
    else:
        cutoff = as_of_ts - pd.Timedelta(days=as_of_ts.weekday() + 1)
    return result.loc[result.index <= cutoff]


def _prepare_frame(frame: Optional[pd.DataFrame]) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    required = {"High", "Low", "Close", "MACD_DIF"}
    if not required.issubset(frame.columns):
        return pd.DataFrame()
    result = frame.sort_index().copy()
    for column in required | {"MACD_Hist", "ATR"}:
        if column in result.columns:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    return result.dropna(subset=sorted(required))


def _is_unique_extreme(values: pd.Series, center: float, kind: str) -> bool:
    extreme = values.max() if kind == "bearish" else values.min()
    return bool(center == extreme and int((values == extreme).sum()) == 1)


def _confirmed_pivots(
    frame: pd.DataFrame, kind: str, config: DivergenceConfig
) -> list[int]:
    column = "High" if kind == "bearish" else "Low"
    pivots = []
    for position in range(config.left, len(frame) - config.right):
        window = frame[column].iloc[
            position - config.left : position + config.right + 1
        ]
        if _is_unique_extreme(window, float(frame[column].iloc[position]), kind):
            pivots.append(position)
    return pivots


def _candidate_pivots(
    frame: pd.DataFrame, kind: str, config: DivergenceConfig
) -> list[int]:
    column = "High" if kind == "bearish" else "Low"
    first_unconfirmed = max(config.left, len(frame) - config.right)
    pivots = []
    for position in range(first_unconfirmed, len(frame)):
        window = frame[column].iloc[position - config.left :]
        if _is_unique_extreme(window, float(frame[column].iloc[position]), kind):
            pivots.append(position)
    return pivots


def _nearest_prior_pivot(
    pivots: list[int], second: int, config: DivergenceConfig
) -> Optional[int]:
    eligible = [
        position
        for position in pivots
        if config.min_gap <= second - position <= config.max_gap
    ]
    return max(eligible) if eligible else None


def _indicator_extreme(
    frame: pd.DataFrame,
    position: int,
    kind: str,
    alignment: int,
) -> tuple[int, float, Optional[float]]:
    start = max(0, position - alignment)
    end = min(len(frame), position + alignment + 1)
    dif_window = frame["MACD_DIF"].iloc[start:end]
    label = dif_window.idxmax() if kind == "bearish" else dif_window.idxmin()
    dif_position = int(frame.index.get_loc(label))
    hist = None
    if "MACD_Hist" in frame.columns:
        value = frame["MACD_Hist"].iloc[dif_position]
        hist = float(value) if pd.notna(value) else None
    return dif_position, float(frame["MACD_DIF"].iloc[dif_position]), hist


def _build_signal(
    frame: pd.DataFrame,
    first: int,
    second: int,
    kind: str,
    timeframe: str,
    status: str,
    config: DivergenceConfig,
) -> Optional[dict]:
    price_column = "High" if kind == "bearish" else "Low"
    first_price = float(frame[price_column].iloc[first])
    second_price = float(frame[price_column].iloc[second])
    atr = None
    if "ATR" in frame.columns and pd.notna(frame["ATR"].iloc[second]):
        atr = abs(float(frame["ATR"].iloc[second]))
    price_threshold = abs(first_price) * config.min_price_pct
    if atr is not None:
        price_threshold = max(price_threshold, atr * config.atr_multiplier)
    price_difference = second_price - first_price
    if kind == "bearish" and price_difference < price_threshold:
        return None
    if kind == "bullish" and price_difference > -price_threshold:
        return None

    first_dif_pos, first_dif, first_hist = _indicator_extreme(
        frame, first, kind, config.dif_alignment
    )
    second_dif_pos, second_dif, second_hist = _indicator_extreme(
        frame, second, kind, config.dif_alignment
    )
    first_normalized = first_dif / abs(first_price) if first_price else 0.0
    second_normalized = second_dif / abs(second_price) if second_price else 0.0
    dif_change = second_normalized - first_normalized
    if kind == "bearish" and dif_change > -config.min_dif_normalized:
        return None
    if kind == "bullish" and dif_change < config.min_dif_normalized:
        return None

    if first_hist is None or second_hist is None:
        histogram_confirms = None
    elif kind == "bearish":
        histogram_confirms = second_hist < first_hist
    else:
        histogram_confirms = second_hist > first_hist

    same_side_of_zero = (
        first_dif > 0 and second_dif > 0
        if kind == "bearish"
        else first_dif < 0 and second_dif < 0
    )
    confirmed_position = second + config.right if status == "confirmed" else None
    missing_right_bars = (
        max(0, second + config.right - (len(frame) - 1))
        if status == "candidate"
        else 0
    )
    return {
        "type": kind,
        "status": status,
        "timeframe": timeframe,
        "firstPivotDate": _iso_date(frame.index[first]),
        "secondPivotDate": _iso_date(frame.index[second]),
        "firstDifDate": _iso_date(frame.index[first_dif_pos]),
        "secondDifDate": _iso_date(frame.index[second_dif_pos]),
        "confirmedAt": (
            _iso_date(frame.index[confirmed_position])
            if confirmed_position is not None
            else None
        ),
        "priceChangePct": round(price_difference / abs(first_price) * 100, 4),
        "difChangeNormalizedPct": round(dif_change * 100, 6),
        "firstDif": first_dif,
        "secondDif": second_dif,
        "histogramConfirms": histogram_confirms,
        "zeroAxisContext": "same_side" if same_side_of_zero else "mixed",
        "confidence": (
            "strong" if same_side_of_zero and histogram_confirms is True else "standard"
        ),
        "missingRightBars": missing_right_bars,
        "expiresAfterBars": config.ttl,
        "decisionRole": (
            "display_only"
            if status == "candidate"
            else (
                "risk_warning_only"
                if kind == "bearish"
                else "wait_for_trend_confirmation"
            )
        ),
    }


def _detect_timeframe(
    frame: Optional[pd.DataFrame],
    timeframe: str,
    config: DivergenceConfig,
) -> dict:
    prepared = _prepare_frame(frame)
    result = {
        "asOf": _iso_date(prepared.index[-1]) if not prepared.empty else None,
        "confirmed": None,
        "candidate": None,
    }
    if len(prepared) < config.left + config.right + config.min_gap + 1:
        return result

    # Only the latest confirmed/candidate pivot can still be actionable. Keep
    # enough history for its TTL, its prior pivot's max gap, and both pivot
    # confirmation windows. Scanning the full multi-year parquet here made a
    # cold scan repeat thousands of Python-level iloc operations per symbol.
    recent_window = (
        config.max_gap + config.ttl + config.left + config.right + 1
    )
    if len(prepared) > recent_window:
        prepared = prepared.tail(recent_window)

    for kind in ("bearish", "bullish"):
        confirmed_pivots = _confirmed_pivots(prepared, kind, config)
        for second in reversed(confirmed_pivots):
            confirmed_position = second + config.right
            if len(prepared) - 1 - confirmed_position > config.ttl:
                continue
            first = _nearest_prior_pivot(confirmed_pivots, second, config)
            if first is None:
                continue
            signal = _build_signal(
                prepared, first, second, kind, timeframe, "confirmed", config
            )
            if signal is not None:
                current = result["confirmed"]
                if current is None or signal["confirmedAt"] > current["confirmedAt"]:
                    result["confirmed"] = signal
                break

        for second in reversed(_candidate_pivots(prepared, kind, config)):
            first = _nearest_prior_pivot(confirmed_pivots, second, config)
            if first is None:
                continue
            signal = _build_signal(
                prepared, first, second, kind, timeframe, "candidate", config
            )
            if signal is not None:
                current = result["candidate"]
                if current is None or signal["secondPivotDate"] > current["secondPivotDate"]:
                    result["candidate"] = signal
                break
    return result


def build_macd_divergence_summary(
    symbol: str,
    daily: Optional[pd.DataFrame],
    weekly: Optional[pd.DataFrame],
    now: Optional[datetime] = None,
) -> dict:
    completed_daily = filter_completed_daily_bars(symbol, daily, now=now)
    daily_prepared = _prepare_frame(completed_daily)
    daily_as_of = daily_prepared.index[-1] if not daily_prepared.empty else None
    completed_weekly = filter_completed_weekly_bars(symbol, weekly, daily_as_of)
    return {
        "daily": _detect_timeframe(daily_prepared, "daily", DAILY_CONFIG),
        "weekly": _detect_timeframe(completed_weekly, "weekly", WEEKLY_CONFIG),
        "policy": {
            "confirmedOnlyForDecision": True,
            "candidateDecisionRole": "display_only",
            "bullishDecisionRole": "wait_for_trend_confirmation",
            "bearishDecisionRole": "risk_warning_only",
        },
    }
