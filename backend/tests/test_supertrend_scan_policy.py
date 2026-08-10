from supertrend_scan_policy import (
    POLICY_VERSION,
    SCHEMA_VERSION,
    build_scan_response,
    classify_symbol_market,
    classify_trading_venue,
    classify_trend_state,
)


def _item(
    symbol: str,
    *,
    state: str = "bull",
    weekly_state: str = "bull",
    adx: float = 35.0,
    distance_atr: float = 1.0,
    monthly_direction: str = "rising",
    daily_complete: bool = True,
    trend_age: int = 8,
    close: float = 101.0,
    st_val: float = 100.0,
    atr: float = 2.0,
    boll_lower: float = 96.0,
    ratio20: float = 1.0,
    boll_squeeze: bool = False,
    boll_squeeze_recent: bool = False,
    macd_hist: float | None = None,
    macd_delta: float | None = None,
    adx_delta: float | None = None,
    candles: list[dict] | None = None,
) -> dict:
    return {
        "symbol": symbol,
        "alias": "",
        "state": state,
        "weeklyState": weekly_state,
        "trendAgeBars": trend_age,
        "close": close,
        "stVal": st_val,
        "distanceToSupertrendAtr": distance_atr,
        "dailySessionComplete": daily_complete,
        "decisionDailyAvailable": True,
        "decisionAsOf": "2026-08-07",
        "hasProvisionalBar": not daily_complete,
        "livePrice": close,
        "liveAsOf": "2026-08-10" if not daily_complete else "2026-08-07",
        "dataStale": False,
        "dataIntegrity": {"hasGap": False},
        "latestDataDate": "2026-08-07" if daily_complete else "2026-08-10",
        "monthlyBoll": {
            "midDirection": monthly_direction,
            "slopeSampleSufficient": True,
        },
        "volumeContext": {
            "sessionComplete": daily_complete,
            "ratio20Completed": ratio20 if daily_complete else None,
        },
        "indicators": {
            "adx": adx,
            "adxDelta": adx_delta,
            "atr": atr,
            "bollLower": boll_lower,
            "macdHist": macd_hist,
            "macdHistDelta": macd_delta,
            "bollSqueeze": boll_squeeze,
            "bollSqueezeRecent": boll_squeeze_recent,
        },
        "bollSqueeze": boll_squeeze,
        "bollSqueezeRecent": boll_squeeze_recent,
        "candles": candles or [],
        "alertType": "hold_bull",
    }


def _representatives() -> list[dict]:
    return [
        _item("000001.SS"),
        _item("000300.SS"),
        _item("SPY"),
        _item("QQQ"),
        _item("BTC-USD"),
        _item("ETH-USD"),
        _item("GC=F"),
        _item("518880.SS"),
    ]


def test_trend_flip_only_applies_to_the_latest_direction_change():
    assert classify_trend_state([-1, 1]) == ("bull_flip", True)
    assert classify_trend_state([-1, 1, 1, 1, 1]) == ("bull", False)
    assert classify_trend_state([1, -1]) == ("bear_flip", True)


def test_symbol_market_classification_handles_cross_market_etfs_before_exchange_suffix():
    assert classify_symbol_market("518880.SS") == "gold"
    assert classify_symbol_market("513100.SS") == "us"
    assert classify_symbol_market("513500.SS") == "us"
    assert classify_symbol_market("513120.SS") == "hong_kong"
    assert classify_symbol_market("510300.SS") == "a_share"
    assert classify_trading_venue("513500.SS") == "china_exchange"


def test_scan_response_has_versioned_envelope_and_complete_primary_group_coverage():
    items = _representatives() + [_item("510300.SS"), _item("AAPL")]

    response = build_scan_response(items, requested_symbols=[item["symbol"] for item in items])

    assert response["schemaVersion"] == SCHEMA_VERSION
    assert response["policyVersion"] == POLICY_VERSION
    assert response["coverage"] == {
        "requested": 10,
        "returned": 10,
        "missing": [],
    }
    grouped = [symbol for group in response["groups"].values() for symbol in group["symbols"]]
    assert sorted(grouped) == sorted(item["symbol"] for item in items)
    assert len(grouped) == len(set(grouped))
    assert all("decision" in item for item in response["items"])


def test_market_mode_uses_two_representatives_and_marks_missing_data():
    items = _representatives()
    next(item for item in items if item["symbol"] == "QQQ")["monthlyBoll"]["midDirection"] = "falling"

    response = build_scan_response(items, requested_symbols=[item["symbol"] for item in items])

    assert response["marketModes"]["a_share"]["mode"] == "seek"
    assert response["marketModes"]["us"]["mode"] == "cautious"
    assert response["marketModes"]["us"]["adxThreshold"] == 30
    assert response["marketModes"]["bond"]["mode"] == "insufficient"
    assert response["marketModes"]["bond"]["missingSymbols"] == ["511010.SS", "TLT"]


def test_system_representatives_are_separate_and_hk_does_not_depend_on_bonds():
    items = _representatives() + [_item("513910.SS", state="bull_flip")]
    representative_items = [
        _item("^HSI"),
        _item("2800.HK"),
        _item("511010.SS"),
        _item("TLT"),
    ]
    response = build_scan_response(
        items,
        requested_symbols=[item["symbol"] for item in items],
        representative_items=representative_items,
    )
    assert response["marketModes"]["hong_kong"]["mode"] == "seek"
    assert response["marketModes"]["bond_cn"]["role"] == "bond_risk_observation"
    assert response["marketModes"]["bond_us"]["role"] == "bond_risk_observation"
    assert "^HSI" not in [item["symbol"] for item in response["items"]]


def test_stale_bond_representative_only_marks_bond_risk_insufficient():
    items = _representatives() + [_item("513910.SS", state="bull_flip")]
    stale_bond = _item("511010.SS")
    stale_bond["dataStale"] = True
    response = build_scan_response(
        items,
        requested_symbols=[item["symbol"] for item in items],
        representative_items=[_item("^HSI"), _item("2800.HK"), stale_bond, _item("TLT")],
    )
    assert response["marketModes"]["bond_cn"]["mode"] == "insufficient"
    assert response["marketModes"]["bond_cn"]["representativeStatus"]["511010.SS"] == "stale"
    assert response["marketModes"]["hong_kong"]["mode"] == "seek"


def test_crypto_uses_last_complete_daily_bar_when_current_utc_bar_is_provisional():
    items = [
        {**_item("BTC-USD", daily_complete=False), "isCrypto": True, "decisionDailyAvailable": True},
        {**_item("ETH-USD", daily_complete=False), "isCrypto": True, "decisionDailyAvailable": True},
    ] + [_item("000001.SS"), _item("000300.SS"), _item("SPY"), _item("QQQ"), _item("GC=F"), _item("518880.SS")]
    response = build_scan_response(items, requested_symbols=[item["symbol"] for item in items])
    btc = next(item for item in response["items"] if item["symbol"] == "BTC-USD")
    assert btc["decision"]["failedGates"] != ["DAILY_SESSION_INCOMPLETE"]


def test_crypto_blocks_only_when_no_complete_daily_bar_exists():
    btc = {**_item("BTC-USD", daily_complete=False), "isCrypto": True, "decisionDailyAvailable": False}
    response = build_scan_response([btc], requested_symbols=["BTC-USD"])
    assert response["items"][0]["decision"]["permission"] == "blocked"
    assert response["items"][0]["decision"]["failedGates"] == ["DAILY_SESSION_INCOMPLETE"]


def test_breakout_requires_weekly_market_adx_and_distance_gates():
    items = _representatives() + [
        _item("AAPL", state="bull_flip", adx=31, distance_atr=1.5),
        _item("MU", state="bull_flip", weekly_state="bear", adx=35, distance_atr=1.0),
        _item("NVDA", state="bull_flip", adx=20, distance_atr=1.0),
        _item("GOOGL", state="bull_flip", adx=35, distance_atr=2.5),
    ]

    response = build_scan_response(items, requested_symbols=[item["symbol"] for item in items])
    by_symbol = {item["symbol"]: item for item in response["items"]}

    assert by_symbol["AAPL"]["decision"]["permission"] == "buy"
    assert by_symbol["AAPL"]["decision"]["label"] == "可买·突破入场"
    assert by_symbol["AAPL"]["decision"]["setup"] == "breakout"
    assert by_symbol["AAPL"]["decision"]["stage"] == "breakout_confirmed"
    assert by_symbol["AAPL"]["decision"]["readinessScore"] == 100
    assert by_symbol["AAPL"]["decision"]["maxAcceptablePrice"] == 104.0
    assert by_symbol["AAPL"]["breakout"] == {
        "triggered": True,
        "signalDate": "2026-08-07",
        "previousState": "bear",
        "currentState": "bull_flip",
        "distanceAtr": 1.5,
        "maxAcceptablePrice": 104.0,
        "stillExecutable": True,
    }
    assert by_symbol["MU"]["decision"]["permission"] == "watch"
    assert by_symbol["MU"]["decision"]["failedGates"] == ["WEEKLY_NOT_BULL"]
    assert by_symbol["NVDA"]["decision"]["failedGates"] == ["ADX_BELOW_25"]
    assert by_symbol["GOOGL"]["decision"]["permission"] == "wait"
    assert by_symbol["GOOGL"]["decision"]["failedGates"] == ["DISTANCE_ABOVE_2_ATR"]


def test_cautious_market_raises_breakout_adx_threshold_to_thirty():
    items = _representatives()
    next(item for item in items if item["symbol"] == "QQQ")["monthlyBoll"]["midDirection"] = "falling"
    items.append(_item("AAPL", state="bull_flip", adx=28, distance_atr=1.0))

    response = build_scan_response(items, requested_symbols=[item["symbol"] for item in items])
    aapl = next(item for item in response["items"] if item["symbol"] == "AAPL")

    assert aapl["marketMode"] == "cautious"
    assert aapl["decision"]["permission"] == "watch"
    assert aapl["decision"]["failedGates"] == ["ADX_BELOW_30"]


def test_pullback_requires_prior_zone_bar_and_current_restrengthening_close():
    candles = [
        {"time": "2026-08-06", "close": 100.5, "st_val": 100.0, "st_dir": 1},
        {"time": "2026-08-07", "close": 101.0, "st_val": 100.0, "st_dir": 1},
    ]
    items = _representatives() + [
        _item("AAPL", distance_atr=0.5, candles=candles),
        _item(
            "MU",
            distance_atr=0.5,
            candles=[
                {"time": "2026-08-06", "close": 101.0, "st_val": 100.0, "st_dir": 1},
                {"time": "2026-08-07", "close": 100.5, "st_val": 100.0, "st_dir": 1},
            ],
        ),
        _item(
            "NVDA",
            distance_atr=0.5,
            candles=[
                {"time": "2026-08-06", "close": 106.0, "st_val": 100.0, "st_dir": 1},
                {"time": "2026-08-07", "close": 101.0, "st_val": 100.0, "st_dir": 1},
            ],
        ),
    ]

    response = build_scan_response(items, requested_symbols=[item["symbol"] for item in items])
    by_symbol = {item["symbol"]: item for item in response["items"]}

    assert by_symbol["AAPL"]["pullback"] == {
        "enteredZone": True,
        "enteredAt": "2026-08-06",
        "supportHeld": True,
        "restrengthConfirmed": True,
        "confirmedAt": "2026-08-07",
        "failed": False,
    }
    assert by_symbol["AAPL"]["decision"]["label"] == "可买·回踩入场"
    assert by_symbol["AAPL"]["decision"]["maxAcceptablePrice"] == 103.0
    assert by_symbol["MU"]["decision"]["label"] == "等确认·已进入回踩区，支撑暂未失守"
    assert by_symbol["NVDA"]["pullback"]["enteredZone"] is True
    assert by_symbol["NVDA"]["pullback"]["enteredAt"] == "2026-08-07"
    assert by_symbol["NVDA"]["pullback"]["restrengthConfirmed"] is False
    assert by_symbol["NVDA"]["decision"]["label"] == "等确认·已进入回踩区，支撑暂未失守"


def test_v_reversal_does_not_relabel_an_existing_daily_bull_trend():
    items = _representatives() + [
        _item("AAPL", state="bull", close=96.5, boll_lower=96.0, atr=2.0, ratio20=0.7),
    ]

    response = build_scan_response(items, requested_symbols=[item["symbol"] for item in items])
    aapl = next(item for item in response["items"] if item["symbol"] == "AAPL")

    assert aapl["vReversal"]["candidate"] is False
    assert aapl["decision"]["setup"] != "v_reversal"


def test_v_reversal_and_yellow_watch_are_observation_only():
    items = _representatives() + [
        _item(
            "AAPL",
            state="bear",
            close=96.5,
            boll_lower=96.0,
            atr=2.0,
            ratio20=0.7,
        ),
        _item("002309.SZ", state="bull", weekly_state="bear", adx=32, distance_atr=1.2),
        _item("600001.SS", state="bull", weekly_state="bear", adx=40, distance_atr=0.8),
    ]

    response = build_scan_response(items, requested_symbols=[item["symbol"] for item in items])
    by_symbol = {item["symbol"]: item for item in response["items"]}

    assert by_symbol["AAPL"]["vReversal"]["candidate"] is True
    assert by_symbol["AAPL"]["decision"]["permission"] == "watch"
    assert by_symbol["AAPL"]["decision"]["setup"] == "v_reversal"
    assert "v_reversal" in by_symbol["AAPL"]["tags"]
    assert by_symbol["002309.SZ"]["decision"]["permission"] == "watch"
    assert by_symbol["002309.SZ"]["primaryGroup"] == "yellow_watch"
    assert "yellow_watch" in by_symbol["002309.SZ"]["tags"]
    assert response["groups"]["yellow_watch"]["symbols"] == ["600001.SS", "002309.SZ"]


def test_in_progress_session_keeps_last_complete_daily_decision():
    items = _representatives() + [_item("AAPL", state="bull_flip", daily_complete=False)]

    response = build_scan_response(items, requested_symbols=[item["symbol"] for item in items])
    aapl = next(item for item in response["items"] if item["symbol"] == "AAPL")

    assert aapl["decision"]["permission"] == "buy"
    assert aapl["sessionContext"] == {
        "status": "in_progress",
        "latestDataDate": "2026-08-10",
        "formalDecisionAsOf": "2026-08-07",
        "formalDecisionAvailable": True,
        "hasProvisionalBar": True,
        "permissionBasis": "completed_close",
    }
    assert aapl["executionStatus"]["status"] == "executable"
    assert aapl["breakout"]["stillExecutable"] is True


def test_in_progress_price_above_max_keeps_signal_but_cancels_execution():
    items = _representatives() + [
        _item("AAPL", state="bull_flip", daily_complete=False, close=101.0) | {"livePrice": 106.0},
    ]

    response = build_scan_response(items, requested_symbols=[item["symbol"] for item in items])
    aapl = next(item for item in response["items"] if item["symbol"] == "AAPL")

    assert aapl["decision"]["permission"] == "buy"
    assert aapl["decision"]["maxAcceptablePrice"] == 104.0
    assert aapl["executionStatus"]["status"] == "above_max_price"
    assert aapl["executionStatus"]["executable"] is False
    assert aapl["breakout"]["stillExecutable"] is False
    assert aapl["lifecycle"]["signalStatus"] == "triggered_not_executable"
    assert aapl["lifecycle"]["executionStatus"] == "above_max_price"
    assert "AAPL" in response["attention"]["formalBuySignals"]
    assert "AAPL" not in response["attention"]["executable"]
    assert aapl["decision"]["technicalExecutionEligible"] is True
    assert aapl["decision"]["liveTradingAllowed"] is False


def test_no_complete_daily_bar_still_blocks_permission():
    aapl = _item("AAPL", state="bull_flip", daily_complete=False)
    aapl["decisionDailyAvailable"] = False

    response = build_scan_response([aapl], requested_symbols=["AAPL"])

    assert response["items"][0]["decision"]["permission"] == "blocked"
    assert response["items"][0]["decision"]["failedGates"] == ["DAILY_SESSION_INCOMPLETE"]


def test_compression_breakout_is_pre_authorized_from_completed_close_and_triggered_intraday():
    candles = [
        {"time": "2026-08-03", "low": 97.5, "close": 98.0, "st_val": 100.0, "st_dir": -1},
        {"time": "2026-08-07", "low": 98.0, "close": 99.2, "st_val": 100.0, "st_dir": -1},
    ]
    candidate = _item(
        "AAPL",
        state="bear",
        weekly_state="bull",
        distance_atr=-0.4,
        close=99.2,
        st_val=100.0,
        atr=2.0,
        adx=20.5,
        adx_delta=-1.0,
        boll_squeeze=True,
        macd_hist=0.35,
        macd_delta=1.18,
        candles=candles,
        daily_complete=False,
    )
    candidate["livePrice"] = 100.5
    response = build_scan_response(_representatives() + [candidate], requested_symbols=[candidate["symbol"]])
    aapl = next(item for item in response["items"] if item["symbol"] == "AAPL")

    assert aapl["primaryGroup"] == "breakout_armed"
    assert aapl["decision"]["permission"] == "conditional"
    assert aapl["decision"]["stage"] == "breakout_armed"
    assert aapl["decision"]["triggerPrice"] == 100.0
    assert aapl["decision"]["maxAcceptablePrice"] == 101.0
    assert aapl["decision"]["invalidationPrice"] == 97.5
    assert aapl["executionStatus"]["status"] == "paper_armed_triggered"
    assert aapl["executionStatus"]["executable"] is False
    assert aapl["executionStatus"]["paperExecutable"] is True
    assert aapl["decision"]["paperOnly"] is True
    assert aapl["decision"]["liveTradingAllowed"] is False
    assert aapl["authorization"]["paperOnly"] is True
    assert aapl["authorization"]["consumptionTracked"] is False
    assert len(aapl["authorization"]["signalId"]) == 24
    assert aapl["executionStatus"]["canUpgradePermissionIntraday"] is False


def test_live_price_below_formal_st_downgrades_buy_execution():
    candidate = _item("AAPL", state="bull_flip", daily_complete=False)
    candidate["livePrice"] = 99.0
    response = build_scan_response(_representatives() + [candidate], requested_symbols=["AAPL"])
    aapl = next(item for item in response["items"] if item["symbol"] == "AAPL")

    assert aapl["decision"]["permission"] == "buy"
    assert aapl["executionStatus"]["status"] == "intraday_below_formal_st"
    assert aapl["executionStatus"]["executable"] is False
    assert aapl["breakout"]["stillExecutable"] is False


def test_stale_data_never_returns_trend_hold_position_guidance():
    candidate = _item("AAPL", state="bull")
    candidate["dataStale"] = True
    response = build_scan_response([candidate], requested_symbols=["AAPL"])
    guidance = response["items"][0]["positionGuidance"]

    assert guidance["status"] == "data_unavailable_review"
    assert guidance["basis"] == "last_valid_close"


def test_lifecycle_counts_only_real_direction_changes():
    candidate = _item("AAPL")
    candidate["decisionHistory"] = [
        {"date": "2026-08-05", "state": "bear"},
        {"date": "2026-08-06", "state": "bull_flip"},
        {"date": "2026-08-07", "state": "bull"},
    ]
    response = build_scan_response(_representatives() + [candidate], requested_symbols=["AAPL"])
    lifecycle = next(item for item in response["items"] if item["symbol"] == "AAPL")["lifecycle"]

    assert lifecycle["recentDirectionChanges"] == [{
        "date": "2026-08-06", "from": "bear", "to": "bull", "event": "bull_flip"
    }]


def test_changes_have_snapshot_times_and_watchlist_membership_semantics():
    first = build_scan_response(
        [_item("AAPL")], requested_symbols=["AAPL"], generated_at="2026-08-07T21:00:00+08:00"
    )
    second = build_scan_response(
        [_item("SPY")],
        requested_symbols=["SPY"],
        generated_at="2026-08-08T21:00:00+08:00",
        previous_response=first,
    )

    assert second["changes"]["baselineGeneratedAt"] == "2026-08-07T21:00:00+08:00"
    assert second["changes"]["currentGeneratedAt"] == "2026-08-08T21:00:00+08:00"
    assert second["changes"]["addedSymbols"] == ["SPY"]
    assert second["changes"]["removedSymbols"] == ["AAPL"]
    assert second["changes"]["replayedFromCache"] is False


def test_changes_record_intraday_execution_downgrade_without_formal_signal_change():
    baseline_item = _item("AAPL", state="bull_flip", daily_complete=False, close=101.0)
    baseline_item["livePrice"] = 101.0
    first = build_scan_response(
        _representatives() + [baseline_item],
        requested_symbols=["AAPL"],
        generated_at="2026-08-10T10:00:00-04:00",
    )
    downgraded_item = _item("AAPL", state="bull_flip", daily_complete=False, close=101.0)
    downgraded_item["livePrice"] = 106.0
    second = build_scan_response(
        _representatives() + [downgraded_item],
        requested_symbols=["AAPL"],
        generated_at="2026-08-10T10:05:00-04:00",
        previous_response=first,
    )

    transition = next(row for row in second["changes"]["items"] if row["symbol"] == "AAPL")
    assert transition["formalChanges"] == {}
    assert transition["executionChanges"]["executionStatus"] == {
        "from": "executable", "to": "above_max_price"
    }
    assert transition["executionChanges"]["executable"] == {"from": True, "to": False}
    assert second["changes"]["formalCount"] == 0
    assert second["changes"]["executionCount"] == 1


def test_compression_breakout_without_weekly_confirmation_remains_watch_only():
    candidate = _item(
        "AAPL",
        state="bear",
        weekly_state="bear",
        distance_atr=-1.0,
        close=98.0,
        st_val=100.0,
        atr=2.0,
        adx=23.0,
        boll_squeeze=True,
        macd_hist=0.4,
        macd_delta=0.2,
    )
    response = build_scan_response(_representatives() + [candidate], requested_symbols=[candidate["symbol"]])
    aapl = next(item for item in response["items"] if item["symbol"] == "AAPL")

    assert aapl["primaryGroup"] == "compression_watch"
    assert aapl["decision"]["permission"] == "watch"
    assert aapl["decision"]["failedGates"] == ["WEEKLY_NOT_BULL"]


def test_spy_august_third_replay_arms_after_recent_squeeze_starts_expanding():
    spy = _item(
        "SPY",
        state="bear",
        weekly_state="bull",
        close=757.6699829101562,
        st_val=761.4939808688321,
        atr=9.218228,
        distance_atr=0.4148300497709884,
        adx=20.506315481634644,
        boll_squeeze=False,
        boll_squeeze_recent=True,
        macd_hist=0.35503871850623436,
        macd_delta=1.1867070690747608,
    )
    response = build_scan_response(_representatives() + [spy], requested_symbols=["SPY"])
    replayed = [item for item in response["items"] if item["symbol"] == "SPY"][-1]

    assert replayed["decision"]["permission"] == "conditional"
    assert replayed["primaryGroup"] == "breakout_armed"
    assert replayed["compressionBreakout"]["bollSqueeze"] is False
    assert replayed["compressionBreakout"]["bollCompressionRecent"] is True


def test_waiting_stages_readiness_attention_themes_and_changes_are_structured():
    first_items = _representatives() + [
        _item("510300.SS", distance_atr=3.0),
        _item("AAPL", distance_atr=2.0),
    ]
    first = build_scan_response(first_items, requested_symbols=[item["symbol"] for item in first_items])
    second_items = _representatives() + [
        _item("510300.SS", distance_atr=1.0),
        _item("AAPL", distance_atr=1.0, candles=[
            {"time": "2026-08-06", "close": 100.5, "st_val": 100.0, "st_dir": 1},
            {"time": "2026-08-07", "close": 101.0, "st_val": 100.0, "st_dir": 1},
        ]),
    ]
    second = build_scan_response(
        second_items,
        requested_symbols=[item["symbol"] for item in second_items],
        previous_response=first,
    )
    aapl = next(item for item in second["items"] if item["symbol"] == "AAPL")

    assert aapl["decision"]["stage"] == "pullback_confirmed"
    assert aapl["transition"]["changes"]["permission"] == {"from": "wait", "to": "buy"}
    assert second["changes"]["baselineAvailable"] is True
    assert second["changes"]["count"] >= 1
    assert "AAPL" in second["attention"]["executable"]
    assert any(theme["themeId"] == "gold" for theme in second["themes"])
    assert any(theme["themeId"] == "csi300" for theme in second["themes"])
