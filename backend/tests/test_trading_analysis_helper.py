import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import trading_analysis_helper as helper


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
        "policyVersion": "scan_v2_right_side_1",
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
    assert result["policyVersion"] == "scan_v2_right_side_1"
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
        "policyVersion": "scan_v2_right_side_1",
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
