# Issue 13: production market data recovery

Verified on 2026-09-10 (Asia/Shanghai). Initial transport recovery was followed by the one-time backfill documented below.

## Findings

- Production `analysis.py`, `analysis_data.py`, and `data_source_guard.py` matched the current checkout before the patch. The host Git HEAD was not a reliable deployed-version identifier because deployment copies files outside Git.
- Yahoo downloads failed through the old proxy with TLS errors; a direct request was rate limited. Several old nodes also failed general connectivity checks.
- Yahoo batch downloads can return empty/all-NaN frames without raising. ProviderGuard therefore incorrectly recorded a successful request, resetting failures and suppressing retries.
- `512400.SS` had `fullRefreshRequired=true`, reason `overlap_changed`. Automatic refresh deliberately skipped it.

## Recovery and verification

- Backed up the old proxy configuration and replaced its subscription with the user-supplied subscription. No subscription URL or credentials are stored in this repository.
- The server could not fetch that subscription directly, so it was downloaded on the workstation and transferred privately. Loaded 116 nodes. Hong Kong 01 initially downloaded the caches but later had intermittent TLS failures, so the final selection is the US 04 native direct node (subscription label 2x). SPY and BTC history requests succeeded through it. Enabled persistent selection and subscription updates through the proxy. The subscription refresh API returned HTTP 204.
- A real SPY download returned five daily bars ending 2026-09-09.
- Backed up and fully refreshed only `512400.SS` using the existing administrative command. Its 1,227 daily rows end on 2026-09-09 and its full-refresh flag is false.
- Refreshed all 31 cached non-A-share symbols. Their latest rows were dated September 9 or 10, but three still lacked September 9. Some feeds included a provisional September 10 bar; its presence did not mean that session had closed or the intervening history was complete.
- The production provider-status API returned closed circuits, zero consecutive failures, and no last error for both providers.
- The initial scan restored US and gold representative availability. Hong Kong still used fallback and crypto remained insufficient: Yahoo's raw chart response explicitly returned null close for September 9 for BTC-USD, ETH-USD, and 2800.HK, despite a provisional September 10 row. Individual history requests reproduced the gap, and restarting the backend did not change it. This limitation was subsequently resolved by the backfill below; no freshness gates were disabled.
- Added validation inside the guarded Yahoo operation so None, empty, and all-NaN responses cannot be recorded as successes. Existing cache fallback remains available. This patch does not claim to solve partial-batch freshness reporting or every `dataUpdate.ok` ambiguity.
- Focused red-green tests reproduced four failures before the fix. The final data-source regression selection passed 49 tests, including retry after an empty response. The patched image imports successfully, and its two patched file hashes match the local checkout.

## Deployment and rollback

- Previous image retained as `trading-backend:issue13-backup-20260910`.
- Patched image: `trading-backend:issue13-20260910`, SHA256 `ad3f38877351f3246ef70b1088105200d2c2f746c9dc712f4cf28d35dccc6282`. Built from the actual running image with only the two patched Python files; deployed as `trading-backend:latest`.
- Server source/data backups: `/home/zsd/trading/backups/issue13-20260910-TIpk14`.
- Proxy configuration backup before successful replacement: `/opt/clash/trading-issue13-p_2f8sw6/runtime.yaml` (private).
- No manual portfolio execution or account replay was performed. Snapshot/order advancement and the next scheduled cycle remain separate verification steps.

## Follow-up: one-time September 9 backfill

The user authorized a data-only repair rather than another application change. All three missing daily rows have now been filled:

| Symbol | Source | Open | High | Low | Close | Volume |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| BTC-USD | CoinMarketCap, asset 1, USD | 78440.5978110523 | 79737.3001997173 | 77768.1480717258 | 78259.5196663801 | 29192409298.11 |
| ETH-USD | CoinMarketCap, asset 1027, USD | 2484.8941777351 | 2522.3696312206 | 2443.7024230978 | 2466.9138158201 | 14955608804.02 |
| 2800.HK | Tencent historical daily, hk02800 | 25.90 | 25.94 | 25.72 | 25.84 | 337893889 |

Crypto sessions use UTC and volume is aggregate USD turnover. Hong Kong uses the exchange session date, HKD prices, and volume in shares. September 7 and 8 OHLCV matched existing Yahoo caches within price floating-point and volume rounding tolerances before insertion. Coinbase candles and Yahoo hourly bars were also inspected, but were not used: exchange-specific volume and summed Yahoo crypto hourly volume are not interchangeable with the existing daily turnover series.

The staged repair asserted exactly one new daily row per symbol, no changes to existing OHLCV, unchanged prior daily indicators, valid candle bounds, and successful Parquet round trips. Daily and weekly indicators were recalculated using the deployed functions. The backend was briefly stopped during the six-file replacement; SHA checks prevented overwriting any file changed since staging. It was then restarted.

Raw responses, request parameters, per-symbol overlap comparisons, before/after Parquet files, and hashes are retained on the server at `/home/zsd/trading/backend/data/.manual-repairs/20260909-0u1aiu4f/manifest.json`. The one-time script is in `/home/zsd/trading/backups/issue13-20260910-TIpk14/backfill.py`; it is not an application or scheduled code change.

Final verification: all 31 Yahoo-backed cached symbols have complete September 9 OHLCV. The production scan marks BTC-USD, ETH-USD, and 2800.HK available with September 9 decision dates. Hong Kong no longer needs fallback for the missing primary. Crypto now reports `survival`, a strategy result rather than `insufficient` data. This resolves the missing-row limitation recorded above; account replay and scheduled-cycle verification were not performed by this repair.
