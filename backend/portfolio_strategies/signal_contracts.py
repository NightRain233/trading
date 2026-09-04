from __future__ import annotations

import hashlib
import json


BULL_FLIP_SIGNAL_CONTRACT_VERSION = "bull_flip_ma200_v1"
RAW_BULL_FLIP_SIGNAL_CONTRACT_VERSION = "bull_flip_raw_v1"


def _bull_flip_contract(entry_market_gate: str) -> dict[str, object]:
    return {
        "entrySignal": "completed_daily_supertrend_7_3_bear_to_bull",
        "entryExecution": "next_valid_open",
        "entryMarketGate": entry_market_gate,
        "universe": "rolling_monthly_pit_v1",
        "exitSignal": "completed_daily_supertrend_7_3_bear",
        "exitExecution": "next_valid_open",
        "scannerFieldsAffectEligibility": False,
    }


BULL_FLIP_SIGNAL_CONTRACT = _bull_flip_contract("reference_close_above_sma_200")
RAW_BULL_FLIP_SIGNAL_CONTRACT = _bull_flip_contract("none")
SIGNAL_CONTRACTS = {
    BULL_FLIP_SIGNAL_CONTRACT_VERSION: BULL_FLIP_SIGNAL_CONTRACT,
    RAW_BULL_FLIP_SIGNAL_CONTRACT_VERSION: RAW_BULL_FLIP_SIGNAL_CONTRACT,
}


def signal_contract_hash(version: str) -> str:
    contract = SIGNAL_CONTRACTS[version]
    return hashlib.sha256(
        json.dumps(contract, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


BULL_FLIP_SIGNAL_CONTRACT_HASH = signal_contract_hash(
    BULL_FLIP_SIGNAL_CONTRACT_VERSION,
)
