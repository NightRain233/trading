# Data Source Protection Design

## Goal

Protect Eastmoney and Yahoo Finance from duplicate, bursty, and wasteful
requests while keeping the API available from cached parquet data. A provider
failure must not look like a missing symbol, corrupt an existing cache, or
cause every Uvicorn worker to repeat the same refresh.

## Scope

- Add one provider-protection layer shared by Eastmoney and Yahoo Finance.
- Coordinate request spacing, duplicate suppression, and circuit state across
  Uvicorn worker processes.
- Make scheduled prewarming single-leader and reduce it to the application's
  intended twice-daily monitoring cadence.
- Use incremental Eastmoney requests in the common case without mixing
  incompatible forward-adjustment bases.
- Expose provider health and return correct upstream-error semantics.
- Support an operational kill switch so Eastmoney can cool down without
  stopping the API.

The design does not introduce a database, Redis, a separate collector service,
or a third market-data vendor.

## Chosen Approach

Use a lightweight file-backed provider guard in the existing backend process.
The backend data directory is already a persistent host-mounted volume and is
shared by all Uvicorn workers. Unix `flock` locks and small JSON state files
therefore provide sufficient cross-process coordination without another
service.

The guard serializes each provider, enforces a minimum request interval,
suppresses recently completed requests for the same symbol, records failures,
and opens a circuit after rate-limit or repeated transient failures.

## Components

### Provider Guard

Create `backend/data_source_guard.py` with:

- `ProviderConfig`: enabled flag, minimum interval, duplicate window, retry
  count, backoff, failure threshold, and circuit cooldown.
- `ProviderGuard`: wraps a network callable under an inter-process provider
  lock.
- Typed errors:
  - `ProviderDisabledError`
  - `ProviderCircuitOpenError`
  - `ProviderRecentlySucceeded`
  - `ProviderRequestError`
- A status snapshot for the health endpoint.

Each provider has:

- `data/.provider-state/<provider>.lock`
- `data/.provider-state/<provider>.json`

The JSON state records:

- last attempt and last success time;
- next allowed request time;
- consecutive failures;
- circuit-open deadline;
- last error category and message;
- recent per-symbol success times.

State updates happen while holding the provider lock and use atomic
replacement. Stale per-symbol entries are pruned.

### Failure Policy

Only one configured route is used for an Eastmoney request. The current
automatic direct-then-proxy retry is removed because it doubles traffic and
the configured proxy may use an unsuitable overseas exit.

Failures are classified:

- HTTP 403/429, empty reply, connection reset, and remote disconnect are
  treated as blocking signals. They open the circuit immediately and are not
  retried.
- Timeouts and HTTP 5xx are transient. They receive at most one retry with
  exponential backoff.
- Other request or parsing failures increment the failure count. The circuit
  opens after three consecutive failures.
- A successful request resets the failure count and closes the circuit.

Defaults:

- Eastmoney minimum interval: 1.5 seconds.
- Yahoo minimum interval: 1.0 second.
- Duplicate-success window: 5 minutes per symbol/batch key.
- Circuit cooldown: 30 minutes.

All values are environment-configurable.

### Eastmoney Refresh Strategy

Eastmoney `fqt=1` history is forward-adjusted. A corporate action can change
historical prices, so blindly merging only new rows can mix adjustment bases.
The normal refresh therefore uses a protected hybrid:

1. A new symbol, legacy source marker, or overdue full calibration downloads
   the configured retention window and replaces OHLCV.
2. Otherwise request from 14 calendar days before the cached last date.
3. Compare overlapping completed OHLC rows, excluding the newest potentially
   changing bar.
4. If overlap differs beyond numeric tolerance, treat it as a rebase and make
   one protected full-history request.
5. If overlap is stable, merge the incremental frame.
6. Force a full calibration every seven days.

The source sidecar advances to `eastmoney-qfq-v2` and stores
`lastFullRefreshAt`. Existing `v1` caches therefore receive one safe full
calibration after the feature is enabled.

Invalid or failed downloads never replace a valid parquet.

### Yahoo Finance

Wrap both `Ticker.history` and batched `yf.download` calls in the Yahoo guard.
Yahoo keeps its current incremental behavior. The existing in-process download
lock remains for thread safety, while the provider guard supplies
cross-process serialization, duplicate suppression, backoff, and circuit
state.

### Single-Leader Prewarm

At FastAPI startup each worker attempts a non-blocking, long-lived lock:

`data/.provider-state/prewarm-leader.lock`

Only the winner starts the background prewarm thread. The OS releases the lock
if that worker exits, allowing another worker to become leader after restart.

The default schedule changes from 09:00/12:00/15:00/21:00 to 12:00/21:00
Asia/Shanghai, matching the documented twice-daily workflow. The hours remain
environment-configurable.

`BACKGROUND_PREWARM_ENABLED=false` disables the scheduler independently of
provider switches.

### Availability and Error Semantics

Cached data remains the primary availability mechanism:

- If a refresh fails and valid parquet exists, return the cached data and mark
  it stale.
- If no valid cache exists and the provider is disabled, circuit-open, or
  unavailable, raise a typed market-data-unavailable error.
- `GET /api/quote/{symbol}` maps that error to HTTP 503 with `Retry-After`
  when available.
- A genuine unsupported or insufficient symbol remains HTTP 404.
- Batch/list endpoints continue returning available cached symbols and report
  provider health through metadata rather than failing the whole batch.

Add `GET /api/data-sources/status`, returning for each provider:

- configured enabled state;
- circuit state and open-until time;
- last attempt/success;
- consecutive failure count;
- sanitized last error category/message;
- next allowed request time.

### Configuration

Add these environment variables with safe defaults:

```text
EASTMONEY_FETCH_ENABLED=true
EASTMONEY_PROXY_MODE=direct
EASTMONEY_MIN_INTERVAL_SECONDS=1.5
EASTMONEY_CIRCUIT_COOLDOWN_SECONDS=1800
EASTMONEY_FULL_REFRESH_DAYS=7
EASTMONEY_INCREMENTAL_OVERLAP_DAYS=14

YAHOO_FETCH_ENABLED=true
YAHOO_MIN_INTERVAL_SECONDS=1.0
YAHOO_CIRCUIT_COOLDOWN_SECONDS=900

BACKGROUND_PREWARM_ENABLED=true
PREWARM_HOURS=12,21
```

Docker Compose passes these values through but keeps the repository defaults
usable for local development.

## Request Flow

For an A-share cache refresh:

1. Cache layer decides a symbol is stale.
2. Eastmoney strategy chooses incremental or full mode from cache metadata.
3. Provider guard checks enabled state, circuit state, duplicate key, and
   request spacing under the cross-process lock.
4. The guarded request runs through exactly one network route.
5. On success, the strategy validates and merges or replaces data.
6. Daily/weekly parquets and metadata are atomically updated.
7. On failure, the old cache remains and provider state records the failure.

## Testing

Unit tests cover:

- cross-process-compatible state transitions using temporary state paths;
- minimum spacing and duplicate-key suppression with injected clock/sleep;
- immediate circuit opening for blocking signals;
- transient retry/backoff and threshold-based circuit opening;
- disabled-provider behavior and sanitized status output;
- Eastmoney incremental range selection;
- stable-overlap merge;
- overlap-change full rebase;
- seven-day full calibration;
- failed refresh preserving parquet and metadata;
- Yahoo calls passing through its guard;
- only one prewarm leader;
- environment schedule parsing;
- cached response during provider failure;
- 503 for a cache miss caused by provider unavailability;
- 404 remaining reserved for genuine missing/insufficient symbols.

The full backend suite must pass after the targeted red-green cycles.

## Deployment and Cooldown

1. Deploy the protected version with `EASTMONEY_FETCH_ENABLED=false`.
2. Keep the API and frontend online; existing parquet remains readable.
3. Confirm the status endpoint reports Eastmoney disabled and Yahoo healthy.
4. Leave Eastmoney disabled for 24–48 hours.
5. Enable Eastmoney and restart the backend.
6. Request one uncached/test symbol and verify one successful guarded call.
7. Run one serialized watchlist refresh and inspect provider state/logs.
8. Keep the circuit breaker enabled permanently.

No full service shutdown is required.
