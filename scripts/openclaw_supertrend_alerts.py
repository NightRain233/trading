#!/usr/bin/env python3
"""Fetch SuperTrend alerts from the local trading backend for OpenClaw jobs."""

import argparse
import json
import sys
from datetime import datetime
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2, "none": 3}
PRIORITY_LABEL = {"high": "高", "medium": "中", "low": "低", "none": "无"}
ACTIONABLE_TYPES = {"buy_candidate", "support_test", "sell_or_risk", "resistance_test"}
POSITION_MANAGEMENT_TYPES = {"support_test", "sell_or_risk", "resistance_test"}


def fetch_scan(api_base: str, timeout: float) -> list[dict[str, Any]]:
    url = api_base.rstrip("/") + "/supertrend/scan"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "openclaw-supertrend-alerts/1.0"})
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError("API returned a non-list payload")
    return payload


def _priority_allowed(item: dict[str, Any], min_priority: str) -> bool:
    priority = str(item.get("alertPriority") or "none")
    return PRIORITY_RANK.get(priority, 3) <= PRIORITY_RANK[min_priority]


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


def _fmt_number(value: Any, digits: int = 2, fallback: str = "-") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return f"{number:.{digits}f}"


def _is_weekly_bullish(item: dict[str, Any]) -> bool:
    return item.get("weeklyState") in ("bull", "bull_flip")


def _is_daily_bull_flip(item: dict[str, Any]) -> bool:
    return item.get("state") == "bull_flip" or (bool(item.get("justFlipped")) and item.get("state") == "bull")


def _is_daily_bear(item: dict[str, Any]) -> bool:
    return item.get("state") == "bear"


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


def _item_name(item: dict[str, Any]) -> str:
    symbol = item.get("symbol", "-")
    alias = item.get("alias") or ""
    return f"{symbol} {alias}".strip()


def _render_compact_item(item: dict[str, Any], *, note: Optional[str] = None) -> str:
    priority = PRIORITY_LABEL.get(str(item.get("alertPriority") or "none"), "无")
    label = item.get("alertLabel") or item.get("alertType") or "无信号"
    close = _fmt_number(item.get("close"), 4)
    key_level = _fmt_number(item.get("keyLevelPrice") or item.get("stVal"), 4)
    distance_pct = _fmt_number(item.get("distanceToSupertrendPct"), 2)
    distance_atr = _fmt_number(item.get("distanceToSupertrendAtr"), 2)
    action = item.get("suggestedAction") or "-"
    suffix = f" / {note}" if note else ""
    return (
        f"- **{_item_name(item)}**: {label} / 优先级 {priority} / "
        f"收盘 {close} / ST {key_level} / 距离 {distance_pct}% ({distance_atr} ATR){suffix}\n"
        f"  - 动作: {action}"
    )


def _append_section(lines: list[str], title: str, items: list[dict[str, Any]], *, empty: str, note: Optional[str] = None) -> None:
    lines.extend(["", f"## {title}"])
    if not items:
        lines.append(empty)
        return
    for item in items:
        lines.append(_render_compact_item(item, note=note))


def render_daily_brief_markdown(items: list[dict[str, Any]], *, title: str) -> str:
    now = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
    brief = build_daily_brief(items)
    lines = [
        f"# {title}",
        "",
        f"- 时间: {now} Asia/Shanghai",
        f"- 今日可开新仓: {len(brief['new_entries'])}",
        f"- 预备观察: {len(brief['prepare_watch'])}",
        f"- 持仓/风控: {len(brief['position_management'])}",
        "",
        "使用原则：只把“周线多头 + 日线刚翻多”视为新仓候选；“周多日空”是等待名单，现在不买。",
    ]

    _append_section(
        lines,
        "今日可开新仓",
        brief["new_entries"],
        empty="暂无周线多头且日线刚翻多的标的。",
        note="新仓候选",
    )
    _append_section(
        lines,
        "预备观察：周多日空，等待日线翻多",
        brief["prepare_watch"],
        empty="暂无周线多头但日线仍为空头的预备标的。",
        note="现在不买，等待日线翻多",
    )
    _append_section(
        lines,
        "持仓/风控",
        brief["position_management"],
        empty="暂无需要特别处理的持仓/风控提醒。",
        note="主要服务已有仓位",
    )
    _append_section(
        lines,
        "趋势背景：已在多头中",
        brief["background_trends"],
        empty="暂无低优先级多头背景。",
        note="不是新买点",
    )
    _append_section(
        lines,
        "其他可操作提醒",
        brief["other_alerts"],
        empty="暂无其他可操作提醒。",
    )

    return "\n".join(lines).rstrip()


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch SuperTrend alerts for OpenClaw scheduled notifications.")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000/api", help="Backend API base URL.")
    parser.add_argument("--timeout", type=float, default=10.0, help="HTTP timeout in seconds.")
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
        help="Minimum priority to include.",
    )
    parser.add_argument(
        "--only-actionable",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Only include actionable alerts.",
    )
    parser.add_argument("--title", default="SuperTrend 定时扫描", help="Markdown report title.")
    args = parser.parse_args()

    try:
        items = fetch_scan(args.api_base, args.timeout)
        alerts = filter_alerts(items, min_priority=args.min_priority, only_actionable=args.only_actionable)
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        print(f"SuperTrend alert fetch failed: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        if args.mode == "daily-brief":
            print(json.dumps(build_daily_brief(items), ensure_ascii=False, indent=2))
        else:
            print(json.dumps(alerts, ensure_ascii=False, indent=2))
    else:
        if args.mode == "daily-brief":
            print(render_daily_brief_markdown(items, title=args.title))
        else:
            print(render_markdown(alerts, title=args.title))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
