# Issue #5 线上行情核验（2026-09-05）

## 当前故障状态

北京时间 2026-09-05 08:54 查询生产 `GET /api/quote/588890.SS`：

- `latestDataDate = decisionAsOf = 2026-09-04`
- `dataStale = false`，`cacheStale = false`，`dataIntegrity.hasGap = false`
- `formalDecisionAvailable = true`，最后完整收盘 1.248
- 服务器 parquet 中 8/26、8/27、8/28、8/31、9/1、9/2、9/3、9/4 均存在。

因此 issue 所述“持续停留在 8/25”当前已恢复。本轮只核验，没有改写生产行情或账本。
首次 API 读取触发了系统正常增量刷新，日志记录获取成功、577 条总数据。

## 来源与复权证据

服务器 `588890.SS.parquet.source.json`：

```json
{
  "sourceVersion": "tickflow-forward-additive-v1",
  "fullRefreshRequired": false,
  "lastFullRefreshAt": "2026-09-03T14:48:58.045319+00:00",
  "lastIncrementalRefreshAt": "2026-09-05T00:54:07.200968+00:00"
}
```

当前 A 股抓取走 TickFlow，不能把 issue 的 yfinance 猜测当成根因。
[基金管理人拆分结果公告](https://paper.cnstock.com/html/2026-08/26/content_2259865.htm)
记录 8/25 实施份额拆分、每份拆为三份，8/26 起查询拆分后份额。
旧 issue 的 8/25 收盘 3.835，对应当前前复权缓存 1.2783333333，恰为三分之一。
8/26 收盘 1.301，调整后序列没有虚假的三分之二跌幅。

代码 `_build_a_share_refresh_result` 在增量重叠窗口价格改变时记录
`fullRefreshRequired` 并阻断增量拼接，需全量重取历史。该机制与本次拆分、9/3 全量
刷新后恢复的证据相符。**推断为复权切换触发保护；无法仅凭现存日志还原最初报错。**
现有容器日志不足以证明 8/26 当时的 typed error 或人工刷新操作者。

## 后续处理边界

可将 #5 标记为“线上已恢复，历史根因高度指向拆分复权保护”。
如果继续改进，重点是将 `fullRefreshRequired` 原因直接传播到 API/日报，明确提示
“复权历史需要全量刷新”，避免统一描述为抓取失败或数据没算完。
不通过放松数据新鲜度门槛恢复交易权限。
