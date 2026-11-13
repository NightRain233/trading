---
name: daily-market-brief
description: 每日短周期技术日报：读取自选技术指标，挑出当天异动，给出大局 AI 解读，并把 AI 的五个交易日方向判断记录下来复核。
---

# 每日自选技术日报

这个 skill 面向周二到周六上海时间 08:30 的 Hermes 定时任务。它只看行情和技术指标，不搜索新闻；主策略三只品种每天都列出，其他自选只列当天有明显变化的前 12 个。

## 运行顺序

在 trading 仓库根目录执行。默认读取本地后端；Hermes 的生产任务把同一个 `TRADING_API_BASE` 传给三个命令，不能混用来源。

```bash
python scripts/daily_market_brief.py --mode evaluate --api-base "${TRADING_API_BASE:-http://127.0.0.1:8000/api}"
python scripts/daily_market_brief.py --mode report --api-base "${TRADING_API_BASE:-http://127.0.0.1:8000/api}"
```

`evaluate` 会把已经满 5 个交易日的旧判断用真实收盘价评分；`report` 只读行情和成绩账本。两条命令失败时要报告“数据不可用”，不能说成“今天没有异动”。

## 日报内容

读取 `report` 返回的 JSON 后，按这个顺序写中文日报：

1. **主策略状态**：先转述 `primaryStrategy` 的状态、净值/回撤和下次检查日；有待执行订单才写执行提醒。`calcError`、`diagnostics` 或 `dataQualityEventCount` 有值时先报异常。这个区块只说冻结规则，不由 AI 观点改仓。
2. **市场温度**：A 股（沪深300）、美股（SPY）、BTC、黄金，各写状态、单日/近 5 日/近 20 日变化、是否站在 EMA20/EMA50 上方、RSI14、MACD 柱方向和成交量相对 20 日均量。它是观察，不预测走势。
3. **自选异动**：只写 `anomalies`，每个标的一句话，说明 `reasons` 和指标组合，再给 `bull`、`bear` 或 `neutral` 观点及 0 到 100 的置信度。`primaryWatch` 的沪深300ETF、纳指100ETF、黄金ETF 无论是否异动都要写，但不把它们写成调仓指令。
4. **AI 大局判断**：根据 `overviewPrompt` 写 3 到 5 句，按结构、动能、量价顺序；指标冲突时说清冲突，不补新闻和基本面故事。
5. **AI 成绩**：把 `forecastLedger` 的近 30 次已评分数量、正确数量、准确率和置信度分组写出；没有样本时写“尚无 5 日样本”。

`technicalPermission`、SuperTrend 状态和市场温度只说明技术观察。A 股标的不能写买入/卖出建议；主策略持仓不因这些短周期观点改变。可以写“看多/看空/观望”作为待验证的方向判断。

## 记录当天判断

日报写完后，把每个 `anomalies` 和 `primaryWatch` 各给一个方向判断，通过 stdin 交给记录命令。不要自己填写价格和日期，程序会从同一份 API 扫描中记录收盘价：

```bash
cat <<'JSON' | python scripts/daily_market_brief.py --mode record --api-base "${TRADING_API_BASE:-http://127.0.0.1:8000/api}"
{
  "forecasts": [
    {"symbol": "NVDA", "stance": "bear", "confidence": 65, "reason": "跌幅、RSI和放量共同转弱"},
    {"symbol": "510300.SS", "stance": "neutral", "confidence": 55, "reason": "主策略观察，短线信号冲突"}
  ]
}
JSON
```

`stance` 只能是 `bull`、`bear`、`neutral`；置信度只能是 0 到 100。只有 bull/bear 计入成绩，neutral 只留档。记录文件默认在 `backend/data/ai_forecasts.json`，服务器容器中对应 `/app/data/ai_forecasts.json`，不会进入 Git。

## 口径

- 数据日期以每个标的的 `latestDataDate` 为准，跨市场日期不同要照实写。
- 结构优先于动能：趋势状态 → RSI/MACD → 量能/布林带。不能用 RSI 超买超卖单独断言反转。
- 主策略仍是 `btc_supertrend_satellite`；这份日报是短周期学习观察，不能覆盖组合规则。
- 5 个交易日按该标的真实交易日计算，周末和休市日不算。成绩由程序计算，Hermes 只转述。
