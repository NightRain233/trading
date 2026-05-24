# 当前 API 契约说明

本文只描述当前后端 API 的请求、返回和字段语义。策略规则见 `doc/current-system-strategy.md`。

## 1. API 总览

当前后端核心接口：

- `GET /`
- `GET /api/quote/{symbol}`
- `POST /api/quotes/batch`
- `POST /api/quotes/batch/charts`
- `GET /api/watchlist`
- `POST /api/watchlist`
- `DELETE /api/watchlist/{symbol}`
- `PUT /api/watchlist/{symbol}/alias`
- `POST /api/groups`
- `PUT /api/watchlist`
- `GET /api/weekly-breakout/scan`
- `GET /api/rs-rotation/holdings`
- `POST /api/backtest`
- `GET /api/strategy-versions`

## 2. 健康检查

### `GET /`

返回：

```json
{
  "status": "ok",
  "message": "Trading Backend is running"
}
```

## 3. 股票分析接口

### `GET /api/quote/{symbol}`

用途：

- 获取单个股票的完整分析结果
- 包含详细日线 `candles`
- 包含详细周线 `weekly_candles`

异常：

- 数据不足或股票不可用时返回 `404`

返回结构示例：

```json
{
  "symbol": "AAPL",
  "name": "AAPL",
  "price": 210.15,
  "changePercent": 1.23,
  "ema20": 205.11,
  "ema50": 198.37,
  "adx": 27.8,
  "rsi": 68.2,
  "rsiPeriod": 14,
  "rsiStatus": "中性",
  "rsiOverbought": 75,
  "rsiOversold": 45,
  "trend": "强势多头",
  "signal": "强烈信号",
  "candles": [],
  "weekly_candles": [],
  "weeklyMA5": 202.4,
  "weeklyMacdStatus": "周线牛市",
  "weeklyPriceVsMA5": "线上",
  "weeklyMacdHist": 1.52,
  "resonanceInPool": true,
  "resonanceBuySignal": false,
  "resonancePoolReason": "周线过滤通过; 日线EMA20/50金叉距今5根K线",
  "resonanceBuyReason": "最近未出现有效回踩确认",
  "resonanceExitSignal": false,
  "resonanceExitLevel": "none",
  "resonanceExitReason": ""
}
```

### `POST /api/quotes/batch`

用途：

- 批量获取列表页摘要数据
- 不返回大体积图表 K 线
- 强依赖缓存，允许返回旧数据并后台刷新

请求体：

```json
{
  "symbols": ["AAPL", "MSFT", "TSLA"],
  "timeframe": "1D"
}
```

说明：

- 当前实现会接收 `timeframe`，但该接口实际只返回摘要，与图表周期无关
- `symbols` 会被去空、去重、转大写、排序

返回结构：

```json
{
  "AAPL": {
    "symbol": "AAPL",
    "name": "AAPL",
    "price": 210.15,
    "changePercent": 1.23,
    "ema20": 205.11,
    "ema50": 198.37,
    "adx": 27.8,
    "rsi": 68.2,
    "rsiPeriod": 14,
    "rsiStatus": "中性",
    "rsiOverbought": 75,
    "rsiOversold": 45,
    "trend": "强势多头",
    "signal": "强烈信号",
    "candles": [],
    "weekly_candles": [],
    "weeklyMA5": 202.4,
    "weeklyMacdStatus": "周线牛市",
    "weeklyPriceVsMA5": "线上",
    "weeklyMacdHist": 1.52,
    "resonanceInPool": true,
    "resonanceBuySignal": false,
    "resonancePoolReason": "周线过滤通过; 日线EMA20/50金叉距今5根K线",
    "resonanceBuyReason": "最近未出现有效回踩确认",
    "resonanceExitSignal": false,
    "resonanceExitLevel": "none",
    "resonanceExitReason": ""
  }
}
```

关键点：

- 返回值是 `Record<symbol, StockData>`，不是数组
- `candles` 和 `weekly_candles` 在这个接口里固定为空数组
- 某个 symbol 没结果时，可能不会出现在返回对象中

### `POST /api/quotes/batch/charts`

用途：

- 批量返回列表页迷你图数据

请求体：

```json
{
  "symbols": ["AAPL", "MSFT"],
  "timeframe": "1D"
}
```

取值：

- `timeframe = "1D"` -> 日线迷你图
- `timeframe = "1W"` -> 周线迷你图

返回结构：

```json
{
  "AAPL": [
    {
      "time": "2026-03-06",
      "open": 207.1,
      "high": 211.0,
      "low": 206.5,
      "close": 210.2,
      "ema5": 208.4,
      "ema10": 206.9,
      "ema20": 205.1,
      "ema50": 198.3,
      "macd_dif": 2.1,
      "macd_dea": 1.8,
      "macd_hist": 0.3
    }
  ]
}
```

## 4. Watchlist 接口

### `GET /api/watchlist`

返回观察列表分组结构，不包含分析指标。

```json
[
  {
    "id": "uuid",
    "name": "默认分组",
    "collapsed": false,
    "symbols": [
      {
        "symbol": "AAPL",
        "alias": "苹果"
      }
    ]
  }
]
```

### `POST /api/watchlist`

请求体：

```json
{
  "symbol": "AAPL",
  "groupId": "optional-group-id",
  "alias": "苹果"
}
```

返回：

- 成功新增：`{"message":"Symbol added"}`
- 已存在：`{"message":"Symbol already in watchlist"}`

### `DELETE /api/watchlist/{symbol}`

返回：

- 成功：`{"message":"Symbol removed"}`
- 不存在：`404`

### `PUT /api/watchlist/{symbol}/alias`

请求体：

```json
{
  "alias": "苹果"
}
```

返回：

```json
{
  "message": "Alias updated"
}
```

### `POST /api/groups`

请求体：

```json
{
  "name": "AI 观察池"
}
```

返回新分组对象：

```json
{
  "id": "uuid",
  "name": "AI 观察池",
  "symbols": [],
  "collapsed": false
}
```

### `PUT /api/watchlist`

用途：

- 全量覆盖 watchlist
- 支持分组排序、股票跨组移动、折叠状态保存

请求体：

```json
{
  "groups": [
    {
      "id": "uuid",
      "name": "默认分组",
      "collapsed": false,
      "symbols": [
        {
          "symbol": "AAPL",
          "alias": "苹果"
        }
      ]
    }
  ]
}
```

返回：

```json
{
  "message": "Watchlist updated"
}
```

## 5. 字段字典

以下字段主要出现在 `/api/quote/{symbol}` 和 `/api/quotes/batch`。

### 5.1 基础字段

- `symbol`: 股票代码
- `name`: 当前实现里与 `symbol` 相同，尚未接入真实公司名
- `price`: 最新收盘价
- `changePercent`: 相对前一交易日收盘价的涨跌幅百分比
- `alias`: 自选别名，主要由 watchlist 数据补充

### 5.2 趋势字段

- `ema20`, `ema50`: 当前日线 EMA 值
- `adx`: 当前 ADX 值
- `trend`: 离散趋势标签
- `signal`: 基于 ADX + trend 的粗粒度环境标签

### 5.3 RSI 字段

- `rsi`: 当前生效周期下的 RSI 数值
- `rsiPeriod`: 当前采用的 RSI 周期，取值为 `7/14/21`
- `rsiStatus`: `超买 | 超卖 | 中性`
- `rsiOverbought`: 当前超买阈值
- `rsiOversold`: 当前超卖阈值

### 5.4 周线字段

- `weeklyMA5`: 当前周线 5 周均线
- `weeklyMacdStatus`: `周线牛市 | 周线反弹 | 周线回调 | 周线熊市`
- `weeklyPriceVsMA5`: `线上 | 线下`
- `weeklyMacdHist`: 周线 MACD 柱值

### 5.5 共振字段

v1 基础字段：

- `resonanceInPool`: 是否进入共振观察池
- `resonanceBuySignal`: 是否出现共振买点
- `resonancePoolReason`: 入池或未入池原因
- `resonanceBuyReason`: 买点判断原因
- `resonanceExitSignal`: 是否出现离场提示
- `resonanceExitLevel`: `none | warn | hard`
- `resonanceExitReason`: 离场原因

v2 新增字段（实时行情页使用）：

- `resonanceStrategyVersion`: 当前策略版本 ID（如 `resonance_v2_atr_1_5`）
- `resonancePoolType`: 入池类型，`earlyTrend | establishedTrend | none`
- `resonanceEntryScore`: 入场质量分，0-100
- `resonanceRiskScore`: 风险评分，0-100（越高越低风险）
- `resonanceRiskLevel`: 风险等级，`low | medium | high`
- `resonanceEntryPrice`: 建议入场价（当前收盘）
- `resonanceStopPrice`: ATR 止损价
- `resonanceRiskPercent`: 止损距离占入场价的百分比
- `resonanceTargetPrice`: ATR 目标价（无固定目标时为 `null`）
- `resonanceRewardRiskRatio`: 盈亏比（无目标时为 `null`）

v2 策略逻辑详见 `docs/resonance-v2-strategy.md`。

### 5.6 图表字段

- `candles`: 详情页日线 K 线
- `weekly_candles`: 详情页周线 K 线

注意：

- 在 `/api/quotes/batch` 中，这两个字段为空数组
- 在 `/api/quote/{symbol}` 中，这两个字段是完整图表数据

## 6. K 线对象结构

详情 K 线字段可能包含：

- `time`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `ema20`
- `ema50`
- `rsi`
- `boll_upper`
- `boll_mid`
- `boll_lower`
- `k`
- `d`
- `j`
- `macd_dif`
- `macd_dea`
- `macd_hist`
- `atr`

迷你图字段更精简，通常包含：

- `time`
- `open`
- `high`
- `low`
- `close`
- `ema5`
- `ema10`
- `ema20`
- `ema50`
- `macd_dif`
- `macd_dea`
- `macd_hist`

系统在输出前会统一做清洗：

- `NaN / Inf` 转成 `null`
- 时间去重并按升序排序
- 删除非法时间和缺失 OHLC 的行

## 7. 缓存与响应头

`/api/quotes/batch` 使用两级缓存：

1. 一级缓存：内存
2. 二级缓存：磁盘 Parquet

关键时间窗口：

- 新鲜缓存：`1小时`
- 允许旧数据：`24小时`
- 数据保留：`2年`

接口策略：

1. 优先返回缓存
2. 冷启动时允许最多同步等待 `5秒`
3. 旧数据或缺失数据会触发后台刷新
4. 当前请求可能先返回旧结果

重要响应头：

- `ETag`
- `Last-Modified`
- `Cache-Control: private, no-cache`
- `X-Data-Updated-At`
- `X-Data-Stale`
- `X-Refresh-Triggered`

含义：

- `X-Data-Stale = 1` 表示这次返回里包含过期或缺失后兜底的数据
- `X-Refresh-Triggered = 1` 表示这次请求触发了后台刷新

条件请求：

- 客户端可传 `If-None-Match`
- 若 ETag 命中，服务端返回 `304 Not Modified`

## 8. 前端消费方式

当前前端按三步消费：

1. `GET /api/watchlist` 获取分组结构
2. `POST /api/quotes/batch` 填充摘要数据
3. `POST /api/quotes/batch/charts` 按需加载迷你图

前端还会对 `/api/quotes/batch` 做轮询和条件请求：

- 页面可见时约 `30s`
- 页面不可见时约 `300s`
- 通过 ETag 减少重复下发
