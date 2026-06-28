# Eastmoney A-Share Data Source Design

## Goal

Eliminate false split crashes and other Yahoo Finance history corruption for
Chinese securities while preserving the existing multi-market behavior for US
stocks, futures, FX, and crypto.

## Decisions

- Use Eastmoney forward-adjusted (`fqt=1`, equivalent to `qfq`) daily OHLCV as
  the canonical source for `.SS` and `.SZ` symbols.
- Keep yfinance as the source for all non-Chinese symbols.
- Refresh the complete configured retention window for Chinese symbols. A
  forward-adjusted history can change after a new corporate action, so merging
  only the latest rows can mix incompatible adjustment bases.
- Keep the last valid parquet when Eastmoney is unavailable or returns
  suspicious data.
- Retain the existing split detector as an integrity warning, not as the
  primary correction mechanism.
- Keep manual split-adjustment configuration out of the main path. A source
  correction is safer than treating isolated bad rows and pre-listing data as
  splits.

## Architecture

`analysis_data.py` owns market classification, Eastmoney download/parsing,
source selection, integrity validation, chronological merge cleanup, and source
version metadata. Both `fetch_stock_data` and `batch_fetch_and_update` use these
shared helpers.

For Chinese symbols, a refresh downloads the complete retention window and
replaces the cached OHLCV base before indicators are calculated. For other
symbols, the current yfinance incremental merge remains in place.

A per-symbol sidecar records the source version used to build each Chinese
parquet. Existing Yahoo-built parquets have no marker and are therefore forced
through one Eastmoney refresh even when their file modification time is still
fresh. This provides automatic in-place migration after deployment.

## Data Integrity

Every merged or replacement frame is normalized to a timezone-naive
`DatetimeIndex`, deduplicated, and sorted before returns or indicators are
calculated.

Chinese source data is rejected when:

- required OHLCV columns are missing;
- OHLC prices are non-positive or internally inconsistent;
- consecutive closes contain an absolute move greater than 40%.

On rejection or download failure, an existing valid parquet remains untouched
and the missing source-version marker causes a later request to retry.

## Batch Refresh

The batch path partitions requested symbols by provider:

- Eastmoney requests run concurrently per Chinese symbol and fetch the full
  retention window.
- yfinance continues to batch non-Chinese symbols from their earliest required
  incremental date.

Only successful Chinese replacements write the current source-version marker.
The daily and weekly parquets and in-memory summary cache are then rebuilt from
the same corrected daily history.

## Migration and Deployment

The source-version marker makes normal traffic migrate watched Chinese symbols
automatically. A small migration command also discovers all persisted
`.SS/.SZ` daily parquets, invalidates their old markers, and refreshes them so
deployment can repair the entire server dataset immediately.

Deployment verification checks:

- all persisted Chinese daily indexes are monotonically increasing;
- no retained Chinese series has an absolute daily close move above 40%;
- `515880.SS` is continuous across 2026-02-03;
- its daily and weekly indicator files were regenerated.

## Testing

Tests cover chronological merging, Eastmoney parameter and parser behavior,
provider routing, rejection of corrupt Chinese data, source-version cache
invalidation, batch full replacement, and migration symbol discovery. The
time-sensitive SuperTrend test uses dates relative to runtime so the baseline
does not expire again.
