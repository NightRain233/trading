---
name: analyze
description: Use when the user asks to analyze a specific stock or ETF with the project's trading indicators, entry timing, action recommendation, and invalidation risks.
---

# /analyze — Deep Stock Analysis

Analyze a specific stock or ETF using all available indicators.

**Steps:**
1. Ask the user which symbol (if not provided)
2. Run: `uv run python scripts/trading_analysis_helper.py --api-base http://8.153.71.148/api --query stock --symbol <SYMBOL>`
3. If backend not reachable on remote, try local: `--api-base http://127.0.0.1:8000/api`
4. Interpret the results using the trading-analysis skill:
   - Trend: EMA20 vs EMA50, SuperTrend daily+weekly
   - Strength: ADX > 25?
   - Momentum: RSI 7/14/21
   - Volatility: BOLL width, ATR
   - Entry signals: BB breakout/pullback
   - Opportunity stage: is this a good time to act?
5. Present findings with a clear verdict and concrete action items
6. Mention risks: what would invalidate the trade

**Output format:**
- 1-line verdict at the top
- Key numbers in a compact table
- Reasoning (3-5 bullet points)
- Action recommendation
- Risk factors
