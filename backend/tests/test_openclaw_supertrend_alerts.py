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
    payload = {"schemaVersion": 2, "marketModes": {"us": {"mode": "seek"}}, "items": [item]}
    monkeypatch.setattr(
        openclaw_supertrend_alerts,
        "_api_get",
        lambda *args, **kwargs: payload,
    )

    assert openclaw_supertrend_alerts.fetch_supertrend_scan("http://example.test/api", 1.0) == payload


def test_daily_brief_distinguishes_healthy_hong_kong_fallback_from_missing_market_data():
    markdown = openclaw_supertrend_alerts.render_daily_brief_markdown(
        [],
        title="Daily",
        market_modes={
            "hong_kong": {
                "mode": "seek",
                "representatives": ["^HSI", "2800.HK"],
                "effectiveRepresentatives": ["2800.HK", "513010.SS"],
                "fallbackUsed": ["513010.SS"],
                "missingSymbols": ["^HSI"],
                "effectiveRepresentativeDates": {
                    "2800.HK": "2026-10-02",
                    "513010.SS": "2026-09-30",
                },
                "effectiveRepresentativeStatus": {
                    "2800.HK": "available",
                    "513010.SS": "available",
                },
                "representativeStatus": {
                    "^HSI": "missing",
                    "2800.HK": "available",
                    "513010.SS": "available",
                    "510900.SS": "missing",
                },
                "role": "equity_permission",
                "representativeDateAlignment": "cross_calendar",
            },
        },
    )

    assert "主代表不可用 ^HSI=missing，fallback 513010.SS 正常" in markdown
    assert "日期错位已回放到共同完整交易日" in markdown
    assert "2800.HK@2026-10-02 [available]" in markdown
    assert "513010.SS@2026-09-30 [available]" in markdown
    assert "有效代表不足" not in markdown


def test_daily_brief_blocks_hong_kong_when_effective_representatives_are_insufficient():
    markdown = openclaw_supertrend_alerts.render_daily_brief_markdown(
        [],
        title="Daily",
        market_modes={
            "hong_kong": {
                "mode": "insufficient",
                "representatives": ["^HSI", "2800.HK"],
                "effectiveRepresentatives": ["2800.HK"],
                "fallbackUsed": [],
                "missingSymbols": ["^HSI"],
                "effectiveRepresentativeDates": {"2800.HK": "2026-10-02"},
                "effectiveRepresentativeStatus": {"2800.HK": "available"},
                "representativeStatus": {
                    "^HSI": "missing",
                    "2800.HK": "available",
                    "513010.SS": "stale",
                    "510900.SS": "missing",
                },
                "role": "equity_permission",
            },
        },
    )

    assert "有效代表不足（1/2），阻断市场许可" in markdown
    assert "^HSI=missing" in markdown
    assert "513010.SS=stale" in markdown
    assert "实际采用 2800.HK@2026-10-02 [available]" in markdown


def test_daily_brief_groups_new_entries_prepare_watch_and_risk_sections():
    items = [
        _item("OLD", state="bull", weekly_state="bull", alert_type="hold_bull", priority="low", distance=9.0),
        _item("WAIT", state="bear", weekly_state="bull", alert_type="avoid_bear", priority="low", distance=1.5),
        _item("RISK", state="bear_flip", weekly_state="bull", alert_type="sell_or_risk", actionable=True, distance=7.0),
        {
            **_item("BUY", state="bull_flip", weekly_state="bull", alert_type="buy_candidate", priority="high", actionable=True, distance=4.0),
            "decision": {"permission": "buy", "setup": "breakout", "nextGate": None},
            "executionStatus": {"executable": True, "status": "executable"},
        },
        _item("PULLBACK", state="bull", weekly_state="bull", alert_type="support_test", priority="high", actionable=True, distance=0.8),
    ]

    brief = openclaw_supertrend_alerts.build_daily_brief(items)

    assert [item["symbol"] for item in brief["new_entries"]] == ["BUY"]
    assert [item["symbol"] for item in brief["prepare_watch"]] == ["WAIT"]
    assert [item["symbol"] for item in brief["position_management"]] == ["PULLBACK", "RISK"]
    assert [item["symbol"] for item in brief["background_trends"]] == ["OLD"]


def test_daily_brief_keeps_unconfirmed_bull_flip_out_of_buy_section():
    item = _item(
        "OBSERVE",
        state="bull_flip",
        weekly_state="bull",
        alert_type="buy_candidate",
        priority="high",
        actionable=True,
    )
    item["decision"] = {
        "permission": "watch",
        "setup": "breakout",
        "nextGate": "ADX_BELOW_25",
    }
    item["executionStatus"] = {"executable": False, "status": "not_applicable"}

    brief = openclaw_supertrend_alerts.build_daily_brief([item])

    assert brief["new_entries"] == []
    assert [row["symbol"] for row in brief["bull_flip_watch"]] == ["OBSERVE"]


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


def test_fetch_portfolio_strategies_keeps_only_btc_satellite_primary(monkeypatch):
    strategies = [
        {"strategyId": "theme_alpha", "displayName": "Theme", "paperEnabled": True, "isPrimary": True},
        {"strategyId": "core90_raw_bull10", "displayName": "Raw", "paperEnabled": True, "isPrimary": False},
        {"strategyId": "risk_parity_core_next_open", "displayName": "RP", "paperEnabled": True, "isPrimary": True},
        {"strategyId": "core90_ma200_bull10", "displayName": "Core90", "paperEnabled": True, "isPrimary": False},
        {"strategyId": "btc_supertrend_satellite", "displayName": "BTC", "paperEnabled": True, "isPrimary": True},
    ]

    def fake_get(_base, path, _timeout):
        if path == "/portfolio-strategies":
            return strategies
        return {"strategyId": path.split("/")[2], "state": "READY"}

    monkeypatch.setattr(openclaw_supertrend_alerts, "_api_get", fake_get)

    result = openclaw_supertrend_alerts.fetch_portfolio_strategies("http://example.test/api", 1.0)

    assert [item["strategyId"] for item in result] == ["btc_supertrend_satellite"]


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
                {"orderId": 2, "symbol": "2800.HK", "side": "SELL", "status": "WAITING_OPEN", "due": False, "nextAttemptDate": "2026-08-20"},
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


def _btc_snapshot(*, latest_on, formal_on):
    return {
        "strategyId": "btc_supertrend_satellite",
        "_displayName": "BTC SuperTrend Satellite 7.5%",
        "state": "NOT_DUE",
        "dates": {"signalDate": "2026-10-14", "nextCheck": "2026-10-28"},
        "observation": {
            "values": {
                "btc_close": 100000.0,
                "supertrend_line": 95000.0 if latest_on else 104000.0,
                "supertrend_on": latest_on,
                "formal_supertrend_on": formal_on,
            },
        },
    }


def test_btc_satellite_reports_daily_supertrend_and_formal_switch():
    lines = openclaw_supertrend_alerts._render_portfolio_strategy(
        _btc_snapshot(latest_on=True, formal_on=True)
    )
    markdown = "\n".join(lines)

    assert "BTC 日线 ST: 向上（收盘 100000，ST 线 95000，距 ST 线 +5.0%）" in markdown
    assert "BTC 正式开关（2026-10-14 检查）: 持有 BTC" in markdown
    assert "将在" not in markdown


def test_btc_satellite_flags_a_flip_waiting_for_the_next_check():
    lines = openclaw_supertrend_alerts._render_portfolio_strategy(
        _btc_snapshot(latest_on=False, formal_on=True)
    )
    markdown = "\n".join(lines)

    assert "BTC 日线 ST: 向下（收盘 100000，ST 线 104000，距 ST 线 -4.0%）" in markdown
    assert "BTC 正式开关（2026-10-14 检查）: 持有 BTC" in markdown
    assert "日线 ST 已转向下，将在 2026-10-28 检查时执行" in markdown


def test_non_btc_strategy_has_no_btc_supertrend_lines():
    lines = openclaw_supertrend_alerts._render_portfolio_strategy(
        {"strategyId": "core90_ma200_bull10", "state": "READY", "observation": {"values": {}}}
    )
    assert not any("BTC" in line for line in lines)


def test_daily_brief_puts_primary_portfolio_before_study_scan():
    markdown = openclaw_supertrend_alerts.render_daily_brief_markdown(
        [], title="Daily",
        portfolio_strategies=[_btc_snapshot(latest_on=True, formal_on=True)],
    )

    assert markdown.index("## 主策略纸面执行") < markdown.index("## 学习观察：SuperTrend 扫描")
    assert markdown.index("## 学习观察：SuperTrend 扫描") < markdown.index("## 🔥 今日可开新仓")


def test_daily_brief_reports_independent_strategy_failure_and_stale_market():
    markdown = openclaw_supertrend_alerts.render_daily_brief_markdown(
        [], title="Daily", portfolio_strategies=[],
        portfolio_job_status={
            "dataUpdate": {"ok": False},
            "strategies": {
                "theme_alpha": {"ok": False},
                "risk_parity_core_next_open": {"ok": True},
            },
            "marketReadiness": {
                "us": {"ready": False}, "a_share": {"ready": True},
            },
        },
    )
    assert "组合数据更新任务失败" in markdown
    assert "组合刷新失败: theme_alpha" in markdown
    assert "尚未确认完成日线的市场: us" in markdown
