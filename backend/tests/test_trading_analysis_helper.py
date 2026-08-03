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


def test_grouped_market_indices_include_integrity_and_macd_metadata(monkeypatch):
    item = {
        "symbol": helper.MARKET_INDICES[0],
        "state": "bull",
        "dataUpdatedAt": "2026-08-03T15:20:00+08:00",
        "cacheStale": False,
        "dataStale": False,
        "dataIntegrity": {"hasGap": False},
        "indicators": {
            "macdHist": 0.2,
            "macdHistPrev": 0.1,
            "macdHistDelta": 0.1,
        },
    }
    monkeypatch.setattr(helper, "_api_get", lambda *args, **kwargs: [item])

    result = helper.query_scan("http://example.test/api", timeout=1.0, grouped=True)
    market = result["market"]["indices"][0]

    assert market["macdDir"] == "↑"
    assert market["dataUpdatedAt"] == item["dataUpdatedAt"]
    assert market["cacheStale"] is False
    assert market["dataIntegrity"] == {"hasGap": False}
