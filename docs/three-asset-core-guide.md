# 三组合：纸面账户怎么用

新版后端已经提供一个与分红修订研究对齐的独立纸面账户：`risk_parity_core_cash_next_open`，版本 `2.0.0`。它支持一次性投入，也支持逐笔记录后续入金。这里说明代码支持的操作和复核方法；本次开发没有部署服务，也没有启用实际用户账户。

想先理解策略，请读 [xquant 普通读者版](../../xquant/docs/strategies/two-three-asset.md)和[一次投入与定投的持有体验](../../xquant/docs/strategies/holding-experience.md)。单独克隆 trading 时，这两份资料位于 xquant 的对应路径。

## 先分清两个账户版本

| 项目 | 新版修订研究纸面账户 | 旧版 RiskParity Core |
|---|---|---|
| 策略 ID | `risk_parity_core_cash_next_open` | `risk_parity_core_next_open` |
| 版本 | `2.0.0` | `1.0.0` |
| 成交和持仓估值 | 原始、未复权的场内 ETF 价格 | 原有加法前复权缓存 |
| 分红 | 登记权益、应收、现金到账分别记账 | 原有价格处理口径 |
| 初始金额和后续入金 | 自定义初始金额、显式逐笔入金 | 保留旧激活方式 |
| 调仓日历起点 | 2015-01-05，沿用冻结研究相位 | 2026-07-01 |
| 费用 | 每筆实际买卖金额收万分之一 | 原有半周转费用公式，参数 10 bp |

两个账户的历史各自保存。页面默认主策略仍是 Core90 + MA200 Bull10；新版没有替换它，也没有修改旧账户的基准。前端本次没有改造，新版完整的初始金额与入金操作通过后端接口使用。

## 新版每天做什么

资产固定为沪深300 ETF `510300.SS`、纳指 ETF `513100.SS`、黄金 ETF `518880.SS`。它按最近20个共同交易日的波动倒数分配目标，每10个共同交易日生成一次调仓信号，在严格晚于信号日的下一个三只 ETF 都有有效开盘价的日子执行。缺开盘价时等待，不拿收盘价代替。原始历史需要覆盖日历起点和此前的20日预热。

分红有两个用途，时间不同：

- **计算波动**：除息日把已公告的现金分红计入当日收益，避免机械除息看起来像一次暴跌；未来分红不会倒改此前的收益率。
- **账户记账**：登记日收盘持仓决定权益；除息记应收，发放日收盘后才转成可花的现金。应收计入权益，但不能用于下单；到账现金等下一次原定调仓再投资。

拆分停牌日按修订研究调整估值标记，收盘后转换份额；复牌后使用实际原始价格。费用按实际买入和卖出金额分别收万分之一，没有最低费用，份额允许小数。

这些是研究合同：没有杠杆、趋势退出、溢价过滤，也没有整手、真实盘口成交或券商资金结算模拟。场内价格已经包含当时的折溢价变化；低波动不能消除溢价风险。可靠海外 ETF 估值流程仍需继续验证。

## 一次性投入和定投有什么区别

**一次性投入**：激活时提供 `initialCash`，这笔钱先作为现金，等激活日及之后的原定信号在下一有效开盘成交。不会用激活当天收盘信号去成交当天开盘。

**定投**：可以用0元激活，再逐笔提交入金日期、金额和唯一编号。非调仓日只用新增资金按上一次已执行的比例买入，不为了入金重新卖买整个账户；第一次入金尚无已执行比例时，使用前一共同交易日已知的波动比例。入金与原定调仓同日时，正常调仓会一起调整现有持仓和新增资金。

逐笔入金是纸面现金流指令，假设指定日期开盘前资金可用；记录时间另行保存。允许提前登记未来日期，未到执行日不计入累计本金，也不使用未来价格。这里没有自动按月扣款任务。已处理日期不能补写或修改入金，相同编号重试不会重复记钱，编号与金额或日期冲突会报错。休市日和已知拆分停牌日不能作为入金买入日期；其他缺行情情况会明确阻断，等待修复输入。

## 准备独立的原始行情

新版只读 `backend/data/core_raw/`，不会拿原有 `data/{symbol}.parquet` 的加法复权行情充当原始成交价。导入命令只整理本地冻结数据，不联网、不创建账户。运行以下命令时，工作目录为 `trading/backend`：

```sh
uv run python scripts/import_core_raw_snapshot.py \
  --input ../../xquant/outputs/etf-dividend-valuation-2026-10-04/inputs/raw.json \
  --data-dir data
```

该输入来自 xquant 的分红修订复现包，准确 SHA256 已固定在导入器中，凭同一份复现包即可导入，不依赖包外的旧采集日志。其他原始行情必须同时提供记录成功请求、明确 `adjust=none` 的采集日志，使用 `--fetch-log` 指定。已经存在的独立快照默认拒绝覆盖；明确更新时才使用 `--replace`。通用行情缓存不受影响。

加载器校验原始价格标识、文件哈希、日期和 OHLC 合法性。当前随代码的公司行动快照只覆盖修订研究所保留的事件，验证截止2026-09-30，不等于三只产品的完整生命周期调查；某资产没有事件行，不能据此认定从未分红或拆分。运行结果的 `observation.values.corporateActionCoverage` 明确标示这一边界。

连续纸面跟踪需要**另行更新原始行情和官方事件快照**。日任务中的常规行情更新不会自动更新 `core_raw`。原始行情落后于预期已完成交易日、超过公司行动验证截止、或者修改了已处理输入时，返回 `BLOCKED` 并保留旧账本；日任务把阻断记为失败。更新事件时可用 `--corporate-actions` 提供同结构 JSON，它需要官方来源、事件哈希与覆盖说明；不能只改验证截止日期来假装已经核查。自定义事件文件也由原始行情 manifest 校验。

## 通过接口操作

以下示例以本地后端 `127.0.0.1:8000` 为例。GET 只读；POST 会写入纸面账本。数值用于说明接口，不是个人资金计划。

先查看账户及输入状态：

```sh
curl 'http://127.0.0.1:8000/api/portfolio-strategies'
curl 'http://127.0.0.1:8000/api/portfolio-strategies/risk_parity_core_cash_next_open/snapshot'
```

一次性投入的激活请求：

```sh
curl -X POST 'http://127.0.0.1:8000/api/portfolio-strategies/risk_parity_core_cash_next_open/activate' \
  -H 'Content-Type: application/json' \
  -d '{"activationDate":"2015-01-05","initialCash":100000}'
```

这是从历史日期开始的纸面回放例子。激活仅登记现金，随后刷新才会补算该账户起始日至最新可用日期。定投回放可改用 `initialCash:0`，**先登记所需的全部历史入金，再刷新**；刷新后不能向已经处理的日期补写入金。同一策略版本只有一个账户，同日同金额激活可重试，不能用不同初始金额重新激活来覆盖它。

增加一笔入金，再推进账本：

```sh
curl -X POST 'http://127.0.0.1:8000/api/portfolio-strategies/risk_parity_core_cash_next_open/deposits' \
  -H 'Content-Type: application/json' \
  -d '{"contributionDate":"2015-02-02","amount":10000,"idempotencyKey":"paper-2015-02"}'
curl -X POST 'http://127.0.0.1:8000/api/portfolio-strategies/risk_parity_core_cash_next_open/refresh'
```

查询入金、逐笔成交和账户曲线：

```sh
curl 'http://127.0.0.1:8000/api/portfolio-strategies/risk_parity_core_cash_next_open/deposits'
curl 'http://127.0.0.1:8000/api/portfolio-strategies/risk_parity_core_cash_next_open/ledger?limit=100'
curl 'http://127.0.0.1:8000/api/portfolio-strategies/risk_parity_core_cash_next_open/nav?start=2015-01-05&end=2026-09-30'
curl 'http://127.0.0.1:8000/api/portfolio-strategies/risk_parity_core_cash_next_open/target-weights'
curl 'http://127.0.0.1:8000/api/portfolio-strategies/risk_parity_core_cash_next_open/rebalance-diff'
```

## 看哪些数字

| 字段 | 普通读者可以怎样理解 |
|---|---|
| `nav.netNav` | 当前总权益，已扣发生的费用，包含尚未到账的分红应收 |
| `nav.cash` / `receivable` | 能用于调仓的现金 / 仍在等待的分红 |
| `nav.principal` | 已执行到该日期的累计初始资金与后续入金；不含未来计划 |
| `nav.contribution` | 当日入金，不是投资收益 |
| `nav.unitNav` / `cumulativeReturn` | 剔除入金影响的单位净值 / 相对初始单位净值的累计收益，不是资金加权年化 |
| `nav.drawdown` | 单位净值从此前高点下跌多少 |
| `nav.marketPnl` / `dividendIncome` | 当日价格变化与分红合计的损益 / 其中的分红收入，勿重复相加 |
| `nav.cumulativeFees` | 累计实际买卖研究佣金 |
| `nav.liquidationWealth` / `profit` | 假设现在退出再扣一次卖出佣金的权益 / 其超过累计本金的部分，仍含应收，并没有实际卖出 |
| `nav.accountResidual` | 权益、入金、损益和费用能否对上；正常只剩浮点误差 |

`grossNav` 是当天费用扣除前的权益标记（净权益加当天费用），不是一条完全不收费用的历史曲线。`desiredWeights` 是最新目标，`currentWeights` 是实际持仓；应收与现金会让资产权重之和低于1。`executableWeights` 留空，不能当作券商下单清单。

## 怎样复核这次接入

已有 [冻结样本对照证据](evidence/corrected-core-parity-2026-10-05.json)。脚本独立运行 trading 的持久化账户，不导入 xquant 模拟核；对照修订研究保存的逐日账本和逐笔成交。

```sh
uv run python scripts/check_corrected_core_parity.py \
  --data-dir data \
  --research-dir ../../xquant/outputs/etf-dividend-valuation-2026-10-04 \
  --output /tmp/corrected-core-parity.json
```

脚本使用临时数据库，不改已有账户。冻结样本为2015-01-05至2026-09-30：一次投入5万元与每月1万元定投分别对照4,287个日估值点、858/1,251笔成交；金额、份额和费用在浮点误差内一致，重复刷新不改变账本。证据文件列出具体误差、输入哈希和源码哈希；这证明接入符合该研究合同，不是新增的样本外有效性或实盘成交验证。

相关检查命令：

```sh
uv run python -m pytest -q tests/test_corrected_core.py tests/test_portfolio_*.py tests/test_next_open_*.py tests/test_xquant_next_open_parity.py
```

纸面会计、API和对照完成后，再接前端的初始金额输入、入金记录和易懂账户曲线；可靠估值、整手执行和持续原始行情更新需要各自验证。
