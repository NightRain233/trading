---
name: trading-analysis
description: Deep interactive analysis of SuperTrend signals, individual stocks, and portfolio strategies. Use when the user wants to analyze specific stocks, investigate signals, review portfolio performance, or do trading research. Complements the OpenClaw daily brief.
---

# Trading Deep Analysis

## When to Use

Invoke this skill when the user asks to:
- Analyze a specific stock/ETF in detail ("分析一下 510300", "看看 NVDA")
- Investigate SuperTrend signals ("为什么 XXX 被标记为买入候选")
- Review portfolio strategy performance ("组合最近怎么样")
- Do cross-market analysis ("A 股和美股对比")
- Any non-trivial trading analysis task

## Architecture

The project has a FastAPI backend serving these key endpoints. Always prefer calling the live API over reading cached files — the API computes indicators fresh.

### Primary Data Endpoints

| Endpoint | Use | Example |
|----------|-----|---------|
| `GET /api/supertrend/scan?force=true` | Full SuperTrend matrix (all watchlist symbols) | Market-wide scan |
| `GET /api/quote/{symbol}` | Single stock: indicators, BB signals, weekly/daily charts | Deep dive |
| `GET /api/portfolio-strategies` | List paper strategies + bootstrap status | Portfolio overview |
| `GET /api/portfolio-strategies/{id}/snapshot` | Full strategy state: NAV, weights, signals | Strategy check |
| `GET /api/portfolio-strategies/{id}/nav` | NAV time series | Performance history |

### API Base

```bash
# Local
API_BASE="http://127.0.0.1:8000/api"
# Remote (production)
API_BASE="http://8.153.71.148/api"
```

Fetch data with `curl` or the helper script:

```bash
uv run python scripts/trading_analysis_helper.py \
  --api-base http://8.153.71.148/api \
  --query stock --symbol 510300.SS

uv run python scripts/trading_analysis_helper.py \
  --api-base http://8.153.71.148/api \
  --query scan --grouped

uv run python scripts/trading_analysis_helper.py \
  --api-base http://8.153.71.148/api \
  --query portfolio --strategy btc_supertrend_satellite
```

## Analysis Workflows

### Workflow 1: Single Stock Deep Dive

When analyzing a specific symbol, fetch and interpret ALL available signals:

1. Call `/api/quote/{symbol}` to get the full indicator suite
2. Interpret in this order:
   - **Trend**: EMA20 vs EMA50 positioning → bull/bear trend
   - **Strength**: ADX > 25 → trending, ADX < 20 → ranging
   - **SuperTrend**: Daily + Weekly state (bull/bear/flip)
   - **Momentum**: RSI 7/14/21 multi-timeframe
   - **Volume**: MACD histogram direction and divergence
   - **Volatility**: BOLL width (squeeze = impending move, wide = active)
   - **Entry timing**: Weekly BB breakout/pullback signals
3. Cross-reference: do daily and weekly indicators agree or conflict?
4. Give a clear verdict with reasoning

Key questions to answer per stock:
- Is the trend clear or ambiguous?
- Is this a good time to enter/add/reduce/exit?
- What's the nearest support/resistance level?
- What would invalidate the trade?

### Workflow 2: Market Scan & Ranking

When scanning the market:

1. Call `/api/supertrend/scan?force=true` for fresh data
2. Group by the standard workflow categories:
   - **新仓候选**: Weekly bull + daily just flipped → highest priority
   - **预备观察**: Weekly bull + daily bear → waiting list
   - **持仓/风控**: Position management alerts
   - **趋势延续**: Already in bull trend
3. Within each group, rank by `distanceToSupertrendPct` (closer to ST line = better entry)
4. Cross-reference with RSI (oversold near ST support = ideal)

### Workflow 3: Portfolio Strategy Health Check

1. Call `/api/portfolio-strategies` to list active strategies
2. For each paper-enabled strategy, call the snapshot endpoint
3. Check:
   - **NAV**: cumulative return, recent drawdown
   - **Weights**: current vs desired, any pending rebalance
   - **State**: READY = has signal, NOT_DUE = waiting, BLOCKED = data issue
   - **BTC Satellite specific**: Is BTC in or out? What's the SuperTrend direction?
   - **Theme Alpha specific**: Defense mode? Which LVT assets are selected?

### Workflow 4: Cross-Reference Analysis

When comparing or validating signals:

1. Check if SuperTrend and BB signals agree
2. Verify daily/weekly alignment (周线定方向，日线定时机)
3. Look for divergence: price making new high but RSI not confirming
4. Check volume: is the move supported by volume?

## Important Trading Rules

- **周线定方向，日线定时机**: Weekly chart determines the trade direction; daily chart determines entry timing
- SuperTrend 翻多 ≠ 立即买入 — wait for pullback to ST support
- 预选观察 ≠ 不要买 — these are candidates once daily flips bull
- ST support break = exit signal, no exceptions
- Use ATR for stop placement: stop = entry - 1.5× ATR

## Output Format

When presenting analysis:
1. Start with a 1-line verdict
2. Show key numbers in a compact table
3. Explain the reasoning
4. List concrete action items
5. Mention risks and what would invalidate the thesis

Keep it actionable. The user wants to make decisions, not read an academic paper.
