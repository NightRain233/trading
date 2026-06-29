# Data Source Protection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add cross-process rate limiting, duplicate suppression, retries, circuit breaking, protected incremental Eastmoney refreshes, single-leader prewarming, provider status, and correct 503 behavior without sacrificing cached-data availability.

**Architecture:** A file-backed `ProviderGuard` serializes each provider and stores circuit/spacing state in the shared data volume. Eastmoney uses incremental overlap checks with periodic or detected full rebases; Yahoo keeps its incremental behavior behind the same guard. A long-lived file lock elects one prewarm worker, while typed provider errors preserve stale caches and distinguish upstream outages from genuine 404s.

**Tech Stack:** Python 3.12, FastAPI, requests, yfinance, pandas, `fcntl.flock`, JSON state files, pytest, Docker Compose.

---

### Task 1: Implement the File-Backed Provider Guard

**Files:**
- Create: `backend/data_source_guard.py`
- Create: `backend/tests/test_data_source_guard.py`

**Step 1: Write failing tests for disabled state and status**

Add tests using a temporary state directory and injected clock:

```python
def test_disabled_provider_never_calls_operation(tmp_path):
    guard = ProviderGuard(
        "eastmoney",
        ProviderConfig(enabled=False),
        state_dir=tmp_path,
    )
    called = False

    def operation():
        nonlocal called
        called = True

    with pytest.raises(ProviderDisabledError):
        guard.call("515880.SS", operation)

    assert not called
    assert guard.status()["enabled"] is False
```

**Step 2: Run the test to verify RED**

Run:

```bash
cd backend
uv run --python 3.12 python -m pytest tests/test_data_source_guard.py -q
```

Expected: import failure because `data_source_guard.py` does not exist.

**Step 3: Add the minimal public API**

Implement:

```python
@dataclass(frozen=True)
class ProviderConfig:
    enabled: bool = True
    min_interval_seconds: float = 0.0
    duplicate_window_seconds: float = 300.0
    max_retries: int = 1
    backoff_seconds: float = 1.0
    failure_threshold: int = 3
    circuit_cooldown_seconds: float = 1800.0


class ProviderError(RuntimeError): ...
class ProviderDisabledError(ProviderError): ...
class ProviderCircuitOpenError(ProviderError): ...
class ProviderRecentlySucceeded(ProviderError): ...
class ProviderBlockingError(ProviderError): ...
class ProviderRequestError(ProviderError): ...


class ProviderGuard:
    def call(self, key: str, operation: Callable[[], T]) -> T: ...
    def status(self) -> dict: ...
```

Use `fcntl.flock(..., LOCK_EX)` around state reads, request spacing, the
operation, and state writes. Create state files lazily.

**Step 4: Verify GREEN**

Run the targeted test and confirm it passes.

**Step 5: Add failing spacing and duplicate tests**

Cover:

- a second symbol waits until `nextAllowedAt`;
- a recently successful identical key raises `ProviderRecentlySucceeded`;
- a different key is allowed after provider spacing;
- old per-key entries are pruned.

Inject `clock` and `sleep` callables so tests contain no wall-clock sleeps.

**Step 6: Implement spacing and duplicate suppression**

Persist `nextAllowedAt` and `recentSuccessByKey`. Update them only after the
appropriate attempt/success events.

**Step 7: Add failing circuit and retry tests**

Cover:

- `ProviderBlockingError` opens the circuit immediately without retry;
- a normal transient error retries once with exponential backoff;
- three failed calls open the circuit;
- a successful call resets failure count;
- status sanitizes/truncates the last error.

**Step 8: Implement circuit and retry policy**

Translate terminal operation errors to `ProviderRequestError` while preserving
provider, key, category, and retry-after metadata.

**Step 9: Run targeted tests**

Expected: all guard tests pass.

**Step 10: Commit**

```bash
git add backend/data_source_guard.py backend/tests/test_data_source_guard.py
git commit -m "feat(data): add cross-process provider guard"
```

### Task 2: Add Provider Configuration and Eastmoney Guarding

**Files:**
- Modify: `backend/analysis_constants.py`
- Modify: `backend/analysis_data.py`
- Modify: `backend/tests/test_analysis_data_sources.py`

**Step 1: Write failing configuration tests**

Test boolean, float, integer, proxy-mode, and schedule parsing from environment.
Use strict fallbacks for invalid values.

Expected constants:

```python
EASTMONEY_FETCH_ENABLED
EASTMONEY_PROXY_MODE
EASTMONEY_MIN_INTERVAL_SECONDS
EASTMONEY_CIRCUIT_COOLDOWN_SECONDS
EASTMONEY_FULL_REFRESH_DAYS
EASTMONEY_INCREMENTAL_OVERLAP_DAYS
YAHOO_FETCH_ENABLED
YAHOO_MIN_INTERVAL_SECONDS
YAHOO_CIRCUIT_COOLDOWN_SECONDS
BACKGROUND_PREWARM_ENABLED
PREWARM_HOURS
```

**Step 2: Verify RED**

Run:

```bash
uv run --python 3.12 python -m pytest tests/test_analysis_data_sources.py -q
```

Expected: missing configuration/guard assertions fail.

**Step 3: Implement environment parsing and guard instances**

Add small `_env_bool`, `_env_float`, `_env_int`, and `_env_hours` helpers.
Construct module-level Eastmoney and Yahoo guards from the parsed constants.

**Step 4: Write failing single-route Eastmoney tests**

Replace the old implicit fallback expectation. Prove:

- `direct` sets `Session.trust_env = False`;
- `environment` sets it to `True`;
- only one session/request route is attempted;
- HTTP 403/429 and remote disconnect become `ProviderBlockingError`;
- provider-disabled and circuit-open errors propagate.

**Step 5: Implement guarded Eastmoney transport**

Split parsing from transport:

```python
def _request_eastmoney_payload(secid, start, end) -> dict: ...
def _parse_eastmoney_payload(payload) -> Optional[pd.DataFrame]: ...
def _fetch_eastmoney_daily(symbol, start, end) -> Optional[pd.DataFrame]:
    return eastmoney_guard.call(
        symbol,
        lambda: _parse_eastmoney_payload(
            _request_eastmoney_payload(secid, start, end)
        ),
    )
```

Do not catch typed provider failures in this low-level function.

**Step 6: Run targeted tests**

Expected: Eastmoney transport and existing parser tests pass.

**Step 7: Commit**

```bash
git add backend/analysis_constants.py backend/analysis_data.py backend/tests/test_analysis_data_sources.py
git commit -m "feat(data): guard Eastmoney requests"
```

### Task 3: Implement Incremental Eastmoney Refresh with Full Rebase

**Files:**
- Modify: `backend/analysis_data.py`
- Modify: `backend/analysis.py`
- Modify: `backend/tests/test_analysis_data_sources.py`
- Modify: `backend/tests/test_cache_metadata.py`

**Step 1: Write failing metadata-v2 tests**

Prove:

- v1 metadata is stale after the source version advances;
- v2 stores and reads `lastFullRefreshAt`;
- new, legacy, and overdue caches require a full fetch;
- a recent v2 cache requests only the overlap window.

Introduce:

```python
A_SHARE_DATA_SOURCE_VERSION = "eastmoney-qfq-v2"

@dataclass
class AShareRefreshResult:
    frame: pd.DataFrame
    full_refresh: bool
```

**Step 2: Verify RED**

Run targeted source tests and confirm failures are about missing v2 behavior.

**Step 3: Implement refresh-mode selection**

Add:

```python
def _read_data_source_metadata(file_path, symbol) -> dict: ...
def _a_share_needs_full_refresh(file_path, symbol, now) -> bool: ...
def _a_share_incremental_start(last_update) -> datetime: ...
```

**Step 4: Write failing overlap tests**

Cover:

- stable completed overlap merges incrementally;
- a difference in completed overlapping OHLC triggers one full request;
- a change only in the newest bar does not trigger rebase;
- invalid incremental or full frames leave the old cache untouched.

**Step 5: Implement overlap comparison and refresh**

Add:

```python
def _has_adjustment_rebase(local, downloaded) -> bool: ...
def _fetch_a_share_refresh(symbol, local, last_update, file_path, now) -> AShareRefreshResult: ...
```

Exclude the newest common row when at least two overlapping rows exist. Compare
Open/High/Low/Close with numeric tolerance.

**Step 6: Update single and batch persistence**

- Full result replaces A-share OHLCV.
- Incremental result merges with local OHLCV.
- Metadata writes `lastFullRefreshAt` only after successful parquet writes.
- A duplicate-suppressed provider call reuses stale cache and does not write
  misleading metadata.

**Step 7: Run source and cache tests**

Run:

```bash
uv run --python 3.12 python -m pytest \
  tests/test_analysis_data_sources.py tests/test_cache_metadata.py -q
```

Expected: all selected tests pass.

**Step 8: Commit**

```bash
git add backend/analysis_data.py backend/analysis.py \
  backend/tests/test_analysis_data_sources.py backend/tests/test_cache_metadata.py
git commit -m "feat(data): add protected incremental A-share refresh"
```

### Task 4: Guard Yahoo Finance

**Files:**
- Modify: `backend/analysis_data.py`
- Modify: `backend/analysis.py`
- Create: `backend/tests/test_yahoo_data_source.py`

**Step 1: Write failing single and batch tests**

Prove:

- `Ticker.history` executes through `yahoo_guard`;
- batch `yf.download` executes through the same guard;
- the batch key is deterministic from normalized symbols;
- disabled/circuit-open Yahoo keeps an existing cache;
- a cache miss surfaces a typed provider error.

**Step 2: Verify RED**

Run the new test file and confirm guard calls are missing.

**Step 3: Wrap Yahoo calls**

Keep `global_download_lock` inside the guarded operation for library thread
safety. Use `yahoo:<symbol>` for single requests and a stable sorted joined key
for batches.

**Step 4: Run targeted tests**

Expected: all Yahoo and cache metadata tests pass.

**Step 5: Commit**

```bash
git add backend/analysis_data.py backend/analysis.py backend/tests/test_yahoo_data_source.py
git commit -m "feat(data): guard Yahoo Finance requests"
```

### Task 5: Elect One Prewarm Leader and Restore Twice-Daily Cadence

**Files:**
- Modify: `backend/main.py`
- Create: `backend/tests/test_prewarm_leader.py`

**Step 1: Write failing leader tests**

Use a temporary lock path to prove:

- the first acquisition wins;
- a second file descriptor/process cannot acquire while held;
- disabled prewarm starts no thread;
- startup starts a thread only for the leader;
- configured hours parse as `(12, 21)` by default.

**Step 2: Verify RED**

Run the new test and confirm leader helpers are missing.

**Step 3: Implement long-lived leader lock**

Add:

```python
_prewarm_leader_handle = None

def _try_become_prewarm_leader(lock_path=None) -> bool: ...
def _start_background_prewarm() -> bool: ...
```

Use `LOCK_EX | LOCK_NB` and keep the winning file handle globally for process
lifetime.

**Step 4: Update startup and schedule**

`startup_event` calls `_start_background_prewarm()`. The scheduler uses parsed
`PREWARM_HOURS`; it no longer hardcodes four runs or forces
`min_interval_seconds=0`.

**Step 5: Run targeted tests**

Expected: leader and existing SuperTrend tests pass.

**Step 6: Commit**

```bash
git add backend/main.py backend/tests/test_prewarm_leader.py
git commit -m "fix(data): elect a single prewarm scheduler"
```

### Task 6: Add Provider Status and Correct 503 Semantics

**Files:**
- Modify: `backend/analysis_data.py`
- Modify: `backend/analysis.py`
- Modify: `backend/main.py`
- Create: `backend/tests/test_data_source_status_api.py`
- Modify: `backend/tests/test_analysis_data_sources.py`

**Step 1: Write failing status endpoint tests**

Prove `GET /api/data-sources/status` returns sanitized Eastmoney and Yahoo
snapshots with enabled, circuit, timing, failure count, and error category.

**Step 2: Write failing quote error tests**

Prove:

- provider unavailable + valid cache returns cached quote;
- provider unavailable + no cache returns HTTP 503;
- `Retry-After` is present for an open circuit;
- a genuine analyzer `None` result without provider failure remains HTTP 404.

**Step 3: Verify RED**

Run both targeted files and confirm missing endpoint/error mapping failures.

**Step 4: Implement typed market-data availability**

Add a `MarketDataUnavailableError` carrying provider, category, and optional
retry-after. Preserve it through `fetch_stock_data` and `analyze_stock` only
when no valid cache can be returned. Batch refresh continues logging and
serving partial stale results.

**Step 5: Add API mapping**

Catch `MarketDataUnavailableError` in `/api/quote/{symbol}` and return 503.
Add the status endpoint.

**Step 6: Run targeted tests**

Expected: status and error-semantics tests pass.

**Step 7: Commit**

```bash
git add backend/analysis_data.py backend/analysis.py backend/main.py \
  backend/tests/test_data_source_status_api.py backend/tests/test_analysis_data_sources.py
git commit -m "feat(api): expose market data source health"
```

### Task 7: Add Deployment Configuration

**Files:**
- Modify: `docker-compose.yml`
- Modify: `Makefile.local.example` if present
- Modify: `README.md` or deployment documentation
- Create or modify: `backend/tests/test_data_source_config.py`

**Step 1: Add configuration tests**

Prove invalid environment values fall back safely and proxy mode accepts only
`direct` or `environment`.

**Step 2: Pass environment variables through Compose**

Use Compose substitution defaults matching the design. Do not commit secrets
or a production `.env`.

**Step 3: Document cooldown deployment**

Document deploying initially with:

```text
EASTMONEY_FETCH_ENABLED=false
BACKGROUND_PREWARM_ENABLED=true
```

and the later single-request recovery procedure.

**Step 4: Validate Compose**

Run:

```bash
docker compose config >/dev/null
```

Expected: exit 0.

**Step 5: Commit**

```bash
git add docker-compose.yml Makefile.local.example README.md \
  backend/tests/test_data_source_config.py
git commit -m "docs(deploy): configure protected market data sources"
```

### Task 8: Full Verification and Completion Audit

**Files:**
- Verify all modified files.

**Step 1: Run the full backend suite**

```bash
cd backend
uv run --python 3.12 python -m pytest
```

Expected: zero failures; cache-history regression tests may retain their
documented skips.

**Step 2: Run syntax and format checks**

```bash
uv run --python 3.12 python -m py_compile \
  data_source_guard.py analysis_constants.py analysis_data.py analysis.py main.py
git diff --check
```

Expected: exit 0.

**Step 3: Exercise the status endpoint locally**

Start the backend with Eastmoney disabled and verify:

```bash
curl -sS http://127.0.0.1:8000/api/data-sources/status
```

Expected: Eastmoney reports disabled and no Eastmoney network request occurs.

**Step 4: Audit each design requirement**

Map tests/runtime evidence to:

- cross-process serialization;
- provider spacing and duplicate suppression;
- retry/backoff/circuit behavior;
- Eastmoney incremental/rebase/full calibration;
- Yahoo guarding;
- single prewarm leader and twice-daily schedule;
- stale-cache availability;
- 503 versus 404;
- status endpoint;
- Compose switches.

Do not claim completion while any item lacks direct evidence.

**Step 5: Prepare branch integration**

Use `superpowers:finishing-a-development-branch` to present merge/push/keep
options after all verification passes.

### Task 9: Deploy Disabled and Verify Cooldown State

**Files:**
- External state: `8.153.71.148:/home/zsd/trading`

**Step 1: Deploy the verified branch**

Use the repository deployment workflow without overwriting remote cache data.

**Step 2: Configure initial cooldown**

Set `EASTMONEY_FETCH_ENABLED=false` in the remote deployment environment and
restart only the backend/frontend containers required by the normal deploy.

**Step 3: Verify service availability**

Check:

- root health endpoint returns 200;
- cached A-share quote returns 200;
- Yahoo-backed quote remains available;
- `/api/data-sources/status` reports Eastmoney disabled;
- logs contain no new Eastmoney outbound attempts.

**Step 4: Leave recovery verification pending for the cooldown window**

After 24–48 hours, enable Eastmoney, restart the backend, perform one guarded
request, and inspect status/logs before allowing a serialized watchlist
refresh.
