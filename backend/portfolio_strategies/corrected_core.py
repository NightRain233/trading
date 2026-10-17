"""Causal IV20 signals and a raw-share, cash-distribution paper account.

Prices are domestic ETF prints, including any premium. Fractional shares and
payment after the modeled open are explicit research assumptions, not broker
settlement. This module has no database, download, or order submission side effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .event_ledger import payload_hash


CORE_SYMBOLS = ("510300.SS", "513100.SS", "518880.SS")
CORRECTED_CORE_ID = "risk_parity_core_cash_next_open"
ACTION_PATH = Path(__file__).with_name("core_corporate_actions.json")


def load_actions(path: Path | str = ACTION_PATH) -> dict:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    metadata = document["metadata"]
    if document.get("schema_version") != 1 or not metadata.get("coverage_limitations"):
        raise ValueError("Corporate-action scope and limitations must be explicit")
    date.fromisoformat(metadata["verified_through"])
    if len(metadata.get("source_sha256", "")) != 64:
        raise ValueError("Corporate-action source provenance is missing")
    actions = document["events"]
    if metadata.get("events_sha256") != payload_hash(actions):
        raise ValueError("Corporate-action events hash does not match the snapshot")
    ids = [e["event_id"] for e in actions]
    if len(ids) != len(set(ids)) or not all(ids):
        raise ValueError("Corporate-action IDs must be nonempty and unique")
    if len({(e["symbol"], e["corporate_action_date"]) for e in actions}) != len(actions):
        raise ValueError("Simultaneous actions require a separately reviewed accounting contract")
    for event in actions:
        if event["symbol"] not in CORE_SYMBOLS:
            raise ValueError("Unexpected corporate-action asset")
        effective = event["effective_quote_date"]
        if event["announcement_date"] >= effective:
            raise ValueError("Corporate-action availability must precede the event")
        if not np.isfinite(float(event["split_ratio"])) or float(event["split_ratio"]) <= 0:
            raise ValueError("Invalid split ratio")
        if not np.isfinite(float(event["cash_per_share"])) or float(event["cash_per_share"]) < 0:
            raise ValueError("Invalid cash distribution")
        if float(event["cash_per_share"]):
            if not (event["announcement_date"] <= event["record_date"] < effective <= event["pay_date"]):
                raise ValueError("Invalid cash distribution lifecycle")
        elif event["announcement_date"] >= event["corporate_action_date"]:
            raise ValueError("Split availability must precede conversion")
    return document


@dataclass
class CoreMarket:
    dates: pd.DatetimeIndex
    opening: np.ndarray
    closing: np.ndarray
    initial_weights: dict[str, list[float]]
    signals: dict[str, list[float]]
    actions_by_date: dict[str, list[tuple[str, dict]]]
    input_hashes: dict[str, str]


def prepare_core_market(frames: dict[str, pd.DataFrame], actions: list[dict], *,
                        anchor: str = "2015-01-05", window: int = 20,
                        interval: int = 10) -> CoreMarket:
    """Native total-return levels first, then sample on common close dates.

    A dividend affects only its ex-date return. It never adjusts earlier prices.
    Halt-day split marks and post-close quantity conversion are kept separate.
    """
    if set(frames) != set(CORE_SYMBOLS):
        raise ValueError("All three raw domestic ETF frames are required")
    common = None
    levels = {}
    native = {}
    for symbol in CORE_SYMBOLS:
        # Zero-volume placeholder OHLC is not evidence of an executable open.
        # Keep it out of both the signal calendar and the fill-price series.
        frame = frames[symbol].loc[frames[symbol].Volume > 0].sort_index()
        if frame.empty:
            raise ValueError(f"No tradable raw bars: {symbol}")
        if frame.index.has_duplicates:
            raise ValueError(f"Duplicate raw dates: {symbol}")
        close = frame.Close
        if not np.isfinite(close).all() or (close <= 0).any():
            raise ValueError(f"Invalid raw close: {symbol}")
        native[symbol] = frame
        common = frame.index if common is None else common.intersection(frame.index)
        returns = close.pct_change(fill_method=None)
        for event in actions:
            day = pd.Timestamp(event["effective_quote_date"])
            if event["symbol"] != symbol or day not in close.index:
                continue
            location = close.index.get_loc(day)
            if location:
                if event["announcement_date"] >= day.date().isoformat():
                    raise ValueError("Action was not available before its signal use")
                returns.loc[day] = (close.loc[day] * float(event["split_ratio"])
                                    + float(event["cash_per_share"])) / close.iloc[location-1] - 1
        levels[symbol] = (1 + returns.fillna(0)).cumprod()
    common = common.sort_values()
    anchor_day = pd.Timestamp(anchor)
    if anchor_day not in common:
        raise ValueError("Raw history must include the frozen 2015-01-05 schedule anchor")
    sampled = pd.DataFrame({s: levels[s].reindex(levels[s].index.union(common)).ffill().reindex(common)
                            for s in CORE_SYMBOLS})
    volatility = sampled.pct_change(fill_method=None).rolling(window).std(ddof=1)
    inverse = 1 / volatility
    weights = inverse.div(inverse.sum(axis=1), axis=0)
    valid = np.isfinite(weights).all(axis=1) & (volatility > 0).all(axis=1)
    initial = {d.date().isoformat(): weights.loc[common[i-1]].tolist()
               for i, d in enumerate(common) if i and bool(valid.loc[common[i-1]])}
    anchor_index = common.get_loc(anchor_day)
    signal_days = common[anchor_index::interval]
    if not bool(valid.loc[anchor_day]):
        raise ValueError("Insufficient pre-anchor IV20 warmup")
    signals = {d.date().isoformat(): weights.loc[d].tolist() for d in signal_days if bool(valid.loc[d])}
    # Stop at a common completed date: never extend a lagging symbol indefinitely.
    end = max(f.index[-1] for f in native.values())
    known_conversion_halts = {(e["symbol"], pd.Timestamp(e["corporate_action_date"]))
                              for e in actions if not float(e["cash_per_share"])}
    if not all(end in native[s].index or (s, end) in known_conversion_halts for s in CORE_SYMBOLS):
        end = common[-1]
    dates = pd.date_range(anchor_day, end)
    closes = pd.DataFrame({s: native[s].Close.reindex(native[s].index.union(dates)).ffill().reindex(dates)
                           for s in CORE_SYMBOLS})
    opens = pd.DataFrame({s: native[s].Open.reindex(dates) for s in CORE_SYMBOLS})
    events_by_date: dict[str, list[tuple[str, dict]]] = {}
    for event in actions:
        if float(event["cash_per_share"]):
            for phase, key in (("register", "record_date"), ("ex", "effective_quote_date"), ("pay", "pay_date")):
                events_by_date.setdefault(event[key], []).append((phase, event))
        else:
            day = event["corporate_action_date"]
            if pd.Timestamp(day) in native[event["symbol"]].index:
                raise ValueError("Split contract requires a halt on conversion date")
            if pd.Timestamp(day) in dates:
                # Carry converted marks across any intervening closed dates,
                # without using the eventual first quote's future price.
                mask = (dates >= pd.Timestamp(day)) & (dates < pd.Timestamp(event["effective_quote_date"]))
                closes.loc[mask, event["symbol"]] /= float(event["split_ratio"])
            events_by_date.setdefault(day, []).append(("split", event))
    if not np.isfinite(closes).all().all() or (closes <= 0).any().any():
        raise ValueError("Missing raw close marks")
    hashes = {}
    for i, day in enumerate(dates):
        text = day.date().isoformat()
        # Initial weights matter only on common dates; signal history is checked
        # separately so an earlier quote correction cannot silently restate a run.
        hashes[text] = payload_hash({
            "open": [float(v) if np.isfinite(v) else None for v in opens.iloc[i]],
            "close": closes.iloc[i].tolist(), "signal": signals.get(text),
            "initial": initial.get(text), "actions": events_by_date.get(text, []),
        })
    return CoreMarket(dates, opens.to_numpy(), closes.to_numpy(), initial, signals, events_by_date, hashes)


def initial_state() -> dict:
    return {"quantity": [0., 0., 0.], "cash": 0., "receivable": 0., "principal": 0.,
            "units": 0., "cumulative_cost": 0., "previous_wealth": 0., "previous_close": None,
            "unit_nav": 1., "peak": 1., "registered": {}, "pending_dividends": {},
            "target": None, "pending_signal": None, "last_signal": None,
            "last_execution": None, "last_date": None, "waiting_open": False}


def solve_literal_rebalance(values: np.ndarray, cash: float, target: np.ndarray,
                            fee: float) -> tuple[np.ndarray, float]:
    gross = float(values.sum() + cash)
    cost = 0.
    for _ in range(100):
        updated = float(np.abs((gross-cost)*target-values).sum()*fee)
        if abs(updated-cost) <= max(1e-9, gross*1e-14):
            return (gross-updated)*target, updated
        cost = updated
    raise ArithmeticError("Literal commission solver did not converge")


def advance_core_day(state: dict, market: CoreMarket, index: int, *, initial_cash: float = 0.,
                     deposit: float = 0., fee_bps: float = 1.) -> tuple[dict, dict, list[dict]]:
    """Apply one completed calendar day; state is copied, never partially mutated.

    Initial cash stays cash until a scheduled next-open execution. A deposit
    buys only new units using the last executed allocation, except on a normal
    scheduled rebalance. Receivables never supply purchasing power.
    """
    if not all(np.isfinite(v) and v >= 0 for v in (initial_cash, deposit, fee_bps)) or fee_bps >= 10000:
        raise ValueError("Invalid cash or commission")
    state = copy.deepcopy(state)
    day = market.dates[index].date().isoformat()
    if state["last_date"] is not None and day <= state["last_date"]:
        raise ValueError("Account dates must advance strictly")
    op, close = market.opening[index], market.closing[index]
    q = np.asarray(state["quantity"], dtype=float)
    old_q = q.copy()
    previous_close = np.asarray(state["previous_close"] if state["previous_close"] is not None else close)
    conversion_close = close.copy()
    income = 0.
    events = []
    day_actions = market.actions_by_date.get(day, [])
    for phase, event in day_actions:
        k, eid = CORE_SYMBOLS.index(event["symbol"]), event["event_id"]
        if phase == "split":
            conversion_close[k] *= float(event["split_ratio"])
        elif phase == "ex":
            amount = state["registered"].get(eid, 0.) * float(event["cash_per_share"])
            state["pending_dividends"][eid] = amount
            state["receivable"] += amount
            income += amount
            events.append({"type": "dividend_receivable", "eventId": eid, "symbol": event["symbol"], "amount": amount})
    valid_open = bool(np.isfinite(op).all() and (op > 0).all())
    flow = initial_cash + deposit
    if deposit and not valid_open:
        raise ValueError(f"No common opening for contribution on {day}")
    if flow:
        mark = op if valid_open else previous_close
        before = float(state["cash"] + q @ mark + state["receivable"])
        flow_price = before/state["units"] if state["units"] else 1.
        if flow_price <= 0:
            raise ValueError("Cannot issue account units at nonpositive equity")
        state["units"] += flow/flow_price
        state["principal"] += flow
        state["cash"] += flow
    else:
        flow_price = None
    if state["target"] is None and day in market.initial_weights:
        state["target"] = market.initial_weights[day]
    cost, changed = 0., False
    fee = fee_bps/10000
    pending = state["pending_signal"]
    due = pending is not None and pending["signal_date"] < day
    if due and valid_open:
        state["waiting_open"] = False
        state["target"] = pending["weights"]
        state["pending_signal"] = None
        state["last_execution"] = day
        if float(q.sum()) > 0 or state["cash"] > 0:
            target = np.asarray(state["target"])
            new_values, cost = solve_literal_rebalance(q*op, state["cash"], target, fee)
            q = new_values/op
            state["cash"] = 0.
            changed = True
            for k, symbol in enumerate(CORE_SYMBOLS):
                delta = float(q[k]-old_q[k])
                events.append({"type": "fill", "symbol": symbol, "quantity_delta": delta,
                               "price": float(op[k]), "notional": abs(delta)*float(op[k]),
                               "commission": abs(delta)*float(op[k])*fee, "fill_type": "rebalance",
                               "signal_date": pending["signal_date"]})
    elif deposit:
        if state["target"] is None:
            raise ValueError("No causal IV20 allocation available for the contribution")
        notional = deposit/(1+fee)
        delta = notional*np.asarray(state["target"])/op
        q += delta
        cost = deposit-notional
        state["cash"] -= deposit
        changed = True
        for k, symbol in enumerate(CORE_SYMBOLS):
            events.append({"type": "fill", "symbol": symbol, "quantity_delta": float(delta[k]),
                           "price": float(op[k]), "notional": float(delta[k]*op[k]),
                           "commission": float(delta[k]*op[k]*fee), "fill_type": "subscription",
                           "signal_date": state["last_signal"]})
    if due and not valid_open:
        state["waiting_open"] = True
        events.append({"type": "waiting_open", "signal_date": pending["signal_date"], "reason": "missing_common_open"})
    pnl_by_asset = old_q*(op-previous_close)+q*(conversion_close-op) if changed else old_q*(conversion_close-previous_close)
    pnl = float(pnl_by_asset.sum()+income)
    for phase, event in day_actions:
        k, eid = CORE_SYMBOLS.index(event["symbol"]), event["event_id"]
        if phase == "register":
            state["registered"][eid] = float(q[k])
            events.append({"type": "dividend_registration", "eventId": eid, "symbol": event["symbol"], "quantity": float(q[k])})
        elif phase == "pay":
            amount = state["pending_dividends"].pop(eid, 0.)
            state["cash"] += amount
            state["receivable"] -= amount
            events.append({"type": "dividend_payment", "eventId": eid, "symbol": event["symbol"], "amount": amount})
        elif phase == "split":
            q[k] *= float(event["split_ratio"])
            events.append({"type": "split", "eventId": eid, "symbol": event["symbol"], "quantity": float(q[k]), "ratio": event["split_ratio"]})
    # Close signals become eligible only at a strictly later opening.
    if day in market.signals and state["pending_signal"] is None:
        state["pending_signal"] = {"signal_date": day, "weights": market.signals[day]}
        state["last_signal"] = day
        events.append({"type": "signal", "weights": market.signals[day], "signal_date": day})
    state["cumulative_cost"] += cost
    wealth = float(state["cash"] + q@close + state["receivable"])
    residual = wealth-state["previous_wealth"]-flow-pnl+cost
    if abs(residual) > max(1e-7, wealth*1e-11) or state["cash"] < -1e-7 or state["receivable"] < -1e-7:
        raise ArithmeticError("Cash, receivable and P&L conservation failed")
    unit = wealth/state["units"] if state["units"] else 1.
    daily_return = unit/state["unit_nav"]-1
    state["peak"] = max(state["peak"], unit)
    liquidation = float(state["cash"]+state["receivable"]+q@close*(1-fee))
    row = {"wealth": wealth, "liquidation_wealth": liquidation, "principal": state["principal"],
           "contribution": flow, "cost": cost, "cumulative_cost": state["cumulative_cost"],
           "unit_nav": unit, "unit_drawdown": unit/state["peak"]-1, "daily_return": daily_return,
           "profit": liquidation-state["principal"], "market_pnl": pnl, "account_residual": residual,
           "pre_flow_unit_price": flow_price, "cash": state["cash"], "receivable": state["receivable"],
           "dividend_income": income, "available_liquidation": float(state["cash"]+q@close*(1-fee)),
           "quantity": q.tolist(), "prices": close.tolist(), "price_pnl": pnl_by_asset.tolist()}
    state.update(quantity=q.tolist(), previous_wealth=wealth, previous_close=close.tolist(),
                 unit_nav=unit, last_date=day)
    return state, row, events
