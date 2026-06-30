# TickFlow A 股日线数据源替换设计

## 目标

用 TickFlow 的收盘后历史日 K 服务替换当前 A 股自动运行链路中的东方财富接口，消除未公开网页接口的限频和静默断连风险，同时继续保证：

- `.SS`、`.SZ` A 股和 ETF 使用一致的前复权日线；
- 非 A 股继续由 Yahoo Finance 提供；
- 上游不可用时优先返回最后一份有效 Parquet；
- 日常只在晚间自动更新一次；
- 全量校准由人工命令触发，不再周期性自动请求。

## 已验证事实

- 本地和远端服务器均可访问 `https://free-api.tickflow.org`。
- 免费服务无需 API Key，支持 A 股、ETF、日 K、起止时间、批量查询和复权参数。
- `adjust=forward_additive` 与东方财富常用的差值前复权口径对应。
- 对 `515880` 的实测中，TickFlow 与当前东方财富缓存有 399 个共同交易日，最大收盘价绝对差约为 `0.00033`。
- TickFlow 的时间戳代表中国交易日零点，需要先按 UTC 解析，再转为 `Asia/Shanghai` 并归一化为无时区日期。
- TickFlow 的 A 股 `volume` 与东方财富原始字段一样以手为单位；写入现有 Parquet 前需要乘以 100，继续保持“股”的内部单位。
- SDK 仓库采用 MIT 许可，但服务端和数据生产链未开源，底层数据来源也未公开。因此 TickFlow 仍应被视为外部托管服务，而不是独立可控的数据仓库。

## 总体决策

### 数据源路由

- A 股和 ETF（`.SS`、`.SZ`）：TickFlow 为唯一自动主源。
- 美股、黄金、加密货币等非 A 股：Yahoo Finance 保持不变。
- 东方财富：从运行时代码、配置、健康状态和自动刷新中删除。
- 旧东方财富实现只保留在 Git 历史和既有设计文档中，不再作为自动 fallback，避免恢复时重新触发静默封禁。

### 接入方式

直接调用 TickFlow 已公开的 REST API，不新增 TickFlow SDK 依赖。

原因：

- 现有 `ProviderGuard` 已负责跨进程串行、重试、退避、熔断和状态持久化；
- 避免 SDK 内置重试与本项目保护层叠加后放大请求；
- REST 返回结构简单，适配代码和测试都可保持明确；
- 将来切换免费或带 API Key 的地址只需要修改环境变量。

默认配置：

```env
TICKFLOW_FETCH_ENABLED=true
TICKFLOW_BASE_URL=https://free-api.tickflow.org
TICKFLOW_API_KEY=
TICKFLOW_MIN_INTERVAL_SECONDS=1.0
TICKFLOW_CIRCUIT_COOLDOWN_SECONDS=900
TICKFLOW_INCREMENTAL_OVERLAP_DAYS=7
PREWARM_HOURS=21
```

如果配置了 `TICKFLOW_API_KEY`，请求增加 `x-api-key`；否则使用免费服务。

## TickFlow 适配

### 标的代码

内部代码保持不变：

- `588890.SS` → TickFlow `588890.SH`
- `159583.SZ` → TickFlow `159583.SZ`

TickFlow 返回的数据转换为现有列：

```text
open   -> Open
high   -> High
low    -> Low
close  -> Close
volume -> Volume * 100
```

### 请求参数

所有 A 股请求固定使用：

```text
period=1d
adjust=forward_additive
```

单标的路径使用 `/v1/klines`，观察列表和迁移使用 `/v1/klines/batch`。批量接口优先于逐只循环，正常晚间预热只产生一个 A 股批量请求。

HTTP `429`、`403`、连接断开和超时进入 TickFlow provider guard。无效 JSON、列长度不一致、空响应和非法 OHLCV 作为数据错误处理，绝不覆盖有效缓存。

## 刷新策略

### 晚间增量

后台预热只保留每天 `21:00` 一次。

对于已有 TickFlow 规范缓存的标的：

1. 找到本批标的最早的最后交易日；
2. 从该日期前 7 个自然日开始批量请求到当前日期；
3. 将下载结果按标的拆分并规范化；
4. 比较重叠区间中已完成的 OHLC；
5. 一致时合并、去重、排序并重算指标；
6. 无新增交易日且 OHLC 未变化时不重写 Parquet。

7 天窗口不是为了多取数据，而是为了覆盖周末、节假日、供应商晚间修订以及复权基准变化。

### 复权变化

TickFlow 与现有东方财富缓存存在亚毫级舍入差异。重叠 OHLC 比较采用小的数值容差，允许 `0.0005` 以内的绝对差，不把正常舍入识别为复权变化。

如果超过容差：

- 不自动发起全量请求；
- 不把新数据拼接到旧序列；
- 在 source sidecar 中持久化 `fullRefreshRequired=true`、原因和检测时间；
- 继续返回旧缓存并记录清晰告警；
- 等待人工执行全量刷新。

这样不会在复权日由多个 worker 或多个标的自动放大全量流量。

### 全量刷新

以下情况允许全量请求：

- 新标的首次加入且没有本地历史；
- 人工运行 `refresh_a_share_data.py --force`；
- 部署 TickFlow 版本时进行一次来源迁移。

人工迁移使用 TickFlow 批量接口和项目的 1850 天保留窗口。成功写入日线、周线和指标后，source sidecar 更新为：

```json
{
  "symbol": "588890.SS",
  "sourceVersion": "tickflow-forward-additive-v1",
  "fullRefreshRequired": false,
  "lastFullRefreshAt": "...",
  "lastIncrementalRefreshAt": "..."
}
```

如果批量响应中部分标的缺失，仅失败标的保留旧缓存，其他标的正常提交。

## 缓存与可用性

现有 Parquet 路径和前端 API 不变。部署期间不删除旧缓存。

- TickFlow 成功：写入规范日线、周线、指标和 source sidecar。
- TickFlow 失败且有缓存：返回缓存，标记上游不可用，不写文件。
- TickFlow 失败且无缓存：返回 `503 Service Unavailable`。
- 标的确实不存在或历史不足：仍返回 `404`。

`GET /api/data-sources/status` 改为返回 `tickflow` 和 `yahoo`，不再返回 `eastmoney`。TickFlow 状态不得暴露 API Key。

## 批量路径

`batch_fetch_and_update` 将待更新标的分为：

- A 股 TickFlow 批次；
- 非 A 股 Yahoo 批次。

TickFlow 批次使用共同时间范围做一次请求。每只标的独立验证、合并和落盘，避免“一只坏数据拖垮整批”。新标的或旧 source marker 在正常流量中可以单独全量初始化，但部署迁移优先通过强制批量命令一次完成。

## 配置与文档清理

删除运行时东方财富配置：

```text
EASTMONEY_FETCH_ENABLED
EASTMONEY_PROXY_MODE
EASTMONEY_MIN_INTERVAL_SECONDS
EASTMONEY_CIRCUIT_COOLDOWN_SECONDS
EASTMONEY_FULL_REFRESH_DAYS
EASTMONEY_INCREMENTAL_OVERLAP_DAYS
```

对应更新：

- `analysis_constants.py`
- `docker-compose.yml`
- `.env.example`
- `README.md`
- 健康状态和测试名称

历史设计文档不改写，保留当时决策背景。

## 测试

单元测试必须覆盖：

- `.SS` → `.SH` 和 `.SZ` 保持不变；
- 请求固定使用 `period=1d`、`adjust=forward_additive`；
- UTC 时间戳转上海交易日；
- OHLCV 列映射和成交量乘 100；
- 列长度不一致、空响应和非法 OHLCV 被拒绝；
- `403`、`429` 和网络错误进入 provider guard；
- 单标的全量初始化；
- 7 天重叠增量；
- 亚毫级差异允许合并；
- 明显重叠变化标记人工全量且不写缓存；
- 批量请求只发生一次并允许部分标的失败；
- Yahoo 不处理 `.SS`、`.SZ`；
- 健康接口只返回 TickFlow 和 Yahoo；
- 默认预热时间只有 `21`；
- 迁移脚本强制刷新并写入 TickFlow source marker。

集成验证必须覆盖：

- 全量后端测试；
- Docker Compose 配置解析；
- 本地真实 TickFlow 单标的与批量请求；
- `515880` 历史连续性和复权事件窗口；
- 远端 `free-api.tickflow.org` 连通；
- 远端迁移报告无失败；
- 线上缓存 A 股、新 A 股和 Yahoo 标的均返回 `200`；
- 日志中不再出现 `push2his.eastmoney.com` 外呼。

## 部署与回滚

1. 先部署代码和 TickFlow 环境变量。
2. 启动后端，确认健康接口显示 TickFlow 可用。
3. 人工运行 A 股强制迁移，批量重建现有来源标记。
4. 验证观察列表和关键 ETF。
5. 保留晚间 `21:00` 预热。
6. 从远端 `.env` 删除东方财富开关。

如果 TickFlow 在迁移中异常，旧 Parquet 不会被覆盖。需要回滚时恢复上一版镜像即可；数据目录仍保留最后一份通过校验的缓存。

