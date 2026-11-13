# 每日自选技术日报（Hermes / OpenClaw）

周二到周六上海时间 08:30 运行 `/daily-market-brief`。这是主策略日报之外的短周期学习观察，不搜索新闻。

```bash
cd /home/zsd/trading
python scripts/daily_market_brief.py --mode evaluate --api-base "${TRADING_API_BASE:-http://127.0.0.1:8000/api}"
python scripts/daily_market_brief.py --mode report --api-base "${TRADING_API_BASE:-http://127.0.0.1:8000/api}"
```

根据第二条命令的 JSON 输出，按 skill 中的顺序生成中文日报：主策略状态、四个市场温度、自选异动、3 到 5 句大局判断、AI 成绩。不要搜索新闻；不要把主策略三只品种的短线观点改写成调仓建议。

写完后，用当天日报中每个 `anomalies` 和 `primaryWatch` 各一个方向判断调用 `--mode record`。程序负责保存真实收盘价、计算 5 个交易日后的结果和汇总准确率，Hermes 不自行计算成绩。
