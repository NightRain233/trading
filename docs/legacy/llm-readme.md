# LLM 阅读入口

如果你是 LLM agent，先不要一次性读完整仓库，优先按任务类型选择文档：

## 1. 做策略分析

先看 [current-system-strategy.md](./current-system-strategy.md)。

适用场景：

- 解释系统当前策略
- 分析 `trend` / `signal` / `resonance_*` 的含义
- 评估策略是否偏多、是否完整、有哪些局限
- 讨论是否应该新增或修改策略规则

## 2. 做接口联调或代码接入

先看 [current-api-contract.md](./current-api-contract.md)。

适用场景：

- 调用后端接口
- 理解返回字段
- 生成前端类型或客户端代码
- 分析缓存头、ETag、304、watchlist 结构

## 3. 推荐理解顺序

如果任务同时涉及策略和接口，按这个顺序：

1. 先读 [current-system-strategy.md](./current-system-strategy.md)
2. 再读 [current-api-contract.md](./current-api-contract.md)

原因：

- 策略文档回答“系统为什么这样判断”
- API 文档回答“这些判断通过什么字段返回”

## 4. 一句话定位

这个项目当前应被理解为：

> 一个面向观察列表的股票技术分析系统，使用日线趋势、周线过滤和 `resonance_v1` 共振状态输出结构化分析结果，并通过批量 API 提供给前端。
