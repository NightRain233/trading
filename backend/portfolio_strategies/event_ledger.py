from __future__ import annotations

from contextlib import contextmanager
from datetime import date
import hashlib
import json
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from .ledger import PortfolioLedger, _utc_now
from .models import StrategyConfig


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
        separators=(",", ":"),
    )


def payload_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def deterministic_key(*parts: object) -> str:
    return payload_hash([str(part) for part in parts])


class EventPortfolioLedger:
    """Append-oriented repository for next-open paper strategies.

    The legacy tables remain owned by :class:`PortfolioLedger`.  This wrapper
    only writes the v2 tables and deliberately uses deterministic uniqueness
    keys so retries from multiple uvicorn workers are harmless.
    """

    def __init__(self, ledger: PortfolioLedger):
        self.ledger = ledger

    @contextmanager
    def _connection(
        self,
        conn: sqlite3.Connection | None,
    ) -> Iterator[sqlite3.Connection]:
        if conn is not None:
            yield conn
        else:
            with self.ledger.transaction() as active:
                yield active

    def activate(
        self,
        config: StrategyConfig,
        *,
        activation_date: date,
        metadata: Mapping[str, Any],
        conn: sqlite3.Connection | None = None,
    ) -> sqlite3.Row:
        with self._connection(conn) as active:
            account = self.ledger.get_or_create_account(
                config,
                bootstrap_signal_date=None,
                bootstrap_valuation_date=activation_date,
                conn=active,
            )
            active.execute(
                """
                INSERT INTO strategy_activations (
                    account_id, activation_date, initial_cash, metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (account_id) DO NOTHING
                """,
                (
                    account["id"],
                    activation_date.isoformat(),
                    config.initial_nav,
                    canonical_json(dict(metadata)),
                    _utc_now(),
                ),
            )
            row = active.execute(
                "SELECT * FROM strategy_activations WHERE account_id = ?",
                (account["id"],),
            ).fetchone()
            assert row is not None
            return row

    def activation(
        self,
        account_id: int,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> sqlite3.Row | None:
        with self._connection(conn) as active:
            return active.execute(
                "SELECT * FROM strategy_activations WHERE account_id = ?",
                (account_id,),
            ).fetchone()

    def record_universe_snapshot(
        self,
        *,
        universe_id: str,
        universe_version: str,
        snapshot_date: date,
        effective_date: date,
        source_hash: str,
        input_hash: str,
        data_quality_status: str,
        metadata: Mapping[str, Any],
        memberships: Sequence[Mapping[str, Any]],
        conn: sqlite3.Connection | None = None,
    ) -> sqlite3.Row:
        with self._connection(conn) as active:
            active.execute(
                """
                INSERT INTO universe_snapshots (
                    universe_id, universe_version, snapshot_date,
                    effective_date, source_hash, input_hash,
                    data_quality_status, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (
                    universe_id, universe_version, effective_date, input_hash
                ) DO NOTHING
                """,
                (
                    universe_id, universe_version, snapshot_date.isoformat(),
                    effective_date.isoformat(), source_hash, input_hash,
                    data_quality_status, canonical_json(dict(metadata)), _utc_now(),
                ),
            )
            snapshot = active.execute(
                """
                SELECT * FROM universe_snapshots
                WHERE universe_id = ? AND universe_version = ?
                  AND effective_date = ? AND input_hash = ?
                """,
                (
                    universe_id, universe_version, effective_date.isoformat(), input_hash,
                ),
            ).fetchone()
            assert snapshot is not None
            for item in memberships:
                active.execute(
                    """
                    INSERT INTO universe_memberships (
                        universe_snapshot_id, symbol, market, selected,
                        qualified, liquidity_rank, score, reason,
                        details_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (universe_snapshot_id, symbol) DO NOTHING
                    """,
                    (
                        snapshot["id"], item["symbol"], item["market"],
                        int(bool(item["selected"])), int(bool(item["qualified"])),
                        item.get("liquidity_rank"), item.get("score"),
                        str(item.get("reason", "")),
                        canonical_json(dict(item.get("details", {}))), _utc_now(),
                    ),
                )
            return snapshot

    def record_data_quality(
        self,
        *,
        account_id: int | None,
        strategy_id: str,
        strategy_version: str,
        event_key: str,
        observed_at: str,
        code: str,
        message: str,
        market_data_date: date | None = None,
        symbol: str | None = None,
        previous_input_hash: str | None = None,
        current_input_hash: str | None = None,
        details: Mapping[str, Any] | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> sqlite3.Row:
        with self._connection(conn) as active:
            active.execute(
                """
                INSERT INTO data_quality_events_v2 (
                    account_id, strategy_id, strategy_version, event_key,
                    observed_at, market_data_date, code, message, symbol,
                    previous_input_hash, current_input_hash, details_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (event_key) DO NOTHING
                """,
                (
                    account_id,
                    strategy_id,
                    strategy_version,
                    event_key,
                    observed_at,
                    market_data_date.isoformat() if market_data_date else None,
                    code,
                    message,
                    symbol,
                    previous_input_hash,
                    current_input_hash,
                    canonical_json(dict(details or {})),
                    _utc_now(),
                ),
            )
            row = active.execute(
                "SELECT * FROM data_quality_events_v2 WHERE event_key = ?",
                (event_key,),
            ).fetchone()
            assert row is not None
            return row

    def record_decision(
        self,
        account_id: int,
        config: StrategyConfig,
        *,
        run_type: str,
        market_data_date: date,
        signal_date: date,
        universe_version: str | None,
        config_hash: str,
        input_hash: str,
        data_quality_status: str,
        payload: Mapping[str, Any],
        items: Sequence[Mapping[str, Any]],
        conn: sqlite3.Connection | None = None,
    ) -> tuple[sqlite3.Row, tuple[sqlite3.Row, ...]]:
        with self._connection(conn) as active:
            authoritative = active.execute(
                """
                SELECT * FROM decision_runs
                WHERE strategy_id = ? AND strategy_version = ?
                  AND run_type = ? AND signal_date = ? AND authoritative = 1
                """,
                (
                    config.strategy_id,
                    config.version,
                    run_type,
                    signal_date.isoformat(),
                ),
            ).fetchone()
            is_authoritative = authoritative is None
            active.execute(
                """
                INSERT INTO decision_runs (
                    account_id, strategy_id, strategy_version, run_type,
                    market_data_date, signal_date, universe_version,
                    config_hash, input_hash, data_quality_status,
                    authoritative, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (
                    strategy_id, strategy_version, run_type, signal_date,
                    input_hash
                ) DO NOTHING
                """,
                (
                    account_id,
                    config.strategy_id,
                    config.version,
                    run_type,
                    market_data_date.isoformat(),
                    signal_date.isoformat(),
                    universe_version,
                    config_hash,
                    input_hash,
                    data_quality_status,
                    int(is_authoritative),
                    canonical_json(dict(payload)),
                    _utc_now(),
                ),
            )
            run = active.execute(
                """
                SELECT * FROM decision_runs
                WHERE strategy_id = ? AND strategy_version = ?
                  AND run_type = ? AND signal_date = ? AND input_hash = ?
                """,
                (
                    config.strategy_id,
                    config.version,
                    run_type,
                    signal_date.isoformat(),
                    input_hash,
                ),
            ).fetchone()
            assert run is not None

            if authoritative is not None and authoritative["input_hash"] != input_hash:
                event_key = deterministic_key(
                    config.strategy_id,
                    config.version,
                    run_type,
                    signal_date,
                    authoritative["input_hash"],
                    input_hash,
                )
                self.record_data_quality(
                    account_id=account_id,
                    strategy_id=config.strategy_id,
                    strategy_version=config.version,
                    event_key=event_key,
                    observed_at=_utc_now(),
                    market_data_date=market_data_date,
                    code="MARKET_DATA_REVISION",
                    message="Decision input changed after the authoritative decision was recorded",
                    previous_input_hash=authoritative["input_hash"],
                    current_input_hash=input_hash,
                    details={"runType": run_type, "signalDate": signal_date.isoformat()},
                    conn=active,
                )

            item_rows: list[sqlite3.Row] = []
            for item in items:
                active.execute(
                    """
                    INSERT INTO decision_items (
                        decision_run_id, symbol, event_type, market, sleeve,
                        eligible, target_weight, priority, reason,
                        payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (decision_run_id, symbol, event_type) DO NOTHING
                    """,
                    (
                        run["id"],
                        item["symbol"],
                        item["event_type"],
                        item["market"],
                        item["sleeve"],
                        int(bool(item.get("eligible", True))),
                        item.get("target_weight"),
                        float(item.get("priority", 0.0)),
                        str(item.get("reason", "")),
                        canonical_json(dict(item.get("payload", {}))),
                        _utc_now(),
                    ),
                )
                row = active.execute(
                    """
                    SELECT * FROM decision_items
                    WHERE decision_run_id = ? AND symbol = ? AND event_type = ?
                    """,
                    (run["id"], item["symbol"], item["event_type"]),
                ).fetchone()
                assert row is not None
                item_rows.append(row)
            return run, tuple(item_rows)

    def create_order(
        self,
        account_id: int,
        config: StrategyConfig,
        *,
        decision_run_id: int,
        decision_item_id: int | None,
        order_key: str,
        sleeve: str,
        symbol: str,
        market: str,
        order_type: str,
        side: str,
        signal_date: date,
        expected_execution_date: date | None,
        target_weight: float | None,
        requested_weight_delta: float | None,
        requested_quantity: float | None = None,
        priority: float = 0.0,
        conn: sqlite3.Connection | None = None,
    ) -> sqlite3.Row:
        with self._connection(conn) as active:
            now = _utc_now()
            active.execute(
                """
                INSERT INTO paper_orders (
                    account_id, decision_run_id, decision_item_id, order_key,
                    strategy_id, strategy_version, sleeve, symbol, market,
                    order_type, side, status, signal_date,
                    expected_execution_date, next_attempt_date, target_weight,
                    requested_weight_delta, requested_quantity, priority,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (order_key) DO NOTHING
                """,
                (
                    account_id,
                    decision_run_id,
                    decision_item_id,
                    order_key,
                    config.strategy_id,
                    config.version,
                    sleeve,
                    symbol,
                    market,
                    order_type,
                    side,
                    signal_date.isoformat(),
                    expected_execution_date.isoformat() if expected_execution_date else None,
                    expected_execution_date.isoformat() if expected_execution_date else None,
                    target_weight,
                    requested_weight_delta,
                    requested_quantity,
                    priority,
                    now,
                    now,
                ),
            )
            row = active.execute(
                "SELECT * FROM paper_orders WHERE order_key = ?",
                (order_key,),
            ).fetchone()
            assert row is not None
            return row

    def pending_orders(
        self,
        account_id: int,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> tuple[sqlite3.Row, ...]:
        with self._connection(conn) as active:
            return tuple(
                active.execute(
                    """
                    SELECT * FROM paper_orders
                    WHERE account_id = ? AND status IN ('PENDING', 'WAITING_OPEN')
                    ORDER BY next_attempt_date, priority DESC, symbol, id
                    """,
                    (account_id,),
                ).fetchall()
            )

    def record_order_delay(
        self,
        order_id: int,
        *,
        attempted_date: date,
        reason: str,
        observed_open: float | None,
        next_expected_execution_date: date | None,
        conn: sqlite3.Connection | None = None,
    ) -> sqlite3.Row:
        with self._connection(conn) as active:
            active.execute(
                """
                INSERT INTO paper_order_attempts (
                    order_id, attempted_date, status, reason, observed_open,
                    next_expected_execution_date, created_at
                ) VALUES (?, ?, 'DELAYED', ?, ?, ?, ?)
                ON CONFLICT (order_id, attempted_date) DO NOTHING
                """,
                (
                    order_id,
                    attempted_date.isoformat(),
                    reason,
                    observed_open,
                    next_expected_execution_date.isoformat()
                    if next_expected_execution_date else None,
                    _utc_now(),
                ),
            )
            active.execute(
                """
                UPDATE paper_orders
                SET status = 'WAITING_OPEN', delay_reason = ?,
                    next_attempt_date = ?, updated_at = ?
                WHERE id = ? AND status IN ('PENDING', 'WAITING_OPEN')
                """,
                (
                    reason,
                    next_expected_execution_date.isoformat()
                    if next_expected_execution_date else None,
                    _utc_now(),
                    order_id,
                ),
            )
            row = active.execute(
                "SELECT * FROM paper_orders WHERE id = ?", (order_id,)
            ).fetchone()
            assert row is not None
            return row

    def record_execution(
        self,
        order_id: int,
        *,
        signal_date: date,
        expected_execution_date: date | None,
        actual_execution_date: date,
        actual_open: float,
        execution_price: float,
        side: str,
        quantity_delta: float,
        weight_delta: float,
        gross_notional: float,
        commission: float,
        slippage: float,
        conn: sqlite3.Connection | None = None,
    ) -> sqlite3.Row:
        with self._connection(conn) as active:
            active.execute(
                """
                INSERT INTO paper_executions (
                    order_id, signal_date, expected_execution_date,
                    actual_execution_date, actual_open, execution_price, side,
                    quantity_delta, weight_delta, gross_notional, commission,
                    slippage, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (order_id) DO NOTHING
                """,
                (
                    order_id,
                    signal_date.isoformat(),
                    expected_execution_date.isoformat()
                    if expected_execution_date else None,
                    actual_execution_date.isoformat(),
                    actual_open,
                    execution_price,
                    side,
                    quantity_delta,
                    weight_delta,
                    gross_notional,
                    commission,
                    slippage,
                    _utc_now(),
                ),
            )
            active.execute(
                """
                UPDATE paper_orders
                SET status = 'EXECUTED', actual_execution_date = ?, side = ?,
                    delay_reason = NULL, updated_at = ?
                WHERE id = ?
                """,
                (actual_execution_date.isoformat(), side, _utc_now(), order_id),
            )
            row = active.execute(
                "SELECT * FROM paper_executions WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            assert row is not None
            return row

    def reject_order(
        self,
        order_id: int,
        *,
        reason: str,
        conn: sqlite3.Connection | None = None,
    ) -> sqlite3.Row:
        with self._connection(conn) as active:
            active.execute(
                """
                UPDATE paper_orders
                SET status = 'REJECTED', rejection_reason = ?, updated_at = ?
                WHERE id = ? AND status IN ('PENDING', 'WAITING_OPEN')
                """,
                (reason, _utc_now(), order_id),
            )
            row = active.execute(
                "SELECT * FROM paper_orders WHERE id = ?", (order_id,)
            ).fetchone()
            assert row is not None
            return row
