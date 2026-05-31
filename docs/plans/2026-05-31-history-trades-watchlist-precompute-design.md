# History Trades Watchlist Precompute Design

## Goal

Make `/history-trades` usable for the symbols already listed in `backend/watchlist.json` by precomputing five years of SuperTrend replay results into the existing SQLite cache.

## Scope

Only watchlist symbols are included. The precompute flow should not add symbols from universe files or from arbitrary local parquet files.

The default replay window is the last five years, ending at the current local date when the command or API call runs. Missing daily data should be downloaded through the existing market-data update path, which also writes the daily and weekly parquet files used elsewhere in the app.

## Backend Design

Reuse the existing `history_trade_reviews` SQLite table and cache key format. Keep `GET /api/history-trades` unchanged so the page can continue to read cached payloads or compute on demand.

Update `precompute_history_trades` so it:

- Builds its symbol catalog from `load_watchlist()`.
- Defaults `start` to five years before today when the caller does not pass a start date.
- Tries `batch_fetch_and_update([symbol])` when `DATA_DIR/{symbol}.parquet` is missing.
- Skips the symbol with a clear reason if download still does not produce local data.
- Returns counts for computed, cached, downloaded, skipped missing, and failed symbols.

Add a local CLI entry point in `backend/main.py` for a single-symbol smoke run or a full watchlist run:

```bash
PYTHONPATH=. uv run python main.py --precompute-history-trades --symbol 510500.SS
PYTHONPATH=. uv run python main.py --precompute-history-trades
```

## Testing

Use focused backend tests around `backend/tests/test_history_trades_api.py`.

Tests should verify:

- Precompute uses only watchlist symbols, not universe/data catalog symbols.
- Missing parquet triggers the existing download/update path before replay.
- The default start date is exactly five years before a patched current date.
- The CLI can target one symbol without requiring the API server.

## Operational Plan

After implementation, run the backend history-trades tests. Then run the CLI for one watchlist symbol and inspect SQLite for a matching cache row. Leave the full watchlist run to the user because it may download and compute every symbol.
