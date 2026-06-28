from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class StrategyMode(str, Enum):
    PAPER = "paper"
    COMPARISON = "comparison"


class CalculationState(str, Enum):
    READY = "READY"
    NOT_DUE = "NOT_DUE"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class AssetConfig:
    symbol: str
    alias: str
    sleeve: str
    market: str = "XSHG"
    synthetic_proxy: bool = False
    note: str = ""


@dataclass(frozen=True)
class CostConfig:
    base_bps: float
    slippage_bps: float = 0.0
    asset_extra_bps: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "asset_extra_bps",
            MappingProxyType(dict(self.asset_extra_bps)),
        )

    def extra_bps(self, symbol: str) -> float:
        return float(self.asset_extra_bps.get(symbol, 0.0))

    def total_bps(self, symbol: str) -> float:
        return self.base_bps + self.slippage_bps + self.extra_bps(symbol)


@dataclass(frozen=True)
class StrategyConfig:
    strategy_id: str
    version: str
    display_name: str
    description: str
    mode: StrategyMode
    execution: str
    initial_nav: float
    base_currency: str
    assets: tuple[AssetConfig, ...]
    params: Mapping[str, Any]
    costs: CostConfig

    def __post_init__(self) -> None:
        object.__setattr__(self, "assets", tuple(self.assets))
        object.__setattr__(self, "params", MappingProxyType(dict(self.params)))

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(asset.symbol for asset in self.assets)

    def asset(self, symbol: str) -> AssetConfig:
        for asset in self.assets:
            if asset.symbol == symbol:
                return asset
        raise KeyError(symbol)


@dataclass(frozen=True)
class DataDiagnostic:
    code: str
    message: str
    symbol: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))


@dataclass(frozen=True)
class StrategyObservation:
    as_of_date: date
    state: str
    reason: str
    values: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))


@dataclass(frozen=True)
class TargetWeight:
    symbol: str
    weight: float
    sleeve: str
    reason: str


@dataclass(frozen=True)
class StrategyCalculation:
    strategy_id: str
    strategy_version: str
    state: CalculationState
    market_data_date: date
    signal_date: date | None
    observation: StrategyObservation
    target_weights: tuple[TargetWeight, ...] = ()
    sleeve_weights: Mapping[str, tuple[TargetWeight, ...]] = field(
        default_factory=dict
    )
    diagnostics: tuple[DataDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_weights", tuple(self.target_weights))
        object.__setattr__(
            self,
            "sleeve_weights",
            MappingProxyType(
                {
                    sleeve: tuple(weights)
                    for sleeve, weights in self.sleeve_weights.items()
                }
            ),
        )
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
