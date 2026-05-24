# Resonance v2 策略说明

本文描述 `resonance_v2` 策略的完整逻辑，包括入池判断、评分系统、风险管理和策略版本机制。

API 字段契约见 `doc/current-api-contract.md`，v1 基础逻辑见 `doc/current-system-strategy.md`。

## 1. 与 v1 的核心区别

| 维度 | v1 | v2 |
|------|----|----|
| 入池类型 | 单一（金叉窗口内） | 两种：`earlyTrend` / `establishedTrend` |
| 评分系统 | 无 | `entryScore`（0-100）+ `riskScore`（0-100） |
| 风险管理 | 无 | ATR 止损/目标价、风险百分比、盈亏比 |
| 策略版本 | 固定参数 | 通过 `strategy_versions.py` 注册，可配置 |

## 2. 入池逻辑

### earlyTrend（早期趋势）

同时满足：
- 周线过滤通过：`MACD_W > MACD_Signal_W` 且 `price > 周线 MA5`
- 最近一次 EMA20 上穿 EMA50 距今在有效窗口内（`established_trend_lookback` 根 K 线内）

### establishedTrend（成熟趋势）

同时满足：
- 周线过滤通过
- 趋势完整：`EMA20 > EMA50` 且 `price > EMA20` 且 `EMA20 >= 前一日 EMA20`（均线上行）
- 金叉距今在 `established_trend_lookback` 根 K 线内

两种类型都会设置 `resonanceInPool = true`，区别在于 `resonancePoolType` 字段。

## 3. 买点逻辑

与 v1 相同：在池中时，检查最近 3 根日 K 是否出现 EMA5 或 EMA10 回踩确认（低价触及均线，收盘站回，且不跌破 EMA20，均线上行，缩量）。

## 4. 评分系统

### entryScore（入场质量分，0-100）

| 条件 | 加分 |
|------|------|
| 周线过滤通过 | +35 |
| poolType = earlyTrend | +25 |
| poolType = establishedTrend | +20 |
| 趋势完整（EMA20 > EMA50 且价格 > EMA20 且均线上行） | +15 |
| EMA5 回踩确认 | +15 |
| EMA10 回踩确认 | +12 |
| 买点出现 | +10 |

### riskScore（风险评分，0-100）

基于风险百分比计算：`max(0, min(100, round(100 - riskPercent * 12)))`

风险越低，分数越高。

### riskLevel（风险等级）

| riskPercent | riskLevel |
|-------------|-----------|
| < 3% | low |
| 3% - 6% | medium |
| > 6% | high |

## 5. 风险管理字段

基于 ATR(14) 计算，参数由策略版本控制：

- `resonanceEntryPrice`：当前收盘价（建议入场价）
- `resonanceStopPrice`：`entryPrice - ATR × atr_stop_multiplier`
- `resonanceTargetPrice`：`entryPrice + ATR × atr_target_multiplier`（`atr_target_multiplier = 0` 时为 null）
- `resonanceRiskPercent`：`(ATR × atr_stop_multiplier / entryPrice) × 100`
- `resonanceRewardRiskRatio`：`atr_target_multiplier / atr_stop_multiplier`

## 6. 策略版本系统

策略版本在 `backend/strategy_versions.py` 中注册，通过 `StrategyVersion` dataclass 定义参数。

### 主要参数

| 参数 | 说明 |
|------|------|
| `established_trend_lookback` | 金叉有效窗口（根 K 线数），默认 80 |
| `atr_stop_multiplier` | ATR 止损倍数 |
| `atr_target_multiplier` | ATR 目标倍数（0 = 无固定目标，持有至离场信号） |
| `market_filter` | 持仓期市场过滤器（`none` / `bullish_ema`） |
| `entry_market_filter` | 入场时市场过滤器 |
| `entry_market_min_close_vs_ema20_pct` | 入场时市场指数收盘须高于 EMA20 的最小百分比 |
| `market_symbol` | 市场过滤器参考标的（如 `SPY`、`000300.SS`） |
| `asset_class_filter` | 资产类别过滤（如 `etf`） |
| `pool_type_filter` | 只允许特定入池类型（如 `establishedTrend`） |
| `exit_mode` | `fixed_target`（固定目标价离场）/ `warn_exit`（技术离场信号） |
| `relative_strength_bucket_filter` | RS 强度过滤（如 `top20`、`top20,top50`） |
| `signal_type` | `resonance` / `weekly_bb_breakout` |

### 当前注册版本

| 版本 ID | 止损倍数 | 目标倍数 | 市场过滤 | 备注 |
|---------|---------|---------|---------|------|
| `resonance_v2_atr_1_5` | 1.5 | 3.0 | 无 | 默认版本 |
| `resonance_v2_atr_2_0` | 2.0 | 4.0 | 无 | |
| `resonance_v2_atr_2_0_spy_bullish_etf_established` | 2.0 | 4.0 | SPY 牛市 | ETF + 成熟趋势 |
| `resonance_v2_atr_2_0_csi300_bullish_etf_established` | 2.0 | 4.0 | CSI300 牛市 | ETF + 成熟趋势 |
| `resonance_v2_atr_2_0_csi300_strict_bullish_etf_established` | 2.0 | 4.0 | CSI300 严格 | 入场+持仓双过滤 |
| `resonance_v2_atr_2_0_csi300_entry_buffer_1_0_etf_established` | 2.0 | 4.0 | CSI300 + 1% 缓冲 | 回测默认版本 |
| `resonance_v3_trend_runner_csi300_entry_buffer_1_0_etf_established` | 2.0 | 0（无目标） | CSI300 + 1% 缓冲 | 持有至技术离场 |
| `resonance_v3_atr_2_0_8_0_csi300_entry_buffer_1_0_etf_established` | 2.0 | 8.0 | CSI300 + 1% 缓冲 | 宽目标 |
| `resonance_v4_rs_top20_csi300_entry_buffer_1_0_etf_established` | 2.0 | 4.0 | CSI300 + 1% 缓冲 | RS top20 过滤 |
| `resonance_v4_rs_top50_csi300_entry_buffer_1_0_etf_established` | 2.0 | 4.0 | CSI300 + 1% 缓冲 | RS top20+50 过滤 |
| `weekly_bb_breakout_ma30` | — | — | 无 | 周线BB突破策略 |

默认版本：`resonance_v2_atr_1_5`（实时行情页使用）。回测页默认：`resonance_v2_atr_2_0_csi300_entry_buffer_1_0_etf_established`。

## 7. 相关文件

| 文件 | 说明 |
|------|------|
| `backend/analysis_strategy.py` | `_evaluate_resonance_strategy_v2()` 实现 |
| `backend/strategy_versions.py` | 版本注册表 |
| `backend/main.py` | `StockResponse` 模型（resonance 字段） |
| `doc/current-system-strategy.md` | v1 策略和通用趋势层说明 |
