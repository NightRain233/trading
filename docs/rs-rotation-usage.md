# RS轮动策略使用指南

## 快速开始

### 查看当前持仓

前端首页点击 **RS轮动** 标签，或直接访问 `RsHoldingsPanel` 组件。

后端 API：
```
GET /api/backtest/rs-rotation/holdings?preset=rs_rotation_a_share
```

返回当前再平衡日的 top5 持仓及各标的 RS 分数。

---

### 手动触发排名

```bash
cd backend
uv run python backtest.py \
  --universe-file universes/a_share_etf_core.json \
  --data-dir data \
  --start 2024-01-01 \
  | python -c "import json,sys; r=json.load(sys.stdin); print(r['rsRotationPortfolio']['equityCurve'][-1])"
```

输出最新一个再平衡日的持仓快照。

---

## 两个预设说明

| 预设 | 池子 | 过滤器 | 适用场景 |
|------|------|--------|---------|
| `rs_rotation_a_share` | A股ETF（31只） | CSI300月MACD + 日均>1亿 | 只做A股，回撤控制优先 |
| `rs_rotation_global` | A股ETF + SPY/QQQ/GC=F/BTC-USD | 各资产类别自己的月MACD | 全球分散，2020/2025年表现更好 |

---

## 修改再平衡日

`simulate_rs_rotation_portfolio` 的 `rebalance_days` 参数控制再平衡频率（默认20个交易日≈1个月）。

**不建议修改**：20日是经过2015-2026回测验证的最优值。更短（10日）会增加交易成本，更长（40日）会错过趋势切换。

如需调整，在调用处传入：
```python
simulate_rs_rotation_portfolio(frames, rebalance_days=20, ...)
```

---

## 扩大 ETF 池子

当前 `universes/a_share_etf_core.json` 已包含 `backend/data/` 目录里所有 A 股 ETF（31只）。

新增 ETF 步骤：
1. 在 `backend/data/` 下载新 ETF 的日线和周线 parquet（通过 `analysis.py` 的缓存机制自动生成）
2. 在 `a_share_etf_core.json` 的 `symbols` 数组里添加条目：
   ```json
   {"symbol": "XXXXXX.SS", "name": "ETF名称", "bucket": "sector"}
   ```
3. 运行回归测试确认数字在容差范围内：
   ```bash
   uv run python -m pytest tests/test_backtest.py::RsRotationRegressionTests -v
   ```

---

## 市场过滤器说明

`market_filter_mode` 支持以下值：

| 模式 | 含义 | 推荐场景 |
|------|------|---------|
| `monthly_macd` | 月线 DIF > DEA | A股/全球（当前默认） |
| `weekly_macd` | 周线 DIF > DEA | 不推荐，切换太频繁 |
| `ema20_slope` | EMA20 10日内上升 | 不推荐，趋势初期会错过 |
| `close_above_ema50` | 收盘 > EMA50 | 备选 |
| `none` | 不过滤，始终持仓 | 仅用于对比测试 |

---

## 回测结果解读

`equityCurve` 每条记录包含：
- `date`：日期
- `equity`：归一化净值（初始=1.0）
- `drawdownPct`：当前回撤百分比
- `openPositions`：持仓数量（0=空仓）
- `holdings`：当前持仓标的列表

`openPositions == 0` 的连续区间即为月MACD过滤触发的空仓期。
