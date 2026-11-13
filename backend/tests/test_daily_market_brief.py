import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "daily_market_brief.py"
SPEC = importlib.util.spec_from_file_location("daily_market_brief", SCRIPT_PATH)
daily = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(daily)


def _item(symbol, *, state="bear", previous_state="bear", change=-0.01, volume=1.0, rsi=45.0):
    latest = 100.0
    previous = latest / (1 + change)
    return {
        "symbol": symbol,
        "alias": symbol,
        "market": "us" if symbol.isalpha() else "cn",
        "isCrypto": symbol == "BTC-USD",
        "state": state,
        "weeklyState": "bull" if symbol == "513100.SS" else "bear",
        "latestDataDate": "2026-11-13",
        "close": latest,
        "signedDistanceToSupertrendPct": -2.0,
        "indicators": {
            "rsi7": rsi,
            "rsi14": rsi,
            "macdHist": -0.2,
            "macdHistPrev": -0.3,
            "macdHistDelta": 0.1,
            "bollWidth": 0.08,
        },
        "volumeContext": {"ratio20Completed": volume},
        "bollSqueezeRecent": False,
        "decision": {"permission": "watch"},
        "decisionHistory": [
            {"date": "2026-11-12", "state": previous_state, "close": previous},
            {"date": "2026-11-13", "state": state, "close": latest},
        ],
    }


def test_primary_watch_is_always_present_and_market_temperature_is_compact():
    items = [
        _item("000300.SS"),
        _item("SPY"),
        _item("BTC-USD", rsi=25),
        _item("510300.SS", volume=0.5),
        _item("513100.SS"),
        _item("518880.SS"),
    ]
    report = daily.build_report({"items": items, "coverage": {"returned": 6}}, {"forecasts": [], "evaluations": []})

    assert [row["symbol"] for row in report["primaryWatch"]] == ["510300.SS", "513100.SS", "518880.SS"]
    assert [row["market"] for row in report["marketTemperature"]] == ["A股", "美股", "BTC", "黄金"]
    assert report["marketTemperature"][2]["temperature"] == "偏弱"


def test_anomaly_requires_a_real_change_for_non_primary_symbols():
    quiet = _item("QUIET", volume=1.2)
    assert daily._anomaly(quiet) is None

    changed = _item("CHANGED", change=-0.08, volume=2.0, rsi=25)
    anomaly = daily._anomaly(changed)
    assert anomaly is not None
    assert any(reason.startswith("单日变动") for reason in anomaly["reasons"])
    assert anomaly["change1dPct"] < -7


def test_report_caps_low_grade_anomalies_but_keeps_omitted_count():
    items = [_item("000300.SS"), _item("SPY"), _item("BTC-USD"), _item("518880.SS")]
    items.extend(_item(f"X{i}", change=-0.04, volume=1.0) for i in range(20))
    report = daily.build_report({"items": items}, {"forecasts": [], "evaluations": []})

    assert len(report["anomalies"]) == 12
    assert report["anomalyCount"] == 12
    assert report["omittedAnomalyCount"] == 8


def test_evaluate_pending_uses_the_fifth_future_trading_bar():
    item = _item("AAPL")
    item["decisionHistory"] = [
        {"date": f"2026-11-{day:02d}", "close": close, "state": "bull"}
        for day, close in [(10, 100), (11, 101), (12, 102), (13, 103), (14, 104), (15, 105), (16, 106)]
    ]
    state = {
        "forecasts": [{
            "forecastId": "2026-11-10:AAPL",
            "symbol": "AAPL",
            "entryDate": "2026-11-10",
            "entryPrice": 100,
            "stance": "bull",
            "confidence": 80,
            "confidenceBucket": "high",
            "horizonTradingDays": 5,
            "status": "pending",
        }],
        "evaluations": [],
    }

    completed = daily._evaluate_pending(state, [item])

    assert len(completed) == 1
    assert completed[0]["targetDate"] == "2026-11-15"
    assert completed[0]["targetPrice"] == 105
    assert completed[0]["correct"] is True
    assert state["forecasts"][0]["status"] == "scored"
