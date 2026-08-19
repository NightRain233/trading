from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json
import math
from collections.abc import Mapping

import pandas as pd

from .ledger import PortfolioLedger
from .event_ledger import EventPortfolioLedger
from .market_data import PortfolioMarketData
from .models import StrategyCalculation, StrategyConfig
from .schedules import xshg_sessions


class PaperAccountNotFoundError(LookupError):
    pass


def _hash_payload(value: Mapping) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        allow_nan=False,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _config_hash(config: StrategyConfig) -> str:
    return _hash_payload(
        {
            "strategy_id": config.strategy_id,
            "version": config.version,
            "execution": config.execution,
            "params": dict(config.params),
            "costs": {
                "base_bps": config.costs.base_bps,
                "slippage_bps": config.costs.slippage_bps,
                "asset_extra_bps": dict(config.costs.asset_extra_bps),
            },
        }
    )


def _calculation_weights(
    calculation: StrategyCalculation,
) -> dict[str, tuple[float, str, str]]:
    weights = {
        item.symbol: (float(item.weight), item.sleeve, item.reason)
        for item in calculation.target_weights
    }
    values = [item[0] for item in weights.values()]
    if not values or any(
        not math.isfinite(weight) or weight < 0.0 for weight in values
    ):
        raise ValueError("Target weights must be finite and nonnegative")
    if not math.isclose(sum(values), 1.0, abs_tol=1e-10):
        raise ValueError("Target weights must sum to one")
    return weights


def _input_hash(calculation: StrategyCalculation) -> str:
    return _hash_payload(
        {
            "market_data_date": calculation.market_data_date.isoformat(),
            "signal_date": (
                calculation.signal_date.isoformat()
                if calculation.signal_date is not None
                else None
            ),
            "state": calculation.state.value,
            "weights": {
                symbol: weight
                for symbol, (weight, _sleeve, _reason) in (
                    _calculation_weights(calculation).items()
                )
            },
        }
    )


def _row_dict(row) -> dict:
    return dict(row) if row is not None else {}


class PortfolioPaperEngine:
    def __init__(self, ledger: PortfolioLedger):
        self.ledger = ledger
        self.events = EventPortfolioLedger(ledger)

    def activate_cash(
        self,
        config: StrategyConfig,
        *,
        activation_date: date,
    ) -> dict:
        """Create an explicit first-live cash account without historical trades."""
        with self.ledger.transaction() as conn:
            activation = self.events.activate(
                config,
                activation_date=activation_date,
                metadata={
                    "mode": "cash_then_next_signal",
                    "accountOrigin": "first_activation",
                    "historicalContinuation": False,
                    "historicalTradesBackfilled": False,
                },
                conn=conn,
            )
            account = self.ledger.get_account(config, conn=conn)
            assert account is not None
            existing = self.ledger.latest_nav(account["id"], conn=conn)
            if existing is None:
                self.ledger.save_position(
                    account["id"],
                    valuation_date=activation_date,
                    symbol="CASH",
                    quantity=float(config.initial_nav),
                    price=1.0,
                    value=float(config.initial_nav),
                    weight=1.0,
                    conn=conn,
                )
                self.ledger.save_nav(
                    account["id"],
                    valuation_date=activation_date,
                    gross_nav=float(config.initial_nav),
                    net_nav=float(config.initial_nav),
                    cash=float(config.initial_nav),
                    daily_return=0.0,
                    cumulative_return=0.0,
                    drawdown=0.0,
                    running_max=float(config.initial_nav),
                    conn=conn,
                )
            return dict(activation)

    def _price(
        self,
        market_data: PortfolioMarketData,
        valuation_date: date,
        symbol: str,
    ) -> float:
        timestamp = pd.Timestamp(valuation_date)
        if timestamp not in market_data.close.index or symbol not in market_data.close:
            raise ValueError(f"Missing close for {symbol} on {valuation_date}")
        price = float(market_data.close.at[timestamp, symbol])
        if not math.isfinite(price) or price <= 0.0:
            raise ValueError(f"Invalid close for {symbol} on {valuation_date}")
        return price

    def _save_snapshot(
        self,
        conn,
        account,
        config: StrategyConfig,
        market_data: PortfolioMarketData,
        valuation_date: date,
        quantities: Mapping[str, float],
        cash: float,
        *,
        gross_nav: float | None = None,
    ) -> dict:
        asset_values = {
            symbol: float(quantities.get(symbol, 0.0))
            * self._price(market_data, valuation_date, symbol)
            for symbol in config.symbols
        }
        net_nav = sum(asset_values.values()) + float(cash)
        if net_nav <= 0.0 or not math.isfinite(net_nav):
            raise ValueError("Paper NAV must remain finite and positive")
        gross = net_nav if gross_nav is None else float(gross_nav)

        for symbol in config.symbols:
            price = self._price(market_data, valuation_date, symbol)
            value = asset_values[symbol]
            self.ledger.save_position(
                account["id"],
                valuation_date=valuation_date,
                symbol=symbol,
                quantity=float(quantities.get(symbol, 0.0)),
                price=price,
                value=value,
                weight=value / net_nav,
                conn=conn,
            )
        self.ledger.save_position(
            account["id"],
            valuation_date=valuation_date,
            symbol="CASH",
            quantity=float(cash),
            price=1.0,
            value=float(cash),
            weight=float(cash) / net_nav,
            conn=conn,
        )

        previous = self.ledger.latest_nav(
            account["id"],
            before=valuation_date,
            conn=conn,
        )
        previous_nav = (
            float(previous["net_nav"])
            if previous is not None
            else float(account["initial_nav"])
        )
        daily_return = net_nav / previous_nav - 1.0 if previous is not None else 0.0
        cumulative_return = net_nav / float(account["initial_nav"]) - 1.0
        previous_max = (
            float(previous["running_max"])
            if previous is not None
            else float(account["initial_nav"])
        )
        running_max = max(previous_max, net_nav)
        drawdown = net_nav / running_max - 1.0
        nav = self.ledger.save_nav(
            account["id"],
            valuation_date=valuation_date,
            gross_nav=gross,
            net_nav=net_nav,
            cash=float(cash),
            daily_return=daily_return,
            cumulative_return=cumulative_return,
            drawdown=drawdown,
            running_max=running_max,
            conn=conn,
        )
        return _row_dict(nav)

    def bootstrap(
        self,
        config: StrategyConfig,
        calculation: StrategyCalculation,
        market_data: PortfolioMarketData,
        valuation_date: date,
    ) -> dict:
        if calculation.signal_date is None:
            raise ValueError("Bootstrap requires an originating formal signal")
        weights = _calculation_weights(calculation)
        with self.ledger.transaction() as conn:
            account = self.ledger.get_or_create_account(
                config,
                bootstrap_signal_date=calculation.signal_date,
                bootstrap_valuation_date=valuation_date,
                conn=conn,
            )
            existing = self.ledger.latest_nav(account["id"], conn=conn)
            if existing is not None:
                return {
                    "status": "BOOTSTRAPPED",
                    "account_id": account["id"],
                    "nav_id": existing["id"],
                }

            self.ledger.get_or_create_signal(
                account["id"],
                config,
                signal_date=calculation.signal_date,
                market_data_date=calculation.market_data_date,
                origin="bootstrap",
                state=calculation.state.value,
                reason=calculation.observation.reason,
                config_hash=_config_hash(config),
                input_hash=_input_hash(calculation),
                weights=weights,
                conn=conn,
            )
            quantities = {}
            for symbol in config.symbols:
                target_weight = weights.get(symbol, (0.0, "", ""))[0]
                quantities[symbol] = (
                    float(account["initial_nav"])
                    * target_weight
                    / self._price(market_data, valuation_date, symbol)
                )
            cash = float(account["initial_nav"]) * weights.get(
                "CASH", (0.0, "", "")
            )[0]
            nav = self._save_snapshot(
                conn,
                account,
                config,
                market_data,
                valuation_date,
                quantities,
                cash,
            )
            return {
                "status": "BOOTSTRAPPED",
                "account_id": account["id"],
                "nav_id": nav["id"],
            }

    def queue_signal(
        self,
        config: StrategyConfig,
        calculation: StrategyCalculation,
    ) -> dict:
        if calculation.signal_date is None:
            raise ValueError("A formal signal date is required")
        weights = _calculation_weights(calculation)
        with self.ledger.transaction() as conn:
            account = self.ledger.get_account(config, conn=conn)
            if account is None:
                raise PaperAccountNotFoundError(config.strategy_id)
            signal = self.ledger.get_or_create_signal(
                account["id"],
                config,
                signal_date=calculation.signal_date,
                market_data_date=calculation.market_data_date,
                origin="live",
                state=calculation.state.value,
                reason=calculation.observation.reason,
                config_hash=_config_hash(config),
                input_hash=_input_hash(calculation),
                weights=weights,
                conn=conn,
            )
            event = self.ledger.get_or_create_rebalance(
                account["id"],
                signal["id"],
                status="pending",
                reason="Waiting for the next complete ETF close",
                conn=conn,
            )
            return _row_dict(event)

    def _execution_date(
        self,
        signal_date: date,
        market_data: PortfolioMarketData,
    ) -> date | None:
        if market_data.market_data_date is None:
            return None
        expected = xshg_sessions(
            signal_date + timedelta(days=1),
            market_data.market_data_date,
        )
        if expected.empty:
            return None
        next_session = expected[0]
        observed = pd.DatetimeIndex(market_data.sessions).normalize()
        return next_session.date() if next_session in observed else None

    def _current_state(
        self,
        conn,
        account,
        config: StrategyConfig,
        market_data: PortfolioMarketData,
        valuation_date: date,
    ) -> tuple[dict[str, float], dict[str, float], float, float]:
        positions = self.ledger.latest_positions(
            account["id"],
            before_or_on=valuation_date,
            conn=conn,
        )
        if not positions:
            raise PaperAccountNotFoundError("Paper account has no positions")
        quantities = {
            row["symbol"]: float(row["quantity"])
            for row in positions
            if row["symbol"] != "CASH"
        }
        cash_row = next(
            (row for row in positions if row["symbol"] == "CASH"),
            None,
        )
        cash = float(cash_row["quantity"]) if cash_row is not None else 0.0
        values = {
            symbol: quantities.get(symbol, 0.0)
            * self._price(market_data, valuation_date, symbol)
            for symbol in config.symbols
        }
        gross_nav = sum(values.values()) + cash
        if gross_nav <= 0.0:
            raise ValueError("Paper account has no positive NAV")
        weights = {symbol: value / gross_nav for symbol, value in values.items()}
        weights["CASH"] = cash / gross_nav
        return quantities, values, cash, gross_nav

    def _desired_weights(
        self,
        conn,
        signal_id: int,
        config: StrategyConfig,
    ) -> dict[str, float]:
        rows = self.ledger.get_signal_weights(signal_id, conn=conn)
        desired = {symbol: 0.0 for symbol in config.symbols}
        desired["CASH"] = 0.0
        for row in rows:
            desired[row["symbol"]] = float(row["weight"])
        if not math.isclose(sum(desired.values()), 1.0, abs_tol=1e-10):
            raise ValueError("Stored signal weights do not sum to one")
        return desired

    def _should_execute(
        self,
        config: StrategyConfig,
        current: Mapping[str, float],
        desired: Mapping[str, float],
    ) -> tuple[bool, float]:
        symbols = (*config.symbols, "CASH")
        turnover = 0.5 * sum(
            abs(desired.get(symbol, 0.0) - current.get(symbol, 0.0))
            for symbol in symbols
        )
        threshold = float(config.params["rebalance_threshold"])
        if config.strategy_id.startswith("btc_supertrend_satellite"):
            switched = (
                current.get("BTC-USD", 0.0) > 1e-12
            ) != (desired.get("BTC-USD", 0.0) > 1e-12)
            max_change = max(
                abs(desired.get(symbol, 0.0) - current.get(symbol, 0.0))
                for symbol in symbols
            )
            return switched or max_change >= threshold - 1e-12, turnover
        return turnover >= threshold - 1e-12, turnover

    def _executable_weights(
        self,
        config: StrategyConfig,
        current: Mapping[str, float],
        desired: Mapping[str, float],
    ) -> dict[str, float]:
        max_trade = config.params.get("max_asset_trade")
        if max_trade is None:
            return dict(desired)
        cap = float(max_trade)
        assets = {
            symbol: max(
                0.0,
                current.get(symbol, 0.0)
                + min(
                    cap,
                    max(
                        -cap,
                        desired.get(symbol, 0.0)
                        - current.get(symbol, 0.0),
                    ),
                ),
            )
            for symbol in config.symbols
        }
        total = sum(assets.values())
        if total > 1.0:
            assets = {symbol: weight / total for symbol, weight in assets.items()}
            total = 1.0
        assets["CASH"] = 1.0 - total
        return assets

    def _solve_execution(
        self,
        config: StrategyConfig,
        current_values: Mapping[str, float],
        gross_nav: float,
        executable: Mapping[str, float],
    ) -> tuple[float, dict[str, float], dict[str, tuple[float, float, float]]]:
        net_nav = gross_nav
        target_values: dict[str, float] = {}
        costs: dict[str, tuple[float, float, float]] = {}
        for _ in range(100):
            target_values = {
                symbol: executable.get(symbol, 0.0) * net_nav
                for symbol in config.symbols
            }
            costs = {}
            total_cost = 0.0
            for symbol in config.symbols:
                notional = abs(
                    target_values[symbol] - current_values.get(symbol, 0.0)
                )
                fee = notional * (
                    config.costs.base_bps + config.costs.extra_bps(symbol)
                ) / 10_000.0
                slippage = (
                    notional * config.costs.slippage_bps / 10_000.0
                )
                costs[symbol] = (notional, fee, slippage)
                total_cost += fee + slippage
            updated = gross_nav - total_cost
            if abs(updated - net_nav) <= 0.005:
                net_nav = updated
                break
            net_nav = updated
        target_values = {
            symbol: executable.get(symbol, 0.0) * net_nav
            for symbol in config.symbols
        }
        return net_nav, target_values, costs

    def reconcile(
        self,
        config: StrategyConfig,
        market_data: PortfolioMarketData,
    ) -> dict:
        with self.ledger.transaction() as conn:
            account = self.ledger.get_account(config, conn=conn)
            if account is None:
                raise PaperAccountNotFoundError(config.strategy_id)
            event = self.ledger.get_pending_rebalance(account["id"], conn=conn)
            if event is None:
                return {"status": "idle"}
            signal_date = date.fromisoformat(event["signal_date"])
            execution_date = self._execution_date(signal_date, market_data)
            if execution_date is None:
                return _row_dict(event)

            quantities, current_values, cash, gross_nav = self._current_state(
                conn,
                account,
                config,
                market_data,
                execution_date,
            )
            current_weights = {
                symbol: value / gross_nav
                for symbol, value in current_values.items()
            }
            current_weights["CASH"] = cash / gross_nav
            desired = self._desired_weights(conn, event["signal_id"], config)
            should_execute, turnover = self._should_execute(
                config,
                current_weights,
                desired,
            )
            if not should_execute:
                self._save_snapshot(
                    conn,
                    account,
                    config,
                    market_data,
                    execution_date,
                    quantities,
                    cash,
                )
                skipped = self.ledger.update_rebalance(
                    event["id"],
                    status="skipped",
                    execution_date=execution_date,
                    turnover=turnover,
                    cost=0.0,
                    reason="Target change is below the rebalance threshold",
                    conn=conn,
                )
                return _row_dict(skipped)

            executable = self._executable_weights(
                config,
                current_weights,
                desired,
            )
            net_nav, target_values, cost_rows = self._solve_execution(
                config,
                current_values,
                gross_nav,
                executable,
            )
            target_quantities = {
                symbol: target_values[symbol]
                / self._price(market_data, execution_date, symbol)
                for symbol in config.symbols
            }
            total_cost = 0.0
            for symbol in config.symbols:
                notional, fee, slippage = cost_rows[symbol]
                if notional <= 1e-8:
                    continue
                quantity_delta = (
                    target_quantities[symbol] - quantities.get(symbol, 0.0)
                )
                weight_delta = (
                    executable.get(symbol, 0.0)
                    - current_weights.get(symbol, 0.0)
                )
                self.ledger.get_or_create_trade(
                    event["id"],
                    symbol=symbol,
                    side="BUY" if quantity_delta > 0.0 else "SELL",
                    price=self._price(market_data, execution_date, symbol),
                    weight_delta=weight_delta,
                    gross_notional=notional,
                    fees=fee,
                    slippage=slippage,
                    quantity_delta=quantity_delta,
                    conn=conn,
                )
                total_cost += fee + slippage

            target_cash = executable["CASH"] * net_nav
            self._save_snapshot(
                conn,
                account,
                config,
                market_data,
                execution_date,
                target_quantities,
                target_cash,
                gross_nav=gross_nav,
            )
            executed = self.ledger.update_rebalance(
                event["id"],
                status="executed",
                execution_date=execution_date,
                turnover=turnover,
                cost=total_cost,
                reason="Executed at the next complete ETF close",
                conn=conn,
            )
            return _row_dict(executed)

    def value(
        self,
        config: StrategyConfig,
        market_data: PortfolioMarketData,
        valuation_date: date,
    ) -> dict:
        with self.ledger.transaction() as conn:
            account = self.ledger.get_account(config, conn=conn)
            if account is None:
                raise PaperAccountNotFoundError(config.strategy_id)
            quantities, _values, cash, _gross_nav = self._current_state(
                conn,
                account,
                config,
                market_data,
                valuation_date,
            )
            return self._save_snapshot(
                conn,
                account,
                config,
                market_data,
                valuation_date,
                quantities,
                cash,
            )
