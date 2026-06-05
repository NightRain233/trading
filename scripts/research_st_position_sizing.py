#!/usr/bin/env python3
"""Research SuperTrend-driven exposure control for RS rotation portfolios."""

from __future__ import annotations

import argparse
import json
import importlib.util
import sys
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import pandas_ta as ta


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

BACKTEST_PATH = BACKEND_DIR / "backtest.py"
DATA_DIR = BACKEND_DIR / "data"
UNIVERSE_FILE = BACKEND_DIR / "universes" / "a_share_etf_core.json"
_BACKTEST_SPEC = importlib.util.spec_from_file_location("backtest", BACKTEST_PATH)
backtest = importlib.util.module_from_spec(_BACKTEST_SPEC)
_BACKTEST_SPEC.loader.exec_module(backtest)


def _latest_st_dir(st_dir: pd.Series, as_of) -> Optional[int]:
    if st_dir is None or st_dir.empty:
        return None
    window = st_dir.sort_index()[st_dir.sort_index().index <= pd.Timestamp(as_of)]
    if window.empty or pd.isna(window.iloc[-1]):
        return None
    return int(float(window.iloc[-1]))


BALANCED_MARKET_EXPOSURE = {
    (1, 1): 1.0,
    (1, -1): 0.5,
    (-1, 1): 0.5,
    (-1, -1): 0.25,
}

MILD_MARKET_EXPOSURE = {
    (1, 1): 1.0,
    (1, -1): 0.75,
    (-1, 1): 0.75,
    (-1, -1): 0.5,
}

LIGHT_MARKET_EXPOSURE = {
    (1, 1): 1.0,
    (1, -1): 0.85,
    (-1, 1): 0.85,
    (-1, -1): 0.65,
}

ULTRA_LIGHT_MARKET_EXPOSURE = {
    (1, 1): 1.0,
    (1, -1): 0.90,
    (-1, 1): 0.90,
    (-1, -1): 0.75,
}


def _market_exposure(
    weekly_dir: Optional[int],
    daily_dir: Optional[int],
    exposure_table: Optional[Dict[tuple, float]] = None,
) -> float:
    table = exposure_table or BALANCED_MARKET_EXPOSURE
    if weekly_dir == 1 and daily_dir == 1:
        return table[(1, 1)]
    if weekly_dir == 1 and daily_dir == -1:
        return table[(1, -1)]
    if weekly_dir == -1 and daily_dir == 1:
        return table[(-1, 1)]
    if weekly_dir == -1 and daily_dir == -1:
        return table[(-1, -1)]
    return table.get((1, -1), 0.5)


def _symbol_exposure(daily_dir: Optional[int]) -> float:
    return 1.0 if daily_dir == 1 else 0.0


def _date_str(value) -> str:
    return pd.Timestamp(value).date().isoformat()


def _close_on_or_before(df: Optional[pd.DataFrame], as_of):
    if df is None or df.empty or "Close" not in df.columns:
        return None
    window = df[df.index <= pd.Timestamp(as_of)]
    if window.empty:
        return None
    value = window.iloc[-1].get("Close")
    return None if pd.isna(value) else float(value)


def _supertrend_dir(df: pd.DataFrame, timeframe: str = "daily") -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype="float64")
    source = df.sort_index()
    if timeframe == "weekly":
        source = (
            source.resample("W")
            .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
            .dropna(subset=["Open", "High", "Low", "Close"])
        )
    st = ta.supertrend(source["High"], source["Low"], source["Close"], length=7, multiplier=3.0)
    if st is None or st.empty:
        return pd.Series(dtype="float64")
    dir_col = next((column for column in st.columns if str(column).startswith("SUPERTd_")), None)
    return st[dir_col].sort_index() if dir_col else pd.Series(dtype="float64")


def simulate_rs_rotation_with_st_exposure(
    daily_frames_by_symbol: Dict[str, pd.DataFrame],
    market_df: pd.DataFrame,
    top_n: int = 5,
    rebalance_days: int = 20,
    lookback_bars: int = 60,
    start: Optional[str] = None,
    end: Optional[str] = None,
    fee_bps: float = 5.0,
    slippage_bps: float = 5.0,
    min_history_bars: int = 250,
    min_avg_volume: float = 1e8,
    volume_lookback: int = 60,
    market_filter_df: Optional[pd.DataFrame] = None,
    market_filter_mode: str = "none",
    exposure_mode: str = "market",
    exposure_table: Optional[Dict[tuple, float]] = None,
) -> Dict[str, object]:
    if exposure_mode not in {"market", "market_symbol"}:
        raise ValueError(f"Unsupported exposure_mode: {exposure_mode}")

    all_dates = set()
    for df in daily_frames_by_symbol.values():
        if df is not None and not df.empty:
            all_dates.update(df.index)
    if not all_dates:
        return {"mode": exposure_mode, "totalReturnPct": 0.0, "maxDrawdownPct": 0.0, "equityCurve": []}

    dates = sorted(all_dates)
    if start:
        dates = [date for date in dates if date >= pd.Timestamp(start)]
    if end:
        dates = [date for date in dates if date <= pd.Timestamp(end)]
    if not dates:
        return {"mode": exposure_mode, "totalReturnPct": 0.0, "maxDrawdownPct": 0.0, "equityCurve": []}

    market_daily_dir = _supertrend_dir(market_df, "daily")
    market_weekly_dir = _supertrend_dir(market_df, "weekly")
    symbol_dirs = {
        symbol: _supertrend_dir(df, "daily")
        for symbol, df in daily_frames_by_symbol.items()
    }

    fee_factor = fee_bps / 10_000
    slip_factor = slippage_bps / 10_000
    portfolio_cash = 1.0
    holdings: Dict[str, Dict[str, object]] = {}
    peak = 1.0
    max_drawdown = 0.0
    equity_curve: List[Dict[str, object]] = []
    last_rebalance_idx = -rebalance_days
    monthly_cache: Dict[int, pd.DataFrame] = {}

    def _portfolio_value(as_of) -> float:
        total = portfolio_cash
        for sym, pos in holdings.items():
            price = _close_on_or_before(daily_frames_by_symbol.get(sym), as_of) or float(pos["cost_price"])
            total += float(pos["shares"]) * price
        return total

    for idx, date in enumerate(dates):
        target_exposure = _market_exposure(
            _latest_st_dir(market_weekly_dir, date),
            _latest_st_dir(market_daily_dir, date),
            exposure_table=exposure_table,
        )

        if idx - last_rebalance_idx >= rebalance_days:
            last_rebalance_idx = idx
            ranked_symbols = backtest._rs_rank_symbols(
                daily_frames_by_symbol,
                date,
                top_n,
                lookback_bars,
                min_history_bars,
                min_avg_volume,
                volume_lookback,
                0.0,
                None,
                market_filter_df,
                market_filter_mode,
                None,
                monthly_cache,
                None,
            )

            target_symbols = []
            symbol_multipliers: Dict[str, float] = {}
            for symbol in ranked_symbols:
                if symbol == backtest._RS_CASH_SYMBOL:
                    continue
                multiplier = 1.0
                if exposure_mode == "market_symbol":
                    multiplier = _symbol_exposure(_latest_st_dir(symbol_dirs.get(symbol), date))
                if multiplier > 0:
                    target_symbols.append(symbol)
                    symbol_multipliers[symbol] = multiplier

            for sym in list(set(holdings.keys()) - set(target_symbols)):
                pos = holdings.pop(sym)
                price = _close_on_or_before(daily_frames_by_symbol.get(sym), date) or float(pos["cost_price"])
                portfolio_cash += float(pos["shares"]) * price * (1 - slip_factor) * (1 - fee_factor)

            current_equity = _portfolio_value(date)
            desired_values = {
                symbol: current_equity / top_n * target_exposure * symbol_multipliers.get(symbol, 1.0)
                for symbol in target_symbols
            }

            for sym in list(holdings.keys()):
                price = _close_on_or_before(daily_frames_by_symbol.get(sym), date) or float(holdings[sym]["cost_price"])
                current_value = float(holdings[sym]["shares"]) * price
                desired = desired_values.get(sym, 0.0)
                if current_value > desired:
                    sell_value = current_value - desired
                    shares_to_sell = sell_value / price if price > 0 else 0.0
                    holdings[sym]["shares"] = float(holdings[sym]["shares"]) - shares_to_sell
                    portfolio_cash += shares_to_sell * price * (1 - slip_factor) * (1 - fee_factor)
                    if float(holdings[sym]["shares"]) <= 1e-12:
                        holdings.pop(sym)

            for sym, desired in desired_values.items():
                price = _close_on_or_before(daily_frames_by_symbol.get(sym), date)
                if not price or price <= 0:
                    continue
                current_value = float(holdings.get(sym, {}).get("shares", 0.0)) * price
                buy_value = max(0.0, desired - current_value)
                if buy_value <= 0:
                    continue
                net_cost = min(buy_value * (1 + fee_factor), portfolio_cash)
                if net_cost <= 0:
                    continue
                shares = (net_cost / (1 + fee_factor)) / (price * (1 + slip_factor))
                portfolio_cash -= net_cost
                if sym in holdings:
                    holdings[sym]["shares"] = float(holdings[sym]["shares"]) + shares
                else:
                    holdings[sym] = {"shares": shares, "cost_price": price * (1 + slip_factor), "entry_date": date}

        equity = _portfolio_value(date)
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak * 100 if peak else 0.0
        max_drawdown = max(max_drawdown, drawdown)
        invested_value = equity - portfolio_cash
        actual_exposure = invested_value / equity if equity else 0.0
        equity_curve.append(
            {
                "date": _date_str(date),
                "equity": equity,
                "drawdownPct": drawdown,
                "openPositions": len(holdings),
                "holdings": sorted(holdings.keys()),
                "cash": portfolio_cash,
                "targetExposure": target_exposure,
                "actualExposure": actual_exposure,
            }
        )

    total_return_pct = (equity_curve[-1]["equity"] - 1) * 100 if equity_curve else 0.0
    return {
        "mode": exposure_mode,
        "topN": top_n,
        "rebalanceDays": rebalance_days,
        "lookbackBars": lookback_bars,
        "startDate": _date_str(dates[0]),
        "endDate": _date_str(dates[-1]),
        "totalReturnPct": total_return_pct,
        "maxDrawdownPct": max_drawdown,
        "equityCurve": equity_curve,
        "averageExposure": sum(point["actualExposure"] for point in equity_curve) / len(equity_curve),
        "lowExposureDayCount": sum(1 for point in equity_curve if point["actualExposure"] < 0.5),
        "marketFilterMode": market_filter_mode,
    }


def _load_universe_symbols(path: Path) -> List[str]:
    payload = json.loads(path.read_text())
    raw_symbols = payload.get("symbols", payload) if isinstance(payload, dict) else payload
    symbols = []
    for item in raw_symbols:
        symbol = item.get("symbol") if isinstance(item, dict) else item
        if not isinstance(symbol, str):
            continue
        normalized = symbol.strip().upper()
        if normalized and normalized not in symbols:
            symbols.append(normalized)
    return symbols


def _load_frame(symbol: str, data_dir: Path = DATA_DIR) -> Optional[pd.DataFrame]:
    path = data_dir / f"{symbol.upper()}.parquet"
    if not path.exists():
        return None
    frame = pd.read_parquet(path).sort_index()
    return frame if not frame.empty else None


def _load_weekly_frame(symbol: str, daily: Optional[pd.DataFrame], data_dir: Path = DATA_DIR) -> Optional[pd.DataFrame]:
    path = data_dir / f"{symbol.upper()}_weekly.parquet"
    if path.exists():
        frame = pd.read_parquet(path).sort_index()
        if not frame.empty:
            return frame
    if daily is None or daily.empty:
        return None
    return (
        daily.resample("W")
        .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
        .dropna(subset=["Open", "High", "Low", "Close"])
    )


def _portfolio_stats(portfolio: Dict[str, object]) -> Dict[str, object]:
    total_return = float(portfolio.get("totalReturnPct") or 0.0)
    max_drawdown = float(portfolio.get("maxDrawdownPct") or 0.0)
    curve = portfolio.get("equityCurve") or []
    avg_exposure = portfolio.get("averageExposure")
    if avg_exposure is None and curve:
        avg_exposure = sum(float(point.get("actualExposure", 1.0 if point.get("openPositions") else 0.0)) for point in curve) / len(curve)
    return {
        "totalReturnPct": total_return,
        "maxDrawdownPct": max_drawdown,
        "returnDrawdownRatio": total_return / max_drawdown if max_drawdown else None,
        "averageExposure": float(avg_exposure or 0.0),
        "lowExposureDayCount": int(portfolio.get("lowExposureDayCount") or 0),
        "startDate": portfolio.get("startDate"),
        "endDate": portfolio.get("endDate"),
    }


def _annual_stats(portfolio: Dict[str, object]) -> List[Dict[str, object]]:
    curve = portfolio.get("equityCurve") or []
    if not curve:
        return []
    by_year: Dict[str, List[Dict[str, object]]] = {}
    for point in curve:
        year = str(pd.Timestamp(point["date"]).year)
        by_year.setdefault(year, []).append(point)
    rows = []
    for year, points in sorted(by_year.items()):
        start_equity = float(points[0]["equity"])
        end_equity = float(points[-1]["equity"])
        exposures = [
            float(point.get("actualExposure", 1.0 if point.get("openPositions") else 0.0))
            for point in points
        ]
        rows.append(
            {
                "year": year,
                "returnPct": (end_equity / start_equity - 1) * 100 if start_equity else 0.0,
                "maxDrawdownPct": max(float(point.get("drawdownPct") or 0.0) for point in points),
                "averageExposure": sum(exposures) / len(exposures) if exposures else 0.0,
            }
        )
    return rows


def build_st_position_sizing_research(
    start: str = "2015-01-01",
    end: str = "2026-06-05",
    universe_file: Path = UNIVERSE_FILE,
    data_dir: Path = DATA_DIR,
) -> Dict[str, object]:
    symbols = _load_universe_symbols(universe_file)
    frames = {
        symbol: frame
        for symbol in symbols
        if (frame := _load_frame(symbol, data_dir)) is not None
    }
    market_symbol = "510300.SS"
    market_df = _load_frame(market_symbol, data_dir)
    market_weekly_df = _load_weekly_frame(market_symbol, market_df, data_dir)
    if market_df is None:
        raise RuntimeError(f"Missing market frame: {market_symbol}")

    common = {
        "top_n": 5,
        "rebalance_days": 20,
        "lookback_bars": 60,
        "start": start,
        "end": end,
        "fee_bps": 5.0,
        "slippage_bps": 5.0,
        "min_history_bars": 0,
        "min_avg_volume": 1e8,
    }
    variants = {
        "rs_no_filter_reference": backtest.simulate_rs_rotation_portfolio(
            frames,
            **common,
            market_filter_mode="none",
        ),
        "rs_monthly_macd_baseline": backtest.simulate_rs_rotation_portfolio(
            frames,
            **common,
            market_filter_df=market_df,
            market_filter_mode="monthly_macd",
        ),
        "rs_market_st_exposure": simulate_rs_rotation_with_st_exposure(
            frames,
            market_df=market_df,
            **common,
            exposure_mode="market",
        ),
        "rs_market_symbol_st_exposure": simulate_rs_rotation_with_st_exposure(
            frames,
            market_df=market_df,
            **common,
            exposure_mode="market_symbol",
        ),
        "rs_monthly_macd_market_st_exposure": simulate_rs_rotation_with_st_exposure(
            frames,
            market_df=market_df,
            **common,
            market_filter_df=market_df,
            market_filter_mode="monthly_macd",
            exposure_mode="market",
        ),
        "rs_monthly_macd_market_st_mild_exposure": simulate_rs_rotation_with_st_exposure(
            frames,
            market_df=market_df,
            **common,
            market_filter_df=market_df,
            market_filter_mode="monthly_macd",
            exposure_mode="market",
            exposure_table=MILD_MARKET_EXPOSURE,
        ),
        "rs_monthly_macd_market_st_light_exposure": simulate_rs_rotation_with_st_exposure(
            frames,
            market_df=market_df,
            **common,
            market_filter_df=market_df,
            market_filter_mode="monthly_macd",
            exposure_mode="market",
            exposure_table=LIGHT_MARKET_EXPOSURE,
        ),
        "rs_monthly_macd_market_st_ultra_light_exposure": simulate_rs_rotation_with_st_exposure(
            frames,
            market_df=market_df,
            **common,
            market_filter_df=market_df,
            market_filter_mode="monthly_macd",
            exposure_mode="market",
            exposure_table=ULTRA_LIGHT_MARKET_EXPOSURE,
        ),
        "rs_monthly_macd_market_symbol_st_exposure": simulate_rs_rotation_with_st_exposure(
            frames,
            market_df=market_df,
            **common,
            market_filter_df=market_df,
            market_filter_mode="monthly_macd",
            exposure_mode="market_symbol",
        ),
    }

    baseline_stats = _portfolio_stats(variants["rs_monthly_macd_baseline"])
    summary = {}
    for key, portfolio in variants.items():
        stats = _portfolio_stats(portfolio)
        summary[key] = {
            **stats,
            "returnRetentionVsBaseline": (
                stats["totalReturnPct"] / baseline_stats["totalReturnPct"]
                if baseline_stats["totalReturnPct"]
                else None
            ),
            "drawdownReductionVsBaseline": (
                (baseline_stats["maxDrawdownPct"] - stats["maxDrawdownPct"]) / baseline_stats["maxDrawdownPct"]
                if baseline_stats["maxDrawdownPct"]
                else None
            ),
        }

    return {
        "params": {
            "start": start,
            "end": end,
            "universeFile": str(universe_file),
            "dataDir": str(data_dir),
            "symbolCount": len(frames),
            "marketSymbol": market_symbol,
            "topN": 5,
            "rebalanceDays": 20,
            "lookbackBars": 60,
            "feeBps": 5.0,
            "slippageBps": 5.0,
            "minAvgVolume": 1e8,
            "stLength": 7,
            "stMultiplier": 3.0,
            "marketExposureTable": {
                "weeklyBullDailyBull": 1.0,
                "weeklyBullDailyBear": 0.5,
                "weeklyBearDailyBull": 0.5,
                "weeklyBearDailyBear": 0.25,
            },
            "mildMarketExposureTable": {
                "weeklyBullDailyBull": 1.0,
                "weeklyBullDailyBear": 0.75,
                "weeklyBearDailyBull": 0.75,
                "weeklyBearDailyBear": 0.5,
            },
            "lightMarketExposureTable": {
                "weeklyBullDailyBull": 1.0,
                "weeklyBullDailyBear": 0.85,
                "weeklyBearDailyBull": 0.85,
                "weeklyBearDailyBear": 0.65,
            },
            "ultraLightMarketExposureTable": {
                "weeklyBullDailyBull": 1.0,
                "weeklyBullDailyBear": 0.90,
                "weeklyBearDailyBull": 0.90,
                "weeklyBearDailyBear": 0.75,
            },
        },
        "summary": summary,
        "annual": {key: _annual_stats(portfolio) for key, portfolio in variants.items()},
        "portfolios": variants,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Research ST position sizing on A-share ETF RS rotation.")
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default="2026-06-05")
    parser.add_argument("--universe-file", default=str(UNIVERSE_FILE))
    parser.add_argument("--data-dir", default=str(DATA_DIR))
    parser.add_argument(
        "--output",
        default=str(BACKEND_DIR / "backtest_results" / "supertrend_position_sizing_2026-06-05.json"),
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_st_position_sizing_research(
        start=args.start,
        end=args.end,
        universe_file=Path(args.universe_file),
        data_dir=Path(args.data_dir),
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"output": str(output_path), "params": payload["params"], "summary": payload["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
