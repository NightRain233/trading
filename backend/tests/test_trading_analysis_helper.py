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


def _scan_item(symbol, stage, previous=None, rs=0.1, dist=0.05, name=None):
    return {
        "symbol": symbol, "name": name or symbol, "stage": stage, "stageLabel": "x", "weeksInStage": 3,
        "ma30Distance": dist, "ma30Slope": 0.01, "rs26": rs, "rsBenchmark": "SPY", "bbState": "none",
        "volumeRatio": 1.2, "weekLabel": "2026-10-18", "previousStage": previous or stage,
        "rule": {"key": "hold", "label": "持有"},
    }


def _fake_api(routes):
    def get(api_base, path, timeout=20.0):
        for prefix, value in routes.items():
            if path.startswith(prefix):
                return value
        raise AssertionError(f"unexpected path {path}")
    return get


PRIMARY_ROUTES = {
    "/portfolio-strategies/btc_supertrend_satellite/snapshot": {
        "state": "NOT_DUE", "dates": {"nextCheck": "2026-10-28"}, "nav": {"netNav": 1.0},
        "assets": [{"symbol": "510300.SS", "alias": "沪深300ETF"}, {"symbol": "BTC-USD", "alias": "BTC"}],
        "currentWeights": [{"symbol": "CASH", "weight": 1.0}], "desiredWeights": [],
        "observation": {"values": {"btc_close": 100.0, "supertrend_line": 90.0, "supertrend_on": True, "formal_supertrend_on": False}},
        "operations": {"orders": []}, "diagnostics": [],
    },
    "/portfolio-strategies": [{"strategyId": "btc_supertrend_satellite", "displayName": "BTC 7.5%", "isPrimary": True}],
}


def test_query_weekly_groups_by_market_and_lists_stage_changes(monkeypatch):
    routes = {
        "/weinstein/scan": [
            _scan_item("SPY", 2), _scan_item("GOOGL", 3, previous=2, dist=-0.03),
            _scan_item("510880.SS", 2, name="红利ETF"), _scan_item("000300.SS", 4, rs=0.0), _scan_item("BTC-USD", 2, rs=None),
        ],
        "/supertrend/scan": {"groups": {"stable": {"symbols": ["SPY"]}, "wait_confirmation": {"symbols": ["510880.SS"]}}, "marketModes": {"us": {"mode": "seek"}}},
        **PRIMARY_ROUTES,
    }
    monkeypatch.setattr(helper, "_api_get", _fake_api(routes))

    result = helper.query_weekly("http://example.test/api", timeout=1.0)

    assert [row["symbol"] for row in result["benchmarks"]] == ["000300.SS", "SPY", "BTC-USD"]
    assert [(c["symbol"], c["from"], c["stage"]) for c in result["stageChanges"]] == [("GOOGL", 2, 3)]
    assert {row["symbol"] for row in result["us"]} == {"SPY", "GOOGL"}
    assert result["cn"]["stageCounts"] == {"1": 0, "2": 1, "3": 0, "4": 1}
    assert [row["name"] for row in result["cn"]["stage2StrongerThanCsi300"]] == ["红利ETF"]
    assert result["supertrend"]["groups"] == {"wait_confirmation": ["510880.SS"]}
    assert result["primary"]["btcSwitch"]["flipPending"] is True
    assert result["primary"]["btcSwitch"]["distancePct"] == 10.0


def test_query_brief_marks_primary_assets(monkeypatch):
    quote = {
        "symbol": "510300.SS", "alias": "沪深300ETF", "latestDataDate": "2026-10-16", "dataStale": False, "price": 4.2,
        "weinstein": {**_scan_item("510300.SS", 4, rs=0.01, dist=-0.1), "ma30": 4.7},
        "weekly_candles": [{"time": "2026-10-18", "close": 4.2, "ma30": 4.7, "stage": 4.0, "rs26": 0.01}],
        "state": "bear", "weeklyState": "bear", "decision": {"permission": "watch", "label": "只观察"},
    }
    monkeypatch.setattr(helper, "_api_get", _fake_api({"/quote/510300.SS": quote, **PRIMARY_ROUTES}))

    result = helper.query_brief("http://example.test/api", "510300.ss", timeout=1.0)

    assert result["inPrimaryStrategy"] is True
    assert result["weinstein"]["stage"] == 4
    assert result["recentWeeks"][-1]["stage"] == 4
    assert result["supertrend"]["permission"] == "watch"
