# 趋势交易系统

基于多技术指标的全栈股票趋势分析工具，支持实时行情分析与交互式图表。

![后端](https://img.shields.io/badge/后端-FastAPI-009688) ![前端](https://img.shields.io/badge/前端-React%2019%20%2B%20TypeScript-3178C6) ![图表](https://img.shields.io/badge/图表-TradingView%20Lightweight-orange)

## 功能特性

- **技术指标**：EMA20/50、ADX、RSI（7/14/21）、MACD、布林带、KDJ、ATR
- **共振策略**：多周期趋势对齐信号，含入场/出场评分
- **交互图表**：五栏联动布局（价格、RSI、KDJ、MACD、ATR），十字线同步
- **自选股管理**：分组管理，支持拖拽排序和自定义别名
- **回测引擎**：单标的回测与 RS 轮动组合模拟
- **周线分析**：周线 K 线重采样与布林带突破检测

## 快速开始

### 环境要求

- Python 3.12+，安装 [uv](https://github.com/astral-sh/uv)
- Node.js 18+，安装 [pnpm](https://pnpm.io)

### 本地开发

```bash
# 安装所有依赖
make install

# 启动前后端（前端 :5173，后端 :8000）
make dev
```

### Docker 部署

```bash
make docker-build
make up
# 查看日志
make logs
```

## 项目结构

```
├── backend/          # FastAPI + pandas-ta
│   ├── main.py       # API 接口与自选股管理
│   ├── analysis*.py  # 指标计算、策略信号、缓存
│   └── backtest.py   # 回测引擎
└── frontend/         # React 19 + Vite + Tailwind CSS 4
    └── src/
        ├── App.tsx         # 自选股列表（含拖拽）
        └── ChartModal.tsx  # 全屏图表弹窗
```

## 回测示例

```bash
cd backend
uv run python backtest.py --symbols 510300.SS 510050.SS --strategy-version resonance_v2_atr_1_5 --start 2023-01-01
```

## 交易策略

系统设计为每日两次复盘（午间 12:00–13:00，晚间 21:00–22:00）：

- **趋势方向**：EMA20 与 EMA50 的相对位置
- **趋势强度**：ADX > 25 确认趋势行情
- **入场时机**：4 小时图回踩 EMA 后出现反转形态
- **止损方式**：动态 1.5× ATR 跟踪止损

## 许可证

MIT
