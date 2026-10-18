#!/usr/bin/env python3
"""Fetch structured trading data for Claude Code deep analysis.

Unlike openclaw_supertrend_alerts.py (which produces polished daily briefs),
this script outputs raw structured JSON optimized for Claude to interpret.

Usage:
  # Single stock deep dive
  uv run python scripts/trading_analysis_helper.py --query stock --symbol 510300.SS

  # Full SuperTrend scan grouped
  uv run python scripts/trading_analysis_helper.py --query scan --grouped

  # Portfolio strategy snapshot
  uv run python scripts/trading_analysis_helper.py --query portfolio --strategy btc_supertrend_satellite

  # All portfolio strategies summary
  uv run python scripts/trading_analysis_helper.py --query portfolio

  # Market overview (scan + portfolio combined, compact)
  uv run python scripts/trading_analysis_helper.py --query overview

  # Weekly BOLL squeeze/breakout scan
  uv run python scripts/trading_analysis_helper.py --query squeeze

  # Weekend review: primary strategy + Weinstein stages by market (a few KB)
  uv run python scripts/trading_analysis_helper.py --query weekly

  # Compact single-symbol brief: Weinstein view + SuperTrend decision essentials
  uv run python scripts/trading_analysis_helper.py --query brief --symbol QQQ
"""

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


def _api_get(api_base: str, path: str, timeout: float = 20.0) -> Any:
    url = api_base.rstrip("/") + path
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "trading-analysis-helper/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Stock deep dive
# ---------------------------------------------------------------------------

INDICATOR_KEYS = [
    "price", "close", "ema20", "ema50", "adx", "rsi", "rsi7", "rsi14", "rsi21",
    "macdDif", "macdDea", "macdHist", "macdHistPrev", "macdHistDelta",
    "bollUpper", "bollMid", "bollLower", "bollWidth", "bollSqueeze", "bollSqueezeRecent", "bollWidthRatio20",
    "kdjK", "kdjD", "kdjJ",
    "atr", "stVal", "stDir",
    "ma30", "ma200",
]

SIGNAL_KEYS = [
    "buySignal", "stopPrice", "targetPrice", "strategyVersion",
    "pullbackSignal", "exitSignal", "weeklyMarkers",
]

SUPERTREND_KEYS = [
    "state", "dailyProvisionalState", "decisionDailyState", "decisionAsOf",
    "decisionDailyAvailable", "weeklyState", "weeklyProvisionalState",
    "weeklyPeriodComplete", "justFlipped", "weeklyJustFlipped",
    "trendAgeBars", "distanceToSupertrendPct", "distanceToSupertrendAtr",
    "alertType", "alertLabel", "alertPriority", "alertReason", "suggestedAction",
    "opportunityStage", "opportunityLabel", "opportunityReason",
    "close", "stVal", "weeklyStVal", "breakout", "pullback", "compressionBreakout", "vReversal",
    "decisionHistory", "lifecycle", "theme", "transition",
]


def _extract_indicators(quote: dict) -> dict:
    result = dict(quote.get("indicators") or {})
    for key in INDICATOR_KEYS:
        if key in quote and key not in result:
            result[key] = quote[key]
    if quote.get("candles"):
        latest = quote["candles"][-1]
        candle_keys = {
            "close": "close", "ema20": "ema20", "ema50": "ema50",
            "boll_upper": "bollUpper", "boll_mid": "bollMid",
            "boll_lower": "bollLower", "atr": "atr", "st_val": "stVal",
            "st_dir": "stDir",
        }
        for source, target in candle_keys.items():
            if target not in result and latest.get(source) is not None:
                result[target] = latest[source]
    # Signals
    result["signals"] = {k: quote.get(k) for k in SIGNAL_KEYS if k in quote and quote.get(k) is not None}
    return result


def query_stock(api_base: str, symbol: str, timeout: float) -> dict:
    quote = _api_get(api_base, f"/quote/{symbol}", timeout)
    if quote.get("schemaVersion") != 2 or not isinstance(quote.get("decision"), dict):
        raise ValueError("Stock quote returned without the unified decision contract")
    return {
        "schemaVersion": quote.get("schemaVersion"),
        "policyVersion": quote.get("policyVersion"),
        "symbol": symbol.upper(),
        "alias": quote.get("alias", ""),
        "indicators": _extract_indicators(quote),
        "supertrend": {k: quote.get(k) for k in SUPERTREND_KEYS if k in quote},
        "decision": quote.get("decision"),
        "sessionContext": quote.get("sessionContext"),
        "executionStatus": quote.get("executionStatus"),
        "positionGuidance": quote.get("positionGuidance"),
        "authorization": quote.get("authorization"),
        "primaryGroup": quote.get("primaryGroup"),
        "market": quote.get("market"),
        "riskMarket": quote.get("riskMarket"),
        "tradingVenue": quote.get("tradingVenue"),
        "assetClass": quote.get("assetClass"),
        "marketMode": quote.get("marketMode"),
        "marketModeContext": quote.get("marketModeContext"),
        "dataQuality": {
            key: quote.get(key)
            for key in (
                "latestDataDate", "dataUpdatedAt", "cacheStale", "dataStale",
                "dataIntegrity", "dailySessionComplete", "volumeContext",
            )
        },
        "weeklyBoll": quote.get("weeklyBoll"),
        "monthlyBoll": quote.get("monthlyBoll"),
        "macdDivergence": quote.get("macdDivergence"),
        "signals": {k: quote.get(k) for k in SIGNAL_KEYS if k in quote and quote.get(k) not in (None, False)},
        "fetchedAt": quote.get("decisionGeneratedAt") or datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
    }


# ---------------------------------------------------------------------------
# SuperTrend scan
# ---------------------------------------------------------------------------

# Market indices for environment summary
MARKET_INDICES = ["000001.SS", "000300.SS", "510500.SS", "588000.SS", "159553.SZ"]
MARKET_INDEX_LABELS = {
    "000001.SS": "上证指数",
    "000300.SS": "沪深300",
    "510500.SS": "中证500",
    "588000.SS": "科创50",
    "159553.SZ": "中证2000",
}

def _build_symbol_entry(m: dict) -> dict:
    """Build a compact symbol entry with quality indicators."""
    ind = m.get("indicators", {})
    # Direction means the histogram is rising/falling, not merely positive/negative.
    macd_delta = ind.get("macdHistDelta")
    macd_prev = ind.get("macdHistPrev")
    tolerance = max(1e-9, abs(float(macd_prev or 0)) * 0.01)
    if macd_delta is None:
        macd_dir = None
    elif float(macd_delta) > tolerance:
        macd_dir = "↑"
    elif float(macd_delta) < -tolerance:
        macd_dir = "↓"
    else:
        macd_dir = "→"

    entry = {
        "symbol": m.get("symbol"),
        "alias": m.get("alias", ""),
        "state": m.get("state"),
        "weeklyState": m.get("weeklyState"),
        "weeklyProvisionalState": m.get("weeklyProvisionalState"),
        "weeklyPeriodComplete": m.get("weeklyPeriodComplete"),
        "alertType": m.get("alertType"),
        "alertLabel": m.get("alertLabel"),
        "alertPriority": m.get("alertPriority"),
        "distanceToSupertrendPct": m.get("distanceToSupertrendPct"),
        "distanceToSupertrendAtr": m.get("distanceToSupertrendAtr"),
        "opportunityStage": m.get("opportunityStage"),
        "opportunityLabel": m.get("opportunityLabel"),
        "alertReason": m.get("alertReason"),
        "suggestedAction": m.get("suggestedAction"),
        "trendAgeBars": m.get("trendAgeBars"),
        "weeklyTrendAgeBars": m.get("weeklyTrendAgeBars"),
        "market": m.get("market"),
        "riskMarket": m.get("riskMarket"),
        "tradingVenue": m.get("tradingVenue"),
        "assetClass": m.get("assetClass"),
        "marketMode": m.get("marketMode"),
        "dailySessionComplete": m.get("dailySessionComplete"),
        "decision": m.get("decision"),
        "sessionContext": m.get("sessionContext"),
        "executionStatus": m.get("executionStatus"),
        "positionGuidance": m.get("positionGuidance"),
        "authorization": m.get("authorization"),
        "primaryGroup": m.get("primaryGroup"),
        "tags": m.get("tags", []),
        "breakout": m.get("breakout"),
        "pullback": m.get("pullback"),
        "compressionBreakout": m.get("compressionBreakout"),
        "vReversal": m.get("vReversal"),
        "lifecycle": m.get("lifecycle"),
        "decisionHistory": m.get("decisionHistory"),
        "theme": m.get("theme"),
        "transition": m.get("transition"),
        # Quality indicators
        "adx": ind.get("adx"),
        "adxPrev": ind.get("adxPrev"),
        "adxDelta": ind.get("adxDelta"),
        "rsi21": ind.get("rsi21"),
        "rsi7": ind.get("rsi7"),
        "macdHist": ind.get("macdHist"),
        "macdHistPrev": macd_prev,
        "macdHistDelta": macd_delta,
        "macdDir": macd_dir,
        "macdDivergence": m.get("macdDivergence"),
        "kdjK": ind.get("kdjK"),
        "kdjD": ind.get("kdjD"),
        "kdjJ": ind.get("kdjJ"),
        "weeklyStVal": m.get("weeklyStVal"),
        "close": m.get("close"),
        "stVal": m.get("stVal"),
        "atr": ind.get("atr"),
        "dailyBoll": {
            "upper": ind.get("bollUpper"),
            "mid": ind.get("bollMid"),
            "lower": ind.get("bollLower"),
        },
        "bollWidth": m.get("bollWidth"),
        "bollSqueeze": m.get("bollSqueeze", False),
        "bollSqueezeRecent": m.get("bollSqueezeRecent", False),
        "weeklyBoll": m.get("weeklyBoll"),
        "monthlyBoll": m.get("monthlyBoll"),
        "volumeContext": m.get("volumeContext"),
        "latestDataDate": m.get("latestDataDate"),
        "dataUpdatedAt": m.get("dataUpdatedAt"),
        "cacheStale": m.get("cacheStale"),
        "dataStale": m.get("dataStale"),
        "dataIntegrity": m.get("dataIntegrity"),
    }
    return entry


def query_scan(api_base: str, timeout: float, grouped: bool = True, force: bool = False) -> dict:
    force_str = "true" if force else "false"
    payload = _api_get(
        api_base,
        f"/supertrend/scan?force={force_str}&include_candles=false",
        timeout,
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("SuperTrend scan returned an invalid schema-v2 payload")
    items = payload["items"]
    result: dict[str, Any] = {
        "total": len(items),
        "fetchedAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "schemaVersion": payload.get("schemaVersion"),
        "policyVersion": payload.get("policyVersion"),
        "generatedAt": payload.get("generatedAt"),
        "coverage": payload.get("coverage"),
        "thresholds": payload.get("thresholds"),
        "marketModes": payload.get("marketModes"),
        "attention": payload.get("attention"),
        "themes": payload.get("themes"),
        "changes": payload.get("changes"),
    }

    if not grouped:
        return payload

    # Build lookup for market indices
    item_map = {i.get("symbol", ""): i for i in items}

    # Market environment summary
    market_symbols = []
    for sym in MARKET_INDICES:
        if sym in item_map:
            m = item_map[sym]
            ind = m.get("indicators", {})
            entry = _build_symbol_entry(m)
            market_symbols.append({
                "symbol": sym,
                "alias": m.get("alias", "") or MARKET_INDEX_LABELS.get(sym, ""),
                "state": m.get("state"),
                "close": m.get("close"),
                "trendAgeBars": m.get("trendAgeBars"),
                "distanceToSupertrendPct": m.get("distanceToSupertrendPct"),
                "distanceToSupertrendAtr": m.get("distanceToSupertrendAtr"),
                "adx": ind.get("adx"),
                "rsi21": ind.get("rsi21"),
                "macdHist": ind.get("macdHist"),
                "macdHistPrev": ind.get("macdHistPrev"),
                "macdHistDelta": ind.get("macdHistDelta"),
                "macdDir": entry.get("macdDir"),
                "macdDivergence": m.get("macdDivergence"),
                "kdjK": ind.get("kdjK"),
                "kdjD": ind.get("kdjD"),
                "kdjJ": ind.get("kdjJ"),
                "weeklyBoll": m.get("weeklyBoll"),
                "monthlyBoll": m.get("monthlyBoll"),
                "volumeContext": m.get("volumeContext"),
                "latestDataDate": m.get("latestDataDate"),
                "dataUpdatedAt": m.get("dataUpdatedAt"),
                "cacheStale": m.get("cacheStale"),
                "dataStale": m.get("dataStale"),
                "dataIntegrity": m.get("dataIntegrity"),
            })
    result["market"] = {
        "indices": market_symbols,
        "summary": "",  # Claude fills this in during presentation
    }

    result["groups"] = {}
    for name, group in (payload.get("groups") or {}).items():
        symbols = [symbol for symbol in group.get("symbols", []) if symbol in item_map]
        result["groups"][name] = {
            "count": len(symbols),
            "symbols": symbols,
        }
    result["allSymbols"] = [_build_symbol_entry(item) for item in items]

    return result


# ---------------------------------------------------------------------------
# Portfolio strategies
# ---------------------------------------------------------------------------


def query_portfolio(api_base: str, timeout: float, strategy_id: Optional[str] = None) -> dict:
    if strategy_id:
        snap = _api_get(api_base, f"/portfolio-strategies/{strategy_id}/snapshot", timeout)
        # Also get NAV history
        try:
            nav = _api_get(api_base, f"/portfolio-strategies/{strategy_id}/nav", timeout)
        except Exception:
            nav = {"points": []}
        return {
            "strategyId": strategy_id,
            "snapshot": snap,
            "navTail": nav.get("points", [])[-10:] if nav.get("points") else [],
            "fetchedAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        }

    # List all + snapshots
    strategies = _api_get(api_base, "/portfolio-strategies", timeout)
    results = []
    for st in strategies:
        if not st.get("paperEnabled"):
            continue
        try:
            snap = _api_get(api_base, f"/portfolio-strategies/{st['strategyId']}/snapshot", timeout)
        except Exception:
            snap = {"state": "UNAVAILABLE"}
        results.append({
            "strategyId": st["strategyId"],
            "displayName": st["displayName"],
            "bootstrapped": st.get("bootstrapped", False),
            "snapshot": snap,
        })
    return {
        "strategies": results,
        "fetchedAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
    }


def _annotate_scan_with_portfolio(scan: dict, portfolio: dict) -> dict:
    """Keep technical permission immutable and add strategy-scoped execution context."""
    symbol_contexts: dict[str, list[dict]] = {}
    for strategy in portfolio.get("strategies", []):
        snapshot = strategy.get("snapshot") or {}
        strategy_id = strategy.get("strategyId")
        state = snapshot.get("state", "UNAVAILABLE")
        current = {row.get("symbol"): row for row in snapshot.get("currentWeights", [])}
        desired = {row.get("symbol"): row for row in snapshot.get("desiredWeights", [])}
        executable = {row.get("symbol"): row for row in snapshot.get("executableWeights", [])}
        delta = {row.get("symbol"): row for row in snapshot.get("deltaWeights", [])}
        for asset in snapshot.get("assets", []):
            symbol = str(asset.get("symbol") or "").upper()
            if not symbol:
                continue
            if state == "BLOCKED":
                permission = "blocked"
            elif symbol in executable:
                permission = "executable"
            else:
                permission = "no_rebalance"
            symbol_contexts.setdefault(symbol, []).append({
                "strategyId": strategy_id,
                "displayName": strategy.get("displayName"),
                "state": state,
                "permission": permission,
                "currentWeight": (current.get(symbol) or {}).get("weight"),
                "desiredWeight": (desired.get(symbol) or {}).get("weight"),
                "deltaWeight": (delta.get(symbol) or {}).get("delta"),
                "executableWeight": (executable.get(symbol) or {}).get("weight"),
                "ledgerStatus": (snapshot.get("ledger") or {}).get("status"),
                "diagnostics": [
                    diagnostic
                    for diagnostic in snapshot.get("diagnostics", [])
                    if diagnostic.get("symbol") in {None, symbol}
                ],
            })

    matrix = []
    for item in scan.get("allSymbols", []):
        symbol = str(item.get("symbol") or "").upper()
        contexts = symbol_contexts.get(symbol, [])
        if not contexts:
            status = "unmanaged"
        else:
            permissions = {context["permission"] for context in contexts}
            if len(permissions) > 1:
                status = "mixed"
            elif "executable" in permissions:
                status = "executable"
            elif "blocked" in permissions:
                status = "blocked"
            else:
                status = "no_rebalance"
        item["portfolioExecution"] = {
            "status": status,
            "contexts": contexts,
            "technicalPermissionUnchanged": True,
        }
        if contexts:
            matrix.append({
                "symbol": symbol,
                "technicalPermission": (item.get("decision") or {}).get("permission"),
                "portfolioPermission": status,
                "contexts": contexts,
            })
    scan["portfolioMatrix"] = matrix
    return scan


# ---------------------------------------------------------------------------
# Overview (compact combined)
# ---------------------------------------------------------------------------


def query_squeeze(api_base: str, timeout: float) -> dict:
    """Scan for weekly BOLL squeeze/breakout/pullback candidates."""
    items = _api_get(api_base, "/weekly-breakout/scan", timeout)
    result: dict[str, Any] = {
        "total": len(items),
        "fetchedAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
    }
    grouped: dict[str, list[dict]] = {"squeeze": [], "breakout": [], "pullback": [], "exit": [], "neutral": []}
    for r in items:
        state = r.get("state", "neutral")
        if state in grouped:
            grouped[state].append(r)
    result["groups"] = grouped
    return result


def query_overview(api_base: str, timeout: float, force: bool = False) -> dict:
    """Get a compact market overview: scan summary + portfolio summary."""
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        scan_future = executor.submit(query_scan, api_base, timeout, grouped=True, force=force)
        portfolio_future = executor.submit(query_portfolio, api_base, timeout)

        scan = scan_future.result()
        portfolio = portfolio_future.result()

    return {
        "supertrend": _annotate_scan_with_portfolio(scan, portfolio),
        "portfolio": portfolio,
        "fetchedAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
    }


# ---------------------------------------------------------------------------
# Weekly review and single-symbol brief (compact; Weinstein first)
# ---------------------------------------------------------------------------

BENCHMARKS = ("000300.SS", "SPY", "QQQ", "BTC-USD", "518880.SS")


def market_of(symbol: str) -> str:
    upper = symbol.upper()
    if upper.endswith("-USD"):
        return "crypto"
    if upper.endswith((".SS", ".SZ", ".HK")):
        return "cn"
    if "=" in upper or upper.startswith("^"):
        return "other"
    return "us"


def _pct(value: Any, digits: int = 1) -> Optional[float]:
    return round(float(value) * 100, digits) if isinstance(value, (int, float)) else None


def _stage_row(item: dict) -> dict:
    return {
        "symbol": item["symbol"],
        "name": item.get("name") or item["symbol"],
        "stage": item.get("stage"),
        "stageLabel": item.get("stageLabel"),
        "weeksInStage": item.get("weeksInStage"),
        "ma30DistancePct": _pct(item.get("ma30Distance")),
        "ma30Slope4wPct": _pct(item.get("ma30Slope"), 2),
        "rs26Pct": _pct(item.get("rs26"), 0),
        "rsBenchmark": item.get("rsBenchmark"),
        "bbState": item.get("bbState"),
        "volumeRatio": round(item["volumeRatio"], 1) if isinstance(item.get("volumeRatio"), (int, float)) else None,
        "rule": (item.get("rule") or {}).get("label"),
    }


def _primary_summary(api_base: str, timeout: float) -> Optional[dict]:
    strategies = _api_get(api_base, "/portfolio-strategies", timeout)
    primary = next((s for s in strategies if s.get("isPrimary")), None)
    if primary is None:
        return None
    snap = _api_get(api_base, f"/portfolio-strategies/{primary['strategyId']}/snapshot", timeout)
    values = (snap.get("observation") or {}).get("values") or {}
    nav = snap.get("nav") or {}
    btc = None
    if "supertrend_on" in values:
        close, line = values.get("btc_close"), values.get("supertrend_line")
        btc = {
            "close": close,
            "stLine": line,
            "distancePct": _pct((close - line) / close) if close and line else None,
            "dailyOn": values.get("supertrend_on"),
            "formalOn": values.get("formal_supertrend_on"),
            "flipPending": values.get("supertrend_on") != values.get("formal_supertrend_on"),
        }
    orders = ((snap.get("operations") or {}).get("orders")) or []
    return {
        "strategyId": primary["strategyId"],
        "displayName": primary.get("displayName"),
        "state": snap.get("state"),
        "dates": snap.get("dates"),
        "nav": {k: nav.get(k) for k in ("netNav", "dailyReturn", "cumulativeReturn", "drawdown")},
        "currentWeights": {w["symbol"]: round(w["weight"], 4) for w in snap.get("currentWeights") or [] if w.get("weight")},
        "assets": {a["symbol"]: a.get("alias") for a in snap.get("assets") or []},
        "desiredWeights": {w["symbol"]: round(w["weight"], 4) for w in snap.get("desiredWeights") or [] if w.get("weight")},
        "openOrders": [o for o in orders if o.get("status") in ("PENDING", "WAITING_OPEN", "DELAYED")],
        "btcSwitch": btc,
        "diagnostics": [d for d in snap.get("diagnostics") or [] if d.get("severity") in ("error", "warning")][:5],
    }


def _supertrend_digest(api_base: str, timeout: float) -> dict:
    scan = _api_get(api_base, "/supertrend/scan?force=false&include_candles=false", timeout)
    groups = {
        key: value.get("symbols", [])
        for key, value in (scan.get("groups") or {}).items()
        if isinstance(value, dict) and value.get("symbols") and key != "stable"
    }
    return {
        "role": "learning observation only; never overrides the primary strategy",
        "groups": groups,
        "marketModes": {k: v.get("mode") for k, v in (scan.get("marketModes") or {}).items()},
    }


def query_weekly(api_base: str, timeout: float) -> dict:
    """Weekend review: primary strategy, market stages, stage changes, per-market rows."""
    items = _api_get(api_base, "/weinstein/scan?weeks=12", timeout)
    by_symbol = {item["symbol"]: item for item in items}
    rows: dict[str, list[dict]] = {"us": [], "crypto": [], "cn": [], "other": []}
    for item in items:
        rows[market_of(item["symbol"])].append(_stage_row(item))
    for market_rows in rows.values():
        market_rows.sort(key=lambda r: -(r["rs26Pct"] if r["rs26Pct"] is not None else -999))
    cn = rows["cn"]
    changes = [
        {**_stage_row(item), "market": market_of(item["symbol"]), "from": item["previousStage"]}
        for item in items
        if item.get("previousStage") and item["previousStage"] != item.get("stage")
    ]
    try:
        supertrend = _supertrend_digest(api_base, timeout)
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        supertrend = {"error": str(exc)}
    return {
        "fetchedAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "weekLabel": items[0].get("weekLabel") if items else None,
        "primary": _primary_summary(api_base, timeout),
        "benchmarks": [_stage_row(by_symbol[s]) for s in BENCHMARKS if s in by_symbol],
        "stageChanges": changes,
        "us": rows["us"],
        "crypto": rows["crypto"],
        "cn": {
            "stageCounts": {str(st): sum(1 for r in cn if r["stage"] == st) for st in (1, 2, 3, 4)},
            "stage2StrongerThanCsi300": [r for r in cn if r["stage"] == 2 and (r["rs26Pct"] or 0) > 0],
            "rows": cn,
        },
        "other": rows["other"],
        "supertrend": supertrend,
    }


def query_brief(api_base: str, symbol: str, timeout: float) -> dict:
    """One symbol: Weinstein view with recent weeks, then SuperTrend essentials."""
    data = _api_get(api_base, f"/quote/{symbol.upper()}", timeout)
    view = data.get("weinstein")
    weeks = []
    for candle in (data.get("weekly_candles") or [])[-10:]:
        weeks.append({
            "week": candle.get("time"),
            "close": candle.get("close"),
            "ma30": round(candle["ma30"], 4) if isinstance(candle.get("ma30"), (int, float)) else None,
            "stage": int(candle["stage"]) if isinstance(candle.get("stage"), (int, float)) else None,
            "rs26Pct": _pct(candle.get("rs26")),
            "bollUpper": candle.get("boll_upper"),
            "bollLower": candle.get("boll_lower"),
            "macdHist": candle.get("macd_hist"),
            "volume": candle.get("volume"),
        })
    decision = data.get("decision") or {}
    primary = None
    try:
        primary = _primary_summary(api_base, timeout)
    except (HTTPError, URLError, TimeoutError, ValueError):
        pass
    return {
        "symbol": data.get("symbol"),
        "name": data.get("alias") or data.get("name")
        or ((primary or {}).get("assets") or {}).get((data.get("symbol") or "").upper())
        or data.get("symbol"),
        "market": market_of(data.get("symbol") or symbol),
        "latestDataDate": data.get("latestDataDate"),
        "dataStale": data.get("dataStale"),
        "price": data.get("price"),
        "weinstein": {**(view or {}), "rule": None} if view is None else {**_stage_row({"symbol": data.get("symbol"), **view}), "ma30": view.get("ma30"), "weekLabel": view.get("weekLabel")},
        "recentWeeks": weeks,
        "supertrend": {
            "role": "learning observation only",
            "dailyState": data.get("state"),
            "weeklyState": data.get("weeklyState"),
            "stVal": data.get("stVal"),
            "adx": data.get("adx"),
            "permission": decision.get("permission"),
            "label": decision.get("label"),
            "nextGate": decision.get("nextGate"),
            "failedGates": decision.get("failedGates"),
            "invalidation": decision.get("invalidation"),
            "marketMode": data.get("marketMode"),
        },
        "inPrimaryStrategy": bool(primary and (data.get("symbol") or "").upper() in primary["assets"]),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch structured trading data for Claude analysis.")
    parser.add_argument(
        "--api-base",
        default=os.environ.get("TRADING_API_BASE", "http://127.0.0.1:8000/api"),
        help="API base; defaults to $TRADING_API_BASE or the local backend.",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument(
        "--query",
        choices=("stock", "scan", "portfolio", "overview", "squeeze", "weekly", "brief"),
        required=True,
        help="What to query.",
    )
    parser.add_argument("--symbol", help="Stock symbol (required for --query stock / brief).")
    parser.add_argument("--strategy", help="Strategy ID (optional for --query portfolio).")
    parser.add_argument("--grouped", action=argparse.BooleanOptionalAction, default=True, help="Group scan results.")
    parser.add_argument("--force", action="store_true", default=False, help="Force refresh cached scan data.")
    args = parser.parse_args()

    try:
        if args.query == "stock":
            if not args.symbol:
                print("Error: --symbol required for stock query.", file=sys.stderr)
                return 1
            result = query_stock(args.api_base, args.symbol, args.timeout)
        elif args.query == "scan":
            result = query_scan(args.api_base, args.timeout, grouped=args.grouped, force=args.force)
        elif args.query == "portfolio":
            result = query_portfolio(args.api_base, args.timeout, args.strategy)
        elif args.query == "overview":
            result = query_overview(args.api_base, args.timeout)
        elif args.query == "squeeze":
            result = query_squeeze(args.api_base, args.timeout)
        elif args.query == "weekly":
            result = query_weekly(args.api_base, args.timeout)
        elif args.query == "brief":
            if not args.symbol:
                print("Error: --symbol required for brief query.", file=sys.stderr)
                return 1
            result = query_brief(args.api_base, args.symbol, args.timeout)
        else:
            return 1
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
