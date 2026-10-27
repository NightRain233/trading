import numpy as np
import pandas as pd

import analysis_weinstein as aw


def _weekly(closes, volume=None):
    index = pd.date_range("2024-01-07", periods=len(closes), freq="W-SUN")
    close = pd.Series(np.asarray(closes, dtype=float), index=index)
    frame = pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close,
                          "Volume": volume if volume is not None else np.full(len(closes), 100.0)}, index=index)
    mid = close.rolling(20).mean()
    sd = close.rolling(20).std(ddof=0)
    frame["BOLL_Mid"], frame["BOLL_Upper"], frame["BOLL_Lower"] = mid, mid + 2 * sd, mid - 2 * sd
    return frame


def test_benchmark_by_market():
    assert aw.benchmark_for("510300.SS") == "000300.SS"
    assert aw.benchmark_for("159915.SZ") == "000300.SS"
    assert aw.benchmark_for("2800.HK") == "2800.HK"
    assert aw.benchmark_for("QQQ") == "SPY"
    assert aw.benchmark_for("BTC-USD") is None
    assert aw.benchmark_for("GC=F") is None


def test_stage_sequence_through_a_full_cycle():
    closes = list(np.linspace(100, 60, 50)) + [60.0] * 30 + list(np.linspace(60, 120, 40))
    frame = _weekly(closes)
    stages = aw.stage_series(frame["Close"], frame["Close"].rolling(30).mean())

    assert np.isnan(stages.iloc[0])
    assert stages.iloc[45] == 4          # falling average, price below
    assert stages.iloc[79] == 1          # flat base after a decline
    assert stages.iloc[-1] == 2          # rising average, price above


def test_flat_after_advance_is_stage_three():
    closes = list(np.linspace(60, 120, 60)) + [120.0] * 30
    frame = _weekly(closes)
    stages = aw.stage_series(frame["Close"], frame["Close"].rolling(30).mean())
    assert stages.iloc[-1] == 3


def test_relative_strength_aligns_by_week_and_uses_26_weeks():
    own = _weekly(np.linspace(100, 200, 40))["Close"]
    bench = own * 0 + 100.0
    bench.iloc[-27:] = np.linspace(100, 110, 27)
    rs = aw.relative_strength(own, bench)

    expected = own.iloc[-1] / own.iloc[-27] - 1 - (110 / 100 - 1)
    assert np.isclose(rs.iloc[-1], expected)
    assert aw.relative_strength(own, None) is None


def test_summary_reports_stage_breakout_and_volume(monkeypatch):
    closes = [100.0] * 60 + [100.5, 101.0, 101.5, 102.0, 120.0]
    volume = np.full(len(closes), 100.0)
    volume[-1] = 300.0
    monkeypatch.setattr(aw, "_benchmark_weekly_close", lambda benchmark: None)

    summary = aw.weinstein_summary("512480.SS", _weekly(closes, volume))

    assert summary["stage"] == 2
    assert summary["stageLabel"] == "上涨"
    assert summary["bbState"] == "squeeze_breakout"
    assert np.isclose(summary["volumeRatio"], 3.0)
    assert summary["rs26"] is None
    assert summary["ma30Distance"] > 0


def test_summary_needs_enough_history():
    assert aw.weinstein_summary("SPY", _weekly([100.0] * 20)) is None


def test_price_against_the_slope_reads_as_transition_stage():
    rising = list(np.linspace(60, 120, 60))
    frame = _weekly(rising + [90.0])
    stages = aw.stage_series(frame["Close"], frame["Close"].rolling(30).mean())
    assert stages.iloc[-1] == 3

    falling = list(np.linspace(120, 60, 60))
    frame = _weekly(falling + [95.0])
    stages = aw.stage_series(frame["Close"], frame["Close"].rolling(30).mean())
    assert stages.iloc[-1] == 1


def test_scan_item_reports_previous_stage_and_history(monkeypatch):
    monkeypatch.setattr(aw, "_benchmark_weekly_close", lambda benchmark: None)
    rising = list(np.linspace(60, 120, 60))
    item = aw.weinstein_scan_item("QQQ", _weekly(rising + [90.0]), weeks=10)

    assert item["stage"] == 3
    assert item["previousStage"] == 2
    assert len(item["history"]) == 10
    assert item["history"][-1]["close"] == 90.0
    assert item["history"][-1]["stage"] == 3


def test_scan_endpoint_reads_cached_weekly_bars(monkeypatch, tmp_path):
    import main

    rising = list(np.linspace(60, 120, 60))
    _weekly(rising).to_parquet(tmp_path / "QQQ_weekly.parquet")
    monkeypatch.setattr(main, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(aw, "_benchmark_weekly_close", lambda benchmark: None)
    monkeypatch.setattr(main, "load_watchlist", lambda: [
        {"id": "g", "name": "美股", "symbols": [{"symbol": "qqq", "alias": ""}, {"symbol": "MISSING", "alias": ""}]},
    ])

    main._weinstein_scan_cache.update(key=None, items=None)
    items = main.weinstein_scan(weeks=12)

    assert [item["symbol"] for item in items] == ["QQQ"]
    assert items[0]["name"] == "QQQ"
    assert items[0]["rule"]["key"] in {"entry", "hold"}
    assert items[0]["stage"] == 2
    assert len(items[0]["history"]) == 12


def test_scan_endpoint_reuses_result_until_files_change(monkeypatch, tmp_path):
    import os
    import main

    _weekly(list(np.linspace(60, 120, 60))).to_parquet(tmp_path / "QQQ_weekly.parquet")
    monkeypatch.setattr(main, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(aw, "_benchmark_weekly_close", lambda benchmark: None)
    monkeypatch.setattr(main, "load_watchlist", lambda: [{"id": "g", "name": "美股", "symbols": [{"symbol": "QQQ", "alias": ""}]}])
    main._weinstein_scan_cache.update(key=None, items=None)
    calls = []
    real = aw.weinstein_scan_item
    monkeypatch.setattr(aw, "weinstein_scan_item", lambda *a, **k: calls.append(1) or real(*a, **k))

    main.weinstein_scan(weeks=12)
    main.weinstein_scan(weeks=12)
    assert len(calls) == 1

    path = tmp_path / "QQQ_weekly.parquet"
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 10))
    main.weinstein_scan(weeks=12)
    assert len(calls) == 2


def test_small_penetrations_keep_the_stage():
    rising = list(np.linspace(60, 120, 60))
    frame = _weekly(rising)
    ma = frame["Close"].rolling(30).mean()
    last_ma = float(ma.iloc[-1])
    # one week 1% under a rising average stays stage 2; 5% under turns stage 3
    near = _weekly(rising + [last_ma * 0.99])
    far = _weekly(rising + [last_ma * 0.95])
    assert aw.stage_series(near["Close"], near["Close"].rolling(30).mean()).iloc[-1] == 2
    assert aw.stage_series(far["Close"], far["Close"].rolling(30).mean()).iloc[-1] == 3


def test_rule_state_matches_plain_rules():
    assert aw.rule_state({"stage": 2, "weeksInStage": 2, "rs26": 0.1, "ma30Distance": 0.03})["key"] == "entry"
    assert aw.rule_state({"stage": 2, "weeksInStage": 9, "rs26": 0.1, "ma30Distance": 0.03})["key"] == "hold"
    assert aw.rule_state({"stage": 3, "weeksInStage": 1, "rs26": 0, "ma30Distance": -0.03})["key"] == "exit"
    assert aw.rule_state({"stage": 4, "weeksInStage": 5, "rs26": -0.1, "ma30Distance": -0.1})["key"] == "out"
    assert aw.rule_state(None)["key"] == "wait"


# --- frozen 2026-10-27 data: expected numbers were worked out by hand from the CSVs ---

from datetime import datetime, timezone
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "weinstein_2026_10_27"
TUESDAY_EVENING = datetime(2026, 10, 27, 15, 0, tzinfo=timezone.utc)   # 23:00 Shanghai, 11:00 New York
SATURDAY = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)


def _fixture(symbol):
    return pd.read_csv(FIXTURE_DIR / f"{symbol}.csv", index_col="Date", parse_dates=True)


def _fixture_summary(monkeypatch, symbol, now=TUESDAY_EVENING):
    monkeypatch.setattr(aw, "_benchmark_weekly_close", lambda benchmark: _fixture(benchmark)["Close"] if benchmark == "SPY" else None)
    return aw.weinstein_summary(symbol, _fixture(symbol), now=now)


def test_cross_market_etfs_are_not_compared_with_csi300():
    assert aw.benchmark_for("518880.SS") is None      # gold
    assert aw.benchmark_for("513100.SS") is None      # Nasdaq 100
    assert aw.benchmark_for("513180.SS") == "2800.HK"  # Hang Seng tech
    assert aw.benchmark_for("510880.SS") == "000300.SS"


def test_unfinished_week_keeps_the_last_closed_week_for_stage_calls(monkeypatch):
    qqq = _fixture_summary(monkeypatch, "QQQ")

    assert qqq["weekComplete"] is False
    assert qqq["weekLabel"] == "2026-11-01"
    assert np.isclose(qqq["ma30"], 708.1192, atol=1e-3)
    closed = qqq["closed"]
    assert closed["weekLabel"] == "2026-10-25"
    assert np.isclose(closed["close"], 704.40, atol=0.01)
    assert np.isclose(closed["ma30"], 703.6579, atol=1e-3)
    assert closed["stage"] == 2


def test_week_is_complete_after_friday_close_but_crypto_waits_for_sunday(monkeypatch):
    assert _fixture_summary(monkeypatch, "QQQ", now=SATURDAY)["weekComplete"] is True
    assert _fixture_summary(monkeypatch, "BTC-USD", now=SATURDAY)["weekComplete"] is False


def test_levels_are_solved_against_the_average_the_close_moves(monkeypatch):
    # sell line x = 0.98 * s29 / (30 - 0.98), s29 = the 29 closed weeks before this one;
    # distance from last week's close (stable), and from the live close (drifts)
    expected = {
        "QQQ": (693.1594, -0.01596, 0.60, -0.03402),
        "SPY": (731.1060, -0.03798, 2.65, -0.04778),
        "BTC-USD": (71678.13, -0.10429, 1.64, -0.10506),
    }
    for symbol, (price, change, moves, now) in expected.items():
        (level,) = _fixture_summary(monkeypatch, symbol)["levels"]
        assert (level["side"], level["becomes"]) == ("below", 3), symbol
        assert np.isclose(level["price"], price, rtol=1e-6), symbol
        assert np.isclose(level["change"], change, atol=2e-5), symbol
        assert np.isclose(level["typicalMoves"], moves, atol=0.01), symbol
        assert np.isclose(level["changeNow"], now, atol=2e-5), symbol


def test_gold_recovery_line_leads_to_a_base_not_an_advance(monkeypatch):
    gold = _fixture_summary(monkeypatch, "518880.SS")

    assert gold["rsBenchmark"] is None and gold["rs26"] is None
    (level,) = gold["levels"]
    assert (level["side"], level["becomes"]) == ("above", 1)   # the average still falls
    assert np.isclose(level["price"], 9.2200, atol=1e-4)
    assert np.isclose(level["change"], 0.12453, atol=1e-4)
    assert np.isclose(level["changeNow"], 0.12893, atol=1e-4)
    assert np.isclose(gold["typicalWeeklyMove"], 0.03231, atol=1e-4)


def test_level_close_lands_on_the_line_it_was_solved_for():
    closes = pd.Series(np.linspace(60, 120, 60))
    (level,) = aw.stage_levels(closes, 2, 120.0, 0.02)
    extended = pd.concat([closes, pd.Series([level["price"]])], ignore_index=True)
    ma = extended.rolling(30).mean()
    assert np.isclose(level["price"], ma.iloc[-1] * 0.98)
    # a hair below the line flips to stage 3, a hair above stays stage 2
    for nudge, stage in ((-1e-6, 3), (1e-6, 2)):
        bumped = extended.copy()
        bumped.iloc[-1] = level["price"] * (1 + nudge)
        assert aw.stage_series(bumped, bumped.rolling(30).mean()).iloc[-1] == stage


def test_band_position_and_closed_week_volume(monkeypatch):
    qqq = _fixture_summary(monkeypatch, "QQQ")

    assert np.isclose(qqq["bandPosition"], 0.4956, atol=1e-3)
    assert np.isclose(qqq["closed"]["bandPosition"], 0.3181, atol=1e-3)   # (704.40 - 680.61) / (755.41 - 680.61)
    # the closed week's volume is compared with the ten weeks before it, not a two-day week
    assert qqq["closed"]["volumeRatio"] > 0.8


def test_flat_average_has_no_price_levels():
    assert aw.stage_levels(pd.Series([100.0] * 40), 3, 101.0, 0.02) == []


def test_live_session_reports_whether_the_latest_bar_has_closed():
    assert aw.live_session("QQQ", "2026-10-27", now=TUESDAY_EVENING) == {"asOf": "2026-10-27", "sessionComplete": False}
    assert aw.live_session("510300.SS", "2026-10-27", now=TUESDAY_EVENING)["sessionComplete"] is True
    assert aw.live_session("QQQ", None) == {"asOf": None, "sessionComplete": None}
