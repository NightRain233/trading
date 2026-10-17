from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
import hashlib
import json

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from portfolio_strategies.api_models import ActivateRequest, DepositRequest, SnapshotResponse, NavSeriesResponse
from portfolio_strategies.corrected_core import (CORE_SYMBOLS, CORRECTED_CORE_ID, CoreMarket,
    advance_core_day, initial_state, load_actions, prepare_core_market, solve_literal_rebalance)
from portfolio_strategies.core_raw_data import CORE_RAW_PRICE_IDENTIFIER, load_core_raw_frames
from portfolio_strategies.ledger import connect
from portfolio_strategies.registry import get_strategy
from portfolio_strategies.models import CostConfig
from portfolio_strategies.service import PortfolioStrategyService


def frames(end="2015-02-10"):
    days = pd.bdate_range("2014-10-01", end)
    result = {}
    for k, symbol in enumerate(CORE_SYMBOLS):
        moves = .001 + .003*np.sin(np.arange(len(days))*(.7+k*.13))
        close = (10+k)*np.cumprod(1+moves)
        result[symbol] = pd.DataFrame({"Open": close*.999, "High": close*1.01,
            "Low": close*.99, "Close": close, "Volume": 1000.}, index=days)
    return result


def write_raw(data_dir, inputs):
    root = data_dir/"core_raw"
    root.mkdir(parents=True, exist_ok=True)
    symbols = {}
    for symbol, f in inputs.items():
        file = root/f"{symbol}.parquet"
        f.to_parquet(file)
        symbols[symbol] = {"file": file.name, "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
            "source": "synthetic fixture", "provenance": "explicit raw fixture", "adjustment": "none"}
    manifest = {"schema_version": 1, "adjustment": "none", "raw_price_identifier": CORE_RAW_PRICE_IDENTIFIER,
        "imported_at": "2026-10-05T00:00:00+00:00", "symbols": symbols,
        "source": {"sha256": "1"*64, "fetch_log_sha256": "2"*64, "requested_adjustment": "none"}}
    (root/"manifest.json").write_text(json.dumps(manifest))
    return root


def market(days, opens, closes, *, actions=None, signals=None):
    dates = pd.DatetimeIndex(days)
    return CoreMarket(dates, np.asarray(opens, dtype=float), np.asarray(closes, dtype=float),
                      {d.date().isoformat(): [1., 0., 0.] for d in dates}, signals or {}, actions or {}, {})


def funded_state(quantity=(100., 0., 0.), prices=(10., 10., 10.)):
    state = initial_state()
    wealth = float(np.asarray(quantity)@np.asarray(prices))
    state.update(quantity=list(quantity), principal=wealth, units=wealth, previous_wealth=wealth,
                 previous_close=list(prices), target=[1., 0., 0.])
    return state


def test_registered_holder_keeps_dividend_after_ex_date_sale_and_payment_is_after_open():
    action = {"event_id": "div", "symbol": CORE_SYMBOLS[0], "cash_per_share": 1., "split_ratio": 1.}
    m = market(["2015-01-05", "2015-01-06", "2015-01-07", "2015-01-08"],
        [[10., 10., 10.], [9., 10., 10.], [9., 10., 10.], [9., 10., 10.]],
        [[10., 10., 10.], [9., 10., 10.], [9., 10., 10.], [9., 10., 10.]],
        actions={"2015-01-05": [("register", action)], "2015-01-06": [("ex", action)], "2015-01-07": [("pay", action)]},
        signals={"2015-01-05": [0., 0., 1.], "2015-01-07": [0., 0., 1.]})
    state, _, _ = advance_core_day(funded_state(), m, 0, fee_bps=0)
    state, row, _ = advance_core_day(state, m, 1, fee_bps=0)
    assert state["quantity"] == pytest.approx([0, 0, 90])
    assert row["receivable"] == 100
    assert row["wealth"] == 1000
    state, row, events = advance_core_day(state, m, 2, deposit=200, fee_bps=0)
    assert row["cash"] == 100  # payment did not fund this day's opening purchase
    assert state["quantity"][2] == 110
    assert sum(e["notional"] for e in events if e["type"] == "fill") == 200
    assert row["unit_nav"] == 1
    state, row, _ = advance_core_day(state, m, 3, fee_bps=0)
    assert row["cash"] == 0 and state["quantity"][2] == 120


def test_ex_date_new_buyer_has_no_prior_registered_entitlement():
    event = {"event_id": "div", "symbol": CORE_SYMBOLS[0], "cash_per_share": 1., "split_ratio": 1.}
    m = market(["2015-01-06"], [[9., 10., 10.]], [[9., 10., 10.]], actions={"2015-01-06": [("ex", event)]})
    _, row, _ = advance_core_day(initial_state(), m, 0, deposit=900, fee_bps=0)
    assert row["receivable"] == 0 and row["dividend_income"] == 0
    assert row["quantity"] == [100, 0, 0]


def test_split_during_halt_preserves_wealth_then_uses_raw_post_split_price():
    event = {"event_id": "split", "symbol": CORE_SYMBOLS[0], "cash_per_share": 0., "split_ratio": 5.}
    m = market(["2015-01-06", "2015-01-07"], [[np.nan]*3, [2., 10., 10.]],
        [[2., 10., 10.], [2.1, 10., 10.]], actions={"2015-01-06": [("split", event)]})
    state, row, _ = advance_core_day(funded_state(), m, 0)
    assert state["quantity"][0] == 500
    assert row["wealth"] == 1000 and row["market_pnl"] == 0
    _, row, _ = advance_core_day(state, m, 1)
    assert row["wealth"] == 1050 and row["market_pnl"] == pytest.approx(50)


def test_deposit_only_buys_new_cash_and_unit_return_excludes_the_flow():
    m = market(["2015-01-06"], [[20., 10., 10.]], [[20., 10., 10.]])
    state = funded_state((50., 30., 20.), (20., 10., 10.))
    state["target"] = [1/3]*3
    after, row, events = advance_core_day(state, m, 0, deposit=300, fee_bps=0)
    assert after["quantity"] == pytest.approx([55., 40., 30.])
    assert row["wealth"] == 1800 and row["principal"] == 1800
    assert row["unit_nav"] == 1 and row["daily_return"] == 0
    assert all(e["quantity_delta"] >= 0 for e in events if e["type"] == "fill")
    assert state["quantity"] == [50, 30, 20]  # input was not mutated


def test_literal_cost_is_buy_and_sell_not_half_turnover():
    values = np.asarray([800., 200., 0.])
    target = np.asarray([.2, .3, .5])
    after, fee = solve_literal_rebalance(values, 100., target, .001)
    assert fee == pytest.approx(np.abs(after-values).sum()*.001, abs=1e-9)
    assert after.sum()+fee == pytest.approx(1100)


def test_missing_open_waits_and_signal_never_trades_same_day():
    m = market(["2015-01-05", "2015-01-06", "2015-01-07"],
        [[10.]*3, [np.nan]*3, [12.]*3], [[10.]*3, [10.]*3, [12.]*3],
        signals={"2015-01-05": [1/3]*3})
    state, _, events = advance_core_day(initial_state(), m, 0, initial_cash=1000, fee_bps=0)
    assert not any(e["type"] == "fill" for e in events)
    state, _, events = advance_core_day(state, m, 1, fee_bps=0)
    assert state["cash"] == 1000 and events[0]["type"] == "waiting_open"
    _, _, events = advance_core_day(state, m, 2, fee_bps=0)
    assert all(e["price"] == 12 for e in events if e["type"] == "fill")


def test_future_distribution_cannot_restate_past_signals():
    inputs = frames()
    before = prepare_core_market(inputs, [])
    action = {"event_id": "future", "symbol": CORE_SYMBOLS[0], "cash_per_share": .5, "split_ratio": 1.,
        "announcement_date": "2015-02-02", "record_date": "2015-02-06", "corporate_action_date": "2015-02-09",
        "effective_quote_date": "2015-02-09", "pay_date": "2015-02-10"}
    after = prepare_core_market(inputs, [action])
    assert {d:w for d,w in before.signals.items() if d < "2015-02-09"} == {
        d:w for d,w in after.signals.items() if d < "2015-02-09"}


@pytest.fixture
def service(tmp_path):
    write_raw(tmp_path/"data", frames())
    return PortfolioStrategyService(data_dir=tmp_path/"data", db_path=tmp_path/"paper.sqlite",
                                   clock=lambda: datetime(2015, 2, 10, 22))


def test_activation_get_and_refresh_are_isolated_and_idempotent(service):
    assert service.get_snapshot(CORRECTED_CORE_ID)["state"] == "EMPTY"
    assert service.refresh(CORRECTED_CORE_ID)["state"] == "EMPTY"
    assert service.ledger.get_account(get_strategy(CORRECTED_CORE_ID)) is None
    service.activate(CORRECTED_CORE_ID, activation_date=date(2015, 1, 5), initial_cash=50000)
    service.activate(CORRECTED_CORE_ID, activation_date=date(2015, 1, 5), initial_cash=50000)
    first = service.refresh(CORRECTED_CORE_ID)
    assert first["state"] != "BLOCKED", first
    second = service.refresh(CORRECTED_CORE_ID)
    assert first == second
    SnapshotResponse.model_validate(second)
    NavSeriesResponse.model_validate(service.nav_series(CORRECTED_CORE_ID))
    assert service.ledger.get_account(get_strategy("risk_parity_core_next_open")) is None
    with pytest.raises(ValueError, match="different initialCash"):
        service.activate(CORRECTED_CORE_ID, activation_date=date(2015, 1, 5), initial_cash=100000)
    with connect(service.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM corrected_core_days").fetchone()[0] == 37
        assert conn.execute("SELECT COUNT(*) FROM portfolio_nav_v2").fetchone()[0] == 0


def test_deposit_idempotency_and_processed_history_cannot_be_changed(service):
    service.activate(CORRECTED_CORE_ID, activation_date=date(2015, 1, 5), initial_cash=0)
    kwargs = dict(contribution_date=date(2015, 1, 5), amount=10000, idempotency_key="2015-01")
    first = service.deposit(CORRECTED_CORE_ID, **kwargs)
    assert first == service.deposit(CORRECTED_CORE_ID, **kwargs)
    with pytest.raises(ValueError, match="different deposit"):
        service.deposit(CORRECTED_CORE_ID, **(kwargs | {"amount": 20000}))
    result = service.refresh(CORRECTED_CORE_ID)
    assert result["nav"]["principal"] == 10000
    assert service.deposits(CORRECTED_CORE_ID)["deposits"][0]["status"] == "posted"
    assert first["deposits"][0]["status"] == "pending"
    assert service.deposit(CORRECTED_CORE_ID, **kwargs)["deposits"][0]["status"] == "posted"
    with pytest.raises(ValueError, match="processed date"):
        service.deposit(CORRECTED_CORE_ID, **(kwargs | {"idempotency_key": "other"}))


def test_continuation_and_single_catchup_are_equivalent(service, tmp_path):
    other_data = tmp_path/"other_data"
    write_raw(other_data, frames())
    other = PortfolioStrategyService(data_dir=other_data, db_path=tmp_path/"other.sqlite")
    for s in (service, other):
        s.activate(CORRECTED_CORE_ID, activation_date=date(2015, 1, 5), initial_cash=50000, now=datetime(2015, 2, 10, 22))
    service.refresh(CORRECTED_CORE_ID, now=datetime(2015, 1, 20, 22))
    service.refresh(CORRECTED_CORE_ID, now=datetime(2015, 2, 10, 22))
    other.refresh(CORRECTED_CORE_ID, now=datetime(2015, 2, 10, 22))
    assert service.nav_series(CORRECTED_CORE_ID) == other.nav_series(CORRECTED_CORE_ID)


def test_audited_price_change_blocks_without_overwriting_history(service):
    service.activate(CORRECTED_CORE_ID, activation_date=date(2015, 1, 5))
    service.refresh(CORRECTED_CORE_ID, now=datetime(2015, 1, 20, 22))
    baseline = service.nav_series(CORRECTED_CORE_ID)
    changed = frames()
    changed[CORE_SYMBOLS[0]].loc["2015-01-06", "Close"] *= 1.002
    write_raw(service.data_dir, changed)
    blocked = service.refresh(CORRECTED_CORE_ID)
    assert blocked["state"] == "BLOCKED"
    assert "Previously processed" in blocked["calcError"]
    assert service.nav_series(CORRECTED_CORE_ID) == baseline


def test_loader_rejects_adjusted_or_hash_changed_snapshot(tmp_path):
    root = write_raw(tmp_path, frames())
    file = root/"manifest.json"
    manifest = json.loads(file.read_text()); manifest["adjustment"] = "forward_additive"
    file.write_text(json.dumps(manifest))
    assert load_core_raw_frames(tmp_path)[1]
    manifest["adjustment"] = "none"; file.write_text(json.dumps(manifest))
    with (root/f"{CORE_SYMBOLS[0]}.parquet").open("ab") as handle:
        handle.write(b"changed")
    assert "SHA256 mismatch" in load_core_raw_frames(tmp_path)[1][CORE_SYMBOLS[0]]


def test_future_dated_deposit_is_pending_until_its_completed_open_exists(service):
    service.activate(CORRECTED_CORE_ID, activation_date=date(2015, 1, 5), initial_cash=50000)
    service.refresh(CORRECTED_CORE_ID)
    result = service.deposit(CORRECTED_CORE_ID, contribution_date=date(2015, 2, 11), amount=3000, idempotency_key="next")
    assert result["deposits"][0]["status"] == "pending"
    assert service.refresh(CORRECTED_CORE_ID)["nav"]["principal"] == 50000
    write_raw(service.data_dir, frames("2015-02-11"))
    result = service.refresh(CORRECTED_CORE_ID, now=datetime(2015, 2, 11, 22))
    assert result["nav"]["principal"] == 53000 and result["state"] != "BLOCKED"
    assert service.deposits(CORRECTED_CORE_ID)["deposits"][0]["status"] == "posted"


def test_stale_raw_snapshot_is_blocked_and_does_not_claim_updated_nav(service):
    service.activate(CORRECTED_CORE_ID, activation_date=date(2015, 1, 5))
    service.refresh(CORRECTED_CORE_ID)
    baseline = service.nav_series(CORRECTED_CORE_ID)
    result = service.refresh(CORRECTED_CORE_ID, now=datetime(2015, 3, 2, 22))
    assert result["state"] == "BLOCKED"
    assert result["diagnostics"][0]["code"] == "RAW_SNAPSHOT_STALE"
    assert service.nav_series(CORRECTED_CORE_ID) == baseline


def test_same_version_fee_changes_are_detected_by_audited_contract_hash(service):
    service.activate(CORRECTED_CORE_ID, activation_date=date(2015, 1, 5))
    service.refresh(CORRECTED_CORE_ID)
    baseline = service.nav_series(CORRECTED_CORE_ID)
    changed = replace(get_strategy(CORRECTED_CORE_ID), costs=CostConfig(base_bps=10))
    result = service.corrected_core.refresh(changed, datetime(2015, 2, 10, 22))
    assert result["state"] == "BLOCKED"
    assert service.nav_series(CORRECTED_CORE_ID) == baseline


def test_mutated_historical_cash_flow_is_detected(service):
    service.activate(CORRECTED_CORE_ID, activation_date=date(2015, 1, 5), initial_cash=0)
    service.deposit(CORRECTED_CORE_ID, contribution_date=date(2015, 1, 5), amount=10000, idempotency_key="x")
    service.refresh(CORRECTED_CORE_ID)
    baseline = service.nav_series(CORRECTED_CORE_ID)
    with connect(service.db_path) as conn:
        conn.execute("UPDATE corrected_core_flows SET amount=20000 WHERE idempotency_key='x'")
    assert service.refresh(CORRECTED_CORE_ID)["state"] == "BLOCKED"
    assert service.nav_series(CORRECTED_CORE_ID) == baseline


def test_refresh_does_not_rebalance_old_holdings_just_because_there_is_a_deposit(service):
    service.activate(CORRECTED_CORE_ID, activation_date=date(2015, 1, 5), initial_cash=50000)
    service.deposit(CORRECTED_CORE_ID, contribution_date=date(2015, 1, 7), amount=3000, idempotency_key="x")
    service.refresh(CORRECTED_CORE_ID)
    events = service.ledger_events(CORRECTED_CORE_ID, limit=200)["events"]
    buys = [e["details"] for e in events if e["eventDate"] == "2015-01-07" and e["type"] == "fill"]
    assert len(buys) == 3 and all(e["fill_type"] == "subscription" and e["quantity_delta"] > 0 for e in buys)


def test_company_action_verification_end_blocks_newer_prices(service):
    root = service.data_dir/"core_raw"
    document = load_actions(); document["metadata"]["verified_through"] = "2015-01-31"
    path = root/"corporate_actions.json"; path.write_text(json.dumps(document))
    manifest_path = root/"manifest.json"; manifest = json.loads(manifest_path.read_text())
    manifest["corporate_actions"] = {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest_path.write_text(json.dumps(manifest))
    service.activate(CORRECTED_CORE_ID, activation_date=date(2015, 1, 5))
    result = service.refresh(CORRECTED_CORE_ID)
    assert result["state"] == "BLOCKED" and result["diagnostics"][0]["code"] == "CORPORATE_ACTION_COVERAGE_EXPIRED"
    assert service.nav_series(CORRECTED_CORE_ID)["points"] == []


def test_zero_volume_placeholder_cannot_supply_a_paper_fill_or_signal_calendar_day():
    inputs = frames()
    inputs[CORE_SYMBOLS[0]].loc["2015-01-06", "Volume"] = 0
    prepared = prepare_core_market(inputs, [])
    day_index = prepared.dates.get_loc(pd.Timestamp("2015-01-06"))
    assert np.isnan(prepared.opening[day_index, 0])
    state, _, _ = advance_core_day(initial_state(), prepared, 0, initial_cash=1000)
    state, _, events = advance_core_day(state, prepared, day_index)
    assert state["cash"] == 1000
    assert not any(e["type"] == "fill" for e in events)


def test_latest_zero_volume_placeholder_reports_suspension_instead_of_trading(service):
    service.activate(CORRECTED_CORE_ID, activation_date=date(2015, 1, 5))
    inputs = frames(); inputs[CORE_SYMBOLS[0]].loc["2015-02-10", "Volume"] = 0
    write_raw(service.data_dir, inputs)
    result = service.refresh(CORRECTED_CORE_ID)
    assert result["state"] == "BLOCKED" and result["diagnostics"][0]["code"] == "RAW_SNAPSHOT_STALE"
    assert service.nav_series(CORRECTED_CORE_ID)["points"] == []


def test_http_handlers_use_corrected_account_and_preserve_error_mapping(service, monkeypatch):
    import main
    from fastapi import HTTPException
    monkeypatch.setattr(main, "_get_portfolio_service", lambda: service)
    request = ActivateRequest(activationDate=date(2015, 1, 5), initialCash=50000)
    assert main.api_portfolio_activate(CORRECTED_CORE_ID, request)["nav"]["cash"] == 50000
    flow = DepositRequest(contributionDate=date(2015, 1, 7), amount=3000, idempotencyKey="monthly")
    result = main.api_portfolio_deposit(CORRECTED_CORE_ID, flow)
    assert result == main.api_portfolio_deposits(CORRECTED_CORE_ID)
    with pytest.raises(HTTPException) as error:
        main.api_portfolio_activate("risk_parity_core_next_open", request)
    assert error.value.status_code == 400
    with pytest.raises(HTTPException) as error:
        main.api_portfolio_deposits("unknown")
    assert error.value.status_code == 404


@pytest.mark.parametrize("body", [{"activationDate": "2015-01-05", "initialCash": -1},
                                  {"activationDate": "2015-01-05", "initialCash": float("nan")}])
def test_activation_request_rejects_invalid_amount(body):
    with pytest.raises(ValidationError):
        ActivateRequest.model_validate(body)


def test_deposit_request_rejects_zero_and_legacy_custom_cash_is_not_ignored(service):
    with pytest.raises(ValidationError):
        DepositRequest.model_validate({"contributionDate": "2015-01-05", "amount": 0, "idempotencyKey": "x"})
    with pytest.raises(ValueError, match="only by"):
        service.activate("risk_parity_core_next_open", activation_date=date(2015, 1, 5), initial_cash=50000)


def test_official_action_snapshot_is_explicitly_bounded():
    document = load_actions()
    assert document["metadata"]["verified_through"] == "2026-09-30"
    assert len(document["events"]) == 15


def provider_package(tmp_path, adjustment="none"):
    payload = {"data": {}}
    for symbol, frame in frames().items():
        dates = [int(pd.Timestamp(d).tz_localize("Asia/Shanghai").timestamp()*1000) for d in frame.index]
        record = {"timestamp": dates, **{c.lower(): frame[c].tolist() for c in ("Open", "High", "Low", "Close")},
                  "volume": (frame.Volume/100).tolist()}
        payload["data"][symbol.replace(".SS", ".SH")] = record
    raw = tmp_path/"raw.json"; raw.write_text(json.dumps(payload))
    (tmp_path/"fetch_log.json").write_text(json.dumps([{"symbols": list(payload["data"]), "status": 200,
        "requested_adjust": adjustment, "retrieved_at": "2026-10-04T21:35:00+08:00"}]))
    return raw


def test_raw_import_keeps_general_cache_and_refuses_implicit_overwrite(tmp_path):
    from scripts.import_core_raw_snapshot import import_snapshot, ImportErrorMessage
    raw = provider_package(tmp_path)
    data = tmp_path/"data"; data.mkdir()
    general = data/"510300.SS.parquet"; general.write_bytes(b"existing adjusted cache")
    import_snapshot(raw, data)
    loaded, errors = load_core_raw_frames(data)
    assert not errors and set(loaded) == set(CORE_SYMBOLS)
    assert general.read_bytes() == b"existing adjusted cache"
    with pytest.raises(ImportErrorMessage, match="already exists"):
        import_snapshot(raw, data)
    assert general.read_bytes() == b"existing adjusted cache"


def test_raw_import_requires_proof_and_rejects_forward_additive_source(tmp_path):
    from scripts.import_core_raw_snapshot import import_snapshot, ImportErrorMessage
    raw = provider_package(tmp_path, adjustment="forward_additive")
    with pytest.raises(ImportErrorMessage, match="none"):
        import_snapshot(raw, tmp_path/"data")
    (tmp_path/"fetch_log.json").unlink()
    with pytest.raises(ImportErrorMessage, match="not the exact approved"):
        import_snapshot(raw, tmp_path/"data")
    assert not (tmp_path/"data/core_raw").exists()
