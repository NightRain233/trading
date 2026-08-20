from __future__ import annotations

from datetime import date
from pathlib import Path

from portfolio_data_quality_admin import record_false_stale_core_corrections
from portfolio_strategies.event_ledger import EventPortfolioLedger
from portfolio_strategies.ledger import PortfolioLedger, connect
from portfolio_strategies.next_open_engine import NextOpenPaperEngine
from portfolio_strategies.registry import get_strategy


def test_false_stale_correction_is_append_only_and_idempotent(tmp_path: Path):
    db_path = tmp_path / "paper.sqlite"
    ledger = PortfolioLedger(db_path)
    config = get_strategy("risk_parity_core_next_open")
    NextOpenPaperEngine(ledger).activate(
        config,
        activation_date=date(2026, 8, 20),
    )
    account = ledger.get_account(config)
    assert account is not None
    EventPortfolioLedger(ledger).record_data_quality(
        account_id=account["id"],
        strategy_id=config.strategy_id,
        strategy_version=config.version,
        event_key="original-false-stale",
        observed_at="2026-08-20T03:42:30+00:00",
        market_data_date=date(2026, 8, 19),
        code="STALE_CORE_DATA",
        message="Core common-session data is stale; no new signal was generated",
        details={"expectedDate": "2026-08-20"},
    )

    first = record_false_stale_core_corrections(
        db_path,
        market_data_date=date(2026, 8, 19),
        incorrect_expected_date=date(2026, 8, 20),
        strategy_ids=(config.strategy_id,),
    )
    second = record_false_stale_core_corrections(
        db_path,
        market_data_date=date(2026, 8, 19),
        incorrect_expected_date=date(2026, 8, 20),
        strategy_ids=(config.strategy_id,),
    )

    assert first[0]["status"] == "CORRECTION_RECORDED"
    assert second[0]["correctionEventId"] == first[0]["correctionEventId"]
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT code, details_json FROM data_quality_events_v2 ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    assert [row["code"] for row in rows] == [
        "STALE_CORE_DATA",
        "CORRECTION_FALSE_STALE_CORE_DATA",
    ]
    assert '"mutationPolicy":"append_only_no_delete"' in rows[1]["details_json"]
