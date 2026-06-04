#!/usr/bin/env python3
"""Compare daily, weekly, and weekly-filtered daily SuperTrend backtests.

This is a research script only. It reads cached parquet files and does not
modify backend strategy code or cached API results.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd
import pandas_ta as ta


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
DATA_DIR = BACKEND_DIR / "data"
WATCHLIST_FILE = BACKEND_DIR / "watchlist.json"

ST_LENGTH = 7
ST_MULTIPLIER = 3.0
BB_LENGTH = 20
BB_STD = 2.0
BB_RANK_WINDOW = 252
ATR_LENGTH = 14
FEE_BPS = 5.0
SLIPPAGE_BPS = 5.0

STRATEGY_KEYS = [
    "dailySt",
    "weeklySt",
    "weeklyDailySt",
    "weeklyDailyStBbSqueeze20",
    "dailyStBbSqueeze20",
    "dailyStBbSqueeze30",
    "dailyStNoChaseAtr1",
]

COMMODITY_SYMBOLS = {"GC=F", "SI=F", "CL=F", "HG=F", "NG=F"}
US_ETF_SYMBOLS = {
    "SPY",
    "QQQ",
    "DIA",
    "IWM",
    "TLT",
    "GLD",
    "SLV",
    "USO",
    "XLF",
    "XLK",
    "XLE",
    "XLV",
    "XLY",
    "XLP",
    "XLI",
    "XLU",
    "XLB",
    "VNQ",
    "ARKK",
}
A_SHARE_ETF_PREFIXES = ("15", "51", "56", "58")


def _date_str(value) -> str:
    return pd.Timestamp(value).date().isoformat()


def _price_with_bps(price: float, direction: str) -> float:
    multiplier = 1 + SLIPPAGE_BPS / 10_000 if direction == "buy" else 1 - SLIPPAGE_BPS / 10_000
    return float(price) * multiplier


def _load_watchlist_symbols() -> List[Dict[str, str]]:
    payload = json.loads(WATCHLIST_FILE.read_text())
    rows: List[Dict[str, str]] = []
    seen = set()
    for group in payload:
        for item in group.get("symbols", []):
            symbol = item.get("symbol", item) if isinstance(item, dict) else item
            if not isinstance(symbol, str):
                continue
            normalized = symbol.strip().upper()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            rows.append(
                {
                    "symbol": normalized,
                    "alias": item.get("alias", "") if isinstance(item, dict) else "",
                    "group": str(group.get("name", "")),
                }
            )
    return rows


def _load_daily(symbol: str) -> Optional[pd.DataFrame]:
    path = DATA_DIR / f"{symbol.upper()}.parquet"
    if not path.exists():
        return None
    daily = pd.read_parquet(path).sort_index()
    return daily if not daily.empty else None


def _load_weekly(symbol: str, daily: pd.DataFrame) -> pd.DataFrame:
    path = DATA_DIR / f"{symbol.upper()}_weekly.parquet"
    if path.exists():
        weekly = pd.read_parquet(path).sort_index()
        if not weekly.empty:
            return weekly
    return (
        daily.resample("W")
        .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
        .dropna(subset=["Open", "High", "Low", "Close"])
    )


def _prepare_symbol_data(metas: List[Dict[str, str]]) -> List[Dict[str, object]]:
    prepared = []
    for meta in metas:
        daily = _load_daily(meta["symbol"])
        if daily is None:
            continue
        weekly = _load_weekly(meta["symbol"], daily)
        prepared.append({"meta": meta, "daily": daily, "weekly": weekly})
    return prepared


def _add_supertrend(
    df: pd.DataFrame,
    prefix: str,
    st_length: int = ST_LENGTH,
    st_multiplier: float = ST_MULTIPLIER,
) -> pd.DataFrame:
    frame = df.sort_index().copy()
    st = ta.supertrend(
        frame["High"],
        frame["Low"],
        frame["Close"],
        length=st_length,
        multiplier=st_multiplier,
    )
    if st is None or st.empty:
        frame[f"{prefix}_dir"] = pd.NA
        frame[f"{prefix}_line"] = pd.NA
        return frame
    dir_col = next((c for c in st.columns if c.startswith("SUPERTd_")), None)
    line_col = next((c for c in st.columns if c.startswith("SUPERT_") and not c.startswith("SUPERTd_")), None)
    frame[f"{prefix}_dir"] = st[dir_col] if dir_col else pd.NA
    frame[f"{prefix}_line"] = st[line_col] if line_col else pd.NA
    return frame


def _rolling_percentile_rank(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=1).apply(
        lambda values: pd.Series(values).rank(pct=True).iloc[-1],
        raw=False,
    )


def _add_bollinger_context(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.sort_index().copy()
    bbands = ta.bbands(frame["Close"], length=BB_LENGTH, std=BB_STD)
    if bbands is None or bbands.empty:
        frame["_bb_width_pct"] = pd.NA
        frame["_bb_width_rank_252"] = pd.NA
        return frame
    lower_col = next((c for c in bbands.columns if c.startswith("BBL_")), None)
    upper_col = next((c for c in bbands.columns if c.startswith("BBU_")), None)
    if not lower_col or not upper_col:
        frame["_bb_width_pct"] = pd.NA
        frame["_bb_width_rank_252"] = pd.NA
        return frame
    frame["_bb_width_pct"] = (bbands[upper_col] - bbands[lower_col]) / frame["Close"] * 100
    frame["_bb_width_rank_252"] = _rolling_percentile_rank(frame["_bb_width_pct"], BB_RANK_WINDOW)
    return frame


def _add_atr_context(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.sort_index().copy()
    atr = ta.atr(frame["High"], frame["Low"], frame["Close"], length=ATR_LENGTH)
    frame["_atr"] = atr if atr is not None else pd.NA
    return frame


def _first_daily_idx_after(daily: pd.DataFrame, signal_date) -> Optional[int]:
    signal_ts = pd.Timestamp(signal_date)
    positions = daily.index.searchsorted(signal_ts, side="right")
    if positions >= len(daily):
        return None
    return int(positions)


def _latest_weekly_dir(weekly: pd.DataFrame, date) -> Optional[float]:
    window = weekly[weekly.index <= pd.Timestamp(date)]
    if window.empty or pd.isna(window.iloc[-1].get("_weekly_dir")):
        return None
    return float(window.iloc[-1]["_weekly_dir"])


def _weekly_dirs_for_index(index: pd.Index, weekly: pd.DataFrame) -> List[Optional[float]]:
    if weekly.empty or "_weekly_dir" not in weekly.columns:
        return [None] * len(index)

    weekly_index = weekly.index
    positions = weekly_index.searchsorted(pd.DatetimeIndex(index), side="right") - 1
    weekly_dirs = weekly["_weekly_dir"].to_numpy()
    aligned: List[Optional[float]] = []
    for position in positions:
        if position < 0:
            aligned.append(None)
            continue
        value = weekly_dirs[int(position)]
        aligned.append(None if pd.isna(value) else float(value))
    return aligned


def _trade_return(side: str, entry: float, exit_price: float) -> float:
    if side != "long":
        raise ValueError("This script only supports long strategy comparisons")
    gross = (float(exit_price) - float(entry)) / float(entry) * 100
    return gross - FEE_BPS * 2 / 100


def _summarize_trades(
    daily: pd.DataFrame,
    trades: List[Dict[str, object]],
    open_position: Optional[Dict[str, object]],
    start: str,
    end: str,
) -> Dict[str, object]:
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    final_equity = 1.0
    active = None
    trades_by_entry = {int(trade["entryIdx"]): trade for trade in trades}

    for idx, (ts, row) in enumerate(daily.iterrows()):
        if ts < start_ts or ts > end_ts:
            continue
        if active is not None and active.get("exitIdx") == idx:
            equity *= 1 + float(active["returnPct"]) / 100
            active = None
        if idx in trades_by_entry:
            active = trades_by_entry[idx]
        if open_position is not None and int(open_position["entryIdx"]) == idx:
            active = open_position

        if active is not None:
            mark = equity * (float(row["Close"]) / float(active["entryPrice"]))
        else:
            mark = equity

        peak = max(peak, mark)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - mark) / peak * 100)
        final_equity = mark

    closed_returns = [float(trade["returnPct"]) for trade in trades]
    wins = [ret for ret in closed_returns if ret > 0]
    total_return = (final_equity - 1) * 100
    return {
        "returnPct": total_return,
        "maxDrawdownPct": max_drawdown,
        "returnDrawdownRatio": total_return / max_drawdown if max_drawdown > 0 else None,
        "tradeCount": len(trades),
        "trades": trades,
        "winRatePct": len(wins) / len(trades) * 100 if trades else 0.0,
        "averageTradeReturnPct": sum(closed_returns) / len(closed_returns) if closed_returns else 0.0,
        "openPosition": (
            {
                "entryDate": open_position["entryDate"],
                "entryPrice": open_position["entryPrice"],
                "currentDate": _date_str(daily[daily.index <= end_ts].index[-1]),
                "currentPrice": float(daily[daily.index <= end_ts].iloc[-1]["Close"]),
            }
            if open_position
            else None
        ),
    }


def _buy_hold_stats(daily: pd.DataFrame, start: str, end: str) -> Dict[str, object]:
    window = daily[(daily.index >= pd.Timestamp(start)) & (daily.index <= pd.Timestamp(end))].dropna(subset=["Close"])
    if window.empty:
        return {"returnPct": 0.0, "maxDrawdownPct": 0.0, "returnDrawdownRatio": None}
    entry_source = "Open" if "Open" in window.columns and pd.notna(window.iloc[0].get("Open")) else "Close"
    entry = _price_with_bps(float(window.iloc[0][entry_source]), "buy")
    exit_price = _price_with_bps(float(window.iloc[-1]["Close"]), "sell")
    total_return = _trade_return("long", entry, exit_price)
    equity = window["Close"].astype(float) / entry
    drawdowns = (equity.cummax() - equity) / equity.cummax() * 100
    max_drawdown = float(drawdowns.max()) if not drawdowns.empty else 0.0
    return {
        "returnPct": total_return,
        "maxDrawdownPct": max_drawdown,
        "returnDrawdownRatio": total_return / max_drawdown if max_drawdown > 0 else None,
    }


def _build_strategy_context(
    daily: pd.DataFrame,
    weekly: pd.DataFrame,
    st_length: int = ST_LENGTH,
    st_multiplier: float = ST_MULTIPLIER,
    include_entry_context: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily_st = _add_supertrend(daily, "_daily", st_length, st_multiplier)
    if include_entry_context:
        daily_st = _add_atr_context(_add_bollinger_context(daily_st))
    weekly_st = _add_supertrend(weekly, "_weekly", st_length, st_multiplier)
    return daily_st, weekly_st


def _daily_st_strategy(
    symbol: str,
    daily: pd.DataFrame,
    weekly: pd.DataFrame,
    start: str,
    end: str,
    st_length: int = ST_LENGTH,
    st_multiplier: float = ST_MULTIPLIER,
    weekly_filter: bool = False,
    weekly_exit: bool = False,
    bb_squeeze_max_rank: Optional[float] = None,
    max_entry_distance_atr: Optional[float] = None,
) -> Dict[str, object]:
    del symbol
    daily_st, weekly_st = _build_strategy_context(daily, weekly, st_length, st_multiplier)
    return _daily_st_strategy_from_context(
        daily_st,
        weekly_st,
        start,
        end,
        weekly_filter=weekly_filter,
        weekly_exit=weekly_exit,
        bb_squeeze_max_rank=bb_squeeze_max_rank,
        max_entry_distance_atr=max_entry_distance_atr,
    )


def _daily_st_strategy_from_context(
    daily_st: pd.DataFrame,
    weekly_st: pd.DataFrame,
    start: str,
    end: str,
    weekly_filter: bool = False,
    weekly_exit: bool = False,
    bb_squeeze_max_rank: Optional[float] = None,
    max_entry_distance_atr: Optional[float] = None,
) -> Dict[str, object]:
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    trades: List[Dict[str, object]] = []
    position: Optional[Dict[str, object]] = None
    weekly_dirs = _weekly_dirs_for_index(daily_st.index, weekly_st)

    for signal_idx in range(1, len(daily_st) - 1):
        signal_date = daily_st.index[signal_idx]
        exec_idx = signal_idx + 1
        exec_date = daily_st.index[exec_idx]
        if exec_date < start_ts:
            continue
        if exec_date > end_ts:
            break

        prev_dir = daily_st.iloc[signal_idx - 1].get("_daily_dir")
        cur_dir = daily_st.iloc[signal_idx].get("_daily_dir")
        if pd.isna(prev_dir) or pd.isna(cur_dir):
            continue
        daily_bull = float(prev_dir) == -1 and float(cur_dir) == 1
        daily_bear = float(prev_dir) == 1 and float(cur_dir) == -1
        weekly_dir = weekly_dirs[signal_idx]
        weekly_bull = weekly_dir == 1
        weekly_bear = weekly_dir == -1
        raw_open = float(daily_st.iloc[exec_idx]["Open"]) if pd.notna(daily_st.iloc[exec_idx].get("Open")) else float(daily_st.iloc[exec_idx]["Close"])

        should_exit = position is not None and (daily_bear or (weekly_exit and weekly_bear))
        if should_exit and position is not None:
            exit_price = _price_with_bps(raw_open, "sell")
            trades.append(
                {
                    **position,
                    "exitIdx": exec_idx,
                    "exitDate": _date_str(exec_date),
                    "exitPrice": exit_price,
                    "returnPct": _trade_return("long", float(position["entryPrice"]), exit_price),
                    "exitReason": "weekly_bear" if weekly_exit and weekly_bear and not daily_bear else "daily_bear",
                }
            )
            position = None
            continue

        passes_squeeze = True
        if bb_squeeze_max_rank is not None:
            bb_rank = daily_st.iloc[signal_idx].get("_bb_width_rank_252")
            passes_squeeze = pd.notna(bb_rank) and float(bb_rank) <= float(bb_squeeze_max_rank)

        passes_no_chase = True
        if max_entry_distance_atr is not None:
            st_line = daily_st.iloc[signal_idx].get("_daily_line")
            atr = daily_st.iloc[signal_idx].get("_atr")
            if pd.isna(st_line) or pd.isna(atr) or float(atr) <= 0:
                passes_no_chase = False
            else:
                distance_atr = max(0.0, raw_open - float(st_line)) / float(atr)
                passes_no_chase = distance_atr <= float(max_entry_distance_atr)

        can_enter = (
            daily_bull
            and (weekly_bull if weekly_filter else True)
            and passes_squeeze
            and passes_no_chase
        )
        if position is None and can_enter:
            position = {
                "entryIdx": exec_idx,
                "entryDate": _date_str(exec_date),
                "entryPrice": _price_with_bps(raw_open, "buy"),
            }

    return _summarize_trades(daily_st, trades, position, start, end)


def _weekly_st_strategy_from_context(
    daily: pd.DataFrame,
    weekly_st: pd.DataFrame,
    start: str,
    end: str,
) -> Dict[str, object]:
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    trades: List[Dict[str, object]] = []
    position: Optional[Dict[str, object]] = None

    for signal_idx in range(1, len(weekly_st)):
        signal_date = weekly_st.index[signal_idx]
        prev_dir = weekly_st.iloc[signal_idx - 1].get("_weekly_dir")
        cur_dir = weekly_st.iloc[signal_idx].get("_weekly_dir")
        if pd.isna(prev_dir) or pd.isna(cur_dir):
            continue
        exec_idx = _first_daily_idx_after(daily, signal_date)
        if exec_idx is None:
            continue
        exec_date = daily.index[exec_idx]
        if exec_date < start_ts:
            continue
        if exec_date > end_ts:
            break

        bull = float(prev_dir) == -1 and float(cur_dir) == 1
        bear = float(prev_dir) == 1 and float(cur_dir) == -1
        raw_open = float(daily.iloc[exec_idx]["Open"]) if pd.notna(daily.iloc[exec_idx].get("Open")) else float(daily.iloc[exec_idx]["Close"])

        if position is not None and bear:
            exit_price = _price_with_bps(raw_open, "sell")
            trades.append(
                {
                    **position,
                    "exitIdx": exec_idx,
                    "exitDate": _date_str(exec_date),
                    "exitPrice": exit_price,
                    "returnPct": _trade_return("long", float(position["entryPrice"]), exit_price),
                    "exitReason": "weekly_bear",
                }
            )
            position = None
        elif position is None and bull:
            position = {
                "entryIdx": exec_idx,
                "entryDate": _date_str(exec_date),
                "entryPrice": _price_with_bps(raw_open, "buy"),
            }

    return _summarize_trades(daily, trades, position, start, end)


def _weekly_st_strategy(
    daily: pd.DataFrame,
    weekly: pd.DataFrame,
    start: str,
    end: str,
    st_length: int = ST_LENGTH,
    st_multiplier: float = ST_MULTIPLIER,
) -> Dict[str, object]:
    weekly_st = _add_supertrend(weekly, "_weekly", st_length, st_multiplier)
    return _weekly_st_strategy_from_context(daily, weekly_st, start, end)


def _asset_bucket(meta: Dict[str, str]) -> str:
    symbol = meta["symbol"].upper()
    if symbol.endswith("-USD") and symbol.split("-")[0] in {"BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE"}:
        return "crypto"
    if symbol in COMMODITY_SYMBOLS:
        return "commodity"
    if symbol.endswith(".SS") or symbol.endswith(".SZ"):
        code = symbol.split(".")[0]
        return "a_share_etf" if code.startswith(A_SHARE_ETF_PREFIXES) else "a_share_stock"
    if symbol in US_ETF_SYMBOLS:
        return "us_etf"
    return "us_stock"


def _analyze_symbol(
    meta: Dict[str, str],
    start: str,
    end: str,
    st_length: int = ST_LENGTH,
    st_multiplier: float = ST_MULTIPLIER,
    include_variants: bool = True,
) -> Optional[Dict[str, object]]:
    symbol = meta["symbol"]
    daily = _load_daily(symbol)
    if daily is None:
        return None
    weekly = _load_weekly(symbol, daily)
    return _analyze_symbol_from_data(
        meta,
        daily,
        weekly,
        start,
        end,
        st_length=st_length,
        st_multiplier=st_multiplier,
        include_variants=include_variants,
    )


def _analyze_symbol_from_data(
    meta: Dict[str, str],
    daily: pd.DataFrame,
    weekly: pd.DataFrame,
    start: str,
    end: str,
    st_length: int = ST_LENGTH,
    st_multiplier: float = ST_MULTIPLIER,
    include_variants: bool = True,
) -> Optional[Dict[str, object]]:
    symbol = meta["symbol"]
    actual_end = min(pd.Timestamp(end), daily.index.max()).date().isoformat()
    if pd.Timestamp(actual_end) <= pd.Timestamp(start):
        return None
    daily_st, weekly_st = _build_strategy_context(
        daily,
        weekly,
        st_length,
        st_multiplier,
        include_entry_context=include_variants,
    )
    row = {
        **meta,
        "assetBucket": _asset_bucket(meta),
        "start": start,
        "end": actual_end,
        "buyHold": _buy_hold_stats(daily, start, actual_end),
        "dailySt": _daily_st_strategy_from_context(daily_st, weekly_st, start, actual_end),
    }
    if not include_variants:
        return row
    return {
        **row,
        "weeklySt": _weekly_st_strategy_from_context(daily, weekly_st, start, actual_end),
        "weeklyDailySt": _daily_st_strategy_from_context(
            daily_st,
            weekly_st,
            start,
            actual_end,
            weekly_filter=True,
            weekly_exit=True,
        ),
        "weeklyDailyStBbSqueeze20": _daily_st_strategy_from_context(
            daily_st,
            weekly_st,
            start,
            actual_end,
            weekly_filter=True,
            weekly_exit=True,
            bb_squeeze_max_rank=0.20,
        ),
        "dailyStBbSqueeze20": _daily_st_strategy_from_context(
            daily_st,
            weekly_st,
            start,
            actual_end,
            bb_squeeze_max_rank=0.20,
        ),
        "dailyStBbSqueeze30": _daily_st_strategy_from_context(
            daily_st,
            weekly_st,
            start,
            actual_end,
            bb_squeeze_max_rank=0.30,
        ),
        "dailyStNoChaseAtr1": _daily_st_strategy_from_context(
            daily_st,
            weekly_st,
            start,
            actual_end,
            max_entry_distance_atr=1.0,
        ),
    }


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def _summarize_strategy(rows: List[Dict[str, object]], key: str) -> Dict[str, object]:
    usable_rows = [row for row in rows if key in row]
    ratios = [
        float(row[key]["returnDrawdownRatio"])
        for row in usable_rows
        if row[key].get("returnDrawdownRatio") is not None
    ]
    return {
        "avgReturnPct": _mean(float(row[key]["returnPct"]) for row in usable_rows),
        "medianReturnPct": float(pd.Series([row[key]["returnPct"] for row in usable_rows]).median()) if usable_rows else 0.0,
        "avgMaxDrawdownPct": _mean(float(row[key]["maxDrawdownPct"]) for row in usable_rows),
        "avgReturnDrawdownRatio": _mean(ratios),
        "medianReturnDrawdownRatio": float(pd.Series(ratios).median()) if ratios else 0.0,
        "beatBuyHoldReturnCount": sum(row[key]["returnPct"] > row["buyHold"]["returnPct"] for row in usable_rows),
        "beatBuyHoldRatioCount": sum(
            (row[key]["returnDrawdownRatio"] is not None)
            and (row["buyHold"]["returnDrawdownRatio"] is not None)
            and row[key]["returnDrawdownRatio"] > row["buyHold"]["returnDrawdownRatio"]
            for row in usable_rows
        ),
    }


def _summarize(rows: List[Dict[str, object]]) -> Dict[str, object]:
    summary = {"symbolCount": len(rows)}
    for key in STRATEGY_KEYS:
        summary[key] = _summarize_strategy(rows, key)
    by_bucket: Dict[str, Dict[str, object]] = {}
    for bucket in sorted({str(row.get("assetBucket", "unknown")) for row in rows}):
        bucket_rows = [row for row in rows if str(row.get("assetBucket", "unknown")) == bucket]
        by_bucket[bucket] = {"symbolCount": len(bucket_rows)}
        for key in STRATEGY_KEYS:
            by_bucket[bucket][key] = _summarize_strategy(bucket_rows, key)
    summary["byAssetBucket"] = by_bucket
    return summary


def _strategy_score(strategy_summary: Dict[str, object]) -> float:
    ratio = strategy_summary.get("avgReturnDrawdownRatio")
    if ratio is not None:
        return float(ratio)
    return float(strategy_summary.get("avgReturnPct", 0.0))


def _grid_config_payload(
    st_length: int,
    st_multiplier: float,
    rows: List[Dict[str, object]],
) -> Dict[str, object]:
    summary = _summarize(rows)
    return {
        "stLength": st_length,
        "stMultiplier": st_multiplier,
        "symbolCount": len(rows),
        "summary": summary,
    }


def _best_grid_config(configs: List[Dict[str, object]], bucket: Optional[str] = None) -> Optional[Dict[str, object]]:
    candidates = []
    for config in configs:
        summary = config["summary"]
        if bucket is None:
            strategy_summary = summary["dailySt"]
        else:
            bucket_summary = summary.get("byAssetBucket", {}).get(bucket)
            if not bucket_summary:
                continue
            strategy_summary = bucket_summary["dailySt"]
        candidates.append((config, _strategy_score(strategy_summary)))
    if not candidates:
        return None
    best, score = max(candidates, key=lambda item: item[1])
    return {
        "stLength": best["stLength"],
        "stMultiplier": best["stMultiplier"],
        "score": score,
        "dailySt": (
            best["summary"]["dailySt"]
            if bucket is None
            else best["summary"]["byAssetBucket"][bucket]["dailySt"]
        ),
    }


def _run_parameter_grid(
    metas: List[Dict[str, str]],
    start: str,
    end: str,
    st_lengths: List[int],
    st_multipliers: List[float],
) -> Dict[str, object]:
    prepared = _prepare_symbol_data(metas)
    configs: List[Dict[str, object]] = []
    for st_length in st_lengths:
        for st_multiplier in st_multipliers:
            rows = [
                row
                for item in prepared
                if (
                    row := _analyze_symbol_from_data(
                        item["meta"],
                        item["daily"],
                        item["weekly"],
                        start,
                        end,
                        st_length=st_length,
                        st_multiplier=st_multiplier,
                        include_variants=False,
                    )
                )
                is not None
            ]
            configs.append(_grid_config_payload(st_length, st_multiplier, rows))

    buckets = sorted(
        {
            bucket
            for config in configs
            for bucket in config["summary"].get("byAssetBucket", {}).keys()
        }
    )
    return {
        "configs": configs,
        "bestOverall": _best_grid_config(configs),
        "bestByAssetBucket": {
            bucket: best
            for bucket in buckets
            if (best := _best_grid_config(configs, bucket)) is not None
        },
    }


def _year_windows(start: str, end: str) -> List[Dict[str, str]]:
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    windows = []
    for year in range(start_ts.year, end_ts.year + 1):
        year_start = max(start_ts, pd.Timestamp(year=year, month=1, day=1))
        year_end = min(end_ts, pd.Timestamp(year=year, month=12, day=31))
        if year_start <= year_end:
            windows.append(
                {
                    "year": str(year),
                    "start": year_start.date().isoformat(),
                    "end": year_end.date().isoformat(),
                }
            )
    return windows


def _build_annual_summary(
    metas: List[Dict[str, str]],
    start: str,
    end: str,
    st_length: int = ST_LENGTH,
    st_multiplier: float = ST_MULTIPLIER,
) -> List[Dict[str, object]]:
    results = []
    for window in _year_windows(start, end):
        rows = [
            row
            for meta in metas
            if (
                row := _analyze_symbol(
                    meta,
                    window["start"],
                    window["end"],
                    st_length=st_length,
                    st_multiplier=st_multiplier,
                )
            )
            is not None
        ]
        results.append({**window, "summary": _summarize(rows)})
    return results


def _print_table(rows: List[Dict[str, object]], limit: int) -> None:
    def fmt(value) -> str:
        if value is None:
            return "-"
        return f"{float(value):.2f}"

    headers = [
        "symbol",
        "alias",
        "bucket",
        "buy_hold",
        "daily_st",
        "weekly_st",
        "weekly+daily",
        "weekly+bb20",
        "bb_p20",
        "bb_p30",
        "no_chase",
        "daily_r/dd",
        "weekly_r/dd",
        "combo_r/dd",
        "weekly_bb20_r/dd",
        "bb20_r/dd",
        "bb30_r/dd",
        "no_chase_r/dd",
    ]
    print("\t".join(headers))
    for row in rows[:limit]:
        print(
            "\t".join(
                [
                    row["symbol"],
                    row.get("alias", ""),
                    row.get("assetBucket", ""),
                    fmt(row["buyHold"]["returnPct"]),
                    fmt(row["dailySt"]["returnPct"]),
                    fmt(row["weeklySt"]["returnPct"]),
                    fmt(row["weeklyDailySt"]["returnPct"]),
                    fmt(row["weeklyDailyStBbSqueeze20"]["returnPct"]),
                    fmt(row["dailyStBbSqueeze20"]["returnPct"]),
                    fmt(row["dailyStBbSqueeze30"]["returnPct"]),
                    fmt(row["dailyStNoChaseAtr1"]["returnPct"]),
                    fmt(row["dailySt"]["returnDrawdownRatio"]),
                    fmt(row["weeklySt"]["returnDrawdownRatio"]),
                    fmt(row["weeklyDailySt"]["returnDrawdownRatio"]),
                    fmt(row["weeklyDailyStBbSqueeze20"]["returnDrawdownRatio"]),
                    fmt(row["dailyStBbSqueeze20"]["returnDrawdownRatio"]),
                    fmt(row["dailyStBbSqueeze30"]["returnDrawdownRatio"]),
                    fmt(row["dailyStNoChaseAtr1"]["returnDrawdownRatio"]),
                ]
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare SuperTrend timeframes from cached parquet data.")
    parser.add_argument("--symbols", nargs="*", help="Symbols to run. Defaults to watchlist.")
    parser.add_argument("--start", default="2021-06-04")
    parser.add_argument("--end", default=None)
    parser.add_argument("--st-length", type=int, default=ST_LENGTH, help="SuperTrend length for the main comparison.")
    parser.add_argument("--st-multiplier", type=float, default=ST_MULTIPLIER, help="SuperTrend multiplier for the main comparison.")
    parser.add_argument("--annual", action="store_true", help="Include annual stability summaries.")
    parser.add_argument("--param-grid", action="store_true", help="Run SuperTrend parameter grid research.")
    parser.add_argument("--st-lengths", nargs="*", type=int, default=[5, 7, 10, 14], help="Lengths for --param-grid.")
    parser.add_argument("--st-multipliers", nargs="*", type=float, default=[2.0, 3.0, 4.0], help="Multipliers for --param-grid.")
    parser.add_argument("--include-rows", action="store_true", help="Include full per-symbol rows when --param-grid is enabled.")
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--json", action="store_true", help="Print full JSON instead of a compact table.")
    args = parser.parse_args()

    if args.symbols:
        metas = [{"symbol": symbol.strip().upper(), "alias": "", "group": "cli"} for symbol in args.symbols]
    else:
        metas = _load_watchlist_symbols()

    today_end = args.end or pd.Timestamp.today().date().isoformat()
    rows = [
        row
        for meta in metas
        if (
            row := _analyze_symbol(
                meta,
                args.start,
                today_end,
                st_length=args.st_length,
                st_multiplier=args.st_multiplier,
            )
        )
        is not None
    ]
    rows.sort(key=lambda row: float(row["weeklyDailySt"]["returnDrawdownRatio"] or -999), reverse=True)

    payload = {
        "params": {
            "start": args.start,
            "end": today_end,
            "supertrendLength": args.st_length,
            "supertrendMultiplier": args.st_multiplier,
            "bollingerLength": BB_LENGTH,
            "bollingerStd": BB_STD,
            "bollingerRankWindow": BB_RANK_WINDOW,
            "atrLength": ATR_LENGTH,
            "feeBpsPerSide": FEE_BPS,
            "slippageBpsPerSide": SLIPPAGE_BPS,
            "execution": "daily signals execute next daily open; weekly signals execute first daily open after weekly close",
            "variants": {
                "dailySt": "Daily SuperTrend baseline",
                "weeklySt": "Weekly SuperTrend baseline",
                "weeklyDailySt": "Daily SuperTrend entries filtered/exited by weekly SuperTrend",
                "weeklyDailyStBbSqueeze20": "Daily SuperTrend entries filtered by weekly SuperTrend and BB bandwidth rank <= 20%",
                "dailyStBbSqueeze20": "Daily SuperTrend entries only when BB bandwidth rank <= 20%",
                "dailyStBbSqueeze30": "Daily SuperTrend entries only when BB bandwidth rank <= 30%",
                "dailyStNoChaseAtr1": "Daily SuperTrend entries only when next open is within 1 ATR above the confirmed ST line",
            },
        },
        "summary": _summarize(rows),
    }
    if not args.param_grid or args.include_rows:
        payload["rows"] = rows
    else:
        payload["rowsOmitted"] = "Use --include-rows to include full per-symbol trade rows with --param-grid."

    if args.annual:
        payload["annualSummary"] = _build_annual_summary(
            metas,
            args.start,
            today_end,
            st_length=args.st_length,
            st_multiplier=args.st_multiplier,
        )

    if args.param_grid:
        payload["parameterGrid"] = _run_parameter_grid(
            metas,
            args.start,
            today_end,
            args.st_lengths,
            args.st_multipliers,
        )

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
        if args.annual:
            print(json.dumps({"annualSummary": payload["annualSummary"]}, ensure_ascii=False, indent=2))
        if args.param_grid:
            print(json.dumps({"parameterGrid": payload["parameterGrid"]}, ensure_ascii=False, indent=2))
        _print_table(rows, args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
