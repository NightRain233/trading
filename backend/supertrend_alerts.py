import math
from typing import Optional


NEAR_ST_PCT = 1.5
NEAR_ST_ATR = 0.5
FRESH_BULL_MAX_BARS = 5
EXTENDED_ST_PCT = 5.0
EXTENDED_ST_ATR = 2.0


def _finite_float(value: object) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _is_weekly_bullish(state: Optional[str]) -> bool:
    return state in ("bull", "bull_flip")


def _is_weekly_bearish(state: Optional[str]) -> bool:
    return state in ("bear", "bear_flip")


def _base_alert(
    *,
    alert_type: str,
    label: str,
    priority: str,
    actionable: bool,
    key_level_type: str,
    key_level_price: Optional[float],
    signed_pct: Optional[float],
    distance_pct: Optional[float],
    distance_atr: Optional[float],
    reason: str,
    action: str,
    opportunity_stage: str = "neutral",
    opportunity_label: str = "观察",
    opportunity_age_bars: Optional[int] = None,
    opportunity_reason: str = "当前没有明确的多头机会阶段",
) -> dict:
    return {
        "alertType": alert_type,
        "alertLabel": label,
        "alertPriority": priority,
        "isActionable": actionable,
        "keyLevelType": key_level_type,
        "keyLevelPrice": key_level_price,
        "signedDistanceToSupertrendPct": signed_pct,
        "distanceToSupertrendPct": distance_pct,
        "distanceToSupertrendAtr": distance_atr,
        "alertReason": reason,
        "suggestedAction": action,
        "opportunityStage": opportunity_stage,
        "opportunityLabel": opportunity_label,
        "opportunityAgeBars": opportunity_age_bars,
        "opportunityReason": opportunity_reason,
    }


def _normalize_age(value: object) -> Optional[int]:
    try:
        age = int(value)
    except (TypeError, ValueError):
        return None
    return age if age > 0 else None


def _opportunity_context(
    *,
    daily_bull: bool,
    daily_bear: bool,
    near_st: bool,
    distance_pct: Optional[float],
    distance_atr: Optional[float],
    trend_age_bars: object,
) -> dict:
    age = _normalize_age(trend_age_bars)

    if daily_bear:
        return {
            "opportunity_stage": "invalidated",
            "opportunity_label": "机会失效",
            "opportunity_age_bars": age,
            "opportunity_reason": "日线 SuperTrend 已转空，多头买入机会失效",
        }

    if not daily_bull:
        return {
            "opportunity_stage": "neutral",
            "opportunity_label": "观察",
            "opportunity_age_bars": age,
            "opportunity_reason": "当前没有明确的多头机会阶段",
        }

    if near_st:
        return {
            "opportunity_stage": "pullback_buy_zone",
            "opportunity_label": "回踩支撑",
            "opportunity_age_bars": age,
            "opportunity_reason": "价格仍贴近 SuperTrend 支撑，属于回踩观察区",
        }

    is_extended_by_pct = distance_pct is not None and distance_pct >= EXTENDED_ST_PCT
    is_extended_by_atr = distance_atr is not None and distance_atr >= EXTENDED_ST_ATR
    is_extended = is_extended_by_pct and is_extended_by_atr
    if is_extended:
        return {
            "opportunity_stage": "extended_from_entry",
            "opportunity_label": "已弹离买点",
            "opportunity_age_bars": age,
            "opportunity_reason": "价格已明显离开 SuperTrend 支撑，避免追高，等待下一次回踩",
        }

    if is_extended_by_atr or is_extended_by_pct:
        return {
            "opportunity_stage": "wait_pullback",
            "opportunity_label": "等待回踩",
            "opportunity_age_bars": age,
            "opportunity_reason": "趋势仍在，但价格已离开支撑区；等待下一次回踩确认",
        }

    if age is not None and age <= FRESH_BULL_MAX_BARS:
        return {
            "opportunity_stage": "fresh_bull",
            "opportunity_label": f"刚翻多 D{age}",
            "opportunity_age_bars": age,
            "opportunity_reason": "仍在翻多后的有效观察期，但入场仍需确认止损距离",
        }

    return {
        "opportunity_stage": "trend_watch",
        "opportunity_label": "延续观察",
        "opportunity_age_bars": age,
        "opportunity_reason": "多头趋势延续，但当前不是贴近支撑的买点",
    }


def classify_supertrend_alert(
    *,
    state: Optional[str],
    weekly_state: Optional[str],
    close: object,
    st_val: object,
    atr: object = None,
    just_flipped: bool = False,
    trend_age_bars: object = None,
) -> dict:
    """Convert SuperTrend state into a stable, UI/script-friendly alert."""
    price = _finite_float(close)
    supertrend = _finite_float(st_val)
    atr_value = _finite_float(atr)

    if price is None or price <= 0 or supertrend is None:
        return _base_alert(
            alert_type="none",
            label="无信号",
            priority="none",
            actionable=False,
            key_level_type="none",
            key_level_price=None,
            signed_pct=None,
            distance_pct=None,
            distance_atr=None,
            reason="价格或 SuperTrend 数据不足",
            action="等待下一次数据刷新",
            opportunity_stage="neutral",
            opportunity_label="数据不足",
            opportunity_age_bars=_normalize_age(trend_age_bars),
            opportunity_reason="价格或 SuperTrend 数据不足，暂不能判断机会阶段",
        )

    signed_pct = (price - supertrend) / price * 100
    distance_pct = abs(signed_pct)
    distance_atr = abs(price - supertrend) / atr_value if atr_value and atr_value > 0 else None
    near_st = distance_pct <= NEAR_ST_PCT or (distance_atr is not None and distance_atr <= NEAR_ST_ATR)
    weekly_bull = _is_weekly_bullish(weekly_state)
    weekly_bear = _is_weekly_bearish(weekly_state)

    daily_bull = state in ("bull", "bull_flip")
    daily_bear = state in ("bear", "bear_flip")
    key_level_type = "support" if daily_bull else "resistance" if daily_bear else "none"
    opportunity = _opportunity_context(
        daily_bull=daily_bull,
        daily_bear=daily_bear,
        near_st=near_st,
        distance_pct=distance_pct,
        distance_atr=distance_atr,
        trend_age_bars=trend_age_bars,
    )

    if state == "bull_flip" or (daily_bull and just_flipped):
        priority = "high" if weekly_bull else "medium"
        return _base_alert(
            alert_type="buy_candidate",
            label="买入候选",
            priority=priority,
            actionable=True,
            key_level_type="support",
            key_level_price=supertrend,
            signed_pct=signed_pct,
            distance_pct=distance_pct,
            distance_atr=distance_atr,
            reason="日线 SuperTrend 刚翻多" + ("，周线同向" if weekly_bull else ""),
            action="关注回踩不破支撑后的入场机会，避免追高",
            **opportunity,
        )

    if state == "bear_flip" or (daily_bear and just_flipped):
        priority = "high" if weekly_bear else "medium"
        return _base_alert(
            alert_type="sell_or_risk",
            label="卖出/风控",
            priority=priority,
            actionable=True,
            key_level_type="resistance",
            key_level_price=supertrend,
            signed_pct=signed_pct,
            distance_pct=distance_pct,
            distance_atr=distance_atr,
            reason="日线 SuperTrend 刚翻空" + ("，周线同向走弱" if weekly_bear else ""),
            action="检查持仓风控；若已跌破趋势线，优先减仓或离场",
            **opportunity,
        )

    if daily_bull and near_st:
        priority = "high" if weekly_bull else "medium"
        return _base_alert(
            alert_type="support_test",
            label="支撑回踩",
            priority=priority,
            actionable=True,
            key_level_type="support",
            key_level_price=supertrend,
            signed_pct=signed_pct,
            distance_pct=distance_pct,
            distance_atr=distance_atr,
            reason="多头趋势中价格接近 SuperTrend 支撑",
            action="等待收盘守住支撑；若跌破则按 SuperTrend 风控",
            **opportunity,
        )

    if daily_bear and near_st:
        return _base_alert(
            alert_type="resistance_test",
            label="阻力测试",
            priority="medium",
            actionable=True,
            key_level_type="resistance",
            key_level_price=supertrend,
            signed_pct=signed_pct,
            distance_pct=distance_pct,
            distance_atr=distance_atr,
            reason="空头趋势中价格接近 SuperTrend 阻力",
            action="观察能否有效突破；未突破前不急于做多",
            **opportunity,
        )

    if daily_bull:
        return _base_alert(
            alert_type="hold_bull",
            label="多头持有",
            priority="low",
            actionable=False,
            key_level_type=key_level_type,
            key_level_price=supertrend,
            signed_pct=signed_pct,
            distance_pct=distance_pct,
            distance_atr=distance_atr,
            reason="日线 SuperTrend 维持多头",
            action="持有观察，使用 SuperTrend 线作为动态风控位",
            **opportunity,
        )

    if daily_bear:
        return _base_alert(
            alert_type="avoid_bear",
            label="空头规避",
            priority="low",
            actionable=False,
            key_level_type=key_level_type,
            key_level_price=supertrend,
            signed_pct=signed_pct,
            distance_pct=distance_pct,
            distance_atr=distance_atr,
            reason="日线 SuperTrend 维持空头",
            action="等待翻多或突破阻力后再评估",
            **opportunity,
        )

    return _base_alert(
        alert_type="none",
        label="无信号",
        priority="none",
        actionable=False,
        key_level_type="none",
        key_level_price=supertrend,
        signed_pct=signed_pct,
        distance_pct=distance_pct,
        distance_atr=distance_atr,
        reason="SuperTrend 状态未知",
        action="等待下一次数据刷新",
        **opportunity,
    )
