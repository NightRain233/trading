#!/usr/bin/env python3
"""Fetch SuperTrend alerts from the local trading backend for OpenClaw jobs."""

import argparse
import json
import sys
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2, "none": 3}
PRIORITY_LABEL = {"high": "高", "medium": "中", "low": "低", "none": "无"}
ACTIONABLE_TYPES = {"buy_candidate", "support_test", "sell_or_risk", "resistance_test"}


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
        print(json.dumps(alerts, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(alerts, title=args.title))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
