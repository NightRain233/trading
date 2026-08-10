---
name: trading-analysis
description: Deep interactive analysis of unified SuperTrend decisions, individual stocks and ETFs, market scans, and portfolio strategies. Use for signal investigation, cross-market comparison, portfolio review, or non-trivial trading research.
---

# Trading Deep Analysis

所有分析使用后端统一策略契约。分析单标的或调查信号前，读取 `references/decision-contract.md`。API 给出正式收盘的 `buy/conditional` 权限，盘中数据管理执行，复盘或 portfolio 决定是否进入持仓模式。

## 数据入口

| Endpoint | 用途 |
|---|---|
| `GET /api/quote/{symbol}` | 单标的完整行情、指标和统一 `decision` |
| `GET /api/supertrend/scan?force=false&include_candles=false` | 全自选 v2 扫描矩阵 |
| `GET /api/portfolio-strategies` | 组合策略与 bootstrap 状态 |
| `GET /api/portfolio-strategies/{id}/snapshot` | NAV、权重、信号、账本与执行状态 |
| `GET /api/portfolio-strategies/{id}/nav` | NAV 时间序列 |

优先使用本地 `http://127.0.0.1:8000/api`；本地不可用或用户明确要求生产数据时使用 `http://8.153.71.148/api`。一次分析不得混用 API base。

使用 `scripts/trading_analysis_helper.py` 获取结构化数据。单标的用 `--query stock --symbol <SYMBOL>`，市场扫描默认用 `--query overview` 同时取得正式分组和组合执行上下文，组合细节用 `--query portfolio`。

## 通用纪律

1. 先读取 `reviews/README.md`、最近 3 个自然日内存在的复盘、持仓总览，以及持仓和最终重点标的的品种页。
2. 先验证 schema、coverage、正式决策日期、数据缺口和正式周线，再解释信号。
3. `weeklyState` 才能授予方向权限；临时日/周/月结构只展示，不能升级权限。
4. 分开输出正式 `decision`、盘中 `executionStatus` 和 `positionGuidance`。
5. `reasonCodes` 表示已通过条件，`failedGates` 表示不能升级的直接原因。
6. RSI、KDJ、MACD、背离、BOLL 和量能均为辅助证据，不能绕过市场模式、周线、日线触发、ADX 或距离门槛。
7. `cacheStale` 只表示缓存刷新状态；`dataStale` 或近期缺口才会阻断行情结论。
8. 盘中信息只可执行上一完整收盘的 `buy/conditional` 许可、取消/降级执行或提示风险，不得升级普通 `wait/watch`。
9. 扫描技术许可不等于组合执行许可。实际动作还要检查 `executableWeights`、pending rebalance、ledger 和 diagnostics。

## 单标的工作流

1. 调用 `/api/quote/{symbol}`，确认 `schemaVersion == 2`、`policyVersion` 和 `decision` 存在。
2. 检查 `dataStale`、`dataIntegrity`、`sessionContext` 和正式 `weeklyState`。session 进行中不等于数据异常。
3. 读取所属 `marketMode`：
   - `seek`：ADX 门槛通常为 25。
   - `cautious`：ADX 门槛提高到 30。
   - `survival`：禁止新仓。
   - `insufficient`：不给自动买入许可。
4. 直接采用 `decision.label`，说明 `setup`、`stage`、`nextGate`、readiness、已通过条件和失败门槛。
5. 用 `decisionHistory/lifecycle` 概括最近状态演化，说明是方向、强度、价格还是时机问题，并判断是否曾有参与窗口。
6. 再解释 EMA20/50、ADX 变化、RSI21、MACD 柱变化、BOLL、KDJ、完整量比和确认背离。
7. 用 `executionStatus` 判断盘中能否执行。压缩突破必须核对 `triggerPrice`、`maxAcceptablePrice` 和 `invalidationPrice`。
8. 复盘或 portfolio 显示当前持仓时，必须单独回答持有、减仓、退出或风险预警。

若 API 返回 `buy` 但 `executionStatus.executable=false`，保留正式信号记录但不得追买。`conditional` 压缩突破当前为纸面实验：`paper_armed_triggered` 也不得实盘执行。若返回 `wait/watch/blocked`，盘中或辅助指标不得将其升级。

## 信号调查工作流

当用户问“为什么进入某组”或“为什么不是可买”时：

1. 在 scan 的 `items[]` 中按 symbol 定位，不能依据截断输出判断缺失。
2. 核对 `primaryGroup` 与 `groups.*.symbols` 一致。
3. 逐项翻译 `reasonCodes` 和 `failedGates`。
4. 对照 `marketModeContext.adxThreshold`、正式周线、日线状态、`distanceToSupertrendAtr` 和形态上下文。
5. 给出 `failureCategory`、权限升级所需的唯一 `nextGate`，以及当前失效条件。

## 市场扫描工作流

市场级扫描必须读取并遵循 `../scan/SKILL.md`，直接使用 API 正式分组、`attention`、`changes` 和 `themes`。用 overview 的 `portfolioMatrix` 分离技术与组合权限。不得恢复旧的自定义分组，也不得只按距离、RSI 或不透明综合分数重排全部标的。

## 组合工作流

1. 查询策略列表和对应 snapshot。
2. 检查 NAV、回撤、当前与目标权重、pending rebalance、ledger、diagnostics 和 `executableWeights`。
3. 区分技术信号、模型目标权重与当前可执行动作。
4. `BLOCKED`、空 `executableWeights` 或会话不完整时，不得输出实际调仓指令。

## 输出要求

先给正式权限结论，再按三层展开：

- 正式决策及其日期
- 最近状态演化、是否曾有参与窗口与失败类型
- 盘中执行状态与实时/正式价格差异
- 无仓和有仓分别怎么做
- 下一触发、最高接受条件和正式失效条件
- 需要组合确认的执行边界

不要用大段指标描述掩盖行动结论，也不要把 ST 值描述成未经计算的前高、平台上沿或结构突破位。
