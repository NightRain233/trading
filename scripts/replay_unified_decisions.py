#!/usr/bin/env python3
"""Replay the production unified scan policy over point-in-time daily closes."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_ta as ta


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import main  # noqa: E402
from analysis_constants import ST_LENGTH, ST_MULTIPLIER  # noqa: E402
from analysis_data import _calculate_daily_indicators, _calculate_weekly_indicators  # noqa: E402
from supertrend_scan_policy import (  # noqa: E402
    POLICY_VERSION,
    SCHEMA_VERSION,
    SYSTEM_MARKET_REPRESENTATIVES,
    build_scan_response,
    classify_asset_class,
    classify_symbol_market,
    classify_trading_venue,
)


OHLCV = ["Open", "High", "Low", "Close", "Volume"]


def _git_state() -> dict[str, Any]:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    status = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True
    )
    tracked_diff = subprocess.check_output(
        ["git", "diff", "--", "backend/main.py", "backend/supertrend_scan_policy.py"],
        cwd=ROOT,
    )
    replay_source = Path(__file__).read_bytes()
    return {
        "sourceCommit": commit,
        "sourceDirty": bool(status.strip()),
        "productionDiffSha256": hashlib.sha256(tracked_diff).hexdigest(),
        "replayScriptSha256": hashlib.sha256(replay_source).hexdigest(),
    }


def _watchlist_symbols(path: Path) -> list[str]:
    payload = json.loads(path.read_text())
    symbols: list[str] = []
    for group in payload:
        for item in group.get("symbols", []):
            symbol = item.get("symbol") if isinstance(item, dict) else item
            normalized = str(symbol or "").strip().upper()
            if normalized and normalized not in symbols:
                symbols.append(normalized)
    return symbols


def _prepare_frames(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = pd.read_parquet(path).sort_index()
    missing = [column for column in OHLCV if column not in raw.columns]
    if missing:
        raise ValueError(f"{path.name} missing OHLCV columns: {missing}")
    raw = raw[OHLCV].apply(pd.to_numeric, errors="coerce").dropna(subset=OHLCV[:4])
    daily = _calculate_daily_indicators(raw.copy())
    daily["_st_val"] = daily["ST_Val"]
    daily["_st_dir"] = daily["ST_Dir"]

    weekly = _calculate_weekly_indicators(raw.copy())
    wst = ta.supertrend(
        weekly["High"], weekly["Low"], weekly["Close"],
        length=ST_LENGTH, multiplier=ST_MULTIPLIER,
    )
    if wst is not None and not wst.empty:
        value_column = next((
            column for column in wst.columns
            if column.startswith("SUPERT_")
            and not any(column.startswith(prefix) for prefix in (
                "SUPERTd_", "SUPERTs_", "SUPERTl_", "SUPERTu_"
            ))
        ), None)
        direction_column = next(
            (column for column in wst.columns if column.startswith("SUPERTd_")),
            None,
        )
        if value_column and direction_column:
            weekly["_wst_val"] = wst[value_column]
            weekly["_wst_dir"] = wst[direction_column]
    return daily, weekly


def _evaluation_clock(symbol: str, session_date: pd.Timestamp) -> datetime:
    day = pd.Timestamp(session_date).date()
    venue = classify_trading_venue(symbol)
    if venue == "china_exchange":
        return datetime.combine(day, time(15, 20), ZoneInfo("Asia/Shanghai"))
    if venue == "hong_kong_exchange":
        return datetime.combine(day, time(16, 20), ZoneInfo("Asia/Hong_Kong"))
    if venue == "crypto_24_7":
        return datetime.combine(day + timedelta(days=1), time(0, 10), timezone.utc)
    if venue == "us_futures":
        return datetime.combine(day, time(17, 20), ZoneInfo("America/New_York"))
    return datetime.combine(day, time(16, 20), ZoneInfo("America/New_York"))


def _weekly_prefix(weekly: pd.DataFrame, session_date: pd.Timestamp) -> pd.DataFrame:
    date = pd.Timestamp(session_date).tz_localize(None).normalize()
    cutoff = date + pd.Timedelta(days=(6 - date.weekday()) % 7)
    return weekly.loc[weekly.index <= cutoff]


def _item_as_of(
    symbol: str,
    frames: dict[str, tuple[pd.DataFrame, pd.DataFrame]],
    session_date: pd.Timestamp,
    evaluation_clock: datetime,
) -> dict[str, Any] | None:
    daily, weekly = frames[symbol]
    daily_prefix = daily.loc[daily.index <= session_date]
    if daily_prefix.empty:
        return None
    return main._build_supertrend_scan_item(
        symbol,
        daily_prefix,
        _weekly_prefix(weekly, session_date),
        now=evaluation_clock,
        cache_stale=False,
        refresh_triggered=False,
        include_auxiliary=False,
    )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _flatten(item: dict[str, Any]) -> dict[str, Any]:
    decision = item.get("decision") or {}
    execution = item.get("executionStatus") or {}
    indicators = item.get("indicators") or {}
    return {
        "schemaVersion": SCHEMA_VERSION,
        "policyVersion": POLICY_VERSION,
        "symbol": item.get("symbol"),
        "decisionDate": item.get("decisionAsOf"),
        "market": item.get("market"),
        "assetClass": classify_asset_class(str(item.get("symbol") or "")),
        "tradingVenue": classify_trading_venue(str(item.get("symbol") or "")),
        "marketMode": item.get("marketMode"),
        "marketAdxThreshold": (item.get("marketModeContext") or {}).get("adxThreshold"),
        "state": item.get("state"),
        "weeklyState": item.get("weeklyState"),
        "trendAgeBars": item.get("trendAgeBars"),
        "close": item.get("close"),
        "stVal": item.get("stVal"),
        "atr": indicators.get("atr"),
        "adx": indicators.get("adx"),
        "adxDelta": indicators.get("adxDelta"),
        "macdHist": indicators.get("macdHist"),
        "macdHistDelta": indicators.get("macdHistDelta"),
        "bollWidthRatio20": indicators.get("bollWidthRatio20"),
        "distanceToSupertrendAtr": item.get("distanceToSupertrendAtr"),
        "permission": decision.get("permission"),
        "setup": decision.get("setup"),
        "stage": decision.get("stage"),
        "primaryGroup": item.get("primaryGroup"),
        "readinessScore": decision.get("readinessScore"),
        "failureCategory": decision.get("failureCategory"),
        "reasonCodes": _json(decision.get("reasonCodes") or []),
        "failedGates": _json(decision.get("failedGates") or []),
        "nextGate": decision.get("nextGate"),
        "triggerPrice": decision.get("triggerPrice"),
        "maxAcceptablePrice": decision.get("maxAcceptablePrice"),
        "invalidationPrice": decision.get("invalidationPrice"),
        "paperOnly": bool(decision.get("paperOnly")),
        "executionStatus": execution.get("status"),
        "executionEligible": bool(execution.get("executable")),
        "dataStale": bool(item.get("dataStale")),
        "dataGap": bool((item.get("dataIntegrity") or {}).get("hasGap")),
    }


def replay(
    *,
    data_dir: Path,
    symbols: list[str],
    start: str,
    end: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    representative_symbols = list(dict.fromkeys(
        symbol
        for values in SYSTEM_MARKET_REPRESENTATIVES.values()
        for symbol in values
    ))
    required = list(dict.fromkeys([*symbols, *representative_symbols]))
    frames: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    missing: list[str] = []
    for symbol in required:
        path = data_dir / f"{symbol}.parquet"
        if not path.exists():
            missing.append(symbol)
            continue
        frames[symbol] = _prepare_frames(path)

    available_symbols = [symbol for symbol in symbols if symbol in frames]
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    representative_cache: dict[tuple[str, str, str], dict[str, Any] | None] = {}
    rows: list[dict[str, Any]] = []
    for symbol in available_symbols:
        daily, _ = frames[symbol]
        dates = daily.index[(daily.index >= start_ts) & (daily.index <= end_ts)]
        for session_date in dates:
            evaluation_clock = _evaluation_clock(symbol, session_date)
            item = _item_as_of(symbol, frames, session_date, evaluation_clock)
            if item is None:
                continue
            representatives = []
            target_market = classify_symbol_market(symbol)
            relevant_representatives = SYSTEM_MARKET_REPRESENTATIVES.get(target_market, ())
            for representative in relevant_representatives:
                if representative not in frames or representative == symbol:
                    continue
                cache_key = (
                    representative,
                    pd.Timestamp(session_date).date().isoformat(),
                    classify_trading_venue(symbol),
                )
                if cache_key not in representative_cache:
                    representative_cache[cache_key] = _item_as_of(
                        representative,
                        frames,
                        session_date,
                        evaluation_clock,
                    )
                representative_item = representative_cache[cache_key]
                if representative_item is not None:
                    representatives.append(representative_item)
            response = build_scan_response(
                [item],
                requested_symbols=[symbol],
                representative_items=representatives,
            )
            normalized = response["items"][0]
            row = _flatten(normalized)
            row["evaluationClock"] = evaluation_clock.isoformat()
            rows.append(row)
        print(f"replayed {symbol}: {len(dates)} sessions", flush=True)

    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values(["decisionDate", "symbol"]).reset_index(drop=True)
    metadata = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceRepository": "trading",
        **_git_state(),
        "schemaVersion": SCHEMA_VERSION,
        "policyVersion": POLICY_VERSION,
        "start": start,
        "end": end,
        "requestedSymbols": symbols,
        "availableSymbols": available_symbols,
        "missingSymbols": missing,
        "rowCount": int(len(result)),
        "pointInTimeRule": "daily data truncated at each target session; production item builder and policy reused",
        "executionRule": "decision stream only; no future prices used",
    }
    return result, metadata


def main_cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=BACKEND / "data")
    parser.add_argument("--watchlist", type=Path, default=BACKEND / "watchlist.json")
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--start", default="2023-03-01")
    parser.add_argument("--end", default="2026-07-10")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata-output", type=Path)
    args = parser.parse_args()
    symbols = [symbol.upper() for symbol in args.symbols] if args.symbols else _watchlist_symbols(args.watchlist)
    decisions, metadata = replay(
        data_dir=args.data_dir,
        symbols=symbols,
        start=args.start,
        end=args.end,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    decisions.to_parquet(args.output, index=False)
    metadata_path = args.metadata_output or args.output.with_suffix(".metadata.json")
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main_cli()
