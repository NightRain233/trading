from __future__ import annotations

from pydantic import BaseModel
from typing import Any, Optional


class StrategyListItem(BaseModel):
    strategyId: str
    version: str
    displayName: str
    description: str
    mode: str
    execution: str
    baseCurrency: str
    initialNav: float
    paperEnabled: bool
    bootstrapped: bool = False
    bootstrapSignalDate: Optional[str] = None
    bootstrapValuationDate: Optional[str] = None


class DiagnosticItem(BaseModel):
    code: str
    message: str
    symbol: Optional[str] = None
    details: dict[str, Any] = {}


class WeightItem(BaseModel):
    symbol: str
    weight: float
    sleeve: str = ""
    reason: str = ""


class PositionItem(BaseModel):
    symbol: str
    weight: float
    quantity: float = 0.0
    price: Optional[float] = None
    value: float = 0.0


class DatesBlock(BaseModel):
    marketDataDate: Optional[str] = None
    signalDate: Optional[str] = None
    executionDate: Optional[str] = None
    nextCheck: Optional[str] = None


class ObservationBlock(BaseModel):
    asOfDate: Optional[str] = None
    state: Optional[str] = None
    reason: Optional[str] = None
    values: dict[str, Any] = {}


class NavBlock(BaseModel):
    valuationDate: Optional[str] = None
    grossNav: Optional[float] = None
    netNav: Optional[float] = None
    cash: Optional[float] = None
    dailyReturn: Optional[float] = None
    cumulativeReturn: Optional[float] = None
    drawdown: Optional[float] = None


class LedgerBlock(BaseModel):
    status: str = "empty"
    rebalanceId: Optional[int] = None
    signalDate: Optional[str] = None


class AssetMeta(BaseModel):
    symbol: str
    alias: str
    sleeve: str
    syntheticProxy: bool = False


class SnapshotResponse(BaseModel):
    strategyId: str
    strategyVersion: str
    state: str
    dates: DatesBlock
    assets: list[AssetMeta] = []
    diagnostics: list[DiagnosticItem] = []
    observation: ObservationBlock
    currentWeights: list[PositionItem] = []
    desiredWeights: list[WeightItem] = []
    executableWeights: list[WeightItem] = []
    deltaWeights: list[dict[str, Any]] = []
    sleeveWeights: dict[str, list[WeightItem]] = {}
    nav: NavBlock = {}
    ledger: LedgerBlock = {}
    calcError: Optional[str] = None


class TargetWeightsResponse(BaseModel):
    strategyId: str
    desired: list[WeightItem] = []
    executable: list[WeightItem] = []


class DiffRow(BaseModel):
    symbol: str
    currentWeight: float
    desiredWeight: float
    delta: float


class RebalanceDiffResponse(BaseModel):
    strategyId: str
    rows: list[DiffRow] = []


class LedgerEventItem(BaseModel):
    type: str
    id: int
    eventDate: Optional[str] = None
    state: Optional[str] = None
    reason: Optional[str] = None
    createdAt: Optional[str] = None


class LedgerEventsResponse(BaseModel):
    strategyId: str
    events: list[LedgerEventItem] = []
    nextCursor: Optional[int] = None


class NavPoint(BaseModel):
    valuationDate: str
    grossNav: float
    netNav: float
    cash: float
    dailyReturn: float
    cumulativeReturn: float
    drawdown: float


class NavSeriesResponse(BaseModel):
    strategyId: str
    points: list[NavPoint] = []
