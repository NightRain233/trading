from __future__ import annotations

from pydantic import BaseModel
from datetime import date
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
    presentationGroup: str = "comparison"
    isPrimary: bool = False
    benchmarkStrategyId: Optional[str] = None
    activationDate: Optional[str] = None
    accountOrigin: str = "not_activated"


class ActivateRequest(BaseModel):
    activationDate: date


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
    sleeve: str = ""


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


class PaperOrderItem(BaseModel):
    orderId: int
    symbol: str
    market: str
    sleeve: str
    orderType: str
    side: str
    status: str
    signalDate: str
    expectedExecutionDate: Optional[str] = None
    nextAttemptDate: Optional[str] = None
    actualExecutionDate: Optional[str] = None
    actualOpen: Optional[float] = None
    requestedWeightDelta: Optional[float] = None
    quantityDelta: Optional[float] = None
    commission: Optional[float] = None
    slippage: Optional[float] = None
    delayReason: Optional[str] = None
    rejectionReason: Optional[str] = None
    due: bool = False


class BullCandidateItem(BaseModel):
    symbol: str
    market: str
    signalDate: str
    eligible: bool
    reason: str
    permission: Optional[str] = None
    referenceSymbol: Optional[str] = None
    referenceDate: Optional[str] = None
    referenceClose: Optional[float] = None
    referenceMa: Optional[float] = None
    riskOn: Optional[bool] = None
    gateReason: Optional[str] = None


class BenchmarkBlock(BaseModel):
    strategyId: str = "risk_parity_core_next_open"
    valuationDate: Optional[str] = None
    benchmarkNav: Optional[float] = None
    relativeNav: Optional[float] = None
    relativeReturn: Optional[float] = None


class OperationsBlock(BaseModel):
    asOfDate: Optional[str] = None
    orders: list[PaperOrderItem] = []
    bullCandidates: list[BullCandidateItem] = []
    dueOrderCount: int = 0
    waitingOpenCount: int = 0
    pendingOrderCount: int = 0
    ma200AllowedCount: int = 0
    ma200BlockedCount: int = 0
    grossExposure: Optional[float] = None
    dataQualityEventCount: int = 0
    benchmark: BenchmarkBlock = {}


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
    operations: OperationsBlock = {}
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
