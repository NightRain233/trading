"""Load the isolated, unadjusted core ETF snapshot used by paper research."""
from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from .frozen_xquant import normalize_daily
from .next_open_data import _completed_through


CORE_RAW_SYMBOLS = ("510300.SS", "513100.SS", "518880.SS")
CORE_RAW_SCHEMA_VERSION = 1
CORE_RAW_PRICE_IDENTIFIER = "tickflow_klines_adjust_none"
REQUIRED_COLUMNS = ("Open", "High", "Low", "Close", "Volume")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _valid_manifest(root: Path) -> tuple[dict[str, Any] | None, str | None]:
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return None, f"missing manifest: {manifest_path}"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"cannot read manifest ({type(exc).__name__}): {manifest_path}"
    if not isinstance(manifest, dict):
        return None, "manifest must be a JSON object"
    if manifest.get("schema_version") != CORE_RAW_SCHEMA_VERSION:
        return None, f"unsupported core_raw schema_version: {manifest.get('schema_version')!r}"
    if manifest.get("adjustment") != "none":
        return None, "manifest adjustment must be 'none'; adjusted prices are not accepted"
    if manifest.get("raw_price_identifier") != CORE_RAW_PRICE_IDENTIFIER:
        return None, "manifest does not identify TickFlow adjust=none raw prices"
    imported_at = manifest.get("imported_at")
    try:
        parsed_imported_at = datetime.fromisoformat(str(imported_at).replace("Z", "+00:00"))
    except ValueError:
        return None, "manifest imported_at must be an ISO-8601 timestamp"
    if parsed_imported_at.tzinfo is None:
        return None, "manifest imported_at must include a timezone"
    symbols = manifest.get("symbols")
    if not isinstance(symbols, dict) or set(symbols) != set(CORE_RAW_SYMBOLS):
        return None, "manifest symbols must contain exactly 510300.SS, 513100.SS, and 518880.SS"
    source = manifest.get("source")
    if not isinstance(source, dict) or not source.get("sha256") or not source.get("fetch_log_sha256"):
        return None, "manifest source must include input and fetch-log SHA256 values"
    if source.get("requested_adjustment") != "none":
        return None, "manifest source does not prove requested_adjust=none"
    action_path = root/"corporate_actions.json"
    if action_path.exists():
        entry = manifest.get("corporate_actions", {})
        if entry.get("file") != action_path.name or entry.get("sha256") != _sha256(action_path):
            return None, "custom corporate actions require a matching manifest hash"
    for symbol in CORE_RAW_SYMBOLS:
        entry = symbols.get(symbol)
        if not isinstance(entry, dict):
            return None, f"manifest entry for {symbol} must be an object"
        if entry.get("file") != f"{symbol}.parquet":
            return None, f"manifest entry for {symbol} names an unexpected file"
        if not isinstance(entry.get("sha256"), str) or len(entry["sha256"]) != 64:
            return None, f"manifest entry for {symbol} has no valid SHA256"
        if not isinstance(entry.get("source"), str) or not entry["source"].strip():
            return None, f"manifest entry for {symbol} has no source identifier"
        if not isinstance(entry.get("provenance"), str) or not entry["provenance"].strip():
            return None, f"manifest entry for {symbol} has no provenance"
        if entry.get("adjustment") != "none":
            return None, f"manifest entry for {symbol} is not marked adjustment=none"
    return manifest, None


def _validate_frame(symbol: str, frame: pd.DataFrame) -> str | None:
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        return f"missing required columns: {', '.join(missing)}"
    numeric = frame.loc[:, REQUIRED_COLUMNS].apply(pd.to_numeric, errors="coerce")
    if numeric.empty:
        return "no OHLC rows"
    values = numeric.to_numpy(dtype=float)
    if not all(math.isfinite(value) for row in values for value in row):
        return "OHLC/Volume contains null or non-finite values"
    prices = numeric.loc[:, ("Open", "High", "Low", "Close")]
    if (prices <= 0).any().any():
        return "OHLC prices must be positive"
    if (numeric["Volume"] < 0).any():
        return "Volume must be non-negative"
    invalid_high = numeric["High"] < numeric.loc[:, ("Open", "Low", "Close")].max(axis=1)
    invalid_low = numeric["Low"] > numeric.loc[:, ("Open", "High", "Close")].min(axis=1)
    if invalid_high.any() or invalid_low.any():
        return "OHLC bounds are inconsistent (High/Low does not contain Open, Close, and Low/High)"
    if frame.index.has_duplicates:
        return "duplicate daily dates"
    if not frame.index.is_monotonic_increasing:
        return "dates are not in ascending order"
    return None


def load_core_raw_frames(
    data_dir: Path | str,
    *,
    through_date: date | None = None,
    as_of: datetime | None = None,
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """Load only ``data_dir/core_raw`` and verify its manifest and file hashes.

    Missing or invalid inputs are returned in ``errors`` keyed by symbol (or
    ``"manifest"`` for a snapshot-wide problem). No generic market-data cache
    is consulted. ``through_date`` and the completed-session cutoff from
    ``as_of`` are both applied when supplied.
    """
    snapshot = Path(data_dir) / "core_raw"
    frames: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    if not snapshot.is_dir():
        reason = f"missing raw snapshot directory: {snapshot}; import a frozen adjust=none package first"
        return frames, {symbol: reason for symbol in CORE_RAW_SYMBOLS}

    manifest, manifest_error = _valid_manifest(snapshot)
    if manifest_error:
        return frames, {"manifest": manifest_error}
    assert manifest is not None

    as_of_cutoff = None
    if as_of is not None:
        as_of_cutoff = _completed_through("510300.SS", as_of)
    cutoff = through_date
    if as_of_cutoff is not None:
        cutoff = min(cutoff, as_of_cutoff) if cutoff is not None else as_of_cutoff

    for symbol in CORE_RAW_SYMBOLS:
        entry = manifest["symbols"][symbol]
        path = snapshot / entry["file"]
        if not path.is_file():
            errors[symbol] = f"missing parquet: {path}"
            continue
        try:
            actual_sha = _sha256(path)
        except OSError as exc:
            errors[symbol] = f"cannot hash {path.name}: {exc}"
            continue
        if actual_sha != entry["sha256"]:
            errors[symbol] = f"SHA256 mismatch for {path.name}; expected {entry['sha256']}, got {actual_sha}"
            continue
        try:
            original = pd.read_parquet(path)
            if original.index.has_duplicates or not original.index.is_monotonic_increasing:
                raise ValueError("Raw dates must be unique and ordered")
            frame = normalize_daily(original)
            if len(frame) != len(original):
                raise ValueError("Raw timestamps collide after daily normalization")
        except Exception as exc:
            errors[symbol] = f"cannot read {path.name} ({type(exc).__name__}): {exc}"
            continue
        frame_error = _validate_frame(symbol, frame)
        if frame_error:
            errors[symbol] = f"invalid {path.name}: {frame_error}"
            continue
        frame = frame.astype({column: float for column in REQUIRED_COLUMNS})
        if cutoff is not None:
            frame = frame.loc[:pd.Timestamp(cutoff)]
        if frame.empty:
            errors[symbol] = "no completed rows remain after the requested date cutoff"
            continue
        frames[symbol] = frame
    return frames, errors
