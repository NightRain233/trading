# 历史买卖点复盘页设计

## 目标

新增一个交互式历史买卖点复盘工具，支持按 `symbol`、`strategy`、`start`、`end` 查询单个标的的历史交易点。首期支持 SuperTrend，返回 K 线、SuperTrend 线、买入/卖出 marker、每笔交易收益、持仓天数和退出原因。该功能作为独立页面提供，不写入静态报告 HTML。

## 推荐方案

采用“单标的 replay 接口 + 独立前端路由”的方案。

后端新增 `GET /api/history-trades`。接口负责读取本地缓存数据，按策略执行历史 replay，并返回图表和交易明细所需的完整结构。首期只接受 `strategy=supertrend`，但保留策略分发层，后续可以接入 ADX 过滤、周线过滤、周线 BB 或其他策略。

前端新增 `/history-trades` 页面。当前应用没有 React Router，继续沿用轻量路径状态：根据 `window.location.pathname` 渲染页面，Header 增加“复盘”入口，并通过 `history.pushState` 切换。生产环境 Nginx 已有 SPA fallback，直接访问该路径仍能加载应用。

## 数据结构

接口响应：

```json
{
  "symbol": "510300.SS",
  "strategy": "supertrend",
  "start": "2023-01-01",
  "end": "2026-05-31",
  "candles": [
    { "time": "2023-01-03", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1000 }
  ],
  "supertrend": [
    { "time": "2023-01-03", "value": 1, "direction": 1 }
  ],
  "markers": [
    { "time": "2023-01-10", "position": "belowBar", "color": "#10b981", "shape": "arrowUp", "text": "买入 1.23", "tradeIndex": 1 }
  ],
  "trades": [
    {
      "tradeIndex": 1,
      "entryDate": "2023-01-10",
      "exitDate": "2023-02-10",
      "entryPrice": 1.23,
      "exitPrice": 1.31,
      "returnPct": 6.4,
      "holdingDays": 22,
      "exitReason": "st_flip"
    }
  ],
  "summary": {
    "tradeCount": 1,
    "winRate": 1,
    "averageReturnPct": 6.4,
    "totalReturnPct": 6.4
  }
}
```

## 后端实现

在 `backend/backtest.py` 中新增 SuperTrend replay helper。它复用现有 `pandas_ta.supertrend` 计算方式，生成：

- filtered daily candles
- SuperTrend points
- buy/sell markers
- completed trades
- summary

交易规则首期与现有 `run_supertrend_backtest` 保持一致：日线 SuperTrend 从空翻多买入；持仓中触及 SuperTrend 动态线或方向翻空卖出；收益扣除双边 fee bps；价格应用 slippage bps。周线过滤和 ADX 过滤作为参数保留，但首期页面默认使用基础 SuperTrend。

在 `backend/main.py` 新增请求模型和接口。接口读取 `backend/data/{SYMBOL}.parquet`，数据缺失时返回 404；策略未知时返回 400；输出使用 JSON-safe 数据。

## 前端实现

新增 `frontend/src/components/HistoryTradesPage.tsx`。页面包含：

- symbol 输入框
- strategy 下拉，首期只有 SuperTrend
- start/end 日期
- 运行按钮
- lightweight-charts K 线图，叠加 SuperTrend 分段线和 marker
- summary 指标行
- trades 明细表
- loading、error、empty 状态

修改 `App.tsx` 和 `Header.tsx`，增加 `history` 页面入口和路径状态。保持现有 watchlist、ST、RS、周线 BB 页面行为不变。

## 测试

后端采用 TDD：

1. 为 SuperTrend replay 写失败测试，验证 candles、markers、trades、summary。
2. 写日期过滤测试，验证 `start/end` 只影响输出范围和交易入场范围。
3. 写接口测试，验证未知策略返回 400，缺失数据返回 404。

前端验证：

- `pnpm build`
- 必要时补充轻量数据格式测试。

## 风险

- 本地 parquet 缓存缺失时无法展示真实标的，需要前端给清晰错误。
- 现有后端测试需要 `PYTHONPATH=.` 才能正确收集。
- `pnpm test` 当前没有配置脚本，不能作为前端验证命令。
