# Eastmoney A-Share Data Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make Eastmoney forward-adjusted daily data canonical for Chinese symbols, automatically migrate existing server parquets, and prevent corrupt or unordered histories from reaching indicators.

**Architecture:** Shared provider and integrity helpers live in `analysis_data.py`. Single-symbol and batch refresh paths replace the complete retained OHLCV history for `.SS/.SZ` symbols while preserving yfinance incremental merging elsewhere. Per-symbol source metadata invalidates legacy Yahoo caches once, and a migration CLI forces immediate server-wide refresh.

**Tech Stack:** Python 3.12, pandas, requests, yfinance, FastAPI backend, pytest/unittest, Parquet.

---

### Task 1: Repair the Time-Sensitive Baseline Test

**Files:**
- Modify: `backend/tests/test_supertrend_scan.py:231`

**Step 1: Use runtime-relative fresh dates**

Replace the fixed `2026-05-29` through `2026-06-02` index with three dates ending
on `pd.Timestamp.now().normalize()`. Assert `latestDataDate` against the computed
last date.

**Step 2: Run the previously failing test**

Run:

```bash
cd backend
uv run --python 3.12 pytest tests/test_supertrend_scan.py::test_supertrend_scan_returns_data_freshness_metadata -q
```

Expected: `1 passed`.

**Step 3: Commit**

```bash
git add backend/tests/test_supertrend_scan.py
git commit -m "test: keep supertrend freshness fixture current"
```

### Task 2: Add Shared Eastmoney Provider and Integrity Helpers

**Files:**
- Create: `backend/tests/test_analysis_data_sources.py`
- Modify: `backend/analysis_data.py`
- Modify: `backend/analysis.py`

**Step 1: Write failing tests**

Add focused tests proving:

```python
def test_merge_and_clean_data_sorts_merged_rows():
    merged = _merge_and_clean_data(local, downloaded, now)
    assert merged.index.is_monotonic_increasing


def test_fetch_new_data_uses_full_retention_eastmoney_for_a_share(monkeypatch):
    result = _fetch_new_data("515880.SS", recent_last_update, now)
    assert eastmoney_start == now - timedelta(days=DATA_RETENTION_DAYS)
    assert result.equals(eastmoney_df)


def test_price_integrity_rejects_false_split_crash():
    assert not _has_valid_price_history(frame_with_65_percent_drop, "515880.SS")


def test_source_metadata_defaults_legacy_a_share_to_stale(tmp_path):
    assert not _has_current_data_source(parquet_path, "515880.SS")
```

Test Eastmoney parsing with a mocked response and assert `fqt=1`, sorted dates,
English OHLCV columns, and lot-to-share volume conversion.

**Step 2: Run tests to verify RED**

Run:

```bash
cd backend
uv run --python 3.12 pytest tests/test_analysis_data_sources.py -q
```

Expected: failures because the new provider and metadata helpers do not exist
and merge cleanup is not sorted.

**Step 3: Implement minimal shared helpers**

In `analysis_data.py` add:

```python
A_SHARE_DATA_SOURCE_VERSION = "eastmoney-qfq-v1"


def _is_a_share_symbol(symbol: str) -> bool: ...
def _eastmoney_secid(symbol: str) -> Optional[str]: ...
def _fetch_eastmoney_daily(symbol: str, start: datetime, end: datetime) -> Optional[pd.DataFrame]: ...
def _has_valid_price_history(df: Optional[pd.DataFrame], symbol: str) -> bool: ...
def _source_metadata_path(file_path: str) -> str: ...
def _has_current_data_source(file_path: str, symbol: str) -> bool: ...
def _write_data_source_metadata(file_path: str, symbol: str) -> None: ...
def _invalidate_data_source_metadata(file_path: str) -> None: ...
```

Change `_merge_and_clean_data` to deduplicate and `sort_index()` before retention
filtering. Change `_fetch_new_data` to fetch the complete retention window from
Eastmoney for A-shares, validate it, and retain the yfinance path for other
symbols.

Re-export the helpers from `analysis.py` and remove its duplicate Eastmoney
implementation after callers have moved.

**Step 4: Run tests to verify GREEN**

Run:

```bash
cd backend
uv run --python 3.12 pytest tests/test_analysis_data_sources.py -q
```

Expected: all tests pass.

**Step 5: Commit**

```bash
git add backend/analysis_data.py backend/analysis.py backend/tests/test_analysis_data_sources.py
git commit -m "feat: add canonical Eastmoney A-share provider"
```

### Task 3: Migrate the Single-Symbol Refresh Path

**Files:**
- Modify: `backend/tests/test_analysis_data_sources.py`
- Modify: `backend/analysis_data.py`

**Step 1: Write failing cache-migration tests**

Cover:

- a fresh legacy A-share parquet without source metadata still downloads;
- successful Eastmoney refresh replaces, rather than incrementally merges, its
  retained OHLCV history;
- successful parquet write creates current source metadata;
- failed or invalid Eastmoney data keeps the existing parquet and does not
  create metadata;
- non-A-share cache behavior remains unchanged.

**Step 2: Run targeted tests to verify RED**

Run:

```bash
cd backend
uv run --python 3.12 pytest tests/test_analysis_data_sources.py -k "fetch_stock_data or legacy" -q
```

Expected: cache migration assertions fail.

**Step 3: Implement single-symbol migration**

In `fetch_stock_data`:

- make source metadata part of `needs_fetch`;
- replace Chinese OHLCV with the full Eastmoney frame;
- merge incrementally only for non-Chinese symbols;
- write source metadata only after the corrected daily parquet succeeds;
- leave legacy metadata missing after a provider failure so the next call
  retries.

**Step 4: Run targeted and related tests**

Run:

```bash
cd backend
uv run --python 3.12 pytest tests/test_analysis_data_sources.py tests/test_cache_metadata.py -q
```

Expected: all selected tests pass.

**Step 5: Commit**

```bash
git add backend/analysis_data.py backend/tests/test_analysis_data_sources.py
git commit -m "feat: auto-migrate A-share symbol caches"
```

### Task 4: Migrate the Batch Refresh Path

**Files:**
- Modify: `backend/tests/test_cache_metadata.py`
- Modify: `backend/analysis.py`

**Step 1: Replace obsolete gap-patch tests with failing provider tests**

Test that:

- batch refresh does not call `yf.download` for an all-A-share request;
- Eastmoney replaces the whole Chinese retained history;
- missing source metadata bypasses a fresh disk hit;
- mixed batches use Eastmoney per Chinese symbol and yfinance for other
  symbols;
- failed Eastmoney refresh preserves the old cache and marker state.

**Step 2: Run tests to verify RED**

Run:

```bash
cd backend
uv run --python 3.12 pytest tests/test_cache_metadata.py -q
```

Expected: new provider-routing assertions fail.

**Step 3: Implement provider partitioning**

Refactor `batch_fetch_and_update` to:

- partition fetch items into A-share and non-A-share sets;
- fetch full-retention Eastmoney frames concurrently;
- retain the current yfinance batch request only for non-A-share symbols;
- replace A-share history and incrementally merge other markets;
- write source metadata only for successful Eastmoney replacements;
- remove the obsolete Eastmoney gap-patch path.

**Step 4: Run related tests**

Run:

```bash
cd backend
uv run --python 3.12 pytest tests/test_cache_metadata.py tests/test_analysis_data_sources.py -q
```

Expected: all selected tests pass.

**Step 5: Commit**

```bash
git add backend/analysis.py backend/tests/test_cache_metadata.py
git commit -m "feat: route A-share batch refresh through Eastmoney"
```

### Task 5: Add Immediate Stored-Data Migration

**Files:**
- Create: `backend/refresh_a_share_data.py`
- Create: `backend/tests/test_refresh_a_share_data.py`

**Step 1: Write failing discovery and orchestration tests**

Test that the command:

- discovers daily `.SS/.SZ.parquet` files but excludes `_weekly.parquet`;
- includes Chinese watchlist symbols without an existing parquet;
- invalidates each source marker when `--force` is used;
- invokes `batch_fetch_and_update` and returns nonzero when symbols fail to
  refresh.

**Step 2: Run tests to verify RED**

Run:

```bash
cd backend
uv run --python 3.12 pytest tests/test_refresh_a_share_data.py -q
```

Expected: import failure because the migration command does not exist.

**Step 3: Implement the migration CLI**

Provide:

```bash
uv run --python 3.12 python refresh_a_share_data.py --force
```

Print refreshed, failed, and remaining-integrity-anomaly counts. Exit nonzero
when any requested symbol lacks corrected output.

**Step 4: Run tests to verify GREEN**

Run:

```bash
cd backend
uv run --python 3.12 pytest tests/test_refresh_a_share_data.py -q
```

Expected: all tests pass.

**Step 5: Commit**

```bash
git add backend/refresh_a_share_data.py backend/tests/test_refresh_a_share_data.py
git commit -m "feat: add A-share cache migration command"
```

### Task 6: Full Local Verification

**Files:**
- Review all modified backend files.

**Step 1: Run the full backend suite**

```bash
cd backend
uv run --python 3.12 pytest -q
```

Expected: zero failures.

**Step 2: Run a live temporary-data smoke test**

Fetch `515880.SS` into a temporary directory and assert:

- the source metadata is `eastmoney-qfq-v1`;
- index order is monotonic;
- no absolute daily close move exceeds 40%;
- 2026-02-03 is continuous.

**Step 3: Inspect the final diff**

```bash
git diff --check
git status --short
git log --oneline --decorate -8
```

Expected: clean diff checks and only intentional files.

### Task 7: Deploy and Verify the Server

**Files:**
- Use existing `Makefile.local`, Docker, and deployment targets.

**Step 1: Deploy the backend image and code**

Use the repository's configured deployment target and restart containers.

**Step 2: Run forced migration in the backend container**

```bash
docker compose exec -T backend python refresh_a_share_data.py --force
```

Expected: all persisted/watchlist A-share symbols refresh successfully.

**Step 3: Verify persisted server data**

Inspect server parquets and assert:

- all `.SS/.SZ` daily indexes are monotonic;
- no retained daily close series has an absolute move above 40%;
- `515880.SS` has no false crash on 2026-02-03;
- source metadata is current.

**Step 4: Verify the running API**

Request `/api/quote/515880.SS` and confirm a successful response with current
price and regenerated indicators.
