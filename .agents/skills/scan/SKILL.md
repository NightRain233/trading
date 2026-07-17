---
name: scan
description: Use when the user asks for a market-wide SuperTrend scan, watchlist ranking, actionable trading candidates, trend continuation, or portfolio risk alerts.
---

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
   - 🟡 **黄灯追踪 — 日多周空** (yellow_watch) — show ALL, never collapse
     - Include every unique symbol whose daily `state` is `bull` or `bull_flip`, weekly `weeklyState` is `bear` or `bear_flip`, and daily `adx` is at least 30.
     - Build this list from **all** `groups.*.symbols` before any display limits, including `background_quiet` and `other_actionable`; do not assume its source group is visible.
     - This is a tracking list, **not** a buy list: write “周线未确认，跟踪不建仓” in the section heading. If 上证 is `bear` or `bear_flip`, additionally write “大盘偏弱，仅跟踪，不开新仓”.
     - Sort by absolute `distanceToSupertrendAtr` ascending, then `adx` descending. State the status briefly: `≤1.5 ATR` = “靠近日线支撑，等确认”, `>1.5 ATR` = “等待回踩，避免追高”.
     - Keep any ST or other clearly high-risk symbol visible for completeness, but label its risk and never elevate it into the top actionable items.
     - A symbol leaves the section automatically once the daily trend turns bearish, the weekly trend turns bullish, or ADX falls below 30. When it leaves because the weekly trend turns bullish, let its normal group determine whether it is a new-entry candidate.
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
   - For `yellow_watch`, make the daily/weekly mismatch explicit, e.g. `日多(15) · 周空(28w)  ADX32  距1.3ATR  靠近日线支撑，等确认`.

5. Highlight the top 3-5 most actionable items with concise reasoning.

6. Summarize: "Today's key takeaway is..."

**Smart filtering rules:**
- `new_entries`, `flip_proximity`, `position_mgmt`: always show ALL
- Derive `yellow_watch` first from every returned group, deduplicate by `symbol`, and show all qualifying symbols even if they were in `background_quiet`.
- Do not repeat a yellow symbol in `background`, `background_quiet`, or `other_actionable`. If it also belongs to an always-show group, keep the mandatory item but use a short “🟡 黄灯追踪同上” reference instead of duplicating its full indicator line.
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
