# 看盘台（trading）

一个给普通投资者用的个人看盘工具：**每天一句话告诉你主策略要不要操作；周末用温斯坦周线看各个市场处在什么阶段。** 所有账户都是纸面跟踪，系统不连券商，也不会自动下单。

策略的研究和回测在同级仓库 [xquant](../xquant/README.md) 里；本仓库负责每天把冻结好的规则跑起来、记账、展示和推送。

![后端](https://img.shields.io/badge/后端-FastAPI-009688) ![前端](https://img.shields.io/badge/前端-React%2019%20%2B%20TypeScript-3178C6) ![图表](https://img.shields.io/badge/图表-SVG%20%2B%20Lightweight%20Charts-orange)

> 这是个人研究与记录工具，不构成投资建议。历史回测不代表未来收益。

## 主策略：三组合 + BTC 7.5%

| 部分 | 买什么 | 规则 |
|---|---|---|
| 核心 92.5% | 沪深300ETF 510300、纳指100ETF 513100、黄金ETF 518880 | 看最近 20 个交易日的波动，波动小的多配、波动大的少配；每 10 个交易日检查一次 |
| 卫星 7.5% | BTC | 只在检查日看 BTC 日线 SuperTrend(10, 3)：向上就持有，向下就换成现金 |

- 不加杠杆、不择时卖出核心资产；手里的闲钱就是缓冲，所以策略里不放债券。
- 预期：长期年化大约 8–12%，要准备承受 15–20% 的回撤。
- 为什么选它、证据到哪一步：见 xquant 的[两组合与三组合](../xquant/docs/strategies/two-three-asset.md)和 [BTC 卫星价格修正复核](../xquant/docs/notes/btc-satellite-corrected-prices-2026-10-18-review.md)。
- 其他策略（Core90 + Bull10、Theme Alpha、RiskParity 等）保留为后台对照账户，只记录、不推送。

技术分析（温斯坦阶段、SuperTrend 扫描）只用来学习和观察，**不改变主策略的持仓**。研究结论是：A 股上所有择时规则都跑不赢一直持有；温斯坦规则在美股指数上能明显降低回撤；BTC 用日线 SuperTrend 最合适。详见 [温斯坦测试总结](../xquant/docs/notes/weinstein-summary-2026-10-18.md)。

## 页面

| 页面 | 用途 |
|---|---|
| **我的组合** `/` | 一句话结论（要不要操作）、净值与回撤、持仓比例、BTC 日线 SuperTrend 历史与开关记录 |
| **看盘** `/watchlist` | 三个大盘的温斯坦阶段；自选按相对强度排序；点开看周线图（布林带、30/20 周线、阶段色条、成交量、相对强度、周 MACD） |
| **周线扫描** `/weekly-scan` | 周末复盘用：本周换阶段、各市场小图；美股按温斯坦规则给出"可买 / 持有 / 卖出"，A 股只看状态 |
| **复盘** `/history-trades` | 选一个品种，把日线 SuperTrend 规则在过去重放一遍，逐笔看买卖和收益 |
| SuperTrend `/supertrend` | 日线趋势扫描，学习观察用 |
| RS 轮动 `/rs-rotation` | 动量轮动的历史回测，研究对照用 |

支持浅色 / 深色 / 跟随系统；手机上用底部导航。涨跌颜色按 A 股习惯：红涨绿跌。

## 每日推送与 AI 助手

- **每日推送**：`scripts/openclaw_supertrend_alerts.py --mode daily-brief` 生成日报，主策略和 BTC 日线开关在前，SuperTrend 扫描压成一行"学习观察"。推送助手（OpenClaw / Hermes）的系统提示词在 [`scripts/openclaw_daily_brief_prompt.md`](scripts/openclaw_daily_brief_prompt.md)。
- **AI 助手 skill**（`.agents/skills/`，Claude Code 通过 `.claude/skills` 读同一份）：

| skill | 做什么 |
|---|---|
| `scan` | 周末复盘：主策略是否操作 → 大盘阶段 → 本周换阶段 → 美股学习账户 → A 股状态 → 一行 SuperTrend |
| `analyze` | 单标的：温斯坦周线结论 → SuperTrend 是否一致 → 和主策略的关系 |
| `portfolio-daily-brief` | 每日组合简报和账户健康检查（只读） |
| `fupan` | 把对话里的判断整理成 `reviews/` 里的复盘笔记 |

所有 skill 先读共用口径 [`.agents/skills/shared/market-rules.md`](.agents/skills/shared/market-rules.md)。取数用 `scripts/trading_analysis_helper.py --query weekly` 或 `--query brief --symbol <代码>`。

## 本地运行

需要 Python 3.12+ 与 [uv](https://github.com/astral-sh/uv)、Node.js 18+ 与 [pnpm](https://pnpm.io)。

```bash
make install   # 安装前后端依赖
make dev       # 前端 http://127.0.0.1:5173，后端 http://127.0.0.1:8000
```

- 美股、黄金、加密行情来自 Yahoo Finance。在国内需要代理，启动后端前设置 `https_proxy` / `http_proxy`，并把 `127.0.0.1,localhost,free-api.tickflow.org` 加进 `no_proxy`。
- A 股和 ETF 行情来自 TickFlow 的收盘后日 K，只在晚间使用已完成的交易日数据。
- 首次打开页面会下载并缓存行情（`backend/data/*.parquet`，已被 git 忽略），之后基本秒开。
- 纸面账户需要显式激活一次（页面上没有按钮，刷新也不会自动创建账户）。新账户从全现金开始，到下一个检查日按规则建仓，不会补算历史：

  ```bash
  curl -X POST http://127.0.0.1:8000/api/portfolio-strategies/btc_supertrend_satellite/activate \
    -H 'Content-Type: application/json' -d '{"activationDate": "2026-10-18", "initialCash": 100000}'
  ```

### 行情数据源保护

TickFlow 和 Yahoo 都有跨进程串行、请求间隔、重复抑制、指数退避和熔断保护，默认只在上海时间 21:00 预热一次。参数通过 `.env` 配置（从 `.env.example` 复制）。运行状态：

```bash
curl http://127.0.0.1:8000/api/data-sources/status
```

需要暂停 TickFlow 时设置 `TICKFLOW_FETCH_ENABLED=false` 并重启后端；已有缓存仍可使用。日常只拉最近 7 个自然日并校验重叠区间；发现复权基准变化时保留旧缓存，等人工全量校准：

```bash
cd backend && uv run python refresh_a_share_data.py --force
```

## 测试

```bash
# 后端（用 --frozen，避免国内镜像改写 uv.lock）
cd backend && PYTHONPATH=. uv run --frozen pytest -q

# 前端
cd frontend && node --test test/*.mjs && pnpm build && pnpm exec eslint src
```

后端测试期间不会写入 `backend/data/`：`tests/conftest.py` 会拦截后台刷新线程。

## 部署

服务器端不需要编译工具：在本地交叉编译 linux/amd64 镜像后上传。

```bash
cp Makefile.local.example Makefile.local   # 填写 DEPLOY_HOST / DEPLOY_PATH（已被 git 忽略）
make deploy-full     # 交叉编译 + 同步代码 + 上传镜像 + 重启
make deploy-images   # 只上传已构建的镜像并重启
```

服务器地址只写在 `Makefile.local` 或环境变量 `TRADING_API_BASE` 里，不要写进仓库文件。

## 目录

```text
├── backend/                    # FastAPI
│   ├── main.py                 # API、自选管理、扫描接口
│   ├── analysis*.py            # 行情缓存、指标、温斯坦阶段（analysis_weinstein.py）
│   ├── portfolio_strategies/   # 纸面组合：策略注册、调仓日历、账本、BTC 卫星
│   └── tests/
├── frontend/                   # React 19 + Vite + Tailwind 4
│   └── src/
│       ├── components/         # 各页面（PortfolioStrategiesPage、MarketPage、WeeklyScanPage …）
│       ├── design.css          # 新版设计 token（浅色 / 深色）
│       └── *.js + *.d.ts       # 纯函数助手，用 node --test 测试
├── scripts/                    # 每日推送、分析助手、研究脚本
├── .agents/skills/             # AI 助手 skill
├── docs/                       # 使用指南、研究报告、计划，入口见 docs/README.md
└── reviews/                    # 个人复盘笔记（Obsidian 格式）
```

## 文档

从 [docs/README.md](docs/README.md) 开始：它按"先读 / 使用指南 / 研究报告 / 运维记录 / 历史"分类列出了所有文档。

## 许可证

MIT，见 [LICENSE](LICENSE)。
