# AGENTS.md

Guidance for coding agents (Claude Code reads it through `CLAUDE.md`). The user-facing overview is [README.md](README.md); the docs index is [docs/README.md](docs/README.md).

## What this project is

A personal market dashboard for one non-technical investor. It runs frozen strategy rules on paper accounts, keeps a ledger, renders the pages, and produces a daily push. It never places real orders. Research and backtests live in the sibling repo `../xquant`.

**Talk to the user in plain Chinese**, conclusions first, with analogies rather than jargon.

### The primary strategy (decided 2026-10-18)

`btc_supertrend_satellite`: 510300.SS / 513100.SS / 518880.SS weighted by 20-session inverse volatility (checked every 10 XSHG sessions) plus a 7.5% BTC sleeve switched by a daily SuperTrend(10, 3, SMA ATR) on check days, executed at the next close. Everything else in `backend/portfolio_strategies/registry.py` is a comparison account.

- Do not add strategies, sleeves or complexity unless the user asks; first ask "does this serve the primary strategy?"
- No bonds inside the strategy: the user's idle cash is the buffer.
- Technical analysis (Weinstein stages, the SuperTrend scan) is a learning layer and never changes primary holdings. Frozen research: A-share timing never beat buy-and-hold; Weinstein helps on US indices; daily ST suits BTC; gold was not tested.

## Commands

```bash
make install          # backend (uv) + frontend (pnpm)
make dev              # frontend :5173, backend :8000
```

Running the backend by hand (Yahoo needs a proxy in China):

```bash
cd backend
BACKGROUND_PREWARM_ENABLED=false https_proxy=http://127.0.0.1:7890 http_proxy=http://127.0.0.1:7890 \
  no_proxy=127.0.0.1,localhost,free-api.tickflow.org .venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

Tests:

```bash
cd backend && PYTHONPATH=. uv run --frozen pytest -q     # or .venv/bin/python -m pytest
cd frontend && node --test test/*.mjs && pnpm build && pnpm exec eslint src
```

- Always pass `--frozen` to `uv run`: the configured Chinese mirror otherwise rewrites `backend/uv.lock`. If it changes anyway, `git checkout -- backend/uv.lock`.
- `backend/tests/conftest.py` blocks the background refresh executor; a full run must not write anything under `backend/data/`.
- Pre-existing lint errors live in untouched legacy components (`ChartModal`, `MiniChart`, `SortableGroup`, …) and `App.tsx` `any`s; do not count them against new work, and do not add new ones.

## Architecture

### Backend (`backend/`, FastAPI)

| Area | Files |
|---|---|
| Market data and cache | `analysis.py` (facade), `analysis_data.py` (fetch, indicators), `analysis_cache.py` (memory/disk cache, swr refresh), `data_source_guard.py` |
| Weinstein view | `analysis_weinstein.py`: 30-week SMA stage with a 2% band, 26-week RS vs market benchmark, Bollinger state, volume ratio, `rule_state` |
| SuperTrend scan (learning layer) | `supertrend_scan_policy.py`, `supertrend_alerts.py`, `/api/supertrend/scan` |
| Paper portfolios | `portfolio_strategies/` (`registry.py`, `schedules.py`, `btc_satellite.py`, `service.py`, ledgers, next-open engine) |
| History replay | `/api/history-trades*`, cache in `backtest_results/` (git-ignored) |

Endpoints used by the redesigned pages: `/api/portfolio-strategies/{id}/snapshot|nav|rebalance-diff|btc-trend`, `/api/quotes/batch`, `/api/quote/{symbol}?decision=false` (chart-only, skips the slow decision scan), `/api/weinstein/scan` (cached until a weekly parquet changes). Full list: `http://127.0.0.1:8000/docs`.

### Frontend (`frontend/`, React 19 + Vite + Tailwind 4)

- `components/AppShell.tsx`: rail on desktop, bottom tab bar on phones, theme toggle.
- Pages: `PortfolioStrategiesPage`, `MarketPage`, `WeeklyScanPage`, `HistoryTradesPage`, `SupertrendPage`, `RsRotationPage`. The watchlist "管理自选" view is still the old dark UI (wrapped in `.ui-legacy`) by the user's choice.
- `design.css` holds the tokens (`--ui-*`), dark-first with light values under `prefers-color-scheme` and `[data-theme]`. Use tokens, never literal colours. A-share convention: **rise red, fall green**.
- Charts: hand-written SVG on the new pages; lightweight-charts elsewhere via `useChartTheme()` (`chartTheme.ts`).
- Pure helpers are `@ts-check` `.js` files with `.d.ts` declarations, tested with `node --test` (`portfolioStrategies.js`, `marketView.js`, `swrCache.js`, …).
- System fonts only; do not add web-font imports (they block first paint in China).

### Skills and agents

`.agents/skills/` is the single source (Claude Code reads it via the `.claude/skills` symlink): `scan`, `analyze`, `portfolio-daily-brief`, `fupan`, plus `shared/market-rules.md` (the house view every skill reads first). Data comes from `scripts/trading_analysis_helper.py --query weekly|brief|portfolio|overview`. The daily push is `scripts/openclaw_supertrend_alerts.py --mode daily-brief`; its assistant prompt is `scripts/openclaw_daily_brief_prompt.md` (pasted into Hermes by the user).

## 复盘记录

分析任何标的之前，先读 `reviews/README.md`，再看最近几天的复盘、`reviews/持仓总览.md` 和相关品种页（Obsidian 格式，wikilink 互联）。复盘里的旧价格和止损不能当作当前事实。

## Rules

- Never write the production server address, personal paths or credentials into tracked files; use `Makefile.local` (git-ignored) or `TRADING_API_BASE`.
- Do not activate, refresh or mutate paper accounts on the production server without the user's explicit request. Local activation only touches the local dev database.
- Deploying (`make deploy-*`) is the user's call.
- Keep dated research reports as written; add a note instead of rewriting their conclusions.
