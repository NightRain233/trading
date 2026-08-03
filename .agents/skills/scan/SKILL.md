---
name: scan
description: Use when the user asks for a market-wide SuperTrend scan, watchlist ranking, actionable trading candidates, trend continuation, or portfolio risk alerts.
---

# /scan — Market-wide SuperTrend Deep Scan

Scan all watchlist symbols with quality indicators, smart filtering, and market environment context.

**Steps:**
1. Run: `uv run python scripts/trading_analysis_helper.py --api-base http://8.153.71.148/api --query scan --grouped`
2. Verify data dates before interpreting signals.
   - Check `latestDataDate`, `dataStale`, and `dataIntegrity` across the displayed symbols; an HTTP success is not proof that every symbol is current.
   - State the snapshot date. If dates are mixed or stale, identify the affected symbols and do not present them as current buy/risk conclusions until refreshed.
3. Present the **Market Environment** section first — this sets the tone for everything else.
   - Show 5 indices (上证, 沪深300, 中证500, 科创50, 中证2000) in a compact table
   - Each with: direction, ADX, RSI(21), MACD direction, confirmed MACD divergence when present, KDJ, distance to and direction of weekly/monthly BOLL mid, and completed-session 20-day volume ratio
   - Provide a 1-line overall tone assessment
4. Present findings organized by priority:

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

5. For each displayed symbol, use compact format:
   ```
   SYMBOL Alias  方向(age)  ADXxx  RSIxx  MACD↑/↓  Kxx  距x.xATR  周xw  周中↑/→/↓±x%  月中↑/→/↓±x%  量x.x
   ```
   - Add a brief note only if there's something actionable (e.g. "回调接近支撑", "MACD 刚死叉")
   - Append confirmed divergence compactly when present: `日MACD确认底背离（6/12→7/03，7/08确认）· 价格-4.2% · DIF抬高` or the weekly equivalent.
   - Candidate divergence (`status=candidate`) must be labelled `疑似…，右侧尚缺N根确认——仅预警，不参与决策`; never let it change grouping, ranking, or an action recommendation.
   - Don't narrate symbols that are simply holding
   - For `yellow_watch`, make the daily/weekly mismatch explicit, e.g. `日多(15) · 周空(28w)  ADX32  距1.3ATR  靠近日线支撑，等确认`.
   - For `new_entries`, `flip_proximity`, `position_mgmt`, and `yellow_watch`, add one compact structure line with actual lower/mid/upper values and mid direction: `周BOLL 下/中↑/上 · 月BOLL 下/中→/上 · 量 当前/20日均=倍数`.
   - For lower-priority background symbols, show the extra structure line only when price is outside a band, within 2% of a weekly/monthly mid, or the completed-session volume ratio is abnormal (`≤0.8` or `≥1.5`).

6. Apply weekly/monthly BOLL and volume as confirmation context, not independent trading permission:
   - `weeklyBoll` and `monthlyBoll` use 20 periods and 2 standard deviations. Use `distanceToMidPct`, `position`, `midSlopePct`, and `midDirection` to explain structure; positive mid distance means price is above the midline, while `rising/flat/falling` maps to `↑/→/↓`.
   - Above both weekly and monthly mids with flat or rising mids is a structural tailwind. Price above a falling mid is only an early recovery, not confirmed strength; below either mid is a resistance/risk flag. None of these overrides the formal “weekly direction, daily timing” entry rule.
   - An upper-band break is not automatically overbought, and a lower-band touch is not automatically a buy. Read it together with trend direction, band position, and volume.
   - Only evaluate volume when `volumeContext.sessionComplete` is `true`. Before the close it is `false`: write “量能未完成”, and do not use the partial `ratio20` for ranking, confirmation, or rejection.
   - After the close, use `volumeContext.ratio20Completed`, not raw volume or the diagnostic-only `ratio20`, for cross-symbol comparison: `≥1.5` = clearly expanding, `0.8-1.5` = normal, `≤0.8` = contracting. Confirm that `volumeContext.asOf` matches the completed session being discussed.
   - A bullish flip/breakout with expanding volume gets stronger confirmation; a pullback near support with contracting volume is healthier. A support break or bearish flip with expanding volume is a stronger risk signal.
   - Weekly/monthly bars may still be in progress. Treat their BOLL values as provisional until the respective period closes.
   - If `sampleSize < 20` or BOLL values are null, write “历史不足” and make no BOLL inference. At exactly 20 samples the bands are valid but `slopeSampleSufficient` is false, so describe the mid direction as “方向历史不足”.

7. Highlight the top 3-5 most actionable items with concise reasoning. Rank formal signal validity first, then weekly/monthly structure and volume confirmation.

8. Summarize: "Today's key takeaway is..."

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
- RSI(21): >75 = overbought, <45 = 上升趋势中的回踩观察区（不是独立买点）
- MACD dir: compare `macdHist` with `macdHistPrev`; ↑ = histogram rising (bullish momentum improving), ↓ = histogram falling (bearish momentum strengthening), → = materially flat. Use a zero-axis crossing for “金叉/死叉”; an arrow alone is not a crossover.
- MACD divergence: only `macdDivergence.*.confirmed` may be used as supporting evidence. Daily bullish divergence can improve `只观察` to `等确认`, but still requires a daily bullish flip/support confirmation. Daily bearish divergence is a risk warning, not an automatic sell. Weekly bullish divergence remains “周线未确认，跟踪不建仓” until the weekly trend turns bullish. Weekly bearish divergence downgrades new-entry priority and raises holding vigilance, while a formal exit still requires the existing ST rule. Candidate divergence is display-only.
- KDJ: K>80 = overbought zone, K<20 = oversold zone
- Distance ATR: <1 = very close (can flip), 1-2 = pullback zone, 2-3 = extended, >3 = very extended

**Tips:**
- Use `--api-base` to switch between local/remote
- For stale data, suggest `?force=true` on the API or `make dev-be` locally
- Cross-reference with portfolio strategies: does any scan signal conflict with current positions?
- Market environment overrides individual signals: if 上证 is weak, all bullish signals get discounted
