from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
from typing import Any, Sequence

from portfolio_strategies.event_ledger import (
    EventPortfolioLedger,
    deterministic_key,
)
from portfolio_strategies.ledger import PortfolioLedger, _utc_now, connect
from portfolio_strategies.registry import get_strategy


DEFAULT_STRATEGIES = (
    "risk_parity_core_next_open",
    "core90_ma200_bull10",
)


def record_false_stale_core_corrections(
    db_path: Path | str,
    *,
    market_data_date: date,
    incorrect_expected_date: date,
    strategy_ids: Sequence[str] = DEFAULT_STRATEGIES,
) -> list[dict[str, Any]]:
    """Append idempotent corrections without modifying the original events."""
    ledger = PortfolioLedger(db_path)
    events = EventPortfolioLedger(ledger)
    results: list[dict[str, Any]] = []

    for strategy_id in strategy_ids:
        config = get_strategy(strategy_id)
        account = ledger.get_account(config)
        if account is None:
            results.append({"strategyId": strategy_id, "status": "ACCOUNT_NOT_FOUND"})
            continue

        conn = connect(db_path)
        try:
            originals = conn.execute(
                """
                SELECT * FROM data_quality_events_v2
                WHERE account_id = ? AND code = 'STALE_CORE_DATA'
                  AND market_data_date = ?
                ORDER BY id
                """,
                (account["id"], market_data_date.isoformat()),
            ).fetchall()
        finally:
            conn.close()

        matched = []
        for original in originals:
            details = json.loads(original["details_json"] or "{}")
            if details.get("expectedDate") == incorrect_expected_date.isoformat():
                matched.append(original)
        if not matched:
            results.append({"strategyId": strategy_id, "status": "EVENT_NOT_FOUND"})
            continue

        with ledger.transaction() as conn:
            for original in matched:
                correction = events.record_data_quality(
                    account_id=account["id"],
                    strategy_id=config.strategy_id,
                    strategy_version=config.version,
                    event_key=deterministic_key(
                        config.strategy_id,
                        config.version,
                        "CORRECTION_FALSE_STALE_CORE_DATA",
                        original["id"],
                    ),
                    observed_at=_utc_now(),
                    market_data_date=market_data_date,
                    code="CORRECTION_FALSE_STALE_CORE_DATA",
                    message=(
                        "Correction: the referenced STALE_CORE_DATA event was a "
                        "pre-close false positive; no strategy signal or valuation "
                        "was missing."
                    ),
                    details={
                        "correctsEventId": int(original["id"]),
                        "correctsEventKey": original["event_key"],
                        "incorrectExpectedDate": incorrect_expected_date.isoformat(),
                        "correctExpectedDate": market_data_date.isoformat(),
                        "mutationPolicy": "append_only_no_delete",
                    },
                    conn=conn,
                )
                results.append({
                    "strategyId": strategy_id,
                    "status": "CORRECTION_RECORDED",
                    "originalEventId": int(original["id"]),
                    "correctionEventId": int(correction["id"]),
                })
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Append audited corrections to portfolio data-quality events",
    )
    parser.add_argument(
        "command",
        choices=("correct-false-stale-core",),
    )
    parser.add_argument("--db", default="backtest_results/portfolio_paper.sqlite")
    parser.add_argument("--market-data-date", required=True)
    parser.add_argument("--incorrect-expected-date", required=True)
    parser.add_argument("--strategy", action="append", dest="strategies")
    args = parser.parse_args()

    result = record_false_stale_core_corrections(
        args.db,
        market_data_date=date.fromisoformat(args.market_data_date),
        incorrect_expected_date=date.fromisoformat(args.incorrect_expected_date),
        strategy_ids=tuple(args.strategies or DEFAULT_STRATEGIES),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
