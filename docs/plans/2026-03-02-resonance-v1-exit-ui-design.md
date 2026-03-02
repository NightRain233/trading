# Resonance V1 Exit & UI Design

## Goal
在不引入持仓状态的前提下，为 `resonance_v1` 增加技术面离场信号，并在列表页展示和筛选共振买点/离场信号。

## Scope
- 后端新增无持仓离场评估（仅基于当前日线/周线指标）。
- API 返回新增离场字段。
- 前端列表新增共振买点/离场徽章。
- 前端筛选新增“共振买点 / 共振离场”。

## Non-Goals
- 不做成本价、仓位、浮盈/浮亏相关逻辑。
- 不自动下单。
- 不改现有 `trend/signal` 主逻辑。

## Exit Rules (No Position Mode)
1. `hard exit`:
   - 收盘跌破 `EMA50`，或
   - 周线 `MACD_W <= MACD_Signal_W`，或
   - 价格跌破周线 `MA5_W`。
2. `warn exit` (仅当未触发 hard):
   - 收盘跌破 `EMA20`，或
   - 日线 `MACD_DIF <= MACD_DEA`。
3. 其他为无离场信号。

## API Fields
- `resonanceExitSignal: bool`
- `resonanceExitLevel: "none" | "warn" | "hard"`
- `resonanceExitReason: str`

## UI
- 桌面端信号列保留原 `signal`，并追加共振徽章：
  - `共振买点`（青色）
  - `离场预警`（琥珀）
  - `共振离场`（红色）
- 移动端在现有信息块内追加同类小徽章。
- 筛选栏新增“共振策略”分组：
  - `共振买点`
  - `共振离场`（匹配 `warn/hard`）

## Testing
- 后端单测覆盖 `hard/warn/none` 与原因字段。
- 前端当前无测试框架，使用 `tsc --noEmit` 做契约与类型验证。
