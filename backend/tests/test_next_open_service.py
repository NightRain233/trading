from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from portfolio_strategies.ledger import connect
from portfolio_strategies.next_open_data import _completed_through
from portfolio_strategies.service import PortfolioStrategyService


def test_service_seeds_frozen_july_pit_snapshot_without_xquant_runtime(tmp_path: Path):
    service = PortfolioStrategyService(
        data_dir=Path(__file__).parents[1] / "data",
        db_path=tmp_path / "paper.sqlite",
        decision_provider=lambda _symbols: {"items": []},
        clock=lambda: datetime(2026, 7, 1, 22, 0),
    )
    service.refresh(
        "risk_parity_core_next_open", now=datetime(2026, 7, 1, 22, 0),
    )
    snapshot = service.refresh(
        "core90_ma200_bull10", now=datetime(2026, 7, 1, 22, 0),
    )
    assert snapshot["state"] == "PENDING_EXECUTION"
    assert snapshot["operations"]["pendingOrderCount"] == 3
    assert snapshot["operations"]["dueOrderCount"] == 0
    assert snapshot["operations"]["grossExposure"] == 0.0
    assert snapshot["operations"]["benchmark"]["benchmarkNav"] == 100_000.0
    assert len(service.target_weights("core90_ma200_bull10")["desired"]) == 3
    assert service.rebalance_diff("core90_ma200_bull10")["rows"]
    assert service.ledger_events("core90_ma200_bull10")["events"]
    assert service.nav_series("core90_ma200_bull10")["points"]

    conn = connect(service.db_path)
    try:
        universe = conn.execute("SELECT * FROM universe_snapshots").fetchone()
        assert universe["snapshot_date"] == "2026-06-30"
        assert universe["effective_date"] == "2026-07-01"
        selected = conn.execute(
            "SELECT COUNT(*) FROM universe_memberships WHERE selected = 1"
        ).fetchone()[0]
        assert selected == 49
    finally:
        conn.close()


def test_completed_bar_cutoffs_are_market_specific():
    china_evening = datetime(2026, 7, 1, 22, 0)
    assert _completed_through("510300.SS", china_evening) == date(2026, 7, 1)
    assert _completed_through("AAPL", china_evening) == date(2026, 6, 30)
    assert _completed_through("BTC-USD", china_evening) == date(2026, 6, 30)
    assert _completed_through("AAPL", datetime(2026, 7, 2, 6, 30)) == date(2026, 7, 1)
