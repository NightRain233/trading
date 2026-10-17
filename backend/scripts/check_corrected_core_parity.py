"""Compare the persisted trading ledger against frozen corrected research CSVs.

Never imports xquant's simulation engine. Accounts are created only in a
temporary SQLite database. No downloads, broker calls or existing account writes.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sys
import tempfile

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from portfolio_strategies.corrected_core import CORRECTED_CORE_ID, CORE_SYMBOLS
from portfolio_strategies.ledger import connect
from portfolio_strategies.service import PortfolioStrategyService


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(data_dir: Path, research_dir: Path) -> dict:
    result = {"strategyId": CORRECTED_CORE_ID, "version": "2.0.0", "accounts": {}, "research_csv_sha256": {},
              "boundary": "temporary paper accounts, fractional shares, literal 1bp commissions, no premium filter; frozen research event coverage"}
    for mode in ("lump", "dca"):
        daily_path = research_dir/f"account_corrected_Three_{mode}.csv"
        fills_path = research_dir/f"fills_corrected_Three_{mode}.csv"
        expected = pd.read_csv(daily_path, index_col=0, parse_dates=True)
        expected_fills = pd.read_csv(fills_path, parse_dates=["date"], dtype={"symbol": str})
        for path in (daily_path, fills_path):
            result["research_csv_sha256"][path.name] = sha(path)
        now = datetime.combine(expected.index[-1].date(), datetime.min.time()).replace(hour=22)
        with tempfile.TemporaryDirectory(prefix="trading-core-ledger-parity-") as temporary:
            service = PortfolioStrategyService(data_dir=data_dir, db_path=Path(temporary)/"paper.sqlite", clock=lambda: now)
            service.activate(CORRECTED_CORE_ID, activation_date=expected.index[0].date(),
                             initial_cash=50000. if mode == "lump" else 0.)
            if mode == "dca":
                for day, amount in expected.contribution[expected.contribution > 0].items():
                    service.deposit(CORRECTED_CORE_ID, contribution_date=day.date(), amount=float(amount),
                                    idempotency_key="frozen-"+day.date().isoformat())
            snapshot = service.refresh(CORRECTED_CORE_ID)
            if snapshot["state"] == "BLOCKED":
                raise AssertionError(snapshot["diagnostics"])
            with closing(connect(service.db_path)) as conn:
                saved = conn.execute("SELECT * FROM corrected_core_days ORDER BY valuation_date").fetchall()
                events = conn.execute("SELECT * FROM corrected_core_events WHERE event_type='fill' ORDER BY event_date,id").fetchall()
            actual = pd.DataFrame([json.loads(r["nav_json"]) for r in saved],
                                  index=pd.to_datetime([r["valuation_date"] for r in saved]))
            if not actual.index.equals(expected.index):
                raise AssertionError("Daily valuation calendars differ")
            columns = ["wealth", "liquidation_wealth", "principal", "contribution", "cost", "cumulative_cost",
                       "unit_nav", "unit_drawdown", "profit", "market_pnl", "cash", "receivable", "dividend_income"]
            differences = {c: float((actual[c]-expected[c]).abs().max()) for c in columns}
            for k, symbol in enumerate(CORE_SYMBOLS):
                differences["quantity_"+symbol] = float(abs(actual.quantity.map(lambda q:q[k]).to_numpy()
                                                           - expected["quantity_"+symbol[:6]].to_numpy()).max())
            if max(differences.values()) > 1e-6:
                raise AssertionError({"daily_differences": differences})
            fills = pd.DataFrame([{"date": pd.Timestamp(r["event_date"]), **json.loads(r["payload_json"])} for r in events])
            fills["symbol"] = fills.symbol.str[:6]
            fills = fills.sort_values(["date", "quantity_delta"], kind="stable").reset_index(drop=True)
            if len(fills) != len(expected_fills):
                raise AssertionError("Fill counts differ")
            for c in ("date", "symbol"):
                if not fills[c].equals(expected_fills[c]):
                    raise AssertionError(f"Fill {c} differs")
            if not fills.fill_type.equals(expected_fills.type):
                raise AssertionError("Fill types differ")
            fill_differences = {c: float((fills[c]-expected_fills[c]).abs().max())
                                for c in ("quantity_delta", "price", "notional", "commission")}
            if max(fill_differences.values()) > 1e-6:
                raise AssertionError({"fill_differences": fill_differences})
            if any(e["signal_date"] and r["event_date"] <= e["signal_date"] for r in events
                   if (e := json.loads(r["payload_json"]))["fill_type"] == "rebalance"):
                raise AssertionError("Fill at or before its signal")
            if snapshot != service.refresh(CORRECTED_CORE_ID):
                raise AssertionError("Repeat refresh changed the snapshot")
            with closing(connect(service.db_path)) as conn:
                if conn.execute("SELECT COUNT(*) FROM corrected_core_days").fetchone()[0] != len(saved):
                    raise AssertionError("Repeat refresh duplicated daily records")
                if conn.execute("SELECT COUNT(*) FROM corrected_core_events WHERE event_type='fill'").fetchone()[0] != len(events):
                    raise AssertionError("Repeat refresh duplicated fills")
            result["accounts"][mode] = {"status": "pass", "daily_points": len(actual), "fills": len(fills),
                "first_date": str(actual.index[0].date()), "last_date": str(actual.index[-1].date()),
                "daily_max_absolute_differences": differences, "fill_max_absolute_differences": fill_differences,
                "final_liquidation_wealth": float(actual.liquidation_wealth.iloc[-1]),
                "repeat_refresh_unchanged": True, "signal_precedes_rebalance_fills": True}
    paths = [ROOT/"portfolio_strategies"/name for name in
             ("corrected_core.py", "corrected_core_account.py", "core_raw_data.py", "core_corporate_actions.json", "registry.py", "service.py")]
    paths += [Path(__file__).resolve(), ROOT/"scripts/import_core_raw_snapshot.py"]
    result["implementation_sha256"] = {str(p.relative_to(ROOT)):sha(p) for p in paths}
    result["raw_manifest_sha256"] = sha(data_dir/"core_raw/manifest.json")
    result["status"] = "pass"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--research-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = check(args.data_dir, args.research_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({"status": result["status"], "accounts": {
        mode:{k:v for k,v in row.items() if k in ("daily_points", "fills", "final_liquidation_wealth")}
        for mode,row in result["accounts"].items()}, "evidence": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
