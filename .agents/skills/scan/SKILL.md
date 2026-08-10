---
name: scan
description: Use when the user asks for a market-wide SuperTrend scan, watchlist ranking, actionable trading candidates, trend continuation, or portfolio risk alerts.
---

# /scan — 自选股统一扫描

扫描全部自选标的，使用后端正式分组回答：哪里必须风控、哪些正式买点仍可执行、哪些只接近触发，以及技术权限与组合权限是否一致。

开始前完整读取 `../trading-analysis/references/decision-contract.md`。阈值、权限、压缩突破实验状态和盘中边界只以该契约及 API 为准，本文件不复制策略公式。

## 准备

1. 读取 `reviews/README.md`。
2. 检查最近 3 个自然日内存在的每日复盘、`reviews/持仓总览.md`，以及当前持仓和最终重点标的的品种页。
3. 品种页与每日复盘冲突时，以品种页当前有效规则为准；旧价格、旧仓位和旧止损不得当作当前事实。
4. 最近三天无有效复盘时，明确说明本次只依据行情数据。

本地服务优先：

```bash
uv run python scripts/trading_analysis_helper.py \
  --api-base http://127.0.0.1:8000/api \
  --query overview --timeout 180
```

本地不可用或用户要求生产数据时，将 API base 改为 `http://8.153.71.148/api`。一次分析不得混用来源。只有需要候选 candles 时才补调 `GET /api/supertrend/scan?include_candles=true`；不能根据截断输出判断没有信号。

## 验证响应

解释前确认：

- `schemaVersion`、`policyVersion` 存在；coverage 完整且 missing 为空。
- `items` 与所有 `groups.*.symbols` 去重后的全集一致。
- 每个标的都有 `decision`、`sessionContext`、`executionStatus`、`positionGuidance`、`lifecycle`。
- `attention`、`themes`、`changes`、`portfolioMatrix` 存在。
- `dataStale=false`、无真实交易日缺口且 `formalDecisionAvailable=true` 才能形成交易结论。
- 交易时段进行中不是数据异常；沿用正式收盘权限，但盘中可以取消或降级执行。
- 量能只使用 `ratio20Completed`；未完成时写“量能未完成”。

若 `changes.replayedFromCache=true`，只能称为缓存快照，不得将其中 transition 描述成“刚刚发生”。若 `baselineAvailable=false`，明确无比较基线。新增/移除自选分别读取 `addedSymbols`、`removedSymbols`，不冒充策略变化。

## 扫描纪律

每个市场独立读取 `marketModes`，不能拿 A 股状态替代美股、黄金或加密。债券代表只作风险观察。市场模式不足或数据异常时，不自行补造许可。

正式新仓路径只有：

- `breakout`：完整日线翻多后的右侧突破。
- `pullback`：已确认多头趋势中的回踩再走强。

`compression_breakout` 是尚未完成样本外和交易成本验证的实验路径：即使上一完整收盘给出 `conditional`、盘中进入 `paper_armed_triggered`，也只能记录纸面触发，`executionStatus.executable` 必须为 false。不得建议实盘小仓、挂单或成交。`authorization.consumptionTracked=false` 时也不得推断已成交或信号已消费。

V 型反转、黄灯追踪、MACD 背离、RSI、KDJ、BOLL 和量能只用于观察或辅助确认，不能升级 API 权限。`readinessScore` 只在同权限内排序，不是胜率。

优先直接采用 API 的 `decision.label`、`reasonCodes`、`failedGates`、`nextGate`、`nextTrigger` 和失效条件。正式 `buy` 仍须以 `executionStatus.executable=true` 为当前技术可执行前提；这不等于最终实盘许可，`liveTradingAllowed` 在技术层固定为 false。技术权限与组合权限永远分开：

```text
技术权限 | 组合权限 | 原因
```

`portfolioPermission=mixed` 表示不同策略意见冲突，必须展开每个 context，不能折叠成可执行。`blocked/no_rebalance` 不得给实际调仓动作；`unmanaged` 只表示不受纸面组合管理。

## 输出顺序

1. 数据日期、完整性、快照是否重放及比较基线。
2. 各市场模式；A 股扫描时附上证、沪深300、中证500、科创50、中证2000的紧凑环境表。
3. 真实新增、升级、降级、失效和自选增删。
4. 全部持仓/风控项。
5. 正式突破买点与回踩买点，并写当前 execution 状态。
6. 压缩突破纸面实验项，显著标注“禁止实盘执行”。
7. 最接近触发的 3–5 项：权限、唯一 nextGate、触发/上限/失效条件。
8. 主题去重后的重点机会和交易载体。
9. 技术/组合权限矩阵；mixed 展开策略分歧。
10. 其余观察组仅列数量与 symbol。
11. 一句“今天最关键的结论”。

单标的紧凑展示方向、trend age、ADX、距 ST 的 ATR、MACD 柱变化、完整量比、正式决策日和行动边界。不要用指标堆叠掩盖权限，不把 ST 说成未计算的前高或平台上沿，不凭空生成仓位数量。
