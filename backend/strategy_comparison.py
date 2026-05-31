import argparse
import json
import math
import os
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from analysis_constants import DATA_DIR
from analysis_data import _calculate_weekly_indicators
from backtest import load_universe_symbols
from backtest import run_backtest_for_symbol
from backtest import run_supertrend_backtest
from backtest import simulate_mark_to_market_portfolio
from backtest import simulate_rs_rotation_portfolio
from backtest import summarize_buy_and_hold_benchmark
from backtest import summarize_trades


DEFAULT_START = "2021-05-31"
DEFAULT_END = "2026-05-30"
DEFAULT_FEE_BPS = 5.0
DEFAULT_SLIPPAGE_BPS = 5.0
FULL_WINDOW_MIN_BARS = 900
ADX_THRESHOLDS = [20.0, 25.0, 30.0]

PROJECT_BACKEND_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = PROJECT_BACKEND_DIR / DATA_DIR
DEFAULT_CHINA_UNIVERSE = PROJECT_BACKEND_DIR / "universes" / "a_share_etf_core.json"

US_SYMBOLS = ["SPY", "QQQ", "AAPL", "GOOGL", "NVDA", "TSLA"]
CRYPTO_SYMBOLS = ["BTC-USD"]
CRYPTO_MOMENTUM_SYMBOLS = ["BTC-USD", "ETH-USD"]
GLOBAL_EXTRA_SYMBOLS = ["SPY", "QQQ", "GC=F", "BTC-USD"]


def _round_float(value):
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return value
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return round(numeric, 4)


def _clean_json(value):
    if isinstance(value, dict):
        return {key: _clean_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean_json(item) for item in value]
    if isinstance(value, float):
        return _round_float(value)
    return value


def _pct(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"{float(value):.1f}%"


def _ratio(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"{float(value):.2f}"


def _load_frame(symbol: str, data_dir: Path) -> Optional[pd.DataFrame]:
    path = data_dir / f"{symbol.upper()}.parquet"
    if not path.exists():
        return None
    return pd.read_parquet(path)


def _load_weekly_or_resample(symbol: str, daily: pd.DataFrame, data_dir: Path) -> tuple[Optional[pd.DataFrame], str]:
    weekly_path = data_dir / f"{symbol.upper()}_weekly.parquet"
    if weekly_path.exists():
        return pd.read_parquet(weekly_path), "cached"
    if daily is None or daily.empty:
        return None, "missing"
    return _calculate_weekly_indicators(daily.copy()), "resampled"


def _window_bar_count(df: pd.DataFrame, start: str, end: str) -> int:
    if df is None or df.empty:
        return 0
    window = df[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]
    return len(window)


def _curve_stats(portfolio: Dict[str, object]) -> Dict[str, object]:
    curve = portfolio.get("equityCurve") or []
    total_return = portfolio.get("totalReturnPct")
    if total_return is None and curve:
        total_return = (float(curve[-1]["equity"]) - 1) * 100
    max_drawdown = portfolio.get("maxDrawdownPct")
    if max_drawdown is None and curve:
        max_drawdown = max(float(point.get("drawdownPct") or 0) for point in curve)
    total_return = float(total_return or 0.0)
    max_drawdown = float(max_drawdown or 0.0)
    return {
        "totalReturnPct": total_return,
        "maxDrawdownPct": max_drawdown,
        "returnDrawdownRatio": total_return / max_drawdown if max_drawdown else None,
        "startDate": portfolio.get("startDate") or (curve[0].get("date") if curve else None),
        "endDate": portfolio.get("endDate") or (curve[-1].get("date") if curve else None),
    }


def _unique_symbols(symbols: List[str]) -> List[str]:
    result = []
    for symbol in symbols:
        normalized = symbol.upper()
        if normalized not in result:
            result.append(normalized)
    return result


def build_supertrend_report(
    symbols: List[str],
    label: str,
    data_dir: Path,
    start: str,
    end: str,
    max_positions: int,
    fee_bps: float,
    slippage_bps: float,
    min_adx_for_entry: Optional[float] = None,
) -> Dict[str, object]:
    frames: Dict[str, pd.DataFrame] = {}
    trades: List[Dict[str, object]] = []
    missing = []
    partial = []
    weekly_resampled = []

    for symbol in _unique_symbols(symbols):
        daily = _load_frame(symbol, data_dir)
        if daily is None:
            missing.append(symbol)
            continue
        weekly, weekly_source = _load_weekly_or_resample(symbol, daily, data_dir)
        if weekly is None:
            missing.append(symbol)
            continue

        bars = _window_bar_count(daily, start, end)
        if bars < FULL_WINDOW_MIN_BARS:
            partial.append(
                {
                    "symbol": symbol,
                    "start": str(daily.index.min().date()),
                    "end": str(daily.index.max().date()),
                    "windowBars": bars,
                }
            )
        if weekly_source == "resampled":
            weekly_resampled.append(symbol)

        frames[symbol] = daily
        trades.extend(
            run_supertrend_backtest(
                symbol,
                daily,
                filter_weekly_df=weekly,
                start=start,
                end=end,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                min_adx_for_entry=min_adx_for_entry,
            )
        )

    portfolio = simulate_mark_to_market_portfolio(
        trades,
        frames,
        max_positions=max_positions,
        curve_start=start,
        curve_end=end,
    )

    return {
        "label": label,
        "minAdxForEntry": min_adx_for_entry,
        "symbolCount": len(frames),
        "symbols": list(frames),
        "missingSymbols": missing,
        "partialSymbols": partial,
        "weeklyResampledSymbols": weekly_resampled,
        "tradeSummary": summarize_trades(
            trades,
            strategy_version=f"supertrend_adx_{min_adx_for_entry:g}" if min_adx_for_entry is not None else "supertrend_weekly_filtered",
        ),
        "portfolio": _curve_stats(portfolio),
        "buyHold": summarize_buy_and_hold_benchmark(
            frames,
            start=start,
            end=end,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        ),
    }


def _build_adx_research_row(
    baseline_report: Dict[str, object],
    variant_reports: List[Dict[str, object]],
) -> Dict[str, object]:
    variants = [
        {
            "threshold": report["minAdxForEntry"],
            "totalReturnPct": report["portfolio"]["totalReturnPct"],
            "maxDrawdownPct": report["portfolio"]["maxDrawdownPct"],
            "returnDrawdownRatio": report["portfolio"]["returnDrawdownRatio"],
            "tradeCount": report["tradeSummary"]["tradeCount"],
            "winRate": report["tradeSummary"]["winRate"],
            "averageHoldingDays": report["tradeSummary"]["averageHoldingDays"],
        }
        for report in variant_reports
    ]
    best = max(
        variants,
        key=lambda row: float(row["returnDrawdownRatio"]) if row.get("returnDrawdownRatio") is not None else float("-inf"),
    ) if variants else None
    baseline = {
        "totalReturnPct": baseline_report["portfolio"]["totalReturnPct"],
        "maxDrawdownPct": baseline_report["portfolio"]["maxDrawdownPct"],
        "returnDrawdownRatio": baseline_report["portfolio"]["returnDrawdownRatio"],
        "tradeCount": baseline_report["tradeSummary"]["tradeCount"],
        "winRate": baseline_report["tradeSummary"]["winRate"],
        "averageHoldingDays": baseline_report["tradeSummary"]["averageHoldingDays"],
    }
    improvement = None
    if best and best.get("returnDrawdownRatio") is not None and baseline.get("returnDrawdownRatio"):
        improvement = float(best["returnDrawdownRatio"]) - float(baseline["returnDrawdownRatio"])
    return {
        "assetGroup": baseline_report["label"],
        "baseline": baseline,
        "bestAdx": best,
        "ratioImprovement": improvement,
        "variants": variants,
    }


def build_momentum_report(
    frames: Dict[str, pd.DataFrame],
    label: str,
    start: str,
    end: str,
    top_n: int,
    per_class_filters: Optional[Dict[str, tuple[pd.DataFrame, str]]] = None,
    min_avg_volume: float = 0.0,
    fee_bps: float = DEFAULT_FEE_BPS,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
) -> Dict[str, object]:
    portfolio = simulate_rs_rotation_portfolio(
        frames,
        top_n=top_n,
        rebalance_days=20,
        lookback_bars=60,
        start=start,
        end=end,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        min_history_bars=0,
        min_avg_volume=min_avg_volume,
        per_class_filters=per_class_filters,
    )
    return {"label": label, "portfolio": _curve_stats(portfolio)}


def build_weekly_bb_report(
    symbols: List[str],
    label: str,
    data_dir: Path,
    start: str,
    end: str,
    max_positions: int,
    fee_bps: float,
    slippage_bps: float,
) -> Dict[str, object]:
    frames: Dict[str, pd.DataFrame] = {}
    trades: List[Dict[str, object]] = []
    missing = []

    for symbol in _unique_symbols(symbols):
        daily = _load_frame(symbol, data_dir)
        if daily is None:
            missing.append(symbol)
            continue
        weekly, _ = _load_weekly_or_resample(symbol, daily, data_dir)
        if weekly is None:
            missing.append(symbol)
            continue
        frames[symbol] = daily
        trades.extend(
            run_backtest_for_symbol(
                symbol,
                daily,
                weekly,
                strategy_version="weekly_bb_breakout_ma30",
                max_hold_days=90,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                start=start,
                end=end,
            )
        )

    portfolio = simulate_mark_to_market_portfolio(
        trades,
        frames,
        max_positions=max_positions,
        curve_start=start,
        curve_end=end,
    )
    summary = summarize_trades(trades, strategy_version="weekly_bb_breakout_ma30")
    return {
        "label": label,
        "strategyVersion": "weekly_bb_breakout_ma30",
        "symbolCount": len(frames),
        "missingSymbols": missing,
        "tradeCount": summary["tradeCount"],
        "winRate": summary["winRate"],
        "averageHoldingDays": summary["averageHoldingDays"],
        "portfolio": _curve_stats(portfolio),
    }


def make_strategy_verdict(report: Dict[str, object]) -> Dict[str, str]:
    rows = report.get("comparisonRows") or []
    comparable_rows = [
        row for row in rows
        if row.get("supertrend", {}).get("returnDrawdownRatio") is not None
        and row.get("momentum", {}).get("returnDrawdownRatio") is not None
    ]
    supertrend_wins = sum(
        1
        for row in comparable_rows
        if float(row["supertrend"]["returnDrawdownRatio"]) > float(row["momentum"]["returnDrawdownRatio"])
    )

    if comparable_rows and supertrend_wins >= max(1, math.ceil(len(comparable_rows) * 0.75)):
        return {
            "defaultStrategy": "supertrend",
            "reason": "SuperTrend 在多数资产组的收益回撤比明显高于当前 RS 动量轮动，更适合做低维护默认观察页。",
            "caveat": "它不是收益最大化策略。美股强趋势单边牛市里，集中买入持有龙头可能收益更高，但回撤和择股压力也更大。",
        }

    return {
        "defaultStrategy": "watchlist",
        "reason": "SuperTrend 尚未在多数资产组证明收益回撤比优于动量轮动，默认页应保持观察列表。",
        "caveat": "可以继续用 SuperTrend 作为提醒页，而不是默认入口。",
    }


def build_strategy_comparison(
    data_dir: Path = DEFAULT_DATA_DIR,
    china_universe: Path = DEFAULT_CHINA_UNIVERSE,
    start: str = DEFAULT_START,
    end: str = DEFAULT_END,
    fee_bps: float = DEFAULT_FEE_BPS,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
) -> Dict[str, object]:
    data_dir = Path(data_dir)
    china_symbols = load_universe_symbols(str(china_universe))
    global_symbols = _unique_symbols(china_symbols + GLOBAL_EXTRA_SYMBOLS)

    supertrend_inputs = [
        (china_symbols, "中国ETF/A股代理", 5),
        (US_SYMBOLS, "美股/美股ETF", 5),
        (CRYPTO_SYMBOLS, "BTC", 1),
        (global_symbols, "全球观察池", 5),
    ]
    supertrend_reports = [
        build_supertrend_report(
            symbols,
            label,
            data_dir,
            start,
            end,
            max_positions=max_positions,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
        for symbols, label, max_positions in supertrend_inputs
    ]
    adx_research_rows = []
    for baseline_report, (symbols, label, max_positions) in zip(supertrend_reports, supertrend_inputs):
        variants = [
            build_supertrend_report(
                symbols,
                label,
                data_dir,
                start,
                end,
                max_positions=max_positions,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                min_adx_for_entry=threshold,
            )
            for threshold in ADX_THRESHOLDS
        ]
        adx_research_rows.append(_build_adx_research_row(baseline_report, variants))

    weekly_bb_reports = [
        build_weekly_bb_report(
            symbols,
            label,
            data_dir,
            start,
            end,
            max_positions=max_positions,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
        for symbols, label, max_positions in supertrend_inputs
    ]

    china_frames = {symbol: _load_frame(symbol, data_dir) for symbol in china_symbols}
    china_frames = {symbol: frame for symbol, frame in china_frames.items() if frame is not None}
    us_frames = {symbol: _load_frame(symbol, data_dir) for symbol in US_SYMBOLS}
    us_frames = {symbol: frame for symbol, frame in us_frames.items() if frame is not None}
    crypto_frames = {symbol: _load_frame(symbol, data_dir) for symbol in CRYPTO_MOMENTUM_SYMBOLS}
    crypto_frames = {symbol: frame for symbol, frame in crypto_frames.items() if frame is not None}
    global_frames = {symbol: _load_frame(symbol, data_dir) for symbol in global_symbols}
    global_frames = {symbol: frame for symbol, frame in global_frames.items() if frame is not None}

    momentum_reports = [
        build_momentum_report(
            china_frames,
            "中国ETF",
            start,
            end,
            top_n=5,
            per_class_filters={"a_share": (_load_frame("510300.SS", data_dir), "monthly_macd")},
            min_avg_volume=1e8,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        ),
        build_momentum_report(
            us_frames,
            "美股/ETF",
            start,
            end,
            top_n=5,
            per_class_filters={"us": (_load_frame("SPY", data_dir), "monthly_macd")},
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        ),
        build_momentum_report(
            crypto_frames,
            "BTC/ETH",
            start,
            end,
            top_n=1,
            per_class_filters={"crypto": (_load_frame("BTC-USD", data_dir), "monthly_macd")},
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        ),
        build_momentum_report(
            global_frames,
            "全球观察池",
            start,
            end,
            top_n=5,
            per_class_filters={
                "a_share": (_load_frame("510300.SS", data_dir), "monthly_macd"),
                "us": (_load_frame("SPY", data_dir), "monthly_macd"),
                "crypto": (_load_frame("BTC-USD", data_dir), "monthly_macd"),
                "commodity": (_load_frame("GC=F", data_dir), "monthly_macd"),
            },
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        ),
    ]

    momentum_by_label = {row["label"]: row for row in momentum_reports}
    label_map = {
        "中国ETF/A股代理": "中国ETF",
        "美股/美股ETF": "美股/ETF",
        "BTC": "BTC/ETH",
        "全球观察池": "全球观察池",
    }
    comparison_rows = []
    for st_report in supertrend_reports:
        momentum = momentum_by_label[label_map[st_report["label"]]]
        comparison_rows.append(
            {
                "assetGroup": st_report["label"],
                "symbolCount": st_report["symbolCount"],
                "supertrend": st_report["portfolio"],
                "momentum": momentum["portfolio"],
                "buyHold": {
                    "equalWeightReturnPct": st_report["buyHold"]["equalWeightReturnPct"],
                    "bestSymbol": st_report["buyHold"].get("bestSymbol"),
                    "worstSymbol": st_report["buyHold"].get("worstSymbol"),
                },
                "tradeCount": st_report["tradeSummary"]["tradeCount"],
                "winRate": st_report["tradeSummary"]["winRate"],
                "averageHoldingDays": st_report["tradeSummary"]["averageHoldingDays"],
            }
        )

    data_caveats = []
    partial_symbols = [
        item["symbol"]
        for report in supertrend_reports
        for item in report.get("partialSymbols", [])
    ]
    missing_symbols = [
        symbol
        for report in supertrend_reports
        for symbol in report.get("missingSymbols", [])
    ]
    if partial_symbols:
        data_caveats.append(f"部分标的缓存不足五年，已纳入但需要谨慎解读：{', '.join(sorted(set(partial_symbols)))}。")
    if missing_symbols:
        data_caveats.append(f"部分 universe 标的没有本地缓存，未参与统计：{', '.join(sorted(set(missing_symbols)))}。")
    resampled_symbols = [
        symbol
        for report in supertrend_reports
        for symbol in report.get("weeklyResampledSymbols", [])
    ]
    if resampled_symbols:
        data_caveats.append(f"部分标的缺周线缓存，报告由日线临时重采样周线：{', '.join(sorted(set(resampled_symbols)))}。")

    report = {
        "window": {"start": start, "end": end, "minFullWindowBars": FULL_WINDOW_MIN_BARS},
        "assumptions": {
            "supertrend": "日线 SuperTrend 翻多买入，日线翻空或触及 SuperTrend 止损卖出，并用周线 SuperTrend 多头过滤。",
            "momentum": "当前代码中的 RS Rotation：60 日相对强弱排名，20 个交易日调仓，按资产类别月 MACD 过滤。",
            "adx": "ADX 研究只作为入场过滤：SuperTrend 翻多时要求 ADX 达到阈值，离场和止损不受 ADX 阻止。",
            "weeklyBb": "周线 BB 对照使用 weekly_bb_breakout_ma30：周线突破优先，没有突破时接受突破后的回踩确认，最大持仓 90 天。",
            "costs": f"单边滑点 {slippage_bps} bps，买卖手续费合计按单边 {fee_bps} bps 估算。",
        },
        "comparisonRows": comparison_rows,
        "adxResearchRows": adx_research_rows,
        "weeklyBbRows": weekly_bb_reports,
        "supertrendReports": supertrend_reports,
        "momentumReports": momentum_reports,
        "dataCaveats": data_caveats,
    }
    report["verdict"] = make_strategy_verdict(report)
    return _clean_json(report)


def format_markdown_report(report: Dict[str, object]) -> str:
    window = report["window"]
    verdict = report.get("verdict", {})
    lines = [
        "# SuperTrend vs 动量策略近五年回测",
        "",
        f"区间：{window['start']} 至 {window['end']}",
        "",
        f"结论：{verdict.get('reason', '')}",
        "",
        f"注意：{verdict.get('caveat', '')}",
        "",
        "| 资产组 | ST收益 | ST回撤 | ST收益回撤比 | 动量收益 | 动量回撤 | 动量收益回撤比 | 买入持有等权收益 | ST交易数 | ST胜率 | 平均持仓 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report.get("comparisonRows", []):
        st = row["supertrend"]
        momentum = row["momentum"]
        buy_hold = row["buyHold"]
        lines.append(
            "| {asset} | {st_ret} | {st_dd} | {st_ratio} | {mom_ret} | {mom_dd} | {mom_ratio} | {bh_ret} | {trades} | {win_rate} | {holding}天 |".format(
                asset=row["assetGroup"],
                st_ret=_pct(st.get("totalReturnPct")),
                st_dd=_pct(st.get("maxDrawdownPct")),
                st_ratio=_ratio(st.get("returnDrawdownRatio")),
                mom_ret=_pct(momentum.get("totalReturnPct")),
                mom_dd=_pct(momentum.get("maxDrawdownPct")),
                mom_ratio=_ratio(momentum.get("returnDrawdownRatio")),
                bh_ret=_pct(buy_hold.get("equalWeightReturnPct")),
                trades=row.get("tradeCount", 0),
                win_rate=_pct(float(row.get("winRate", 0)) * 100),
                holding=f"{float(row.get('averageHoldingDays', 0)):.1f}",
            )
        )

    adx_rows = report.get("adxResearchRows") or []
    if adx_rows:
        lines.extend([
            "",
            "## ADX 过滤研究",
            "",
            "| 资产组 | 基础ST收益回撤比 | 最优ADX过滤 | ADX收益 | ADX回撤 | ADX收益回撤比 | 交易数变化 | 判断 |",
            "| --- | ---: | --- | ---: | ---: | ---: | ---: | --- |",
        ])
        for row in adx_rows:
            baseline = row["baseline"]
            best = row.get("bestAdx") or {}
            baseline_ratio = baseline.get("returnDrawdownRatio")
            best_ratio = best.get("returnDrawdownRatio")
            baseline_trades = int(baseline.get("tradeCount") or 0)
            best_trades = int(best.get("tradeCount") or 0)
            threshold = best.get("threshold")
            improved = best_ratio is not None and baseline_ratio is not None and float(best_ratio) > float(baseline_ratio)
            judgment = "改善" if improved else "未改善"
            lines.append(
                "| {asset} | {base_ratio} | ADX >= {threshold:g} | {ret} | {dd} | {ratio} | {trade_delta:+d} | {judgment} |".format(
                    asset=row["assetGroup"],
                    base_ratio=_ratio(baseline_ratio),
                    threshold=float(threshold) if threshold is not None else 0.0,
                    ret=_pct(best.get("totalReturnPct")),
                    dd=_pct(best.get("maxDrawdownPct")),
                    ratio=_ratio(best_ratio),
                    trade_delta=best_trades - baseline_trades,
                    judgment=judgment,
                )
            )

    weekly_bb_rows = report.get("weeklyBbRows") or []
    if weekly_bb_rows:
        lines.extend([
            "",
            "## 周线 BB 突破+回踩",
            "",
            "| 资产组 | BB收益 | BB回撤 | BB收益回撤比 | BB交易数 | BB胜率 | 平均持仓 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        for row in weekly_bb_rows:
            portfolio = row["portfolio"]
            lines.append(
                "| {asset} | {ret} | {dd} | {ratio} | {trades} | {win_rate} | {holding}天 |".format(
                    asset=row["label"] if "label" in row else row["assetGroup"],
                    ret=_pct(portfolio.get("totalReturnPct")),
                    dd=_pct(portfolio.get("maxDrawdownPct")),
                    ratio=_ratio(portfolio.get("returnDrawdownRatio")),
                    trades=row.get("tradeCount", 0),
                    win_rate=_pct(float(row.get("winRate", 0)) * 100),
                    holding=f"{float(row.get('averageHoldingDays', 0)):.1f}",
                )
            )

    assumptions = report.get("assumptions") or {}
    if assumptions:
        lines.extend(["", "## 假设"])
        for value in assumptions.values():
            lines.append(f"- {value}")

    caveats = report.get("dataCaveats") or []
    if caveats:
        lines.extend(["", "## 数据说明"])
        for caveat in caveats:
            lines.append(f"- {caveat}")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare SuperTrend, RS momentum, and buy-and-hold over the cached five-year data window.")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    args = parser.parse_args()

    report = build_strategy_comparison(
        data_dir=Path(args.data_dir),
        start=args.start,
        end=args.end,
    )
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_markdown_report(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
