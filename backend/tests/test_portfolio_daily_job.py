from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

import portfolio_daily_job


class FakeService:
    def __init__(self, root: Path):
        self.data_dir = root / "data"
        self.db_path = root / "paper.sqlite"
        self.calls: list[str] = []

    def refresh(self, strategy_id: str, now: datetime):
        self.calls.append(strategy_id)
        if strategy_id == "theme_alpha":
            raise RuntimeError("isolated failure")
        return {
            "state": "EMPTY" if strategy_id == "btc_supertrend_satellite" else "READY",
            "diagnostics": [],
        }


def test_daily_job_updates_first_isolates_failures_and_writes_status(
    tmp_path: Path, monkeypatch,
):
    service = FakeService(tmp_path)
    events: list[str] = []

    def update(symbols):
        assert symbols
        events.append("update")
        return {"ok": True}

    monkeypatch.setattr(
        portfolio_daily_job, "assess_market_readiness",
        lambda *_args: {"us": {"ready": False, "staleCount": 1, "symbols": []}},
    )
    status_path = tmp_path / "status.json"
    result = portfolio_daily_job.run_daily_job(
        service=service, data_updater=update, status_path=status_path,
        now=datetime(2026, 8, 19, 7, 15),
    )
    assert events == ["update"]
    assert service.calls == list(portfolio_daily_job.PRIMARY_STRATEGIES)
    assert result["strategies"]["theme_alpha"]["ok"] is False
    assert result["strategies"]["btc_supertrend_satellite"]["notActivated"] is True
    assert result["strategies"]["risk_parity_core_next_open"]["ok"] is True
    assert json.loads(status_path.read_text())["marketReadiness"]["us"]["ready"] is False
