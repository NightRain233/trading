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
    assert service.calls == list(portfolio_daily_job.TRACKED_STRATEGIES)
    assert result["strategies"]["theme_alpha"]["ok"] is False
    assert result["strategies"]["btc_supertrend_satellite"]["notActivated"] is True
    assert result["strategies"]["risk_parity_core_next_open"]["ok"] is True
    assert json.loads(status_path.read_text())["marketReadiness"]["us"]["ready"] is False


def test_market_readiness_reuses_structured_freshness_statuses(tmp_path: Path, monkeypatch):
    frames = {"510300.SS": object(), "AAPL": object()}
    monkeypatch.setattr(
        portfolio_daily_job,
        "load_next_open_frames",
        lambda *_args, **_kwargs: (frames, {}),
    )

    def fake_freshness(symbol, frame, *, known_at, source_error=None):
        assert frame is frames[symbol]
        assert known_at == datetime(2026, 10, 2, 12, 0)
        return {
            "symbol": symbol,
            "venue": "XSHG" if symbol.endswith(".SS") else "XNYS",
            "expectedLastCompletedSession": "2026-09-30",
            "actualLastCompletedSession": "2026-09-30",
            "missingExpectedSessions": [],
            "closedByCalendarSessions": ["2026-10-01"],
            "freshnessStatus": "OK" if symbol.endswith(".SS") else "SOURCE_STALE",
        }

    monkeypatch.setattr(portfolio_daily_job, "assess_freshness", fake_freshness, raising=False)

    result = portfolio_daily_job.assess_market_readiness(
        tmp_path, ["510300.SS", "AAPL"], datetime(2026, 10, 2, 12, 0),
    )

    assert result["a_share"]["symbols"][0]["freshnessStatus"] == "OK"
    assert result["a_share"]["ready"] is True
    assert result["us"]["symbols"][0]["freshnessStatus"] == "SOURCE_STALE"
    assert result["us"]["ready"] is False
