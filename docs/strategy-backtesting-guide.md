# 策略回测复盘指南

这份文档记录本轮策略研究的收获，并说明新增的可重复比较脚本如何使用。目标不是证明某个指标永远正确，而是把“为什么现在默认看 SuperTrend”变成可复查、可重跑、可扩展的证据。

## 本轮主要收获

1. **基础 SuperTrend 更适合做默认观察页。**  
   在 2021-05-31 至 2026-05-30 的本地缓存数据中，SuperTrend 在中国 ETF/代理、美股/ETF、BTC、全球观察池四组里，收益回撤比都明显高于当前 RS 动量轮动。

2. **ADX 入场过滤没有带来更好的收益回撤比。**  
   ADX >= 20/25/30 的过滤确实减少了交易和回撤，但它砍掉的有效趋势更多。当前样本里，最优 ADX 过滤仍低于基础 SuperTrend。

3. **周线 BB 突破+回踩不适合作默认入口。**  
   它更像低频主题机会策略。美股组有正收益，但中国 ETF 和全球观察池的收益回撤比明显弱于 SuperTrend。

4. **“普通人适合”更接近收益回撤比，而不是单纯收益最大。**  
   美股买入持有等权收益很高，主要受强趋势大牛股影响；但它要求承受大波动、持续持有、选中强势标的。SuperTrend 的价值是把风险控制和趋势跟踪合成一个低维护流程。

## 新增脚本

脚本路径：

```bash
backend/strategy_comparison.py
```

作用：

- 固定同一批资产组，比较基础 SuperTrend、RS 动量轮动、买入持有、ADX 过滤 SuperTrend、周线 BB 突破+回踩。
- 自动读取 `backend/data/*.parquet` 本地缓存。
- 缺少周线缓存时，会用日线数据临时重采样生成周线。
- 输出 Markdown 或 JSON，便于写报告、做网页、后续接前端。

默认比较区间：

```text
2021-05-31 至 2026-05-30
```

默认资产组：

- 中国 ETF/A股代理：`backend/universes/a_share_etf_core.json`
- 美股/ETF：`SPY`, `QQQ`, `AAPL`, `GOOGL`, `NVDA`, `TSLA`
- BTC：`BTC-USD`
- 全球观察池：中国 ETF/A股代理 + `SPY`, `QQQ`, `GC=F`, `BTC-USD`

## 使用方法

在仓库根目录执行：

```bash
cd backend
PYTHONPATH=. uv run python strategy_comparison.py --format markdown
```

输出 JSON：

```bash
cd backend
PYTHONPATH=. uv run python strategy_comparison.py --format json
```

换回测区间：

```bash
cd backend
PYTHONPATH=. uv run python strategy_comparison.py \
  --format markdown \
  --start 2022-01-01 \
  --end 2026-05-30
```

使用其他数据目录：

```bash
cd backend
PYTHONPATH=. uv run python strategy_comparison.py \
  --data-dir /path/to/parquet-data \
  --format markdown
```

## 当前策略假设

### SuperTrend

- 日线 SuperTrend 翻多买入。
- 日线翻空或触及 SuperTrend 线卖出。
- 用周线 SuperTrend 多头作为入场过滤。
- 手续费和滑点按单边 5 bps 估算。

### ADX 过滤

- 只过滤入场，不阻止离场和止损。
- 测试阈值：ADX >= 20、ADX >= 25、ADX >= 30。
- 当前结论：不建议作为默认过滤，因为收益回撤比未改善。

### RS 动量轮动

- 60 日相对强弱排序。
- 每 20 个交易日调仓。
- 按资产类别使用月 MACD 做市场过滤。

### 周线 BB 突破+回踩

- 使用 `weekly_bb_breakout_ma30`。
- 优先识别周线突破，没有突破时接受突破后的回踩确认。
- 最大持仓 90 天。

## 历史具体买卖点怎么看

不建议把所有标的的历史买卖点塞进静态 HTML 报告。

原因：

- 买卖点是交互型问题：你通常会问“某个标的、某段时间、某个策略参数下发生了什么”。
- 静态报告适合解释结论，不适合承载大量 K 线、交易列表、筛选、缩放、复盘标注。
- 如果把所有交易点都放进 HTML，文件会很大，而且每次换标的/参数都要重新生成。

更好的设计是做一个专门的前后端查询页：

- 后端提供 `/api/backtest/trades` 或 `/api/supertrend/trades/{symbol}`。
- 参数包含 `symbol`、`strategy`、`start`、`end`、`minAdxForEntry`、是否启用周线过滤。
- 返回交易列表、买卖点 marker、回撤曲线、每笔收益。
- 前端在图表上叠加 SuperTrend 线和买卖点，并允许切换策略。

HTML 报告可以保留一个“怎么看买卖点”的入口说明和一两个示意图，但不应该替代交互式复盘页。

## ST 标的太多怎么办

当前 SuperTrend 默认页会扫描观察池里的所有标的。它适合作为总雷达，但日常使用确实可能信息太多。

更合理的做法是**分层精简**，而不是直接砍到很少的标的：

1. **默认层：只看高优先级和可操作信号。**  
   包括刚翻多、刚翻空、接近 SuperTrend 支撑/阻力的标的。适合每日快速检查。

2. **确认层：优先看周线多头 + 日线翻多/支撑回踩。**  
   这类信号更少，也更符合“少操心”的使用方式。

3. **候补层：保留所有多头但降低显示权重。**  
   它们不是今天要动的标的，但可以观察趋势延续。

4. **回避层：空头且非阻力测试的标的默认折叠。**  
   保留数据，但不占用注意力。

不建议一开始把标的池砍得太狠。SuperTrend 的收益来自覆盖足够多的趋势机会；如果只保留少数标的，可能体验变轻，但错过趋势的概率也会上升。

下一步应该做的是：把不同筛选层也纳入回测，例如：

- 只交易刚翻多。
- 只交易周线多头 + 日线刚翻多。
- 只交易支撑回踩。
- 只交易高优先级提醒。
- 只交易高优先级且资产组分散。

如果这些精简层的收益回撤比接近基础 ST，就可以把前端默认视图进一步收窄；如果明显变差，就保留广覆盖扫描，但用 UI 折叠和排序降低心智负担。

