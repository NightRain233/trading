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


def test_fetch_supertrend_scan_reads_items_from_schema_v2_envelope(monkeypatch):
    item = _item(
        "SPY",
        state="bull_flip",
        weekly_state="bull",
        alert_type="buy_candidate",
        priority="high",
    )
    monkeypatch.setattr(
        openclaw_supertrend_alerts,
        "_api_get",
        lambda *args, **kwargs: {"schemaVersion": 2, "items": [item]},
    )

    assert openclaw_supertrend_alerts.fetch_supertrend_scan("http://example.test/api", 1.0) == [item]


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

    assert "预备观察" in markdown
    assert "现在不买" in markdown
    assert "WAIT" in markdown
    # Verify new header format with emoji
    assert "## 👀 预备观察：周多日空，等待日线翻多" in markdown


def test_fetch_portfolio_strategies_keeps_only_four_primary_in_fixed_order(monkeypatch):
    strategies = [
        {"strategyId": "theme_alpha", "displayName": "Theme", "paperEnabled": True, "isPrimary": True},
        {"strategyId": "core90_raw_bull10", "displayName": "Raw", "paperEnabled": True, "isPrimary": False},
        {"strategyId": "risk_parity_core_next_open", "displayName": "RP", "paperEnabled": True, "isPrimary": True},
    ]

    def fake_get(_base, path, _timeout):
        if path == "/portfolio-strategies":
            return strategies
        return {"strategyId": path.split("/")[2], "state": "READY"}

    monkeypatch.setattr(openclaw_supertrend_alerts, "_api_get", fake_get)

    result = openclaw_supertrend_alerts.fetch_portfolio_strategies("http://example.test/api", 1.0)

    assert [item["strategyId"] for item in result] == ["risk_parity_core_next_open", "theme_alpha"]


def test_portfolio_markdown_prioritizes_orders_and_reports_policy_audit():
    strategy = {
        "strategyId": "core90_ma200_bull10",
        "_displayName": "Core90 + MA200 Bull10",
        "state": "PENDING_EXECUTION",
        "nav": {"netNav": 100420, "cash": 4000, "dailyReturn": 0.001, "cumulativeReturn": 0.0042, "drawdown": -0.01},
        "currentWeights": [{"symbol": "510300.SS", "weight": 0.96}],
        "diagnostics": [{"code": "OPEN_MISSING", "message": "open delayed"}],
        "operations": {
            "orders": [
                {"orderId": 1, "symbol": "AAPL", "side": "BUY", "status": "PENDING", "due": True},
                {"orderId": 2, "symbol": "2800.HK", "side": "SELL", "status": "DELAYED", "due": False, "nextAttemptDate": "2026-08-20"},
            ],
            "bullCandidates": [
                {"symbol": "AAPL", "eligible": True},
                {"symbol": "0700.HK", "eligible": False},
            ],
            "ma200AllowedCount": 1,
            "ma200BlockedCount": 1,
            "grossExposure": 0.96,
            "dataQualityEventCount": 1,
            "benchmark": {"relativeReturn": 0.002},
        },
    }

    markdown = openclaw_supertrend_alerts.render_portfolio_summary_markdown([strategy])

    assert markdown.index("### 执行优先") < markdown.index("### Core90 + MA200 Bull10")
    assert "今日执行: AAPL BUY" in markdown
    assert "等待 Open: 2800.HK SELL，下一尝试 2026-08-20" in markdown
    assert "Bull flip: 2 个（MA200 允许 1 / 拦截 1）" in markdown
    assert "总敞口 96.0%" in markdown
    assert "相对 RiskParity: +0.20%" in markdown
    assert "异常: 策略诊断 1 / 数据质量事件 1" in markdown
