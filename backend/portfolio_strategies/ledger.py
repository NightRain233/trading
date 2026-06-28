from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sqlite3
from collections.abc import Iterator, Mapping

from .models import StrategyConfig, StrategyMode
from .registry import ComparisonStrategyError


SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_accounts (
    id INTEGER PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    initial_nav REAL NOT NULL,
    base_currency TEXT NOT NULL,
    bootstrap_signal_date TEXT,
    bootstrap_valuation_date TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (strategy_id, strategy_version)
);

CREATE TABLE IF NOT EXISTS signal_snapshots (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES paper_accounts(id) ON DELETE CASCADE,
    strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    signal_date TEXT NOT NULL,
    market_data_date TEXT NOT NULL,
    origin TEXT NOT NULL,
    state TEXT NOT NULL,
    reason TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (strategy_id, strategy_version, signal_date)
);

CREATE TABLE IF NOT EXISTS signal_weights (
    id INTEGER PRIMARY KEY,
    signal_id INTEGER NOT NULL REFERENCES signal_snapshots(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    weight REAL NOT NULL,
    sleeve TEXT NOT NULL,
    reason TEXT NOT NULL,
    UNIQUE (signal_id, symbol)
);

CREATE TABLE IF NOT EXISTS rebalance_events (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES paper_accounts(id) ON DELETE CASCADE,
    signal_id INTEGER NOT NULL REFERENCES signal_snapshots(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    execution_date TEXT,
    turnover REAL,
    cost REAL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (signal_id)
);

CREATE TABLE IF NOT EXISTS paper_trades (
    id INTEGER PRIMARY KEY,
    rebalance_event_id INTEGER NOT NULL
        REFERENCES rebalance_events(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    weight_delta REAL NOT NULL,
    gross_notional REAL NOT NULL,
    quantity_delta REAL NOT NULL,
    fees REAL NOT NULL,
    slippage REAL NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (rebalance_event_id, symbol)
);

CREATE TABLE IF NOT EXISTS position_snapshots (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES paper_accounts(id) ON DELETE CASCADE,
    valuation_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    value REAL NOT NULL,
    weight REAL NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (account_id, valuation_date, symbol)
);

CREATE TABLE IF NOT EXISTS nav_snapshots (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES paper_accounts(id) ON DELETE CASCADE,
    valuation_date TEXT NOT NULL,
    gross_nav REAL NOT NULL,
    net_nav REAL NOT NULL,
    cash REAL NOT NULL,
    daily_return REAL NOT NULL,
    cumulative_return REAL NOT NULL,
    drawdown REAL NOT NULL,
    running_max REAL NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (account_id, valuation_date)
);

CREATE TABLE IF NOT EXISTS data_quality_events (
    id INTEGER PRIMARY KEY,
    account_id INTEGER REFERENCES paper_accounts(id) ON DELETE CASCADE,
    strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    symbol TEXT,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

TABLES = frozenset(
    {
        "paper_accounts",
        "signal_snapshots",
        "signal_weights",
        "rebalance_events",
        "paper_trades",
        "position_snapshots",
        "nav_snapshots",
        "data_quality_events",
    }
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _date_text(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(db_path), timeout=5.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.row_factory = sqlite3.Row
    return conn


class PortfolioLedger:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with connect(self.db_path) as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = connect(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def _connection(
        self,
        conn: sqlite3.Connection | None,
    ) -> Iterator[sqlite3.Connection]:
        if conn is not None:
            yield conn
        else:
            with self.transaction() as owned:
                yield owned

    def get_or_create_account(
        self,
        config: StrategyConfig,
        *,
        bootstrap_signal_date: date | None = None,
        bootstrap_valuation_date: date | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> sqlite3.Row:
        if config.mode is not StrategyMode.PAPER:
            raise ComparisonStrategyError(
                f"{config.strategy_id} is comparison-only and cannot create a paper account"
            )
        with self._connection(conn) as active:
            active.execute(
                """
                INSERT INTO paper_accounts (
                    strategy_id, strategy_version, initial_nav, base_currency,
                    bootstrap_signal_date, bootstrap_valuation_date, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (strategy_id, strategy_version) DO UPDATE SET
                    bootstrap_signal_date = COALESCE(
                        paper_accounts.bootstrap_signal_date,
                        excluded.bootstrap_signal_date
                    ),
                    bootstrap_valuation_date = COALESCE(
                        paper_accounts.bootstrap_valuation_date,
                        excluded.bootstrap_valuation_date
                    )
                """,
                (
                    config.strategy_id,
                    config.version,
                    config.initial_nav,
                    config.base_currency,
                    _date_text(bootstrap_signal_date),
                    _date_text(bootstrap_valuation_date),
                    _utc_now(),
                ),
            )
            row = active.execute(
                """
                SELECT * FROM paper_accounts
                WHERE strategy_id = ? AND strategy_version = ?
                """,
                (config.strategy_id, config.version),
            ).fetchone()
            assert row is not None
            return row

    def get_account(
        self,
        config: StrategyConfig,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> sqlite3.Row | None:
        with self._connection(conn) as active:
            return active.execute(
                """
                SELECT * FROM paper_accounts
                WHERE strategy_id = ? AND strategy_version = ?
                """,
                (config.strategy_id, config.version),
            ).fetchone()

    def get_or_create_signal(
        self,
        account_id: int,
        config: StrategyConfig,
        *,
        signal_date: date,
        market_data_date: date,
        origin: str,
        state: str,
        reason: str,
        config_hash: str,
        input_hash: str,
        weights: Mapping[str, tuple[float, str, str]],
        conn: sqlite3.Connection | None = None,
    ) -> sqlite3.Row:
        with self._connection(conn) as active:
            active.execute(
                """
                INSERT INTO signal_snapshots (
                    account_id, strategy_id, strategy_version, signal_date,
                    market_data_date, origin, state, reason, config_hash,
                    input_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (strategy_id, strategy_version, signal_date)
                DO NOTHING
                """,
                (
                    account_id,
                    config.strategy_id,
                    config.version,
                    signal_date.isoformat(),
                    market_data_date.isoformat(),
                    origin,
                    state,
                    reason,
                    config_hash,
                    input_hash,
                    _utc_now(),
                ),
            )
            row = active.execute(
                """
                SELECT * FROM signal_snapshots
                WHERE strategy_id = ? AND strategy_version = ? AND signal_date = ?
                """,
                (config.strategy_id, config.version, signal_date.isoformat()),
            ).fetchone()
            assert row is not None
            for symbol, (weight, sleeve, weight_reason) in weights.items():
                active.execute(
                    """
                    INSERT INTO signal_weights (
                        signal_id, symbol, weight, sleeve, reason
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT (signal_id, symbol) DO NOTHING
                    """,
                    (row["id"], symbol, weight, sleeve, weight_reason),
                )
            return row

    def get_or_create_rebalance(
        self,
        account_id: int,
        signal_id: int,
        *,
        status: str,
        reason: str,
        execution_date: date | None = None,
        turnover: float | None = None,
        cost: float | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> sqlite3.Row:
        with self._connection(conn) as active:
            now = _utc_now()
            active.execute(
                """
                INSERT INTO rebalance_events (
                    account_id, signal_id, status, execution_date, turnover,
                    cost, reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (signal_id) DO NOTHING
                """,
                (
                    account_id,
                    signal_id,
                    status,
                    _date_text(execution_date),
                    turnover,
                    cost,
                    reason,
                    now,
                    now,
                ),
            )
            row = active.execute(
                "SELECT * FROM rebalance_events WHERE signal_id = ?",
                (signal_id,),
            ).fetchone()
            assert row is not None
            return row

    def get_or_create_trade(
        self,
        rebalance_event_id: int,
        *,
        symbol: str,
        side: str,
        price: float,
        weight_delta: float,
        gross_notional: float,
        fees: float,
        slippage: float,
        quantity_delta: float = 0.0,
        conn: sqlite3.Connection | None = None,
    ) -> sqlite3.Row:
        with self._connection(conn) as active:
            active.execute(
                """
                INSERT INTO paper_trades (
                    rebalance_event_id, symbol, side, price, weight_delta,
                    gross_notional, quantity_delta, fees, slippage, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (rebalance_event_id, symbol) DO NOTHING
                """,
                (
                    rebalance_event_id,
                    symbol,
                    side,
                    price,
                    weight_delta,
                    gross_notional,
                    quantity_delta,
                    fees,
                    slippage,
                    _utc_now(),
                ),
            )
            row = active.execute(
                """
                SELECT * FROM paper_trades
                WHERE rebalance_event_id = ? AND symbol = ?
                """,
                (rebalance_event_id, symbol),
            ).fetchone()
            assert row is not None
            return row

    def get_pending_rebalance(
        self,
        account_id: int,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> sqlite3.Row | None:
        with self._connection(conn) as active:
            return active.execute(
                """
                SELECT rebalance_events.*, signal_snapshots.signal_date
                FROM rebalance_events
                JOIN signal_snapshots
                  ON signal_snapshots.id = rebalance_events.signal_id
                WHERE rebalance_events.account_id = ?
                  AND rebalance_events.status = 'pending'
                ORDER BY signal_snapshots.signal_date, rebalance_events.id
                LIMIT 1
                """,
                (account_id,),
            ).fetchone()

    def get_signal_weights(
        self,
        signal_id: int,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> tuple[sqlite3.Row, ...]:
        with self._connection(conn) as active:
            return tuple(
                active.execute(
                    """
                    SELECT * FROM signal_weights
                    WHERE signal_id = ?
                    ORDER BY id
                    """,
                    (signal_id,),
                ).fetchall()
            )

    def update_rebalance(
        self,
        rebalance_id: int,
        *,
        status: str,
        execution_date: date,
        turnover: float,
        cost: float,
        reason: str,
        conn: sqlite3.Connection | None = None,
    ) -> sqlite3.Row:
        with self._connection(conn) as active:
            active.execute(
                """
                UPDATE rebalance_events
                SET status = ?, execution_date = ?, turnover = ?, cost = ?,
                    reason = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    execution_date.isoformat(),
                    turnover,
                    cost,
                    reason,
                    _utc_now(),
                    rebalance_id,
                ),
            )
            row = active.execute(
                "SELECT * FROM rebalance_events WHERE id = ?",
                (rebalance_id,),
            ).fetchone()
            assert row is not None
            return row

    def latest_positions(
        self,
        account_id: int,
        *,
        before_or_on: date | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> tuple[sqlite3.Row, ...]:
        with self._connection(conn) as active:
            condition = ""
            params: list[object] = [account_id]
            if before_or_on is not None:
                condition = "AND valuation_date <= ?"
                params.append(before_or_on.isoformat())
            valuation = active.execute(
                f"""
                SELECT MAX(valuation_date) FROM position_snapshots
                WHERE account_id = ? {condition}
                """,
                params,
            ).fetchone()[0]
            if valuation is None:
                return ()
            return tuple(
                active.execute(
                    """
                    SELECT * FROM position_snapshots
                    WHERE account_id = ? AND valuation_date = ?
                    ORDER BY id
                    """,
                    (account_id, valuation),
                ).fetchall()
            )

    def latest_nav(
        self,
        account_id: int,
        *,
        before: date | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> sqlite3.Row | None:
        with self._connection(conn) as active:
            if before is None:
                return active.execute(
                    """
                    SELECT * FROM nav_snapshots
                    WHERE account_id = ?
                    ORDER BY valuation_date DESC
                    LIMIT 1
                    """,
                    (account_id,),
                ).fetchone()
            return active.execute(
                """
                SELECT * FROM nav_snapshots
                WHERE account_id = ? AND valuation_date < ?
                ORDER BY valuation_date DESC
                LIMIT 1
                """,
                (account_id, before.isoformat()),
            ).fetchone()

    def save_position(
        self,
        account_id: int,
        *,
        valuation_date: date,
        symbol: str,
        quantity: float,
        price: float,
        value: float,
        weight: float,
        conn: sqlite3.Connection | None = None,
    ) -> sqlite3.Row:
        with self._connection(conn) as active:
            active.execute(
                """
                INSERT INTO position_snapshots (
                    account_id, valuation_date, symbol, quantity, price,
                    value, weight, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (account_id, valuation_date, symbol) DO UPDATE SET
                    quantity = excluded.quantity,
                    price = excluded.price,
                    value = excluded.value,
                    weight = excluded.weight
                """,
                (
                    account_id,
                    valuation_date.isoformat(),
                    symbol,
                    quantity,
                    price,
                    value,
                    weight,
                    _utc_now(),
                ),
            )
            row = active.execute(
                """
                SELECT * FROM position_snapshots
                WHERE account_id = ? AND valuation_date = ? AND symbol = ?
                """,
                (account_id, valuation_date.isoformat(), symbol),
            ).fetchone()
            assert row is not None
            return row

    def save_nav(
        self,
        account_id: int,
        *,
        valuation_date: date,
        gross_nav: float,
        net_nav: float,
        cash: float,
        daily_return: float,
        cumulative_return: float,
        drawdown: float,
        running_max: float,
        conn: sqlite3.Connection | None = None,
    ) -> sqlite3.Row:
        with self._connection(conn) as active:
            active.execute(
                """
                INSERT INTO nav_snapshots (
                    account_id, valuation_date, gross_nav, net_nav, cash,
                    daily_return, cumulative_return, drawdown, running_max,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (account_id, valuation_date) DO UPDATE SET
                    gross_nav = excluded.gross_nav,
                    net_nav = excluded.net_nav,
                    cash = excluded.cash,
                    daily_return = excluded.daily_return,
                    cumulative_return = excluded.cumulative_return,
                    drawdown = excluded.drawdown,
                    running_max = excluded.running_max
                """,
                (
                    account_id,
                    valuation_date.isoformat(),
                    gross_nav,
                    net_nav,
                    cash,
                    daily_return,
                    cumulative_return,
                    drawdown,
                    running_max,
                    _utc_now(),
                ),
            )
            row = active.execute(
                """
                SELECT * FROM nav_snapshots
                WHERE account_id = ? AND valuation_date = ?
                """,
                (account_id, valuation_date.isoformat()),
            ).fetchone()
            assert row is not None
            return row

    def count_rows(self, table: str) -> int:
        if table not in TABLES:
            raise ValueError(f"Unknown ledger table: {table}")
        with connect(self.db_path) as conn:
            return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    @staticmethod
    def encode_json(value: Mapping) -> str:
        return json.dumps(
            value,
            sort_keys=True,
            allow_nan=False,
            separators=(",", ":"),
        )
