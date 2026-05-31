import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "openclaw_supertrend_alerts.py"
SPEC = importlib.util.spec_from_file_location("openclaw_supertrend_alerts", SCRIPT_PATH)
openclaw_supertrend_alerts = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(openclaw_supertrend_alerts)


def _item(symbol, *, state, weekly_state, alert_type, priority="medium", actionable=False, distance=5.0):
    return {
        "symbol": symbol,
        "alias": "",
        "state": state,
        "weeklyState": weekly_state,
        "alertType": alert_type,
        "alertLabel": alert_type,
        "alertPriority": priority,
        "isActionable": actionable,
        "close": 100.0,
        "keyLevelPrice": 98.0,
        "distanceToSupertrendPct": distance,
        "distanceToSupertrendAtr": 1.2,
        "alertReason": f"{symbol} reason",
        "suggestedAction": f"{symbol} action",
    }


def test_daily_brief_groups_new_entries_prepare_watch_and_risk_sections():
    items = [
        _item("OLD", state="bull", weekly_state="bull", alert_type="hold_bull", priority="low", distance=9.0),
        _item("WAIT", state="bear", weekly_state="bull", alert_type="avoid_bear", priority="low", distance=1.5),
        _item("RISK", state="bear_flip", weekly_state="bull", alert_type="sell_or_risk", actionable=True, distance=7.0),
        _item("BUY", state="bull_flip", weekly_state="bull", alert_type="buy_candidate", priority="high", actionable=True, distance=4.0),
        _item("PULLBACK", state="bull", weekly_state="bull", alert_type="support_test", priority="high", actionable=True, distance=0.8),
    ]

    brief = openclaw_supertrend_alerts.build_daily_brief(items)

    assert [item["symbol"] for item in brief["new_entries"]] == ["BUY"]
    assert [item["symbol"] for item in brief["prepare_watch"]] == ["WAIT"]
    assert [item["symbol"] for item in brief["position_management"]] == ["PULLBACK", "RISK"]
    assert [item["symbol"] for item in brief["background_trends"]] == ["OLD"]


def test_daily_brief_markdown_explains_prepare_watch_is_not_a_buy_signal():
    items = [
        _item("WAIT", state="bear", weekly_state="bull", alert_type="avoid_bear", priority="low", distance=1.5),
    ]

    markdown = openclaw_supertrend_alerts.render_daily_brief_markdown(items, title="SuperTrend Daily")

    assert "## 预备观察：周多日空，等待日线翻多" in markdown
    assert "现在不买" in markdown
    assert "WAIT" in markdown

