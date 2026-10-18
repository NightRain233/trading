---
name: scan
description: Use when the user asks for a market scan, weekend review, "看看现在市场怎么样", watchlist ranking, or which markets/symbols are worth watching. Produces the primary-strategy status first, then Weinstein weekly stages by market, with SuperTrend compressed to one learning line.
---

# /scan — 周末复盘扫描

回答三个问题：**主策略这周要不要动？各个市场处在什么阶段？学习账户按规则该怎样？**

开始前完整读取 [../shared/market-rules.md](../shared/market-rules.md)。口径、边界和"不能下的结论"以它为准。

## 1. 取数

```bash
uv run python scripts/trading_analysis_helper.py --query weekly --timeout 120
```

若用户有近期复盘，再读 `reviews/README.md` 和最近 7 天的复盘文件，只用来对照"上次说要关注什么"，不沿用旧价格。

## 2. 检查

- `primary` 存在；`primary.diagnostics` 有 error/warning 时先报告。
- `weekLabel` 和主策略 `dates.marketDataDate` 是否新鲜（相差超过一周要说明）。
- `supertrend.error` 存在时，第 6 段写"学习观察暂不可用"，其余照常。

## 3. 输出（按顺序，标题用中文）

1. **主策略**：一句话"这周要不要操作"。
   - 有 `openOrders` 或 `dates.signalDate` 等于最新数据日：写要做什么。
   - 否则写"不用操作，下次检查 `nextCheck`"。
   - BTC 开关：日线方向、距 ST 线百分比、正式开关；`flipPending=true` 时说明"将在下次检查日执行"，不是已经交易。
2. **大盘阶段**：表格列出 `benchmarks`（市场 / 阶段 / 已持续周数 / 离 30 周线 / 30 周线方向），再用一两句话总结。离 30 周线 3% 以内的上涨阶段要提醒"贴近 30 周线"。
3. **本周换阶段**：逐个列 `stageChanges`，说明从几到几、意味着什么。没有就写"没有"。
4. **美股学习账户**：按 `rule` 分组写——可买（新进第二阶段）、持有、卖出（跌破 30 周线）、不持有。每组列名称和一个关键数字（相对强度或离 30 周线）。
5. **A 股只看状态**：`cn.stageCounts` 一句话概括；列出 `stage2StrongerThanCsi300`；不写买卖建议。加密和其他市场各一句。
6. **学习观察（SuperTrend）**：一行，只写非 stable 分组的数量和名称。若 `marketModes` 与大盘阶段冲突，加一句"两套口径不一致，以周线为准"。
7. **一句话结论**：这周最值得记住的一件事。

## 4. 风格

- 先结论后理由；整份不超过一屏半。
- 数字保留一位小数，带正负号和单位。
- 不堆指标：一个品种最多两个数字。
- 用户追问某个品种时，切换到 `analyze` skill。
