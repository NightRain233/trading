"""Deterministic decision policy for the market-wide SuperTrend scan."""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo


SCHEMA_VERSION = 2
POLICY_VERSION = "scan_v2_right_side_1"

NORMAL_ADX_THRESHOLD = 25.0
CAUTIOUS_ADX_THRESHOLD = 30.0
BREAKOUT_MAX_DISTANCE_ATR = 2.0
PULLBACK_ZONE_ATR = 1.5
V_REVERSAL_BOLL_DISTANCE_ATR = 0.5
V_REVERSAL_MAX_VOLUME_RATIO = 0.8

MARKET_REPRESENTATIVES = {
    "a_share": ("000001.SS", "000300.SS"),
    "us": ("SPY", "QQQ"),
    "crypto": ("BTC-USD", "ETH-USD"),
    "gold": ("GC=F", "518880.SS"),
    "bond": ("511010.SS", "TLT"),
}

GOLD_SYMBOLS = {"GC=F", "518880.SS"}
BOND_SYMBOLS = {"511010.SS", "TLT"}
CRYPTO_SYMBOLS = {"BTC-USD", "ETH-USD"}
US_EXPOSURE_SYMBOLS = {"513100.SS"}
HK_EXPOSURE_SYMBOLS = {"513010.SS", "513120.SS", "513180.SS", "513910.SS"}

PRIMARY_GROUPS = (
    "risk",
    "breakout_buy",
    "pullback_buy",
    "wait_confirmation",
    "yellow_watch",
    "v_reversal_watch",
    "trend_continuation",
    "stable",
    "blocked",
)


def classify_symbol_market(symbol: str) -> str:
    normalized = str(symbol or "").upper()
    if normalized in GOLD_SYMBOLS:
        return "gold"
    if normalized in BOND_SYMBOLS:
        return "bond"
    if normalized in CRYPTO_SYMBOLS:
        return "crypto"
    if normalized in US_EXPOSURE_SYMBOLS:
        return "us"
    if normalized in HK_EXPOSURE_SYMBOLS:
        return "hong_kong"
    if normalized.endswith((".SS", ".SZ")):
        return "a_share"
    if normalized.endswith("-USD"):
        return "crypto"
    if normalized.endswith("=F"):
        return "commodity"
    return "us"


def classify_trend_state(directions: Iterable[Any]) -> tuple[str, bool]:
    normalized: list[int] = []
    for direction in directions:
        try:
            value = int(direction)
        except (TypeError, ValueError):
            continue
        if value in {-1, 1}:
            normalized.append(value)
    current = normalized[-1] if normalized else -1
    just_flipped = len(normalized) >= 2 and normalized[-1] != normalized[-2]
    if current == 1:
        return ("bull_flip" if just_flipped else "bull", just_flipped)
    return ("bear_flip" if just_flipped else "bear", just_flipped)


def _monthly_direction(item: Optional[dict[str, Any]]) -> Optional[str]:
    if not item:
        return None
    context = item.get("monthlyBoll") or {}
    direction = (
        context.get("decisionMidDirection")
        if "decisionMidDirection" in context
        else context.get("midDirection")
    )
    if direction not in {"rising", "flat", "falling"}:
        return None
    if context.get("slopeSampleSufficient") is False:
        return None
    return str(direction)


def build_market_modes(items: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    item_map = {str(item.get("symbol") or "").upper(): item for item in items}
    modes: dict[str, dict[str, Any]] = {}
    for market, representatives in MARKET_REPRESENTATIVES.items():
        directions = {symbol: _monthly_direction(item_map.get(symbol)) for symbol in representatives}
        missing = [symbol for symbol, direction in directions.items() if direction is None]
        values = [direction for direction in directions.values() if direction is not None]
        if missing:
            mode = "insufficient"
            adx_threshold = None
        elif all(direction in {"rising", "flat"} for direction in values):
            mode = "seek"
            adx_threshold = NORMAL_ADX_THRESHOLD
        elif all(direction == "falling" for direction in values):
            mode = "survival"
            adx_threshold = None
        else:
            mode = "cautious"
            adx_threshold = CAUTIOUS_ADX_THRESHOLD
        modes[market] = {
            "mode": mode,
            "representatives": list(representatives),
            "directions": directions,
            "adxThreshold": adx_threshold,
            "missingSymbols": missing,
        }
    return modes


def _finite_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _absolute_or_infinity(value: Any) -> float:
    number = _finite_float(value)
    return abs(number) if number is not None else float("inf")


def _weekly_bull(item: dict[str, Any]) -> bool:
    return item.get("weeklyState") in {"bull", "bull_flip"}


def _data_failure(item: dict[str, Any]) -> Optional[str]:
    if item.get("dataStale") is True:
        return "DATA_STALE"
    integrity = item.get("dataIntegrity") or {}
    if integrity.get("hasGap") or integrity.get("hasRecentGap"):
        return "DATA_GAP"
    if item.get("dailySessionComplete") is not True:
        return "DAILY_SESSION_INCOMPLETE"
    return None


def _market_context(
    item: dict[str, Any],
    market_modes: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    market = classify_symbol_market(str(item.get("symbol") or ""))
    context = market_modes.get(market) or {
        "mode": "insufficient",
        "representatives": [],
        "directions": {},
        "adxThreshold": None,
        "missingSymbols": [],
    }
    return market, context


def _pullback_context(item: dict[str, Any]) -> dict[str, Any]:
    atr = _finite_float((item.get("indicators") or {}).get("atr"))
    close = _finite_float(item.get("close"))
    st_val = _finite_float(item.get("stVal"))
    distance = _finite_float(item.get("distanceToSupertrendAtr"))
    age = int(item.get("trendAgeBars") or 0)
    eligible_structure = (
        item.get("state") == "bull"
        and _weekly_bull(item)
        and age > 3
        and distance is not None
        and 0 <= distance <= PULLBACK_ZONE_ATR
        and close is not None
        and st_val is not None
        and close >= st_val
    )
    context = {
        "enteredZone": eligible_structure,
        "enteredAt": item.get("latestDataDate") if eligible_structure else None,
        "supportHeld": bool(eligible_structure),
        "restrengthConfirmed": False,
        "confirmedAt": None,
        "failed": item.get("state") in {"bear", "bear_flip"},
    }
    candles = item.get("candles") or []
    if not eligible_structure or atr is None or atr <= 0 or len(candles) < 2:
        return context

    previous, current = candles[-2], candles[-1]
    previous_close = _finite_float(previous.get("close"))
    previous_st = _finite_float(previous.get("st_val"))
    current_close = _finite_float(current.get("close"))
    current_st = _finite_float(current.get("st_val"))
    previous_in_zone = (
        previous.get("st_dir") == 1
        and previous_close is not None
        and previous_st is not None
        and previous_close >= previous_st
        and abs(previous_close - previous_st) / atr <= PULLBACK_ZONE_ATR
    )
    support_held = (
        current.get("st_dir") == 1
        and current_close is not None
        and current_st is not None
        and current_close >= current_st
    )
    confirmed = previous_in_zone and support_held and current_close > previous_close
    context.update({
        "enteredZone": True,
        "enteredAt": previous.get("time") if previous_in_zone else current.get("time", item.get("latestDataDate")),
        "supportHeld": bool(support_held),
        "restrengthConfirmed": bool(confirmed),
        "confirmedAt": current.get("time") if confirmed else None,
        "failed": False,
    })
    return context


def _v_reversal_context(item: dict[str, Any]) -> dict[str, Any]:
    indicators = item.get("indicators") or {}
    close = _finite_float(item.get("close"))
    lower = _finite_float(indicators.get("bollLower"))
    atr = _finite_float(indicators.get("atr"))
    volume = item.get("volumeContext") or {}
    ratio = _finite_float(volume.get("ratio20Completed"))
    near_lower = (
        close is not None
        and lower is not None
        and atr is not None
        and atr > 0
        and close <= lower + V_REVERSAL_BOLL_DISTANCE_ATR * atr
    )
    volume_contracting = volume.get("sessionComplete") is True and ratio is not None and ratio <= V_REVERSAL_MAX_VOLUME_RATIO
    candidate = _weekly_bull(item) and near_lower and volume_contracting and item.get("state") == "bear"
    divergence = item.get("macdDivergence") or {}
    daily_divergence = divergence.get("daily") or {}
    return {
        "candidate": bool(candidate),
        "nearLowerBoll": bool(near_lower),
        "volumeContracting": bool(volume_contracting),
        "confirmedDivergence": daily_divergence.get("confirmed") is not None,
        "permission": "watch" if candidate else "none",
    }


def _decision(
    item: dict[str, Any],
    market_context: dict[str, Any],
    pullback: dict[str, Any],
    v_reversal: dict[str, Any],
) -> tuple[dict[str, Any], str, list[str]]:
    state = item.get("state")
    weekly_bull = _weekly_bull(item)
    adx = _finite_float((item.get("indicators") or {}).get("adx"))
    distance = _finite_float(item.get("distanceToSupertrendAtr"))
    mode = str(market_context.get("mode") or "insufficient")
    threshold = _finite_float(market_context.get("adxThreshold"))
    tags: list[str] = []

    data_failure = _data_failure(item)
    if data_failure:
        return ({
            "permission": "blocked",
            "label": "禁止交易·数据未完成",
            "setup": "none",
            "stage": "blocked",
            "reasonCodes": [],
            "failedGates": [data_failure],
            "nextTrigger": "刷新并等待完整收盘数据",
            "invalidation": None,
            "maxAcceptablePrice": None,
        }, "blocked", tags)

    if state == "bear_flip" or item.get("alertType") == "sell_or_risk":
        return ({
            "permission": "risk",
            "label": "持有/风控·日线翻空",
            "setup": "risk",
            "stage": "confirmed",
            "reasonCodes": ["DATA_VALID", "DAILY_BEAR_FLIP"],
            "failedGates": [],
            "nextTrigger": "按持仓和品种页规则处理",
            "invalidation": None,
            "maxAcceptablePrice": None,
        }, "risk", tags)

    if mode == "survival":
        return ({
            "permission": "blocked",
            "label": "禁止交易·市场保命模式",
            "setup": "none",
            "stage": "blocked",
            "reasonCodes": ["DATA_VALID"],
            "failedGates": ["MARKET_SURVIVAL"],
            "nextTrigger": "等待市场月线模式改善",
            "invalidation": None,
            "maxAcceptablePrice": None,
        }, "blocked", tags)

    yellow = state in {"bull", "bull_flip"} and not weekly_bull and adx is not None and adx >= 30
    if yellow:
        tags.append("yellow_watch")

    if state == "bull_flip":
        reasons = ["DATA_VALID"]
        failed: list[str] = []
        if mode == "seek":
            reasons.append("MARKET_SEEK")
        elif mode == "cautious":
            reasons.append("MARKET_CAUTIOUS")
        else:
            failed.append("MARKET_MODE_INSUFFICIENT")
        if weekly_bull:
            reasons.append("WEEKLY_BULL")
        else:
            failed.append("WEEKLY_NOT_BULL")
        reasons.append("DAILY_BULL_FLIP")
        if threshold is not None:
            if adx is not None and adx >= threshold:
                reasons.append("ADX_PASSED")
            elif adx is None:
                failed.append("ADX_UNAVAILABLE")
            else:
                failed.append(f"ADX_BELOW_{int(threshold)}")
        if distance is not None and distance <= BREAKOUT_MAX_DISTANCE_ATR:
            reasons.append("DISTANCE_PASSED")
        else:
            failed.append("DISTANCE_ABOVE_2_ATR")

        st_val = _finite_float(item.get("stVal"))
        atr = _finite_float((item.get("indicators") or {}).get("atr"))
        max_price = st_val + BREAKOUT_MAX_DISTANCE_ATR * atr if st_val is not None and atr is not None else None
        if not failed:
            permission, label, stage, group = "buy", "可买·突破入场", "confirmed", "breakout_buy"
        elif failed == ["DISTANCE_ABOVE_2_ATR"]:
            permission, label, stage, group = "wait", "等确认·突破已发生，等待回踩", "extended", "wait_confirmation"
        elif "MARKET_MODE_INSUFFICIENT" in failed:
            permission, label, stage, group = "wait", "等确认·市场模式数据不足", "waiting", "wait_confirmation"
        else:
            permission, label, stage = "watch", "只观察·突破条件未通过", "watch"
            group = "yellow_watch" if yellow else "stable"
        return ({
            "permission": permission,
            "label": label,
            "setup": "breakout",
            "stage": stage,
            "reasonCodes": reasons,
            "failedGates": failed,
            "nextTrigger": "下一交易日不超过最高接受价时执行" if permission == "buy" else "等待未通过条件改善",
            "invalidation": "日线收盘重新翻空",
            "maxAcceptablePrice": max_price,
        }, group, tags)

    if yellow:
        return ({
            "permission": "watch",
            "label": "只观察·黄灯追踪，周线未确认",
            "setup": "yellow_watch",
            "stage": "watch",
            "reasonCodes": ["DATA_VALID", "DAILY_BULL", "ADX_AT_LEAST_30"],
            "failedGates": ["WEEKLY_NOT_BULL"],
            "nextTrigger": "等待周线翻多后重新评估",
            "invalidation": "日线翻空、周线翻多或ADX跌破30",
            "maxAcceptablePrice": None,
        }, "yellow_watch", tags)

    if pullback["enteredZone"]:
        reasons = ["DATA_VALID"]
        failed = []
        if mode == "seek":
            reasons.append("MARKET_SEEK")
        elif mode == "cautious":
            reasons.append("MARKET_CAUTIOUS")
        else:
            failed.append("MARKET_MODE_INSUFFICIENT")
        reasons.extend(["WEEKLY_BULL", "PULLBACK_ZONE", "SUPPORT_HELD"])
        if threshold is not None:
            if adx is not None and adx >= threshold:
                reasons.append("ADX_PASSED")
            elif adx is None:
                failed.append("ADX_UNAVAILABLE")
            else:
                failed.append(f"ADX_BELOW_{int(threshold)}")
        if pullback["restrengthConfirmed"]:
            reasons.append("RESTRENGTH_CONFIRMED")
        else:
            failed.append("RESTRENGTH_NOT_CONFIRMED")
        if not failed:
            permission, label, stage, group = "buy", "可买·回踩入场", "confirmed", "pullback_buy"
        else:
            permission, label, stage, group = "wait", "等确认·回踩接近支撑", "approaching", "wait_confirmation"
        return ({
            "permission": permission,
            "label": label,
            "setup": "pullback",
            "stage": stage,
            "reasonCodes": reasons,
            "failedGates": failed,
            "nextTrigger": "下一交易日按回踩计划执行" if permission == "buy" else "等待完整日线重新走强",
            "invalidation": "日线收盘跌破SuperTrend",
            "maxAcceptablePrice": None,
        }, group, tags)

    if v_reversal["candidate"]:
        tags.append("v_reversal")
        return ({
            "permission": "watch",
            "label": "只观察·V型反转前兆",
            "setup": "v_reversal",
            "stage": "watch",
            "reasonCodes": ["DATA_VALID", "WEEKLY_BULL", "NEAR_DAILY_BOLL_LOWER", "VOLUME_CONTRACTING"],
            "failedGates": ["DAILY_BULL_FLIP_MISSING"],
            "nextTrigger": "等待日线SuperTrend收盘翻多",
            "invalidation": "周线翻空或放量跌破结构",
            "maxAcceptablePrice": None,
        }, "v_reversal_watch", tags)

    if mode == "insufficient" and weekly_bull:
        return ({
            "permission": "wait",
            "label": "等确认·市场模式数据不足",
            "setup": "none",
            "stage": "waiting",
            "reasonCodes": ["DATA_VALID", "WEEKLY_BULL"],
            "failedGates": ["MARKET_MODE_INSUFFICIENT"],
            "nextTrigger": "补齐市场代表品种数据",
            "invalidation": "周线翻空",
            "maxAcceptablePrice": None,
        }, "wait_confirmation", tags)

    if state == "bull":
        return ({
            "permission": "watch",
            "label": "只观察·趋势延续",
            "setup": "none",
            "stage": "trend",
            "reasonCodes": ["DATA_VALID", "DAILY_BULL"],
            "failedGates": ["NO_ENTRY_TRIGGER"],
            "nextTrigger": "等待有效回踩或下一次正式突破",
            "invalidation": "日线翻空",
            "maxAcceptablePrice": None,
        }, "trend_continuation", tags)

    return ({
        "permission": "watch",
        "label": "只观察·空头规避",
        "setup": "none",
        "stage": "stable",
        "reasonCodes": ["DATA_VALID"],
        "failedGates": ["DAILY_NOT_BULL"],
        "nextTrigger": "等待完整日线SuperTrend翻多",
        "invalidation": None,
        "maxAcceptablePrice": None,
    }, "stable", tags)


def build_scan_response(
    items: Iterable[dict[str, Any]],
    *,
    requested_symbols: Iterable[str],
    generated_at: Optional[str] = None,
) -> dict[str, Any]:
    normalized_items = [copy.deepcopy(item) for item in items]
    requested = list(dict.fromkeys(str(symbol).upper() for symbol in requested_symbols))
    returned = [str(item.get("symbol") or "").upper() for item in normalized_items]
    market_modes = build_market_modes(normalized_items)
    groups = {name: {"count": 0, "symbols": []} for name in PRIMARY_GROUPS}

    for item in normalized_items:
        market, market_context = _market_context(item, market_modes)
        pullback = _pullback_context(item)
        v_reversal = _v_reversal_context(item)
        decision, primary_group, tags = _decision(item, market_context, pullback, v_reversal)
        breakout_triggered = item.get("state") == "bull_flip"
        breakout = {
            "triggered": breakout_triggered,
            "signalDate": item.get("latestDataDate") if breakout_triggered else None,
            "previousState": "bear" if breakout_triggered else None,
            "currentState": item.get("state"),
            "distanceAtr": _finite_float(item.get("distanceToSupertrendAtr")),
            "maxAcceptablePrice": decision.get("maxAcceptablePrice") if breakout_triggered else None,
            "stillExecutable": breakout_triggered and decision.get("permission") == "buy",
        }
        item.update({
            "market": market,
            "marketMode": market_context["mode"],
            "breakout": breakout,
            "pullback": pullback,
            "vReversal": v_reversal,
            "decision": decision,
            "primaryGroup": primary_group,
            "tags": tags,
        })
        groups[primary_group]["symbols"].append(item["symbol"])

    item_map = {item["symbol"]: item for item in normalized_items}
    for name, group in groups.items():
        if name == "yellow_watch":
            group["symbols"].sort(key=lambda symbol: (
                _absolute_or_infinity(item_map[symbol].get("distanceToSupertrendAtr")),
                -(_finite_float((item_map[symbol].get("indicators") or {}).get("adx")) or 0.0),
                symbol,
            ))
        elif name in {"breakout_buy", "pullback_buy", "wait_confirmation"}:
            group["symbols"].sort(key=lambda symbol: (
                _absolute_or_infinity(item_map[symbol].get("distanceToSupertrendAtr")),
                symbol,
            ))
        group["count"] = len(group["symbols"])

    return {
        "schemaVersion": SCHEMA_VERSION,
        "policyVersion": POLICY_VERSION,
        "includesCandles": True,
        "generatedAt": generated_at or datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "coverage": {
            "requested": len(requested),
            "returned": len(returned),
            "missing": [symbol for symbol in requested if symbol not in returned],
        },
        "thresholds": {
            "normalAdx": NORMAL_ADX_THRESHOLD,
            "cautiousAdx": CAUTIOUS_ADX_THRESHOLD,
            "breakoutMaxAtr": BREAKOUT_MAX_DISTANCE_ATR,
            "pullbackZoneAtr": PULLBACK_ZONE_ATR,
            "vReversalBollDistanceAtr": V_REVERSAL_BOLL_DISTANCE_ATR,
            "vReversalMaxVolumeRatio": V_REVERSAL_MAX_VOLUME_RATIO,
        },
        "marketModes": market_modes,
        "groups": groups,
        "items": normalized_items,
    }
