#!/usr/bin/env python3
"""Walk-forward SuperTrend fit research.

This research script is offline-only. It reads local parquet cache data and
does not modify production strategy behavior.
"""

from __future__ import annotations

import calendar
import argparse
import importlib.util
import json
import math
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import pandas_ta as ta


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
DATA_DIR = BACKEND_DIR / "data"
WATCHLIST_FILE = BACKEND_DIR / "watchlist.json"
COMPARE_ST_PATH = ROOT / "scripts" / "compare_supertrend_timeframes.py"

_COMPARE_SPEC = importlib.util.spec_from_file_location("compare_supertrend_timeframes", COMPARE_ST_PATH)
compare_st = importlib.util.module_from_spec(_COMPARE_SPEC)
_COMPARE_SPEC.loader.exec_module(compare_st)


def _date_str(value) -> str:
    return pd.Timestamp(value).date().isoformat()


def _add_months(value, months: int) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    month_index = ts.month - 1 + int(months)
    year = ts.year + month_index // 12
    month = month_index % 12 + 1
    day = min(ts.day, calendar.monthrange(year, month)[1])
    return pd.Timestamp(year=year, month=month, day=day)


def _build_walk_forward_windows(
    start: str,
    end: str,
    train_years: int = 2,
    test_months: int = 6,
    step_months: int = 6,
) -> List[Dict[str, str]]:
    start_ts = pd.Timestamp(start).normalize()
    end_ts = pd.Timestamp(end).normalize()
    train_months = int(train_years) * 12
    windows: List[Dict[str, str]] = []
    train_start = start_ts

    while True:
        train_end = _add_months(train_start, train_months)
        test_start = train_end + timedelta(days=1)
        test_end = _add_months(train_end, test_months)
        if test_end > end_ts:
            break
        windows.append(
            {
                "trainStart": _date_str(train_start),
                "trainEnd": _date_str(train_end),
                "testStart": _date_str(test_start),
                "testEnd": _date_str(test_end),
            }
        )
        train_start = _add_months(train_start, step_months)

    return windows


def _safe_rdd(return_pct: float, max_drawdown_pct: float, min_drawdown_pct: float = 5.0) -> float:
    denominator = max(float(max_drawdown_pct or 0.0), float(min_drawdown_pct))
    return float(return_pct or 0.0) / denominator


def _insufficient_trade_penalty(trade_count: int) -> float:
    if int(trade_count or 0) <= 0:
        return 1.0
    if int(trade_count) == 1:
        return 0.5
    return 0.0


def _tier_for_rank(rank: int, count: int) -> str:
    if count <= 1:
        return "top"
    if count == 2:
        return "top" if rank == 1 else "bottom"
    top_cutoff = max(1, count // 3)
    bottom_start = count - max(1, count // 3) + 1
    if rank <= top_cutoff:
        return "top"
    if rank >= bottom_start:
        return "bottom"
    return "mid"


def _assign_tiers(rows: List[Dict[str, object]], score_key: str, prefix: str) -> List[Dict[str, object]]:
    ranked_rows = [dict(row) for row in rows]
    by_bucket = {}
    for row in ranked_rows:
        by_bucket.setdefault(str(row.get("assetBucket", "unknown")), []).append(row)

    for bucket_rows in by_bucket.values():
        bucket_rows.sort(key=lambda row: float(row.get(score_key) or -999999.0), reverse=True)
        count = len(bucket_rows)
        low_sample = count < 3
        for index, row in enumerate(bucket_rows, start=1):
            row[f"{prefix}Rank"] = index
            row[f"{prefix}Percentile"] = (count - index + 1) / count if count else 0.0
            row[f"{prefix}Tier"] = _tier_for_rank(index, count)
            row[f"{prefix}LowSample"] = low_sample

    return ranked_rows


def _cohort_key(row: Dict[str, object]) -> str:
    return str(row.get("normalizationCohort") or row.get("assetBucket") or "unknown")


def _finite_float(value, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _robust_z_values(values: List[float]) -> List[float]:
    series = pd.Series([_finite_float(value) for value in values], dtype="float64")
    if series.empty:
        return []
    lower = float(series.quantile(0.05))
    upper = float(series.quantile(0.95))
    clipped = series.clip(lower=lower, upper=upper)
    median = float(clipped.median())
    iqr = float(clipped.quantile(0.75) - clipped.quantile(0.25))
    scale = max(iqr / 1.349, 1e-9)
    z = ((clipped - median) / scale).clip(lower=-3.0, upper=3.0) / 3.0
    return [float(value) for value in z]


def _robust_normalize_rows(rows: List[Dict[str, object]], raw_keys: List[str]) -> List[Dict[str, object]]:
    normalized = [dict(row) for row in rows]
    cohorts = sorted({_cohort_key(row) for row in normalized})
    for raw_key in raw_keys:
        for cohort in cohorts:
            cohort_indexes = [
                index for index, row in enumerate(normalized)
                if _cohort_key(row) == cohort
            ]
            values = [_finite_float(normalized[index].get(raw_key)) for index in cohort_indexes]
            z_values = _robust_z_values(values)
            for index, z_value in zip(cohort_indexes, z_values):
                normalized[index][f"{raw_key}Z"] = z_value
    return normalized


def _history_raw_fields(train_row: Dict[str, object]) -> Dict[str, object]:
    daily_st = train_row.get("dailySt", {}) or {}
    buy_hold = train_row.get("buyHold", {}) or {}
    st_return = _finite_float(daily_st.get("returnPct"))
    st_drawdown = _finite_float(daily_st.get("maxDrawdownPct"))
    buy_hold_return = _finite_float(buy_hold.get("returnPct"))
    buy_hold_drawdown = _finite_float(buy_hold.get("maxDrawdownPct"))
    st_rdd = _safe_rdd(st_return, st_drawdown)
    buy_hold_rdd = _safe_rdd(buy_hold_return, buy_hold_drawdown)
    trade_count = int(_finite_float(daily_st.get("tradeCount")))
    excess_log_return = math.log(max(0.01, 1 + st_return / 100)) - math.log(
        max(0.01, 1 + buy_hold_return / 100)
    )
    return {
        "trainDailyStReturnPct": st_return,
        "trainDailyStMaxDrawdownPct": st_drawdown,
        "trainDailyStRddSafe": st_rdd,
        "trainBuyHoldReturnPct": buy_hold_return,
        "trainBuyHoldMaxDrawdownPct": buy_hold_drawdown,
        "trainBuyHoldRddSafe": buy_hold_rdd,
        "excessRddSafe": st_rdd - buy_hold_rdd,
        "drawdownReductionPct": (buy_hold_drawdown - st_drawdown) / max(buy_hold_drawdown, 5.0),
        "excessLogReturn": excess_log_return,
        "trainTradeCount": trade_count,
        "tradeReliability": min(1.0, trade_count / 4),
        "winRatePct": _finite_float(daily_st.get("winRatePct")),
        "avgTradeReturnPct": _finite_float(daily_st.get("averageTradeReturnPct")),
        "insufficientTradePenalty": _insufficient_trade_penalty(trade_count),
    }


def _indicator_column(frame: pd.DataFrame, prefix: str):
    return next((column for column in frame.columns if str(column).startswith(prefix)), None)


def _compute_shape_features(daily: pd.DataFrame, train_start: str, train_end: str) -> Dict[str, float]:
    window = daily[
        (daily.index >= pd.Timestamp(train_start))
        & (daily.index <= pd.Timestamp(train_end))
    ].sort_index().copy()
    if window.empty:
        return {
            "trendEfficiency63Median": 0.0,
            "adx14TrendShare": 0.0,
            "emaBullPersistence": 0.0,
            "stFlipRatePerYear": 0.0,
            "atrPctMedian": 0.0,
            "atrPctIqrOverMedian": 0.0,
        }

    close = window["Close"].astype(float)
    returns = close.pct_change()
    path_63 = returns.abs().rolling(63, min_periods=20).sum()
    directional_63 = (close / close.shift(63) - 1).abs()
    efficiency_63 = (directional_63 / path_63.replace(0, pd.NA)).dropna()

    adx = ta.adx(window["High"], window["Low"], window["Close"], length=14)
    adx_col = _indicator_column(adx, "ADX_") if adx is not None and not adx.empty else None
    adx_series = adx[adx_col].dropna() if adx_col else pd.Series(dtype="float64")

    ema20 = ta.ema(close, length=20)
    ema50 = ta.ema(close, length=50)
    if ema20 is None:
        ema20 = close.ewm(span=20, adjust=False).mean()
    if ema50 is None:
        ema50 = close.ewm(span=50, adjust=False).mean()
    ema_mask = (close > ema50) & (ema20 > ema50)
    ema_bull_persistence = float(ema_mask.dropna().mean()) if not ema_mask.dropna().empty else 0.0

    st = ta.supertrend(window["High"], window["Low"], window["Close"], length=7, multiplier=3.0)
    st_dir_col = _indicator_column(st, "SUPERTd_") if st is not None and not st.empty else None
    if st_dir_col:
        dirs = st[st_dir_col].dropna()
        flips = int((dirs != dirs.shift(1)).sum() - 1) if len(dirs) > 1 else 0
    else:
        flips = 0
    years = max((window.index.max() - window.index.min()).days / 365.25, 1 / 365.25)

    atr = ta.atr(window["High"], window["Low"], window["Close"], length=14)
    if atr is None:
        true_range = pd.concat(
            [
                window["High"] - window["Low"],
                (window["High"] - close.shift(1)).abs(),
                (window["Low"] - close.shift(1)).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = true_range.rolling(14, min_periods=1).mean()
    atr_pct = (atr / close).replace([float("inf"), -float("inf")], pd.NA).dropna()
    atr_pct_median = float(atr_pct.median()) if not atr_pct.empty else 0.0
    atr_iqr = float(atr_pct.quantile(0.75) - atr_pct.quantile(0.25)) if not atr_pct.empty else 0.0

    features = {
        "trendEfficiency63Median": float(efficiency_63.median()) if not efficiency_63.empty else 0.0,
        "adx14TrendShare": float((adx_series >= 20).mean()) if not adx_series.empty else 0.0,
        "emaBullPersistence": ema_bull_persistence,
        "stFlipRatePerYear": flips / years,
        "atrPctMedian": atr_pct_median,
        "atrPctIqrOverMedian": atr_iqr / atr_pct_median if atr_pct_median > 0 else 0.0,
    }
    return {key: round(_finite_float(value), 10) for key, value in features.items()}


HISTORY_RAW_KEYS = [
    "excessRddSafe",
    "drawdownReductionPct",
    "excessLogReturn",
    "avgTradeReturnPct",
]

SHAPE_RAW_KEYS = [
    "trendEfficiency63Median",
    "adx14TrendShare",
    "emaBullPersistence",
    "negStFlipRatePerYear",
    "negAtrPctIqrOverMedian",
]


def _score_rows(rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    enriched: List[Dict[str, object]] = []
    for row in rows:
        shape = row.get("shapeFeatures", {}) or {}
        next_row = {**row, **_history_raw_fields(row), **shape}
        next_row["negStFlipRatePerYear"] = -_finite_float(shape.get("stFlipRatePerYear"))
        next_row["negAtrPctIqrOverMedian"] = -_finite_float(shape.get("atrPctIqrOverMedian"))
        enriched.append(next_row)

    normalized = _robust_normalize_rows(enriched, HISTORY_RAW_KEYS + SHAPE_RAW_KEYS)
    scored: List[Dict[str, object]] = []
    for row in normalized:
        history_score = (
            0.45 * _finite_float(row.get("excessRddSafeZ"))
            + 0.25 * _finite_float(row.get("drawdownReductionPctZ"))
            + 0.20 * _finite_float(row.get("excessLogReturnZ"))
            + 0.10 * _finite_float(row.get("avgTradeReturnPctZ"))
        )
        adjusted_history = history_score * _finite_float(row.get("tradeReliability"))
        shape_score = (
            0.30 * _finite_float(row.get("trendEfficiency63MedianZ"))
            + 0.25 * _finite_float(row.get("adx14TrendShareZ"))
            + 0.20 * _finite_float(row.get("emaBullPersistenceZ"))
            + 0.15 * _finite_float(row.get("negStFlipRatePerYearZ"))
            + 0.10 * _finite_float(row.get("negAtrPctIqrOverMedianZ"))
        )
        history_contribution = 0.60 * adjusted_history
        shape_contribution = 0.40 * shape_score
        penalty = _finite_float(row.get("insufficientTradePenalty"))
        scored.append(
            {
                **row,
                "historyScore": history_score,
                "adjustedHistoryScore": adjusted_history,
                "shapeScore": shape_score,
                "historyContribution": history_contribution,
                "shapeContribution": shape_contribution,
                "hybridScore": history_contribution + shape_contribution - penalty,
            }
        )
    return scored


def _mean(values: List[float]) -> float:
    values = [_finite_float(value) for value in values]
    return sum(values) / len(values) if values else 0.0


def _median(values: List[float]) -> float:
    return float(pd.Series([_finite_float(value) for value in values]).median()) if values else 0.0


def _spearman(x_values: List[float], y_values: List[float]):
    pairs = [
        (_finite_float(x), _finite_float(y))
        for x, y in zip(x_values, y_values)
        if math.isfinite(_finite_float(x)) and math.isfinite(_finite_float(y))
    ]
    if len(pairs) < 2:
        return None
    x_rank = pd.Series([pair[0] for pair in pairs], dtype="float64").rank(method="average")
    y_rank = pd.Series([pair[1] for pair in pairs], dtype="float64").rank(method="average")
    if float(x_rank.std()) == 0.0 or float(y_rank.std()) == 0.0:
        return None
    corr = float(x_rank.corr(y_rank))
    return round(corr, 10) if math.isfinite(corr) else None


def _tier_summary(rows: List[Dict[str, object]]) -> Dict[str, object]:
    if not rows:
        return {
            "symbolCount": 0,
            "avgTestExcessRddSafe": 0.0,
            "medianTestExcessRddSafe": 0.0,
            "avgTestDailyStReturnPct": 0.0,
            "avgTestDailyStMaxDrawdownPct": 0.0,
            "beatBuyHoldRddRate": 0.0,
        }
    return {
        "symbolCount": len(rows),
        "avgTestExcessRddSafe": _mean([row.get("testExcessRddSafe", 0.0) for row in rows]),
        "medianTestExcessRddSafe": _median([row.get("testExcessRddSafe", 0.0) for row in rows]),
        "avgTestDailyStReturnPct": _mean([row.get("testDailyStReturnPct", 0.0) for row in rows]),
        "avgTestDailyStMaxDrawdownPct": _mean([row.get("testDailyStMaxDrawdownPct", 0.0) for row in rows]),
        "beatBuyHoldRddRate": (
            sum(1 for row in rows if bool(row.get("testBeatBuyHoldRdd"))) / len(rows)
        ),
    }


def _summarize_score_mode(rows: List[Dict[str, object]], prefix: str) -> Dict[str, object]:
    score_key = f"{prefix}Score"
    tier_key = f"{prefix}Tier"
    result = {"byAssetBucket": {}}
    for bucket in sorted({str(row.get("assetBucket", "unknown")) for row in rows}):
        bucket_rows = [row for row in rows if str(row.get("assetBucket", "unknown")) == bucket]
        tiers = {
            tier: _tier_summary([row for row in bucket_rows if row.get(tier_key) == tier])
            for tier in ["top", "mid", "bottom"]
        }
        top = tiers["top"]
        bottom = tiers["bottom"]
        result["byAssetBucket"][bucket] = {
            "symbolCount": len(bucket_rows),
            "rankCorrelation": _spearman(
                [_finite_float(row.get(score_key)) for row in bucket_rows],
                [_finite_float(row.get("testExcessRddSafe")) for row in bucket_rows],
            ),
            "tiers": tiers,
            "topMinusBottom": {
                "testExcessRddSafe": top["avgTestExcessRddSafe"] - bottom["avgTestExcessRddSafe"],
                "testDailyStReturnPct": (
                    top["avgTestDailyStReturnPct"] - bottom["avgTestDailyStReturnPct"]
                ),
                "testDailyStMaxDrawdownPct": (
                    top["avgTestDailyStMaxDrawdownPct"] - bottom["avgTestDailyStMaxDrawdownPct"]
                ),
                "beatBuyHoldRddRate": top["beatBuyHoldRddRate"] - bottom["beatBuyHoldRddRate"],
            },
        }
    return result


def _parent_market_bucket(asset_bucket: str) -> str:
    if asset_bucket.startswith("a_share"):
        return "a_share"
    if asset_bucket.startswith("us_"):
        return "us"
    return asset_bucket


def _with_normalization_cohorts(rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    bucket_counts = {}
    for row in rows:
        bucket = str(row.get("assetBucket", "unknown"))
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
    result = []
    for row in rows:
        bucket = str(row.get("assetBucket", "unknown"))
        result.append(
            {
                **row,
                "normalizationCohort": (
                    bucket if bucket_counts.get(bucket, 0) >= 8 else _parent_market_bucket(bucket)
                ),
                "cohortSize": bucket_counts.get(bucket, 0),
            }
        )
    return result


def _validation_fields(test_row: Dict[str, object]) -> Dict[str, object]:
    daily_st = test_row.get("dailySt", {}) or {}
    buy_hold = test_row.get("buyHold", {}) or {}
    st_return = _finite_float(daily_st.get("returnPct"))
    st_drawdown = _finite_float(daily_st.get("maxDrawdownPct"))
    buy_hold_return = _finite_float(buy_hold.get("returnPct"))
    buy_hold_drawdown = _finite_float(buy_hold.get("maxDrawdownPct"))
    st_rdd = _safe_rdd(st_return, st_drawdown)
    buy_hold_rdd = _safe_rdd(buy_hold_return, buy_hold_drawdown)
    return {
        "testDailyStReturnPct": st_return,
        "testDailyStMaxDrawdownPct": st_drawdown,
        "testDailyStRddSafe": st_rdd,
        "testBuyHoldReturnPct": buy_hold_return,
        "testBuyHoldMaxDrawdownPct": buy_hold_drawdown,
        "testBuyHoldRddSafe": buy_hold_rdd,
        "testExcessRddSafe": st_rdd - buy_hold_rdd,
        "testExcessLogReturn": math.log(max(0.01, 1 + st_return / 100)) - math.log(
            max(0.01, 1 + buy_hold_return / 100)
        ),
        "testBeatBuyHoldReturn": st_return > buy_hold_return,
        "testBeatBuyHoldRdd": st_rdd > buy_hold_rdd,
        "testTradeCount": int(_finite_float(daily_st.get("tradeCount"))),
    }


def _build_window_rows(prepared: List[Dict[str, object]], window: Dict[str, str]) -> List[Dict[str, object]]:
    train_rows = []
    tests_by_symbol: Dict[str, Dict[str, object]] = {}
    for item in prepared:
        meta = item["meta"]
        daily = item["daily"]
        weekly = item["weekly"]
        train = compare_st._analyze_symbol_from_data(
            meta,
            daily,
            weekly,
            window["trainStart"],
            window["trainEnd"],
            include_variants=False,
        )
        test = compare_st._analyze_symbol_from_data(
            meta,
            daily,
            weekly,
            window["testStart"],
            window["testEnd"],
            include_variants=False,
        )
        if train is None or test is None:
            continue
        symbol = str(meta["symbol"])
        asset_bucket = str(train.get("assetBucket") or compare_st._asset_bucket(meta))
        train_rows.append(
            {
                **meta,
                "assetBucket": asset_bucket,
                "trainStart": window["trainStart"],
                "trainEnd": window["trainEnd"],
                "testStart": window["testStart"],
                "testEnd": window["testEnd"],
                "dailySt": train["dailySt"],
                "buyHold": train["buyHold"],
                "shapeFeatures": _compute_shape_features(
                    daily,
                    window["trainStart"],
                    window["trainEnd"],
                ),
            }
        )
        tests_by_symbol[symbol] = test

    scored = _score_rows(_with_normalization_cohorts(train_rows))
    for score_key, prefix in [
        ("historyScore", "history"),
        ("shapeScore", "shape"),
        ("hybridScore", "hybrid"),
    ]:
        scored = _assign_tiers(scored, score_key, prefix)

    result = []
    for row in scored:
        test = tests_by_symbol.get(str(row["symbol"]))
        if not test:
            continue
        result.append({**row, **_validation_fields(test)})
    return result


def _load_prepared_symbols(symbols: Optional[List[str]] = None) -> List[Dict[str, object]]:
    if symbols:
        metas = [{"symbol": symbol.strip().upper(), "alias": "", "group": "cli"} for symbol in symbols]
    else:
        metas = compare_st._load_watchlist_symbols()
    prepared = []
    for meta in metas:
        daily = compare_st._load_daily(meta["symbol"])
        if daily is None:
            continue
        weekly = compare_st._load_weekly(meta["symbol"], daily)
        prepared.append({"meta": meta, "daily": daily, "weekly": weekly})
    return prepared


def _summarize_all(rows: List[Dict[str, object]]) -> Dict[str, object]:
    return {
        "symbolWindowCount": len(rows),
        "scoreModes": {
            "history": _summarize_score_mode(rows, "history"),
            "shape": _summarize_score_mode(rows, "shape"),
            "hybrid": _summarize_score_mode(rows, "hybrid"),
        },
    }


def build_supertrend_fit_research(
    start: str,
    end: str,
    train_years: int = 2,
    test_months: int = 6,
    step_months: int = 6,
    symbols: Optional[List[str]] = None,
) -> Dict[str, object]:
    prepared = _load_prepared_symbols(symbols)
    windows = _build_walk_forward_windows(
        start,
        end,
        train_years=train_years,
        test_months=test_months,
        step_months=step_months,
    )
    all_rows: List[Dict[str, object]] = []
    window_payloads = []
    for window in windows:
        rows = _build_window_rows(prepared, window)
        all_rows.extend(rows)
        window_payloads.append(
            {
                **window,
                "symbolWindowCount": len(rows),
                "summary": _summarize_all(rows),
            }
        )

    bucket_counts = {}
    for item in prepared:
        bucket = compare_st._asset_bucket(item["meta"])
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1

    return {
        "params": {
            "start": start,
            "end": end,
            "trainYears": train_years,
            "testMonths": test_months,
            "stepMonths": step_months,
            "strategy": "dailySt",
            "supertrendLength": 7,
            "supertrendMultiplier": 3.0,
            "scoreModes": ["history", "shape", "hybrid"],
            "execution": "training scores use prior window only; validation metrics are future six-month windows",
            "symbolCount": len(prepared),
            "assetBucketCounts": bucket_counts,
        },
        "windows": window_payloads,
        "rows": all_rows,
        "summary": _summarize_all(all_rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Research SuperTrend fit scoring with walk-forward validation.")
    parser.add_argument("--start", default="2021-06-05")
    parser.add_argument("--end", default=pd.Timestamp.today().date().isoformat())
    parser.add_argument("--train-years", type=int, default=2)
    parser.add_argument("--test-months", type=int, default=6)
    parser.add_argument("--step-months", type=int, default=6)
    parser.add_argument("--symbols", nargs="*", help="Optional symbol subset. Defaults to watchlist.")
    parser.add_argument(
        "--output",
        default=str(BACKEND_DIR / "backtest_results" / "supertrend_fit_research_2026-06-05.json"),
    )
    parser.add_argument("--json", action="store_true", help="Print JSON payload to stdout.")
    args = parser.parse_args()

    payload = build_supertrend_fit_research(
        args.start,
        args.end,
        train_years=args.train_years,
        test_months=args.test_months,
        step_months=args.step_months,
        symbols=args.symbols,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            json.dumps(
                {
                    "output": str(output_path),
                    "params": payload["params"],
                    "summary": payload["summary"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
