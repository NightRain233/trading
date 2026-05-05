# Strategy Continuation Status

Last updated: 2026-05-05

## What Is Done

- Resonance v2 now produces a risk-aware opportunity model:
  - `poolType`
  - `entryScore`
  - `riskScore`
  - `riskLevel`
  - `stopPrice`
  - `riskPercent`
  - `targetPrice`
  - `rewardRiskRatio`
- Strategy versions live in `backend/strategy_versions.py`.
- Backtest engine lives in `backend/backtest.py`.
- Backtest tests live in `backend/tests/test_backtest.py`.
- Strategy version tests live in `backend/tests/test_strategy_versions.py`.
- ETF universes live in `backend/universes/`.
- A-share ETF strategy version uses CSI 300 (`000300.SS`) as the market filter.
- Two stricter A-share ETF strategy versions were added:
  - `resonance_v2_atr_2_0_csi300_strict_bullish_etf_established`
  - `resonance_v2_atr_2_0_csi300_entry_buffer_1_0_etf_established`
- Two v3 A-share ETF strategy experiments were added:
  - `resonance_v3_trend_runner_csi300_entry_buffer_1_0_etf_established`
  - `resonance_v3_atr_2_0_8_0_csi300_entry_buffer_1_0_etf_established`
- Two v4 relative-strength A-share ETF strategy experiments were added:
  - `resonance_v4_rs_top20_csi300_entry_buffer_1_0_etf_established`
  - `resonance_v4_rs_top50_csi300_entry_buffer_1_0_etf_established`
- Backtest JSON reports now include:
  - `summary`
  - `byPoolType`
  - `byAssetClass`
  - `byYear`
  - `symbolContribution`
  - `diagnostics`
  - `diagnosticsByYear`
  - `portfolio`
  - `markToMarketPortfolio`
  - `benchmark`
  - `marketBenchmark`
- Trades can now be annotated with entry-date relative strength:
  - `relativeStrengthPct`
  - `relativeStrengthRank`
  - `relativeStrengthUniverseSize`
  - `relativeStrengthBucket`

## Latest A-Share ETF Backtest

Command:

```bash
cd backend
uv run python -m backtest \
  --universe-file universes/a_share_etf_core.json \
  --strategy-version resonance_v2_atr_2_0_csi300_bullish_etf_established \
  > backtest_a_share_etf_core_resonance_v2_atr_2_0_csi300_bullish_etf_established.json
```

Output file:

```text
backend/backtest_a_share_etf_core_resonance_v2_atr_2_0_csi300_bullish_etf_established.json
```

Key result after fixing the market-symbol override:

- `marketFilter`: `bullish_ema`
- `marketSymbol`: `000300.SS`
- trades: `76`
- win rate: `64.47%`
- average return per trade: `+2.89%`
- max drawdown: `12.94%`
- missing symbols: none

Year split:

- 2024: 3 trades, 0% win rate, average `-3.30%`
- 2025: 67 trades, 73.13% win rate, average `+3.78%`
- 2026: 6 trades, 0% win rate, average `-4.02%`

Important diagnostic:

- Trades exiting while the market stayed `bullish_ema` performed well.
- Trades exiting during `bullish_trend_pullback` performed poorly.
- This suggests the next strategy improvement should focus on avoiding entries
  when the broad market is already losing short-term strength.

## Latest Strategy Comparison

Same universe: `backend/universes/a_share_etf_core.json`.

| Strategy | Trades | Win Rate | Avg Trade | Closed Portfolio | MTM Portfolio | MTM DD | Equal Weight B&H |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `resonance_v2_atr_2_0_csi300_bullish_etf_established` | 76 | 64.47% | +2.89% | +23.23% | not rerun with MTM | n/a | +42.87% |
| `resonance_v2_atr_2_0_csi300_entry_buffer_1_0_etf_established` | 59 | 71.19% | +3.53% | +26.87% | +26.12% | 5.04% | +42.87% |
| `resonance_v3_trend_runner_csi300_entry_buffer_1_0_etf_established` | 77 | 61.04% | +1.12% | +8.25% | not rerun with MTM | n/a | +42.87% |
| `resonance_v3_atr_2_0_8_0_csi300_entry_buffer_1_0_etf_established` | 47 | 72.34% | +4.58% | +25.18% | +24.44% | 4.82% | +42.87% |
| `resonance_v4_rs_top20_csi300_entry_buffer_1_0_etf_established` | 20 | 85.00% | +5.70% | +20.04% | +19.49% | 4.22% | +42.87% |
| `resonance_v4_rs_top50_csi300_entry_buffer_1_0_etf_established` | 40 | 70.00% | +3.99% | +25.27% | +24.73% | 3.77% | +42.87% |

Interpretation:

- Requiring CSI 300 to remain bullish at the entry date helps, but it is not
  enough to avoid the 2026 losses.
- Requiring entry-day CSI 300 close to be at least 1% above EMA20 filters out
  the weak 2026 entries in the current sample.
- `warn_exit` v3 is too tight. It exits on normal EMA20 pullbacks and performs
  much worse than buffered v2.
- `ATR 2.0/8.0` v3 improves average return per trade, but it still does not
  beat buffered v2 on the current closed-trade portfolio simulation.
- Relative strength is useful as a diagnostic: top20 trades have much stronger
  average trade return, but the top20 strategy has too few trades to improve
  total portfolio return.
- The top50 relative-strength strategy improves drawdown versus buffered v2,
  but it still does not improve total mark-to-market return.
- All current active strategies still underperform same-window buy-and-hold in
  the A-share ETF universe. This is now visible directly in the report.

Portfolio note:

- `portfolio` currently uses a closed-trade equal-slot simulation with a default
  `--portfolio-max-positions 5`.
- It realizes P/L on trade exit dates and respects overlapping-position slots.
- `markToMarketPortfolio` is now the daily mark-to-market version. It marks open
  positions with daily closes and realizes the backtest trade return on exit.

## Commands

Fill or refresh cache for the A-share ETF universe plus CSI 300:

```bash
cd backend
uv run python - <<'PY'
from analysis import batch_fetch_and_update
from backtest import load_universe_symbols

symbols = load_universe_symbols("universes/a_share_etf_core.json")
symbols.append("000300.SS")
result = batch_fetch_and_update(symbols)
print(f"cached={len(result)} requested={len(symbols)}")
print("missing=", sorted(set(symbols) - set(result)))
PY
```

Run the same A-share ETF backtest again:

```bash
cd backend
uv run python -m backtest \
  --universe-file universes/a_share_etf_core.json \
  --strategy-version resonance_v2_atr_2_0_csi300_bullish_etf_established \
  > backtest_a_share_etf_core_resonance_v2_atr_2_0_csi300_bullish_etf_established.json
```

Run the buffered A-share ETF strategy:

```bash
cd backend
uv run python -m backtest \
  --universe-file universes/a_share_etf_core.json \
  --strategy-version resonance_v2_atr_2_0_csi300_entry_buffer_1_0_etf_established \
  > backtest_a_share_etf_core_resonance_v2_atr_2_0_csi300_entry_buffer_1_0_etf_established.json
```

Run the v3 wide-target A-share ETF strategy:

```bash
cd backend
uv run python -m backtest \
  --universe-file universes/a_share_etf_core.json \
  --strategy-version resonance_v3_atr_2_0_8_0_csi300_entry_buffer_1_0_etf_established \
  > backtest_a_share_etf_core_resonance_v3_atr_2_0_8_0_csi300_entry_buffer_1_0_etf_established.json
```

Run the v3 wide-target A-share ETF strategy with a longer hold window:

```bash
cd backend
uv run python -m backtest \
  --universe-file universes/a_share_etf_core.json \
  --strategy-version resonance_v3_atr_2_0_8_0_csi300_entry_buffer_1_0_etf_established \
  --max-hold-days 60 \
  > backtest_a_share_etf_core_resonance_v3_atr_2_0_8_0_csi300_entry_buffer_1_0_etf_established_60d.json
```

Run the v4 relative-strength top50 A-share ETF strategy:

```bash
cd backend
uv run python -m backtest \
  --universe-file universes/a_share_etf_core.json \
  --strategy-version resonance_v4_rs_top50_csi300_entry_buffer_1_0_etf_established \
  > backtest_a_share_etf_core_resonance_v4_rs_top50_csi300_entry_buffer_1_0_etf_established.json
```

Inspect the main result:

```bash
cd backend
uv run python - <<'PY'
import json
from pathlib import Path

p = Path("backtest_a_share_etf_core_resonance_v2_atr_2_0_csi300_bullish_etf_established.json")
data = json.loads(p.read_text())
print(json.dumps({
    "marketFilter": data["marketFilter"],
    "marketSymbol": data["marketSymbol"],
    "summary": data["summary"],
    "portfolio": data["portfolio"],
    "markToMarketPortfolio": {
        "totalReturnPct": data["markToMarketPortfolio"]["totalReturnPct"],
        "maxDrawdownPct": data["markToMarketPortfolio"]["maxDrawdownPct"],
        "acceptedTradeCount": data["markToMarketPortfolio"]["acceptedTradeCount"],
        "skippedTradeCount": data["markToMarketPortfolio"]["skippedTradeCount"],
    },
    "benchmark": {
        "symbolCount": data["benchmark"]["symbolCount"],
        "equalWeightReturnPct": data["benchmark"]["equalWeightReturnPct"],
        "bestSymbol": data["benchmark"]["bestSymbol"],
        "worstSymbol": data["benchmark"]["worstSymbol"],
    },
    "marketBenchmark": data["marketBenchmark"],
    "byYear": data["byYear"],
    "lossSummary": data["diagnostics"]["lossSummary"],
    "byRelativeStrengthBucket": data["diagnostics"]["byRelativeStrengthBucket"],
    "byMarketRegimeAtExit": data["diagnostics"]["byMarketRegimeAtExit"],
    "worstTrades": data["diagnostics"]["worstTrades"][:8],
}, ensure_ascii=False, indent=2))
PY
```

Run backend tests:

```bash
cd backend
uv run python -m unittest discover -s tests -v
```

Run frontend build:

```bash
cd frontend
npm run build
```

## Not Done Yet

- No UI page for backtest reports yet.
- No walk-forward or parameter sweep.
- No data quality dashboard.
- No structured signal reason codes.
- No position management workflow.
- No automatic report comparison between strategy versions.
- No true top-N ETF rotation allocator yet.

## Recommended Next Direction

Treat `resonance_v2_atr_2_0_csi300_entry_buffer_1_0_etf_established` as the
current live candidate, not the final strategy. Treat
`resonance_v3_atr_2_0_8_0_csi300_entry_buffer_1_0_etf_established` as a useful
experiment because it raises average trade return but does not yet improve
portfolio-level return.

Recommended next work:

- add a strategy comparison CLI so these tables do not require ad hoc scripts;
- build a top-N ETF rotation allocator instead of only filtering signal trades;
- compare across a broader A-share ETF universe, the US ETF universe, and
  explicit date ranges such as 2024, 2025, and 2026 separately.
