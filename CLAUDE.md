# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A trend trading system with real-time stock analysis and visualization. The application provides technical analysis based on EMA (Exponential Moving Average), ADX (Average Directional Index), MACD, RSI, and other indicators to support trend-following trading strategies.

**Architecture**: Full-stack application with Python FastAPI backend and React TypeScript frontend, containerized with Docker.

## Commands

### Development

```bash
# Install all dependencies (frontend + backend)
make install

# Run full stack locally (both frontend and backend in parallel)
make dev

# Run frontend only (Vite dev server on port 5173)
make dev-fe

# Run backend only (uvicorn on port 8000)
make dev-be
```

### Build & Deploy

```bash
# Build frontend production bundle
make build-fe

# Build Docker images
make docker-build

# Start containers (detached mode)
make up

# Stop containers
make down

# View logs
make logs

# Restart containers
make restart

# Deploy to remote server (uses rsync)
make deploy
```

### Package Management

- **Frontend**: Uses `pnpm` (required, not npm/yarn)
- **Backend**: Uses `uv` for Python dependency management (replaces pip/venv)

## Technical Architecture

### Backend (`/backend`)

**Framework**: FastAPI with uvicorn ASGI server

**Core Files**:
- `main.py`: FastAPI application with REST API endpoints and watchlist management
- `analysis.py`: Facade module — re-exports all symbols from sub-modules and contains top-level functions (`analyze_stock`, `batch_fetch_and_update`, `analyze_stock_summary`)
- `analysis_constants.py`: All configuration constants (cache durations, indicator periods, thresholds)
- `analysis_cache.py`: Thread locks, in-memory cache, async/sync refresh workers, `get_cached_batch_summaries`
- `analysis_data.py`: Data fetching (yfinance), merging, and indicator calculation (`_calculate_daily_indicators`, `_calculate_weekly_indicators`, `fetch_stock_data`)
- `analysis_strategy.py`: Resonance strategy signals (`_evaluate_resonance_strategy_v2`, `_evaluate_resonance_exit_no_position`, etc.)
- `analysis_candles.py`: Candlestick construction (`_build_candles`, `_build_mini_candles`)
- `backtest.py`: Backtesting engine — single-symbol backtest, portfolio simulation, RS rotation strategy
- `strategy_versions.py`: Strategy version registry (entry/exit parameters per version ID)

**Key Features**:
- **Watchlist Management**: Group-based organization with drag-and-drop support, symbol aliases
- **Technical Indicators**: EMA20/50, ADX(14), RSI (7/14/21 periods), MACD, BOLL, KDJ, ATR
- **Data Caching**: Parquet-based caching (1-hour cache duration, 2-year retention)
- **Thread Safety**: Fine-grained locking per symbol for indicator calculation, global lock for yfinance downloads
- **Weekly Data**: Resampled weekly candles and indicators for longer-term trend analysis

**API Endpoints**:
- `GET /api/quote/{symbol}`: Fetch detailed stock analysis with all indicators
- `GET /api/watchlist`: Get watchlist structure (groups and symbols)
- `POST /api/watchlist`: Add symbol to watchlist group
- `DELETE /api/watchlist/{symbol}`: Remove symbol from watchlist
- `PUT /api/watchlist/{symbol}/alias`: Update symbol alias
- `POST /api/groups`: Create new watchlist group
- `PUT /api/watchlist`: Update entire watchlist structure (for reordering)

**Dependencies**: FastAPI, pandas, pandas-ta, yfinance, pyarrow (for Parquet), uvicorn

### Frontend (`/frontend`)

**Framework**: React 19 + TypeScript + Vite

**Key Libraries**:
- **UI**: Tailwind CSS 4, framer-motion (animations), lucide-react (icons)
- **Charts**: lightweight-charts (TradingView-style charts)
- **Drag & Drop**: @dnd-kit/core, @dnd-kit/sortable

**Core Components**:
- `App.tsx`: Main application with watchlist groups, drag-and-drop reordering, stock search
- `ChartModal.tsx`: Full-screen chart modal with 5-panel stacked layout (Price/OHLC, RSI, KDJ, MACD, ATR), synchronized crosshairs and time axis, responsive mobile layout with magnet mode
- `StatusBadge.tsx`: Visual indicator badges for trend/signal status
- `StockGroup.tsx`: Collapsible group component with drag-and-drop support

**State Management**: React hooks (useState, useEffect, useMemo) - no external state library

**API Client**: Utility functions in `utils.ts` for all backend communication

### Docker Deployment

**Network Mode**: Both containers use `host` network mode for simplified communication

**Backend Container**:
- Base: `python:3.12-slim` with `uv` installed
- Runs with 4 uvicorn workers
- HTTP proxy configured for China network access
- Volume mount: `./backend/data` for persistent cache

**Frontend Container**:
- Multi-stage build: Node.js build → Nginx serve
- Nginx proxies `/api/*` requests to `http://127.0.0.1:8000`
- Serves static files from `/usr/share/nginx/html`

## Development Workflow

### Adding New Technical Indicators

1. Define parameters as constants in `analysis_constants.py`
2. Calculate indicator in `_calculate_daily_indicators()` in `analysis_data.py`
3. Add fields to `StockResponse` model in `main.py`
4. Update TypeScript types in `frontend/src/types.ts`
5. Render indicator in `ChartModal.tsx` (add new chart panel or overlay)

### Modifying Chart Layout

The chart modal uses a 5-panel stacked layout with synchronized time axis and crosshairs:
- Price chart (OHLC + EMA + BOLL)
- RSI panel
- KDJ panel
- MACD panel
- ATR panel

Each chart is created with `createChart()` from lightweight-charts. Synchronization is handled via shared `syncHandler` function that coordinates crosshair movement across all charts.

### Watchlist Data Structure

```typescript
{
  id: string,           // UUID for group
  name: string,         // Display name
  symbols: [            // Array of stocks
    {
      symbol: string,   // Ticker (e.g., "AAPL")
      alias: string     // Custom name (e.g., "苹果")
    }
  ],
  collapsed: boolean    // UI state
}
```

Stored in `backend/watchlist.json` with automatic migration from legacy formats.

## Trading System Context

This application implements a trend-following system based on:
- **Trend Direction**: EMA20 vs EMA50 positioning
- **Trend Strength**: ADX > 25 indicates trending market
- **Entry Timing**: 4-hour chart pullbacks to EMA lines with reversal patterns
- **Risk Management**: Dynamic stops using 1.5× ATR

The system is designed for twice-daily monitoring (lunch: 12:00-13:00, evening: 21:00-22:00) rather than continuous intraday trading.

### Backtesting

Run a backtest from the command line:
```bash
cd backend
uv run python backtest.py --symbols 510300.SS 510050.SS --strategy-version resonance_v2_atr_1_5 --start 2023-01-01
```

Key functions in `backtest.py`:
- `run_backtest_for_symbol`: single-symbol long-only backtest (signal → next-bar entry → stop/target/exit)
- `simulate_rs_rotation_portfolio`: momentum rotation — ranks symbols by `lookback_bars` return, rebalances every `rebalance_days` trading days, holds top `top_n`
- `summarize_backtest_report`: aggregates trades into report with `byPoolType`, `byAssetClass`, `byYear`, `diagnostics`, portfolio simulation
- `annotate_relative_strength`: adds RS rank/bucket to each trade at entry date

**RS Rotation presets** (used by the frontend backtest page):
- `rs_rotation_a_share`: A-share ETFs, monthly MACD filter on CSI300
- `rs_rotation_global`: A-share + SPY/QQQ/BTC-USD/GC=F, per-class monthly MACD filters

**Backtest results** are saved to `backend/backtest_results/` (not the repo root).

**Regression tests** in `tests/test_backtest.py` (`RsRotationRegressionTests`) require local parquet data covering 2015–2022. They auto-skip when the cache only holds recent data (< 2 years history).

## Important Notes

- **yfinance API**: Downloads are throttled to avoid rate limiting. Cache aggressively.
- **Time Zones**: Market data timestamps may require conversion for display
- **Indicator Calculation**: pandas-ta column names vary by version (use prefix matching)
- **Mobile Support**: ChartModal has responsive breakpoints and touch-optimized interactions
- **Thread Safety**: When adding new data fetching, use `get_symbol_lock()` for indicator calculation and `global_download_lock` for yfinance downloads
