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
- 说明数据日期（`latestDataDate`）和最新一周是否已收盘。

## 3. 输出

1. **一句话结论**：阶段 + 规则状态 +（若 SuperTrend 一致/不一致）。A 股、黄金只写状态，不写买卖。
2. **周线位置**：收盘、30 周线、离 30 周线、30 周线方向、相对强度（对比谁）。
3. **最近 10 周怎么走过来的**：从 `recentWeeks` 概括阶段变化、是否反复穿越 30 周线、布林带是否收窄、量能有无异常。
4. **SuperTrend 是否一致**：`supertrend.label` 和 `nextGate`，一两句话；两者冲突时说明各自看的周期。
5. **和主策略的关系**：
   - `inPrimaryStrategy=true`：明确写"这是主策略的持仓，按主策略规则持有，阶段变化不影响它"，再说它在组合里的作用（分散、增长或卫星）。
   - 否则说明它属于学习账户（美股）、只看状态（A 股、黄金）或主策略之外的观察。
6. **接下来看什么**：一两个具体价位或条件，例如"周收盘跌破 325（布林下轨）就进入第四阶段"、"站回 30 周线 2% 以上恢复第二阶段"。

## 4. 风格

- 先结论后理由，通俗中文，不超过一屏。
- 不给仓位数量；不说"必涨/必跌"；不把观察说成指令。
