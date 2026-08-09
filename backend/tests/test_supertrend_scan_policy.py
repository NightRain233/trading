from supertrend_scan_policy import (
    POLICY_VERSION,
    SCHEMA_VERSION,
    build_scan_response,
    classify_symbol_market,
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
        "dataStale": False,
        "dataIntegrity": {"hasGap": False},
        "latestDataDate": "2026-08-07",
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
            "atr": atr,
            "bollLower": boll_lower,
        },
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
    assert classify_symbol_market("513120.SS") == "hong_kong"
    assert classify_symbol_market("510300.SS") == "a_share"


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


def test_breakout_requires_weekly_market_adx_and_distance_gates():
    items = _representatives() + [
        _item("AAPL", state="bull_flip", adx=31, distance_atr=1.5),
        _item("MU", state="bull_flip", weekly_state="bear", adx=35, distance_atr=1.0),
        _item("NVDA", state="bull_flip", adx=20, distance_atr=1.0),
        _item("GOOGL", state="bull_flip", adx=35, distance_atr=2.5),
    ]

    response = build_scan_response(items, requested_symbols=[item["symbol"] for item in items])
    by_symbol = {item["symbol"]: item for item in response["items"]}

    assert by_symbol["AAPL"]["decision"] == {
        "permission": "buy",
        "label": "可买·突破入场",
        "setup": "breakout",
        "stage": "confirmed",
        "reasonCodes": [
            "DATA_VALID",
            "MARKET_SEEK",
            "WEEKLY_BULL",
            "DAILY_BULL_FLIP",
            "ADX_PASSED",
            "DISTANCE_PASSED",
        ],
        "failedGates": [],
        "nextTrigger": "下一交易日不超过最高接受价时执行",
        "invalidation": "日线收盘重新翻空",
        "maxAcceptablePrice": 104.0,
    }
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
    assert by_symbol["MU"]["decision"]["label"] == "等确认·回踩接近支撑"
    assert by_symbol["NVDA"]["pullback"]["enteredZone"] is True
    assert by_symbol["NVDA"]["pullback"]["enteredAt"] == "2026-08-07"
    assert by_symbol["NVDA"]["pullback"]["restrengthConfirmed"] is False
    assert by_symbol["NVDA"]["decision"]["label"] == "等确认·回踩接近支撑"


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


def test_stale_or_incomplete_data_blocks_buy_permission():
    items = _representatives() + [_item("AAPL", state="bull_flip", daily_complete=False)]

    response = build_scan_response(items, requested_symbols=[item["symbol"] for item in items])
    aapl = next(item for item in response["items"] if item["symbol"] == "AAPL")

    assert aapl["decision"]["permission"] == "blocked"
    assert aapl["decision"]["failedGates"] == ["DAILY_SESSION_INCOMPLETE"]
    assert aapl["primaryGroup"] == "blocked"
