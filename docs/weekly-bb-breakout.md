# 周线 BB 突破策略

## 策略口径

- **布林带**：周线 BB(20, 2)，只使用上轨和下轨参与信号判断。
- **BB 中轨（MA20）**：仅作为前端图表可选展示，不参与任何信号逻辑。
- **趋势过滤**：30 周均线 MA30，收盘须在 MA30 之上才允许入场。
- **目标**：捕捉周线长期挤压后放量突破上轨的趋势段。

## 入场条件（同时满足）

1. 当前周线收盘 > BB 上轨
2. 当前周线收盘 > MA30
3. 近 8 周内出现过带宽收窄（带宽 < 近 8 周均值的 80%）

## 离场条件（任一触发）

- 收盘跌破 MA30（趋势破坏）
- 收盘回到 BB 上轨以内，且上轨斜率走平或向下（动能衰竭）

## 扫描状态说明

| 状态 | 含义 |
|------|------|
| **突破** | 满足全部入场条件，策略入场信号 |
| **挤压** | 当前带宽 < 近 20 周均值的 85%，布林带收窄蓄力，等待方向选择 |
| **离场** | 触发离场条件，持仓应考虑退出 |
| **观望** | 不满足以上任何条件 |

典型节奏：**挤压 → 突破（入场）→ 离场（退出）**

## 前端入口

Header 导航栏点击「周线BB」标签（靛蓝色），进入九宫格扫描页。

### 工具栏开关

| 开关 | 说明 |
|------|------|
| 全部 / 突破 / 挤压 / 离场 | 按信号状态筛选 |
| BB中轨 | 主图叠加 BB 中轨（紫色虚线），默认隐藏 |
| MA5 | 主图叠加周 MA5（绿色细线），默认隐藏 |
| MACD | 主图下方展示周 MACD 副图（柱状 + DIF/DEA 线），默认隐藏 |

### 图表图例

| 颜色 | 含义 |
|------|------|
| 紫色实线 | BB 上轨 / 下轨 |
| 紫色虚线 | BB 中轨（可选） |
| 琥珀色 | MA30 |
| 绿色细线 | MA5（可选） |
| 蓝色 / 橙色 | MACD DIF / DEA（副图可选） |
| 绿/红柱 | MACD Histogram（副图可选） |

九宫格按信号状态排序（突破 → 挤压 → 离场 → 观望），每格显示最近 52 周 K 线。

## 后端接口

`GET /api/weekly-breakout/scan`

扫描 watchlist 所有标的，返回数组，每项包含：

```json
{
  "symbol": "510300.SS",
  "alias": "沪深300",
  "state": "squeeze",
  "stopPrice": 3.85,
  "candles": [
    {
      "time": "2025-01-05",
      "open": 3.90, "high": 3.95, "low": 3.88, "close": 3.92,
      "boll_upper": 4.10, "boll_mid": 3.95, "boll_lower": 3.80,
      "ma30": 3.85, "ma5": 3.91,
      "macd_dif": 0.02, "macd_dea": 0.01, "macd_hist": 0.01
    }
  ]
}
```

## 回测

策略版本 ID：`weekly_bb_breakout_ma30`，可在回测页面选择。

- 止损：跌破 MA30
- 止盈：无固定目标，持有至离场信号触发（`exit_mode: warn_exit`）

## 相关文件

| 文件 | 说明 |
|------|------|
| `backend/backtest.py` | `evaluate_weekly_bb_breakout` / `evaluate_weekly_bb_exit` 信号函数 |
| `backend/strategy_versions.py` | `weekly_bb_breakout_ma30` 策略版本定义 |
| `backend/main.py` | `GET /api/weekly-breakout/scan` 接口 |
| `frontend/src/components/WeeklyBreakoutPage.tsx` | 九宫格扫描页 |
| `frontend/src/components/Header.tsx` | 「周线BB」标签入口 |
