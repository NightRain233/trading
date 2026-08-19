from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
import math
import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import exchange_calendars as xcals

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
from .event_ledger import EventPortfolioLedger, payload_hash
from .frozen_xquant import (
    evaluate_universe_snapshot,
    frozen_membership_snapshot,
    frozen_universe,
    normalize_daily,
)
from .next_open_data import load_next_open_frames
from .next_open_engine import NextOpenPaperEngine
from .next_open_strategies import (
    CORE_SYMBOLS,
    bearish_signal_dates,
    calculate_bull_decision,
    calculate_risk_parity_decision,
    core_common_sessions,
    core_signal_due,
)
from .operation_lock import portfolio_operation_lock
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
        decision_provider: Callable[[Sequence[str]], Mapping[str, Any]] | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self.data_dir = Path(data_dir)
        self.db_path = Path(db_path)
        self.ledger = PortfolioLedger(self.db_path)
        self.engine = PortfolioPaperEngine(self.ledger)
        self.next_open_engine = NextOpenPaperEngine(self.ledger)
        self.events = EventPortfolioLedger(self.ledger)
        self._refresh_fn = refresh_fn
        self._decision_provider = decision_provider
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def list_strategies(self) -> list[dict[str, Any]]:
        primary_ids = {
            "risk_parity_core_next_open",
            "core90_ma200_bull10",
            "theme_alpha",
            "btc_supertrend_satellite",
        }
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
                "presentationGroup": "primary" if config.strategy_id in primary_ids else "comparison",
                "isPrimary": config.strategy_id in primary_ids,
                "benchmarkStrategyId": (
                    None if config.strategy_id == "risk_parity_core_next_open"
                    else "risk_parity_core_next_open"
                ),
            }
            account = self.ledger.get_account(config) if config.mode == StrategyMode.PAPER else None
            entry["bootstrapped"] = account is not None
            activation = (
                self.events.activation(account["id"])
                if account is not None else None
            )
            activation_metadata = (
                json.loads(activation["metadata_json"])
                if activation is not None else {}
            )
            entry["activationDate"] = (
                activation["activation_date"] if activation is not None
                else account["bootstrap_valuation_date"] if account is not None
                else None
            )
            entry["accountOrigin"] = (
                activation_metadata.get("accountOrigin")
                if activation is not None
                else "legacy_preexisting" if account is not None
                else "not_activated"
            )
            if account is not None:
                entry["bootstrapSignalDate"] = account["bootstrap_signal_date"]
                entry["bootstrapValuationDate"] = account["bootstrap_valuation_date"]
            result.append(entry)
        return result

    def _today(self) -> date:
        return self._shanghai_date(self._clock())

    @staticmethod
    def _shanghai_date(value: datetime) -> date:
        aware = (
            value.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            if value.tzinfo is None else value
        )
        return aware.astimezone(ZoneInfo("Asia/Shanghai")).date()

    def _benchmark_block(
        self,
        config: StrategyConfig,
        *,
        valuation_date: str | None,
        net_nav: float | None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"strategyId": "risk_parity_core_next_open"}
        if valuation_date is None or net_nav is None:
            return result
        benchmark_config = get_strategy("risk_parity_core_next_open")
        benchmark_account = self.ledger.get_account(benchmark_config)
        if benchmark_account is None:
            return result
        conn = connect(self.db_path)
        try:
            benchmark = conn.execute(
                """SELECT * FROM portfolio_nav_v2 WHERE account_id = ?
                AND authoritative = 1 AND valuation_date <= ?
                ORDER BY valuation_date DESC, id DESC LIMIT 1""",
                (benchmark_account["id"], valuation_date),
            ).fetchone()
        finally:
            conn.close()
        if benchmark is None:
            return result
        strategy_ratio = net_nav / float(config.initial_nav)
        benchmark_ratio = float(benchmark["net_nav"]) / float(benchmark_account["initial_nav"])
        return {
            "strategyId": benchmark_config.strategy_id,
            "valuationDate": benchmark["valuation_date"],
            "benchmarkNav": float(benchmark["net_nav"]),
            "relativeNav": strategy_ratio / benchmark_ratio,
            "relativeReturn": strategy_ratio / benchmark_ratio - 1.0,
        }

    def _legacy_operations(
        self,
        config: StrategyConfig,
        account: Any,
        nav: Mapping[str, Any] | None,
        pending: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        orders: list[dict[str, Any]] = []
        if pending is not None:
            expected = pending.get("execution_date")
            orders.append({
                "orderId": -int(pending["id"]), "symbol": "BATCH",
                "market": "XSHG", "sleeve": "portfolio",
                "orderType": "NEXT_CLOSE_REBALANCE", "side": "REBALANCE",
                "status": "PENDING", "signalDate": pending["signal_date"],
                "expectedExecutionDate": expected, "nextAttemptDate": expected,
                "due": bool(expected and expected <= self._today().isoformat()),
            })
        net_nav = float(nav["net_nav"]) if nav is not None else None
        cash = float(nav["cash"]) if nav is not None else None
        gross_exposure = (
            max(0.0, 1.0 - cash / net_nav)
            if net_nav and cash is not None else None
        )
        valuation_date = str(nav["valuation_date"]) if nav is not None else None
        return {
            "asOfDate": valuation_date,
            "orders": orders,
            "bullCandidates": [],
            "dueOrderCount": sum(bool(order["due"]) for order in orders),
            "waitingOpenCount": 0,
            "pendingOrderCount": len(orders),
            "ma200AllowedCount": 0,
            "ma200BlockedCount": 0,
            "grossExposure": gross_exposure,
            "dataQualityEventCount": 0,
            "benchmark": self._benchmark_block(
                config, valuation_date=valuation_date, net_nav=net_nav,
            ),
        }

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
        if config.execution == "next_open":
            return self._get_next_open_snapshot(config)
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
        nav = None

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
                        "sleeve": "",
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

        response = {
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
        response["operations"] = self._legacy_operations(
            config, account, nav, pending,
        )
        return response

    def activate(
        self,
        strategy_id: str,
        *,
        activation_date: date,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        config = require_paper_strategy(strategy_id)
        effective_now = now or self._clock()
        local_today = self._shanghai_date(effective_now)
        if activation_date > local_today:
            raise ValueError("activationDate cannot be in the future")
        with portfolio_operation_lock(self.db_path, f"strategy-{strategy_id}"):
            account = self.ledger.get_account(config)
            if account is not None:
                existing = self.events.activation(account["id"])
                if existing is None and config.execution == "next_open":
                    raise ValueError(
                        "Existing next-open account has no activation audit record; "
                        "manual migration review is required"
                    )
                if (
                    existing is not None
                    and existing["activation_date"] != activation_date.isoformat()
                ):
                    raise ValueError(
                        "Strategy is already activated on "
                        f"{existing['activation_date']}"
                    )
                return self.get_snapshot(strategy_id)
            if config.execution == "next_open":
                self.next_open_engine.activate(
                    config, activation_date=activation_date,
                )
            else:
                self.engine.activate_cash(
                    config, activation_date=activation_date,
                )
            return self.get_snapshot(strategy_id)

    def refresh(self, strategy_id: str, now: datetime | None = None) -> dict[str, Any]:
        config = require_paper_strategy(strategy_id)
        with portfolio_operation_lock(self.db_path, f"strategy-{strategy_id}"):
            return self._refresh_locked(config, now=now)

    def _refresh_locked(
        self,
        config: StrategyConfig,
        *,
        now: datetime | None,
    ) -> dict[str, Any]:
        if config.execution == "next_open":
            return self._refresh_next_open(config, now=now)
        effective_now = now or self._clock()
        market_data = self._refresh_and_load(config)

        if market_data.blocked:
            return self.get_snapshot(config.strategy_id)

        as_of = market_data.market_data_date or effective_now.date()
        try:
            calculation = _calculate(config, market_data, as_of)
        except Exception:
            return self.get_snapshot(strategy_id)

        account = self.ledger.get_account(config)
        if account is None:
            return self.get_snapshot(config.strategy_id)
        elif calculation.state == CalculationState.READY and calculation.signal_date is not None:
            activation = self.events.activation(account["id"])
            if (
                activation is None
                or calculation.signal_date
                > date.fromisoformat(activation["activation_date"])
            ):
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

        return self.get_snapshot(config.strategy_id)

    def _next_open_frames(
        self,
        config: StrategyConfig,
        *,
        through_date: date,
        as_of: datetime | None = None,
    ) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
        symbols = list(config.symbols)
        if config.strategy_id.startswith("core90_"):
            universe = frozen_universe()
            symbols.extend(universe.reference_symbol_by_market.values())
        return load_next_open_frames(
            self.data_dir, symbols, through_date=through_date, as_of=as_of,
        )

    def _active_membership(
        self,
        signal_date: date,
    ) -> dict[str, dict[str, Any]]:
        conn = connect(self.db_path)
        try:
            snapshot = conn.execute(
                """
                SELECT * FROM universe_snapshots
                WHERE universe_id = ? AND universe_version = ?
                  AND effective_date <= ?
                ORDER BY effective_date DESC, id ASC LIMIT 1
                """,
                (
                    frozen_universe().universe_id,
                    frozen_universe().universe_version,
                    signal_date.isoformat(),
                ),
            ).fetchone()
            if snapshot is None:
                return {}
            rows = conn.execute(
                """
                SELECT * FROM universe_memberships
                WHERE universe_snapshot_id = ? AND selected = 1
                """,
                (snapshot["id"],),
            ).fetchall()
            return {
                row["symbol"]: {
                    "effectiveDate": snapshot["effective_date"],
                    "liquidityRank": row["liquidity_rank"],
                }
                for row in rows
            }
        finally:
            conn.close()

    def _ensure_current_universe(
        self,
        frames: Mapping[str, pd.DataFrame],
        signal_date: date,
    ) -> None:
        universe = frozen_universe()
        month_start = pd.Timestamp(signal_date).replace(day=1).normalize()
        non_crypto_dates: set[pd.Timestamp] = set()
        for symbol, frame in frames.items():
            if universe.market_by_symbol.get(symbol) == "crypto":
                continue
            non_crypto_dates.update(frame.index[frame.index < month_start])
        if not non_crypto_dates:
            return
        snapshot_date = max(non_crypto_dates).date()
        future_dates: set[pd.Timestamp] = set()
        snapshot_ts = pd.Timestamp(snapshot_date)
        for symbol, frame in frames.items():
            if universe.market_by_symbol.get(symbol) == "crypto":
                continue
            future_dates.update(frame.index[frame.index > snapshot_ts])
        if not future_dates:
            return
        effective_date = min(future_dates).date()
        conn = connect(self.db_path)
        try:
            exists = conn.execute(
                """
                SELECT 1 FROM universe_snapshots
                WHERE universe_id = ? AND universe_version = ?
                  AND effective_date = ? LIMIT 1
                """,
                (universe.universe_id, universe.universe_version, effective_date.isoformat()),
            ).fetchone()
        finally:
            conn.close()
        if exists is not None:
            return
        frozen = frozen_membership_snapshot(effective_date)
        result = None if frozen is not None else evaluate_universe_snapshot(
            frames, snapshot_date=snapshot_date, effective_date=effective_date,
            universe=universe,
        )
        serialized = []
        memberships = []
        if frozen is not None:
            snapshot_date = date.fromisoformat(str(frozen["snapshotDate"]))
            selected = set(frozen["selectedSymbols"])
            source_rows = [{
                "snapshotDate": snapshot_date.isoformat(),
                "effectiveDate": effective_date.isoformat(),
                "symbol": symbol,
                "market": universe.market_by_symbol[symbol],
                "qualified": symbol in selected,
                "selected": symbol in selected,
                "liquidityRank": None,
                "failureReasons": "" if symbol in selected else "not_selected_in_frozen_snapshot",
            } for symbol in universe.symbols]
        else:
            assert result is not None
            source_rows = result.to_dict("records")
        for row in source_rows:
            def clean(value: Any) -> Any:
                if pd.isna(value):
                    return None
                if isinstance(value, (float, int)) and not math.isfinite(float(value)):
                    return None
                if isinstance(value, pd.Timestamp):
                    return value.date().isoformat()
                if isinstance(value, (pd.Timedelta,)):
                    return str(value)
                if hasattr(value, "item"):
                    return value.item()
                return value
            details = {key: clean(value) for key, value in row.items()}
            serialized.append(details)
            memberships.append({
                "symbol": row["symbol"],
                "market": row["market"],
                "selected": bool(row["selected"]),
                "qualified": bool(row["qualified"]),
                "liquidity_rank": clean(row["liquidityRank"]),
                "reason": str(row["failureReasons"]),
                "details": details,
            })
        self.events.record_universe_snapshot(
            universe_id=universe.universe_id,
            universe_version=universe.universe_version,
            snapshot_date=snapshot_date,
            effective_date=effective_date,
            source_hash=universe.source_hash,
            input_hash=payload_hash(serialized),
            data_quality_status="OK",
            metadata={
                "selectionMode": "monthly_point_in_time",
                "frozenXquantSnapshot": frozen is not None,
            },
            memberships=memberships,
        )

    def _refresh_next_open(
        self,
        config: StrategyConfig,
        *,
        now: datetime | None,
    ) -> dict[str, Any]:
        effective_now = now or self._clock()
        through_date = self._shanghai_date(effective_now)
        if self._refresh_fn is not None:
            refresh_strategy_universe(config, 30.0, refresh_fn=self._refresh_fn)
        frames, errors = self._next_open_frames(
            config, through_date=through_date, as_of=effective_now,
        )
        if any(symbol not in frames for symbol in CORE_SYMBOLS):
            return self._get_next_open_snapshot(config, load_errors=errors)
        sessions = core_common_sessions(frames)
        if sessions.empty:
            return self._get_next_open_snapshot(config, load_errors=errors)
        market_data_date = sessions[-1].date()
        account = self.ledger.get_account(config)
        if account is not None and self.events.activation(account["id"]) is None:
            errors = dict(errors)
            errors["ACTIVATION_RECORD"] = "missing_for_existing_next_open_account"
            return self._get_next_open_snapshot(config, load_errors=errors)
        expected_sessions = xcals.get_calendar("XSHG").sessions_in_range(
            pd.Timestamp(through_date) - pd.Timedelta(days=14),
            pd.Timestamp(through_date),
        )
        expected_core_date = (
            pd.Timestamp(expected_sessions[-1]).tz_localize(None).date()
            if not expected_sessions.empty else through_date
        )
        core_stale = market_data_date < expected_core_date
        if core_stale:
            errors = dict(errors)
            errors["CORE_COMMON_SESSION"] = (
                f"stale:{market_data_date.isoformat()}<expected:{expected_core_date.isoformat()}"
            )
            if account is not None:
                self.next_open_engine.reconcile(config, frames, through_date=through_date)
                self.events.record_data_quality(
                    account_id=account["id"], strategy_id=config.strategy_id,
                    strategy_version=config.version,
                    event_key=payload_hash([
                        config.strategy_id, "STALE_CORE_DATA",
                        market_data_date.isoformat(), expected_core_date.isoformat(),
                    ]),
                    observed_at=effective_now.isoformat(),
                    market_data_date=market_data_date,
                    code="STALE_CORE_DATA",
                    message="Core common-session data is stale; no new signal was generated",
                    details={"expectedDate": expected_core_date.isoformat()},
                )
        if account is None:
            return self._get_next_open_snapshot(config, load_errors=errors)

        # First settle prior signals using each symbol's own valid Open.
        self.next_open_engine.reconcile(config, frames, through_date=through_date)
        state = self.next_open_engine.current_state(config)
        assert state is not None
        account = self.ledger.get_account(config)
        assert account is not None
        activation = self.events.activation(account["id"])
        assert activation is not None
        activation_date = date.fromisoformat(activation["activation_date"])
        conn = connect(self.db_path)
        try:
            pending = conn.execute(
                """
                SELECT * FROM paper_orders
                WHERE account_id = ? AND status IN ('PENDING', 'WAITING_OPEN')
                """,
                (account["id"],),
            ).fetchall()
            last_core_signal = conn.execute(
                """SELECT MAX(signal_date) FROM decision_runs
                WHERE account_id = ? AND run_type = 'CORE_REBALANCE'
                  AND authoritative = 1""",
                (account["id"],),
            ).fetchone()[0]
        finally:
            conn.close()

        has_core = bool(state.held_symbols("core"))
        pending_core = any(row["order_type"] == "CORE_REBALANCE" for row in pending)
        anchor = date.fromisoformat(str(
            last_core_signal or config.params["schedule_anchor_signal_date"]
        ))
        if not core_stale and market_data_date > activation_date and not pending_core and (
            not has_core
            or core_signal_due(
                frames, market_data_date, anchor_signal_date=anchor,
                every=int(config.params["rebalance_sessions"]),
            )
        ):
            decision = calculate_risk_parity_decision(
                config, frames, signal_date=market_data_date,
            )
            self.next_open_engine.queue_decision(config, decision, frames)

        if config.strategy_id == "core90_ma200_bull10":
            self._ensure_current_universe(frames, market_data_date)
            if self._decision_provider is not None:
                scan = self._decision_provider(frozen_universe().symbols)
                items = list(scan.get("items", ()))
                for item_date_text in {
                    str(item.get("decisionAsOf")) for item in items
                    if item.get("decisionAsOf")
                }:
                    try:
                        item_date = date.fromisoformat(item_date_text)
                    except ValueError:
                        continue
                    if activation_date < item_date <= through_date:
                        self._ensure_current_universe(frames, item_date)
                self._refresh_bull_symbols(
                    config, account, state, pending, frames, items,
                    activation_date=activation_date,
                )

        # Today-generated signals cannot execute on today's close; this pass
        # only catches independently-dated markets already due from prior days.
        self.next_open_engine.reconcile(config, frames, through_date=through_date)
        try:
            self.next_open_engine.value(config, frames, through_date)
        except ValueError:
            pass
        return self._get_next_open_snapshot(config, load_errors=errors)

    def _refresh_bull_symbols(
        self,
        config: StrategyConfig,
        account: Mapping[str, Any],
        state: Any,
        pending: Sequence[Mapping[str, Any]],
        frames: Mapping[str, pd.DataFrame],
        items: Sequence[Mapping[str, Any]],
        *,
        activation_date: date,
    ) -> None:
        """Advance every satellite symbol on its own completed daily calendar."""
        universe = frozen_universe()
        by_symbol = {
            str(item["symbol"]): item for item in items if item.get("symbol")
        }
        held = state.held_symbols("satellite")
        pending_exit_symbols = {
            str(row["symbol"]) for row in pending
            if row["order_type"] == "ST_BEAR_EXIT"
            and row["status"] in ("PENDING", "WAITING_OPEN")
        }
        symbols = sorted(held | set(by_symbol))
        conn = connect(self.db_path)
        try:
            cursors = {
                row["run_type"].split(":", 1)[1]: date.fromisoformat(row["cursor_date"])
                for row in conn.execute(
                    """SELECT run_type, MAX(signal_date) AS cursor_date
                    FROM decision_runs WHERE account_id = ? AND authoritative = 1
                    AND run_type LIKE 'BULL_DAILY:%' GROUP BY run_type""",
                    (account["id"],),
                ).fetchall()
            }
        finally:
            conn.close()

        for symbol in symbols:
            frame = frames.get(symbol)
            if frame is None or universe.market_by_symbol.get(symbol) is None:
                continue
            normalized = normalize_daily(frame)
            if normalized.empty:
                continue
            latest_date = normalized.index[-1].date()
            cursor = max(activation_date, cursors.get(symbol, activation_date))
            run_type = f"BULL_DAILY:{symbol}"

            if symbol in held:
                if symbol in pending_exit_symbols:
                    continue
                candidate_dates = [
                    timestamp.date() for timestamp in normalized.index
                    if cursor < timestamp.date() <= latest_date
                ]
                if not candidate_dates:
                    continue
                bearish = set(bearish_signal_dates(
                    frame,
                    after_date=cursor,
                    through_date=latest_date,
                    atr_window=int(config.params["supertrend_atr_window"]),
                    multiplier=float(config.params["supertrend_multiplier"]),
                ))
                for signal_date in candidate_dates:
                    decision = calculate_bull_decision(
                        config, (), frames, {}, signal_date=signal_date,
                        held_symbols=(symbol,) if signal_date in bearish else (),
                        pending_exit_symbols=pending_exit_symbols,
                        run_type=run_type,
                    )
                    orders = self.next_open_engine.queue_decision(config, decision, frames)
                    if orders:
                        pending_exit_symbols.add(symbol)
                        break
                continue

            item = by_symbol.get(symbol)
            item_date_text = item.get("decisionAsOf") if item else None
            try:
                item_date = date.fromisoformat(str(item_date_text))
            except (TypeError, ValueError):
                continue
            # A production decision is usable only for this symbol's own latest
            # completed bar.  Another market's newer as-of date is irrelevant.
            if (
                item_date != latest_date
                or item_date <= activation_date
                or item_date < cursors.get(symbol, activation_date)
            ):
                continue
            membership = self._active_membership(item_date)
            own_membership = (
                {symbol: membership[symbol]} if symbol in membership else {}
            )
            decision = calculate_bull_decision(
                config, (item,), frames, own_membership,
                signal_date=item_date,
                pending_exit_symbols=pending_exit_symbols,
                run_type=run_type,
            )
            self.next_open_engine.queue_decision(config, decision, frames)

    def _get_next_open_snapshot(
        self,
        config: StrategyConfig,
        *,
        load_errors: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        account = self.ledger.get_account(config)
        assets = [{
            "symbol": asset.symbol, "alias": asset.alias, "sleeve": asset.sleeve,
            "syntheticProxy": asset.synthetic_proxy,
        } for asset in config.assets]
        if account is None:
            return {
                "strategyId": config.strategy_id, "strategyVersion": config.version,
                "state": "EMPTY",
                "dates": {}, "assets": assets,
                "diagnostics": [], "observation": {}, "currentWeights": [],
                "desiredWeights": [], "executableWeights": [], "deltaWeights": [],
                "sleeveWeights": {}, "nav": {}, "ledger": {"status": "empty"},
                "operations": {
                    "orders": [], "bullCandidates": [],
                    "benchmark": {"strategyId": "risk_parity_core_next_open"},
                },
                "calcError": None,
            }
        conn = connect(self.db_path)
        try:
            nav = conn.execute(
                """SELECT * FROM portfolio_nav_v2 WHERE account_id = ?
                AND authoritative = 1 ORDER BY valuation_date DESC, id DESC LIMIT 1""",
                (account["id"],),
            ).fetchone()
            positions = conn.execute(
                """SELECT * FROM portfolio_positions_v2 WHERE account_id = ?
                AND authoritative = 1 AND valuation_date = (
                    SELECT MAX(valuation_date) FROM portfolio_positions_v2
                    WHERE account_id = ? AND authoritative = 1)
                ORDER BY sleeve, symbol""",
                (account["id"], account["id"]),
            ).fetchall()
            pending = conn.execute(
                """SELECT * FROM paper_orders WHERE account_id = ?
                AND status IN ('PENDING', 'WAITING_OPEN')
                ORDER BY next_attempt_date, priority DESC, symbol""",
                (account["id"],),
            ).fetchall()
            today_text = self._today().isoformat()
            operation_orders = conn.execute(
                """SELECT o.*, e.actual_open, e.quantity_delta,
                    e.commission, e.slippage
                FROM paper_orders o
                LEFT JOIN paper_executions e ON e.order_id = o.id
                WHERE o.account_id = ? AND (
                    o.status IN ('PENDING', 'WAITING_OPEN')
                    OR o.actual_execution_date = ?
                )
                ORDER BY COALESCE(o.next_attempt_date, o.actual_execution_date),
                         o.priority DESC, o.symbol""",
                (account["id"], today_text),
            ).fetchall()
            latest_bull_run = conn.execute(
                """SELECT * FROM decision_runs WHERE account_id = ?
                AND authoritative = 1 AND run_type LIKE 'BULL_DAILY:%'
                ORDER BY signal_date DESC, id DESC LIMIT 1""",
                (account["id"],),
            ).fetchone()
            bull_rows = [] if latest_bull_run is None else conn.execute(
                """SELECT i.*, r.signal_date AS run_signal_date
                FROM decision_items i JOIN decision_runs r
                  ON r.id = i.decision_run_id
                WHERE r.account_id = ? AND r.authoritative = 1
                  AND r.run_type LIKE 'BULL_DAILY:%'
                  AND r.signal_date = ? AND i.event_type = 'BULL_FLIP_ENTRY'
                ORDER BY i.priority DESC, i.symbol""",
                (account["id"], latest_bull_run["signal_date"]),
            ).fetchall()
            data_quality_count = conn.execute(
                "SELECT COUNT(*) FROM data_quality_events_v2 WHERE account_id = ?",
                (account["id"],),
            ).fetchone()[0]
            latest_decision = conn.execute(
                """SELECT * FROM decision_runs WHERE account_id = ? AND authoritative = 1
                ORDER BY signal_date DESC, id DESC LIMIT 1""", (account["id"],),
            ).fetchone()
            desired = []
            if latest_decision is not None:
                desired = [dict(row) for row in conn.execute(
                    """SELECT symbol, target_weight AS weight, sleeve, reason
                    FROM decision_items WHERE decision_run_id = ? AND eligible = 1
                    AND target_weight IS NOT NULL ORDER BY priority DESC, symbol""",
                    (latest_decision["id"],),
                ).fetchall()]
        finally:
            conn.close()
        current = [{
            "symbol": row["symbol"], "weight": float(row["weight"]),
            "quantity": float(row["quantity"]), "price": float(row["price"]),
            "value": float(row["value"]),
            "sleeve": row["sleeve"],
        } for row in positions]
        diagnostics = [{
            "code": "MISSING_OPTIONAL_MARKET_DATA", "message": reason,
            "symbol": symbol, "details": {},
        } for symbol, reason in sorted((load_errors or {}).items())]
        pending_dates = [row["next_attempt_date"] for row in pending if row["next_attempt_date"]]
        orders = [{
            "orderId": row["id"], "symbol": row["symbol"],
            "market": row["market"], "sleeve": row["sleeve"],
            "orderType": row["order_type"], "side": row["side"],
            "status": row["status"], "signalDate": row["signal_date"],
            "expectedExecutionDate": row["expected_execution_date"],
            "nextAttemptDate": row["next_attempt_date"],
            "actualExecutionDate": row["actual_execution_date"],
            "actualOpen": row["actual_open"],
            "requestedWeightDelta": row["requested_weight_delta"],
            "quantityDelta": row["quantity_delta"],
            "commission": row["commission"], "slippage": row["slippage"],
            "delayReason": row["delay_reason"],
            "rejectionReason": row["rejection_reason"],
            "due": bool(
                row["status"] in ("PENDING", "WAITING_OPEN")
                and row["next_attempt_date"]
                and row["next_attempt_date"] <= today_text
            ),
        } for row in operation_orders]
        bull_candidates = []
        for row in bull_rows:
            payload = json.loads(row["payload_json"])
            bull_candidates.append({
                "symbol": row["symbol"], "market": row["market"],
                "signalDate": row["run_signal_date"],
                "eligible": bool(row["eligible"]), "reason": row["reason"],
                "permission": payload.get("permission"),
                "referenceSymbol": payload.get("referenceSymbol"),
                "referenceDate": payload.get("referenceDate"),
                "referenceClose": payload.get("referenceClose"),
                "referenceMa": payload.get("referenceMa"),
                "riskOn": payload.get("riskOn"),
                "gateReason": payload.get("gateReason"),
            })
        net_nav = float(nav["net_nav"]) if nav is not None else None
        valuation_date = nav["valuation_date"] if nav is not None else None
        operations = {
            "asOfDate": valuation_date,
            "orders": orders,
            "bullCandidates": bull_candidates,
            "dueOrderCount": sum(bool(order["due"]) for order in orders),
            "waitingOpenCount": sum(order["status"] == "WAITING_OPEN" for order in orders),
            "pendingOrderCount": len(pending),
            "ma200AllowedCount": sum(item.get("riskOn") is True for item in bull_candidates),
            "ma200BlockedCount": sum(item.get("riskOn") is False for item in bull_candidates),
            "grossExposure": float(nav["gross_exposure"]) if nav is not None else None,
            "dataQualityEventCount": int(data_quality_count),
            "benchmark": self._benchmark_block(
                config, valuation_date=valuation_date, net_nav=net_nav,
            ),
        }
        return {
            "strategyId": config.strategy_id, "strategyVersion": config.version,
            "state": "PENDING_EXECUTION" if pending else "ACTIVE",
            "dates": {
                "marketDataDate": nav["valuation_date"] if nav else None,
                "signalDate": latest_decision["signal_date"] if latest_decision else None,
                "executionDate": min(pending_dates) if pending_dates else None,
                "nextCheck": min(pending_dates) if pending_dates else None,
            },
            "assets": assets, "diagnostics": diagnostics,
            "observation": {
                "asOfDate": nav["valuation_date"] if nav else None,
                "state": "deterministic", "reason": "Frozen next-open paper state",
                "values": {
                    "pendingOrders": len(pending),
                    "waitingOpen": sum(row["status"] == "WAITING_OPEN" for row in pending),
                },
            },
            "currentWeights": current, "desiredWeights": desired,
            "executableWeights": [], "deltaWeights": [], "sleeveWeights": {},
            "nav": ({
                "valuationDate": nav["valuation_date"], "grossNav": nav["gross_nav"],
                "netNav": nav["net_nav"], "cash": nav["cash"],
                "dailyReturn": nav["daily_return"],
                "cumulativeReturn": nav["cumulative_return"],
                "drawdown": nav["drawdown"],
            } if nav else {}),
            "ledger": {
                "status": "pending" if pending else "active",
                "signalDate": latest_decision["signal_date"] if latest_decision else None,
            },
            "operations": operations,
            "calcError": None,
        }

    def target_weights(self, strategy_id: str) -> dict[str, Any]:
        config = get_strategy(strategy_id)
        if config.execution == "next_open":
            account = self.ledger.get_account(config)
            if account is None:
                return {"strategyId": strategy_id, "desired": [], "executable": []}
            conn = connect(self.db_path)
            try:
                run = conn.execute(
                    """SELECT id FROM decision_runs WHERE account_id = ?
                    AND authoritative = 1 ORDER BY signal_date DESC, id DESC LIMIT 1""",
                    (account["id"],),
                ).fetchone()
                desired = [] if run is None else [dict(row) for row in conn.execute(
                    """SELECT symbol, target_weight AS weight, sleeve, reason
                    FROM decision_items WHERE decision_run_id = ? AND eligible = 1
                    AND target_weight IS NOT NULL ORDER BY priority DESC, symbol""",
                    (run["id"],),
                ).fetchall()]
                return {"strategyId": strategy_id, "desired": desired, "executable": []}
            finally:
                conn.close()
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
        if config.execution == "next_open":
            account = self.ledger.get_account(config)
            if account is None:
                return {"strategyId": strategy_id, "rows": []}
            snapshot = self._get_next_open_snapshot(config)
            current: dict[str, float] = {}
            for row in snapshot["currentWeights"]:
                current[row["symbol"]] = (
                    current.get(row["symbol"], 0.0) + float(row["weight"])
                )
            desired = {
                row["symbol"]: float(row["weight"])
                for row in self.target_weights(strategy_id)["desired"]
            }
            rows = [{
                "symbol": symbol,
                "currentWeight": current.get(symbol, 0.0),
                "desiredWeight": desired.get(symbol, 0.0),
                "delta": desired.get(symbol, 0.0) - current.get(symbol, 0.0),
            } for symbol in sorted(set(current) | set(desired))]
            return {"strategyId": strategy_id, "rows": rows}
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

        if config.execution == "next_open":
            conn = connect(self.db_path)
            try:
                query = """
                    SELECT * FROM (
                        SELECT 'decision' AS type, id * 10 + 1 AS event_id,
                               signal_date AS event_date,
                               data_quality_status AS state,
                               run_type AS reason, created_at
                        FROM decision_runs WHERE account_id = ?
                        UNION ALL
                        SELECT 'order' AS type, id * 10 + 2 AS event_id,
                               COALESCE(actual_execution_date, signal_date) AS event_date,
                               status AS state,
                               symbol || ' ' || order_type || COALESCE(' ' || delay_reason, '') AS reason,
                               updated_at AS created_at
                        FROM paper_orders WHERE account_id = ?
                        UNION ALL
                        SELECT 'data_quality' AS type, id * 10 + 3 AS event_id,
                               market_data_date AS event_date, code AS state,
                               message AS reason, created_at
                        FROM data_quality_events_v2 WHERE account_id = ?
                    )
                """
                params: list[Any] = [account["id"], account["id"], account["id"]]
                if cursor is not None:
                    query += " WHERE event_id < ?"
                    params.append(cursor)
                query += " ORDER BY event_id DESC LIMIT ?"
                params.append(limit + 1)
                rows = conn.execute(query, params).fetchall()
                has_more = len(rows) > limit
                rows = rows[:limit]
                events = [{
                    "type": row["type"], "id": row["event_id"],
                    "eventDate": row["event_date"], "state": row["state"],
                    "reason": row["reason"], "createdAt": row["created_at"],
                } for row in rows]
                return {
                    "strategyId": strategy_id, "events": events,
                    "nextCursor": events[-1]["id"] if has_more and events else None,
                }
            finally:
                conn.close()

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
            table = "portfolio_nav_v2" if config.execution == "next_open" else "nav_snapshots"
            authoritative = " AND authoritative = 1" if config.execution == "next_open" else ""
            query = f"SELECT * FROM {table} WHERE account_id = ?{authoritative}"
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
