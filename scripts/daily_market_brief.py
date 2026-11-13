#!/usr/bin/env python3
"""Build the short-cycle technical packet used by the daily-market-brief skill.

The backend remains the source of truth for prices and indicators.  This script
only reshapes the scan response, identifies deterministic changes worth sending
to Hermes, and keeps a tiny JSON ledger for five-trading-day AI forecasts.

Examples::

    python scripts/daily_market_brief.py --mode report
    python scripts/daily_market_brief.py --mode evaluate
    echo '{"forecasts": [...]}' | python scripts/daily_market_brief.py --mode record
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")
PRIMARY_SYMBOLS = ("510300.SS", "513100.SS", "518880.SS")
MARKET_REPRESENTATIVES = (
    ("A股", "000300.SS"),
    ("美股", "SPY"),
    ("BTC", "BTC-USD"),
    ("黄金", "518880.SS"),
)
ALIAS_FALLBACKS = {
    "000300.SS": "沪深300",
    "510300.SS": "沪深300ETF",
    "513100.SS": "纳指100ETF",
    "518880.SS": "黄金ETF",
    "BTC-USD": "BTC",
    "SPY": "标普500",
}
FORECAST_STANCES = {"bull", "bear", "neutral"}
CONFIDENCE_BUCKETS = (("high", 70), ("medium", 50), ("low", 0))


def _api_get(api_base: str, path: str, timeout: float) -> Any:
    request = Request(
        api_base.rstrip("/") + path,
        headers={"Accept": "application/json", "User-Agent": "daily-market-brief/1.0"},
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def _round(value: Any, digits: int = 4) -> float | None:
    number = _number(value)
    return round(number, digits) if number is not None else None


def _percent(value: float | None, digits: int = 2) -> float | None:
    return _round(value * 100, digits) if value is not None else None


def _history(item: dict[str, Any]) -> list[dict[str, Any]]:
    rows = item.get("decisionHistory") or []
    return [row for row in rows if isinstance(row, dict) and row.get("date")]


def _latest_close(item: dict[str, Any]) -> float | None:
    rows = _history(item)
    history_close = _number((rows[-1] if rows else {}).get("close"))
    return history_close if history_close is not None else _number(item.get("close"))


def _daily_change(item: dict[str, Any]) -> float | None:
    rows = _history(item)
    if len(rows) >= 2:
        current = _number(rows[-1].get("close"))
        previous = _number(rows[-2].get("close"))
        if current is not None and previous not in (None, 0):
            return current / previous - 1
    return None


def _candles(item: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row for row in item.get("candles") or []
        if isinstance(row, dict) and _number(row.get("close")) is not None
    ]


def _period_return(item: dict[str, Any], sessions: int) -> float | None:
    rows = _candles(item)
    if len(rows) <= sessions:
        return None
    latest = _number(rows[-1].get("close"))
    earlier = _number(rows[-sessions - 1].get("close"))
    if latest is None or earlier in (None, 0):
        return None
    return latest / earlier - 1


def _ema(values: list[float], span: int) -> float | None:
    if not values:
        return None
    alpha = 2 / (span + 1)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1 - alpha) * result
    return result


def _moving_average_position(item: dict[str, Any]) -> dict[str, Any]:
    rows = _candles(item)
    closes = [float(_number(row["close"])) for row in rows]
    close = closes[-1] if closes else _latest_close(item)
    result: dict[str, Any] = {}
    for span in (20, 50):
        average = _ema(closes, span) if len(closes) >= span else None
        result[f"ema{span}"] = _round(average, 6)
        result[f"aboveEma{span}"] = close is not None and average is not None and close >= average
        result[f"distanceToEma{span}Pct"] = _round((close / average - 1) * 100, 2) if close and average else None
    return result


def _volume_ratio(item: dict[str, Any]) -> float | None:
    context = item.get("volumeContext") or {}
    completed = _number(context.get("ratio20Completed"))
    return completed if completed is not None else _number(context.get("ratio20"))


def _macd_direction(item: dict[str, Any]) -> str | None:
    indicators = item.get("indicators") or {}
    hist = _number(indicators.get("macdHist"))
    previous = _number(indicators.get("macdHistPrev"))
    if hist is None:
        return None
    if previous is not None and hist * previous < 0:
        return "上穿" if hist > 0 else "下穿"
    delta = _number(indicators.get("macdHistDelta"))
    if delta is None:
        return "正" if hist > 0 else "负"
    return "改善" if delta > 0 else "转弱" if delta < 0 else "走平"


def _market_temperature(item: dict[str, Any]) -> dict[str, Any]:
    indicators = item.get("indicators") or {}
    close = _latest_close(item)
    mid = _number(indicators.get("bollMid"))
    rsi = _number(indicators.get("rsi14"))
    hist = _number(indicators.get("macdHist"))
    score = 0
    state = str(item.get("state") or "")
    if state in {"bull", "bull_flip"}:
        score += 1
    elif state in {"bear", "bear_flip"}:
        score -= 1
    if close is not None and mid not in (None, 0):
        score += 1 if close > mid else -1
    if rsi is not None:
        score += 1 if rsi >= 55 else -1 if rsi <= 45 else 0
    if hist is not None:
        score += 1 if hist > 0 else -1
    label = "偏强" if score >= 2 else "偏弱" if score <= -2 else "中性"
    return {
        "market": item.get("_market"),
        "symbol": item.get("symbol"),
        "name": item.get("alias") or ALIAS_FALLBACKS.get(item.get("symbol"), item.get("symbol")),
        "asOfDate": item.get("latestDataDate"),
        "temperature": label,
        "score": score,
        "state": item.get("state"),
        "change1dPct": _percent(_daily_change(item)),
        "change5dPct": _percent(_period_return(item, 5)),
        "change20dPct": _percent(_period_return(item, 20)),
        **_moving_average_position(item),
        "rsi14": _round(rsi, 1),
        "macd": _macd_direction(item),
        "volumeRatio20": _round(_volume_ratio(item), 2),
        "bollSqueeze": bool(item.get("bollSqueeze") or item.get("bollSqueezeRecent")),
        "distanceToSupertrendPct": _round(item.get("signedDistanceToSupertrendPct"), 2),
    }


def _recent_flip(item: dict[str, Any]) -> bool:
    rows = _history(item)
    if len(rows) < 2:
        return False
    current_state = str(item.get("state") or "")
    previous_state = str(rows[-2].get("state") or "")
    return current_state in {"bull", "bull_flip", "bear", "bear_flip"} and previous_state in {
        "bull", "bull_flip", "bear", "bear_flip"
    } and (current_state.startswith("bull") != previous_state.startswith("bull"))


def _anomaly(item: dict[str, Any], *, primary: bool = False) -> dict[str, Any] | None:
    indicators = item.get("indicators") or {}
    change = _daily_change(item)
    rsi = _number(indicators.get("rsi14"))
    volume = _volume_ratio(item)
    hist = _number(indicators.get("macdHist"))
    hist_prev = _number(indicators.get("macdHistPrev"))
    reasons: list[str] = []
    score = 0

    if item.get("justFlipped") or _recent_flip(item):
        reasons.append("日线趋势转向")
        score += 4
    if item.get("weeklyJustFlipped"):
        reasons.append("周线趋势转向")
        score += 3
    if change is not None:
        threshold = 0.05 if item.get("isCrypto") else 0.03 if item.get("market") in {"us", "hong_kong"} else 0.02
        if abs(change) >= threshold:
            reasons.append(f"单日变动 {change * 100:+.1f}%")
            score += 2
    if volume is not None and (volume >= 1.5 or volume <= 0.7):
        reasons.append("成交量明显偏离20日均量")
        score += 1
    if rsi is not None and (rsi <= 30 or rsi >= 70):
        reasons.append(f"RSI14 {'偏低' if rsi <= 30 else '偏高'}")
        score += 1
    if hist is not None and hist_prev is not None and hist * hist_prev < 0:
        reasons.append("MACD柱翻正/翻负")
        score += 2
    if item.get("bollSqueezeRecent") and change is not None and abs(change) >= 0.015:
        reasons.append("布林带收窄后出现价格变化")
        score += 1
    if str(item.get("alertPriority") or "") == "high":
        score += 2
    elif str(item.get("alertPriority") or "") == "medium":
        score += 1

    if not primary and score < 2:
        return None
    return {
        "symbol": item.get("symbol"),
        "name": item.get("alias") or ALIAS_FALLBACKS.get(item.get("symbol"), item.get("symbol")),
        "asOfDate": item.get("latestDataDate"),
        "primary": primary,
        "score": score,
        "reasons": reasons or ["主策略品种每日观察"],
        "state": item.get("state"),
        "weeklyState": item.get("weeklyState"),
        "close": _round(_latest_close(item), 6),
        "change1dPct": _percent(change),
        "change5dPct": _percent(_period_return(item, 5)),
        "change20dPct": _percent(_period_return(item, 20)),
        **_moving_average_position(item),
        "rsi7": _round(indicators.get("rsi7"), 1),
        "rsi14": _round(rsi, 1),
        "macd": _macd_direction(item),
        "macdHist": _round(hist, 6),
        "volumeRatio20": _round(volume, 2),
        "bollWidth": _round(indicators.get("bollWidth"), 4),
        "bollSqueezeRecent": bool(item.get("bollSqueezeRecent")),
        "distanceToSupertrendPct": _round(item.get("signedDistanceToSupertrendPct"), 2),
        "technicalPermission": (item.get("decision") or {}).get("permission"),
        "dataQuality": {
            "latestDataDate": item.get("latestDataDate"),
            "dataStale": item.get("dataStale"),
            "cacheStale": item.get("cacheStale"),
            "dailySessionComplete": item.get("dailySessionComplete"),
        },
    }


def _default_ledger_path() -> Path:
    override = os.environ.get("AI_FORECAST_LEDGER_PATH")
    if override:
        return Path(override)
    script_root = Path(__file__).resolve().parents[1]
    local = script_root / "backend" / "data"
    if local.exists() or (script_root / "backend").exists():
        return local / "ai_forecasts.json"
    container = Path("/app/data")
    if container.exists() or Path("/app").exists():
        return container / "ai_forecasts.json"
    return Path("data/ai_forecasts.json")


def _load_ledger(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        value = {}
    if not isinstance(value, dict):
        value = {}
    value.setdefault("schemaVersion", 1)
    value.setdefault("forecasts", [])
    value.setdefault("evaluations", [])
    return value


def _write_ledger(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _with_ledger_lock(path: Path):
    lock = path.with_suffix(path.suffix + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    handle = lock.open("a+")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle


def _summary(state: dict[str, Any]) -> dict[str, Any]:
    evaluations = [row for row in state.get("evaluations", []) if row.get("scored")]
    recent = evaluations[-30:]
    result: dict[str, Any] = {
        "completed": len(recent),
        "correct": sum(bool(row.get("correct")) for row in recent),
        "accuracyPct": round(100 * sum(bool(row.get("correct")) for row in recent) / len(recent), 1) if recent else None,
        "byConfidence": {},
    }
    for bucket, _ in CONFIDENCE_BUCKETS:
        rows = [row for row in recent if row.get("confidenceBucket") == bucket]
        result["byConfidence"][bucket] = {
            "completed": len(rows),
            "correct": sum(bool(row.get("correct")) for row in rows),
            "accuracyPct": round(100 * sum(bool(row.get("correct")) for row in rows) / len(rows), 1) if rows else None,
        }
    result["pending"] = sum(1 for row in state.get("forecasts", []) if row.get("status") == "pending")
    return result


def _confidence_bucket(value: float) -> str:
    return "high" if value >= 70 else "medium" if value >= 50 else "low"


def _scan_payload(api_base: str, timeout: float) -> dict[str, Any]:
    payload = _api_get(api_base, "/supertrend/scan?force=false&include_candles=true", timeout)
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("SuperTrend scan returned an invalid payload")
    return payload


def _primary_strategy(api_base: str, timeout: float) -> dict[str, Any] | None:
    """Return a compact primary-account status without duplicating the renderer."""
    try:
        strategies = _api_get(api_base, "/portfolio-strategies", timeout)
        primary = next((row for row in strategies if row.get("isPrimary")), None)
        if not primary:
            return None
        snapshot = _api_get(api_base, f"/portfolio-strategies/{primary['strategyId']}/snapshot", timeout)
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return {"status": "unavailable"}
    operations = snapshot.get("operations") or {}
    orders = [
        order for order in operations.get("orders") or []
        if order.get("due") or order.get("status") in {"PENDING", "WAITING_OPEN", "DELAYED"}
    ]
    nav = snapshot.get("nav") or {}
    weights = snapshot.get("currentWeights") or []
    cash_weight = next(
        (_number(row.get("weight")) or 0.0 for row in weights if row.get("symbol") == "CASH"),
        0.0,
    )
    return {
        "strategyId": primary.get("strategyId"),
        "status": snapshot.get("state"),
        "accountStatus": "未建仓：账户全部是现金" if cash_weight >= 0.99 else "已建仓",
        "signalDate": (snapshot.get("dates") or {}).get("signalDate"),
        "nextCheck": (snapshot.get("dates") or {}).get("nextCheck"),
        "marketDataDate": (snapshot.get("dates") or {}).get("marketDataDate"),
        "nav": {
            "netNav": _round(nav.get("netNav"), 2),
            "dailyReturnPct": _round((_number(nav.get("dailyReturn")) or 0) * 100, 2),
            "drawdownPct": _round((_number(nav.get("drawdown")) or 0) * 100, 2),
        },
        "currentWeights": weights,
        "pendingOrders": orders,
        "ledgerStatus": (snapshot.get("ledger") or {}).get("status"),
        "diagnostics": snapshot.get("diagnostics") or [],
        "calcError": snapshot.get("calcError"),
        "dataQualityEventCount": operations.get("dataQualityEventCount", 0),
    }


def build_report(payload: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    items = [item for item in payload.get("items", []) if isinstance(item, dict) and item.get("symbol")]
    by_symbol = {str(item["symbol"]).upper(): item for item in items}
    markets = []
    for market, symbol in MARKET_REPRESENTATIVES:
        item = by_symbol.get(symbol)
        if item:
            item = {**item, "_market": market}
            markets.append(_market_temperature(item))
    primary = []
    for symbol in PRIMARY_SYMBOLS:
        item = by_symbol.get(symbol)
        if item:
            primary_item = _anomaly(item, primary=True)
            if primary_item:
                primary.append(primary_item)
    anomalies = []
    for item in items:
        if str(item.get("symbol")).upper() in PRIMARY_SYMBOLS:
            continue
        row = _anomaly(item)
        if row:
            anomalies.append(row)
    anomalies.sort(key=lambda row: (-int(row.get("score") or 0), str(row.get("symbol"))))
    # A 47-symbol watchlist can have many low-grade volume/squeeze flags on a
    # volatile day.  Keep the packet readable and let Hermes focus on the
    # strongest twelve; the omitted count remains visible for auditability.
    anomaly_limit = 12
    as_of_dates = [item.get("latestDataDate") for item in items if item.get("latestDataDate")]
    return {
        "schemaVersion": 1,
        "reportType": "daily_market_brief",
        "generatedAt": datetime.now(SHANGHAI).isoformat(),
        "asOfDate": max(as_of_dates) if as_of_dates else None,
        "coverage": payload.get("coverage"),
        "source": "backend /api/supertrend/scan",
        "primaryStrategy": None,
        "marketTemperature": markets,
        "primaryWatch": primary,
        "anomalies": anomalies[:anomaly_limit],
        "anomalyCount": min(len(anomalies), anomaly_limit),
        "omittedAnomalyCount": max(0, len(anomalies) - anomaly_limit),
        "overviewPrompt": (
            "根据 marketTemperature、primaryWatch 和 anomalies 写 3 到 5 句大局判断。"
            "只用技术数据，不搜索新闻；按结构、动能、量价顺序解释，说明哪些信号互相支持或冲突。"
            "不要把观察写成主策略调仓指令，不给 A 股个股买卖建议。"
        ),
        "forecastInstructions": {
            "horizonTradingDays": 5,
            "scope": "anomalies 加 primaryWatch 中的每个品种各给一个 bull、bear 或 neutral 判断及 0 到 100 置信度",
            "scoring": "只有 bull/bear 计入成绩；5 个交易日后用真实收盘价判断方向，neutral 不计分",
            "recordCommand": "把 forecasts JSON 通过 stdin 交给 daily_market_brief.py --mode record",
        },
        "forecastLedger": _summary(state),
    }


def _evaluate_pending(state: dict[str, Any], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_symbol = {str(item.get("symbol")).upper(): item for item in items}
    created: list[dict[str, Any]] = []
    for forecast in state.get("forecasts", []):
        if forecast.get("status") != "pending":
            continue
        item = by_symbol.get(str(forecast.get("symbol") or "").upper())
        if not item:
            continue
        if item.get("dailySessionComplete") is False or item.get("dataStale") is True:
            continue
        dates_prices = [
            (str(row.get("date")), _number(row.get("close")))
            for row in _history(item)
            if _number(row.get("close")) is not None
        ]
        future = [(date, price) for date, price in dates_prices if date > str(forecast.get("entryDate") or "")]
        horizon = max(1, int(forecast.get("horizonTradingDays") or 5))
        if len(future) < horizon:
            continue
        target_date, target_price = future[horizon - 1]
        entry_price = _number(forecast.get("entryPrice"))
        if entry_price in (None, 0) or target_price is None:
            continue
        stance = forecast.get("stance")
        correct = target_price > entry_price if stance == "bull" else target_price < entry_price if stance == "bear" else None
        evaluation = {
            "forecastId": forecast.get("forecastId"),
            "symbol": forecast.get("symbol"),
            "entryDate": forecast.get("entryDate"),
            "targetDate": target_date,
            "entryPrice": entry_price,
            "targetPrice": target_price,
            "stance": stance,
            "confidence": forecast.get("confidence"),
            "confidenceBucket": forecast.get("confidenceBucket"),
            "correct": correct,
            "scored": correct is not None,
            "returnPct": round((target_price / entry_price - 1) * 100, 4),
            "evaluatedAt": datetime.now(SHANGHAI).isoformat(),
        }
        forecast["status"] = "scored" if correct is not None else "excluded"
        forecast["evaluation"] = evaluation
        state.setdefault("evaluations", []).append(evaluation)
        created.append(evaluation)
    return created


def record_forecasts(api_base: str, timeout: float, path: Path, request: dict[str, Any]) -> dict[str, Any]:
    payload = _scan_payload(api_base, timeout)
    by_symbol = {str(item.get("symbol")).upper(): item for item in payload.get("items", [])}
    forecasts = request.get("forecasts") if isinstance(request, dict) else None
    if not isinstance(forecasts, list) or not forecasts:
        raise ValueError("record expects {\"forecasts\": [{...}]} on stdin")
    lock = _with_ledger_lock(path)
    try:
        state = _load_ledger(path)
        added = []
        for row in forecasts:
            if not isinstance(row, dict):
                raise ValueError("each forecast must be an object")
            symbol = str(row.get("symbol") or "").upper()
            item = by_symbol.get(symbol)
            stance = str(row.get("stance") or "").lower()
            confidence = _number(row.get("confidence"))
            if not item or stance not in FORECAST_STANCES or confidence is None or not 0 <= confidence <= 100:
                raise ValueError(f"invalid forecast for {symbol or '?'}")
            entry_date = str(item.get("latestDataDate") or "")
            entry_price = _latest_close(item)
            if not entry_date or entry_price is None:
                raise ValueError(f"no complete close available for {symbol}")
            if item.get("dailySessionComplete") is False or item.get("dataStale") is True:
                raise ValueError(f"latest daily bar is not complete/fresh for {symbol}")
            duplicate = next(
                (existing for existing in state["forecasts"] if existing.get("symbol") == symbol and existing.get("entryDate") == entry_date),
                None,
            )
            if duplicate:
                continue
            forecast = {
                "forecastId": f"{entry_date}:{symbol}",
                "symbol": symbol,
                "name": item.get("alias") or ALIAS_FALLBACKS.get(symbol, symbol),
                "entryDate": entry_date,
                "entryPrice": entry_price,
                "stance": stance,
                "confidence": round(confidence, 1),
                "confidenceBucket": _confidence_bucket(confidence),
                "reason": str(row.get("reason") or ""),
                "horizonTradingDays": int(row.get("horizonTradingDays") or 5),
                "status": "pending",
                "recordedAt": datetime.now(SHANGHAI).isoformat(),
            }
            if forecast["horizonTradingDays"] < 1:
                raise ValueError(f"horizonTradingDays must be positive for {symbol}")
            state["forecasts"].append(forecast)
            added.append(forecast)
        _write_ledger(path, state)
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()
    return {"added": added, "ledgerPath": str(path), "summary": _summary(state)}


def evaluate_forecasts(api_base: str, timeout: float, path: Path) -> dict[str, Any]:
    payload = _scan_payload(api_base, timeout)
    lock = _with_ledger_lock(path)
    try:
        state = _load_ledger(path)
        completed = _evaluate_pending(state, payload.get("items", []))
        _write_ledger(path, state)
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()
    return {"completed": completed, "ledgerPath": str(path), "summary": _summary(state)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the daily technical market brief and score AI forecasts.")
    parser.add_argument("--mode", choices=("report", "record", "evaluate"), required=True)
    parser.add_argument("--api-base", default=os.environ.get("TRADING_API_BASE", "http://127.0.0.1:8000/api"))
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--ledger-path", type=Path, default=_default_ledger_path())
    args = parser.parse_args()
    try:
        if args.mode == "record":
            request = json.load(__import__("sys").stdin)
            result = record_forecasts(args.api_base, args.timeout, args.ledger_path, request)
        elif args.mode == "evaluate":
            result = evaluate_forecasts(args.api_base, args.timeout, args.ledger_path)
        else:
            payload = _scan_payload(args.api_base, args.timeout)
            state = _load_ledger(args.ledger_path)
            result = build_report(payload, state)
            result["source"] = args.api_base.rstrip("/")
            result["primaryStrategy"] = _primary_strategy(args.api_base, args.timeout)
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
