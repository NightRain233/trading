from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
import json
import os
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

from portfolio_strategies.frozen_xquant import normalize_daily
from portfolio_strategies.next_open_data import _completed_through, load_next_open_frames
from portfolio_strategies.operation_lock import portfolio_operation_lock
from portfolio_strategies.registry import get_strategy
from portfolio_strategies.service import PortfolioStrategyService


SHANGHAI = ZoneInfo("Asia/Shanghai")
PRIMARY_STRATEGIES = (
    "risk_parity_core_next_open",
    "core90_ma200_bull10",
    "theme_alpha",
    "btc_supertrend_satellite",
)


def _expected_session(symbol: str, cutoff: date) -> date:
    if symbol.endswith("-USD"):
        return cutoff
    calendar_name = (
        "XSHG" if symbol.endswith((".SS", ".SZ"))
        else "XHKG" if symbol.endswith(".HK")
        else "XNYS"
    )
    sessions = xcals.get_calendar(calendar_name).sessions_in_range(
        pd.Timestamp(cutoff) - pd.Timedelta(days=10), pd.Timestamp(cutoff),
    )
    return (
        pd.Timestamp(sessions[-1]).tz_localize(None).date()
        if not sessions.empty else cutoff
    )


def assess_market_readiness(
    data_dir: Path | str,
    symbols: Sequence[str],
    now: datetime,
) -> dict[str, Any]:
    frames, errors = load_next_open_frames(data_dir, symbols, as_of=now)
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for symbol in symbols:
        market = get_strategy("core90_ma200_bull10").asset(symbol).market
        frame = frames.get(symbol)
        actual = normalize_daily(frame).index[-1].date() if frame is not None else None
        expected = _expected_session(symbol, _completed_through(symbol, now))
        rows[str(market)].append({
            "symbol": symbol,
            "expectedCompletedDate": expected.isoformat(),
            "latestDataDate": actual.isoformat() if actual else None,
            "ready": bool(actual is not None and actual >= expected),
            "error": errors.get(symbol),
        })
    return {
        market: {
            "ready": all(row["ready"] for row in market_rows),
            "staleCount": sum(not row["ready"] for row in market_rows),
            "symbols": market_rows,
        }
        for market, market_rows in sorted(rows.items())
    }


def run_daily_job(
    *,
    service: PortfolioStrategyService,
    data_updater: Callable[[list[str]], Any],
    status_path: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    started = now or datetime.now(SHANGHAI)
    symbols = sorted({
        symbol
        for strategy_id in PRIMARY_STRATEGIES
        for symbol in get_strategy(strategy_id).symbols
    })
    status: dict[str, Any] = {
        "startedAt": started.isoformat(),
        "completedAt": None,
        "dataUpdate": {"ok": False},
        "marketReadiness": {},
        "strategies": {},
    }
    try:
        try:
            update_result = data_updater(symbols)
            status["dataUpdate"] = {
                "ok": True,
                "symbolCount": len(symbols),
                "resultType": type(update_result).__name__,
            }
        except Exception as exc:  # each strategy still gets a chance on cached data
            status["dataUpdate"] = {
                "ok": False, "symbolCount": len(symbols),
                "error": f"{type(exc).__name__}: {exc}",
            }
        try:
            status["marketReadiness"] = assess_market_readiness(
                service.data_dir, get_strategy("core90_ma200_bull10").symbols, started,
            )
        except Exception as exc:
            status["marketReadinessError"] = f"{type(exc).__name__}: {exc}"

        for strategy_id in PRIMARY_STRATEGIES:
            try:
                snapshot = service.refresh(strategy_id, now=started)
                status["strategies"][strategy_id] = {
                    "ok": True,
                    "state": snapshot.get("state"),
                    "notActivated": snapshot.get("state") == "EMPTY",
                    "diagnostics": snapshot.get("diagnostics", []),
                }
            except Exception as exc:
                status["strategies"][strategy_id] = {
                    "ok": False, "state": "FAILED",
                    "error": f"{type(exc).__name__}: {exc}",
                }
    finally:
        status["completedAt"] = datetime.now(SHANGHAI).isoformat()
        status_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = status_path.with_suffix(status_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        os.replace(temporary, status_path)
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh the four primary paper portfolios")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--db", default="backtest_results/portfolio_paper.sqlite")
    parser.add_argument(
        "--status", default="backtest_results/portfolio_daily_job_status.json",
    )
    args = parser.parse_args()

    # Importing here keeps the orchestration module testable without loading the API app.
    from analysis import batch_fetch_and_update
    from main import supertrend_scan

    service = PortfolioStrategyService(
        data_dir=args.data_dir,
        db_path=args.db,
        decision_provider=lambda symbols: supertrend_scan(
            force=False, include_candles=False,
            requested_symbols=",".join(symbols),
        ),
    )
    with portfolio_operation_lock(Path(args.db), "daily-job"):
        result = run_daily_job(
            service=service,
            data_updater=batch_fetch_and_update,
            status_path=Path(args.status),
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
