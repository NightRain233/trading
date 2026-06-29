#!/usr/bin/env python3
"""Fetch SuperTrend alerts and portfolio strategy snapshots for OpenClaw daily briefs.

Usage:
  # Full daily brief (SuperTrend + portfolio strategies)
  python scripts/openclaw_supertrend_alerts.py --mode daily-brief

  # SuperTrend only, flat list
  python scripts/openclaw_supertrend_alerts.py --mode flat --no-include-portfolio

  # JSON output for programmatic consumption
  python scripts/openclaw_supertrend_alerts.py --format json
"""

import argparse
import json
import sys
from datetime import datetime
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2, "none": 3}
PRIORITY_LABEL = {"high": "高", "low": "低", "medium": "中", "none": "无"}
PRIORITY_EMOJI = {"high": "🔴", "medium": "🟡", "low": "🟢", "none": "⚪"}
ACTIONABLE_TYPES = {"buy_candidate", "support_test", "sell_or_risk", "resistance_test"}
POSITION_MANAGEMENT_TYPES = {"support_test", "sell_or_risk", "resistance_test"}

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _api_get(api_base: str, path: str, timeout: float) -> Any:
    url = api_base.rstrip("/") + path
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "openclaw-daily-brief/2.0"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# SuperTrend scan
# ---------------------------------------------------------------------------


def fetch_supertrend_scan(api_base: str, timeout: float) -> list[dict[str, Any]]:
    payload = _api_get(api_base, "/supertrend/scan", timeout)
    if not isinstance(payload, list):
        raise ValueError("SuperTrend scan returned a non-list payload")
    return payload


def filter_alerts(
    items: list[dict[str, Any]],
    *,
    min_priority: str,
    only_actionable: bool,
) -> list[dict[str, Any]]:
    alerts = []
    for item in items:
        if not _priority_allowed(item, min_priority):
            continue
        if only_actionable and not bool(item.get("isActionable")):
            continue
        alerts.append(item)
    return sorted(
        alerts,
        key=lambda item: (
            PRIORITY_RANK.get(str(item.get("alertPriority") or "none"), 3),
            float(item.get("distanceToSupertrendPct") or 999999),
            str(item.get("symbol") or ""),
        ),
    )


def _priority_allowed(item: dict[str, Any], min_priority: str) -> bool:
    priority = str(item.get("alertPriority") or "none")
    return PRIORITY_RANK.get(priority, 3) <= PRIORITY_RANK[min_priority]


# ---------------------------------------------------------------------------
# Portfolio strategies
# ---------------------------------------------------------------------------


def fetch_portfolio_strategies(api_base: str, timeout: float) -> list[dict[str, Any]]:
    """Return paper-enabled strategies with their latest snapshots."""
    strategies = _api_get(api_base, "/portfolio-strategies", timeout)
    if not isinstance(strategies, list):
        return []

    result = []
    for st in strategies:
        if not st.get("paperEnabled"):
            continue
        try:
            snapshot = _api_get(api_base, f"/portfolio-strategies/{st['strategyId']}/snapshot", timeout)
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
            snapshot = {"state": "UNAVAILABLE", "calcError": "Failed to fetch snapshot"}
        snapshot["_displayName"] = st.get("displayName", st.get("strategyId", ""))
        snapshot["_bootstrapped"] = st.get("bootstrapped", False)
        result.append(snapshot)
    return result


# ---------------------------------------------------------------------------
# Grouping / classification
# ---------------------------------------------------------------------------


def _is_weekly_bullish(item: dict[str, Any]) -> bool:
    return item.get("weeklyState") in ("bull", "bull_flip")


def _is_daily_bull_flip(item: dict[str, Any]) -> bool:
    return item.get("state") == "bull_flip" or (bool(item.get("justFlipped")) and item.get("state") == "bull")


def _is_daily_bear(item: dict[str, Any]) -> bool:
    return item.get("state") == "bear"


def build_daily_brief(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group scan rows by how a human should use them in a daily review."""
    new_entries = []
    prepare_watch = []
    position_management = []
    background_trends = []
    other_alerts = []
    assigned_symbols = set()

    for item in items:
        symbol = str(item.get("symbol") or "")
        if _is_weekly_bullish(item) and _is_daily_bull_flip(item):
            new_entries.append(item)
            assigned_symbols.add(symbol)

    for item in items:
        symbol = str(item.get("symbol") or "")
        if symbol in assigned_symbols:
            continue
        if _is_weekly_bullish(item) and _is_daily_bear(item):
            prepare_watch.append(item)
            assigned_symbols.add(symbol)

    for item in items:
        symbol = str(item.get("symbol") or "")
        if symbol in assigned_symbols:
            continue
        if item.get("alertType") in POSITION_MANAGEMENT_TYPES:
            position_management.append(item)
            assigned_symbols.add(symbol)

    for item in items:
        symbol = str(item.get("symbol") or "")
        if symbol in assigned_symbols:
            continue
        if item.get("alertType") == "hold_bull":
            background_trends.append(item)
            assigned_symbols.add(symbol)

    for item in items:
        symbol = str(item.get("symbol") or "")
        if symbol not in assigned_symbols and bool(item.get("isActionable")):
            other_alerts.append(item)

    return {
        "new_entries": _sort_by_priority_distance_symbol(new_entries),
        "prepare_watch": _sort_by_distance_symbol(prepare_watch),
        "position_management": _sort_by_priority_distance_symbol(position_management),
        "background_trends": _sort_by_distance_symbol(background_trends),
        "other_alerts": _sort_by_priority_distance_symbol(other_alerts),
    }


def _sort_by_priority_distance_symbol(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            PRIORITY_RANK.get(str(item.get("alertPriority") or "none"), 3),
            float(item.get("distanceToSupertrendPct") or 999999),
            str(item.get("symbol") or ""),
        ),
    )


def _sort_by_distance_symbol(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            float(item.get("distanceToSupertrendPct") or 999999),
            str(item.get("symbol") or ""),
        ),
    )


# ---------------------------------------------------------------------------
# Data freshness
# ---------------------------------------------------------------------------


def _assess_data_freshness(supertrend_items: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a data-freshness summary for the header."""
    total = len(supertrend_items)
    if total == 0:
        return {"status": "no_data", "stale_count": 0, "missing_count": 0, "total": 0}

    stale = sum(1 for item in supertrend_items if item.get("dataStale") or item.get("cacheStale"))
    missing = sum(1 for item in supertrend_items if item.get("dataIntegrity", {}).get("hasRecentGap", False))
    partial_refresh = sum(1 for item in supertrend_items if item.get("refreshTriggered"))

    if stale > total * 0.5:
        status = "⚠️ 大部分数据过期"
    elif stale > 0 or partial_refresh > 0:
        status = "⚠️ 部分数据需刷新"
    elif missing > 0:
        status = "⚠️ 部分数据有缺口"
    else:
        status = "✅ 数据正常"

    return {
        "status": status,
        "stale_count": stale,
        "missing_count": missing,
        "total": total,
        "partial_refresh": partial_refresh,
    }


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def _fmt_number(value: Any, digits: int = 2, fallback: str = "-") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return f"{number:.{digits}f}"


def _fmt_pct(value: Any, digits: int = 2, fallback: str = "-") -> str:
    """Format a ratio as percentage string, e.g. 0.0234 → +2.34%."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    sign = "+" if number >= 0 else ""
    return f"{sign}{number * 100:.{digits}f}%"


def _fmt_pct_direct(value: Any, digits: int = 2, fallback: str = "-") -> str:
    """Format an already-percentage value, e.g. 2.34 → +2.34%."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    sign = "+" if number >= 0 else ""
    return f"{sign}{number:.{digits}f}%"


def _item_name(item: dict[str, Any]) -> str:
    symbol = item.get("symbol", "-")
    alias = item.get("alias") or ""
    return f"{symbol} {alias}".strip()


def _state_emoji(state: Optional[str]) -> str:
    """Return an emoji for the overall strategy state."""
    if not state:
        return "⚪"
    return {
        "READY": "🟢",
        "PENDING_EXECUTION": "🔄",
        "NOT_DUE": "⏳",
        "BOOTSTRAPPED": "🔵",
        "EMPTY": "⚪",
        "BLOCKED": "🔴",
        "UNAVAILABLE": "💀",
    }.get(state, "⚪")


# ---------------------------------------------------------------------------
# SuperTrend rendering (compact style)
# ---------------------------------------------------------------------------


def _render_compact_item(item: dict[str, Any], *, note: Optional[str] = None) -> str:
    priority = PRIORITY_LABEL.get(str(item.get("alertPriority") or "none"), "无")
    emoji = PRIORITY_EMOJI.get(str(item.get("alertPriority") or "none"), "⚪")
    label = item.get("alertLabel") or item.get("alertType") or "无信号"
    close = _fmt_number(item.get("close"), 4)
    key_level = _fmt_number(item.get("keyLevelPrice") or item.get("stVal"), 4)
    distance_pct = _fmt_number(item.get("distanceToSupertrendPct"), 2)
    action = item.get("suggestedAction") or "-"
    suffix = f" / {note}" if note else ""
    return (
        f"- {emoji} **{_item_name(item)}**: {label} / "
        f"收盘 {close} / ST {key_level} / 距 {distance_pct}%{suffix}\n"
        f"  - {action}"
    )


def _append_section(lines: list[str], title: str, items: list[dict[str, Any]], *, empty: str, note: Optional[str] = None) -> None:
    lines.extend(["", f"## {title}"])
    if not items:
        lines.append(empty)
        return
    for item in items:
        lines.append(_render_compact_item(item, note=note))


# ---------------------------------------------------------------------------
# Portfolio rendering
# ---------------------------------------------------------------------------


def _render_portfolio_strategy(snapshot: dict[str, Any]) -> list[str]:
    """Render a single portfolio strategy as a compact Markdown block."""
    name = snapshot.get("_displayName", snapshot.get("strategyId", "Unknown"))
    sid = snapshot.get("strategyId", "")
    state = snapshot.get("state", "EMPTY")
    emoji = _state_emoji(state)
    lines = [f"### {emoji} {name}"]

    # Key metrics row
    nav = snapshot.get("nav", {})
    if nav:
        nav_val = _fmt_number(nav.get("netNav"), 0)
        cum_ret = _fmt_pct(nav.get("cumulativeReturn"), 2)
        drawdown = _fmt_pct(nav.get("drawdown"), 2)
        daily_ret = _fmt_pct(nav.get("dailyReturn"), 2)
        lines.append(f"- 净值 ¥{nav_val} | 累计 {cum_ret} | 今日 {daily_ret} | 最大回撤 {drawdown}")
    else:
        lines.append("- 净值: 暂无数据")

    # Current positions
    current = snapshot.get("currentWeights", [])
    if current:
        non_cash = [p for p in current if p.get("symbol") != "CASH" and float(p.get("weight", 0)) > 0.005]
        cash_item = next((p for p in current if p.get("symbol") == "CASH"), None)
        if non_cash:
            pos_str = " / ".join(
                f"{p['symbol']} {float(p['weight']) * 100:.0f}%"
                for p in sorted(non_cash, key=lambda x: float(x.get("weight", 0)), reverse=True)
            )
            if cash_item and float(cash_item.get("weight", 0)) > 0.01:
                pos_str += f" / 💵 {float(cash_item['weight']) * 100:.0f}%"
            lines.append(f"- 持仓: {pos_str}")
        elif cash_item and float(cash_item.get("weight", 0)) > 0.99:
            lines.append("- 持仓: 💵 全现金")
    else:
        desired = snapshot.get("desiredWeights", [])
        if desired:
            non_cash = [w for w in desired if w.get("symbol") != "CASH" and float(w.get("weight", 0)) > 0.005]
            if non_cash:
                pos_str = " / ".join(
                    f"{w['symbol']} →{float(w['weight']) * 100:.0f}%"
                    for w in sorted(non_cash, key=lambda x: float(x.get("weight", 0)), reverse=True)
                )
                lines.append(f"- 目标权重: {pos_str}")

    # Observation / signal reason
    obs = snapshot.get("observation", {})
    if obs and obs.get("reason"):
        reason = obs["reason"]
        # Truncate long reasons
        if len(reason) > 120:
            reason = reason[:117] + "..."
        lines.append(f"- 信号: {reason}")

    # Pending rebalance alert
    ledger = snapshot.get("ledger", {})
    if ledger.get("status") == "pending":
        signal_date = ledger.get("signalDate", "?")
        lines.append(f"- ⚠️ 待执行调仓，信号日 {signal_date}")

    # Next check date
    dates = snapshot.get("dates", {})
    next_check = dates.get("nextCheck")
    if next_check:
        lines.append(f"- 下次检查: {next_check}")

    # Error
    error = snapshot.get("calcError")
    if error:
        lines.append(f"- ⚠️ 计算错误: {error}")

    return lines


def render_portfolio_summary_markdown(strategies: list[dict[str, Any]]) -> str:
    """Render the portfolio strategy section for the daily brief."""
    if not strategies:
        return ""

    lines = ["", "## 📊 组合策略"]

    # Quick summary row
    summaries = []
    for st in strategies:
        name = st.get("_displayName", st.get("strategyId", ""))
        # Shorten display name
        short_name = name.replace("SuperTrend Satellite", "ST Sat").replace("Theme Alpha", "Theme α")
        nav = st.get("nav", {})
        daily_ret = _fmt_pct(nav.get("dailyReturn"), 2) if nav else "-"
        state = st.get("state", "EMPTY")
        emoji = _state_emoji(state)
        summaries.append(f"{emoji} {short_name}: {daily_ret}")
    lines.append(" | ".join(summaries))
    lines.append("")

    # Per-strategy details
    for st in strategies:
        lines.extend(_render_portfolio_strategy(st))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Daily brief (combined)
# ---------------------------------------------------------------------------


def render_daily_brief_markdown(
    supertrend_items: list[dict[str, Any]],
    *,
    title: str,
    portfolio_strategies: Optional[list[dict[str, Any]]] = None,
) -> str:
    now = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
    brief = build_daily_brief(supertrend_items)
    freshness = _assess_data_freshness(supertrend_items)

    lines = [
        f"# {title}",
        "",
        f"**{now} Asia/Shanghai** | 数据: {freshness['status']} | 扫描: {freshness['total']} 个标的",
        "",
        f"| 新仓候选 | 预备观察 | 持仓风控 | 趋势延续 |",
        f"|---------|---------|---------|---------|",
        f"| **{len(brief['new_entries'])}** | {len(brief['prepare_watch'])} | {len(brief['position_management'])} | {len(brief['background_trends'])} |",
        "",
        "> 使用原则：只把「周线多头 + 日线刚翻多」视为新仓候选；「周多日空」是等待名单，现在不买。",
    ]

    # Data freshness warning
    if freshness["stale_count"] > 0:
        lines.append(f"> ⚠️ {freshness['stale_count']} 个标的数据可能过期，建议在面板中手动刷新。")
    if freshness["partial_refresh"] > 0:
        lines.append(f"> ⏳ 本次触发了部分刷新，未完成的标的可能数据不完整。")

    # SuperTrend sections
    _append_section(
        lines,
        "🔥 今日可开新仓",
        brief["new_entries"],
        empty="暂无周线多头且日线刚翻多的标的。",
        note="新仓候选",
    )
    _append_section(
        lines,
        "👀 预备观察：周多日空，等待日线翻多",
        brief["prepare_watch"],
        empty="暂无周线多头但日线仍为空头的预备标的。",
        note="现在不买，等待日线翻多",
    )
    _append_section(
        lines,
        "🛡️ 持仓/风控",
        brief["position_management"],
        empty="暂无需要特别处理的持仓/风控提醒。",
        note="主要服务已有仓位",
    )
    _append_section(
        lines,
        "📈 趋势背景：已在多头中",
        brief["background_trends"],
        empty="暂无低优先级多头背景。",
        note="不是新买点",
    )
    _append_section(
        lines,
        "📋 其他可操作提醒",
        brief["other_alerts"],
        empty="暂无其他可操作提醒。",
    )

    # Portfolio strategies
    if portfolio_strategies is not None:
        lines.append(render_portfolio_summary_markdown(portfolio_strategies))

    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Legacy flat markdown render
# ---------------------------------------------------------------------------


def render_markdown(alerts: list[dict[str, Any]], *, title: str) -> str:
    now = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# {title}",
        "",
        f"- 时间: {now} Asia/Shanghai",
        f"- 数量: {len(alerts)}",
        "",
    ]

    if not alerts:
        lines.append("暂无符合条件的 SuperTrend 提醒。")
        return "\n".join(lines)

    for item in alerts:
        symbol = item.get("symbol", "-")
        alias = item.get("alias") or ""
        name = f"{symbol} {alias}".strip()
        priority = PRIORITY_LABEL.get(str(item.get("alertPriority") or "none"), "无")
        label = item.get("alertLabel") or item.get("alertType") or "无信号"
        close = _fmt_number(item.get("close"), 4)
        key_level = _fmt_number(item.get("keyLevelPrice") or item.get("stVal"), 4)
        distance_pct = _fmt_number(item.get("distanceToSupertrendPct"), 2)
        distance_atr = _fmt_number(item.get("distanceToSupertrendAtr"), 2)
        reason = item.get("alertReason") or "-"
        action = item.get("suggestedAction") or "-"

        lines.extend(
            [
                f"## {name}",
                f"- 提醒: {label} / 优先级 {priority}",
                f"- 收盘: {close} / ST关键位: {key_level} / 距离: {distance_pct}% ({distance_atr} ATR)",
                f"- 原因: {reason}",
                f"- 动作: {action}",
                "",
            ]
        )

    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch SuperTrend alerts and portfolio snapshots for OpenClaw daily briefs.")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000/api", help="Backend API base URL.")
    parser.add_argument("--timeout", type=float, default=15.0, help="HTTP timeout in seconds.")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown", help="Output format.")
    parser.add_argument(
        "--mode",
        choices=("daily-brief", "flat"),
        default="daily-brief",
        help="daily-brief groups alerts by trading workflow; flat keeps the legacy priority list.",
    )
    parser.add_argument(
        "--min-priority",
        choices=("high", "medium", "low", "none"),
        default="medium",
        help="Minimum SuperTrend priority to include.",
    )
    parser.add_argument(
        "--only-actionable",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Only include actionable SuperTrend alerts.",
    )
    parser.add_argument(
        "--include-portfolio",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include portfolio strategy snapshots in the daily brief.",
    )
    parser.add_argument("--title", default="SuperTrend 每日扫描", help="Markdown report title.")
    args = parser.parse_args()

    # Fetch SuperTrend
    try:
        supertrend_items = fetch_supertrend_scan(args.api_base, args.timeout)
        alerts = filter_alerts(supertrend_items, min_priority=args.min_priority, only_actionable=args.only_actionable)
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        print(f"SuperTrend alert fetch failed: {exc}", file=sys.stderr)
        return 2

    # Fetch portfolio (optional)
    portfolio_strategies = None
    if args.include_portfolio and args.mode == "daily-brief":
        try:
            portfolio_strategies = fetch_portfolio_strategies(args.api_base, args.timeout)
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            # Non-fatal: just skip portfolio section
            print(f"Portfolio fetch failed (continuing without it): {exc}", file=sys.stderr)
            portfolio_strategies = None

    # Render
    if args.format == "json":
        output: dict[str, Any] = {
            "timestamp": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            "mode": args.mode,
        }
        if args.mode == "daily-brief":
            output["supertrend"] = build_daily_brief(supertrend_items)
            if portfolio_strategies is not None:
                output["portfolio"] = portfolio_strategies
        else:
            output["alerts"] = alerts
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        if args.mode == "daily-brief":
            print(render_daily_brief_markdown(
                supertrend_items,
                title=args.title,
                portfolio_strategies=portfolio_strategies,
            ))
        else:
            print(render_markdown(alerts, title=args.title))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
