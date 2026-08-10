import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import trading_analysis_helper as helper


def test_query_stock_requires_and_preserves_unified_decision_contract(monkeypatch):
    payload = {
        "schemaVersion": 2,
        "policyVersion": "scan_v2_right_side_4",
        "symbol": "AAPL",
        "price": 210.0,
        "ema20": 205.0,
        "ema50": 190.0,
        "adx": 31.0,
        "candles": [{"close": 210.0, "atr": 4.0, "st_val": 202.0, "st_dir": 1}],
        "indicators": {"rsi21": 62.0, "macdHist": 0.8},
        "state": "bull_flip",
        "weeklyState": "bull",
        "decision": {"permission": "buy", "label": "可买·突破入场"},
        "sessionContext": {"status": "in_progress", "formalDecisionAsOf": "2026-08-07"},
        "executionStatus": {"status": "executable", "executable": True},
        "positionGuidance": {"status": "trend_hold", "label": "持仓观察·正式趋势维持"},
        "primaryGroup": "breakout_buy",
        "market": "us",
        "marketMode": "seek",
        "marketModeContext": {"mode": "seek", "adxThreshold": 25},
        "latestDataDate": "2026-08-07",
        "dataStale": False,
        "dataIntegrity": {"hasGap": False},
    }
    monkeypatch.setattr(helper, "_api_get", lambda *args, **kwargs: payload)

    result = helper.query_stock("http://example.test/api", "AAPL", timeout=1.0)

    assert result["decision"]["permission"] == "buy"
    assert result["sessionContext"]["status"] == "in_progress"
    assert result["executionStatus"]["executable"] is True
    assert result["positionGuidance"]["status"] == "trend_hold"
    assert result["marketModeContext"]["adxThreshold"] == 25
    assert result["indicators"]["ema20"] == 205.0
    assert result["indicators"]["rsi21"] == 62.0
    assert result["supertrend"]["weeklyState"] == "bull"
    assert result["dataQuality"]["dataStale"] is False


def test_query_stock_rejects_legacy_quote_without_decision(monkeypatch):
    monkeypatch.setattr(helper, "_api_get", lambda *args, **kwargs: {"symbol": "AAPL"})

    try:
        helper.query_stock("http://example.test/api", "AAPL", timeout=1.0)
    except ValueError as exc:
        assert "unified decision contract" in str(exc)
    else:
        raise AssertionError("legacy quote must not be treated as actionable analysis")


def test_build_symbol_entry_uses_histogram_change_for_macd_direction():
    rising = helper._build_symbol_entry({
        "symbol": "SPY",
        "indicators": {
            "macdHist": -0.5,
            "macdHistPrev": -1.0,
            "macdHistDelta": 0.5,
        },
    })
    falling = helper._build_symbol_entry({
        "symbol": "QQQ",
        "indicators": {
            "macdHist": 0.5,
            "macdHistPrev": 1.0,
            "macdHistDelta": -0.5,
        },
    })

    assert rising["macdDir"] == "↑"
    assert falling["macdDir"] == "↓"


def test_build_symbol_entry_preserves_macd_divergence_without_changing_groups():
    divergence = {
        "daily": {
            "confirmed": {
                "type": "bullish",
                "status": "confirmed",
                "decisionRole": "wait_for_trend_confirmation",
            },
            "candidate": None,
        }
    }

    entry = helper._build_symbol_entry({
        "symbol": "TEST",
        "macdDivergence": divergence,
        "indicators": {},
    })

    assert entry["macdDivergence"] == divergence


def test_grouped_market_indices_include_integrity_and_macd_metadata(monkeypatch):
    item = {
        "symbol": helper.MARKET_INDICES[0],
        "state": "bull",
        "dataUpdatedAt": "2026-08-03T15:20:00+08:00",
        "cacheStale": False,
        "dataStale": False,
        "dataIntegrity": {"hasGap": False},
        "decision": {"permission": "watch"},
        "primaryGroup": "trend_continuation",
        "tags": [],
        "indicators": {
            "macdHist": 0.2,
            "macdHistPrev": 0.1,
            "macdHistDelta": 0.1,
        },
    }
    payload = {
        "schemaVersion": 2,
        "policyVersion": "scan_v2_right_side_4",
        "generatedAt": "2026-08-03T15:20:00+08:00",
        "coverage": {"requested": 1, "returned": 1, "missing": []},
        "thresholds": {},
        "marketModes": {},
        "groups": {"trend_continuation": {"count": 1, "symbols": [item["symbol"]]}},
        "items": [item],
    }
    monkeypatch.setattr(helper, "_api_get", lambda *args, **kwargs: payload)

    result = helper.query_scan("http://example.test/api", timeout=1.0, grouped=True)
    market = result["market"]["indices"][0]

    assert market["macdDir"] == "↑"
    assert market["dataUpdatedAt"] == item["dataUpdatedAt"]
    assert market["cacheStale"] is False
    assert market["dataIntegrity"] == {"hasGap": False}
    assert result["schemaVersion"] == 2
    assert result["policyVersion"] == "scan_v2_right_side_4"
    assert result["groups"]["trend_continuation"]["symbols"] == [item["symbol"]]
    assert result["allSymbols"][0]["decision"] == {"permission": "watch"}
    assert len(result["allSymbols"]) == result["total"] == 1


def test_grouped_scan_uses_api_groups_without_dropping_non_actionable_items(monkeypatch):
    items = [
        {
            "symbol": "AAPL",
            "state": "bull_flip",
            "primaryGroup": "breakout_buy",
            "decision": {"permission": "buy"},
            "tags": [],
            "indicators": {},
        },
        {
            "symbol": "TSLA",
            "state": "bear",
            "primaryGroup": "stable",
            "decision": {"permission": "watch"},
            "tags": [],
            "indicators": {},
        },
    ]
    payload = {
        "schemaVersion": 2,
        "policyVersion": "scan_v2_right_side_4",
        "generatedAt": "2026-08-03T15:20:00+08:00",
        "coverage": {"requested": 2, "returned": 2, "missing": []},
        "thresholds": {},
        "marketModes": {},
        "groups": {
            "breakout_buy": {"count": 1, "symbols": ["AAPL"]},
            "stable": {"count": 1, "symbols": ["TSLA"]},
        },
        "items": items,
    }
    monkeypatch.setattr(helper, "_api_get", lambda *args, **kwargs: payload)

    result = helper.query_scan("http://example.test/api", timeout=1.0, grouped=True)

    assert [item["symbol"] for item in result["allSymbols"]] == ["AAPL", "TSLA"]
    grouped_symbols = [symbol for group in result["groups"].values() for symbol in group["symbols"]]
    assert grouped_symbols == ["AAPL", "TSLA"]


def test_overview_keeps_technical_permission_and_adds_portfolio_execution_context(monkeypatch):
    scan = {
        "allSymbols": [{
            "symbol": "AAPL",
            "decision": {"permission": "buy"},
        }],
    }
    portfolio = {
        "strategies": [{
            "strategyId": "test_strategy",
            "displayName": "Test Strategy",
            "snapshot": {
                "state": "BLOCKED",
                "assets": [{"symbol": "AAPL"}],
                "currentWeights": [{"symbol": "AAPL", "weight": 0.2}],
                "desiredWeights": [{"symbol": "AAPL", "weight": 0.3}],
                "executableWeights": [],
                "deltaWeights": [{"symbol": "AAPL", "delta": 0.1}],
                "ledger": {"status": "empty"},
                "diagnostics": [{"code": "BLOCKED_TEST", "symbol": "AAPL"}],
            },
        }],
    }

    result = helper._annotate_scan_with_portfolio(scan, portfolio)
    entry = result["allSymbols"][0]

    assert entry["decision"]["permission"] == "buy"
    assert entry["portfolioExecution"]["status"] == "blocked"
    assert entry["portfolioExecution"]["technicalPermissionUnchanged"] is True
    assert result["portfolioMatrix"][0]["technicalPermission"] == "buy"
    assert result["portfolioMatrix"][0]["portfolioPermission"] == "blocked"


def test_overview_marks_conflicting_strategy_permissions_as_mixed():
    scan = {"allSymbols": [{"symbol": "AAPL", "decision": {"permission": "buy"}}]}
    portfolio = {"strategies": [
        {
            "strategyId": "strategy_a",
            "displayName": "A",
            "snapshot": {
                "state": "READY",
                "assets": [{"symbol": "AAPL"}],
                "executableWeights": [{"symbol": "AAPL", "weight": 0.3}],
            },
        },
        {
            "strategyId": "strategy_b",
            "displayName": "B",
            "snapshot": {
                "state": "BLOCKED",
                "assets": [{"symbol": "AAPL"}],
                "executableWeights": [],
            },
        },
    ]}

    result = helper._annotate_scan_with_portfolio(scan, portfolio)

    assert result["allSymbols"][0]["portfolioExecution"]["status"] == "mixed"
    assert {row["permission"] for row in result["allSymbols"][0]["portfolioExecution"]["contexts"]} == {
        "executable", "blocked"
    }
