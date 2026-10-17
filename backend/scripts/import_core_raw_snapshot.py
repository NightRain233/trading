"""Import a frozen raw core-ETF file set for paper research; never fetch data."""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any
import uuid

import pandas as pd


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from portfolio_strategies.core_raw_data import (  # noqa: E402
    CORE_RAW_PRICE_IDENTIFIER,
    CORE_RAW_SYMBOLS,
    load_core_raw_frames,
)
from portfolio_strategies.corrected_core import load_actions


SOURCE_SYMBOLS = {
    "510300.SS": "510300.SH",
    "513100.SS": "513100.SH",
    "518880.SS": "518880.SH",
}
SOURCE_FIELDS = ("open", "high", "low", "close", "volume")
DEFAULT_INPUT = (
    BACKEND_ROOT.parents[1]
    / "xquant/outputs/etf-dividend-valuation-2026-10-04/inputs/raw.json"
)
# Exact bytes in the independently audited 2026-10-04 reproduction bundle.
# Compared against the original successful adjust=none request and delivery
# manifest; this permits importing that self-contained bundle without an older
# package's fetch log. Other inputs still require their own successful log.
FROZEN_RAW_SHA256 = "ace18b4e70d3029e959b7c72e77c6c6300a90ecd673fa1dcaf3c085c8d1ca8b6"
FROZEN_FETCH_LOG_SHA256 = "c470c1912a08c629a85778bb0defaffdb899067018c85abc14c009de88c2ebfc"
FROZEN_RETRIEVED_AT = "2026-10-04T21:35:06.343060+08:00"


class ImportErrorMessage(ValueError):
    """A source package cannot safely be imported as unadjusted raw data."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ImportErrorMessage(f"Cannot read JSON file {path}: {exc}") from exc


def _verified_fetch_records(fetch_log_path: Path) -> dict[str, dict[str, Any]]:
    payload = _read_json(fetch_log_path)
    if not isinstance(payload, list):
        raise ImportErrorMessage("fetch_log.json must be a list of request records")
    verified: dict[str, dict[str, Any]] = {}
    for target, provider_symbol in SOURCE_SYMBOLS.items():
        records = [
            record for record in payload
            if isinstance(record, dict)
            and provider_symbol in record.get("symbols", [])
        ]
        if not records:
            raise ImportErrorMessage(
                f"fetch_log.json has no request record for {provider_symbol}"
            )
        if any(record.get("requested_adjust") != "none" for record in records):
            raise ImportErrorMessage(
                f"{provider_symbol} is not unambiguously marked requested_adjust=none"
            )
        successful = [record for record in records if record.get("status") == 200]
        if len(successful) != 1:
            raise ImportErrorMessage(
                f"expected one successful adjust=none request for {provider_symbol}; found {len(successful)}"
            )
        record = successful[0]
        retrieved_at = record.get("retrieved_at")
        try:
            timestamp = datetime.fromisoformat(str(retrieved_at).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ImportErrorMessage(
                f"fetch record for {provider_symbol} has invalid retrieved_at"
            ) from exc
        if timestamp.tzinfo is None:
            raise ImportErrorMessage(
                f"fetch record for {provider_symbol} retrieved_at has no timezone"
            )
        verified[target] = record
    return verified


def _provider_frame(symbol: str, provider_symbol: str, record: Any) -> pd.DataFrame:
    if not isinstance(record, dict):
        raise ImportErrorMessage(f"data.{provider_symbol} must be an object")
    timestamps = record.get("timestamp")
    if not isinstance(timestamps, list) or not timestamps:
        raise ImportErrorMessage(f"data.{provider_symbol}.timestamp is missing or empty")
    lengths = {field: len(record.get(field, [])) for field in SOURCE_FIELDS}
    expected = len(timestamps)
    inconsistent = {field: length for field, length in lengths.items() if length != expected}
    if inconsistent:
        raise ImportErrorMessage(
            f"data.{provider_symbol} OHLCV arrays do not align with timestamp: {inconsistent}"
        )
    try:
        dates = (
            pd.to_datetime(timestamps, unit="ms", utc=True)
            .tz_convert("Asia/Shanghai")
            .tz_localize(None)
            .normalize()
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise ImportErrorMessage(
            f"data.{provider_symbol}.timestamp is not a millisecond epoch array"
        ) from exc
    frame = pd.DataFrame(
        {field.capitalize(): record[field] for field in SOURCE_FIELDS},
        index=pd.DatetimeIndex(dates, name="Date"),
    )
    # The provider reports ETF volume in hands; xquant's research importer
    # converts it to shares. Prices remain exactly the adjust=none OHLC values.
    frame["Volume"] = pd.to_numeric(frame["Volume"], errors="coerce") * 100
    if "amount" in record:
        if not isinstance(record["amount"], list) or len(record["amount"]) != expected:
            raise ImportErrorMessage(f"data.{provider_symbol}.amount does not align with timestamp")
        frame["Amount"] = record["amount"]
    frame = frame.sort_index()
    if frame.index.has_duplicates:
        raise ImportErrorMessage(f"data.{provider_symbol} contains duplicate Shanghai dates")
    return frame


def _load_source(input_path: Path, fetch_log_path: Path) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    payload = _read_json(input_path)
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise ImportErrorMessage("source JSON must have the TickFlow shape {\"data\": {symbol: fields}}")
    data = payload["data"]
    if fetch_log_path.is_file():
        fetch_records = _verified_fetch_records(fetch_log_path)
        log_hash = _sha256(fetch_log_path)
        verification = "successful_adjust_none_fetch_log"
    elif _sha256(input_path) == FROZEN_RAW_SHA256:
        fetch_records = {symbol: {"retrieved_at": FROZEN_RETRIEVED_AT} for symbol in CORE_RAW_SYMBOLS}
        log_hash = FROZEN_FETCH_LOG_SHA256
        verification = "exact_pinned_2026_10_04_research_input_hash; original_fetch_log_archived_separately"
    else:
        raise ImportErrorMessage("Missing fetch log: input is not the exact approved frozen research file; requested_adjust=none must be established")
    frames: dict[str, pd.DataFrame] = {}
    symbol_provenance: dict[str, dict[str, str]] = {}
    for symbol, provider_symbol in SOURCE_SYMBOLS.items():
        if provider_symbol not in data:
            raise ImportErrorMessage(f"source JSON is missing data.{provider_symbol}")
        frame = _provider_frame(symbol, provider_symbol, data[provider_symbol])
        frames[symbol] = frame
        request = fetch_records[symbol]
        symbol_provenance[symbol] = {
            "source": f"TickFlow raw JSON data.{provider_symbol}",
            "provenance": (
                f"requested_adjust=none; retrieved_at={request['retrieved_at']}; "
                f"source_sha256={_sha256(input_path)}"
            ),
        }
    metadata = {
        "input_path": input_path,
        "input_sha256": _sha256(input_path),
        "fetch_log_path": fetch_log_path,
        "fetch_log_sha256": log_hash,
        "source_verification": verification,
        "fetch_records": fetch_records,
        "symbol_provenance": symbol_provenance,
    }
    return frames, metadata


def _write_staged_snapshot(
    snapshot_dir: Path,
    frames: dict[str, pd.DataFrame],
    metadata: dict[str, Any],
) -> None:
    snapshot_dir.mkdir()
    symbols: dict[str, dict[str, Any]] = {}
    for symbol in CORE_RAW_SYMBOLS:
        frame = frames[symbol]
        filename = f"{symbol}.parquet"
        path = snapshot_dir / filename
        frame.to_parquet(path, index=True)
        source_info = metadata["symbol_provenance"][symbol]
        symbols[symbol] = {
            "file": filename,
            "sha256": _sha256(path),
            "source": source_info["source"],
            "provenance": source_info["provenance"],
            "adjustment": "none",
            "rows": len(frame),
            "first_date": frame.index[0].date().isoformat(),
            "last_date": frame.index[-1].date().isoformat(),
            "volume_unit": "shares (TickFlow hands multiplied by 100)",
        }
    source = {
        "provider": "TickFlow",
        "file": metadata["input_path"].name,
        "sha256": metadata["input_sha256"],
        "fetch_log_file": metadata["fetch_log_path"].name,
        "fetch_log_sha256": metadata["fetch_log_sha256"],
        "requested_adjustment": "none",
        "verification": metadata["source_verification"],
        "fetch_log_retrieved_at": {
            symbol: metadata["fetch_records"][symbol]["retrieved_at"]
            for symbol in CORE_RAW_SYMBOLS
        },
    }
    manifest = {
        "schema_version": 1,
        "adjustment": "none",
        "raw_price_identifier": CORE_RAW_PRICE_IDENTIFIER,
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "symbols": symbols,
    }
    manifest_path = snapshot_dir / "manifest.json"
    temporary_manifest = snapshot_dir / ".manifest.json.tmp"
    temporary_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_manifest, manifest_path)


def _rename_exchange(first: Path, second: Path) -> bool:
    """Use an OS atomic directory exchange when the platform exposes one."""
    encoded_first = os.fsencode(first)
    encoded_second = os.fsencode(second)
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        operation = library.renameat2
        operation.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        operation.restype = ctypes.c_int
        result = operation(-100, encoded_first, -100, encoded_second, 2)  # AT_FDCWD, RENAME_EXCHANGE
    elif sys.platform == "darwin" and hasattr(library, "renamex_np"):
        operation = library.renamex_np
        operation.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        operation.restype = ctypes.c_int
        result = operation(encoded_first, encoded_second, 2)  # RENAME_SWAP
    else:
        return False
    if result == 0:
        return True
    error_number = ctypes.get_errno()
    if error_number in (22, 38, 45, 95):  # unsupported by filesystem/kernel
        return False
    raise OSError(error_number, os.strerror(error_number), str(second))


def _atomic_install(stage: Path, destination: Path, *, replace: bool) -> None:
    if destination.is_symlink():
        raise ImportErrorMessage(f"Refusing symlink raw snapshot path: {destination}")
    if not destination.exists():
        os.replace(stage, destination)
        return
    if not replace:
        raise ImportErrorMessage(
            f"raw snapshot already exists: {destination}; pass --replace to replace only this isolated snapshot"
        )
    if not destination.is_dir():
        raise ImportErrorMessage(f"existing raw snapshot path is not a directory: {destination}")
    if _rename_exchange(stage, destination):
        shutil.rmtree(stage)
        return

    # Safe fallback for filesystems without atomic directory exchange: retain a
    # same-filesystem backup and restore it if installing the staged tree fails.
    backup = destination.parent / f".core_raw.backup-{uuid.uuid4().hex}"
    os.replace(destination, backup)
    try:
        os.replace(stage, destination)
    except Exception:
        os.replace(backup, destination)
        raise
    shutil.rmtree(backup)


def import_snapshot(
    input_path: Path,
    data_dir: Path,
    *,
    fetch_log_path: Path | None = None,
    replace: bool = False,
    corporate_actions_path: Path | None = None,
) -> None:
    input_path = input_path.expanduser().resolve()
    data_dir = data_dir.expanduser().resolve()
    fetch_log_path = (fetch_log_path or input_path.parent / "fetch_log.json").expanduser().resolve()
    if (data_dir/"core_raw/corporate_actions.json").exists() and corporate_actions_path is None:
        raise ImportErrorMessage("Existing snapshot has custom corporate actions; supply --corporate-actions explicitly to preserve/update it")
    if corporate_actions_path is not None:
        corporate_actions_path = corporate_actions_path.expanduser().resolve()
        load_actions(corporate_actions_path)
    if not input_path.is_file():
        raise ImportErrorMessage(f"input JSON does not exist: {input_path}")
    frames, metadata = _load_source(input_path, fetch_log_path)
    data_dir.mkdir(parents=True, exist_ok=True)
    lock_path = data_dir / ".core_raw_snapshot_import.lock"
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ImportErrorMessage(
            f"another import may be active, or a stale lock exists: {lock_path}"
        ) from exc

    stage_root: Path | None = None
    try:
        os.write(lock_fd, f"pid={os.getpid()}\n".encode())
        os.close(lock_fd)
        stage_root = Path(tempfile.mkdtemp(prefix=".core_raw_import-", dir=data_dir))
        stage_snapshot = stage_root / "core_raw"
        _write_staged_snapshot(stage_snapshot, frames, metadata)
        if corporate_actions_path is not None:
            shutil.copyfile(corporate_actions_path, stage_snapshot/"corporate_actions.json")
            manifest_path = stage_snapshot/"manifest.json"
            manifest = _read_json(manifest_path)
            manifest["corporate_actions"] = {"file": "corporate_actions.json",
                                             "sha256": _sha256(stage_snapshot/"corporate_actions.json")}
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n")
        staged_frames, errors = load_core_raw_frames(stage_root)
        if errors or set(staged_frames) != set(CORE_RAW_SYMBOLS):
            raise ImportErrorMessage(f"staged snapshot validation failed: {errors}")
        destination = data_dir / "core_raw"
        if destination.exists() and not replace:
            raise ImportErrorMessage(
                f"raw snapshot already exists: {destination}; pass --replace to replace only this isolated snapshot"
            )
        _atomic_install(stage_snapshot, destination, replace=replace)
    finally:
        try:
            os.close(lock_fd)
        except OSError:
            pass
        lock_path.unlink(missing_ok=True)
        if stage_root is not None and stage_root.exists():
            shutil.rmtree(stage_root)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Import a local frozen TickFlow adjust=none JSON package into the isolated "
            "core_raw paper-research input directory. This command never downloads data, "
            "never updates the generic market cache, and never reads or changes an account."
        ),
        epilog=(
            "Importing a frozen package makes that package available as paper-research input; "
            "it is different from fetching/updating a market-data cache or applying data to an account. "
            "Existing core_raw snapshots are refused unless --replace is explicitly supplied."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"local TickFlow JSON file (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--fetch-log",
        type=Path,
        default=None,
        help="local successful adjust=none fetch log; only the exact pinned 2026-10-04 bundle input can omit it",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=BACKEND_ROOT / "data",
        help="parent data directory; output is the isolated data-dir/core_raw/ tree",
    )
    parser.add_argument(
        "--corporate-actions", type=Path, default=None,
        help="explicit verified event JSON (optional; otherwise the versioned research snapshot is used)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="explicitly replace an existing core_raw snapshot; never touches generic symbol parquets",
    )
    args = parser.parse_args()
    try:
        import_snapshot(
            args.input,
            args.data_dir,
            fetch_log_path=args.fetch_log,
            replace=args.replace,
            corporate_actions_path=args.corporate_actions,
        )
    except (ImportErrorMessage, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Imported isolated raw core snapshot into {(args.data_dir / 'core_raw').resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
