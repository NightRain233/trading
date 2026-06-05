#!/usr/bin/env python3
"""Compare A-share ETF RS rotation and ST portfolios on identical windows."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

PURE_ST_PATH = ROOT / "scripts" / "research_a_share_etf_pure_st_portfolio.py"
UNIVERSE_FILE = BACKEND_DIR / "universes" / "a_share_etf_core.json"
DATA_DIR = BACKEND_DIR / "data"
RESULTS_DIR = BACKEND_DIR / "backtest_results"
REPORT_FILE = ROOT / "docs" / "a-share-etf-st-rs-fair-comparison-2026-06-06.md"

STRATEGY_KEYS = [
    "rs_monthly_macd_baseline",
    "equal_weight_buy_hold",
    "daily_st_equal_weight",
    "weekly_daily_st_equal_weight",
    "daily_st_top5_rs",
]

STRATEGY_LABELS = {
    "rs_monthly_macd_baseline": "RS 轮动 + 510300 月 MACD",
    "equal_weight_buy_hold": "A 股 ETF 等权参考",
    "daily_st_equal_weight": "日线 ST 等权",
    "weekly_daily_st_equal_weight": "周线+日线 ST 等权",
    "daily_st_top5_rs": "日线 ST 后 RS top5",
}

DEFAULT_WINDOWS = [
    {"name": "full_cache", "start": "2015-01-01", "end": "2026-06-05"},
    {"name": "recent_5y", "start": "2021-05-06", "end": "2026-06-05"},
]

_PURE_ST_SPEC = importlib.util.spec_from_file_location("research_a_share_etf_pure_st_portfolio", PURE_ST_PATH)
pure_st = importlib.util.module_from_spec(_PURE_ST_SPEC)
_PURE_ST_SPEC.loader.exec_module(pure_st)


def _window_label(window: Dict[str, str]) -> str:
    return f"{window['name']}: {window['start']} to {window['end']}"


def _copy_strategy_stats(stats: Dict[str, object]) -> Dict[str, object]:
    return {
        "totalReturnPct": float(stats.get("totalReturnPct") or 0.0),
        "maxDrawdownPct": float(stats.get("maxDrawdownPct") or 0.0),
        "returnDrawdownRatio": stats.get("returnDrawdownRatio"),
        "averageExposure": float(stats.get("averageExposure") or 0.0),
    }


def _summarize_window_payload(
    payload: Dict[str, object],
    strategy_keys: Iterable[str] = STRATEGY_KEYS,
) -> Dict[str, Dict[str, object]]:
    summary = payload.get("summary", {})
    return {key: _copy_strategy_stats(summary[key]) for key in strategy_keys if key in summary}


def build_fair_comparison(
    windows: Optional[List[Dict[str, str]]] = None,
    universe_file: Path = UNIVERSE_FILE,
    data_dir: Path = DATA_DIR,
) -> Dict[str, object]:
    selected_windows = windows or DEFAULT_WINDOWS
    results: Dict[str, Dict[str, object]] = {}
    for window in selected_windows:
        payload = pure_st.build_research(
            start=window["start"],
            end=window["end"],
            universe_file=universe_file,
            data_dir=data_dir,
        )
        results[window["name"]] = {
            "window": dict(window),
            "label": _window_label(window),
            "params": payload.get("params", {}),
            "summary": _summarize_window_payload(payload),
            "annual": {key: payload.get("annual", {}).get(key, []) for key in STRATEGY_KEYS},
        }

    return {
        "params": {
            "universeFile": str(universe_file),
            "dataDir": str(data_dir),
            "windowCount": len(selected_windows),
            "strategyKeys": STRATEGY_KEYS,
            "strategyLabels": STRATEGY_LABELS,
            "costModel": {
                "feeBps": pure_st.FEE_BPS,
                "slippageBps": pure_st.SLIPPAGE_BPS,
            },
            "supertrend": {
                "length": pure_st.ST_LENGTH,
                "multiplier": pure_st.ST_MULTIPLIER,
            },
            "rsRotation": {
                "topN": pure_st.RS_TOP_N,
                "lookbackBars": pure_st.RS_LOOKBACK_BARS,
                "rebalanceDays": pure_st.RS_REBALANCE_DAYS,
                "minAvgVolume": pure_st.MIN_AVG_VOLUME,
            },
        },
        "windows": results,
    }


def _format_pct(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}%"


def _format_ratio(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"


def _markdown_table(summary: Dict[str, Dict[str, object]]) -> str:
    lines = [
        "| Strategy | Return | Max drawdown | Return/drawdown | Avg exposure |",
        "|---|---:|---:|---:|---:|",
    ]
    for key in STRATEGY_KEYS:
        stats = summary.get(key)
        if not stats:
            continue
        lines.append(
            "| {label} | {ret} | {dd} | {ratio} | {exposure} |".format(
                label=STRATEGY_LABELS[key],
                ret=_format_pct(stats.get("totalReturnPct")),
                dd=_format_pct(stats.get("maxDrawdownPct")),
                ratio=_format_ratio(stats.get("returnDrawdownRatio")),
                exposure=_format_pct(float(stats.get("averageExposure") or 0.0) * 100),
            )
        )
    return "\n".join(lines)


def _best_by_ratio(summary: Dict[str, Dict[str, object]]) -> str:
    return max(
        summary,
        key=lambda key: float(summary[key].get("returnDrawdownRatio") or -999999),
    )


def _write_report(payload: Dict[str, object], report_file: Path = REPORT_FILE) -> None:
    windows = payload["windows"]
    full = windows.get("full_cache")
    recent = windows.get("recent_5y")
    full_best = _best_by_ratio(full["summary"]) if full else None
    recent_best = _best_by_ratio(recent["summary"]) if recent else None

    lines = [
        "# A 股 ETF ST vs RS 公平对照研究 2026-06-06",
        "",
        "## 口径",
        "",
        f"- 样本：`{payload['params']['universeFile']}`",
        "- 数据：本地 parquet 缓存，不联网下载。",
        "- 成本：单边手续费 5 bps，单边滑点 5 bps。",
        "- RS：60 日强度排序、20 个交易日再平衡、持有 top5、用 510300 月 MACD 做市场过滤。",
        "- ST：`SuperTrend(7,3)`，收盘确认信号，下一组合交易日调仓。",
        "- 关键控制：每个窗口内所有策略使用同一个 ETF 池、同一个数据目录、同一个起止日期。",
        "- 限制：这是当前 ETF 池的研究，不是无后验的历史可投资 ETF 全市场；较晚上市的 ETF 只在有本地数据后参与。",
        "",
    ]

    for name, window in windows.items():
        lines.extend(
            [
                f"## {window['label']}",
                "",
                _markdown_table(window["summary"]),
                "",
            ]
        )

    lines.extend(
        [
            "## 解释",
            "",
            "这次把此前的基准差异拆开了：旧报告里的强 RS 基准来自更长的全历史窗口；"
            "而纯 ST 组合报告默认跑的是 2021-05 之后的近 5 年窗口。时间窗口不同，会显著改变 RS 策略的表现。",
            "",
            "全历史窗口里 ST 收益很高，但不能直接当作实盘收益预期：它使用的是当前研究 ETF 池，"
            "天然带有一定后验选池色彩。这个窗口更适合用来观察策略形态，近 5 年窗口更适合观察当前市场环境下的稳健性。",
            "",
        ]
    )
    if full_best:
        lines.append(
            "全历史窗口里，收益/回撤最高的是 "
            f"`{STRATEGY_LABELS[full_best]}`，比值 "
            f"{_format_ratio(full['summary'][full_best].get('returnDrawdownRatio'))}。"
        )
    if recent_best:
        lines.append(
            "近 5 年窗口里，收益/回撤最高的是 "
            f"`{STRATEGY_LABELS[recent_best]}`，比值 "
            f"{_format_ratio(recent['summary'][recent_best].get('returnDrawdownRatio'))}。"
        )
    lines.extend(
        [
            "",
            "结论：日线 ST 在近 5 年窗口明显不稳，不适合作为 A 股 ETF 组合主策略；周线+日线 ST 值得继续研究，"
            "但它更像一个高波动趋势暴露方案，下一步应测试和 RS/月 MACD 的组合降回撤能力。",
            "",
        ]
    )

    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fairly compare A-share ETF ST and RS portfolio strategies.")
    parser.add_argument("--universe-file", default=str(UNIVERSE_FILE))
    parser.add_argument("--data-dir", default=str(DATA_DIR))
    parser.add_argument(
        "--output",
        default=str(RESULTS_DIR / "a_share_etf_st_rs_fair_comparison_2026-06-06.json"),
    )
    parser.add_argument("--report", default=str(REPORT_FILE))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_fair_comparison(
        universe_file=Path(args.universe_file),
        data_dir=Path(args.data_dir),
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_report(payload, Path(args.report))

    compact = {
        "output": str(output_path),
        "report": str(Path(args.report)),
        "params": payload["params"],
        "windows": {
            name: {"label": window["label"], "summary": window["summary"]}
            for name, window in payload["windows"].items()
        },
    }
    print(json.dumps(payload if args.json else compact, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
