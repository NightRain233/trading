# 文档索引

文档按"用不用得上"排序。带日期的研究报告保留当时的口径，不随后来的结论改写；读旧报告时先看本页的"现状"一栏。

策略研究的主战场在同级仓库 xquant，这里的研究报告多是 2026 年 6 月前后在本仓库里做的 SuperTrend / RS 轮动探索。**当前结论以 xquant 为准**：

- [xquant README](../../xquant/README.md)：三组合是什么、证据到哪一步
- [温斯坦测试总结（2026-10-18）](../../xquant/docs/notes/weinstein-summary-2026-10-18.md)：哪些择时有效、哪些无效
- [xquant 研究索引](../../xquant/docs/strategies/research-index.md)

## 先读

| 文档 | 内容 |
|---|---|
| [../README.md](../README.md) | 这个工具做什么、主策略、页面、本地运行、部署 |
| [portfolio-strategies-paper-tracking.md](portfolio-strategies-paper-tracking.md) | 纸面组合账户：有哪些策略、怎么调仓、2026-10-18 主策略切换说明 |
| [../.agents/skills/shared/market-rules.md](../.agents/skills/shared/market-rules.md) | 看盘口径：主线边界、温斯坦定义、SuperTrend 的定位、不能下的结论 |

## 使用指南

| 文档 | 内容 |
|---|---|
| [three-asset-core-guide.md](three-asset-core-guide.md) | 三组合分红修正版纸面账户：初始金额、逐笔入金、复核命令 |
| [strategy-backtesting-guide.md](strategy-backtesting-guide.md) | 本仓库的策略比较脚本怎么跑 |
| [rs-rotation-usage.md](rs-rotation-usage.md) | RS 轮动页面和回测怎么用 |
| [trading-ledger-handoff-2026-09-06.md](trading-ledger-handoff-2026-09-06.md) | 跨仓库交接：研究包、日报入口、账本复现 |
| [../scripts/openclaw_daily_brief_prompt.md](../scripts/openclaw_daily_brief_prompt.md) | 每日推送助手的系统提示词 |

## 研究报告

### 组合与多资产

| 文档 | 现状 |
|---|---|
| [multi-asset-balanced-portfolio-research-2026-06-06.md](multi-asset-balanced-portfolio-research-2026-06-06.md) | 早期多资产风险预算探索；后续由 xquant 三组合研究取代 |
| [bull-flip-strategy-convergence-2026-09-03.md](bull-flip-strategy-convergence-2026-09-03.md) | Core90 + Bull10 的收敛决策；该策略现为后台对照 |
| [def200-cash-strategy-check-and-cny-small-capital-readiness-2026-09-06.md](def200-cash-strategy-check-and-cny-small-capital-readiness-2026-09-06.md) | Theme Alpha 的 Def200 现金防守核对；现为后台对照 |
| [def200-manual-launch-handoff-2026-09-06.md](def200-manual-launch-handoff-2026-09-06.md) | Def200 小额手动试运行交接；未作为主线 |

### SuperTrend（现为学习观察层）

| 文档 | 现状 |
|---|---|
| [supertrend-strategy.md](supertrend-strategy.md) | SuperTrend 研究笔记总入口 |
| [supertrend-vs-momentum-5y-report.md](supertrend-vs-momentum-5y-report.md) | 与动量轮动的近五年对比（另有 [HTML 版](supertrend-vs-momentum-5y-report.html)） |
| [supertrend-optimization-research-2026-06-04.md](supertrend-optimization-research-2026-06-04.md) | 参数优化记录 |
| [supertrend-asset-optimization-summary-2026-06-05.md](supertrend-asset-optimization-summary-2026-06-05.md) | 分资产优化阶段总结 |
| [supertrend-fit-research-2026-06-05.md](supertrend-fit-research-2026-06-05.md) | 哪些品种适合 SuperTrend |
| [supertrend-position-sizing-research-2026-06-05.md](supertrend-position-sizing-research-2026-06-05.md) | 仓位控制 |
| [us-supertrend-optimization-2026-06-05.md](us-supertrend-optimization-2026-06-05.md) | 美股专项 |
| [crypto-supertrend-robustness-2026-06-05.md](crypto-supertrend-robustness-2026-06-05.md) | 加密货币稳健性；BTC 日线 ST 后来进入主策略卫星 |

### A 股 ETF（结论：择时跑不赢持有）

| 文档 | 现状 |
|---|---|
| [a-share-supertrend-optimization-2026-06-04.md](a-share-supertrend-optimization-2026-06-04.md) | A 股 SuperTrend 优化 |
| [a-share-etf-pure-st-portfolio-2026-06-06.md](a-share-etf-pure-st-portfolio-2026-06-06.md) | 纯 ST 组合 |
| [a-share-etf-st-rs-fair-comparison-2026-06-06.md](a-share-etf-st-rs-fair-comparison-2026-06-06.md) | ST 与 RS 公平对照 |
| [a-share-weekly-daily-st-equal-weight-2026-06-06.md](a-share-weekly-daily-st-equal-weight-2026-06-06.md) | 周线 + 日线 ST 等权 |
| [a-share-theme-etf-st-monthly-filters-2026-06-06.md](a-share-theme-etf-st-monthly-filters-2026-06-06.md) | 主题 ETF 月级别过滤 |
| [dynamic-a-share-theme-etf-st-research-2026-06-06.md](dynamic-a-share-theme-etf-st-research-2026-06-06.md) | 无后验动态主题池 |
| [a-share-dca-timing-research-2026-06-06.md](a-share-dca-timing-research-2026-06-06.md) | 定投节奏 |
| [a-share-broad-rs-vs-hold-dca-calendar-year-2026-06-06.md](a-share-broad-rs-vs-hold-dca-calendar-year-2026-06-06.md) | 宽基 RS、持有、定投按自然年对比 |

### RS 动量轮动（现为研究对照）

| 文档 | 现状 |
|---|---|
| [rs-rotation-conclusions-2026-06-05.md](rs-rotation-conclusions-2026-06-05.md) | 阶段结论，先读这篇 |
| [rs-rotation-decisions.md](rs-rotation-decisions.md) | 设计决策 |
| [rs-rotation-backtest-results.md](rs-rotation-backtest-results.md) | 回测结果 |
| [rs-rotation-robustness-research-2026-06-05.md](rs-rotation-robustness-research-2026-06-05.md) | 鲁棒性 |
| [rs-rotation-lookahead-audit-2026-06-05.md](rs-rotation-lookahead-audit-2026-06-05.md) | 未来函数审计 |
| [rs-rotation-calendar-year-market-comparison-2026-06-05.md](rs-rotation-calendar-year-market-comparison-2026-06-05.md) | 跨市场自然年比较 |
| [rs-drawdown-protection-research-2026-06-05.md](rs-drawdown-protection-research-2026-06-05.md) | 回撤保护 |
| [us-rs-benchmark-comparison-2026-06-05.md](us-rs-benchmark-comparison-2026-06-05.md) | 美股 ETF 基准比较 |

## 运维与事故记录

| 文档 | 内容 |
|---|---|
| [issue-5-live-audit-2026-09-05.md](issue-5-live-audit-2026-09-05.md) | 线上行情核验 |
| [issue13-market-data-recovery-2026-09-10.md](issue13-market-data-recovery-2026-09-10.md) | 生产行情数据恢复 |
| [evidence/](evidence/) | 账本一致性等核验证据 |

## 实施计划

[plans/](plans/) 按日期保存设计稿和实施计划（`*-design.md` 是设计，同名无后缀的是实施步骤）。它们记录当时的决定，不保证与现在的代码一致。

## 历史（已被取代）

| 文档 | 说明 |
|---|---|
| [legacy/llm-readme.md](legacy/llm-readme.md)、[legacy/current-system-strategy.md](legacy/current-system-strategy.md)、[legacy/current-api-contract.md](legacy/current-api-contract.md) | 2026 年初 resonance_v1 时代的系统与接口说明 |
| [legacy/resonance-v2-strategy.md](legacy/resonance-v2-strategy.md) | resonance v2 共振策略 |
| [legacy/weekly-bb-breakout.md](legacy/weekly-bb-breakout.md) | 周线布林突破扫描；页面已由温斯坦周线扫描取代 |

现在的接口以代码为准：后端启动后打开 `http://127.0.0.1:8000/docs` 查看自动生成的接口文档。
