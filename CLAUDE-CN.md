# CLAUDE.md (中文版)

此文件为 Claude Code (claude.ai/code) 在此代码库中工作时提供指导。

## 项目概览

一个具有实时股票分析和可视化功能的趋势交易系统。该应用基于 EMA（指数移动平均线）、ADX（平均趋向指标）、MACD、RSI 等指标提供技术分析，以支持趋势跟踪交易策略。

**架构**：全栈应用，采用 Python FastAPI 后端和 React TypeScript 前端，使用 Docker 进行容器化。

## 常用命令

### 开发

```bash
# 安装所有依赖（前端 + 后端）
make install

# 在本地运行全栈（前端和后端同时运行）
make dev

# 仅运行前端（Vite 开发服务器，端口 5173）
make dev-fe

# 仅运行后端（uvicorn，端口 8000）
make dev-be
```

### 构建与部署

```bash
# 构建前端生产包
make build-fe

# 构建 Docker 镜像
make docker-build

# 启动容器（后台运行模式）
make up

# 停止容器
make down

# 查看日志
make logs

# 重启容器
make restart

# 部署到远程服务器（使用 rsync）
make deploy
```

### 包管理

- **前端**：使用 `pnpm`（必须使用，不要使用 npm/yarn）
- **后端**：使用 `uv` 进行 Python 依赖管理（替代 pip/venv）

## 技术架构

### 后端 (`/backend`)

**框架**：FastAPI 及 uvicorn ASGI 服务器

**核心文件**：
- `main.py`：包含 REST API 接口和自选列表（watchlist）管理的 FastAPI 应用
- `analysis.py`：股票数据获取 (yfinance)、技术指标计算 (pandas-ta) 和缓存逻辑

**核心功能**：
- **自选列表管理**：支持拖拽排序的分组组织方式，支持代码别名
- **技术指标**：EMA20/50, ADX(14), RSI (7/14/21 周期), MACD, BOLL, KDJ, ATR
- **数据缓存**：基于 Parquet 的缓存（1 小时缓存有效期，2 年数据保留）
- **线程安全**：每个股票的代码在指标计算时使用细粒度锁，而在 yfinance 下载时使用全局锁
- **周线数据**：重采样周线 K 线及指标，用于长期趋势分析

**API 接口**：
- `GET /api/quote/{symbol}`：获取包含所有指标的详细股票分析
- `GET /api/watchlist`：获取自选列表结构（分组和股票代码）
- `POST /api/watchlist`：向自选分组添加股票代码
- `DELETE /api/watchlist/{symbol}`：从自选列表中移除股票代码
- `PUT /api/watchlist/{symbol}/alias`：更新股票别名
- `POST /api/groups`：创建新的自选分组
- `PUT /api/watchlist`：更新整个自选列表结构（用于重新排序）

**依赖**：FastAPI, pandas, pandas-ta, yfinance, pyarrow (用于 Parquet), uvicorn

### 前端 (`/frontend`)

**框架**：React 19 + TypeScript + Vite

**关键库**：
- **UI**：Tailwind CSS 4, framer-motion (动画), lucide-react (图标)
- **图表**：lightweight-charts (TradingView 风格图表)
- **拖拽**：@dnd-kit/core, @dnd-kit/sortable

**核心组件**：
- `App.tsx`：主应用，包含自选分组、拖拽排序及股票搜索
- `ChartModal.tsx`：全屏图表弹窗，采用 5 栏堆叠布局（价格/OHLC, RSI, KDJ, MACD, ATR），支持十字线和时间轴同步，具有磁力模式的响应式移动端布局
- `StatusBadge.tsx`：趋势/信号状态的可视化指示徽章
- `StockGroup.tsx`：支持拖拽的可折叠分组组件

**状态管理**：React hooks (useState, useEffect, useMemo) - 无外部状态管理库

**API 客户端**：`utils.ts` 中的工具函数处理所有后端通信

### Docker 部署

**网络模式**：两个容器均使用 `host` 网络模式，以简化通信

**后端容器**：
- 基础镜像：安装了 `uv` 的 `python:3.12-slim`
- 运行 4 个 uvicorn 工作进程
- 为中国网络访问配置了 HTTP 代理
- 挂载卷：`./backend/data` 用于持久化缓存

**前端容器**：
- 多阶段构建：Node.js 构建 → Nginx 托管
- Nginx 将 `/api/*` 请求代理至 `http://127.0.0.1:8000`
- 托管来自 `/usr/share/nginx/html` 的静态文件

## 开发工作流

### 添加新的技术指标

1. 在 `analysis.py`（顶部区域）将参数定义为常量
2. 在 `_calculate_indicators()` 函数中计算指标（使用 pandas-ta）
3. 在 `main.py` 的 `StockResponse` 模型中添加字段
4. 在 `frontend/src/types.ts` 中更新 TypeScript 类型
5. 在 `ChartModal.tsx` 中渲染指标（添加新的图表栏或叠加层）

### 修改图表布局

图表弹窗使用 5 栏堆叠布局，具有同步的时间轴和十字线：
- 价格图表 (OHLC + EMA + BOLL)
- RSI 面板
- KDJ 面板
- MACD 面板
- ATR 面板

每个图表都使用 lightweight-charts 的 `createChart()` 创建。同步通过共享的 `syncHandler` 函数处理，协调所有图表的十字线移动。

### 自选列表数据结构

```typescript
{
  id: string,           // 分组的 UUID
  name: string,         // 显示名称
  symbols: [            // 股票数组
    {
      symbol: string,   // 代码 (例如 "AAPL")
      alias: string     // 自定义名称 (例如 "苹果")
    }
  ],
  collapsed: boolean    // UI 状态
}
```

存储在 `backend/watchlist.json` 中，支持从旧格式自动迁移。

## 交易系统背景

此应用实现了一个基于以下内容的趋势跟踪系统：
- **趋势方向**：EMA20 与 EMA50 的相对位置
- **趋势强度**：ADX > 25 表示存在趋势市场
- **入场时机**：4 小时图回调至 EMA 线并出现反转形态
- **风险管理**：使用 1.5× ATR 的动态止损

系统设计用于每日两次监控（午餐：12:00-13:00，晚上：21:00-22:00），而非持续的日内交易。

## 重要事项

- **yfinance API**：下载速度受限以避免频率限制（rate limiting）。请积极利用缓存。
- **时区**：市场数据时间戳在显示时可能需要转换
- **指标计算**：pandas-ta 的列名因版本而异（使用前缀匹配）
- **移动端支持**：ChartModal 具有响应式断点和针对触摸优化的交互
- **线程安全**：添加新的数据获取逻辑时，指标计算请使用 `get_symbol_lock()`，yfinance 下载请使用 `global_download_lock`
