from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import math
import sqlite3
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

import exchange_calendars as xcals
import numpy as np
import pandas as pd

from .event_ledger import (
    EventPortfolioLedger,
    deterministic_key,
    payload_hash,
)
from .frozen_xquant import normalize_daily
from .ledger import PortfolioLedger, _utc_now
from .models import StrategyConfig
from .next_open_strategies import (
    CASH_SYMBOL,
    CORE_SYMBOLS,
    FrozenDecision,
    calculate_core_open_rebalance,
    next_core_valid_open_date,
    next_valid_open_date,
)


ACTIVE_ORDER_STATUSES = ("PENDING", "WAITING_OPEN")


@dataclass
class AccountState:
    quantities: dict[tuple[str, str], float]
    cash: dict[str, float]

    def held_symbols(self, sleeve: str | None = None) -> set[str]:
        return {
            symbol
            for (item_sleeve, symbol), quantity in self.quantities.items()
            if quantity > 1e-12 and (sleeve is None or item_sleeve == sleeve)
        }


def _execution_calendar_name(symbol: str) -> str | None:
    if symbol.endswith((".SS", ".SZ")):
        return "XSHG"
    if symbol.endswith(".HK"):
        return "XHKG"
    if symbol.endswith("-USD"):
        return None
    return "XNYS"


def expected_next_market_date(symbol: str, signal_date: date) -> date:
    if symbol.endswith("-USD"):
        return signal_date + timedelta(days=1)
    calendar = xcals.get_calendar(_execution_calendar_name(symbol) or "XNYS")
    sessions = calendar.sessions_in_range(
        pd.Timestamp(signal_date + timedelta(days=1)),
        pd.Timestamp(signal_date + timedelta(days=14)),
    )
    if sessions.empty:
        raise ValueError(f"No expected market session for {symbol} after {signal_date}")
    return pd.Timestamp(sessions[0]).tz_localize(None).date()


def _price_on_or_before(
    frame: pd.DataFrame,
    valuation_date: date,
    field: str = "Close",
) -> tuple[date, float]:
    data = normalize_daily(frame)
    available = data.index[data.index <= pd.Timestamp(valuation_date)]
    if available.empty or field not in data:
        raise ValueError(f"Missing {field} on or before {valuation_date}")
    values = pd.to_numeric(data.loc[available, field], errors="coerce")
    valid = values.notna() & np.isfinite(values) & values.gt(0)
    if not valid.any():
        raise ValueError(f"No valid {field} on or before {valuation_date}")
    timestamp = values.index[valid][-1]
    return timestamp.date(), float(values.loc[timestamp])


class NextOpenPaperEngine:
    """Event-driven next-open engine for the frozen xquant strategies."""

    def __init__(self, ledger: PortfolioLedger):
        self.ledger = ledger
        self.events = EventPortfolioLedger(ledger)

    def activate(
        self,
        config: StrategyConfig,
        *,
        activation_date: date,
    ) -> dict[str, Any]:
        with self.ledger.transaction() as conn:
            activation = self.events.activate(
                config,
                activation_date=activation_date,
                metadata={
                    "mode": config.params["activation_mode"],
                    "accountOrigin": "first_activation",
                    "historicalContinuation": False,
                    "historicalTradesBackfilled": False,
                },
                conn=conn,
            )
            account = self.ledger.get_account(config, conn=conn)
            assert account is not None
            existing = self._latest_nav(account["id"], conn=conn)
            if existing is None:
                if config.strategy_id.startswith("core90_"):
                    cash = {
                        "core": config.initial_nav * float(config.params["core_allocation"]),
                        "satellite": config.initial_nav * float(config.params["satellite_allocation"]),
                    }
                else:
                    cash = {"core": config.initial_nav}
                self._save_snapshot(
                    conn,
                    account,
                    config,
                    activation_date,
                    AccountState(quantities={}, cash=cash),
                    prices={},
                    snapshot_reason="activation_cash",
                )
            return dict(activation)

    def _latest_nav(
        self,
        account_id: int,
        *,
        conn: sqlite3.Connection,
    ) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT * FROM portfolio_nav_v2
            WHERE account_id = ? AND authoritative = 1
            ORDER BY valuation_date DESC, id DESC LIMIT 1
            """,
            (account_id,),
        ).fetchone()

    def _load_state(
        self,
        account_id: int,
        *,
        conn: sqlite3.Connection,
    ) -> AccountState:
        latest_date = conn.execute(
            """
            SELECT MAX(valuation_date) FROM portfolio_positions_v2
            WHERE account_id = ? AND authoritative = 1
            """,
            (account_id,),
        ).fetchone()[0]
        if latest_date is None:
            raise ValueError("Next-open account has no position snapshot")
        rows = conn.execute(
            """
            SELECT * FROM portfolio_positions_v2
            WHERE account_id = ? AND valuation_date = ? AND authoritative = 1
            """,
            (account_id, latest_date),
        ).fetchall()
        quantities: dict[tuple[str, str], float] = {}
        cash: dict[str, float] = defaultdict(float)
        for row in rows:
            if row["symbol"] == CASH_SYMBOL:
                cash[row["sleeve"]] += float(row["quantity"])
            else:
                quantities[(row["sleeve"], row["symbol"])] = float(row["quantity"])
        return AccountState(quantities=quantities, cash=dict(cash))

    def current_state(self, config: StrategyConfig) -> AccountState | None:
        with self.ledger.transaction() as conn:
            account = self.ledger.get_account(config, conn=conn)
            if account is None or self.events.activation(account["id"], conn=conn) is None:
                return None
            return self._load_state(account["id"], conn=conn)

    def value(
        self,
        config: StrategyConfig,
        prices: Mapping[str, pd.DataFrame],
        valuation_date: date,
    ) -> dict[str, Any]:
        with self.ledger.transaction() as conn:
            account = self.ledger.get_account(config, conn=conn)
            if account is None or self.events.activation(account["id"], conn=conn) is None:
                raise ValueError(f"Strategy is not activated: {config.strategy_id}")
            state = self._load_state(account["id"], conn=conn)
            return dict(self._save_snapshot(
                conn, account, config, valuation_date, state, prices,
                snapshot_reason="daily_close_valuation",
                record_revision_quality=True,
            ))

    def _mark_state(
        self,
        state: AccountState,
        prices: Mapping[str, pd.DataFrame],
        valuation_date: date,
        *,
        field: str = "Close",
    ) -> tuple[dict[tuple[str, str], float], dict[str, date], float]:
        values: dict[tuple[str, str], float] = {}
        price_dates: dict[str, date] = {}
        total = sum(state.cash.values())
        for key, quantity in state.quantities.items():
            _sleeve, symbol = key
            price_date, price = _price_on_or_before(prices[symbol], valuation_date, field)
            values[key] = quantity * price
            price_dates[symbol] = price_date
            total += values[key]
        return values, price_dates, total

    def _save_snapshot(
        self,
        conn: sqlite3.Connection,
        account: sqlite3.Row,
        config: StrategyConfig,
        valuation_date: date,
        state: AccountState,
        prices: Mapping[str, pd.DataFrame],
        *,
        snapshot_reason: str,
        record_revision_quality: bool = False,
    ) -> sqlite3.Row:
        values: dict[tuple[str, str], float] = {}
        price_info: dict[str, tuple[date, float]] = {}
        for key, quantity in state.quantities.items():
            _sleeve, symbol = key
            price_info[symbol] = _price_on_or_before(prices[symbol], valuation_date)
            values[key] = quantity * price_info[symbol][1]
        net_nav = sum(values.values()) + sum(state.cash.values())
        if not math.isfinite(net_nav) or net_nav <= 0:
            raise ValueError("Paper NAV must remain finite and positive")
        snapshot_payload = {
            "valuationDate": valuation_date.isoformat(),
            "quantities": {
                f"{sleeve}:{symbol}": quantity
                for (sleeve, symbol), quantity in sorted(state.quantities.items())
            },
            "cash": dict(sorted(state.cash.items())),
            "prices": {
                symbol: {"date": value[0].isoformat(), "close": value[1]}
                for symbol, value in sorted(price_info.items())
            },
        }
        input_hash = payload_hash(snapshot_payload)
        existing = conn.execute(
            """
            SELECT * FROM portfolio_nav_v2
            WHERE account_id = ? AND valuation_date = ? AND input_hash = ?
            """,
            (account["id"], valuation_date.isoformat(), input_hash),
        ).fetchone()
        if existing is not None:
            return existing

        previous_authoritative = conn.execute(
            """
            SELECT * FROM portfolio_nav_v2
            WHERE account_id = ? AND valuation_date = ? AND authoritative = 1
            ORDER BY id DESC LIMIT 1
            """,
            (account["id"], valuation_date.isoformat()),
        ).fetchone()
        if record_revision_quality and previous_authoritative is not None:
            self.events.record_data_quality(
                account_id=account["id"],
                strategy_id=config.strategy_id,
                strategy_version=config.version,
                event_key=deterministic_key(
                    config.strategy_id, config.version, "VALUATION_REVISION",
                    valuation_date, previous_authoritative["input_hash"], input_hash,
                ),
                observed_at=_utc_now(),
                market_data_date=valuation_date,
                code="MARKET_DATA_VALUATION_REVISION",
                message="Valuation inputs changed after an authoritative snapshot was recorded",
                previous_input_hash=previous_authoritative["input_hash"],
                current_input_hash=input_hash,
                details={"snapshotReason": snapshot_reason},
                conn=conn,
            )

        conn.execute(
            """
            UPDATE portfolio_positions_v2 SET authoritative = 0
            WHERE account_id = ? AND valuation_date = ? AND authoritative = 1
            """,
            (account["id"], valuation_date.isoformat()),
        )
        conn.execute(
            """
            UPDATE portfolio_nav_v2 SET authoritative = 0
            WHERE account_id = ? AND valuation_date = ? AND authoritative = 1
            """,
            (account["id"], valuation_date.isoformat()),
        )
        created = _utc_now()
        for (sleeve, symbol), quantity in sorted(state.quantities.items()):
            price_date, price = price_info[symbol]
            value = values[(sleeve, symbol)]
            conn.execute(
                """
                INSERT INTO portfolio_positions_v2 (
                    account_id, valuation_date, sleeve, symbol, quantity,
                    price, price_date, value, weight, input_hash,
                    authoritative, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    account["id"], valuation_date.isoformat(), sleeve, symbol,
                    quantity, price, price_date.isoformat(), value,
                    value / net_nav, input_hash, created,
                ),
            )
        for sleeve, cash in sorted(state.cash.items()):
            conn.execute(
                """
                INSERT INTO portfolio_positions_v2 (
                    account_id, valuation_date, sleeve, symbol, quantity,
                    price, price_date, value, weight, input_hash,
                    authoritative, created_at
                ) VALUES (?, ?, ?, 'CASH', ?, 1, ?, ?, ?, ?, 1, ?)
                """,
                (
                    account["id"], valuation_date.isoformat(), sleeve, cash,
                    valuation_date.isoformat(), cash, cash / net_nav,
                    input_hash, created,
                ),
            )
        previous = conn.execute(
            """
            SELECT * FROM portfolio_nav_v2
            WHERE account_id = ? AND valuation_date < ? AND authoritative = 1
            ORDER BY valuation_date DESC, id DESC LIMIT 1
            """,
            (account["id"], valuation_date.isoformat()),
        ).fetchone()
        previous_nav = float(previous["net_nav"]) if previous else float(account["initial_nav"])
        previous_max = float(previous["running_max"]) if previous else float(account["initial_nav"])
        running_max = max(previous_max, net_nav)
        gross_exposure = sum(values.values()) / net_nav
        conn.execute(
            """
            INSERT INTO portfolio_nav_v2 (
                account_id, valuation_date, gross_nav, net_nav, cash,
                gross_exposure, daily_return, cumulative_return, drawdown,
                running_max, input_hash, authoritative, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                account["id"], valuation_date.isoformat(), net_nav, net_nav,
                sum(state.cash.values()), gross_exposure,
                net_nav / previous_nav - 1.0 if previous else 0.0,
                net_nav / float(account["initial_nav"]) - 1.0,
                net_nav / running_max - 1.0,
                running_max, input_hash, created,
            ),
        )
        row = conn.execute(
            """
            SELECT * FROM portfolio_nav_v2
            WHERE account_id = ? AND valuation_date = ? AND input_hash = ?
            """,
            (account["id"], valuation_date.isoformat(), input_hash),
        ).fetchone()
        assert row is not None
        return row

    def queue_decision(
        self,
        config: StrategyConfig,
        decision: FrozenDecision,
        prices: Mapping[str, pd.DataFrame],
    ) -> tuple[dict[str, Any], ...]:
        with self.ledger.transaction() as conn:
            account = self.ledger.get_account(config, conn=conn)
            if account is None or self.events.activation(account["id"], conn=conn) is None:
                raise ValueError(f"Strategy is not activated: {config.strategy_id}")
            run, item_rows = self.events.record_decision(
                account["id"], config,
                run_type=decision.run_type,
                market_data_date=decision.market_data_date,
                signal_date=decision.signal_date,
                universe_version=decision.universe_version,
                config_hash=decision.config_hash,
                input_hash=decision.input_hash,
                data_quality_status=decision.data_quality_status,
                payload=decision.payload,
                items=decision.items,
                conn=conn,
            )
            if not bool(run["authoritative"]):
                return ()
            state = self._load_state(account["id"], conn=conn)
            latest_nav = self._latest_nav(account["id"], conn=conn)
            account_nav = float(latest_nav["net_nav"]) if latest_nav else config.initial_nav
            current_values: dict[str, float] = defaultdict(float)
            latest_positions = conn.execute(
                """
                SELECT * FROM portfolio_positions_v2
                WHERE account_id = ? AND authoritative = 1
                  AND valuation_date = (
                    SELECT MAX(valuation_date) FROM portfolio_positions_v2
                    WHERE account_id = ? AND authoritative = 1
                  )
                """,
                (account["id"], account["id"]),
            ).fetchall()
            for position in latest_positions:
                current_values[position["symbol"]] += float(position["value"])
            by_key = {
                (row["symbol"], row["event_type"]): row for row in item_rows
            }
            orders: list[dict[str, Any]] = []
            for item in decision.items:
                if not bool(item.get("eligible", True)):
                    continue
                symbol = str(item["symbol"])
                event_type = str(item["event_type"])
                target = item.get("target_weight")
                if event_type == "BULL_FLIP_ENTRY":
                    side = "BUY"
                    delta = float(target or 0.0) * float(
                        config.params["satellite_allocation"]
                    )
                elif event_type == "ST_BEAR_EXIT":
                    side = "SELL"
                    delta = -current_values.get(symbol, 0.0) / account_nav
                else:
                    desired_value = float(target or 0.0) * account_nav
                    delta = (desired_value - current_values.get(symbol, 0.0)) / account_nav
                    if event_type != "CORE_REBALANCE" and abs(delta) <= 1e-12:
                        continue
                    side = "BUY" if delta > 0 else "SELL"
                expected = (
                    expected_next_market_date("510300.SS", decision.signal_date)
                    if event_type == "CORE_REBALANCE"
                    else expected_next_market_date(symbol, decision.signal_date)
                )
                item_row = by_key[(symbol, event_type)]
                order_key = deterministic_key(
                    config.strategy_id, config.version, run["id"], item_row["id"],
                    symbol, side, event_type,
                )
                order = self.events.create_order(
                    account["id"], config,
                    decision_run_id=run["id"],
                    decision_item_id=item_row["id"],
                    order_key=order_key,
                    sleeve=str(item["sleeve"]),
                    symbol=symbol,
                    market=str(item["market"]),
                    order_type=event_type,
                    side=side,
                    signal_date=decision.signal_date,
                    expected_execution_date=expected,
                    target_weight=float(target) if target is not None else None,
                    requested_weight_delta=delta,
                    priority=float(item.get("priority", 0.0)),
                    conn=conn,
                )
                orders.append(dict(order))
            return tuple(orders)

    def reconcile(
        self,
        config: StrategyConfig,
        prices: Mapping[str, pd.DataFrame],
        *,
        through_date: date,
    ) -> tuple[dict[str, Any], ...]:
        with self.ledger.transaction() as conn:
            account = self.ledger.get_account(config, conn=conn)
            if account is None:
                raise ValueError(f"Unknown next-open account: {config.strategy_id}")
            pending = list(self.events.pending_orders(account["id"], conn=conn))
            if not pending:
                return ()
            state = self._load_state(account["id"], conn=conn)
            results: list[dict[str, Any]] = []

            core_orders = [row for row in pending if row["order_type"] == "CORE_REBALANCE"]
            if core_orders:
                results.extend(self._reconcile_core_batch(
                    conn, account, config, state, prices, core_orders, through_date
                ))

            other = [row for row in pending if row["order_type"] != "CORE_REBALANCE"]
            by_date: dict[date, list[sqlite3.Row]] = defaultdict(list)
            for order in other:
                due = date.fromisoformat(
                    order["next_attempt_date"] or order["expected_execution_date"]
                )
                if due <= through_date:
                    by_date[due].append(order)
            for due_date in sorted(by_date):
                orders = sorted(
                    by_date[due_date],
                    key=lambda row: (
                        0 if row["side"] == "SELL" else 1,
                        -float(row["priority"]), row["symbol"], row["id"],
                    ),
                )
                for order in orders:
                    result = self._reconcile_single_order(
                        conn, account, config, state, prices, order, through_date
                    )
                    results.append(result)
                    actual_text = result.get("actual_execution_date")
                    if actual_text:
                        self._save_snapshot(
                            conn, account, config, date.fromisoformat(actual_text),
                            state, prices, snapshot_reason="bull_order_execution",
                        )
            return tuple(results)

    def _reconcile_core_batch(
        self,
        conn: sqlite3.Connection,
        account: sqlite3.Row,
        config: StrategyConfig,
        state: AccountState,
        prices: Mapping[str, pd.DataFrame],
        orders: list[sqlite3.Row],
        through_date: date,
    ) -> list[dict[str, Any]]:
        signal_date = date.fromisoformat(orders[0]["signal_date"])
        expected = date.fromisoformat(orders[0]["expected_execution_date"])
        due = date.fromisoformat(
            orders[0]["next_attempt_date"] or orders[0]["expected_execution_date"]
        )
        if due > through_date:
            return []
        last_attempt = conn.execute(
            """
            SELECT MAX(attempted_date) FROM paper_order_attempts
            WHERE order_id IN ({})
            """.format(",".join("?" for _ in orders)),
            tuple(row["id"] for row in orders),
        ).fetchone()[0]
        search_after = date.fromisoformat(last_attempt) if last_attempt else signal_date
        actual = next_core_valid_open_date(prices, search_after)
        latest_loaded = min(
            normalize_daily(prices[symbol]).index.max().date() for symbol in CORE_SYMBOLS
        )
        if actual is None and latest_loaded < due:
            return []
        if actual is None or actual > through_date:
            next_attempt = expected_next_market_date("510300.SS", through_date)
            for order in orders:
                self.events.record_order_delay(
                    order["id"], attempted_date=due,
                    reason="COMMON_CORE_OPEN_NOT_AVAILABLE",
                    observed_open=None, next_expected_execution_date=next_attempt,
                    conn=conn,
                )
            return [{"orderId": row["id"], "status": "WAITING_OPEN"} for row in orders]
        if actual > due:
            for order in orders:
                self.events.record_order_delay(
                    order["id"], attempted_date=due,
                    reason="COMMON_CORE_OPEN_NOT_AVAILABLE",
                    observed_open=None, next_expected_execution_date=actual,
                    conn=conn,
                )

        self._rebalance_sleeves(conn, account, config, state, prices, actual, signal_date)
        opens = {symbol: _price_on_or_before(prices[symbol], actual, "Open")[1] for symbol in CORE_SYMBOLS}
        target_raw = {row["symbol"]: float(row["target_weight"]) for row in orders}
        rebalance = calculate_core_open_rebalance(
            {symbol: state.quantities.get(("core", symbol), 0.0) for symbol in CORE_SYMBOLS},
            state.cash.get("core", 0.0), opens, target_raw,
            cost_bps=float(config.params.get(
                "core_one_way_cost_bps", config.params.get("one_way_cost_bps", 10.0)
            )),
        )
        total_cost = rebalance.cost
        account_open_nav = rebalance.gross_nav + state.cash.get("satellite", 0.0)
        for (sleeve, satellite_symbol), quantity in state.quantities.items():
            if sleeve != "satellite":
                continue
            frame = normalize_daily(prices[satellite_symbol])
            prior = frame.index[frame.index < pd.Timestamp(actual)]
            if prior.empty:
                raise ValueError(f"Missing prior satellite Close: {satellite_symbol}")
            close = pd.to_numeric(frame.loc[prior, "Close"], errors="coerce").dropna()
            if close.empty:
                raise ValueError(f"Invalid prior satellite Close: {satellite_symbol}")
            account_open_nav += quantity * float(close.iloc[-1])
        deltas: dict[str, tuple[float, float]] = {}
        total_abs = 0.0
        for symbol in CORE_SYMBOLS:
            target_quantity = rebalance.target_quantities[symbol]
            quantity_delta = target_quantity - state.quantities.get(("core", symbol), 0.0)
            abs_notional = abs(quantity_delta * opens[symbol])
            deltas[symbol] = (quantity_delta, abs_notional)
            total_abs += abs_notional
        results = []
        for order in orders:
            symbol = order["symbol"]
            quantity_delta, gross_notional = deltas[symbol]
            allocated_cost = total_cost * gross_notional / total_abs if total_abs else 0.0
            execution = self.events.record_execution(
                order["id"],
                signal_date=signal_date,
                expected_execution_date=expected,
                actual_execution_date=actual,
                actual_open=opens[symbol],
                execution_price=opens[symbol],
                side="BUY" if quantity_delta > 0 else "SELL",
                quantity_delta=quantity_delta,
                weight_delta=quantity_delta * opens[symbol] / account_open_nav,
                gross_notional=gross_notional,
                commission=allocated_cost,
                slippage=0.0,
                conn=conn,
            )
            state.quantities[("core", symbol)] = (
                state.quantities.get(("core", symbol), 0.0) + quantity_delta
            )
            results.append(dict(execution))
        state.cash["core"] = 0.0
        self._save_snapshot(
            conn, account, config, actual, state, prices,
            snapshot_reason="core_next_open_rebalance",
        )
        return results

    def _rebalance_sleeves(
        self,
        conn: sqlite3.Connection,
        account: sqlite3.Row,
        config: StrategyConfig,
        state: AccountState,
        prices: Mapping[str, pd.DataFrame],
        execution_date: date,
        signal_date: date,
    ) -> None:
        if not config.strategy_id.startswith("core90_"):
            return
        # xquant resets sleeve budgets before applying that calendar day's
        # sleeve returns.  Mark both sleeves at the last Close strictly before
        # the core execution date; the core Open gap is handled afterwards by
        # the core rebalance itself.
        values: dict[tuple[str, str], float] = {}
        total = sum(state.cash.values())
        for key, quantity in state.quantities.items():
            _sleeve, symbol = key
            frame = normalize_daily(prices[symbol])
            prior = frame.index[frame.index < pd.Timestamp(execution_date)]
            if prior.empty:
                raise ValueError(f"Missing prior Close for sleeve mark: {symbol}")
            close = pd.to_numeric(frame.loc[prior, "Close"], errors="coerce").dropna()
            if close.empty or not math.isfinite(float(close.iloc[-1])):
                raise ValueError(f"Invalid prior Close for sleeve mark: {symbol}")
            values[key] = quantity * float(close.iloc[-1])
            total += values[key]
        core_value = state.cash.get("core", 0.0) + sum(
            value for (sleeve, _symbol), value in values.items() if sleeve == "core"
        )
        satellite_value = total - core_value
        core_weight = core_value / total
        desired_core_weight = float(config.params["core_allocation"])
        turnover = abs(core_weight - desired_core_weight)
        cost = total * turnover * float(config.params["sleeve_rebalance_cost_bps"]) / 10_000.0
        after_cost = total - cost
        desired_values = {
            "core": after_cost * desired_core_weight,
            "satellite": after_cost * (1.0 - desired_core_weight),
        }
        current_values = {"core": core_value, "satellite": satellite_value}
        for sleeve in ("core", "satellite"):
            current = current_values[sleeve]
            if current > 0:
                factor = desired_values[sleeve] / current
                state.cash[sleeve] = state.cash.get(sleeve, 0.0) * factor
                for key in list(state.quantities):
                    if key[0] == sleeve:
                        state.quantities[key] *= factor
            else:
                state.cash[sleeve] = desired_values[sleeve]
        if turnover > 1e-15:
            from_sleeve, to_sleeve = (
                ("core", "satellite") if core_weight > desired_core_weight
                else ("satellite", "core")
            )
            conn.execute(
                """
                INSERT INTO sleeve_transfer_events (
                    account_id, signal_date, execution_date, from_sleeve,
                    to_sleeve, gross_notional, cost, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (
                    account_id, signal_date, from_sleeve, to_sleeve
                ) DO NOTHING
                """,
                (
                    account["id"], signal_date.isoformat(), execution_date.isoformat(),
                    from_sleeve, to_sleeve, total * turnover, cost,
                    "Restore frozen core/satellite budget", _utc_now(),
                ),
            )

    def _reconcile_single_order(
        self,
        conn: sqlite3.Connection,
        account: sqlite3.Row,
        config: StrategyConfig,
        state: AccountState,
        prices: Mapping[str, pd.DataFrame],
        order: sqlite3.Row,
        through_date: date,
    ) -> dict[str, Any]:
        symbol = order["symbol"]
        signal_date = date.fromisoformat(order["signal_date"])
        expected = date.fromisoformat(order["expected_execution_date"])
        due = date.fromisoformat(order["next_attempt_date"] or order["expected_execution_date"])
        frame = prices.get(symbol)
        last_attempt = conn.execute(
            "SELECT MAX(attempted_date) FROM paper_order_attempts WHERE order_id = ?",
            (order["id"],),
        ).fetchone()[0]
        search_after = date.fromisoformat(last_attempt) if last_attempt else signal_date
        actual = next_valid_open_date(frame, search_after) if frame is not None else None
        if frame is None or normalize_daily(frame).index.max().date() < due:
            return {"orderId": order["id"], "status": "PENDING"}
        if actual is None or actual > through_date:
            next_attempt = expected_next_market_date(symbol, through_date)
            self.events.record_order_delay(
                order["id"], attempted_date=due,
                reason="VALID_OPEN_NOT_AVAILABLE", observed_open=None,
                next_expected_execution_date=next_attempt, conn=conn,
            )
            return {"orderId": order["id"], "status": "WAITING_OPEN"}
        actual_open = _price_on_or_before(frame, actual, "Open")[1]
        if actual > due:
            self.events.record_order_delay(
                order["id"], attempted_date=due,
                reason="MISSING_OR_INVALID_OPEN", observed_open=None,
                next_expected_execution_date=actual, conn=conn,
            )
        sleeve = order["sleeve"]
        key = (sleeve, symbol)
        commission_rate = float(config.params["bull_commission_bps"]) / 10_000.0
        slippage_rate = float(config.params["bull_slippage_bps"]) / 10_000.0
        values, _dates, total_nav = self._mark_state(state, prices, actual, field="Open")
        sleeve_nav = state.cash.get(sleeve, 0.0) + sum(
            value for (item_sleeve, _symbol), value in values.items()
            if item_sleeve == sleeve
        )
        if order["side"] == "SELL":
            quantity = state.quantities.get(key, 0.0)
            if quantity <= 1e-12:
                rejected = self.events.reject_order(order["id"], reason="NO_POSITION", conn=conn)
                return dict(rejected)
            execution_price = actual_open * (1.0 - slippage_rate)
            gross_notional = quantity * execution_price
            commission = gross_notional * commission_rate
            slippage = quantity * (actual_open - execution_price)
            quantity_delta = -quantity
            state.quantities.pop(key, None)
            state.cash[sleeve] = state.cash.get(sleeve, 0.0) + gross_notional - commission
        else:
            if state.quantities.get(key, 0.0) > 1e-12:
                rejected = self.events.reject_order(order["id"], reason="ALREADY_HELD", conn=conn)
                return dict(rejected)
            if len(state.held_symbols("satellite")) >= int(config.params["max_concurrent_positions"]):
                rejected = self.events.reject_order(order["id"], reason="CONCURRENCY_LIMIT", conn=conn)
                return dict(rejected)
            satellite_target = sleeve_nav * float(config.params["max_satellite_position_weight"])
            position_cap = total_nav * float(config.params["satellite_allocation"]) * float(
                config.params["max_satellite_position_weight"]
            )
            satellite_gross = sum(
                value for (item_sleeve, _symbol), value in values.items()
                if item_sleeve == "satellite"
            )
            sleeve_cap = total_nav * float(config.params["satellite_allocation"]) * float(
                config.params["max_satellite_gross_exposure"]
            )
            remaining_exposure = max(0.0, sleeve_cap - satellite_gross)
            target_notional = min(satellite_target, position_cap, remaining_exposure)
            affordable = state.cash.get(sleeve, 0.0) / (1.0 + commission_rate)
            gross_notional = min(target_notional, affordable)
            if gross_notional <= 1e-9:
                rejected = self.events.reject_order(order["id"], reason="CAPITAL_LIMIT", conn=conn)
                return dict(rejected)
            execution_price = actual_open * (1.0 + slippage_rate)
            quantity_delta = gross_notional / execution_price
            commission = gross_notional * commission_rate
            slippage = quantity_delta * (execution_price - actual_open)
            state.quantities[key] = quantity_delta
            state.cash[sleeve] = state.cash.get(sleeve, 0.0) - gross_notional - commission
        weight_delta = quantity_delta * actual_open / total_nav
        execution = self.events.record_execution(
            order["id"], signal_date=signal_date,
            expected_execution_date=expected, actual_execution_date=actual,
            actual_open=actual_open, execution_price=execution_price,
            side=order["side"], quantity_delta=quantity_delta,
            weight_delta=weight_delta, gross_notional=gross_notional,
            commission=commission, slippage=slippage, conn=conn,
        )
        return dict(execution)
