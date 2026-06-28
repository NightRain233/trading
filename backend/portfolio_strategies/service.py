from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from collections.abc import Callable, Mapping
from typing import Any

import pandas as pd

from .btc_satellite import calculate_btc_satellite
from .ledger import PortfolioLedger, connect
from .market_data import (
    PortfolioMarketData,
    load_strategy_market_data,
    refresh_strategy_universe,
)
from .models import (
    CalculationState,
    DataDiagnostic,
    StrategyCalculation,
    StrategyConfig,
    StrategyMode,
    TargetWeight,
)
from .paper_engine import PaperAccountNotFoundError, PortfolioPaperEngine
from .registry import (
    ComparisonStrategyError,
    UnknownStrategyError,
    get_strategy,
    list_paper_strategies,
    list_strategies,
    require_paper_strategy,
)
from .theme_alpha import calculate_theme_alpha


def _calculate(config: StrategyConfig, market_data: PortfolioMarketData, as_of: date) -> StrategyCalculation:
    if config.strategy_id.startswith("btc_supertrend_satellite"):
        return calculate_btc_satellite(config, market_data, as_of)
    if config.strategy_id == "theme_alpha":
        return calculate_theme_alpha(config, market_data, as_of)
    raise UnknownStrategyError(config.strategy_id)


def _diagnostics_to_dict(diagnostics: tuple[DataDiagnostic, ...]) -> list[dict[str, Any]]:
    return [
        {
            "code": d.code,
            "message": d.message,
            "symbol": d.symbol,
            "details": dict(d.details),
        }
        for d in diagnostics
    ]


def _weights_to_list(weights: tuple[TargetWeight, ...]) -> list[dict[str, Any]]:
    return [
        {"symbol": w.symbol, "weight": w.weight, "sleeve": w.sleeve, "reason": w.reason}
        for w in weights
    ]


class PortfolioStrategyService:
    def __init__(
        self,
        data_dir: Path | str = "data",
        db_path: Path | str = "backtest_results/portfolio_paper.sqlite",
        *,
        refresh_fn: Callable | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self.data_dir = Path(data_dir)
        self.db_path = Path(db_path)
        self.ledger = PortfolioLedger(self.db_path)
        self.engine = PortfolioPaperEngine(self.ledger)
        self._refresh_fn = refresh_fn
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def list_strategies(self) -> list[dict[str, Any]]:
        result = []
        for config in list_strategies():
            entry: dict[str, Any] = {
                "strategyId": config.strategy_id,
                "version": config.version,
                "displayName": config.display_name,
                "description": config.description,
                "mode": config.mode.value,
                "execution": config.execution,
                "baseCurrency": config.base_currency,
                "initialNav": config.initial_nav,
                "paperEnabled": config.mode == StrategyMode.PAPER,
            }
            account = self.ledger.get_account(config) if config.mode == StrategyMode.PAPER else None
            entry["bootstrapped"] = account is not None
            if account is not None:
                entry["bootstrapSignalDate"] = account["bootstrap_signal_date"]
                entry["bootstrapValuationDate"] = account["bootstrap_valuation_date"]
            result.append(entry)
        return result

    def _load_market_data(self, config: StrategyConfig) -> PortfolioMarketData:
        return load_strategy_market_data(config, self.data_dir, self._clock())

    def _refresh_and_load(self, config: StrategyConfig, timeout: float = 30.0) -> PortfolioMarketData:
        refresh_strategy_universe(
            config,
            timeout,
            refresh_fn=self._refresh_fn,
        )
        return self._load_market_data(config)

    def get_snapshot(self, strategy_id: str) -> dict[str, Any]:
        config = get_strategy(strategy_id)
        market_data = self._load_market_data(config)
        account = self.ledger.get_account(config)

        # Build dates block
        dates: dict[str, Any] = {
            "marketDataDate": market_data.market_data_date.isoformat() if market_data.market_data_date else None,
            "signalDate": None,
            "executionDate": None,
            "nextCheck": None,
        }

        # Try calculation
        calculation: StrategyCalculation | None = None
        calc_error: str | None = None
        if not market_data.blocked:
            try:
                calculation = _calculate(config, market_data, market_data.market_data_date or date.today())
            except Exception as exc:
                calc_error = str(exc)

        if calculation is not None:
            dates["signalDate"] = calculation.signal_date.isoformat() if calculation.signal_date else None
            if calculation.signal_date and calculation.market_data_date:
                next_sessions = pd.DatetimeIndex(market_data.sessions)
                future = next_sessions[next_sessions > pd.Timestamp(calculation.market_data_date)]
                dates["nextCheck"] = future[0].date().isoformat() if not future.empty else None

        # Ledger state
        current_weights: list[dict[str, Any]] = []
        desired_weights: list[dict[str, Any]] = []
        executable_weights: list[dict[str, Any]] = []
        delta_weights: list[dict[str, Any]] = []
        nav_metrics: dict[str, Any] = {}
        ledger_summary: dict[str, Any] = {"status": "empty" if account is None else "bootstrapped"}
        pending = None

        if account is not None:
            positions = self.ledger.latest_positions(account["id"])
            nav = self.ledger.latest_nav(account["id"])
            if nav is not None:
                nav_metrics = {
                    "valuationDate": nav["valuation_date"],
                    "grossNav": nav["gross_nav"],
                    "netNav": nav["net_nav"],
                    "cash": nav["cash"],
                    "dailyReturn": nav["daily_return"],
                    "cumulativeReturn": nav["cumulative_return"],
                    "drawdown": nav["drawdown"],
                }
            if positions:
                total_value = sum(float(p["value"]) for p in positions)
                for p in positions:
                    current_weights.append({
                        "symbol": p["symbol"],
                        "weight": float(p["weight"]),
                        "quantity": float(p["quantity"]),
                        "price": float(p["price"]) if p["price"] is not None else None,
                        "value": float(p["value"]),
                    })

            pending = self.ledger.get_pending_rebalance(account["id"])
            if pending is not None:
                signal_id = pending["signal_id"]
                signal_weights = self.ledger.get_signal_weights(signal_id)
                for sw in signal_weights:
                    desired_weights.append({
                        "symbol": sw["symbol"],
                        "weight": float(sw["weight"]),
                        "sleeve": sw["sleeve"],
                        "reason": sw["reason"],
                    })
                dates["signalDate"] = pending["signal_date"]
                dates["executionDate"] = pending.get("execution_date")
                ledger_summary = {
                    "status": "pending",
                    "rebalanceId": pending["id"],
                    "signalDate": pending["signal_date"],
                }

        # Determine overall state
        if market_data.blocked:
            overall_state = "BLOCKED"
        elif calculation is not None and calculation.state == CalculationState.READY:
            overall_state = "READY" if pending is None else "PENDING_EXECUTION"
        elif calculation is not None and calculation.state == CalculationState.NOT_DUE:
            overall_state = "NOT_DUE"
        elif account is not None:
            overall_state = "BOOTSTRAPPED"
        else:
            overall_state = "EMPTY"

        # Target weights from calculation
        calc_targets: list[dict[str, Any]] = []
        calc_sleeves: dict[str, list[dict[str, Any]]] = {}
        if calculation is not None and calculation.target_weights:
            calc_targets = _weights_to_list(calculation.target_weights)
            calc_sleeves = {
                sleeve: _weights_to_list(weights)
                for sleeve, weights in calculation.sleeve_weights.items()
            }

        assets = [
            {
                "symbol": asset.symbol,
                "alias": asset.alias,
                "sleeve": asset.sleeve,
                "syntheticProxy": asset.synthetic_proxy,
            }
            for asset in config.assets
        ]

        return {
            "strategyId": config.strategy_id,
            "strategyVersion": config.version,
            "state": overall_state,
            "dates": dates,
            "assets": assets,
            "diagnostics": _diagnostics_to_dict(
                calculation.diagnostics if calculation is not None else market_data.diagnostics
            ),
            "observation": {
                "asOfDate": calculation.observation.as_of_date.isoformat() if calculation and calculation.observation else None,
                "state": calculation.observation.state if calculation and calculation.observation else None,
                "reason": calculation.observation.reason if calculation and calculation.observation else calc_error,
                "values": dict(calculation.observation.values) if calculation and calculation.observation else {},
            } if calculation else {"asOfDate": None, "state": None, "reason": calc_error, "values": {}},
            "currentWeights": current_weights,
            "desiredWeights": calc_targets if calc_targets else desired_weights,
            "executableWeights": [],
            "deltaWeights": [],
            "sleeveWeights": calc_sleeves,
            "nav": nav_metrics,
            "ledger": ledger_summary,
            "calcError": calc_error,
        }

    def refresh(self, strategy_id: str, now: datetime | None = None) -> dict[str, Any]:
        config = require_paper_strategy(strategy_id)
        effective_now = now or self._clock()
        market_data = self._refresh_and_load(config)

        if market_data.blocked:
            return self.get_snapshot(strategy_id)

        as_of = market_data.market_data_date or effective_now.date()
        try:
            calculation = _calculate(config, market_data, as_of)
        except Exception:
            return self.get_snapshot(strategy_id)

        account = self.ledger.get_account(config)
        if account is None:
            # Bootstrap
            if calculation.signal_date is None:
                return self.get_snapshot(strategy_id)
            valuation_date = market_data.market_data_date or as_of
            self.engine.bootstrap(config, calculation, market_data, valuation_date)
        elif calculation.state == CalculationState.READY and calculation.signal_date is not None:
            self.engine.queue_signal(config, calculation)

        # Reconcile any pending rebalance
        try:
            self.engine.reconcile(config, market_data)
        except PaperAccountNotFoundError:
            pass

        # Daily valuation
        account = self.ledger.get_account(config)
        if account is not None and market_data.market_data_date is not None:
            try:
                self.engine.value(config, market_data, market_data.market_data_date)
            except (PaperAccountNotFoundError, ValueError):
                pass

        return self.get_snapshot(strategy_id)

    def target_weights(self, strategy_id: str) -> dict[str, Any]:
        config = get_strategy(strategy_id)
        account = self.ledger.get_account(config)
        if account is None:
            return {"strategyId": strategy_id, "desired": [], "executable": []}

        desired = []
        pending = self.ledger.get_pending_rebalance(account["id"])
        signal_id = pending["signal_id"] if pending is not None else None
        if signal_id is not None:
            for sw in self.ledger.get_signal_weights(signal_id):
                desired.append({
                    "symbol": sw["symbol"],
                    "weight": float(sw["weight"]),
                    "sleeve": sw["sleeve"],
                    "reason": sw["reason"],
                })

        return {
            "strategyId": strategy_id,
            "desired": desired,
            "executable": [],
        }

    def rebalance_diff(self, strategy_id: str) -> dict[str, Any]:
        config = get_strategy(strategy_id)
        account = self.ledger.get_account(config)
        if account is None:
            return {"strategyId": strategy_id, "current": [], "desired": [], "delta": []}

        positions = self.ledger.latest_positions(account["id"])
        current = {
            p["symbol"]: float(p["weight"])
            for p in positions
        }

        desired: dict[str, float] = {}
        pending = self.ledger.get_pending_rebalance(account["id"])
        if pending is not None:
            for sw in self.ledger.get_signal_weights(pending["signal_id"]):
                desired[sw["symbol"]] = float(sw["weight"])

        all_symbols = sorted(set(current.keys()) | set(desired.keys()))
        rows = []
        for sym in all_symbols:
            cw = current.get(sym, 0.0)
            dw = desired.get(sym, 0.0)
            rows.append({
                "symbol": sym,
                "currentWeight": cw,
                "desiredWeight": dw,
                "delta": dw - cw,
            })

        return {
            "strategyId": strategy_id,
            "rows": rows,
        }

    def ledger_events(self, strategy_id: str, limit: int = 50, cursor: int | None = None) -> dict[str, Any]:
        config = require_paper_strategy(strategy_id)
        account = self.ledger.get_account(config)
        if account is None:
            return {"strategyId": strategy_id, "events": [], "nextCursor": None}

        conn = connect(self.db_path)
        try:
            base = """
                SELECT 'signal' AS type, id, signal_date AS event_date, state, reason, created_at
                FROM signal_snapshots WHERE account_id = ?
            """
            params: list[Any] = [account["id"]]
            if cursor is not None:
                base += " AND id < ?"
                params.append(cursor)
            base += " ORDER BY id DESC LIMIT ?"
            params.append(limit + 1)

            rows = conn.execute(base, params).fetchall()
            has_more = len(rows) > limit
            events_rows = rows[:limit]

            events = []
            for row in events_rows:
                events.append({
                    "type": row["type"],
                    "id": row["id"],
                    "eventDate": row["event_date"],
                    "state": row["state"],
                    "reason": row["reason"],
                    "createdAt": row["created_at"],
                })

            return {
                "strategyId": strategy_id,
                "events": events,
                "nextCursor": events[-1]["id"] if has_more and events else None,
            }
        finally:
            conn.close()

    def nav_series(self, strategy_id: str, start: str | None = None, end: str | None = None) -> dict[str, Any]:
        config = require_paper_strategy(strategy_id)
        account = self.ledger.get_account(config)
        if account is None:
            return {"strategyId": strategy_id, "points": []}

        conn = connect(self.db_path)
        try:
            query = """
                SELECT * FROM nav_snapshots
                WHERE account_id = ?
            """
            params: list[Any] = [account["id"]]
            if start is not None:
                query += " AND valuation_date >= ?"
                params.append(start)
            if end is not None:
                query += " AND valuation_date <= ?"
                params.append(end)
            query += " ORDER BY valuation_date ASC"

            rows = conn.execute(query, params).fetchall()
            points = [
                {
                    "valuationDate": row["valuation_date"],
                    "grossNav": row["gross_nav"],
                    "netNav": row["net_nav"],
                    "cash": row["cash"],
                    "dailyReturn": row["daily_return"],
                    "cumulativeReturn": row["cumulative_return"],
                    "drawdown": row["drawdown"],
                }
                for row in rows
            ]
            return {"strategyId": strategy_id, "points": points}
        finally:
            conn.close()
