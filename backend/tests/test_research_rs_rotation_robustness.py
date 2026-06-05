import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "research_rs_rotation_robustness.py"
SPEC = importlib.util.spec_from_file_location("research_rs_rotation_robustness", SCRIPT_PATH)
research_rs_rotation_robustness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(research_rs_rotation_robustness)


def test_a_share_broad_universe_excludes_sector_and_theme_etfs():
    universes = research_rs_rotation_robustness.build_static_universes()

    assert "510300.SS" in universes["a_share_broad"]
    assert "159915.SZ" in universes["a_share_broad"]
    assert "512760.SS" not in universes["a_share_broad"]
    assert "515790.SS" not in universes["a_share_broad"]
    assert "515070.SS" not in universes["a_share_broad"]


def test_broad_style_universe_adds_style_without_sector_etfs():
    universes = research_rs_rotation_robustness.build_static_universes()

    assert "510880.SS" in universes["a_share_broad_style"]
    assert "512890.SS" in universes["a_share_broad_style"]
    assert "512880.SS" not in universes["a_share_broad_style"]
    assert "512010.SS" not in universes["a_share_broad_style"]


def test_filter_spec_uses_asset_class_specific_market_filters():
    specs = research_rs_rotation_robustness.build_filter_specs()

    global_filters = specs["global_available"]["perClassFilters"]
    assert global_filters["a_share"] == ("510300.SS", "monthly_macd")
    assert global_filters["us"] == ("SPY", "monthly_macd")
    assert global_filters["crypto"] == ("BTC-USD", "monthly_macd")
    assert global_filters["commodity"] == ("GC=F", "monthly_macd")


def test_annual_and_rolling_stats_identify_weak_windows():
    curve = [
        {"date": "2021-01-01", "equity": 1.0, "drawdownPct": 0.0},
        {"date": "2021-12-31", "equity": 1.2, "drawdownPct": 2.0},
        {"date": "2022-12-31", "equity": 0.9, "drawdownPct": 25.0},
        {"date": "2023-12-31", "equity": 1.0, "drawdownPct": 18.0},
        {"date": "2024-12-31", "equity": 1.5, "drawdownPct": 4.0},
        {"date": "2025-12-31", "equity": 1.8, "drawdownPct": 3.0},
    ]

    annual = research_rs_rotation_robustness.annual_stats(curve)
    rolling = research_rs_rotation_robustness.rolling_year_stats(curve, years=3)

    assert min(row["returnPct"] for row in annual) < 0
    assert rolling[0]["startYear"] == "2021"
    assert rolling[0]["endYear"] == "2023"
    assert rolling[0]["maxDrawdownPct"] == 25.0
