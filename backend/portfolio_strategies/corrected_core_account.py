"""Isolated, incremental paper ledger for the corrected three-ETF contract."""
from __future__ import annotations

from dataclasses import replace
from contextlib import closing
from datetime import date, datetime
import json
import math
from pathlib import Path

import pandas as pd
import exchange_calendars as xcals

from .corrected_core import (CORE_SYMBOLS, advance_core_day, initial_state,
                             load_actions, prepare_core_market)
from .core_raw_data import load_core_raw_frames
from .event_ledger import EventPortfolioLedger, canonical_json, payload_hash
from .ledger import PortfolioLedger, _utc_now, connect
from .models import StrategyConfig
from .market_freshness import assess_freshness


SCHEMA = """
CREATE TABLE IF NOT EXISTS corrected_core_state (
    account_id INTEGER PRIMARY KEY REFERENCES paper_accounts(id),
    state_json TEXT NOT NULL, diagnostics_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS corrected_core_flows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES paper_accounts(id),
    flow_date TEXT NOT NULL, amount REAL NOT NULL CHECK(amount > 0),
    idempotency_key TEXT NOT NULL, created_at TEXT NOT NULL,
    UNIQUE(account_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS corrected_core_days (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES paper_accounts(id),
    valuation_date TEXT NOT NULL, input_hash TEXT NOT NULL,
    nav_json TEXT NOT NULL, state_json TEXT NOT NULL,
    UNIQUE(account_id, valuation_date)
);
CREATE TABLE IF NOT EXISTS corrected_core_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES paper_accounts(id),
    event_date TEXT NOT NULL, event_type TEXT NOT NULL,
    event_key TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
    UNIQUE(account_id, event_key)
);
"""


class CorrectedCoreAccount:
    def __init__(self, ledger: PortfolioLedger, data_dir: Path | str):
        self.ledger = ledger
        self.data_dir = Path(data_dir)
        self.events = EventPortfolioLedger(ledger)
        with closing(connect(ledger.db_path)) as conn:
            conn.executescript(SCHEMA)

    def activate(self, config: StrategyConfig, day: date, initial_cash: float | None) -> None:
        amount = config.initial_nav if initial_cash is None else float(initial_cash)
        if not math.isfinite(amount) or amount < 0:
            raise ValueError("initialCash must be finite and nonnegative")
        if day.isoformat() < config.params["schedule_anchor_signal_date"]:
            raise ValueError("activationDate precedes the corrected schedule anchor")
        with self.ledger.transaction() as conn:
            existing = self.ledger.get_account(config, conn=conn)
            if existing is not None:
                activation = self.events.activation(existing["id"], conn=conn)
                if activation is None or activation["activation_date"] != day.isoformat():
                    raise ValueError("Conflicting activationDate or missing activation audit")
                if initial_cash is not None and float(activation["initial_cash"]) != amount:
                    raise ValueError("Account is already activated with a different initialCash")
                return
            configured = replace(config, initial_nav=amount)
            activation = self.events.activate(configured, activation_date=day,
                metadata={"accountOrigin": "explicit_corrected_paper", "accountingContract": "raw_cash_dividend_v1",
                          "fractionalShares": True, "initialCashTreatment": "cash_until_scheduled_next_open"}, conn=conn)
            conn.execute("INSERT INTO corrected_core_state(account_id,state_json) VALUES (?,?)",
                         (activation["account_id"], canonical_json(initial_state())))

    def _read(self, config: StrategyConfig) -> tuple:
        with closing(connect(self.ledger.db_path)) as conn:
            conn.execute("BEGIN")
            account = self.ledger.get_account(config, conn=conn)
            if account is None:
                return None, None, initial_state(), [], None
            activation = self.events.activation(account["id"], conn=conn)
            row = conn.execute("SELECT * FROM corrected_core_state WHERE account_id=?", (account["id"],)).fetchone()
            if row is None or activation is None:
                raise ValueError("Corrected account is missing its audit state")
            latest = conn.execute("SELECT * FROM corrected_core_days WHERE account_id=? ORDER BY valuation_date DESC LIMIT 1",
                                  (account["id"],)).fetchone()
            return account, activation, json.loads(row["state_json"]), json.loads(row["diagnostics_json"]), latest

    def contribute(self, config: StrategyConfig, *, day: date, amount: float, key: str,
                   now: datetime) -> dict:
        if not math.isfinite(amount) or amount <= 0:
            raise ValueError("amount must be finite and positive")
        if not key.strip() or len(key) > 128:
            raise ValueError("idempotencyKey must contain 1 to 128 characters")
        account, activation, state, _, _ = self._read(config)
        if account is None:
            raise ValueError("Activate the corrected paper account before adding a deposit")
        with closing(connect(self.ledger.db_path)) as conn:
            existing = conn.execute("SELECT * FROM corrected_core_flows WHERE account_id=? AND idempotency_key=?",
                                    (account["id"], key)).fetchone()
        if existing is not None:
            if existing["flow_date"] != day.isoformat() or float(existing["amount"]) != amount:
                raise ValueError("idempotencyKey was already used for a different deposit")
            return self.flow_records(config)
        if day.isoformat() < activation["activation_date"]:
            raise ValueError("contributionDate precedes activationDate")
        if state["last_date"] is not None and day.isoformat() <= state["last_date"]:
            raise ValueError("Cannot add a deposit to a processed date; existing history is immutable")
        # A dated paper instruction may be recorded before prices exist. It
        # stays pending until that date has three completed raw opening bars.
        # This is an explicit cash-flow schedule, not an automated DCA mandate.
        calendar = xcals.get_calendar("XSHG")
        try:
            if not calendar.is_session(pd.Timestamp(day)):
                raise ValueError("contributionDate must be an XSHG trading session")
        except (ValueError, IndexError) as exc:
            raise ValueError(f"Cannot establish contributionDate trading session: {day}") from exc
        action_path = self.data_dir / "core_raw" / "corporate_actions.json"
        actions = load_actions(action_path) if action_path.exists() else load_actions()
        if any(e["type"] == "split" and e["corporate_action_date"] == day.isoformat() for e in actions["events"]):
            raise ValueError("contributionDate is a known core ETF split halt")
        with self.ledger.transaction() as conn:
            conn.execute("INSERT INTO corrected_core_flows(account_id,flow_date,amount,idempotency_key,created_at) VALUES (?,?,?,?,?)",
                         (account["id"], day.isoformat(), amount, key, _utc_now()))
            self._append_event(conn, account["id"], day.isoformat(),
                               {"type": "deposit_instruction", "amount": amount, "idempotencyKey": key})
        return self.flow_records(config)

    def flow_records(self, config: StrategyConfig) -> dict:
        account, activation, state, _, _ = self._read(config)
        records = []
        if account is not None:
            with closing(connect(self.ledger.db_path)) as conn:
                rows = conn.execute("SELECT * FROM corrected_core_flows WHERE account_id=? ORDER BY flow_date,id",
                                    (account["id"],)).fetchall()
            records = [{"id": r["id"], "contributionDate": r["flow_date"], "amount": r["amount"],
                        "idempotencyKey": r["idempotency_key"], "recordedAt": r["created_at"],
                        "status": "posted" if state["last_date"] and r["flow_date"] <= state["last_date"] else "pending"}
                       for r in rows]
        return {"strategyId": config.strategy_id, "initialCash": float(activation["initial_cash"]) if activation else None,
                "initialCashDate": activation["activation_date"] if activation else None, "deposits": records}

    @staticmethod
    def _append_event(conn, account_id: int, day: str, event: dict) -> None:
        conn.execute("""INSERT INTO corrected_core_events(account_id,event_date,event_type,event_key,payload_json,created_at)
                     VALUES (?,?,?,?,?,?) ON CONFLICT(account_id,event_key) DO NOTHING""",
                     (account_id, day, event["type"], payload_hash([day, event]), canonical_json(event), _utc_now()))

    def _blocked(self, config: StrategyConfig, code: str, message: str) -> dict:
        account, _, state, _, _ = self._read(config)
        if account is not None:
            diagnostics = [{"code": code, "message": message}]
            with self.ledger.transaction() as conn:
                conn.execute("UPDATE corrected_core_state SET diagnostics_json=? WHERE account_id=?",
                             (canonical_json(diagnostics), account["id"]))
                self._append_event(conn, account["id"], state["last_date"] or "", {"type": "data_quality", **diagnostics[0]})
        return self.snapshot(config)

    def refresh(self, config: StrategyConfig, now: datetime) -> dict:
        account, activation, state, _, _ = self._read(config)
        if account is None:
            return self.snapshot(config)
        frames, errors = load_core_raw_frames(self.data_dir, as_of=now)
        if errors:
            return self._blocked(config, "RAW_DATA_UNAVAILABLE", canonical_json(errors))
        try:
            document = load_actions(self.data_dir / "core_raw" / "corporate_actions.json"
                                    if (self.data_dir / "core_raw" / "corporate_actions.json").exists() else
                                    Path(__file__).with_name("core_corporate_actions.json"))
            market = prepare_core_market(frames, document["events"],
                anchor=config.params["schedule_anchor_signal_date"], window=config.params["risk_parity_window"],
                interval=config.params["rebalance_sessions"])
            if market.dates[-1].date().isoformat() > document["metadata"]["verified_through"]:
                return self._blocked(config, "CORPORATE_ACTION_COVERAGE_EXPIRED",
                                     "Raw prices extend beyond verified corporate actions; update the official event snapshot first")
            known_at = pd.Timestamp(now)
            known_at = known_at.tz_localize("Asia/Shanghai") if known_at.tzinfo is None else known_at
            for symbol, frame in frames.items():
                freshness = assess_freshness(symbol, frame, known_at=known_at)
                halts = {e["corporate_action_date"] for e in document["events"]
                         if e["symbol"] == symbol and e["type"] == "split"}
                missing = set(freshness["missingExpectedSessions"])-halts
                suspended = freshness["freshnessStatus"] == "SUSPENDED" and freshness["expectedLastCompletedSession"] not in halts
                if freshness["freshnessStatus"] == "CALENDAR_UNKNOWN" or suspended or missing:
                    return self._blocked(config, "RAW_SNAPSHOT_STALE",
                                         canonical_json({**freshness, "missingExpectedSessions": sorted(missing)}))
            with self.ledger.transaction() as conn:
                flow_rows = conn.execute("SELECT flow_date,amount,idempotency_key FROM corrected_core_flows WHERE account_id=? ORDER BY flow_date,idempotency_key",
                                         (account["id"],)).fetchall()
                flows_by_date = {}
                for r in flow_rows:
                    flows_by_date.setdefault(r["flow_date"], []).append({"amount": float(r["amount"]), "key": r["idempotency_key"]})
                deposits = {day: sum(r["amount"] for r in rows) for day, rows in flows_by_date.items()}
                contract = {"id": config.strategy_id, "version": config.version, "params": dict(config.params),
                            "cost_bps": config.costs.base_bps, "symbols": list(config.symbols),
                            "activationDate": activation["activation_date"], "initialCash": float(activation["initial_cash"])}
                def input_hash(day):
                    return payload_hash({"market": market.input_hashes.get(day), "contract": contract,
                                         "flows": flows_by_date.get(day, [])})
                history = conn.execute("SELECT valuation_date,input_hash FROM corrected_core_days WHERE account_id=?",
                                       (account["id"],)).fetchall()
                for row in history:
                    if input_hash(row["valuation_date"]) != row["input_hash"]:
                        raise ValueError(f"Previously processed market inputs changed: {row['valuation_date']}")
                start = max(activation["activation_date"], state["last_date"] or activation["activation_date"])
                for i in range(market.dates.searchsorted(pd.Timestamp(start)), len(market.dates)):
                    day = market.dates[i].date().isoformat()
                    if state["last_date"] and day <= state["last_date"]:
                        continue
                    state, nav, events = advance_core_day(state, market, i,
                        initial_cash=float(activation["initial_cash"]) if day == activation["activation_date"] else 0.,
                        deposit=deposits.get(day, 0.), fee_bps=config.costs.base_bps)
                    conn.execute("INSERT INTO corrected_core_days(account_id,valuation_date,input_hash,nav_json,state_json) VALUES (?,?,?,?,?)",
                                 (account["id"], day, input_hash(day), canonical_json(nav), canonical_json(state)))
                    for event in events:
                        self._append_event(conn, account["id"], day, event)
                    if nav["contribution"]:
                        self._append_event(conn, account["id"], day, {"type": "cash_flow_posted", "amount": nav["contribution"]})
                conn.execute("UPDATE corrected_core_state SET state_json=?,diagnostics_json='[]' WHERE account_id=?",
                             (canonical_json(state), account["id"]))
        except (ValueError, KeyError, ArithmeticError, OSError) as exc:
            return self._blocked(config, "CORRECTED_CORE_INPUT_BLOCKED", str(exc))
        return self.snapshot(config)

    @staticmethod
    def nav_point(day: str, nav: dict) -> dict:
        return {"valuationDate": day, "grossNav": nav["wealth"]+nav["cost"], "netNav": nav["wealth"],
                "cash": nav["cash"], "dailyReturn": nav["daily_return"], "cumulativeReturn": nav["unit_nav"]-1,
                "drawdown": nav["unit_drawdown"], "receivable": nav["receivable"], "principal": nav["principal"],
                "unitNav": nav["unit_nav"], "cumulativeFees": nav["cumulative_cost"], "contribution": nav["contribution"],
                "dividendIncome": nav["dividend_income"], "marketPnl": nav["market_pnl"],
                "liquidationWealth": nav["liquidation_wealth"], "profit": nav["profit"], "accountResidual": nav["account_residual"]}

    def snapshot(self, config: StrategyConfig) -> dict:
        account, activation, state, diagnostics, latest = self._read(config)
        nav = json.loads(latest["nav_json"]) if latest else None
        pending = state["pending_signal"]
        target = pending["weights"] if pending else state["target"]
        desired = [{"symbol": s, "weight": float(w), "sleeve": "core", "reason": "causal_IV20"}
                   for s, w in zip(CORE_SYMBOLS, target or [])]
        current = []
        if nav:
            for k, s in enumerate(CORE_SYMBOLS):
                value = nav["quantity"][k]*nav["prices"][k]
                current.append({"symbol": s, "weight": value/nav["wealth"] if nav["wealth"] else 0.,
                                "quantity": nav["quantity"][k], "price": nav["prices"][k], "value": value, "sleeve": "core"})
        metrics = self.nav_point(latest["valuation_date"], nav) if nav else {
            "cash": float(activation["initial_cash"]) if activation else None,
            "principal": float(activation["initial_cash"]) if activation else None,
            "receivable": 0., "unitNav": 1.}
        return {"strategyId": config.strategy_id, "strategyVersion": config.version,
                "state": "EMPTY" if account is None else "BLOCKED" if diagnostics else "PENDING_EXECUTION" if pending else "READY" if nav else "ACTIVATED",
                "dates": {"marketDataDate": state["last_date"], "signalDate": state["last_signal"], "executionDate": state["last_execution"]},
                "assets": [{"symbol": a.symbol, "alias": a.alias, "sleeve": a.sleeve,
                            "quoteCurrency": "CNY", "baseCurrency": "CNY", "investableInstrument": a.symbol} for a in config.assets],
                "diagnostics": diagnostics,
                "observation": {"asOfDate": state["last_date"], "state": "paper", "reason": "raw_cash_dividend_v1",
                                "values": {"fractionalShares": True, "feeBpsPerTradedNotional": config.costs.base_bps,
                                           "premiumFilterEnabled": False, "depositExecution": "dated_instruction_before_open",
                                           "cashFlowTimingIsResearchAssumption": True,
                                           "corporateActionCoverage": "frozen_research_events_not_full_product_lifecycle",
                                           "noEventRowsDoesNotProveNoDistributions": True,
                                           "rawSnapshotUpdate": "explicit_import_not_daily_job_download"}},
                "currentWeights": current, "desiredWeights": desired, "executableWeights": [],
                "deltaWeights": [], "sleeveWeights": {"core": desired}, "nav": metrics,
                "ledger": {"status": "empty" if account is None else "pending" if pending else "active", "signalDate": state["last_signal"]},
                "operations": {"asOfDate": state["last_date"], "pendingOrderCount": 3 if pending else 0,
                               "waitingOpenCount": 3 if pending and state["waiting_open"] else 0, "grossExposure": sum(p["weight"] for p in current),
                               "benchmark": {"strategyId": config.strategy_id, "comparisonStatus": "SEPARATE_ACCOUNTING_CONTRACT"}},
                "calcError": diagnostics[0]["message"] if diagnostics else None}

    def nav_series(self, config: StrategyConfig, start: str | None, end: str | None) -> dict:
        account, _, _, _, _ = self._read(config)
        if account is None:
            return {"strategyId": config.strategy_id, "points": []}
        with closing(connect(self.ledger.db_path)) as conn:
            rows = conn.execute("SELECT valuation_date,nav_json FROM corrected_core_days WHERE account_id=? ORDER BY valuation_date",
                                (account["id"],)).fetchall()
        return {"strategyId": config.strategy_id, "points": [self.nav_point(r["valuation_date"], json.loads(r["nav_json"]))
                for r in rows if (start is None or r["valuation_date"] >= start) and (end is None or r["valuation_date"] <= end)]}

    def ledger_events(self, config: StrategyConfig, limit: int, cursor: int | None) -> dict:
        account, _, _, _, _ = self._read(config)
        if account is None:
            return {"strategyId": config.strategy_id, "events": [], "nextCursor": None}
        with closing(connect(self.ledger.db_path)) as conn:
            rows = conn.execute("""SELECT * FROM corrected_core_events WHERE account_id=? AND (? IS NULL OR id < ?)
                                 ORDER BY id DESC LIMIT ?""", (account["id"], cursor, cursor, limit+1)).fetchall()
        events = [{"id": r["id"], "type": r["event_type"], "eventDate": r["event_date"], "createdAt": r["created_at"],
                   "state": r["event_type"], "reason": r["event_type"], "details": json.loads(r["payload_json"])} for r in rows[:limit]]
        return {"strategyId": config.strategy_id, "events": events,
                "nextCursor": events[-1]["id"] if len(rows) > limit else None}
