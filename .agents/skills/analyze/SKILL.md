---
name: analyze
description: Use when the user asks to analyze a specific stock, ETF, cryptocurrency, commodity, or index with the project's unified trading decision, entry timing, action recommendation, and invalidation risks.
---

# /analyze — 单标的统一决策分析

使用现有 `/api/quote/{symbol}` 分析指定标的。先完整读取 `../trading-analysis/references/decision-contract.md`；策略阈值和权限语义不在本文件重复定义。分析必须回答当前处于哪段生命周期、为什么不能升级，以及下一条可参与路径。

## 1. 分析前准备

若用户未提供 symbol，先询问。开始分析后：

1. 读取 `reviews/README.md`。
2. 检查最近 3 个自然日内存在的每日复盘、`reviews/持仓总览.md` 和对应品种页。
3. 品种页与每日复盘冲突时，以品种页当前有效规则为准；不得沿用过期价格、止损或仓位。
4. 最近三天无有效复盘时，明确说明本次只依据行情数据。

## 2. 获取数据

本地优先：

```bash
uv run python scripts/trading_analysis_helper.py \
  --api-base http://127.0.0.1:8000/api \
  --query stock --symbol <SYMBOL> --timeout 180
```

本地不可用或用户要求生产数据时，使用同一命令改为 `http://8.153.71.148/api`。同一次分析中的行情、scan 和 portfolio 查询不得混用不同 API base。

## 3. 契约与数据检查

先确认：

- `schemaVersion == 2` 且存在 `policyVersion`
- `decision`、`primaryGroup`、`marketMode`、`marketModeContext` 完整
- `decisionHistory`、`lifecycle`、`decision.nextGate` 和 `decision.readinessScore` 完整
- `dataQuality.dataStale == false`
- `dataQuality.dataIntegrity` 无近期缺口
- `sessionContext.formalDecisionAvailable == true`
- 只有正式决策不存在、数据过期或存在缺口时才按数据异常阻断
- `weeklyState` 使用最近完整周，`weeklyProvisionalState` 只能说明临时方向

当前 session 进行中不是数据异常。沿用最近完整收盘决策，并读取 `executionStatus` 管理盘中执行。

## 4. 决策顺序

按以下顺序解释，不得跳步：

```text
数据有效性 -> 市场模式 -> 正式周线 -> 正式日线信号
-> ADX 门槛 -> 距 ST 的 ATR 距离 -> 辅助指标 -> 持仓执行边界
```

直接采用正式 `decision.permission` 和 `decision.label`，再单独解释 `executionStatus` 与 `positionGuidance`：

- `buy`：技术条件可执行，仍需检查持仓和风险预算。
- `conditional`：压缩突破纸面实验计划；即使进入 `paper_armed_triggered` 也禁止实盘执行。
- `wait`：结构允许但触发或确认不足。
- `watch`：只观察，不建立新仓。
- `risk`：只处理已有持仓风险。
- `blocked`：数据或市场条件禁止形成交易结论。

不得因为 RSI 超卖、MACD 改善、背离、BOLL 位置、KDJ 或成交量而升级 API 权限。`stVal` 是 SuperTrend 支撑/阻力锚点，不是前高或平台突破价。

## 5. 路径

- `breakout`：完整收盘已经 `bull_flip`，按周线、市场、ADX 和 2 ATR 上限判断。
- `pullback`：已确认多头趋势回到 1.5 ATR 支撑区，等待完整日线重新走强。
- `compression_breakout`：尚未完成样本外与交易成本验证，只能纸面跟踪；正式周线和市场条件不足时仍为 `compression_watch`。

压缩路径的盘中触发不是临时创造信号。上一完整收盘必须已经给出固定触发、上限和失效价；盘中只能记录等待、纸面触发、取消追价或失效。`authorization.consumptionTracked=false` 时不得声称已经成交或消费。

## 6. 状态演化与失败诊断

读取 `decisionHistory` 和 `lifecycle`，用最近 5-10 个完整日线概括：

```text
趋势方向 -> 压缩/回踩 -> 动能变化 -> 正式触发 -> 当前乖离
```

明确标记 `lifecycle.signalStatus`：尚未触发、正在形成、纸面布防/触发、正式买点可执行、已触发但过度扩张或趋势中无入场。按 `failureCategory` 区分数据、市场、方向、强度、价格和时机失败。价格失败不等于方向错误；方向失败不得用低价或超卖美化。

## 7. 行动建议

- 先复述 `decision.reasonCodes` 和 `failedGates`，再用 EMA、RSI、MACD、BOLL、KDJ、量能解释背景。
- 使用 `decision.nextTrigger` 写下一步；实际能否盘中执行以 `executionStatus.executable` 为准。
- 先写唯一的 `decision.nextGate`，再写其他次要条件。量化当前距离、触发价、最高接受价和失效价。
- 使用 `decision.invalidation` 作为主要失效条件。除非具体策略另有明确规则，不机械生成 `entry - 1.5×ATR` 止损。
- 复盘显示当前持仓时自动进入持仓模式；涉及实际数量或组合调仓时再查询同一 API base 的 portfolio。
- 无仓且价格过度扩张时禁止追高；已有仓位不因乖离大自动卖出，按 `positionGuidance` 和正式 ST 管理。

## 8. 输出格式

1. 一句话正式决策
2. 实时价、正式收盘、正式决策日和会话状态
3. 最近状态演化与“是否曾有参与窗口”
4. 已通过条件、首要失败门槛及失败类型
5. 盘中执行状态
6. 无仓与有仓的不同动作
7. 下一路径、唯一 `nextGate`、触发价、最高接受条件和正式失效条件
8. 关键辅助指标与复盘冲突
