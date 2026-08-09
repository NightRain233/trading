---
name: scan
description: Use when the user asks for a market-wide SuperTrend scan, watchlist ranking, actionable trading candidates, trend continuation, or portfolio risk alerts.
---

# /scan - 严格右侧趋势扫描

扫描全部自选标的，先判断市场是否允许交易，再寻找两类右侧机会：

1. 日线 SuperTrend 收盘翻多后的突破入场
2. 已确认多头趋势中的回踩入场

反转前兆、MACD 背离、RSI、KDJ、BOLL 和成交量只能提高观察优先级或增强确认，不能单独产生买入许可。

## 一、不可违背的原则

- 周线定方向，日线定时机：周线未确认多头，不开新多仓。
- 只使用完整收盘数据。盘中数据、未完成成交量和进行中的周/月线只能作为临时信息。
- `weeklyState` 使用最近完整周，`weeklyProvisionalState` 只展示本周临时方向，不能授予买入权限。
- `bull_flip` 是突破信号，不等于自动买入。
- 扫描候选不等于组合可以执行。实际交易还要检查持仓、风险预算、账本和 `executableWeights`。
- 数据不完整时暂停结论，不用指标猜测缺失信息。
- 所有标的最终必须明确标为：`可买`、`等确认`、`只观察`、`持有/风控` 或 `禁止交易`。

## 二、分析前准备

### 1. 读取复盘

先读取 `reviews/README.md`，然后检查：

- 最近 3 个自然日内存在的每日复盘 `reviews/YYYY-MM-DD.md`
- `reviews/持仓总览.md`
- 当前持仓和最终重点标的对应的品种页

如果最近 3 个自然日没有复盘，明确写：

> 最近三天无有效复盘，本次只依据行情数据，不继承旧复盘中的市场判断。

品种页与每日复盘冲突时，以品种页中当前有效规则为准。品种页过期时，不把旧价格、旧止损或旧仓位当成当前事实。

### 2. 获取扫描数据

本地服务可用时优先调用本地：

```bash
uv run python scripts/trading_analysis_helper.py \
  --api-base http://127.0.0.1:8000/api \
  --query scan --grouped --timeout 180
```

需要远程数据时改用：

```bash
uv run python scripts/trading_analysis_helper.py \
  --api-base http://8.153.71.148/api \
  --query scan --grouped --timeout 180
```

`GET /api/supertrend/scan?force=false` 返回统一的扫描契约。先检查：

- `schemaVersion` 和 `policyVersion`
- `coverage.requested == coverage.returned`
- `coverage.missing` 为空
- 每个 `items[]` 都有 `decision`、`primaryGroup` 和 `marketMode`
- 所有 `groups.*.symbols` 去重后与 `items[].symbol` 完全一致

helper 的 `allSymbols` 是不含 candles 的紧凑全量列表，`groups` 直接使用 API 的正式分组。需要最终候选的 candles 时，使用 `include_candles=true` 调用 API 后按 symbol 提取。输出过长时先保存 JSON，再用结构化工具提取必要字段；不能根据被截断的输出判断“没有信号”。

## 三、数据有效性检查

在解释任何信号前，逐个检查：

- `latestDataDate`
- `dataStale`
- `dataIntegrity`
- `volumeContext.sessionComplete`
- `volumeContext.asOf`

规则：

- HTTP 200 不代表每个标的都有效。
- 股票、加密资产和其他市场按各自交易日判断，不要求日期完全相同。
- `dataStale=true` 或存在近期缺口：该标的暂停买入和风控结论，先刷新。
- `cacheStale=true` 只是缓存刷新提示；当 `dataStale=false` 且日期正确时，不能据此宣称行情过期。
- 成交量未完成时写“量能未完成”，不能使用 `ratio20` 排序或确认。
- 完整收盘后只使用 `ratio20Completed`。

## 四、先判断各市场模式

不同市场独立判断，不能用 A 股状态替代美股、加密或黄金状态。

代表品种：

- A 股：`000001.SS`、`000300.SS`
- 美股：`SPY`、`QQQ`
- 加密：`BTC-USD`、`ETH-USD`
- 黄金：`GC=F`、`518880.SS`
- 债券风险观察：`511010.SS`、`TLT`

使用两个代表品种的 `monthlyBoll.midDirection`：

- 两者都是 `rising` 或 `flat`：`找买点模式`
- 一者 `falling`，另一者 `rising` 或 `flat`：`谨慎模式`
- 两者都是 `falling`：`保命模式`
- 任一代表品种缺失或月线历史不足：`模式数据不足`

交易权限：

- 找买点模式：允许评估突破和回踩，ADX 最低门槛为 25。
- 谨慎模式：只评估高质量机会，ADX 最低门槛提高到 30。
- 保命模式：禁止新仓，只处理持仓风险。
- 模式数据不足：不给自动买入许可，标记为 `等确认`，并说明缺失数据。
- 债券代表品种不完整时，不得输出“股债双杀”或“流动性危机已确认”。

先用一个紧凑表展示 5 个 A 股市场指数：上证、沪深300、中证500、科创50、中证2000。至少包含方向、ADX、RSI21、MACD 柱方向、确认背离、KDJ、周/月 BOLL 中轨方向与距离、完整 20 日量比，并给出一句市场定性。

## 五、统一交易权限

按以下顺序判断，不得跳步：

```text
数据有效性
-> 所属市场模式
-> 周线方向
-> 日线信号
-> ADX 门槛
-> 距离与追高检查
-> BOLL / 量能 / MACD 辅助确认
-> 持仓与风险预算检查
-> 最终权限
```

权限定义：

- `可买`：所有硬条件通过，下一交易日可以按计划执行。
- `等确认`：结构允许，但缺少日线触发、止跌确认或市场模式数据。
- `只观察`：反转前兆、背离、周线未确认、ADX 不足或距离过远。
- `持有/风控`：已有持仓的继续持有、减仓、退出或止损检查。
- `禁止交易`：市场处于保命模式，或者数据异常不能形成可靠结论。

## 六、形态一：突破入场

第一版中，“突破”只指：

> 完整日线收盘后，SuperTrend 从空头翻为多头，即 `state=bull_flip`。

`keyLevelPrice` 当前只是 SuperTrend 支撑/阻力值，不是前高、平台上沿或结构突破价。不要把它解释成价格形态关键位。

### 突破可买条件

以下条件必须全部满足：

1. 数据有效且日线已经完整收盘。
2. `state=bull_flip`。
3. `weeklyState` 为 `bull` 或 `bull_flip`。
4. 所属市场为找买点模式或谨慎模式。
5. ADX 通过对应市场门槛。
6. `distanceToSupertrendAtr <= 2`。

结论映射：

- 全部通过：`可买·突破入场`
- 周线仍空：`只观察·黄灯追踪，周线未确认，不建仓`
- ADX 不足：`只观察·弱趋势翻多`
- 距 ST 超过 2 ATR：`等确认·突破已发生，等待回踩，禁止追高`
- 保命模式：`禁止交易·市场不允许新仓`
- 数据异常：`禁止交易·暂停判断并刷新数据`

执行口径：

- 信号日收盘确认，下一交易日执行。
- 最高接受价原则上不得使入场距离超过 2 ATR；信号日可用 `stVal + 2 * ATR` 作为参考上限。
- 下一交易日明显高开并超过最高接受条件时，取消追买，转入回踩观察。
- MACD、量能和 BOLL 可以提高或降低突破优先级，但不能补齐周线、ADX或距离硬条件。

## 七、形态二：回踩入场

回踩用于已经确认的多头趋势，不是下跌中的抄底。

### 回踩观察条件

1. 数据有效。
2. `weeklyState` 为 `bull` 或 `bull_flip`。
3. 日线维持 `bull`，且不是当天刚翻多。
4. `trendAgeBars > 3`。
5. `0 <= distanceToSupertrendAtr <= 1.5`。
6. 日线收盘仍在 ST 上方。

满足以上条件时标记：

```text
等确认·回踩接近支撑
```

### 回踩可买确认

进入回踩观察区后，等待后续一个完整日线收盘同时满足：

- 仍然收在 ST 上方
- 收盘价高于前一个完整交易日收盘价
- ADX 通过所属市场门槛
- 所属市场不是保命模式

满足后标记：

```text
可买·回踩入场
```

失效条件：

- 日线收盘跌破 ST 或重新翻空：`回踩失败`，取消买入候选。
- ADX 跌破门槛：降为 `只观察`。
- 距 ST 重新扩大到 2 ATR 以上但尚未确认：停止追价，等待下一次回踩。

日线 ST 是主要支撑锚点。EMA20、BOLL 中轨等只用于说明是否共振，不能在 ST 失效后另选一条更低的线继续解释为“回踩不破”。

## 八、V 型反转前兆

反转前兆用于提前发现，不产生买入许可。

可进入观察组的条件：

- 周线多头结构未破坏
- 日线价格位于 BOLL 下轨或距离下轨不超过 0.5 ATR
- `volumeContext.sessionComplete=true`
- `ratio20Completed <= 0.8`
- 可附加确认底背离作为加分项

统一标记：

```text
只观察·V 型反转前兆，等待日线右侧确认
```

即使出现缩量、下轨、超卖或确认背离，也必须等待日线 ST 翻多后，重新按照“突破入场”规则检查。反转前兆不得建立试探仓。

## 九、黄灯追踪

API 从完整 `items` 派生并去重，条件为：

- `state` 为 `bull` 或 `bull_flip`
- `weeklyState` 为 `bear` 或 `bear_flip`
- `adx >= 30`

按 `abs(distanceToSupertrendAtr)` 升序、ADX 降序排列，必须展示全部。

标题固定为：

> 黄灯追踪 - 周线未确认，跟踪不建仓

状态说明：

- 距 ST `<=1.5 ATR`：靠近日线支撑，等周线确认
- 距 ST `>1.5 ATR`：等待回踩，避免追高

黄灯标的不得进入 `可买`。周线翻多后，再由突破或回踩规则重新判断。

## 十、指标的正确角色

- ADX：交易许可门槛，不判断方向。找买点模式要求 `>=25`，谨慎模式要求 `>=30`。
- MACD 柱方向：比较 `macdHist` 与 `macdHistPrev`；柱改善不是金叉，也不是买入许可。
- MACD 背离：只有 `confirmed` 可作为辅助证据；`candidate` 只预警，不改变分组、排序硬条件或交易权限。
- RSI21：`>75` 提示拥挤，`<45` 只表示多头趋势中的回踩观察区，不是买点。
- KDJ：`K>80` 为高位，`K<20` 为低位；超卖不能对抗空头趋势。
- 周/月 BOLL：说明结构顺风、阻力或历史不足，不独立授权交易。
- 成交量：只使用完整交易日的 `ratio20Completed`；放量突破是加分，缩量回踩是加分，但两者都不能替代正式信号。

当 BOLL `sampleSize < 20` 或数值为空时写“历史不足”。正好 20 个样本但 `slopeSampleSufficient=false` 时写“方向历史不足”。进行中的周线和月线 BOLL 必须标记为临时结构。

## 十一、持仓与执行边界

扫描完成后，单独检查 portfolio strategy 的：

- 当前状态
- `executableWeights`
- pending rebalance
- ledger
- diagnostics

调用：

```bash
uv run python scripts/trading_analysis_helper.py \
  --api-base http://127.0.0.1:8000/api \
  --query portfolio --timeout 180
```

使用远程 scan 时，portfolio 查询必须使用同一个 `--api-base`，不能混用本地与远程快照。

规则：

- scan 的 `可买` 只表示技术条件允许，不代表组合必须交易。
- `BLOCKED`、`executableWeights=[]` 或执行会话不完整时，不得把候选写成实际调仓动作。
- 已持仓标的优先检查风控。日线 ST 翻空时按既有品种页和组合规则处理，不用 RSI、KDJ或背离拖延正式退出。
- 具体数量和总仓位由风险预算决定，不由 scan skill 凭空生成。

突破和回踩可以顺序配合：

```text
突破确认 -> 可建立第一笔
回踩不破 -> 可增加第二笔
再次走强 -> 在总风险预算内补足目标仓位
```

没有回踩就保留已有突破仓，不追高；错过突破但后来出现有效回踩，也可以按回踩规则首次建仓。

## 十二、输出顺序

严格按以下顺序输出：

1. 数据日期与完整性
2. 各市场模式
3. A 股 5 个指数环境表和一句总判断
4. 持仓/风控，展示全部
5. `可买·突破入场`，展示全部
6. `可买·回踩入场`，展示全部
7. `等确认`，按接近触发程度排序
8. 黄灯追踪，展示全部
9. V 型反转前兆，只观察
10. 趋势延续中值得关注的标的
11. 趋势平稳数量，不逐个展开
12. 最值得关注的 3-5 项
13. “今天最关键的结论是……”

单个标的使用紧凑格式：

```text
SYMBOL 名称  权限/形态  日线方向(age)  周线方向(age)
ADXxx  RSIxx  MACD↑/→/↓  Kxx  距ST x.xATR
周BOLL 下/中↑/上  月BOLL 下/中→/上  完整量比x.x
原因：通过了什么，还缺什么；下一步触发与失效条件
```

对于 `可买` 和 `等确认` 标的，必须写清楚：

- 入场触发
- 最高接受条件
- 失效条件或止损依据
- 当前为什么不是更高或更低一级权限

不要逐个叙述普通持有标的，也不要用大段指标描述掩盖最终行动结论。
