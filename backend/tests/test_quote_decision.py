import main


def test_quote_extends_legacy_payload_with_unified_decision(monkeypatch):
    monkeypatch.setattr(
        main,
        "analyze_stock",
        lambda symbol: {
            "symbol": symbol,
            "name": symbol,
            "price": 210.0,
            "changePercent": 1.0,
            "ema20": 205.0,
            "ema50": 190.0,
            "adx": 31.0,
            "rsi": 62.0,
            "rsiPeriod": 21,
            "rsiStatus": "中性",
            "rsiOverbought": 75.0,
            "rsiOversold": 25.0,
            "trend": "强势多头",
            "signal": "强烈信号",
            "candles": [],
            "weekly_candles": [],
        },
    )
    monkeypatch.setattr(
        main,
        "supertrend_scan",
        lambda **kwargs: {
            "schemaVersion": 2,
            "policyVersion": "scan_v2_right_side_4",
            "generatedAt": "2026-08-10T12:00:00+08:00",
            "coverage": {"requested": 1, "returned": 1, "missing": []},
            "thresholds": {"normalAdx": 25},
            "marketModes": {"us": {"mode": "seek", "adxThreshold": 25}},
            "items": [{
                "symbol": "AAPL",
                "market": "us",
                "marketMode": "seek",
                "primaryGroup": "breakout_buy",
                "decision": {
                    "permission": "buy",
                    "label": "可买·突破入场",
                    "setup": "breakout",
                    "stage": "breakout_confirmed",
                    "reasonCodes": [],
                    "failedGates": [],
                },
            }],
        },
    )

    result = main.get_quote("aapl")

    assert result["price"] == 210.0
    assert result["schemaVersion"] == 2
    assert result["policyVersion"] == "scan_v2_right_side_4"
    assert result["decision"]["permission"] == "buy"
    assert result["marketModeContext"]["adxThreshold"] == 25
    assert result["decisionAvailable"] is True

    serialized = main.StockResponse.model_validate(result).model_dump()
    assert serialized["decision"]["permission"] == "buy"
    assert serialized["marketMode"] == "seek"


def test_quote_returns_actual_weekly_candles_when_requested(monkeypatch):
    daily_candles = [{"time": "2026-08-19", "close": 4551.0, "st_dir": 1}]
    weekly_candles = [{"time": "2026-08-23", "close": 4551.0, "st_dir": -1}]
    monkeypatch.setattr(
        main,
        "analyze_stock",
        lambda symbol: {
            "symbol": symbol,
            "name": symbol,
            "price": 4551.0,
            "changePercent": 4.2,
            "ema20": 4300.0,
            "ema50": 4200.0,
            "adx": 30.0,
            "rsi": 60.0,
            "rsiPeriod": 14,
            "rsiStatus": "中性",
            "rsiOverbought": 70.0,
            "rsiOversold": 30.0,
            "trend": "强势多头",
            "signal": "持有",
            "candles": daily_candles,
            "weekly_candles": weekly_candles,
        },
    )
    monkeypatch.setattr(
        main,
        "supertrend_scan",
        lambda **kwargs: {
            "items": [],
            "coverage": {},
            "thresholds": {},
            "marketModes": {},
        },
    )

    result = main.get_quote("GC=F", timeframe="1W")

    assert result["candles"] == weekly_candles
    assert result["candles"][0]["time"] != daily_candles[0]["time"]
    assert result["candlesTimeframe"] == "1W"


def test_quote_keeps_legacy_payload_available_when_decision_build_fails(monkeypatch):
    legacy = {
        "symbol": "AAPL",
        "name": "AAPL",
        "price": 210.0,
        "changePercent": 1.0,
        "ema20": 205.0,
        "ema50": 190.0,
        "adx": 31.0,
        "rsi": 62.0,
        "rsiPeriod": 21,
        "rsiStatus": "中性",
        "rsiOverbought": 75.0,
        "rsiOversold": 25.0,
        "trend": "强势多头",
        "signal": "强烈信号",
        "candles": [],
        "weekly_candles": [],
    }
    monkeypatch.setattr(main, "analyze_stock", lambda symbol: legacy.copy())
    monkeypatch.setattr(
        main,
        "supertrend_scan",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("decision unavailable")),
    )

    result = main.get_quote("AAPL")

    assert result["price"] == 210.0
    assert result["decisionAvailable"] is False
    assert result["decisionError"] == "decision unavailable"
