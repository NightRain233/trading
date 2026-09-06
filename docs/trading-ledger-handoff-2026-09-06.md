# 交易策略研究与纸面运行交接

更新时间：2026-09-06

这份文档交接两个仓库之间的职责、已经完成的修复和下一步运行入口。当前系统仍是纸面跟踪，
没有券商实盘连接，也没有因为本次研究或提交而激活、部署或改写生产账户。

## 先记住这条边界

历史研究和每日纸面状态是两条不同的工作流：

- [xquant 研究包](/Users/zz/Desktop/Code/zsd/xquant/research/trading-ledger-2026-09-05/README.md)
  保存原始研究恢复、修复后历史基准、五个三资产变种的统一账本、审计文件和复现脚本。它用于
  复现、审计和开启下一轮独立研究，不用于显示今天的持仓或决定今天是否成交。
- trading 中已有的 [`/portfolio-daily-brief` skill](/Users/zz/Desktop/Code/zsd/trading/.agents/skills/portfolio-daily-brief/SKILL.md)
  用当前 API 和日报渲染器展示纸面账户。它是只读入口，不创建订单、不刷新账户、不修改参数，
  也不把连接失败解释成“没有订单”。目前不需要再做第二套日报 skill。
- 写入账户状态的是 `scripts/run_portfolio_daily.sh` 及其调用的 `portfolio_daily_job.py`；日报
  skill 只读取写入后的状态。日报生成和账户刷新要分开理解。

因此，日常查看用 `/portfolio-daily-brief`，历史问题追溯和重新计算用 xquant 研究包入口。
如果将来接入真实券商，还需要单独的券商适配、成交回报和资金对账，不能把纸面日报称为实盘证明。

## 已完成的工作

### #5：线上行情故障核验

上次只读核验截至 2026-09-04：`588890.SS` 已恢复到最新完整数据日，连续日期存在，
`dataStale=false`、`dataIntegrity.hasGap=false`。服务器缓存显示 A 股走 TickFlow，8 月 25 日
份额拆分与后续三分之一价格对应；现有证据高度指向复权切换触发全量刷新保护，但无法从旧日志
还原最初的具体异常。详见
[`docs/issue-5-live-audit-2026-09-05.md`](/Users/zz/Desktop/Code/zsd/trading/docs/issue-5-live-audit-2026-09-05.md)。

结论是“线上已恢复，根因高度指向拆分复权保护”，没有放松新鲜度门槛，也没有改写生产账本或
关闭 GitHub issue。

### #7：执行统一

trading 的 `NextOpenPaperEngine`、账本、执行规则和共享逐日循环现在是成交、持仓、现金和 NAV
的唯一实现。`research_replay.py` 只接收冻结的 `FrozenDecision` 与行情，直接调用这套执行内核；
研究代码不再复制另一套成交计算。

核心修复包括：

- 信号在 D 日完成收盘后冻结，下一可成交 Open 执行；缺 Open 时保留订单并延迟，不用 Close 代替。
- 卫星预算调整产生真实 `SLEEVE_RESIZE` 订单、成交和费用，不再直接改持仓数量。
- 研究和 paper 服务共享 `advance_current_contract`，按 checkpoint 补齐漏跑日期，不回填旧账户历史。
- 交易仓库只保留轻量合成 golden fixture；历史 CSV、原始压缩包和研究测试迁入 xquant。

### #10：可复现研究包

xquant 的 `research/trading-ledger-2026-09-05/` 现在包含：

- `core90_recovery_2026_09_05/`：原始 xquant 研究、81 个可观察标的的封存行情和旧结果复现；
- `core90_current_contract_2026_09_05/`：当前 `core90_ma200_bull10` 2.1.0 合同的历史基准、
  订单/成交/持仓/NAV、现金与数量守恒审计、旧版差异和 28 项跨仓库源码哈希；
- `three_asset_variant_comparison_2026_09_05/`：纯三资产、90% 核心加现金、整体 SuperTrend、
  一会话延迟和修复版 Bull10 五个版本的统一账本输出与审计。

主基准重跑仍为 `PASS_EXECUTION_AUDIT`：数量不一致 0 行、现金最大误差约 `5.98e-10`、
提前成交 0 笔，CAGR 14.98%、Sharpe 1.30、最大回撤 -12.66%。五个变种也全部通过数量、
现金和时序审计。这个结论限定在有限可观察标的池和已记录的 FX、开盘可成交性假设内，不能扩展
为完整市场验证、样本外盈利证明或实盘授权。

提交已经拆开：

- trading `c1731bb`：next-open 执行和 sleeve 成交修复；
- trading `2a5530c`：纸面执行适配器、轻量 fixture、测试和文档；
- xquant `f35a3a8`：研究包、历史产物、复现脚本和研究测试。

两边工作区在交接时均干净，没有推送、部署或 issue 状态变更。

## 当前策略状态

历史研究的默认比较基准是 100% 三资产 RiskParity；修复版 Core90 + MA200 Bull10 保留为增强
观察线。统一重算结果没有证明 SuperTrend 让整个组合明显变强：整体 SuperTrend 过滤版本年化
更高，但最大回撤明显更深、Sharpe 更低；Bull10 相比 90% 核心加现金多一些收益，相比满仓
三资产少一些收益。不要在已冻结样本上继续挑选参数。

上次线上只读记录显示纸面账户在 2026-08-20 激活，至 2026-09-04 持续追加每日 NAV 和订单；
生产账户仍是旧的 1.0.0 运行状态，修复版 2.1.0 尚未部署。交接后首先积累冻结规则下的前向
记录，不要把短期连续运行当作长期优势证明。

## 日常运行顺序

### 写入和生成日报

由维护任务先更新行情、推进纸面账户并生成 Markdown 日报：

```bash
cd /Users/zz/Desktop/Code/zsd/trading
scripts/run_portfolio_daily.sh
```

默认输出为 `backend/backtest_results/openclaw_portfolio_daily.md`，状态文件为
`backend/backtest_results/portfolio_daily_job_status.json`。定时任务应保持现有的 16:40 和
次日 07:15 两次检查；如果数据源或某个策略失败，状态必须在日报中保留。

### 只读查看

交互式查看使用：

```text
/portfolio-daily-brief
```

Skill 先检查 `daily-job-status`，再只展开 `core90_ma200_bull10`，按“到期订单 → 等待 Open 的
订单 → Bull flip/MA200 → 持仓现金敞口 → NAV/回撤/相对 RiskParity → 异常”顺序展示。
RiskParity、Theme Alpha 和 BTC 账户继续作为比较线，除非明确要求比较，否则不要混在主策略中。

需要直接生成只读 Markdown 时，可在 trading 根目录运行：

```bash
python3 scripts/openclaw_supertrend_alerts.py \
  --api-base http://127.0.0.1:8000/api \
  --mode daily-brief \
  --format markdown \
  --include-portfolio
```

本地 API 不可用时，只有在明确要求生产数据且生产地址已配置时才切换到生产 API；一份日报只用
一个 API 来源，不能混用本地和生产响应。

## 交接后的禁止事项和升级条件

- 只读 skill 不得调用 refresh 或 activate；它展示状态，不执行交易。
- `PENDING_EXECUTION` 是未成交订单；缺 Open 只能说延迟，不能说已成交或已取消。
- 不为已激活账户回填历史，不把研究 CSV 导入生产账本，不在当前基准上调参后覆盖旧结果。
- 需要重新研究时使用新版本号、新输出目录和新的研究说明；不要修改冻结的 2.1.0 结果。
- 只有完成独立的券商执行、资金/持仓对账、风险限额、审批和小额前向验证后，才讨论真实资金；
  当前日报 skill 本身不提供实盘授权。

## 入口索引

- 研究包总说明：`/Users/zz/Desktop/Code/zsd/xquant/research/trading-ledger-2026-09-05/README.md`
- 主策略复现：`.../core90_current_contract_2026_09_05/README.md`
- 变种比较：`.../three_asset_variant_comparison_2026_09_05/README.md`
- 纸面策略合同：[`docs/portfolio-strategies-paper-tracking.md`](/Users/zz/Desktop/Code/zsd/trading/docs/portfolio-strategies-paper-tracking.md)
- 日报 skill：[`portfolio-daily-brief/SKILL.md`](/Users/zz/Desktop/Code/zsd/trading/.agents/skills/portfolio-daily-brief/SKILL.md)
