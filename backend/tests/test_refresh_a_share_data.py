import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import analysis_data


def _write_daily(path: Path) -> None:
    index = pd.to_datetime(["2026-06-25", "2026-06-26"])
    close = pd.Series([1.0, 1.01], index=index)
    pd.DataFrame(
        {
            "Open": close,
            "High": close + 0.01,
            "Low": close - 0.01,
            "Close": close,
            "Volume": 1000,
        },
        index=index,
    ).to_parquet(path)


def test_discover_a_share_symbols_uses_daily_parquets_and_watchlist(tmp_path):
    import refresh_a_share_data

    _write_daily(tmp_path / "515880.SS.parquet")
    _write_daily(tmp_path / "515880.SS_weekly.parquet")
    _write_daily(tmp_path / "SPY.parquet")
    watchlist_path = tmp_path / "watchlist.json"
    watchlist_path.write_text(
        json.dumps(
            [
                {
                    "symbols": [
                        {"symbol": "512010.SS", "alias": "医药"},
                        {"symbol": "SPY", "alias": ""},
                    ]
                }
            ]
        ),
        encoding="utf-8",
    )

    symbols = refresh_a_share_data.discover_a_share_symbols(
        tmp_path,
        watchlist_path,
    )

    assert symbols == ["512010.SS", "515880.SS"]


def test_run_migration_force_invalidates_markers_and_reports_success(tmp_path):
    import refresh_a_share_data

    symbols = ["512010.SS", "515880.SS"]
    for symbol in symbols:
        parquet_path = tmp_path / f"{symbol}.parquet"
        _write_daily(parquet_path)
        analysis_data._write_data_source_metadata(str(parquet_path), symbol)

    def fake_batch(requested):
        assert requested == symbols
        for symbol in symbols:
            assert not analysis_data._has_current_data_source(
                str(tmp_path / f"{symbol}.parquet"),
                symbol,
            )
        return {symbol: object() for symbol in symbols}

    with patch.object(
        refresh_a_share_data,
        "batch_fetch_and_update",
        side_effect=fake_batch,
    ) as mock_batch, patch.object(
        refresh_a_share_data,
        "_verify_refreshed_symbol",
        return_value=True,
    ):
        report = refresh_a_share_data.run_migration(
            symbols,
            data_dir=tmp_path,
            force=True,
        )

    mock_batch.assert_called_once_with(symbols)
    assert report == {
        "requested": 2,
        "refreshed": symbols,
        "failed": [],
    }


def test_run_migration_reports_symbols_without_current_output(tmp_path):
    import refresh_a_share_data

    with patch.object(
        refresh_a_share_data,
        "batch_fetch_and_update",
        return_value={},
    ), patch.object(
        refresh_a_share_data,
        "_verify_refreshed_symbol",
        return_value=False,
    ):
        report = refresh_a_share_data.run_migration(
            ["515880.SS"],
            data_dir=tmp_path,
            force=False,
        )

    assert report["refreshed"] == []
    assert report["failed"] == ["515880.SS"]


def test_verify_refreshed_symbol_requires_regenerated_weekly_indicators(tmp_path):
    import refresh_a_share_data

    daily_path = tmp_path / "515880.SS.parquet"
    _write_daily(daily_path)
    analysis_data._write_data_source_metadata(
        str(daily_path),
        "515880.SS",
    )

    assert not refresh_a_share_data._verify_refreshed_symbol(
        tmp_path,
        "515880.SS",
    )
