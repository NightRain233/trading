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
"""

import argparse
import json
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
    "close", "ema20", "ema50", "adx", "rsi7", "rsi14", "rsi21",
    "macd", "macdSignal", "macdHistogram",
    "bollUpper", "bollMid", "bollLower", "bollWidth",
    "kdjK", "kdjD", "kdjJ",
    "atr", "stVal", "stDir",
    "ma30", "ma200",
]

SIGNAL_KEYS = [
    "buySignal", "stopPrice", "targetPrice", "strategyVersion",
    "pullbackSignal", "exitSignal", "weeklyMarkers",
]

SUPERTREND_KEYS = [
    "state", "weeklyState", "justFlipped", "weeklyJustFlipped",
    "trendAgeBars", "distanceToSupertrendPct", "distanceToSupertrendAtr",
    "alertType", "alertLabel", "alertPriority", "alertReason", "suggestedAction",
    "opportunityStage", "opportunityLabel", "opportunityReason",
    "close", "stVal",
]


def _extract_indicators(quote: dict) -> dict:
    result = {}
    for key in INDICATOR_KEYS:
        if key in quote:
            result[key] = quote[key]
    # Weekly indicators
    if "weeklyIndicators" in quote:
        wi = quote["weeklyIndicators"]
        result["weekly"] = {k: wi.get(k) for k in INDICATOR_KEYS if k in wi}
    # Signals
    result["signals"] = {k: quote.get(k) for k in SIGNAL_KEYS if k in quote and quote.get(k) is not None}
    return result


def query_stock(api_base: str, symbol: str, timeout: float) -> dict:
    quote = _api_get(api_base, f"/quote/{symbol}", timeout)
    return {
        "symbol": symbol.upper(),
        "alias": quote.get("alias", ""),
        "indicators": _extract_indicators(quote),
        "supertrend": {k: quote.get(k) for k in SUPERTREND_KEYS if k in quote},
        "signals": {k: quote.get(k) for k in SIGNAL_KEYS if k in quote and quote.get(k) not in (None, False)},
        "fetchedAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
    }


# ---------------------------------------------------------------------------
# SuperTrend scan
# ---------------------------------------------------------------------------

PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2, "none": 3}

# Market indices for environment summary
MARKET_INDICES = ["000001.SS", "000300.SS", "510500.SS", "588000.SS", "159553.SZ"]
MARKET_INDEX_LABELS = {
    "000001.SS": "上证指数",
    "000300.SS": "沪深300",
    "510500.SS": "中证500",
    "588000.SS": "科创50",
    "159553.SZ": "中证2000",
}

# Filters for "worthy" background symbols
def _is_worthy_background(item: dict) -> bool:
    """A background (trend continuation) symbol is worth showing if it has a signal change."""
    d_atr = abs(float(item.get("distanceToSupertrendAtr") or 0))
    if d_atr < 2.0:
        return True  # Close to ST, potential pullback
    ind = item.get("indicators", {})
    adx = float(ind.get("adx") or 0)
    if adx > 35:
        return True  # Strong trend
    rsi21 = float(ind.get("rsi21") or 50)
    if rsi21 < 50:
        return True  # Oversold in uptrend
    age = int(item.get("trendAgeBars") or 0)
    if age < 10:
        return True  # Fresh trend
    if abs(float(item.get("distanceToSupertrendPct") or 0)) > 20:
        return True  # Extreme extension
    return False


GROUP_RULES = [
    ("new_entries", lambda i: i.get("weeklyState") in ("bull", "bull_flip") and i.get("state") in ("bull_flip",) or (i.get("justFlipped") and i.get("state") == "bull")),
    ("prepare_watch", lambda i: i.get("weeklyState") in ("bull", "bull_flip") and i.get("state") == "bear"),
    ("position_mgmt", lambda i: i.get("alertType") in ("support_test", "sell_or_risk", "resistance_test")),
    ("flip_proximity", lambda i: i.get("alertType") not in ("support_test", "sell_or_risk", "resistance_test") and abs(float(i.get("distanceToSupertrendAtr") or 999)) < 0.5),
    ("background", lambda i: i.get("alertType") == "hold_bull"),
]


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
        # Quality indicators
        "adx": ind.get("adx"),
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
        "bollWidth": m.get("bollWidth"),
        "bollSqueeze": m.get("bollSqueeze", False),
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
    items = _api_get(api_base, f"/supertrend/scan?force={force_str}", timeout)
    result: dict[str, Any] = {
        "total": len(items),
        "fetchedAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
    }

    if not grouped:
        result["items"] = items
        return result

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

    # Group
    assigned = set()
    groups = {}
    for group_name, rule in GROUP_RULES:
        members = []
        for item in items:
            sym = item.get("symbol", "")
            if sym in assigned:
                continue
            if rule(item):
                members.append(item)
                assigned.add(sym)
        if group_name == "background":
            # Split: worthy vs quiet
            worthy = [m for m in members if _is_worthy_background(m)]
            quiet = [m for m in members if not _is_worthy_background(m)]
            # Sort worthy by ADX desc (strongest trends first)
            worthy.sort(key=lambda i: float(i.get("indicators", {}).get("adx") or 0), reverse=True)
            quiet.sort(key=lambda i: float(i.get("indicators", {}).get("adx") or 0), reverse=True)
            groups[group_name] = worthy
            groups["background_quiet"] = quiet
        elif group_name == "prepare_watch":
            # Sort by distance (closest to ST = closest to flip)
            groups[group_name] = sorted(members, key=lambda i: abs(float(i.get("distanceToSupertrendPct") or 999)))
        elif group_name == "flip_proximity":
            groups[group_name] = sorted(members, key=lambda i: abs(float(i.get("distanceToSupertrendAtr") or 999)))
        else:
            groups[group_name] = sorted(
                members,
                key=lambda i: (
                    PRIORITY_RANK.get(str(i.get("alertPriority") or "none"), 3),
                    float(i.get("distanceToSupertrendPct") or 999999),
                ),
            )

    # BOLL squeeze candidates (not already in higher-priority groups)
    squeezing = [
        i for i in items
        if i.get("symbol") not in assigned and i.get("bollSqueeze")
    ]
    if squeezing:
        groups["squeeze_alerts"] = sorted(
            squeezing,
            key=lambda i: float(i.get("bollWidth") or 999),
        )

    # Remaining actionable
    other = [
        i for i in items
        if i.get("symbol") not in assigned and i.get("isActionable")
    ]
    groups["other_actionable"] = sorted(
        other,
        key=lambda i: (
            PRIORITY_RANK.get(str(i.get("alertPriority") or "none"), 3),
            float(i.get("distanceToSupertrendPct") or 999999),
        ),
    )

    # Build summary with quality indicators
    result["groups"] = {}
    for name, members in groups.items():
        symbols = [_build_symbol_entry(m) for m in members]
        if name == "background_quiet":
            result["groups"][name] = {
                "count": len(members),
                "collapsed": True,
                "symbols": symbols,
            }
        else:
            result["groups"][name] = {
                "count": len(members),
                "symbols": symbols,
            }

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
        "supertrend": scan,
        "portfolio": portfolio,
        "fetchedAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch structured trading data for Claude analysis.")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000/api")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument(
        "--query",
        choices=("stock", "scan", "portfolio", "overview", "squeeze"),
        required=True,
        help="What to query.",
    )
    parser.add_argument("--symbol", help="Stock symbol (required for --query stock).")
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
        else:
            return 1
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
