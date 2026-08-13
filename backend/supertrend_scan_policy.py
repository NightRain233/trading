"""Deterministic decision policy for the market-wide SuperTrend scan."""

from __future__ import annotations

import copy
import hashlib
from datetime import datetime
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo


SCHEMA_VERSION = 2
POLICY_VERSION = "scan_v2_right_side_4"

NORMAL_ADX_THRESHOLD = 25.0
CAUTIOUS_ADX_THRESHOLD = 30.0
BREAKOUT_MAX_DISTANCE_ATR = 2.0
PULLBACK_ZONE_ATR = 1.5
PULLBACK_APPROACHING_ATR = 2.5
COMPRESSION_MAX_DISTANCE_ATR = 1.5
COMPRESSION_MAX_TRIGGER_SLIPPAGE_ATR = 0.5
COMPRESSION_NORMAL_ADX_MIN = 18.0
COMPRESSION_CAUTIOUS_ADX_MIN = 22.0
V_REVERSAL_BOLL_DISTANCE_ATR = 0.5
V_REVERSAL_MAX_VOLUME_RATIO = 0.8

SYSTEM_MARKET_REPRESENTATIVES = {
    "a_share": ("000001.SS", "000300.SS"),
    "hong_kong": ("^HSI", "2800.HK"),
    "us": ("SPY", "QQQ"),
    "crypto": ("BTC-USD", "ETH-USD"),
    "gold": ("GC=F", "518880.SS"),
    "bond_cn": ("511010.SS",),
    "bond_us": ("TLT",),
}
# Some yfinance index/ETF series are intermittently incomplete.  These are
# only used to fill a missing Hong Kong representative; they do not replace a
# healthy primary series.
MARKET_REPRESENTATIVE_FALLBACKS = {
    "hong_kong": ("513010.SS", "510900.SS"),
}
MARKET_REPRESENTATIVES = {**SYSTEM_MARKET_REPRESENTATIVES, "bond": ("511010.SS", "TLT")}

GOLD_SYMBOLS = {"GC=F", "518880.SS"}
BOND_SYMBOLS = {"511010.SS", "TLT"}
CRYPTO_SYMBOLS = {"BTC-USD", "ETH-USD"}
US_EXPOSURE_SYMBOLS = {"513100.SS", "513500.SS"}
HK_EXPOSURE_SYMBOLS = {"513010.SS", "513120.SS", "513180.SS", "513910.SS"}

THEME_DEFINITIONS = {
    "gold": ("黄金", ("GC=F", "518880.SS")),
    "sp500": ("标普500", ("SPY", "513500.SS")),
    "nasdaq100": ("纳指100", ("QQQ", "513100.SS")),
    "csi300": ("沪深300", ("000300.SS", "510300.SS")),
    "hang_seng_tech": ("恒生科技", ("513010.SS", "513180.SS")),
    "china_chip": ("国产芯片ETF", ("159995.SZ", "588890.SS")),
}

PRIMARY_GROUPS = (
    "risk",
    "breakout_buy",
    "pullback_buy",
    "breakout_armed",
    "wait_confirmation",
    "compression_watch",
    "yellow_watch",
    "v_reversal_watch",
    "trend_continuation",
    "stable",
    "blocked",
)

PERMISSION_PRIORITY = {
    "risk": 0,
    "buy": 1,
    "conditional": 2,
    "wait": 3,
    "watch": 4,
    "blocked": 5,
}


def classify_symbol_market(symbol: str) -> str:
    normalized = str(symbol or "").upper()
    if normalized in GOLD_SYMBOLS:
        return "gold"
    if normalized in BOND_SYMBOLS:
        return "bond_cn" if normalized == "511010.SS" else "bond_us"
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


def classify_trading_venue(symbol: str) -> str:
    normalized = str(symbol or "").upper()
    if normalized.endswith((".SS", ".SZ")):
        return "china_exchange"
    if normalized.endswith(".HK") or normalized.startswith("^") and "HSI" in normalized:
        return "hong_kong_exchange"
    if normalized.endswith("-USD"):
        return "crypto_24_7"
    if normalized.endswith("=F"):
        return "us_futures"
    return "us_exchange"


def classify_asset_class(symbol: str) -> str:
    normalized = str(symbol or "").upper()
    if normalized.endswith("-USD"):
        return "crypto"
    if normalized.endswith("=F"):
        return "commodity_future"
    if normalized.endswith((".SS", ".SZ")):
        return "fund_or_equity_cn"
    if normalized.startswith("^"):
        return "index"
    return "equity_or_etf_us"


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
    if item.get("dataStale") is True:
        return None
    integrity = item.get("dataIntegrity") or {}
    if integrity.get("hasGap") or integrity.get("hasRecentGap"):
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


def _representative_status(item: Optional[dict[str, Any]]) -> str:
    if not item:
        return "missing"
    if item.get("dataStale") is True:
        return "stale"
    integrity = item.get("dataIntegrity") or {}
    if integrity.get("hasGap") or integrity.get("hasRecentGap"):
        return "data_gap"
    return "available" if _monthly_direction(item) is not None else "monthly_direction_unavailable"


def build_market_modes(items: Iterable[dict[str, Any]], representative_items: Iterable[dict[str, Any]] = ()) -> dict[str, dict[str, Any]]:
    item_map = {str(item.get("symbol") or "").upper(): item for item in items}
    item_map.update({str(item.get("symbol") or "").upper(): item for item in representative_items})
    modes: dict[str, dict[str, Any]] = {}
    for market, representatives in SYSTEM_MARKET_REPRESENTATIVES.items():
        primary_directions = {symbol: _monthly_direction(item_map.get(symbol)) for symbol in representatives}
        fallback_representatives = MARKET_REPRESENTATIVE_FALLBACKS.get(market, ())
        # Keep primary data whenever it is usable, and fill only unavailable
        # slots from the fallback pool.  Requiring two usable directions keeps
        # a single ETF from silently deciding the whole market mode.
        directions = dict(primary_directions)
        effective_directions = {
            symbol: direction
            for symbol, direction in primary_directions.items()
            if direction is not None
        }
        for symbol in fallback_representatives:
            if len(effective_directions) >= len(representatives):
                break
            direction = _monthly_direction(item_map.get(symbol))
            if direction is not None:
                directions[symbol] = direction
                effective_directions[symbol] = direction
        missing = [symbol for symbol in representatives if primary_directions[symbol] is None]
        values = list(effective_directions.values())
        if len(values) < len(representatives):
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
            "effectiveRepresentatives": list(effective_directions),
            "fallbackRepresentatives": list(fallback_representatives),
            "directions": directions,
            "adxThreshold": adx_threshold,
            "missingSymbols": missing,
            "representativeStatus": {symbol: _representative_status(item_map.get(symbol)) for symbol in representatives},
            "role": "bond_risk_observation" if market.startswith("bond_") else "equity_permission",
        }
    modes["bond"] = {
        "mode": "insufficient" if any(modes[key]["missingSymbols"] for key in ("bond_cn", "bond_us")) else "cautious",
        "representatives": ["511010.SS", "TLT"],
        "directions": {symbol: _monthly_direction(item_map.get(symbol)) for symbol in ("511010.SS", "TLT")},
        "adxThreshold": None,
        "missingSymbols": [symbol for symbol in ("511010.SS", "TLT") if _monthly_direction(item_map.get(symbol)) is None],
        "representativeStatus": {symbol: _representative_status(item_map.get(symbol)) for symbol in ("511010.SS", "TLT")},
        "role": "bond_risk_observation",
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


def _symbol_theme(symbol: str) -> Optional[dict[str, str]]:
    normalized = str(symbol or "").upper()
    for theme_id, (label, members) in THEME_DEFINITIONS.items():
        if normalized in members:
            return {"id": theme_id, "label": label}
    return None


def _compression_adx_threshold(mode: str) -> Optional[float]:
    if mode == "seek":
        return COMPRESSION_NORMAL_ADX_MIN
    if mode == "cautious":
        return COMPRESSION_CAUTIOUS_ADX_MIN
    return None


def _first_gate(failed: list[str]) -> Optional[str]:
    priority = (
        "DATA_STALE", "DATA_GAP", "DAILY_SESSION_INCOMPLETE",
        "MARKET_SURVIVAL", "MARKET_MODE_INSUFFICIENT", "WEEKLY_NOT_BULL",
        "DAILY_BULL_FLIP_MISSING", "ADX_UNAVAILABLE", "ADX_BELOW",
        "DISTANCE_ABOVE", "RESTRENGTH_NOT_CONFIRMED", "NO_ENTRY_TRIGGER",
    )
    for prefix in priority:
        match = next((gate for gate in failed if gate.startswith(prefix)), None)
        if match:
            return match
    return failed[0] if failed else None


def _failure_category(gate: Optional[str]) -> Optional[str]:
    if gate is None:
        return None
    if gate.startswith(("DATA_", "DAILY_SESSION_")):
        return "data"
    if gate.startswith("MARKET_"):
        return "market"
    if gate.startswith(("WEEKLY_", "DAILY_BULL_FLIP", "DAILY_NOT_BULL")):
        return "direction"
    if gate.startswith("ADX_"):
        return "strength"
    if gate.startswith("DISTANCE_"):
        return "price"
    return "timing"


def _readiness_score(item: dict[str, Any], decision: dict[str, Any]) -> int:
    permission = decision.get("permission")
    stage = decision.get("stage")
    if permission in {"buy", "risk"}:
        return 100
    if permission == "blocked":
        return 0
    if permission == "conditional":
        distance = _absolute_or_infinity(item.get("distanceToSupertrendAtr"))
        closeness = max(0.0, 1.0 - min(distance, COMPRESSION_MAX_DISTANCE_ATR) / COMPRESSION_MAX_DISTANCE_ATR)
        adx_delta = _finite_float((item.get("indicators") or {}).get("adxDelta"))
        return min(95, round(80 + 10 * closeness + (3 if adx_delta is not None and adx_delta > 0 else 0)))
    stage_bases = {
        "pullback_wait_restrength": 78,
        "pullback_approaching": 68,
        "extended_wait_pullback": 58,
        "market_confirmation_missing": 45,
        "weekly_confirmation_missing": 40,
        "compression_watch": 52,
        "v_reversal_watch": 35,
        "trend": 30,
    }
    return stage_bases.get(str(stage), 20)


def _decorate_decision(item: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    failed = list(decision.get("failedGates") or [])
    next_gate = _first_gate(failed)
    decision["nextGate"] = next_gate
    decision["failureCategory"] = _failure_category(next_gate)
    decision["readinessScore"] = _readiness_score(item, decision)
    trigger = _finite_float(decision.get("triggerPrice"))
    close = _finite_float(item.get("close"))
    atr = _finite_float((item.get("indicators") or {}).get("atr"))
    decision["distanceToTriggerAtr"] = (
        (trigger - close) / atr
        if trigger is not None and close is not None and atr is not None and atr > 0
        else None
    )
    decision.setdefault("paperOnly", False)
    decision.setdefault("technicalExecutionEligible", decision.get("permission") == "buy")
    # Final live permission belongs to the portfolio/risk layer, not this
    # cross-asset technical heuristic.
    decision.setdefault("liveTradingAllowed", False)
    return decision


def _authorization_context(item: dict[str, Any], decision: dict[str, Any]) -> Optional[dict[str, Any]]:
    if decision.get("permission") != "conditional":
        return None
    decision_as_of = str(item.get("decisionAsOf") or "")
    raw_id = "|".join((
        str(item.get("symbol") or "").upper(),
        POLICY_VERSION,
        decision_as_of,
        str(decision.get("setup") or ""),
    ))
    return {
        "signalId": hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:24],
        "armedAt": decision_as_of or None,
        "validFor": "next_market_session_only",
        "expiresAfter": "next_completed_daily_bar",
        "consumptionTracked": False,
        "paperOnly": True,
    }


def _weekly_bull(item: dict[str, Any]) -> bool:
    return item.get("weeklyState") in {"bull", "bull_flip"}


def _data_failure(item: dict[str, Any]) -> Optional[str]:
    if item.get("dataStale") is True:
        return "DATA_STALE"
    integrity = item.get("dataIntegrity") or {}
    if integrity.get("hasGap") or integrity.get("hasRecentGap"):
        return "DATA_GAP"
    if item.get("decisionDailyAvailable") is not True:
        return "DAILY_SESSION_INCOMPLETE"
    return None


def _session_context(item: dict[str, Any]) -> dict[str, Any]:
    session_complete = item.get("dailySessionComplete")
    if session_complete is True:
        status = "complete"
    elif session_complete is False:
        status = "in_progress"
    else:
        status = "unknown"
    return {
        "status": status,
        "latestDataDate": item.get("latestDataDate"),
        "formalDecisionAsOf": item.get("decisionAsOf"),
        "formalDecisionAvailable": item.get("decisionDailyAvailable") is True,
        "hasProvisionalBar": bool(item.get("hasProvisionalBar")),
        "permissionBasis": "completed_close",
    }


def _execution_status(item: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    live_price = _finite_float(item.get("livePrice"))
    formal_st = _finite_float(item.get("stVal"))
    atr = _finite_float((item.get("indicators") or {}).get("atr"))
    max_price = _finite_float(decision.get("maxAcceptablePrice"))
    session_in_progress = item.get("dailySessionComplete") is False
    live_distance_atr = (
        (live_price - formal_st) / atr
        if live_price is not None and formal_st is not None and atr is not None and atr > 0
        else None
    )

    status = "not_applicable"
    executable = False
    paper_executable = False
    reason = "当前没有经完整收盘确认的可执行入场信号"
    if decision.get("permission") == "conditional":
        trigger_price = _finite_float(decision.get("triggerPrice"))
        invalidation_price = _finite_float(decision.get("invalidationPrice"))
        if live_price is not None and invalidation_price is not None and live_price < invalidation_price:
            status = "armed_invalidated"
            reason = "实时价格跌破预设失效价，取消压缩突破计划"
        elif live_price is not None and max_price is not None and live_price > max_price:
            status = "armed_above_max"
            reason = "实时价格跳过压缩突破最高接受价，取消追买并转回踩观察"
        elif live_price is not None and trigger_price is not None and live_price >= trigger_price:
            status = "paper_armed_triggered"
            paper_executable = True
            reason = "压缩突破进入预设触发区间，但策略未经回测验证，仅记录纸面触发，禁止实盘执行"
        else:
            status = "armed_waiting_trigger"
            reason = "压缩突破计划已授权，等待实时价格触及预设触发价"
    elif decision.get("permission") == "buy":
        if session_in_progress and live_price is not None and formal_st is not None and live_price < formal_st:
            status = "intraday_below_formal_st"
            reason = "实时价格盘中跌破正式SuperTrend，取消新仓执行并等待收盘确认"
        elif live_price is not None and max_price is not None and live_price > max_price:
            status = "above_max_price"
            reason = "实时价格已超过正式信号的最高接受价，取消追买"
        else:
            status = "executable"
            executable = True
            reason = "正式收盘信号有效，实时价格未超过最高接受条件"
    elif session_in_progress and item.get("state") in {"bull", "bull_flip"} and live_price is not None and formal_st is not None and live_price < formal_st:
        status = "intraday_below_formal_st"
        reason = "实时价格盘中跌破正式SuperTrend，仅作风险预警，等待收盘确认"
    elif session_in_progress and item.get("state") in {"bear", "bear_flip"} and live_price is not None and formal_st is not None and live_price > formal_st:
        status = "provisional_recovery"
        reason = "实时价格盘中站上正式SuperTrend，不得据此升级买入权限"
    elif session_in_progress:
        status = "monitoring"
        reason = "沿用最近完整收盘决策，盘中信息只可降级执行或提示风险"

    return {
        "status": status,
        "executable": executable,
        "paperExecutable": paper_executable,
        "reason": reason,
        "livePrice": live_price,
        "liveAsOf": item.get("liveAsOf"),
        "formalClose": _finite_float(item.get("close")),
        "formalStVal": formal_st,
        "liveDistanceToFormalStAtr": live_distance_atr,
        "maxAcceptablePrice": max_price,
        "triggerPrice": _finite_float(decision.get("triggerPrice")),
        "invalidationPrice": _finite_float(decision.get("invalidationPrice")),
        "canUpgradePermissionIntraday": False,
        "canDowngradeExecutionIntraday": True,
    }


def _position_guidance(item: dict[str, Any], execution: dict[str, Any]) -> dict[str, Any]:
    state = item.get("state")
    weekly_bull = _weekly_bull(item)
    data_failure = _data_failure(item)
    if data_failure:
        status, label, action = "data_unavailable_review", "持仓复核·数据不可用", "不能确认继续持有或正式退出；沿用最后有效风险线并人工核对最新行情"
    elif state == "bear_flip" or item.get("alertType") == "sell_or_risk":
        status, label, action = "formal_exit", "持仓风控·正式日线翻空", "若有持仓，按品种页和组合规则减仓或退出"
    elif state == "bear":
        status, label, action = "avoid_or_exit_review", "持仓风控·日线空头", "无仓继续规避；有仓检查既有退出规则"
    elif execution.get("status") == "intraday_below_formal_st":
        status, label, action = "intraday_risk_warning", "持仓预警·盘中跌破正式ST", "不等同正式退出；检查止损并等待收盘确认"
    elif not weekly_bull:
        status, label, action = "hold_with_weekly_risk", "持仓观察·周线未确认", "若有持仓可按正式日线风控持有，不新增仓位"
    else:
        status, label, action = "trend_hold", "持仓观察·正式趋势维持", "若有持仓继续按正式SuperTrend管理风险"
    return {
        "status": status,
        "label": label,
        "action": action,
        "basis": "last_valid_close" if data_failure else "completed_close",
        "dataFailure": data_failure,
    }


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


def _compression_context(item: dict[str, Any], market_context: dict[str, Any]) -> dict[str, Any]:
    indicators = item.get("indicators") or {}
    state = item.get("state")
    reported_distance = _finite_float(item.get("distanceToSupertrendAtr"))
    st_val = _finite_float(item.get("stVal"))
    atr = _finite_float(indicators.get("atr"))
    close = _finite_float(item.get("close"))
    distance = (
        (close - st_val) / atr
        if close is not None and st_val is not None and atr is not None and atr > 0
        else reported_distance
    )
    adx = _finite_float(indicators.get("adx"))
    adx_delta = _finite_float(indicators.get("adxDelta"))
    macd_hist = _finite_float(indicators.get("macdHist"))
    macd_delta = _finite_float(indicators.get("macdHistDelta"))
    mode = str(market_context.get("mode") or "insufficient")
    adx_threshold = _compression_adx_threshold(mode)
    near_trigger = distance is not None and -COMPRESSION_MAX_DISTANCE_ATR <= distance < 0
    squeeze = item.get("bollSqueeze") is True or indicators.get("bollSqueeze") is True
    compression_recent = (
        item.get("bollSqueezeRecent") is True
        or indicators.get("bollSqueezeRecent") is True
        or squeeze
    )
    momentum_improving = (
        macd_hist is not None
        and macd_hist > 0
        and macd_delta is not None
        and macd_delta > 0
    )
    adx_acceptable = adx_threshold is not None and adx is not None and adx >= adx_threshold
    technical_candidate = bool(
        state == "bear"
        and near_trigger
        and compression_recent
        and momentum_improving
        and adx_acceptable
        and st_val is not None
        and atr is not None
        and atr > 0
    )
    weekly_bull = _weekly_bull(item)
    market_allowed = mode in {"seek", "cautious"}
    armed = technical_candidate and weekly_bull and market_allowed
    candles = item.get("candles") or []
    recent_lows = [
        value
        for candle in candles[-5:]
        if (value := _finite_float(candle.get("low"))) is not None
    ]
    structure_low = min(recent_lows) if recent_lows else None
    bounded_invalidation = (
        max(structure_low, st_val - COMPRESSION_MAX_DISTANCE_ATR * atr)
        if structure_low is not None and st_val is not None and atr is not None
        else None
    )
    return {
        "candidate": technical_candidate,
        "armed": armed,
        "watchOnly": technical_candidate and not armed,
        "triggerPrice": st_val if technical_candidate else None,
        "maxAcceptablePrice": (
            st_val + COMPRESSION_MAX_TRIGGER_SLIPPAGE_ATR * atr
            if technical_candidate and st_val is not None and atr is not None
            else None
        ),
        "invalidationPrice": bounded_invalidation if technical_candidate else None,
        "distanceToTriggerAtr": abs(distance) if near_trigger and distance is not None else None,
        "nearTrigger": near_trigger,
        "bollSqueeze": squeeze,
        "bollCompressionRecent": compression_recent,
        "macdPositiveImproving": momentum_improving,
        "adx": adx,
        "adxDelta": adx_delta,
        "adxThreshold": adx_threshold,
        "adxAcceptable": adx_acceptable,
        "weeklyConfirmed": weekly_bull,
        "marketAllowed": market_allowed,
        "permissionBasis": "previous_completed_close",
    }


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
    compression: dict[str, Any],
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

    if compression["armed"]:
        tags.append("compression_breakout")
        return ({
            "permission": "conditional",
            "label": "纸面布防·压缩突破实验",
            "setup": "compression_breakout",
            "stage": "breakout_armed",
            "reasonCodes": [
                "DATA_VALID", "MARKET_ALLOWED", "WEEKLY_BULL", "DAILY_BEAR_NEAR_ST",
                "BOLL_COMPRESSION_RECENT", "MACD_POSITIVE_IMPROVING", "COMPRESSION_ADX_PASSED",
            ],
            "failedGates": [],
            "nextTrigger": "下一交易时段记录纸面触发；完成样本外与成本回测前禁止实盘",
            "invalidation": "触发前跌破压缩结构低点，或触发后日线收盘未能维持多头结构",
            "triggerPrice": compression["triggerPrice"],
            "maxAcceptablePrice": compression["maxAcceptablePrice"],
            "invalidationPrice": compression["invalidationPrice"],
            "paperOnly": True,
            "liveTradingAllowed": False,
            "validationStatus": "unvalidated_heuristic",
        }, "breakout_armed", tags)

    if compression["watchOnly"]:
        tags.append("compression_breakout")
        failed = []
        if not compression["weeklyConfirmed"]:
            failed.append("WEEKLY_NOT_BULL")
        if not compression["marketAllowed"]:
            failed.append("MARKET_MODE_INSUFFICIENT")
        return ({
            "permission": "watch",
            "label": "只观察·压缩突破前兆",
            "setup": "compression_breakout",
            "stage": "compression_watch",
            "reasonCodes": [
                "DATA_VALID", "DAILY_BEAR_NEAR_ST", "BOLL_COMPRESSION_RECENT",
                "MACD_POSITIVE_IMPROVING", "COMPRESSION_ADX_PASSED",
            ],
            "failedGates": failed,
            "nextTrigger": "等待正式周线与市场权限确认后再布防；当前不得建立新仓",
            "invalidation": "价格远离触发区、压缩解除向下或MACD动能重新转弱",
            "triggerPrice": compression["triggerPrice"],
            "maxAcceptablePrice": compression["maxAcceptablePrice"],
            "invalidationPrice": compression["invalidationPrice"],
        }, "compression_watch", tags)

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
            permission, label, stage, group = "buy", "可买·突破入场", "breakout_confirmed", "breakout_buy"
        elif failed == ["DISTANCE_ABOVE_2_ATR"]:
            permission, label, stage, group = "wait", "等确认·突破已发生，等待回踩", "extended_wait_pullback", "wait_confirmation"
        elif "MARKET_MODE_INSUFFICIENT" in failed:
            permission, label, stage, group = "wait", "等确认·市场模式数据不足", "market_confirmation_missing", "wait_confirmation"
        else:
            permission, label, stage = "watch", "只观察·突破条件未通过", "breakout_gates_failed"
            group = "yellow_watch" if yellow else "stable"
        return ({
            "permission": permission,
            "label": label,
            "setup": "breakout",
            "stage": stage,
            "reasonCodes": reasons,
            "failedGates": failed,
            "nextTrigger": (
                "下一交易日不超过最高接受价时执行"
                if permission == "buy"
                else "等待价格回到1.5 ATR回踩区"
                if stage == "extended_wait_pullback"
                else "等待首个失败门槛改善"
            ),
            "invalidation": "日线收盘重新翻空",
            "maxAcceptablePrice": max_price,
        }, group, tags)

    if yellow:
        return ({
            "permission": "watch",
            "label": "只观察·黄灯追踪，周线未确认",
            "setup": "yellow_watch",
            "stage": "weekly_confirmation_missing",
            "reasonCodes": ["DATA_VALID", "DAILY_BULL", "ADX_AT_LEAST_30"],
            "failedGates": ["WEEKLY_NOT_BULL"],
            "nextTrigger": "等待周线翻多后重新评估",
            "invalidation": "日线翻空、周线翻多或ADX跌破30",
            "maxAcceptablePrice": None,
        }, "yellow_watch", tags)

    if state == "bull" and not weekly_bull:
        return ({
            "permission": "watch",
            "label": "只观察·日线多头，周线未确认",
            "setup": "none",
            "stage": "weekly_confirmation_missing",
            "reasonCodes": ["DATA_VALID", "DAILY_BULL"],
            "failedGates": ["WEEKLY_NOT_BULL"],
            "nextTrigger": "等待完整周线翻多后重新评估",
            "invalidation": "日线翻空",
            "maxAcceptablePrice": None,
        }, "stable", tags)

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
            permission, label, stage, group = "buy", "可买·回踩入场", "pullback_confirmed", "pullback_buy"
        else:
            permission, label, stage, group = "wait", "等确认·已进入回踩区，支撑暂未失守", "pullback_wait_restrength", "wait_confirmation"
        pullback_st = _finite_float(item.get("stVal"))
        pullback_atr = _finite_float((item.get("indicators") or {}).get("atr"))
        pullback_max_price = (
            pullback_st + PULLBACK_ZONE_ATR * pullback_atr
            if pullback_st is not None and pullback_atr is not None
            else None
        )
        return ({
            "permission": permission,
            "label": label,
            "setup": "pullback",
            "stage": stage,
            "reasonCodes": reasons,
            "failedGates": failed,
            "nextTrigger": "下一交易日不超过回踩区上限时执行" if permission == "buy" else "已进入回踩区，支撑暂未失守；等待后续完整日线重新走强",
            "invalidation": "日线收盘跌破SuperTrend",
            "maxAcceptablePrice": pullback_max_price,
        }, group, tags)

    if v_reversal["candidate"]:
        tags.append("v_reversal")
        return ({
            "permission": "watch",
            "label": "只观察·V型反转前兆",
            "setup": "v_reversal",
            "stage": "v_reversal_watch",
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
            "stage": "market_confirmation_missing",
            "reasonCodes": ["DATA_VALID", "WEEKLY_BULL"],
            "failedGates": ["MARKET_MODE_INSUFFICIENT"],
            "nextTrigger": "补齐市场代表品种数据",
            "invalidation": "周线翻空",
            "maxAcceptablePrice": None,
        }, "wait_confirmation", tags)

    if (
        state == "bull"
        and weekly_bull
        and int(item.get("trendAgeBars") or 0) > 3
        and distance is not None
        and PULLBACK_ZONE_ATR < distance <= PULLBACK_APPROACHING_ATR
    ):
        return ({
            "permission": "wait",
            "label": "等确认·正在接近回踩区",
            "setup": "pullback",
            "stage": "pullback_approaching",
            "reasonCodes": ["DATA_VALID", "WEEKLY_BULL", "DAILY_BULL"],
            "failedGates": ["PULLBACK_ZONE_NOT_REACHED"],
            "nextTrigger": "等待价格进入距SuperTrend 1.5 ATR以内，再观察完整日线止跌转强",
            "invalidation": "日线收盘跌破SuperTrend",
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


def _lifecycle_context(
    item: dict[str, Any],
    decision: dict[str, Any],
    execution: dict[str, Any],
) -> dict[str, Any]:
    history = item.get("decisionHistory") or []
    changes: list[dict[str, Any]] = []
    previous_direction = None
    for point in history:
        current_state = str(point.get("state") or "")
        current_direction = "bull" if current_state.startswith("bull") else "bear" if current_state.startswith("bear") else None
        if previous_direction and current_direction and current_direction != previous_direction:
            changes.append({
                "date": point.get("date"),
                "from": previous_direction,
                "to": current_direction,
                "event": current_state if current_state.endswith("_flip") else "direction_change",
            })
        if current_direction:
            previous_direction = current_direction
    permission = decision.get("permission")
    stage = str(decision.get("stage") or "")
    execution_status = str(execution.get("status") or "not_applicable")
    if _data_failure(item):
        signal_status = "data_unavailable"
    elif permission == "buy" and execution.get("executable") is True:
        signal_status = "triggered_executable"
    elif permission == "buy":
        signal_status = "triggered_not_executable"
    elif permission == "conditional":
        signal_status = "paper_triggered" if execution.get("paperExecutable") is True else "paper_armed"
    elif stage == "extended_wait_pullback":
        signal_status = "triggered_extended"
    elif stage in {"pullback_approaching", "pullback_wait_restrength"}:
        signal_status = "approaching_trigger"
    elif stage in {"compression_watch", "v_reversal_watch"}:
        signal_status = "forming_watch"
    elif item.get("state") in {"bull", "bull_flip"}:
        signal_status = "trend_active_no_entry"
    else:
        signal_status = "not_triggered"
    return {
        "currentStage": stage,
        "signalStatus": signal_status,
        "executionStatus": execution_status,
        "recentStateChanges": changes[-3:],
        "recentDirectionChanges": changes[-3:],
        "historyPoints": len(history),
    }


def _build_themes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    themed: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        theme = item.get("theme")
        if theme:
            themed.setdefault(theme["id"], []).append(item)
    result = []
    for theme_id, members in themed.items():
        if len(members) < 2:
            continue
        ranked = sorted(members, key=lambda item: (
            PERMISSION_PRIORITY.get((item.get("decision") or {}).get("permission"), 99),
            -int((item.get("decision") or {}).get("readinessScore") or 0),
            str(item.get("symbol") or ""),
        ))
        result.append({
            "themeId": theme_id,
            "label": ranked[0]["theme"]["label"],
            "leader": ranked[0]["symbol"],
            "members": [item["symbol"] for item in ranked],
            "bestPermission": (ranked[0].get("decision") or {}).get("permission"),
            "bestStage": (ranked[0].get("decision") or {}).get("stage"),
        })
    return sorted(result, key=lambda theme: (
        PERMISSION_PRIORITY.get(theme.get("bestPermission"), 99),
        theme["themeId"],
    ))


def _build_changes(
    items: list[dict[str, Any]],
    previous_response: Optional[dict[str, Any]],
    current_generated_at: str,
) -> dict[str, Any]:
    previous_payload = previous_response if isinstance(previous_response, dict) else {}
    previous_items = {
        str(item.get("symbol") or "").upper(): item
        for item in previous_payload.get("items", [])
        if isinstance(item, dict)
    }
    changes = []
    formal_changes = []
    execution_changes = []
    position_changes = []
    current_symbols = {str(item.get("symbol") or "").upper() for item in items}
    previous_symbols = set(previous_items)
    for item in items:
        symbol = str(item.get("symbol") or "").upper()
        previous = previous_items.get(symbol)
        transition = None
        if previous:
            old_decision = previous.get("decision") or {}
            new_decision = item.get("decision") or {}
            formal_fields = {
                "group": (previous.get("primaryGroup"), item.get("primaryGroup")),
                "permission": (old_decision.get("permission"), new_decision.get("permission")),
                "setup": (old_decision.get("setup"), new_decision.get("setup")),
                "stage": (old_decision.get("stage"), new_decision.get("stage")),
            }
            old_execution = previous.get("executionStatus") or {}
            new_execution = item.get("executionStatus") or {}
            execution_fields = {
                "executionStatus": (old_execution.get("status"), new_execution.get("status")),
                "executable": (old_execution.get("executable"), new_execution.get("executable")),
                "paperExecutable": (old_execution.get("paperExecutable"), new_execution.get("paperExecutable")),
            }
            old_position = previous.get("positionGuidance") or {}
            new_position = item.get("positionGuidance") or {}
            position_fields = {
                "positionGuidance": (old_position.get("status"), new_position.get("status")),
            }
            formal_delta = {key: {"from": old, "to": new} for key, (old, new) in formal_fields.items() if old != new}
            execution_delta = {key: {"from": old, "to": new} for key, (old, new) in execution_fields.items() if old != new}
            position_delta = {key: {"from": old, "to": new} for key, (old, new) in position_fields.items() if old != new}
            changed_fields = {**formal_delta, **execution_delta, **position_delta}
            if changed_fields:
                transition = {
                    "symbol": symbol,
                    "observedAt": current_generated_at,
                    "changes": changed_fields,
                    "formalChanges": formal_delta,
                    "executionChanges": execution_delta,
                    "positionChanges": position_delta,
                }
                changes.append(transition)
                if formal_delta:
                    formal_changes.append(transition)
                if execution_delta:
                    execution_changes.append(transition)
                if position_delta:
                    position_changes.append(transition)
        item["transition"] = transition
    return {
        "baselineAvailable": bool(previous_items),
        "baselineGeneratedAt": previous_payload.get("generatedAt"),
        "currentGeneratedAt": current_generated_at,
        "addedSymbols": sorted(current_symbols - previous_symbols) if previous_items else [],
        "removedSymbols": sorted(previous_symbols - current_symbols) if previous_items else [],
        "replayedFromCache": False,
        "count": len(changes),
        "items": changes,
        "formalCount": len(formal_changes),
        "formalItems": formal_changes,
        "executionCount": len(execution_changes),
        "executionItems": execution_changes,
        "positionCount": len(position_changes),
        "positionItems": position_changes,
    }


def _build_attention(groups: dict[str, dict[str, Any]], item_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    near = sorted(
        groups["wait_confirmation"]["symbols"],
        key=lambda symbol: -int((item_map[symbol].get("decision") or {}).get("readinessScore") or 0),
    )[:5]
    return {
        "mustAct": list(groups["risk"]["symbols"]),
        "formalBuySignals": list(groups["breakout_buy"]["symbols"] + groups["pullback_buy"]["symbols"]),
        "executable": [
            symbol
            for symbol in groups["breakout_buy"]["symbols"] + groups["pullback_buy"]["symbols"]
            if (item_map[symbol].get("executionStatus") or {}).get("executable") is True
        ],
        "armed": list(groups["breakout_armed"]["symbols"]),
        "nearTrigger": near,
        "observationCount": sum(
            groups[name]["count"]
            for name in ("compression_watch", "yellow_watch", "v_reversal_watch", "trend_continuation", "stable")
        ),
    }


def build_scan_response(
    items: Iterable[dict[str, Any]],
    *,
    requested_symbols: Iterable[str],
    representative_items: Iterable[dict[str, Any]] = (),
    generated_at: Optional[str] = None,
    previous_response: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    current_generated_at = generated_at or datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    normalized_items = [copy.deepcopy(item) for item in items]
    requested = list(dict.fromkeys(str(symbol).upper() for symbol in requested_symbols))
    returned = [str(item.get("symbol") or "").upper() for item in normalized_items]
    market_modes = build_market_modes(normalized_items, representative_items)
    groups = {name: {"count": 0, "symbols": []} for name in PRIMARY_GROUPS}

    for item in normalized_items:
        market, market_context = _market_context(item, market_modes)
        pullback = _pullback_context(item)
        compression = _compression_context(item, market_context)
        v_reversal = _v_reversal_context(item)
        decision, primary_group, tags = _decision(item, market_context, pullback, compression, v_reversal)
        decision = _decorate_decision(item, decision)
        authorization = _authorization_context(item, decision)
        session_context = _session_context(item)
        execution_status = _execution_status(item, decision)
        if authorization is not None:
            authorization["status"] = execution_status.get("status")
        position_guidance = _position_guidance(item, execution_status)
        breakout_triggered = item.get("state") == "bull_flip"
        breakout = {
            "triggered": breakout_triggered,
            "signalDate": item.get("decisionAsOf") if breakout_triggered else None,
            "previousState": "bear" if breakout_triggered else None,
            "currentState": item.get("state"),
            "distanceAtr": _finite_float(item.get("distanceToSupertrendAtr")),
            "maxAcceptablePrice": decision.get("maxAcceptablePrice") if breakout_triggered else None,
            "stillExecutable": breakout_triggered and execution_status.get("executable") is True,
        }
        item.update({
            "market": market,
            "marketMode": market_context["mode"],
            "breakout": breakout,
            "pullback": pullback,
            "compressionBreakout": compression,
            "vReversal": v_reversal,
            "decision": decision,
            "sessionContext": session_context,
            "executionStatus": execution_status,
            "positionGuidance": position_guidance,
            "authorization": authorization,
            "primaryGroup": primary_group,
            "tags": tags,
            "theme": _symbol_theme(str(item.get("symbol") or "")),
            "tradingVenue": classify_trading_venue(str(item.get("symbol") or "")),
            "riskMarket": market,
            "assetClass": classify_asset_class(str(item.get("symbol") or "")),
            "lifecycle": _lifecycle_context(item, decision, execution_status),
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
        elif name in {"breakout_buy", "pullback_buy", "breakout_armed", "wait_confirmation", "compression_watch"}:
            group["symbols"].sort(key=lambda symbol: (
                -int((item_map[symbol].get("decision") or {}).get("readinessScore") or 0),
                _absolute_or_infinity(item_map[symbol].get("distanceToSupertrendAtr")),
                symbol,
            ))
        group["count"] = len(group["symbols"])

    changes = _build_changes(normalized_items, previous_response, current_generated_at)
    themes = _build_themes(normalized_items)
    attention = _build_attention(groups, item_map)

    return {
        "schemaVersion": SCHEMA_VERSION,
        "policyVersion": POLICY_VERSION,
        "includesCandles": True,
        "generatedAt": current_generated_at,
        "coverage": {
            "requested": len(requested),
            "returned": len(returned),
            "missing": [symbol for symbol in requested if symbol not in returned],
        },
        "thresholds": {
            "validationStatus": "cross_asset_heuristic_not_out_of_sample_validated",
            "compressionLiveTradingAllowed": False,
            "normalAdx": NORMAL_ADX_THRESHOLD,
            "cautiousAdx": CAUTIOUS_ADX_THRESHOLD,
            "breakoutMaxAtr": BREAKOUT_MAX_DISTANCE_ATR,
            "pullbackZoneAtr": PULLBACK_ZONE_ATR,
            "pullbackApproachingAtr": PULLBACK_APPROACHING_ATR,
            "compressionMaxDistanceAtr": COMPRESSION_MAX_DISTANCE_ATR,
            "compressionMaxTriggerSlippageAtr": COMPRESSION_MAX_TRIGGER_SLIPPAGE_ATR,
            "compressionNormalAdxMin": COMPRESSION_NORMAL_ADX_MIN,
            "compressionCautiousAdxMin": COMPRESSION_CAUTIOUS_ADX_MIN,
            "vReversalBollDistanceAtr": V_REVERSAL_BOLL_DISTANCE_ATR,
            "vReversalMaxVolumeRatio": V_REVERSAL_MAX_VOLUME_RATIO,
        },
        "marketModes": market_modes,
        "groups": groups,
        "attention": attention,
        "themes": themes,
        "changes": changes,
        "items": normalized_items,
    }
