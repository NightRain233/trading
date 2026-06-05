import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "research_a_share_etf_st_rs_fair_comparison.py"
SPEC = importlib.util.spec_from_file_location("research_a_share_etf_st_rs_fair_comparison", SCRIPT_PATH)
research_a_share_etf_st_rs_fair_comparison = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(research_a_share_etf_st_rs_fair_comparison)


def test_window_label_includes_name_and_dates():
    label = research_a_share_etf_st_rs_fair_comparison._window_label(
        {"name": "recent_5y", "start": "2021-05-06", "end": "2026-06-05"}
    )

    assert label == "recent_5y: 2021-05-06 to 2026-06-05"


def test_summarize_window_payload_keeps_only_requested_strategy_stats():
    payload = {
        "summary": {
            "rs_monthly_macd_baseline": {
                "totalReturnPct": 10.0,
                "maxDrawdownPct": 5.0,
                "returnDrawdownRatio": 2.0,
                "averageExposure": 0.4,
                "extra": "ignored",
            },
            "daily_st_equal_weight": {
                "totalReturnPct": -3.0,
                "maxDrawdownPct": 9.0,
                "returnDrawdownRatio": -0.333333,
                "averageExposure": 0.9,
            },
            "not_part_of_report": {"totalReturnPct": 999.0},
        }
    }

    summary = research_a_share_etf_st_rs_fair_comparison._summarize_window_payload(
        payload,
        strategy_keys=["rs_monthly_macd_baseline", "daily_st_equal_weight"],
    )

    assert list(summary) == ["rs_monthly_macd_baseline", "daily_st_equal_weight"]
    assert summary["rs_monthly_macd_baseline"] == {
        "totalReturnPct": 10.0,
        "maxDrawdownPct": 5.0,
        "returnDrawdownRatio": 2.0,
        "averageExposure": 0.4,
    }
    assert summary["daily_st_equal_weight"]["totalReturnPct"] == -3.0


def test_build_fair_comparison_uses_same_universe_params_for_each_window(monkeypatch):
    calls = []

    def fake_build_research(start, end, universe_file, data_dir):
        calls.append((start, end, str(universe_file), str(data_dir)))
        return {
            "params": {
                "start": start,
                "end": end,
                "universeFile": str(universe_file),
                "dataDir": str(data_dir),
                "symbolCount": 2,
            },
            "summary": {
                "rs_monthly_macd_baseline": {
                    "totalReturnPct": 1.0,
                    "maxDrawdownPct": 2.0,
                    "returnDrawdownRatio": 0.5,
                    "averageExposure": 0.3,
                },
                "equal_weight_buy_hold": {
                    "totalReturnPct": 2.0,
                    "maxDrawdownPct": 2.0,
                    "returnDrawdownRatio": 1.0,
                    "averageExposure": 1.0,
                },
                "daily_st_equal_weight": {
                    "totalReturnPct": 3.0,
                    "maxDrawdownPct": 2.0,
                    "returnDrawdownRatio": 1.5,
                    "averageExposure": 0.8,
                },
                "weekly_daily_st_equal_weight": {
                    "totalReturnPct": 4.0,
                    "maxDrawdownPct": 2.0,
                    "returnDrawdownRatio": 2.0,
                    "averageExposure": 0.7,
                },
                "daily_st_top5_rs": {
                    "totalReturnPct": 5.0,
                    "maxDrawdownPct": 2.0,
                    "returnDrawdownRatio": 2.5,
                    "averageExposure": 0.6,
                },
            },
            "annual": {},
        }

    monkeypatch.setattr(
        research_a_share_etf_st_rs_fair_comparison.pure_st,
        "build_research",
        fake_build_research,
    )

    result = research_a_share_etf_st_rs_fair_comparison.build_fair_comparison(
        windows=[
            {"name": "short", "start": "2024-01-01", "end": "2024-01-31"},
            {"name": "long", "start": "2023-01-01", "end": "2024-01-31"},
        ],
        universe_file=Path("universe.json"),
        data_dir=Path("data"),
    )

    assert calls == [
        ("2024-01-01", "2024-01-31", "universe.json", "data"),
        ("2023-01-01", "2024-01-31", "universe.json", "data"),
    ]
    assert result["params"]["windowCount"] == 2
    assert result["windows"]["short"]["summary"]["weekly_daily_st_equal_weight"]["totalReturnPct"] == 4.0
