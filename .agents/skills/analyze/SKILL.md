---
name: analyze
description: Use when the user asks to analyze one stock, ETF, index, crypto, or commodity ("看看 QQQ", "黄金怎么样", "GOOGL 能买吗"). Weinstein weekly view first, then whether SuperTrend agrees, then how it relates to the primary strategy.
---

# /analyze — 单标的分析

回答：**它现在处在哪个阶段？按规则该怎样？和主策略有没有关系？**

开始前完整读取 [../shared/market-rules.md](../shared/market-rules.md)。用户没给代码时先问。

## 1. 取数

```bash
uv run python scripts/trading_analysis_helper.py --query brief --symbol <SYMBOL> --timeout 120
```

再看 `reviews/` 里有没有这个品种的页面（`reviews/<名称-代码>.md`）和最近 7 天复盘；有的话读出当时的判断和规则，用来对照，不沿用旧价格。

## 2. 检查

- `dataStale=true` 或 `weinstein` 为空：说明数据问题，只给能确认的部分。
- 说明数据日期（`latestDataDate`）；`weinstein.now.weekComplete=false` 时说明阶段按上周收盘（`closedWeek`），`recentWeeks` 最后一行标了 `complete: false` 的是本周暂定数据。

## 3. 输出

1. **一句话结论**：阶段 + 规则状态 + 离换阶段线几次正常周波动（`levels[].typicalMoves`）。A 股、黄金只写状态，不写买卖。
2. **位置**：一张小表——现价、30 周线、区间位置（上周收盘 `bandPositionPct`，本周实时 `now.bandPositionPct` 放括号里）、换阶段线（收盘在价位之上/之下 / 离上周收盘 / 几次正常周波动 / 变成第几阶段；需要时另写"截至 `now.asOf` 离现价 X%"），以及正常一周涨跌幅（`typicalWeeklyMovePct`）。主策略品种另起一行写主策略自己的线（BTC 写 `btcSwitch`），并注明哪条线管钱。
3. **最近 10 周怎么走过来的**：只用已收盘的周概括阶段变化、是否反复穿越 30 周线、布林带是否收窄；量能只用 `volumeLabel`。按 market-rules 3.1 的顺序给出一句裁定（例如"结构还在，强弱转弱，量能不支持 → 持有但不该加"）。
4. **SuperTrend 是否一致**：`supertrend.label` 和 `nextGate`，一两句话；冲突时说明各自看的周期。
5. **和主策略的关系**：
   - `inPrimaryStrategy=true`：明确写"这是主策略的持仓，按主策略规则持有，阶段变化不影响它"，再说它在组合里的作用（分散、增长或卫星）。
   - 否则说明它属于学习账户（美股）、只看状态（A 股、黄金）或主策略之外的观察。
6. **什么情况说明判断错了**：
   - 往不利方向：越过哪条线、要几次正常周波动。
   - 往有利方向：越过哪条线说明这次只是回调（或止跌）。
   - 假跌破的代价：规则先卖、站回 +2% 再买，来回大约差两条线之间的距离（约 4%）；只描述，不发明额外的等待规则。

## 4. 风格

- 先结论后理由，通俗中文，不超过一屏；结论只写一次。正文里一个品种最多两个数字（表格除外）。
- 有 `warning` 或 `conflict` 时，在一句话结论里就说出来。
- 不给仓位数量；不说"必涨/必跌"；不把观察说成指令。
