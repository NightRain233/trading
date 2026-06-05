# SuperTrend 适配度筛选研究 2026-06-05

## 研究目的

本轮研究验证一个问题：能否用过去 2 年数据事前筛出更适合默认日线 `ST(7,3)` 的标的，并在未来 6 个月样本外验证。

这不是机器学习模型，而是固定规则的启发式打分。评分权重事前固定，验证期结果不参与打分、归一化、分层或权重选择。

## 数据与窗口

- 样本池：现有 `backend/watchlist.json` + 本地 parquet 缓存。
- 标的数：34。
- 重点分桶：A 股 ETF 13 个、A 股个股 12 个、美股 ETF 2 个、美股个股 4 个。
- 研究区间：`2021-06-05` 至 `2026-06-05`。
- 滚动窗口：过去 2 年训练，未来 6 个月验证，步长 6 个月。
- 窗口数：6。
- 总 symbol-window：204。
- 策略：默认日线 `ST(7,3)`，沿用收盘确认、下一交易日开盘执行口径。

输出文件：

```text
backend/backtest_results/supertrend_fit_research_2026-06-05.json
```

运行命令：

```bash
cd backend
PYTHONPATH=. uv run python ../scripts/research_supertrend_fit.py \
  --output backtest_results/supertrend_fit_research_2026-06-05.json
```

## 三种评分

| 模式 | 含义 |
|---|---|
| `history` | 训练期 ST 相对买入持有的收益回撤改善、回撤下降、超额 log return、平均单笔收益，并惩罚训练期交易太少。 |
| `shape` | 训练期形态特征：63 日趋势效率、ADX 趋势占比、EMA 多头持续性、ST 翻转密度、ATR 波动稳定性。 |
| `hybrid` | 固定组合：`0.60 * adjustedHistoryScore + 0.40 * shapeScore - lowTradePenalty`。 |

评价主指标是验证期 `testExcessRddSafe`，即默认 ST 的安全收益回撤比减去买入持有的安全收益回撤比。安全收益回撤比用 `max(maxDD, 5%)` 做分母，避免极小回撤导致比值爆炸。

## 总览

| 分桶 | 最有用评分 | Rank IC | Top-Bottom Excess R/DD | Top Beat BH R/DD | 判断 |
|---|---:|---:|---:|---:|---|
| A 股 ETF | `history` / `hybrid` | `0.19` / `0.14` | `+0.33` / `+0.31` | `45.8%` / `54.2%` | 有弱正向信号。 |
| A 股个股 | 无 | 约 `-0.07` 到 `-0.09` | 负或很弱 | `25%-29%` | 不成立。 |
| 美股 ETF | 无 | 约 `-0.17` 到 `+0.03` | 不稳定 | `33.3%` | 样本只有 2 个，不能解读。 |
| 美股个股 | 无 | 约 `-0.09` 到 `-0.28` | 明显负 | `16.7%-33.3%` | 不成立，Top 反而更差。 |

## A 股 ETF

A 股 ETF 是本轮唯一看到弱正向样本外信号的分桶。

| 评分 | Rank IC | Top Excess R/DD | Bottom Excess R/DD | Top-Bottom | Top Beat BH R/DD |
|---|---:|---:|---:|---:|---:|
| history | `0.19` | `-0.30` | `-0.64` | `+0.33` | `45.8%` |
| shape | `0.07` | `-0.46` | `-0.38` | `-0.07` | `41.7%` |
| hybrid | `0.14` | `-0.16` | `-0.48` | `+0.31` | `54.2%` |

解读：

- `history` 和 `hybrid` 能把更差的 ETF 放到底部，Top 相对 Bottom 的验证期 Excess R/DD 为正。
- 但 Top 平均 ST 收益不高，且 Top 最大回撤高于 Bottom。这个筛选更像“提高相对买持的风险收益胜率”，不是收益增强器。
- `shape` 单独不够好，说明当前形态因子还不能替代训练期 ST 表现。

结论：A 股 ETF 可以继续研究适配度筛选，但只作为研究过滤/排序，不直接产品化为硬门槛。

## A 股个股

| 评分 | Rank IC | Top Excess R/DD | Bottom Excess R/DD | Top-Bottom | Top Beat BH R/DD |
|---|---:|---:|---:|---:|---:|
| history | `-0.09` | `-0.86` | `-0.46` | `-0.40` | `16.7%` |
| shape | `-0.07` | `-0.59` | `-0.67` | `+0.08` | `29.2%` |
| hybrid | `-0.08` | `-0.73` | `-0.45` | `-0.28` | `25.0%` |

解读：

- 训练期表现好的个股，在未来 6 个月并没有延续优势。
- `shape` Top-Bottom 略正，但 Rank IC 为负，且 beat buy-hold R/DD 没改善。
- 这与前一阶段报告一致：个股分化大，且当前 watchlist 里有指数、强周期和特殊强趋势样本，简单规则容易被少数标的扰动。

结论：A 股个股暂不适合做 ST 适配度筛选产品化。后续需要先清洗样本池，再研究 `ST(10,3)` 或行业/波动分层。

## 美股 ETF

| 评分 | Rank IC | Top Excess R/DD | Bottom Excess R/DD | Top-Bottom | Top Beat BH R/DD |
|---|---:|---:|---:|---:|---:|
| history | `-0.17` | `-0.85` | `-0.69` | `-0.16` | `33.3%` |
| shape | `0.03` | `-0.71` | `-0.83` | `+0.11` | `33.3%` |
| hybrid | `-0.01` | `-0.87` | `-0.67` | `-0.19` | `33.3%` |

解读：

- 美股 ETF 只有 `QQQ` 和 `SPY`，每个窗口只能排 top/bottom，没有 mid。
- 当前结果不支持适配度筛选。
- 前一阶段结论仍然更重要：美股 ETF 默认 `ST(7,3)` 主要用于降低回撤，不是为了跑赢买持收益。

结论：美股 ETF 样本太少，不应基于本研究做筛选规则。

## 美股个股

| 评分 | Rank IC | Top Excess R/DD | Bottom Excess R/DD | Top-Bottom | Top Beat BH R/DD |
|---|---:|---:|---:|---:|---:|
| history | `-0.25` | `-1.36` | `-0.41` | `-0.95` | `16.7%` |
| shape | `-0.09` | `-0.99` | `-0.44` | `-0.55` | `33.3%` |
| hybrid | `-0.28` | `-1.36` | `-0.41` | `-0.95` | `16.7%` |

解读：

- 三种评分都没有样本外正向筛选能力。
- Top 组验证期 ST 收益有时很高，但 Excess R/DD 明显更差，说明它可能选中了波动更高的标的，而不是更适合 ST 的标的。
- 当前样本只有 `AAPL`, `GOOGL`, `NVDA`, `TSLA`，NVDA/TSLA 会强烈影响均值。

结论：美股个股不应使用本轮 fitScore。扩大样本前，不建议把适配度筛选接到产品。

## 结论

1. 当前 watchlist 样本下，**A 股 ETF 的 history/hybrid 分数有弱正向样本外信号**。它能改善 Top 相对 Bottom 的验证期 Excess R/DD 和 beat buy-hold R/DD 率。
2. **A 股个股、美股 ETF、美股个股没有稳定正向证据**。尤其个股分桶里，Top 往往不如 Bottom。
3. `shape` 单独效果弱，说明当前形态特征不足以替代训练期 ST 表现。
4. `hybrid` 没有全面优于 `history`。A 股 ETF 上它的 beat rate 更好，但 Rank IC 略低；其他分桶不成立。
5. 暂不进入机器学习。当前样本太小，简单 ML 大概率会过拟合窗口、年份和少数强趋势标的。

## 建议

- 产品侧暂不新增硬筛选规则。
- A 股 ETF 可以继续做只读研究排序：默认展示 `history` 与 `hybrid` 的 fitScore，但必须标注“研究信号”。
- 个股侧先不要上 fitScore；先扩样本、清洗指数/ST 股票/特殊周期样本，再复跑。
- 下一轮若继续推进，优先扩展样本池，而不是调权重。
