# TickFlow A 股日线数据源替换实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 用 TickFlow 收盘后历史日 K 完整替换 A 股自动链路中的东方财富，将自动预热降为每天 21:00 一次，并把周期性全量校准改为人工触发。

**Architecture:** 复用现有文件型 `ProviderGuard`，通过 TickFlow REST API 获取 `forward_additive` 日 K。单标的请求服务详情页，批量请求服务观察列表与迁移；7 天重叠窗口负责检测复权变化，发现变化时持久化人工全量标记并保留旧缓存。Yahoo 路由保持只处理非 A 股。

**Tech Stack:** Python 3.12、FastAPI、requests、pandas、Parquet、pytest、Docker Compose、TickFlow REST API

---

### Task 1: 将 provider 配置和健康状态从东方财富切换到 TickFlow

**Files:**
- Modify: `backend/analysis_constants.py`
- Modify: `backend/analysis_data.py`
- Modify: `backend/tests/test_data_source_config.py`
- Modify: `backend/tests/test_data_source_status_api.py`

**Step 1: 写失败的配置测试**

在 `backend/tests/test_data_source_config.py` 增加模块重载测试，断言默认值：

```python
def test_tickflow_defaults(monkeypatch):
    for key in (
        "TICKFLOW_FETCH_ENABLED",
        "TICKFLOW_BASE_URL",
        "TICKFLOW_API_KEY",
        "TICKFLOW_MIN_INTERVAL_SECONDS",
        "TICKFLOW_CIRCUIT_COOLDOWN_SECONDS",
        "TICKFLOW_INCREMENTAL_OVERLAP_DAYS",
        "PREWARM_HOURS",
    ):
        monkeypatch.delenv(key, raising=False)

    module = importlib.reload(analysis_constants)

    assert module.TICKFLOW_FETCH_ENABLED is True
    assert module.TICKFLOW_BASE_URL == "https://free-api.tickflow.org"
    assert module.TICKFLOW_API_KEY == ""
    assert module.TICKFLOW_MIN_INTERVAL_SECONDS == 1.0
    assert module.TICKFLOW_CIRCUIT_COOLDOWN_SECONDS == 900
    assert module.TICKFLOW_INCREMENTAL_OVERLAP_DAYS == 7
    assert module.PREWARM_HOURS == (21,)
```

更新健康接口测试，期望 provider key 是 `tickflow` 与 `yahoo`，并将错误样例 provider 从 `eastmoney` 改为 `tickflow`。

**Step 2: 运行测试确认失败**

Run:

```bash
cd backend
uv run --python 3.12 python -m pytest \
  tests/test_data_source_config.py \
  tests/test_data_source_status_api.py -q
```

Expected: FAIL，缺少 TickFlow 常量，状态仍返回 Eastmoney。

**Step 3: 实现 TickFlow 配置和 guard**

在 `analysis_constants.py` 删除运行时 Eastmoney 常量，增加：

```python
TICKFLOW_FETCH_ENABLED = _env_bool("TICKFLOW_FETCH_ENABLED", True)
TICKFLOW_BASE_URL = os.getenv(
    "TICKFLOW_BASE_URL",
    "https://free-api.tickflow.org",
).rstrip("/")
TICKFLOW_API_KEY = os.getenv("TICKFLOW_API_KEY", "").strip()
TICKFLOW_MIN_INTERVAL_SECONDS = _env_float(
    "TICKFLOW_MIN_INTERVAL_SECONDS",
    1.0,
)
TICKFLOW_CIRCUIT_COOLDOWN_SECONDS = _env_int(
    "TICKFLOW_CIRCUIT_COOLDOWN_SECONDS",
    900,
)
TICKFLOW_INCREMENTAL_OVERLAP_DAYS = _env_int(
    "TICKFLOW_INCREMENTAL_OVERLAP_DAYS",
    7,
    minimum=1,
)
PREWARM_HOURS = _env_hours("PREWARM_HOURS", (21,))
```

在 `analysis_data.py` 将 `eastmoney_guard` 替换为：

```python
tickflow_guard = ProviderGuard(
    "tickflow",
    ProviderConfig(
        enabled=TICKFLOW_FETCH_ENABLED,
        min_interval_seconds=TICKFLOW_MIN_INTERVAL_SECONDS,
        duplicate_window_seconds=5 * 60,
        max_retries=1,
        backoff_seconds=1.0,
        failure_threshold=3,
        circuit_cooldown_seconds=TICKFLOW_CIRCUIT_COOLDOWN_SECONDS,
    ),
    state_dir=PROVIDER_STATE_DIR,
)
```

健康状态只返回：

```python
def get_data_source_status() -> dict:
    return {
        "tickflow": tickflow_guard.status(),
        "yahoo": yahoo_guard.status(),
    }
```

暂时保留旧 Eastmoney传输函数到 Task 2，避免一次修改跨越多个测试关注点。

**Step 4: 运行测试确认通过**

Run:

```bash
cd backend
uv run --python 3.12 python -m pytest \
  tests/test_data_source_config.py \
  tests/test_data_source_status_api.py -q
```

Expected: PASS。

**Step 5: 提交**

```bash
git add backend/analysis_constants.py backend/analysis_data.py \
  backend/tests/test_data_source_config.py \
  backend/tests/test_data_source_status_api.py
git commit -m "feat(data): configure TickFlow provider"
```

### Task 2: 实现 TickFlow REST 传输、标的映射和数据规范化

**Files:**
- Modify: `backend/analysis_data.py`
- Modify: `backend/analysis.py`
- Modify: `backend/tests/test_analysis_data_sources.py`

**Step 1: 用 TickFlow 行为替换 Eastmoney 传输测试**

覆盖以下测试：

```python
def test_tickflow_symbol_mapping():
    assert analysis_data._tickflow_symbol("588890.SS") == "588890.SH"
    assert analysis_data._tickflow_symbol("159583.SZ") == "159583.SZ"
    assert analysis_data._tickflow_symbol("SPY") is None
```

```python
def test_fetch_tickflow_daily_normalizes_forward_additive_payload():
    payload = {
        "data": {
            "timestamp": [1782748800000],
            "open": [5.50],
            "high": [5.60],
            "low": [5.45],
            "close": [5.57],
            "volume": [379147],
            "amount": [211000000.0],
        }
    }
    # mock Session.get and tickflow_guard.call
    result = analysis_data._fetch_tickflow_daily(
        "588890.SS",
        datetime(2026, 6, 20),
        datetime(2026, 7, 1),
    )
    assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert result.index[0] == pd.Timestamp("2026-06-30")
    assert result.iloc[0]["Volume"] == 37_914_700
```

同时断言请求：

```python
assert url == "https://free-api.tickflow.org/v1/klines"
assert params["symbol"] == "588890.SH"
assert params["period"] == "1d"
assert params["adjust"] == "forward_additive"
assert params["start_time"] == int(pd.Timestamp(start, tz="Asia/Shanghai").timestamp() * 1000)
```

增加以下失败响应测试：

- 返回列长度不一致时抛出 `ValueError`；
- 空 `data` 时返回空 DataFrame，随后被数据完整性校验拒绝；
- HTTP `403`、`429` 转为 `ProviderBlockingError`；
- 配置 API Key 时只在 header 发送 `x-api-key`；
- 日常日志和异常中不包含 API Key。

**Step 2: 运行测试确认失败**

Run:

```bash
cd backend
uv run --python 3.12 python -m pytest \
  tests/test_analysis_data_sources.py -q
```

Expected: FAIL，TickFlow 函数尚不存在。

**Step 3: 实现 TickFlow 适配**

在 `analysis_data.py` 增加：

```python
def _tickflow_symbol(symbol: str) -> Optional[str]:
    normalized = symbol.upper()
    if normalized.endswith(".SS"):
        return f"{normalized[:-3]}.SH"
    if normalized.endswith(".SZ"):
        return normalized
    return None
```

```python
def _tickflow_timestamp(value: int) -> pd.Timestamp:
    return (
        pd.to_datetime(value, unit="ms", utc=True)
        .tz_convert("Asia/Shanghai")
        .tz_localize(None)
        .normalize()
    )
```

```python
def _parse_tickflow_payload(payload: dict) -> pd.DataFrame:
    data = payload.get("data") or {}
    required = ("timestamp", "open", "high", "low", "close", "volume")
    lengths = {len(data.get(name) or []) for name in required}
    if lengths == {0}:
        return pd.DataFrame(
            columns=["Open", "High", "Low", "Close", "Volume"]
        )
    if len(lengths) != 1 or 0 in lengths:
        raise ValueError("TickFlow payload columns have inconsistent lengths")
    frame = pd.DataFrame(
        {
            "Date": [_tickflow_timestamp(v) for v in data["timestamp"]],
            "Open": data["open"],
            "High": data["high"],
            "Low": data["low"],
            "Close": data["close"],
            "Volume": np.asarray(data["volume"], dtype=float) * 100,
        }
    )
    return frame.set_index("Date").sort_index()
```

将单标的请求封装到 `tickflow_guard.call`：

```python
def _fetch_tickflow_daily(
    symbol: str,
    start: datetime,
    end: datetime,
    *,
    request_key: Optional[str] = None,
) -> Optional[pd.DataFrame]:
    provider_symbol = _tickflow_symbol(symbol)
    if provider_symbol is None:
        return None
    params = {
        "symbol": provider_symbol,
        "period": "1d",
        "adjust": "forward_additive",
        "start_time": _to_tickflow_ms(start),
        "end_time": _to_tickflow_ms(end),
    }
    headers = (
        {"x-api-key": TICKFLOW_API_KEY}
        if TICKFLOW_API_KEY
        else {}
    )
    # GET, 8 秒 timeout，403/429 分类为 ProviderBlockingError
    # 其他 HTTP/JSON/连接错误交给 ProviderGuard 重试和熔断
```

删除 `_eastmoney_secid`、`_fetch_eastmoney_daily` 及相关路由逻辑。`analysis.py` 改为 re-export `_fetch_tickflow_daily`。

**Step 4: 运行测试确认通过**

Run:

```bash
cd backend
uv run --python 3.12 python -m pytest \
  tests/test_analysis_data_sources.py -q
```

Expected: PASS。

**Step 5: 提交**

```bash
git add backend/analysis_data.py backend/analysis.py \
  backend/tests/test_analysis_data_sources.py
git commit -m "feat(data): add TickFlow daily transport"
```

### Task 3: 改为 7 天增量、人工全量和 TickFlow source marker

**Files:**
- Modify: `backend/analysis_data.py`
- Modify: `backend/tests/test_analysis_data_sources.py`
- Modify: `backend/tests/test_cache_metadata.py`

**Step 1: 写失败的刷新策略测试**

测试以下规则：

1. `A_SHARE_DATA_SOURCE_VERSION == "tickflow-forward-additive-v1"`。
2. 新标的从 `now - DATA_RETENTION_DAYS` 获取全量。
3. 当前来源标的从 `last_update - 7 days` 获取增量。
4. 不再因为 `lastFullRefreshAt` 超过 7 天自动全量。
5. `0.00033` 的 OHLC 差异不触发 rebase。
6. `0.01` 的重叠差异：
   - 不自动调用第二次全量请求；
   - sidecar 写入 `fullRefreshRequired=true`；
   - 抛出带 `category="full_refresh_required"` 的 typed error；
   - 原 Parquet mtime 和内容保持不变。
7. `--force` 全量成功后清除 `fullRefreshRequired`。

示例：

```python
def test_overlap_change_requires_manual_full_refresh(tmp_path):
    local = _ohlcv(["2026-06-27", "2026-06-30"], [1.00, 1.01])
    downloaded = _ohlcv(
        ["2026-06-27", "2026-06-30", "2026-07-01"],
        [1.02, 1.03, 1.04],
    )
    # mock _fetch_tickflow_daily once
    with pytest.raises(AShareFullRefreshRequiredError):
        _fetch_a_share_refresh(...)
    assert mock_fetch.call_count == 1
    metadata = _read_data_source_metadata(...)
    assert metadata["fullRefreshRequired"] is True
```

**Step 2: 运行测试确认失败**

Run:

```bash
cd backend
uv run --python 3.12 python -m pytest \
  tests/test_analysis_data_sources.py \
  tests/test_cache_metadata.py -q
```

Expected: FAIL，仍存在周期全量和自动 rebase。

**Step 3: 实现 source metadata 和人工标记**

设置：

```python
A_SHARE_DATA_SOURCE_VERSION = "tickflow-forward-additive-v1"
TICKFLOW_OVERLAP_ATOL = 5e-4
```

更新 metadata 写入：

```python
payload = {
    "symbol": symbol.upper(),
    "sourceVersion": A_SHARE_DATA_SOURCE_VERSION,
    "fullRefreshRequired": full_refresh_required,
    "lastFullRefreshAt": normalized_full_timestamp,
    "lastIncrementalRefreshAt": normalized_incremental_timestamp,
}
```

增加：

```python
class AShareFullRefreshRequiredError(ProviderError):
    pass
```

```python
def _mark_full_refresh_required(
    file_path: str,
    symbol: str,
    *,
    reason: str,
    detected_at: datetime,
) -> None:
    metadata = _read_data_source_metadata(file_path, symbol)
    metadata.update(
        {
            "symbol": symbol.upper(),
            "sourceVersion": A_SHARE_DATA_SOURCE_VERSION,
            "fullRefreshRequired": True,
            "fullRefreshReason": reason,
            "fullRefreshDetectedAt": _normalize_metadata_timestamp(
                detected_at
            ),
        }
    )
    _atomic_write_source_metadata(file_path, metadata)
```

移除 `_a_share_needs_full_refresh` 的 7 天周期判断。只有无缓存、无更新时间或 source marker 非当前版本才自动全量；当前版本且 `fullRefreshRequired=true` 时直接抛 typed error，不发网络请求。

重叠比较改为：

```python
np.isclose(left, right, rtol=1e-8, atol=TICKFLOW_OVERLAP_ATOL)
```

发现变化时只标记并抛错，不进行第二次全量请求。

**Step 4: 运行测试确认通过**

Run:

```bash
cd backend
uv run --python 3.12 python -m pytest \
  tests/test_analysis_data_sources.py \
  tests/test_cache_metadata.py -q
```

Expected: PASS。

**Step 5: 提交**

```bash
git add backend/analysis_data.py \
  backend/tests/test_analysis_data_sources.py \
  backend/tests/test_cache_metadata.py
git commit -m "feat(data): use manual TickFlow full calibration"
```

### Task 4: 将 A 股批量更新收敛为 TickFlow 批量请求

**Files:**
- Modify: `backend/analysis_data.py`
- Modify: `backend/analysis.py`
- Modify: `backend/tests/test_cache_metadata.py`
- Modify: `backend/tests/test_analysis_data_sources.py`

**Step 1: 写失败的批量测试**

增加：

```python
def test_tickflow_batch_fetches_multiple_a_shares_once():
    # two cached A-share items
    # mock one /v1/klines/batch response
    result = batch_fetch_and_update(["510300.SS", "159915.SZ"])
    assert mock_session_get.call_count == 1
    assert request_url.endswith("/v1/klines/batch")
    assert request_params["symbols"] == "159915.SZ,510300.SH"
```

以及：

- 批量响应缺失一只时，其他标的仍更新；
- 新标的与已有标的分为全量、增量两批，最多两个 TickFlow 请求；
- 全量批次使用 1850 天范围；
- 增量批次使用共同的最早 `last_update - 7 days`；
- Yahoo mock 未收到任何 `.SS`、`.SZ`；
- TickFlow guard key 包含排序后的标的与时间范围。

**Step 2: 运行测试确认失败**

Run:

```bash
cd backend
uv run --python 3.12 python -m pytest \
  tests/test_cache_metadata.py \
  tests/test_analysis_data_sources.py -q
```

Expected: FAIL，当前 A 股逐只请求。

**Step 3: 实现批量传输与逐标的提交**

在 `analysis_data.py` 增加：

```python
def _fetch_tickflow_daily_batch(
    symbols: list[str],
    start: datetime,
    end: datetime,
    *,
    request_key: Optional[str] = None,
) -> dict[str, pd.DataFrame]:
    provider_to_internal = {
        _tickflow_symbol(symbol): symbol.upper()
        for symbol in symbols
    }
    params = {
        "symbols": ",".join(sorted(provider_to_internal)),
        "period": "1d",
        "adjust": "forward_additive",
        "start_time": _to_tickflow_ms(start),
        "end_time": _to_tickflow_ms(end),
    }
    # GET /v1/klines/batch
    # 对 payload["data"] 的每个 provider symbol 独立 parse
    # 缺失项不伪造空成功
```

抽取纯函数：

```python
def _build_a_share_refresh_result(
    symbol: str,
    *,
    downloaded: pd.DataFrame,
    df_local: Optional[pd.DataFrame],
    file_path: str,
    now: datetime,
    full_refresh: bool,
) -> AShareRefreshResult:
    ...
```

`batch_fetch_and_update`：

1. 把 A 股项目按“首次/旧来源全量”和“当前来源增量”分组；
2. 每组调用一次 `_fetch_tickflow_daily_batch`；
3. 每只标的独立构建 `AShareRefreshResult`；
4. 缺失或失败标的不进入 `downloaded_data`；
5. 保留现有逐标的锁、指标重算和原子 source metadata 时序。

**Step 4: 运行测试确认通过**

Run:

```bash
cd backend
uv run --python 3.12 python -m pytest \
  tests/test_cache_metadata.py \
  tests/test_analysis_data_sources.py -q
```

Expected: PASS。

**Step 5: 提交**

```bash
git add backend/analysis_data.py backend/analysis.py \
  backend/tests/test_cache_metadata.py \
  backend/tests/test_analysis_data_sources.py
git commit -m "feat(data): batch TickFlow A-share refreshes"
```

### Task 5: 更新迁移命令、预热时间、部署配置和文档

**Files:**
- Modify: `backend/refresh_a_share_data.py`
- Modify: `backend/tests/test_refresh_a_share_data.py`
- Modify: `backend/tests/test_prewarm_leader.py`
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `README.md`

**Step 1: 写失败的迁移与时间测试**

更新断言：

```python
def test_default_prewarm_only_runs_at_21():
    assert main.PREWARM_HOURS == (21,)
```

迁移测试断言：

- `--force` 使所有目标进入 TickFlow 全量批次；
- 成功后的 source marker 是 `tickflow-forward-additive-v1`；
- 失败项保留旧 Parquet；
- CLI 描述不再提 Eastmoney。

增加静态配置测试，确保运行时文件中不存在 `EASTMONEY_`，且 Compose 传入全部 `TICKFLOW_` 变量。

**Step 2: 运行测试确认失败**

Run:

```bash
cd backend
uv run --python 3.12 python -m pytest \
  tests/test_refresh_a_share_data.py \
  tests/test_prewarm_leader.py \
  tests/test_data_source_config.py -q
```

Expected: FAIL，默认时间仍含 12，部署配置仍是 Eastmoney。

**Step 3: 更新迁移和部署文档**

将 CLI 描述改为：

```python
description="Refresh persisted A-share data from TickFlow."
```

`.env.example` 和 `docker-compose.yml` 使用 Task 1 的 TickFlow 变量，默认：

```env
PREWARM_HOURS=21
```

README 说明：

- TickFlow 是 A 股主源；
- 免费日 K 只在收盘后更新；
- Yahoo 只处理非 A 股；
- `refresh_a_share_data.py --force` 是人工全量校准；
- provider 状态返回 TickFlow/Yahoo；
- 上游失败时缓存与 503 语义。

**Step 4: 运行相关测试和配置检查**

Run:

```bash
cd backend
uv run --python 3.12 python -m pytest \
  tests/test_refresh_a_share_data.py \
  tests/test_prewarm_leader.py \
  tests/test_data_source_config.py -q
cd ..
docker compose config >/dev/null
git diff --check
```

Expected: 全部通过，仅允许 Compose 现有 `version` obsolete 警告。

**Step 5: 提交**

```bash
git add backend/refresh_a_share_data.py \
  backend/tests/test_refresh_a_share_data.py \
  backend/tests/test_prewarm_leader.py \
  backend/tests/test_data_source_config.py \
  docker-compose.yml .env.example README.md
git commit -m "docs(deploy): switch A-share runtime to TickFlow"
```

### Task 6: 完成全量回归和真实数据验证

**Files:**
- No code changes unless verification exposes a defect

**Step 1: 搜索残留运行时引用**

Run:

```bash
rg -n "eastmoney|Eastmoney|EASTMONEY|push2his" \
  backend/*.py backend/tests docker-compose.yml .env.example README.md
```

Expected: 无运行时引用；允许历史设计文档和历史结果 JSON 保留。

**Step 2: 运行全量后端测试**

Run:

```bash
cd backend
uv run --python 3.12 python -m pytest
```

Expected: 全部通过，原有依赖历史数据的 6 个测试可继续 skip。

**Step 3: 运行编译和 Compose 验证**

Run:

```bash
cd backend
uv run --python 3.12 python -m py_compile \
  analysis_constants.py analysis_data.py analysis.py \
  data_source_guard.py main.py refresh_a_share_data.py
cd ..
docker compose config >/dev/null
git diff --check
```

Expected: exit 0。

**Step 4: 真实 TickFlow 冒烟验证**

使用临时数据目录或只读脚本验证：

- `588890.SS` 单标的返回最新已完成日 K；
- `510300.SS`、`159915.SZ`、`588890.SS` 一次批量返回；
- `515880.SS` 在 2026-02-03 附近无假暴跌；
- TickFlow 与现有缓存的共同日期 OHLC 差异在设计容差内；
- 时间戳落到正确的上海交易日；
- Volume 写入前乘 100。

不覆盖正式 `backend/data`。

**Step 5: 提交验证中必要的修复**

如无修复，不创建空提交。若有修复：

```bash
git add <exact-files>
git commit -m "fix(data): harden TickFlow migration"
```

### Task 7: 合并、部署和迁移线上 A 股缓存

**Files:**
- Remote: `/home/zsd/trading/.env`
- Remote data: `/home/zsd/trading/backend/data/`

**Step 1: 按分支收尾流程选择并执行本地合并**

使用 `superpowers:finishing-a-development-branch`。本地合并后在 `main` 再运行 Task 6 的全量测试。

**Step 2: 更新远端环境变量**

原子更新 `.env`：

```env
TICKFLOW_FETCH_ENABLED=true
TICKFLOW_BASE_URL=https://free-api.tickflow.org
TICKFLOW_API_KEY=
TICKFLOW_MIN_INTERVAL_SECONDS=1.0
TICKFLOW_CIRCUIT_COOLDOWN_SECONDS=900
TICKFLOW_INCREMENTAL_OVERLAP_DAYS=7
YAHOO_FETCH_ENABLED=true
BACKGROUND_PREWARM_ENABLED=true
PREWARM_HOURS=21
```

删除所有 `EASTMONEY_` 行。

**Step 3: 从干净 worktree 构建和部署**

Run:

```bash
make deploy-full \
  DEPLOY_HOST=root@8.153.71.148 \
  DEPLOY_PATH=/home/zsd/trading
```

Expected: 两个容器均为 `Up`。

**Step 4: 运行一次人工全量来源迁移**

Run remotely:

```bash
cd /home/zsd/trading
docker compose exec -T backend \
  uv run --no-dev python refresh_a_share_data.py --force
```

Expected:

- `failed` 为空；
- 所有 A 股 source marker 为 `tickflow-forward-additive-v1`；
- 日线和周线均单调递增；
- 无绝对日涨跌超过 40% 的异常序列。

**Step 5: 验证线上 API 和日志**

验证：

```text
GET /api/data-sources/status       -> tickflow/yahoo enabled
GET /api/quote/510300.SS           -> 200
GET /api/quote/588890.SS           -> 200
GET /api/quote/159583.SZ           -> 200
GET /api/quote/SPY                 -> 200
```

同时确认：

- 两个 uvicorn worker 中只有一个预热 leader；
- `push2his.eastmoney.com` 日志计数为 0；
- TickFlow 请求没有 API Key 泄漏；
- `PREWARM_HOURS=21` 已进入容器；
- 删除上传的镜像压缩包。

**Step 6: 完成目标审计**

逐项对照设计文档确认：

- 东方财富已从自动运行时代码和远端配置移除；
- A 股真实数据由 TickFlow 提供；
- Yahoo 不接管 A 股；
- 晚间只预热一次；
- 周期全量已取消，人工 `--force` 可用；
- 缓存、503、健康状态和回滚路径均验证。

