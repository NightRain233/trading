# 统一决策契约

按四层解释单标的，不混淆正式信号、条件纸面计划、盘中执行和持仓风险。

## 1. 正式收盘决策

- `decision`、`state`、`weeklyState`、ADX、ATR 距离均以 `sessionContext.formalDecisionAsOf` 的完整收盘数据为准。
- 当前交易时段进行中不自动阻断正式决策；只有 `formalDecisionAvailable=false`、数据过期或存在缺口才属于数据异常。
- `decision.permission=buy` 表示正式技术条件通过，不代表任意盘中价格都可执行。
- `technicalExecutionEligible=true` 只表示技术层进入执行评估；`liveTradingAllowed` 固定为 false，最终实盘许可必须来自组合风险、仓位与账本层。
- `decision.permission=conditional` 表示上一完整收盘形成压缩突破纸面实验计划，不是实盘授权，也不等于已经成交。
- `decision.setup` 只使用 `breakout`、`pullback`、`compression_breakout`、观察或风险类型；`decision.stage` 描述生命周期阶段。
- `decision.nextGate` 是权限升级前的首要门槛；`readinessScore` 只用于同权限内排序，不能覆盖硬门槛。

## 2. 条件纸面计划

`compression_breakout` 只有同时满足日线仍空且贴近 ST、当日或最近 5 日存在 BOLL 压缩且带宽尚未过度扩张、MACD 柱为正且改善、压缩路径 ADX 门槛、正式周线多头和市场允许时才能返回 `conditional`。

纸面计划必须包含：

- `triggerPrice`：上一完整收盘确定的固定触发价。
- `maxAcceptablePrice`：允许执行的最高价格，不能跳过后追买。
- `invalidationPrice`：触发前取消计划的价格锚点。

周线未确认的同类结构只能 `watch/compression_watch`。该启发式尚未完成样本外、跨资产和交易成本验证，因此当前固定 `paperOnly=true`、`liveTradingAllowed=false`；不能建议实盘小仓、挂单或成交。

`authorization.signalId` 用于稳定识别同一纸面计划，计划仅对下一市场时段有效并在下一根完整日线后过期。当前 `consumptionTracked=false`，所以系统不能证明是否成交或已消费，分析不得自行推断。

## 3. 盘中执行状态

读取 `executionStatus`：

- `executable`：正式信号有效，实时价格未超过最高接受条件。
- `above_max_price`：保留正式信号记录，但取消本次追买。
- `intraday_below_formal_st`：盘中跌破正式 ST；对新仓会取消当前执行，对已有仓位是风险预警而非自动正式退出。
- `provisional_recovery`：空头中的盘中站回，不得升级买入权限。
- `monitoring`：沿用正式决策，盘中暂未改变执行条件。
- `not_applicable`：当前没有正式可执行入场信号。
- `armed_waiting_trigger`：压缩突破已授权，尚未触及触发价。
- `paper_armed_triggered`：进入预设触发价与最高接受价之间，只记录纸面触发，`executable=false`。
- `armed_above_max`：跳过最高接受价，取消追买并转回踩观察。
- `armed_invalidated`：跌破预设失效价，取消计划。

盘中数据只能取消/降级执行或提示风险，不能创造 `buy`。始终并列展示 `livePrice`、`formalClose`、`formalDecisionAsOf` 和会话状态。

## 4. 行情生命周期

读取 `decisionHistory` 与 `lifecycle`，解释最近完整日线的 ST 状态、ATR 距离、ADX、MACD 柱和 BOLL 宽度如何演变。区分：正在形成、已布防、已触发可执行、已触发但过度扩张、趋势仍在但无入场。`failureCategory` 必须区分数据、市场、方向、强度、价格和时机失败。

## 5. 持仓风险指引

先从复盘或 portfolio 判断是否持仓，再使用 `positionGuidance`：

- `trend_hold`：若有持仓，按正式 ST 管理风险。
- `hold_with_weekly_risk`：日线尚可但周线未确认，不新增仓位。
- `intraday_risk_warning`：盘中风险提示，不等同正式退出。
- `formal_exit`：正式日线翻空，按品种页或组合规则处理。
- `avoid_or_exit_review`：无仓规避；有仓检查退出规则。
- `data_unavailable_review`：行情过期或有缺口，不能确认继续持有或正式退出；沿用最后有效风险线并人工核对。

## 6. 快照变化与组合冲突

- `changes.replayedFromCache=true` 表示返回缓存快照，不是新变化通知。
- 用 `baselineGeneratedAt/currentGeneratedAt` 界定比较区间；`addedSymbols/removedSymbols` 是自选范围变化，不是策略升级或降级。
- `portfolioPermission=mixed` 表示多个策略对同一标的权限冲突，必须保留逐策略 context，不能因为其中一个 executable 就聚合成可执行。

新仓权限和持仓动作必须分别回答。`blocked` 新仓不等于无法管理已有持仓。

## 7. 输出顺序

1. 正式决策：截至日期、权限、通过条件、失败门槛。
2. 生命周期：最近状态演化、是否曾出现参与窗口、当前是方向问题还是位置问题。
3. 条件纸面计划与盘中执行：实时价与正式收盘、是否纸面触发、是否超过上限或触发风险预警。
4. 持仓动作：无仓与有仓分别怎么做。
5. 下一路径、唯一 `nextGate`、最高接受条件和正式失效条件。
