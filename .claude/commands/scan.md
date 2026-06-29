# /scan — Market-wide SuperTrend Deep Scan

Scan all watchlist symbols with quality indicators, smart filtering, and market environment context.

**Steps:**
1. Run: `uv run python scripts/trading_analysis_helper.py --api-base http://8.153.71.148/api --query scan --grouped`
2. Present the **Market Environment** section first — this sets the tone for everything else.
   - Show 5 indices (上证, 沪深300, 中证500, 科创50, 中证2000) in a compact table
   - Each with: direction, ADX, RSI(21), MACD direction, KDJ
   - Provide a 1-line overall tone assessment
3. Present findings organized by priority:

   - 🔥 **新仓候选** (new_entries) — show ALL, never collapse
   - ⚠️ **逼近变盘** (flip_proximity) — show ALL (within 0.5 ATR of ST, can flip any day)
   - 🛡️ **持仓/风控** (position_mgmt) — show ALL
   - 👀 **预备观察** (prepare_watch) — show top 5 closest to flipping, collapse rest as "其余 X 个略"
   - 📈 **趋势延续 — 值得关注** (background) — sorted by ADX descending; these passed the "worthy" filter:
     - Within 2 ATR of ST (pullback near support)
     - OR ADX > 35 (strong trend)
     - OR RSI < 50 (pullback in uptrend)
     - OR trend age < 10 days (fresh trend)
     - OR extreme extension > 20% from ST
   - 📦 **趋势平稳** (background_quiet) — collapsed count only; "其余 X 个趋势平稳，持有不动"
     - Only mention specific names if user asks
   - 📋 **其他** (other_actionable) — if any

4. For each displayed symbol, use compact format:
   ```
   SYMBOL Alias  方向(age)  ADXxx  RSIxx  MACD↑/↓  Kxx  距x.xATR  周xw
   ```
   - Add a brief note only if there's something actionable (e.g. "回调接近支撑", "MACD 刚死叉")
   - Don't narrate symbols that are simply holding

5. Highlight the top 3-5 most actionable items with concise reasoning.

6. Summarize: "Today's key takeaway is..."

**Smart filtering rules:**
- `new_entries`, `flip_proximity`, `position_mgmt`: always show ALL
- `prepare_watch`: show top 5 (closest to ST), collapse rest
- `background`: show only "worthy" ones (filtered by helper). These are sorted by ADX desc.
- `background_quiet`: collapsed count only. DON'T list individual symbols unless user asks.
- If a symbol appears in multiple scans/conversations, elevate its importance.

**Quality tags reference:**
- ADX: >35 = strong trend 🔥, 25-35 = trending, <25 = weak/choppy ⚠️
- RSI(21): >75 = overbought, <45 = oversold (in uptrend this is a buy zone)
- MACD dir: ↑ = expanding (bullish momentum), ↓ = contracting (weakening), → = flat
- KDJ: K>80 = overbought zone, K<20 = oversold zone
- Distance ATR: <1 = very close (can flip), 1-2 = pullback zone, 2-3 = extended, >3 = very extended

**Tips:**
- Use `--api-base` to switch between local/remote
- For stale data, suggest `?force=true` on the API or `make dev-be` locally
- Cross-reference with portfolio strategies: does any scan signal conflict with current positions?
- Market environment overrides individual signals: if 上证 is weak, all bullish signals get discounted
