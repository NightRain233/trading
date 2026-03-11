# 当前系统策略说明

本文只描述当前系统“实际实现的策略逻辑”，不展开 API 细节。接口和字段契约见 `doc/current-api-contract.md`。

## 1. 系统定位

当前系统是一个股票技术分析与观察列表系统，不是自动交易系统，也不是完整的持仓管理系统。

它主要输出三类结果：

1. 通用趋势状态
2. 周线背景状态
3. `resonance_v1` 共振策略状态

因此，LLM 分析本系统时，应把它理解为“规则型技术分析引擎 + 观察列表信号汇总层”。

## 2. 策略结构

当前代码里有两层核心逻辑：

1. 通用趋势分析层
2. `resonance_v1` 共振策略层

前者描述市场状态，后者更接近“筛池 + 买点 + 风险提示”。

## 3. 通用趋势分析层

### 3.1 趋势方向

基于 `EMA20`、`EMA50` 与当前价格关系判断：

- `EMA20 > EMA50 * 1.001`
  - `price > EMA20` -> `强势多头`
  - `EMA50 < price <= EMA20` -> `回调多头`
  - `price <= EMA50` -> `潜在转空`
- `EMA20 < EMA50 * 0.999`
  - `price < EMA20` -> `强势空头`
  - `EMA20 <= price < EMA50` -> `反弹空头`
  - `price >= EMA50` -> `潜在转多`
- 其余 -> `震荡`

这里的 `trend` 是状态标签，不是直接买卖指令。

### 3.2 趋势强度

基于 `ADX` 输出粗粒度信号：

- `adx <= 25` -> `signal = 观望`
- `adx > 25` 且 `trend` 为 `强势多头/强势空头` -> `强烈信号`
- `adx > 25` 且 `trend` 为 `回调多头/反弹空头` -> `谨慎信号`
- 其他 -> `观望`

因此 `signal` 的含义更接近“当前趋势环境是否值得关注”。

### 3.3 动态 RSI

系统不是固定使用 RSI(14)，而是根据 ADX 切换周期：

- `ADX > 30` -> `RSI(21)`
- `ADX < 20` -> `RSI(7)`
- 其他 -> `RSI(14)`

超买超卖阈值也是动态的：

- 强上升趋势 -> `超买 75 / 超卖 45`
- 强下降趋势 -> `超买 60 / 超卖 25`
- 其他 -> `超买 70 / 超卖 30`

这意味着：

- `rsiPeriod` 表示当前生效周期
- `rsiStatus` 才是更值得 LLM 直接消费的结论
- 不能脱离 `rsiOverbought/rsiOversold` 机械理解 `rsi`

## 4. 周线状态层

系统会把日线数据重采样成周线，并计算周线 MA5、MACD 等指标。

关键语义字段：

- `weeklyMA5`
- `weeklyMacdStatus`
- `weeklyPriceVsMA5`
- `weeklyMacdHist`

判定规则：

- `MACD_W > MACD_Signal_W`
  - 且 `MACD_W > 0` -> `周线牛市`
  - 否则 -> `周线反弹`
- `MACD_W <= MACD_Signal_W`
  - 且 `MACD_W > 0` -> `周线回调`
  - 否则 -> `周线熊市`

价格相对周 MA5：

- `price > weeklyMA5` -> `线上`
- 否则 -> `线下`

这层主要承担中周期背景过滤作用。

## 5. `resonance_v1` 共振策略

这是当前系统中最接近“可操作策略”的部分，核心输出三类状态：

1. 是否进入观察池
2. 是否出现买点
3. 是否出现离场预警/离场信号

相关字段：

- `resonanceInPool`
- `resonanceBuySignal`
- `resonancePoolReason`
- `resonanceBuyReason`
- `resonanceExitSignal`
- `resonanceExitLevel`
- `resonanceExitReason`

### 5.1 入池条件

需要同时满足：

1. 周线过滤通过
2. 日线 EMA20/50 金叉仍在有效窗口内

周线过滤通过的定义：

- `MACD_W > MACD_Signal_W`
- 当前价格 `> 周线 MA5`

日线金叉有效的定义：

- 当前仍满足 `EMA20 > EMA50`
- 最近一次 `EMA20` 上穿 `EMA50` 距今不超过 `15` 根日 K

满足则：

- `resonanceInPool = true`

否则：

- `resonanceInPool = false`
- `resonancePoolReason` 说明失败原因

### 5.2 买点条件

前提：必须先在池中。

买点逻辑是“短均线回踩确认”，检查最近 `3` 根日 K 内是否出现：

- 回踩 `EMA5` 后收回
- 或回踩 `EMA10` 后收回

并且同时满足：

- 最低价触及对应均线，收盘重新站回均线之上
- 最低价不跌破 `EMA20`
- 对应均线本身在上行
- 当日成交量相对近 `20` 日均量缩量，阈值 `<= 0.8 * 20日均量`

满足则：

- `resonanceBuySignal = true`
- `resonanceBuyReason` 为 `EMA5回踩确认` 或 `EMA10回踩确认`

否则：

- `resonanceBuySignal = false`

### 5.3 离场信号

当前实现是“无持仓状态下的技术离场提示”，不是完整卖出系统。

离场分级：

- `warn`
- `hard`
- `none`

硬离场 `hard` 条件，满足任一即可：

- 收盘跌破 `EMA50`
- 周线 `MACD_W <= MACD_Signal_W`
- 当前价格跌破周线 `MA5`

预警 `warn` 条件，满足任一即可：

- 收盘跌破 `EMA20`
- 日线 `MACD_DIF <= MACD_DEA`

否则：

- `resonanceExitLevel = none`

因此：

- `resonanceBuySignal` 是当前最接近“买点出现”的字段
- `resonanceExitLevel = warn/hard` 是当前最接近“风险升级”的字段
- 但系统仍未接入仓位、成本价、分批止盈止损

## 6. 系统实际计算的指标

日线侧当前实际计算：

- `EMA5`
- `EMA10`
- `EMA20`
- `EMA50`
- `ADX(14)`
- `RSI(7/14/21)`
- `BOLL`
- `KDJ`
- `MACD(12,26,9)`
- `ATR(14)`

周线侧会基于重采样结果计算：

- `MA5_W`
- `EMA5/10/20/50`
- `MACD_W`
- `MACD_Signal_W`
- `MACD_Hist_W`
- `BOLL`
- `KDJ`
- `RSI_14`
- `ATR`

## 7. 给 LLM 的推荐理解方式

建议按下面的优先级理解：

1. 这是分析系统，不是交易执行系统。
2. `trend/signal` 是背景状态，不等于买卖点。
3. `resonance_*` 是更接近策略动作的字段。
4. 当前可操作策略明显偏多头共振筛选，不是双向交易系统。
5. `resonanceExitLevel` 更适合作为风险标签，而不是绝对卖出指令。

## 8. 一句话总结

当前系统的核心策略可以概括为：

> 用日线 EMA 结构识别趋势，用 ADX 过滤趋势强弱，用动态 RSI 做状态解释，用周线 MACD 和周 MA5 做中周期过滤，再通过 `resonance_v1` 输出“入池、回踩买点、分级离场提示”。
