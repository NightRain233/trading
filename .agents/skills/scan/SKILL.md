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
- `primary.accountStatus` 不是"已建仓"时，放在报告第一句。
- `weekLabel` 和主策略 `dates.marketDataDate` 是否新鲜（相差超过一周要说明）；`now.weekComplete=false` 时说明"本周没收盘，阶段按上周收盘"。
- `supertrend.error` 存在时，第 6 段写"学习观察暂不可用"，其余照常。

## 3. 输出（按顺序，标题用中文）

0. **决策层（四五行，整份报告只在这里下结论）**：
   - 账户状态（`accountStatus`）。
   - 组合处境：按 `primary.targetByStage` 说主策略目标仓位有多少在上涨、多少在下跌阶段，并照 market-rules 说明"阶段只描述现状、不预测走势"；不建议调仓。
   - 这周要不要操作。
   - 这周最值得盯的一件事：具体到价位、离上周收盘多远、几次正常周波动；需要时补一句"截至 `now.asOf`（盘中）离现价 X%"。
   - 这个判断最可能错在哪：本周没收盘时先说"周五前所有暂定都可能变"，再说最弱的假设。
   后面各段只解释，不再重复结论。
1. **主策略**：
   - 有 `openOrders` 或 `dates.signalDate` 等于最新数据日：写要做什么；否则写"不用操作，下次检查 `nextCheck`"。
   - BTC 开关：日线方向、距 ST 线百分比、正式开关；`flipPending=true` 时说明"将在下次检查日执行"。按 `btcSwitch.rule` 说明它不是止损。
2. **大盘阶段**：一张表，列 = 市场 / 阶段与周数（上周收盘）/ 区间位置（行上的 `bandPositionPct`）/ 换阶段线（价位、离上周收盘、几次正常周波动）。表头写明"距离按上周收盘"；最新价是盘中的市场在表下注明。`typicalMoves` ≤ 1 的标"⚠️ 一个普通的周就能碰到"。表下每个市场一句裁定，按 market-rules 3.1 的顺序（结构 → 强弱 → 量价），量能只用 `volumeLabel`，例如"结构还在，强弱转弱，量能正常 → 按规则持有，不该加"。
3. **换阶段**：只列大盘、主策略品种、美股学习账户和 BTC/ETH；A 股个股和行业 ETF 的换阶段只给个数。先列 `stageChanges`（已确认），再列 `provisionalStageChanges`（暂定）；`conflict=true` 的写明"周五若成立，上周那次是假信号"。没有就写"没有"。
4. **美股学习账户**：按 `rule` 分组——可买、持有、卖出、不持有。持有组每个写一个数：离卖出线几次正常周波动。卖出组写一句"如果是假跌破"：规则会先卖，重新站上 30 周线 2% 以上再买回，来回大约损失两条线之间的距离（约 4%）。
5. **A 股只看状态**：`cn.stageCounts` 一句话；列出 `stage2StrongerThanCsi300`；不写买卖建议。加密和其他市场各一句。
6. **学习观察（SuperTrend）**：一行，只写非 stable 分组的数量和名称；`blocked` 说成"市场模式不允许开仓"，不是数据问题。`marketModes` 与大盘阶段冲突时加一句"两套口径不一致，以周线为准"。

## 4. 风格

- 结论只在决策层出现一次；整份不超过一屏半。
- 指标冲突时按 market-rules 3.1 的顺序裁定，写出裁定结果，不并列罗列。
- 数字保留一位小数，带正负号和单位。
- 不堆指标：正文里一个品种最多两个数字（表格除外）。
- 用户追问某个品种时，切换到 `analyze` skill。
