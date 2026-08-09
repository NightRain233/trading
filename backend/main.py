import argparse
from fastapi import FastAPI, HTTPException, Header, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from pathlib import Path
from typing import List, Optional, Literal
from backtest import (
    load_universe_symbols,
    run_backtest_for_symbol,
    summarize_backtest_report,
    simulate_rs_rotation_portfolio,
    annotate_relative_strength,
    classify_asset,
    RS_ROTATION_PRESETS,
    list_rs_rotation_presets,
    evaluate_weekly_bb_breakout,
    evaluate_weekly_bb_pullback,
    evaluate_weekly_bb_exit,
    replay_weekly_bb_markers,
    build_supertrend_history_review,
    run_supertrend_backtest,
    SUPER_TREND_EXECUTION_MODE,
    SUPER_TREND_DEFAULT_HISTORY_EXIT_MODE,
    SUPER_TREND_HISTORY_EXIT_MODES,
)
from strategy_versions import get_strategy_version, list_strategy_versions
from supertrend_alerts import classify_supertrend_alert
from supertrend_scan_policy import build_scan_response, classify_trend_state, SYSTEM_MARKET_REPRESENTATIVES
from analysis import (
    DATA_DIR,
    analyze_stock,
    batch_fetch_and_update,
    _build_mini_candles,
    get_cached_batch_summaries,
    refresh_symbols_async,
    refresh_symbols_sync_with_timeout,
    get_data_source_status,
    build_macd_divergence_summary,
    filter_completed_weekly_bars,
    is_daily_session_complete,
)
from data_source_guard import MarketDataUnavailableError
from portfolio_strategies.registry import (
    UnknownStrategyError,
    ComparisonStrategyError,
    list_strategies as list_portfolio_strategies,
)
from portfolio_strategies.service import PortfolioStrategyService
from portfolio_strategies import api_models as pm
import json
import os
import copy
import fcntl
import sqlite3
import uuid
import time
import logging
import threading
import hashlib
import pandas as pd
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import formatdate
from zoneinfo import ZoneInfo
from analysis_constants import BACKGROUND_PREWARM_ENABLED, PREWARM_HOURS

# 获取日志记录器，用于在控制台输出信息
logger = logging.getLogger(__name__)

@contextmanager
def timer(name: str):
    """
    一个简单的计时器工具（上下文管理器）。
    用法:
    with timer("步骤名称"):
        做一些事情...
    """
    start_time = time.perf_counter()
    yield
    end_time = time.perf_counter()
    logger.info(f"==> [耗时统计] {name}: {end_time - start_time:.4f} 秒")

app = FastAPI()

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WATCHLIST_FILE = str(Path(__file__).resolve().parent / "watchlist.json")
RS_HOLDINGS_CACHE_FILE = "backtest_results/rs_holdings_cache.json"
HISTORY_TRADES_CACHE_FILE = "backtest_results/history_trades_cache.sqlite"
PREWARM_TZ = ZoneInfo("Asia/Shanghai")
COLD_START_SYNC_TIMEOUT_SECONDS = 5.0
PORTFOLIO_PAPER_DB = "backtest_results/portfolio_paper.sqlite"

_portfolio_service: PortfolioStrategyService | None = None
_prewarm_leader_handle = None


def _get_portfolio_service() -> PortfolioStrategyService:
    global _portfolio_service
    if _portfolio_service is None:
        _portfolio_service = PortfolioStrategyService(
            data_dir=DATA_DIR,
            db_path=PORTFOLIO_PAPER_DB,
        )
    return _portfolio_service

class UpdateAliasRequest(BaseModel):
    alias: str


SHANGHAI_SYMBOL_PREFIXES = (
    "600", "601", "603", "605", "688",
    "510", "511", "512", "513", "515", "516", "517", "518", "588",
)
SHENZHEN_SYMBOL_PREFIXES = ("000", "001", "002", "003", "300", "301", "159")
SPECIAL_A_SHARE_SYMBOLS = {
    "000001": [
        ("000001.SS", "上证指数"),
        ("000001.SZ", "平安银行"),
    ],
}
BUILTIN_A_SHARE_NAMES = {
    "000001.SS": "上证指数",
    "000001.SZ": "平安银行",
    "000300.SS": "沪深300",
    "600519.SS": "贵州茅台",
}


class SymbolResolveCandidate(BaseModel):
    symbol: str
    displayCode: str
    name: str
    market: str
    confidence: Literal["exact", "rule", "special"]


def _display_code_for_yahoo_symbol(symbol: str) -> str:
    if symbol.endswith(".SS"):
        return f"{symbol[:-3]}.SH"
    return symbol


def _market_for_yahoo_symbol(symbol: str) -> str:
    if symbol.endswith(".SS"):
        return "上海"
    if symbol.endswith(".SZ"):
        return "深圳"
    return "其他"


def _load_known_a_share_names() -> dict:
    names = dict(BUILTIN_A_SHARE_NAMES)

    universe_files = [
        Path(__file__).resolve().parent / "universes" / "a_share_etf_core.json",
        Path(__file__).resolve().parent / "universes" / "etf_core.json",
    ]
    for universe_file in universe_files:
        if not universe_file.exists():
            continue
        try:
            with open(universe_file, "r") as f:
                payload = json.load(f)
        except Exception as exc:
            logger.warning(f"读取标的名称文件失败 {universe_file}: {exc}")
            continue

        raw_symbols = payload.get("symbols", []) if isinstance(payload, dict) else payload
        for item in raw_symbols:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol", "")).strip().upper()
            name = str(item.get("name", "")).strip()
            if symbol and name:
                names.setdefault(symbol, name)

    try:
        for group in load_watchlist():
            for item in group.get("symbols", []):
                if not isinstance(item, dict):
                    continue
                symbol = str(item.get("symbol", "")).strip().upper()
                alias = str(item.get("alias", "")).strip()
                if symbol and alias:
                    names.setdefault(symbol, alias)
    except Exception as exc:
        logger.warning(f"读取 watchlist 名称失败: {exc}")

    return names


def _build_symbol_candidate(symbol: str, name: str = "", confidence: Literal["exact", "rule", "special"] = "rule") -> dict:
    normalized = symbol.strip().upper().replace(".SH", ".SS")
    display_code = _display_code_for_yahoo_symbol(normalized)
    names = _load_known_a_share_names()
    return {
        "symbol": normalized,
        "displayCode": display_code,
        "name": name or names.get(normalized, display_code),
        "market": _market_for_yahoo_symbol(normalized),
        "confidence": confidence,
    }


def resolve_symbol_candidates(raw: str) -> List[dict]:
    query = raw.strip().upper()
    if not query:
        return []

    if query.endswith(".SH"):
        return [_build_symbol_candidate(query, confidence="exact")]
    if query.endswith(".SS") or query.endswith(".SZ"):
        return [_build_symbol_candidate(query, confidence="exact")]
    if not (query.isdigit() and len(query) == 6):
        return []

    special_candidates = SPECIAL_A_SHARE_SYMBOLS.get(query)
    if special_candidates:
        return [
            _build_symbol_candidate(symbol, name=name, confidence="special")
            for symbol, name in special_candidates
        ]

    if query.startswith(SHANGHAI_SYMBOL_PREFIXES):
        return [_build_symbol_candidate(f"{query}.SS", confidence="rule")]
    if query.startswith(SHENZHEN_SYMBOL_PREFIXES):
        return [_build_symbol_candidate(f"{query}.SZ", confidence="rule")]
    return []


def normalize_watchlist_symbol(raw: str) -> str:
    symbol = raw.strip().upper()
    if not symbol:
        return ""
    candidates = resolve_symbol_candidates(symbol)
    if candidates:
        return candidates[0]["symbol"]
    return symbol.replace(".SH", ".SS")

def load_watchlist():
    """Load watchlist with migration support for legacy format."""
    if not os.path.exists(WATCHLIST_FILE):
        return [{"id": str(uuid.uuid4()), "name": "默认分组", "symbols": [], "collapsed": False}]
    
    with open(WATCHLIST_FILE, "r") as f:
        data = json.load(f)
    
    # Validation & Migration
    migrated = False
    
    # 1. Root level list -> Default Group
    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], (str, dict)) and "id" not in data[0]:
         # It's an old raw list of symbols, convert to group
         data = [{
            "id": str(uuid.uuid4()),
            "name": "默认分组",
            "symbols": data,
            "collapsed": False
        }]
         migrated = True

    # 2. String symbols -> Object symbols
    for group in data:
        new_symbols = []
        for item in group.get("symbols", []):
            if isinstance(item, str):
                new_symbols.append({"symbol": item, "alias": ""})
                migrated = True
            elif isinstance(item, dict) and "symbol" in item:
                if "alias" not in item:
                    item["alias"] = ""
                    migrated = True
                new_symbols.append(item)
        group["symbols"] = new_symbols
    
    if migrated:
        save_watchlist(data)
        
    return data

def save_watchlist(watchlist):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(watchlist, f, indent=2, ensure_ascii=False)

class SymbolItem(BaseModel):
    symbol: str
    alias: Optional[str] = ""

class StockResponse(BaseModel):
    symbol: str
    name: str
    price: float
    changePercent: float
    ema20: float
    ema50: float
    adx: float
    rsi: float
    rsiPeriod: int
    rsiStatus: str
    rsiOverbought: float
    rsiOversold: float
    trend: str
    signal: str
    candles: List[dict]
    weekly_candles: List[dict] = []
    alias: Optional[str] = ""
    # Weekly Indicators
    weeklyMA5: Optional[float] = None
    weeklyMacdStatus: Optional[str] = None
    weeklyPriceVsMA5: Optional[str] = None
    weeklyMacdHist: Optional[float] = None
    # Resonance Strategy
    resonanceInPool: Optional[bool] = None
    resonanceBuySignal: Optional[bool] = None
    resonancePoolReason: Optional[str] = None
    resonanceBuyReason: Optional[str] = None
    resonanceStrategyVersion: Optional[str] = None
    resonancePoolType: Optional[str] = None
    resonanceEntryScore: Optional[int] = None
    resonanceRiskScore: Optional[int] = None
    resonanceRiskLevel: Optional[str] = None
    resonanceEntryPrice: Optional[float] = None
    resonanceStopPrice: Optional[float] = None
    resonanceRiskPercent: Optional[float] = None
    resonanceTargetPrice: Optional[float] = None
    resonanceRewardRiskRatio: Optional[float] = None
    resonanceExitSignal: Optional[bool] = None
    resonanceExitLevel: Optional[str] = None
    resonanceExitReason: Optional[str] = None
    macdDivergence: Optional[dict] = None

class Group(BaseModel):
    id: str
    name: str
    symbols: List[SymbolItem] # Changed from List[str]
    collapsed: bool = False

class AddStockRequest(BaseModel):
    symbol: str
    groupId: Optional[str] = None
    alias: Optional[str] = ""

class CreateGroupRequest(BaseModel):
    name: str

class UpdateWatchlistRequest(BaseModel):
    groups: List[Group]


class SupertrendScanCoverage(BaseModel):
    requested: int
    returned: int
    missing: List[str]


class SupertrendScanDecision(BaseModel):
    permission: Literal["buy", "wait", "watch", "risk", "blocked"]
    label: str
    setup: str
    stage: str
    reasonCodes: List[str]
    failedGates: List[str]
    nextTrigger: Optional[str] = None
    invalidation: Optional[str] = None
    maxAcceptablePrice: Optional[float] = None


class SupertrendScanItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    symbol: str
    state: Literal["bull", "bull_flip", "bear", "bear_flip"]
    weeklyState: Optional[Literal["bull", "bull_flip", "bear", "bear_flip"]] = None
    dailySessionComplete: Optional[bool] = None
    market: str
    marketMode: str
    primaryGroup: str
    tags: List[str]
    decision: SupertrendScanDecision


class SupertrendScanGroup(BaseModel):
    count: int
    symbols: List[str]


class SupertrendScanMarketMode(BaseModel):
    model_config = ConfigDict(extra="allow")
    mode: Literal["seek", "cautious", "survival", "insufficient"]
    representatives: List[str]
    directions: dict
    adxThreshold: Optional[float] = None
    missingSymbols: List[str]


class SupertrendScanResponse(BaseModel):
    schemaVersion: int
    policyVersion: str
    includesCandles: bool
    generatedAt: str
    coverage: SupertrendScanCoverage
    thresholds: dict
    marketModes: dict[str, SupertrendScanMarketMode]
    groups: dict[str, SupertrendScanGroup]
    items: List[SupertrendScanItem]

class BatchQuoteRequest(BaseModel):
    symbols: List[str]
    timeframe: Literal["1D", "1W"] = "1D"


def normalize_symbols(symbols: List[str]) -> List[str]:
    """标准化 symbol 列表：去空、去重、转大写、排序。"""
    return sorted({s.strip().upper() for s in symbols if isinstance(s, str) and s.strip()})


def _clean_etag(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("W/"):
        cleaned = cleaned[2:]
    return cleaned.strip('"')


def etag_matches(if_none_match: Optional[str], current_etag: str) -> bool:
    """支持 If-None-Match 多值与弱 ETag 的匹配。"""
    if not if_none_match:
        return False
    normalized_current = _clean_etag(current_etag)
    for candidate in if_none_match.split(","):
        tag = candidate.strip()
        if tag == "*":
            return True
        if _clean_etag(tag) == normalized_current:
            return True
    return False


def build_quotes_etag(symbols: List[str], payload: dict, latest_mtime: Optional[float]) -> str:
    """为批量行情响应生成稳定 ETag。"""
    hash_input = json.dumps(
        {
            "symbols": symbols,
            "latest_mtime": round(latest_mtime, 3) if latest_mtime else None,
            "payload": payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()[:32]
    return f"\"{digest}\""


def build_cache_headers(
    etag: str,
    latest_mtime: Optional[float],
    latest_data_ts: Optional[float],
    data_stale: bool,
    refresh_triggered: bool,
) -> dict:
    last_modified_ts = latest_mtime if latest_mtime is not None else time.time()
    updated_ts = latest_data_ts if latest_data_ts is not None else last_modified_ts
    last_modified = formatdate(last_modified_ts, usegmt=True)
    updated_at = datetime.fromtimestamp(updated_ts, tz=timezone.utc).isoformat()
    return {
        "ETag": etag,
        "Last-Modified": last_modified,
        "Cache-Control": "private, no-cache",
        "X-Data-Updated-At": updated_at,
        "X-Data-Stale": "1" if data_stale else "0",
        "X-Refresh-Triggered": "1" if refresh_triggered else "0",
    }

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Trading Backend is running"}


@app.get("/api/symbol/resolve", response_model=List[SymbolResolveCandidate])
def resolve_symbol(q: str = ""):
    return resolve_symbol_candidates(q)


@app.get("/api/data-sources/status")
def api_data_source_status():
    return get_data_source_status()


@app.get("/api/quote/{symbol}", response_model=StockResponse)
def get_quote(symbol: str):
    try:
        data = analyze_stock(symbol.upper())
    except MarketDataUnavailableError as exc:
        headers = (
            {"Retry-After": str(exc.retry_after)}
            if exc.retry_after is not None
            else None
        )
        raise HTTPException(
            status_code=503,
            detail=str(exc),
            headers=headers,
        ) from exc
    if not data:
        raise HTTPException(status_code=404, detail="Stock not found or insufficient data")
    return data

@app.post("/api/quotes/batch")
def get_batch_quotes(
    request: BatchQuoteRequest,
    if_none_match: Optional[str] = Header(default=None, alias="If-None-Match"),
):
    """批量获取股票摘要数据（列表页使用，不含 K 线数据）"""
    normalized_symbols = normalize_symbols(request.symbols)
    if not normalized_symbols:
        return JSONResponse(content={})

    start_total = time.perf_counter()
    refresh_triggered = False

    # 第一步：仅读缓存，不在请求路径阻塞网络下载
    with timer(f"批量读取缓存 ({len(normalized_symbols)} 只股票)"):
        cache_info = get_cached_batch_summaries(normalized_symbols)
    response_payload = cache_info["results"]

    # 冷启动兜底：首次请求且全量无缓存，允许限时同步刷新（超时后转后台继续）
    if not response_payload and not if_none_match:
        with timer("冷启动限时刷新"):
            completed = refresh_symbols_sync_with_timeout(
                normalized_symbols,
                timeout_seconds=COLD_START_SYNC_TIMEOUT_SECONDS,
                reason="cold_start",
            )
        if not completed:
            refresh_triggered = True
        cache_info = get_cached_batch_summaries(normalized_symbols)
        response_payload = cache_info["results"]

    refresh_candidates = sorted(set(cache_info["stale_symbols"] + cache_info["missing_symbols"]))
    if refresh_candidates:
        if refresh_symbols_async(refresh_candidates, reason="batch_swr"):
            refresh_triggered = True

    data_stale = bool(cache_info["stale_symbols"] or cache_info["missing_symbols"])
    etag = build_quotes_etag(normalized_symbols, response_payload, cache_info["latest_mtime"])
    headers = build_cache_headers(
        etag=etag,
        latest_mtime=cache_info["latest_mtime"],
        latest_data_ts=cache_info["latest_data_ts"],
        data_stale=data_stale,
        refresh_triggered=refresh_triggered,
    )

    if etag_matches(if_none_match, etag):
        end_total = time.perf_counter()
        logger.info(f"==> [总耗时] 批量获取接口完成(304): {end_total - start_total:.4f} 秒")
        return Response(status_code=304, headers=headers)

    end_total = time.perf_counter()
    logger.info(f"==> [总耗时] 批量获取接口完成: {end_total - start_total:.4f} 秒")
    return JSONResponse(content=response_payload, headers=headers)

@app.post("/api/quotes/batch/charts")
def get_batch_charts(request: BatchQuoteRequest):
    """批量获取迷你 K 线图数据（列表页缩略图使用）"""
    if not request.symbols:
        return {}
    timeframe = request.timeframe or "1D"
    results = batch_fetch_and_update(request.symbols)
    response = {}
    for symbol, result_tuple in results.items():
        if timeframe == "1W":
            df = result_tuple[1]
        else:
            df = result_tuple[0]
        if df is not None and not df.empty:
            response[symbol] = _build_mini_candles(df)
    return response

@app.get("/api/watchlist")
def get_watchlist():
    """Returns watchlist structure (groups and symbols) without detailed analysis."""
    groups = load_watchlist()
    return groups

@app.post("/api/watchlist")
def add_to_watchlist(request: AddStockRequest):
    """Add symbol to a group (default: first group)."""
    symbol = normalize_watchlist_symbol(request.symbol)
    if not symbol:
        raise HTTPException(status_code=400, detail="Invalid symbol")
    
    groups = load_watchlist()
    
    # Find target group
    target_group = None
    if request.groupId:
        for g in groups:
            if g["id"] == request.groupId:
                target_group = g
                break
    else:
        target_group = groups[0] if groups else None
    
    if not target_group:
        raise HTTPException(status_code=400, detail="No group found")
    
    # Check if already exists in any group
    for g in groups:
        for s in g["symbols"]:
            if s["symbol"] == symbol:
                return {"message": "Symbol already in watchlist"}
    
    target_group["symbols"].append({
        "symbol": symbol,
        "alias": request.alias or ""
    })
    save_watchlist(groups)
    return {"message": "Symbol added"}

@app.delete("/api/watchlist/{symbol}")
def remove_from_watchlist(symbol: str):
    """Remove symbol from all groups."""
    symbol = symbol.strip().upper()
    groups = load_watchlist()
    
    found = False
    for g in groups:
        # Filter out the symbol (checking s['symbol'] since s is now a dict)
        original_len = len(g["symbols"])
        g["symbols"] = [s for s in g["symbols"] if s["symbol"] != symbol]
        if len(g["symbols"]) < original_len:
            found = True
    
    if found:
        save_watchlist(groups)
        return {"message": "Symbol removed"}
    
    raise HTTPException(status_code=404, detail="Symbol not found in watchlist")

@app.put("/api/watchlist/{symbol}/alias")
def update_alias(symbol: str, request: UpdateAliasRequest):
    """Update alias for a specific symbol."""
    symbol = symbol.strip().upper()
    groups = load_watchlist()
    found = False
    
    for g in groups:
        for s in g["symbols"]:
            if s["symbol"] == symbol:
                s["alias"] = request.alias
                found = True
                # Break inner loop, but keep checking if symbol exists in multiple groups (though usually unique)
    
    if found:
        save_watchlist(groups)
        return {"message": "Alias updated"}
        
    raise HTTPException(status_code=404, detail="Symbol not found")

@app.post("/api/groups")
def create_group(request: CreateGroupRequest):
    """Create a new group."""
    groups = load_watchlist()
    new_group = {
        "id": str(uuid.uuid4()),
        "name": request.name,
        "symbols": [],
        "collapsed": False
    }
    groups.append(new_group)
    save_watchlist(groups)
    return new_group

@app.put("/api/watchlist")
def update_watchlist(request: UpdateWatchlistRequest):
    """Replace entire watchlist structure (for drag & drop reordering)."""
    groups = [g.dict() for g in request.groups]
    save_watchlist(groups)
    return {"message": "Watchlist updated"}


class BacktestRequest(BaseModel):
    universe_file: str = "universes/a_share_etf_core.json"
    strategy_version: str = "resonance_v2_atr_2_0_csi300_entry_buffer_1_0_etf_established"
    start: Optional[str] = None
    end: Optional[str] = None
    max_hold_days: int = 30
    cooldown_bars: int = 3
    fee_bps: float = 5.0
    slippage_bps: float = 5.0
    portfolio_max_positions: int = 5
    rs_top_n: int = 5
    rs_rebalance_days: int = 20
    rs_lookback_bars: int = 60
    rs_min_history_bars: int = 250
    rs_min_avg_volume: float = 1e8
    rs_preset: Optional[str] = None  # "rs_rotation_a_share" or "rs_rotation_global"


def _build_rs_rotation(request: "BacktestRequest", benchmark_frames: dict, data_dir: str) -> dict:
    import pandas as pd
    preset_id = request.rs_preset
    if preset_id and preset_id in RS_ROTATION_PRESETS:
        preset = RS_ROTATION_PRESETS[preset_id]
        frames = dict(benchmark_frames)
        for s in preset["extra_symbols"]:
            p = os.path.join(data_dir, f"{s}.parquet")
            if os.path.exists(p):
                frames[s] = pd.read_parquet(p)
        # resolve filter dfs
        per_class = {}
        for cls, (sym, mode) in preset["per_class_filters"].items():
            p = os.path.join(data_dir, f"{sym.upper()}.parquet")
            fdf = pd.read_parquet(p) if os.path.exists(p) else None
            per_class[cls] = (fdf, mode)
        return simulate_rs_rotation_portfolio(
            frames, top_n=request.rs_top_n, rebalance_days=request.rs_rebalance_days,
            lookback_bars=request.rs_lookback_bars, start=request.start, end=request.end,
            fee_bps=request.fee_bps, slippage_bps=request.slippage_bps,
            min_history_bars=0, min_avg_volume=preset["min_avg_volume"],
            per_class_filters=per_class,
        )
    return simulate_rs_rotation_portfolio(
        benchmark_frames, top_n=request.rs_top_n, rebalance_days=request.rs_rebalance_days,
        lookback_bars=request.rs_lookback_bars, start=request.start, end=request.end,
        fee_bps=request.fee_bps, slippage_bps=request.slippage_bps,
        min_history_bars=request.rs_min_history_bars, min_avg_volume=request.rs_min_avg_volume,
    )


@app.post("/api/backtest")
def run_backtest(request: BacktestRequest):
    from analysis import DATA_DIR
    import pandas as pd

    try:
        symbols = load_universe_symbols(request.universe_file)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    version = get_strategy_version(request.strategy_version)
    market_symbol = version.market_symbol
    market_regime_daily = None
    if market_symbol:
        import os
        mp = os.path.join(DATA_DIR, f"{market_symbol.upper()}.parquet")
        if os.path.exists(mp):
            import pandas as pd
            market_regime_daily = pd.read_parquet(mp)

    all_trades = []
    benchmark_daily_frames = {}
    missing = []
    import os
    for symbol in symbols:
        daily_path = os.path.join(DATA_DIR, f"{symbol.upper()}.parquet")
        weekly_path = os.path.join(DATA_DIR, f"{symbol.upper()}_weekly.parquet")
        if not os.path.exists(daily_path) or not os.path.exists(weekly_path):
            missing.append(symbol)
            continue
        import pandas as pd
        daily = pd.read_parquet(daily_path)
        weekly = pd.read_parquet(weekly_path)
        if not version.asset_class_filter or classify_asset(symbol) == version.asset_class_filter:
            benchmark_daily_frames[symbol.upper()] = daily
        all_trades.extend(run_backtest_for_symbol(
            symbol, daily, weekly,
            strategy_version=request.strategy_version,
            max_hold_days=request.max_hold_days,
            cooldown_bars=request.cooldown_bars,
            fee_bps=request.fee_bps,
            slippage_bps=request.slippage_bps,
            market_regime_daily=market_regime_daily,
            market_filter=version.market_filter,
            entry_market_filter=version.entry_market_filter,
            entry_market_min_close_vs_ema20_pct=version.entry_market_min_close_vs_ema20_pct,
            start=request.start,
            end=request.end,
        ))

    if benchmark_daily_frames:
        all_trades = annotate_relative_strength(all_trades, benchmark_daily_frames)

    report = summarize_backtest_report(
        all_trades,
        strategy_version=request.strategy_version,
        asset_class_filter=version.asset_class_filter,
        pool_type_filter=version.pool_type_filter,
        relative_strength_bucket_filter=version.relative_strength_bucket_filter,
        portfolio_max_positions=request.portfolio_max_positions,
        benchmark_daily_frames=benchmark_daily_frames if benchmark_daily_frames else None,
        benchmark_start=request.start,
        benchmark_end=request.end,
        fee_bps=request.fee_bps,
        slippage_bps=request.slippage_bps,
    )

    rs_rotation = _build_rs_rotation(request, benchmark_daily_frames, DATA_DIR)

    return {**report, "rsRotationPortfolio": rs_rotation, "missingSymbols": missing}


def _is_rs_holdings_cache_valid(cache: dict) -> bool:
    """缓存有效条件：今天是交易日则当天计算过；否则上一个交易日计算过。"""
    cached_date = cache.get("cached_date")
    if not cached_date:
        return False
    tz = ZoneInfo("Asia/Shanghai")
    now = datetime.now(tz).date()
    cached = datetime.fromisoformat(cached_date).date()
    # 简单判断：同一自然日内有效（非交易日也不会有新数据）
    return cached >= now


def _load_rs_holdings_cache() -> dict | None:
    if not os.path.exists(RS_HOLDINGS_CACHE_FILE):
        return None
    try:
        with open(RS_HOLDINGS_CACHE_FILE) as f:
            cache = json.load(f)
        if _is_rs_holdings_cache_valid(cache):
            return cache.get("data")
    except Exception:
        pass
    return None


def _save_rs_holdings_cache(data: dict) -> None:
    os.makedirs(os.path.dirname(RS_HOLDINGS_CACHE_FILE), exist_ok=True)
    tz = ZoneInfo("Asia/Shanghai")
    payload = {"cached_date": datetime.now(tz).isoformat(), "data": data}
    with open(RS_HOLDINGS_CACHE_FILE, "w") as f:
        json.dump(payload, f, ensure_ascii=False)


@app.get("/api/rs-rotation/holdings")
def get_rs_rotation_holdings(force: bool = False):
    """返回两个 RS 轮动预设当前持仓（最新 rebalance 选出的 top5），结果按天缓存。"""
    if not force:
        cached = _load_rs_holdings_cache()
        if cached is not None:
            return cached

    from analysis import DATA_DIR
    import pandas as pd

    universe_symbols = load_universe_symbols("universes/a_share_etf_core.json")
    frames_a: dict = {}
    for s in universe_symbols:
        p = os.path.join(DATA_DIR, f"{s.upper()}.parquet")
        if os.path.exists(p):
            frames_a[s.upper()] = pd.read_parquet(p)

    result = {}
    for preset_id, preset in RS_ROTATION_PRESETS.items():
        frames = dict(frames_a)
        for s in preset["extra_symbols"]:
            p = os.path.join(DATA_DIR, f"{s}.parquet")
            if os.path.exists(p):
                frames[s] = pd.read_parquet(p)
        per_class = {}
        for cls, (sym, mode) in preset["per_class_filters"].items():
            p = os.path.join(DATA_DIR, f"{sym.upper()}.parquet")
            fdf = pd.read_parquet(p) if os.path.exists(p) else None
            per_class[cls] = (fdf, mode)
        rotation = simulate_rs_rotation_portfolio(
            frames, top_n=5, rebalance_days=20, lookback_bars=60,
            fee_bps=5.0, slippage_bps=5.0,
            min_history_bars=0, min_avg_volume=preset["min_avg_volume"],
            per_class_filters=per_class,
        )
        last = rotation["equityCurve"][-1] if rotation["equityCurve"] else {}
        result[preset_id] = {
            "label": preset["label"],
            "holdings": last.get("holdings", []),
            "date": last.get("date"),
        }

    _save_rs_holdings_cache(result)
    return result


@app.get("/api/backtest/strategies")
def list_strategies():
    return [{"id": v.id, "label": v.label} for v in list_strategy_versions()] + list_rs_rotation_presets()


def _history_cache_key(
    symbol: str,
    strategy: str,
    start: Optional[str],
    end: Optional[str],
    min_adx_for_entry: Optional[float],
    weekly_filter: bool,
    exit_mode: str = SUPER_TREND_DEFAULT_HISTORY_EXIT_MODE,
    execution_mode: str = SUPER_TREND_EXECUTION_MODE,
) -> str:
    return json.dumps(
        {
            "symbol": symbol.strip().upper(),
            "strategy": strategy,
            "executionMode": execution_mode,
            "exitMode": exit_mode,
            "start": start or None,
            "end": end or None,
            "minAdxForEntry": float(min_adx_for_entry) if min_adx_for_entry is not None else None,
            "weeklyFilter": bool(weekly_filter),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _history_cache_path(db_path: Optional[str] = None) -> str:
    return db_path or HISTORY_TRADES_CACHE_FILE


def _ensure_history_cache(db_path: Optional[str] = None) -> None:
    db_path = _history_cache_path(db_path)
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS history_trade_reviews (
                cache_key TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                strategy TEXT NOT NULL,
                start_date TEXT,
                end_date TEXT,
                min_adx_for_entry REAL,
                weekly_filter INTEGER NOT NULL,
                data_mtime REAL NOT NULL,
                payload_json TEXT NOT NULL,
                computed_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_history_trade_reviews_symbol ON history_trade_reviews(symbol)")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(history_trade_reviews)").fetchall()}
        if "exit_mode" not in columns:
            conn.execute("ALTER TABLE history_trade_reviews ADD COLUMN exit_mode TEXT")
        if "execution_mode" not in columns:
            conn.execute("ALTER TABLE history_trade_reviews ADD COLUMN execution_mode TEXT")


def _normalize_history_exit_mode(exit_mode: str) -> str:
    normalized = (exit_mode or SUPER_TREND_DEFAULT_HISTORY_EXIT_MODE).strip()
    if normalized not in SUPER_TREND_HISTORY_EXIT_MODES:
        raise HTTPException(status_code=400, detail=f"Unsupported exit_mode: {exit_mode}")
    return normalized


def load_history_trade_cache(
    symbol: str,
    strategy: str,
    start: Optional[str],
    end: Optional[str],
    min_adx_for_entry: Optional[float],
    weekly_filter: bool,
    data_mtime: float,
    db_path: Optional[str] = None,
    exit_mode: str = SUPER_TREND_DEFAULT_HISTORY_EXIT_MODE,
) -> Optional[dict]:
    db_path = _history_cache_path(db_path)
    if not os.path.exists(db_path):
        return None
    _ensure_history_cache(db_path)
    key = _history_cache_key(
        symbol,
        strategy,
        start,
        end,
        min_adx_for_entry,
        weekly_filter,
        exit_mode,
        SUPER_TREND_EXECUTION_MODE,
    )
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT payload_json, data_mtime, execution_mode FROM history_trade_reviews WHERE cache_key = ?",
            (key,),
        ).fetchone()
    if row is None:
        return None
    payload_json, cached_mtime, cached_execution_mode = row
    if cached_execution_mode not in (None, SUPER_TREND_EXECUTION_MODE):
        return None
    if float(cached_mtime) < float(data_mtime):
        return None
    payload = json.loads(payload_json)
    summary = payload.get("summary") if isinstance(payload, dict) else None
    if not isinstance(summary, dict) or "maxDrawdownPct" not in summary:
        return None
    if "benchmark" not in payload or "strategyComparisons" not in payload:
        return None
    if payload.get("exitMode") is not None and payload.get("exitMode") != exit_mode:
        return None
    if payload.get("executionMode") != SUPER_TREND_EXECUTION_MODE:
        return None
    return payload


def save_history_trade_cache(
    payload: dict,
    data_mtime: float,
    db_path: Optional[str] = None,
    min_adx_for_entry: Optional[float] = None,
    weekly_filter: bool = False,
    exit_mode: str = SUPER_TREND_DEFAULT_HISTORY_EXIT_MODE,
) -> None:
    db_path = _history_cache_path(db_path)
    _ensure_history_cache(db_path)
    symbol = str(payload.get("symbol", "")).strip().upper()
    strategy = str(payload.get("strategy", "supertrend"))
    start = payload.get("start")
    end = payload.get("end")
    payload_exit_mode = str(payload.get("exitMode") or exit_mode)
    payload_execution_mode = str(payload.get("executionMode") or SUPER_TREND_EXECUTION_MODE)
    payload.setdefault("executionMode", payload_execution_mode)
    key = _history_cache_key(
        symbol,
        strategy,
        start,
        end,
        min_adx_for_entry,
        weekly_filter,
        payload_exit_mode,
        payload_execution_mode,
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO history_trade_reviews (
                cache_key, symbol, strategy, start_date, end_date, min_adx_for_entry,
                weekly_filter, exit_mode, execution_mode, data_mtime, payload_json, computed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                exit_mode = excluded.exit_mode,
                execution_mode = excluded.execution_mode,
                data_mtime = excluded.data_mtime,
                payload_json = excluded.payload_json,
                computed_at = excluded.computed_at
            """,
            (
                key,
                symbol,
                strategy,
                start,
                end,
                float(min_adx_for_entry) if min_adx_for_entry is not None else None,
                1 if weekly_filter else 0,
                payload_exit_mode,
                payload_execution_mode,
                float(data_mtime),
                json.dumps(payload, ensure_ascii=False, allow_nan=False),
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def _valid_history_symbol(symbol: str) -> bool:
    normalized = symbol.strip().upper()
    if not normalized:
        return False
    if " " in normalized:
        return False
    if normalized.startswith((".", "-", "=")):
        return False
    return any(ch.isalnum() for ch in normalized)


def _add_catalog_item(catalog: dict, symbol: str, name: str = "", source: str = "") -> None:
    normalized = symbol.strip().upper() if isinstance(symbol, str) else ""
    if not _valid_history_symbol(normalized):
        return
    existing = catalog.get(normalized, {})
    catalog[normalized] = {
        "symbol": normalized,
        "name": existing.get("name") or (name.strip() if isinstance(name, str) else ""),
        "source": existing.get("source") or source,
    }


def collect_history_trade_symbol_catalog(
    universe_files: Optional[List[str]] = None,
) -> dict:
    catalog: dict = {}

    for group in load_watchlist():
        for item in group.get("symbols", []):
            if isinstance(item, dict):
                _add_catalog_item(catalog, item.get("symbol", ""), item.get("alias", ""), "watchlist")
            else:
                _add_catalog_item(catalog, item, "", "watchlist")

    resolved_universe_files = (
        ["universes/a_share_etf_core.json", "universes/etf_core.json"]
        if universe_files is None
        else universe_files
    )
    for universe_file in resolved_universe_files:
        if not os.path.exists(universe_file):
            continue
        try:
            with open(universe_file, "r") as f:
                payload = json.load(f)
        except Exception:
            continue
        raw_symbols = payload.get("symbols", []) if isinstance(payload, dict) else payload
        for item in raw_symbols:
            if isinstance(item, dict):
                _add_catalog_item(catalog, item.get("symbol", ""), item.get("name", ""), universe_file)
            else:
                _add_catalog_item(catalog, item, "", universe_file)

    if os.path.exists(DATA_DIR):
        for filename in os.listdir(DATA_DIR):
            if not filename.endswith(".parquet") or filename.endswith("_weekly.parquet"):
                continue
            _add_catalog_item(catalog, filename[:-8], "", "data")

    return dict(sorted(catalog.items()))


def collect_watchlist_history_trade_symbol_catalog(symbols: Optional[List[str]] = None) -> dict:
    requested = set(normalize_symbols(symbols)) if symbols else None
    catalog: dict = {}
    for group in load_watchlist():
        for item in group.get("symbols", []):
            if isinstance(item, dict):
                symbol = item.get("symbol", "")
                name = item.get("alias", "")
            else:
                symbol = item
                name = ""
            normalized = symbol.strip().upper() if isinstance(symbol, str) else ""
            if requested is not None and normalized not in requested:
                continue
            _add_catalog_item(catalog, normalized, name, "watchlist")
    return dict(sorted(catalog.items()))


def _cached_symbols(db_path: Optional[str] = None) -> dict:
    db_path = _history_cache_path(db_path)
    if not os.path.exists(db_path):
        return {}
    _ensure_history_cache(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT symbol, MAX(computed_at), COUNT(*)
            FROM history_trade_reviews
            GROUP BY symbol
            """
        ).fetchall()
    return {symbol: {"cachedAt": computed_at, "cacheCount": count} for symbol, computed_at, count in rows}


@app.get("/api/history-trades/symbols")
def list_history_trade_symbols(universe_files: Optional[List[str]] = None):
    require_ready = universe_files is None
    catalog = (
        collect_history_trade_symbol_catalog(universe_files=universe_files)
        if universe_files is not None
        else collect_history_trade_symbol_catalog(universe_files=[])
    )
    cached = _cached_symbols()
    for symbol in cached.keys():
        _add_catalog_item(catalog, symbol, "", "cache")
    results = []
    for symbol, item in catalog.items():
        daily_path = os.path.join(DATA_DIR, f"{symbol}.parquet")
        cache_info = cached.get(symbol, {})
        has_data = os.path.exists(daily_path)
        has_cache = symbol in cached
        if require_ready and not (has_data and has_cache):
            continue
        name = item.get("name", "")
        results.append({
            "symbol": symbol,
            "name": name,
            "displayName": f"{symbol} · {name}" if name else symbol,
            "source": item.get("source", ""),
            "hasData": has_data,
            "hasCache": has_cache,
            "cachedAt": cache_info.get("cachedAt"),
            "cacheCount": cache_info.get("cacheCount", 0),
        })
    return results


def _history_data_mtime(symbol: str, weekly_filter: bool = False) -> float:
    paths = [os.path.join(DATA_DIR, f"{symbol}.parquet")]
    if weekly_filter:
        weekly_path = os.path.join(DATA_DIR, f"{symbol}_weekly.parquet")
        if os.path.exists(weekly_path):
            paths.append(weekly_path)
    return max(os.path.getmtime(path) for path in paths if os.path.exists(path))


def _default_history_precompute_start(today=None) -> str:
    current = today or datetime.now(PREWARM_TZ).date()
    if isinstance(current, datetime):
        current = current.date()
    try:
        start_date = current.replace(year=current.year - 5)
    except ValueError:
        start_date = current.replace(year=current.year - 5, day=28)
    return start_date.isoformat()


@app.get("/api/history-trades")
def get_history_trades(
    symbol: str,
    strategy: str = "supertrend",
    start: Optional[str] = None,
    end: Optional[str] = None,
    min_adx_for_entry: Optional[float] = None,
    weekly_filter: bool = False,
    exit_mode: str = SUPER_TREND_DEFAULT_HISTORY_EXIT_MODE,
):
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        raise HTTPException(status_code=400, detail="Invalid symbol")

    if strategy != "supertrend":
        raise HTTPException(status_code=400, detail=f"Unsupported strategy: {strategy}")
    resolved_exit_mode = _normalize_history_exit_mode(exit_mode)

    import pandas as pd

    daily_path = os.path.join(DATA_DIR, f"{normalized_symbol}.parquet")
    if not os.path.exists(daily_path):
        raise HTTPException(status_code=404, detail=f"No cached data for symbol: {normalized_symbol}")

    data_mtime = _history_data_mtime(normalized_symbol, weekly_filter=weekly_filter)
    cached = load_history_trade_cache(
        normalized_symbol,
        strategy,
        start,
        end,
        min_adx_for_entry,
        weekly_filter,
        data_mtime=data_mtime,
        exit_mode=resolved_exit_mode,
    )
    if cached is not None:
        return cached

    daily = pd.read_parquet(daily_path)
    weekly = None
    if weekly_filter:
        weekly_path = os.path.join(DATA_DIR, f"{normalized_symbol}_weekly.parquet")
        if os.path.exists(weekly_path):
            weekly = pd.read_parquet(weekly_path)

    payload = build_supertrend_history_review(
        normalized_symbol,
        daily,
        start=start,
        end=end,
        filter_weekly_df=weekly,
        min_adx_for_entry=min_adx_for_entry,
        exit_mode=resolved_exit_mode,
    )
    save_history_trade_cache(
        payload,
        data_mtime=data_mtime,
        min_adx_for_entry=min_adx_for_entry,
        weekly_filter=weekly_filter,
        exit_mode=resolved_exit_mode,
    )
    return payload


@app.post("/api/history-trades/precompute")
def precompute_history_trades(
    strategy: str = "supertrend",
    start: Optional[str] = None,
    end: Optional[str] = None,
    min_adx_for_entry: Optional[float] = None,
    weekly_filter: bool = False,
    exit_mode: str = SUPER_TREND_DEFAULT_HISTORY_EXIT_MODE,
    force: bool = False,
    symbols: Optional[List[str]] = None,
):
    if strategy != "supertrend":
        raise HTTPException(status_code=400, detail=f"Unsupported strategy: {strategy}")
    resolved_exit_mode = _normalize_history_exit_mode(exit_mode)

    import pandas as pd

    resolved_start = start or _default_history_precompute_start()
    catalog = collect_watchlist_history_trade_symbol_catalog(symbols=symbols)
    computed = 0
    cached_count = 0
    downloaded = 0
    skipped_missing = []
    failed = []

    for symbol in catalog.keys():
        daily_path = os.path.join(DATA_DIR, f"{symbol}.parquet")
        if not os.path.exists(daily_path):
            try:
                batch_fetch_and_update([symbol])
            except Exception as exc:
                failed.append({"symbol": symbol, "error": f"download failed: {exc}"})
                continue
            if os.path.exists(daily_path):
                downloaded += 1
            else:
                skipped_missing.append(symbol)
                continue
        try:
            data_mtime = _history_data_mtime(symbol, weekly_filter=weekly_filter)
            if not force and load_history_trade_cache(
                symbol,
                strategy,
                resolved_start,
                end,
                min_adx_for_entry,
                weekly_filter,
                data_mtime=data_mtime,
                exit_mode=resolved_exit_mode,
            ) is not None:
                cached_count += 1
                continue

            daily = pd.read_parquet(daily_path)
            weekly = None
            if weekly_filter:
                weekly_path = os.path.join(DATA_DIR, f"{symbol}_weekly.parquet")
                if os.path.exists(weekly_path):
                    weekly = pd.read_parquet(weekly_path)
            payload = build_supertrend_history_review(
                symbol,
                daily,
                start=resolved_start,
                end=end,
                filter_weekly_df=weekly,
                min_adx_for_entry=min_adx_for_entry,
                exit_mode=resolved_exit_mode,
            )
            save_history_trade_cache(
                payload,
                data_mtime=data_mtime,
                min_adx_for_entry=min_adx_for_entry,
                weekly_filter=weekly_filter,
                exit_mode=resolved_exit_mode,
            )
            computed += 1
        except Exception as exc:
            failed.append({"symbol": symbol, "error": str(exc)})

    return {
        "strategy": strategy,
        "executionMode": SUPER_TREND_EXECUTION_MODE,
        "exitMode": resolved_exit_mode,
        "start": resolved_start,
        "end": end,
        "computed": computed,
        "cached": cached_count,
        "downloaded": downloaded,
        "skippedMissingData": len(skipped_missing),
        "skippedMissingSymbols": skipped_missing,
        "failed": failed,
        "dbPath": HISTORY_TRADES_CACHE_FILE,
    }


@app.get("/api/weekly-breakout/scan")
def weekly_breakout_scan():
    """扫描所有 watchlist 标的的周线BB突破状态，返回九宫格所需数据。"""
    import pandas as pd
    from analysis import DATA_DIR

    groups = load_watchlist()
    symbols = []
    alias_map = {}
    for g in groups:
        for item in g.get("symbols", []):
            sym = item["symbol"] if isinstance(item, dict) else item
            if sym not in symbols:
                symbols.append(sym)
                alias_map[sym] = item.get("alias", "") if isinstance(item, dict) else ""

    results = []
    for sym in symbols:
        daily_path = os.path.join(DATA_DIR, f"{sym.upper()}.parquet")
        weekly_path = os.path.join(DATA_DIR, f"{sym.upper()}_weekly.parquet")
        daily = pd.read_parquet(daily_path) if os.path.exists(daily_path) else None
        if not os.path.exists(weekly_path):
            if daily is None:
                continue
            from analysis_data import _calculate_weekly_indicators
            weekly = _calculate_weekly_indicators(daily.copy())
        else:
            weekly = pd.read_parquet(weekly_path)

        required = {"Close", "BOLL_Upper", "BOLL_Lower", "BOLL_Mid", "MA30"}
        if not required.issubset(weekly.columns):
            from analysis_data import _calculate_weekly_indicators
            if daily is not None:
                weekly = _calculate_weekly_indicators(daily.copy())

        daily_required = {"Close", "EMA20", "MA30"}
        if daily is not None and not daily_required.issubset(daily.columns):
            from analysis_data import _calculate_daily_indicators
            daily = _calculate_daily_indicators(daily.copy())

        signal = evaluate_weekly_bb_breakout(weekly)
        pullback_signal = evaluate_weekly_bb_pullback(weekly, daily)
        exit_sig = evaluate_weekly_bb_exit(weekly)

        # Ensure weekly ST fields exist
        if "ST_Val" not in weekly.columns or "ST_Dir" not in weekly.columns:
            from analysis_constants import ST_LENGTH, ST_MULTIPLIER
            import pandas_ta as ta
            st = ta.supertrend(weekly["High"], weekly["Low"], weekly["Close"], length=ST_LENGTH, multiplier=ST_MULTIPLIER)
            if st is not None:
                st_val_col = next((c for c in st.columns if "SUPERT_" in c and "d" not in c.lower() and "l" not in c.lower()), None)
                st_dir_col = next((c for c in st.columns if "SUPERTd_" in c), None)
                if st_val_col:
                    weekly["ST_Val"] = st[st_val_col]
                if st_dir_col:
                    weekly["ST_Dir"] = st[st_dir_col]

        w = weekly.dropna(subset=["Close"]) if not weekly.empty else weekly
        last = w.iloc[-1] if not w.empty else None

        def _fv(row, col):
            return float(row[col]) if col in row and pd.notna(row[col]) else None

        # Build last 26 weekly candles for mini chart
        chart_rows = w.tail(26)
        markers = replay_weekly_bb_markers(chart_rows)
        candles = []
        for ts, row in chart_rows.iterrows():
            candles.append({
                "time": pd.Timestamp(ts).date().isoformat(),
                "open": _fv(row, "Open") or float(row["Close"]),
                "high": _fv(row, "High") or float(row["Close"]),
                "low": _fv(row, "Low") or float(row["Close"]),
                "close": float(row["Close"]),
                "boll_upper": _fv(row, "BOLL_Upper"),
                "boll_mid": _fv(row, "BOLL_Mid"),
                "boll_lower": _fv(row, "BOLL_Lower"),
                "ma30": _fv(row, "MA30"),
                "ma5": _fv(row, "MA5_W"),
                "macd_dif": _fv(row, "MACD_DIF"),
                "macd_dea": _fv(row, "MACD_DEA"),
                "macd_hist": _fv(row, "MACD_Hist"),
                "st_val": _fv(row, "ST_Val"),
                "st_dir": int(row["ST_Dir"]) if "ST_Dir" in row and pd.notna(row["ST_Dir"]) else None,
            })

        # Build last 260 daily candles
        daily_candles = []
        if daily is not None:
            if "ST_Val" not in daily.columns or "ST_Dir" not in daily.columns:
                from analysis_constants import ST_LENGTH, ST_MULTIPLIER
                import pandas_ta as ta
                st = ta.supertrend(daily["High"], daily["Low"], daily["Close"], length=ST_LENGTH, multiplier=ST_MULTIPLIER)
                if st is not None:
                    st_val_col = next((c for c in st.columns if "SUPERT_" in c and "d" not in c.lower() and "l" not in c.lower()), None)
                    st_dir_col = next((c for c in st.columns if "SUPERTd_" in c), None)
                    if st_val_col:
                        daily["ST_Val"] = st[st_val_col]
                    if st_dir_col:
                        daily["ST_Dir"] = st[st_dir_col]
            d = daily.dropna(subset=["Close"])
            for ts, row in d.tail(65).iterrows():
                daily_candles.append({
                    "time": pd.Timestamp(ts).date().isoformat(),
                    "open": _fv(row, "Open") or float(row["Close"]),
                    "high": _fv(row, "High") or float(row["Close"]),
                    "low": _fv(row, "Low") or float(row["Close"]),
                    "close": float(row["Close"]),
                    "boll_upper": _fv(row, "BOLL_Upper"),
                    "boll_mid": _fv(row, "BOLL_Mid"),
                    "boll_lower": _fv(row, "BOLL_Lower"),
                    "ma30": _fv(row, "MA30"),
                    "ma5": _fv(row, "MA5") if "MA5" in row else None,
                    "macd_dif": _fv(row, "MACD_DIF"),
                    "macd_dea": _fv(row, "MACD_DEA"),
                    "macd_hist": _fv(row, "MACD_Hist"),
                    "st_val": _fv(row, "ST_Val"),
                    "st_dir": int(row["ST_Dir"]) if "ST_Dir" in row and pd.notna(row["ST_Dir"]) else None,
                })

        # Determine signal state
        if signal.get("buySignal"):
            state = "breakout"
            active_signal = signal
        elif pullback_signal.get("buySignal"):
            state = "pullback"
            active_signal = pullback_signal
        elif exit_sig.get("exitSignal"):
            state = "exit"
            active_signal = {}
        elif last is not None and "BOLL_Upper" in last and "BOLL_Lower" in last and "BOLL_Mid" in last and pd.notna(last.get("BOLL_Upper")):
            bw = (float(last["BOLL_Upper"]) - float(last["BOLL_Lower"])) / float(last["BOLL_Mid"]) if float(last["BOLL_Mid"]) != 0 else 0
            # Check if squeezing: compare current bw to 20-week mean
            recent_bw = (w.tail(20)["BOLL_Upper"] - w.tail(20)["BOLL_Lower"]) / w.tail(20)["BOLL_Mid"].replace(0, float("nan"))
            state = "squeeze" if bool(bw < recent_bw.mean() * 0.85) else "neutral"
            active_signal = {}
        else:
            state = "neutral"
            active_signal = {}

        results.append({
            "symbol": sym.upper(),
            "alias": alias_map.get(sym, ""),
            "state": state,
            "stopPrice": active_signal.get("stopPrice"),
            "entryType": active_signal.get("entryType"),
            "candles": candles,
            "daily_candles": daily_candles,
            "markers": markers,
        })

    return results


ST_SCAN_REFRESH_THRESHOLD_SECONDS = 15 * 60
ST_SCAN_MISSING_REFRESH_TIMEOUT_SECONDS = 8.0
ST_SCAN_STALE_REFRESH_TIMEOUT_SECONDS = 5.0

_st_scan_cache: dict = {"data": None, "ts": 0.0}


def _st_scan_response_view(payload: dict, include_candles: bool) -> dict:
    if include_candles:
        return payload
    compact = copy.deepcopy(payload)
    compact["includesCandles"] = False
    for item in compact.get("items", []):
        item.pop("candles", None)
        item.pop("weeklyCandles", None)
    return compact


def _st_path(symbol: str, weekly: bool = False) -> str:
    from analysis import DATA_DIR as current_data_dir
    suffix = "_weekly.parquet" if weekly else ".parquet"
    return os.path.join(current_data_dir, f"{symbol.upper()}{suffix}")


def _st_file_mtime(path: str) -> Optional[float]:
    try:
        return os.path.getmtime(path) if os.path.exists(path) else None
    except OSError:
        return None


def _st_iso_from_timestamp(timestamp: Optional[float]) -> Optional[str]:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _st_latest_data_date(df) -> Optional[str]:
    if df is None or df.empty:
        return None
    try:
        index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
        if index.empty:
            return None
        return index.max().date().isoformat()
    except Exception:
        return None


def _st_is_a_share_symbol(symbol: str) -> bool:
    normalized = symbol.upper()
    code = normalized.split(".", 1)[0]
    return normalized.endswith((".SS", ".SZ")) and code.isdigit() and len(code) == 6


def _st_recent_gap_info(symbol: str, df) -> dict:
    """保守的 A 股近期缺口提示：只检查最近窗口，避免节假日历史误报。"""
    empty = {"hasGap": False, "firstMissingDate": None, "expectedLatestDate": None}
    if not _st_is_a_share_symbol(symbol) or df is None or df.empty:
        return empty
    try:
        dates = pd.DatetimeIndex(df.index).tz_localize(None).normalize().unique().sort_values()
    except Exception:
        return empty
    if len(dates) < 2:
        return empty

    latest = dates[-1]
    window_start = latest - pd.Timedelta(days=14)
    recent_dates = dates[dates >= window_start]
    if len(recent_dates) < 2:
        return empty

    expected = pd.bdate_range(recent_dates[0], recent_dates[-1])
    missing = expected.difference(recent_dates)
    if missing.empty:
        return empty

    return {
        "hasGap": True,
        "firstMissingDate": missing[0].date().isoformat(),
        "expectedLatestDate": None,
    }


def _st_data_stale(latest_data_date: Optional[str], integrity: dict) -> bool:
    if integrity.get("hasGap"):
        return True
    if not latest_data_date:
        return True
    try:
        latest = datetime.fromisoformat(latest_data_date).date()
    except ValueError:
        return True
    now_local = datetime.now(PREWARM_TZ).date()
    return (now_local - latest).days > 3


def _st_boll_context(
    close: pd.Series,
    period: int = 20,
    std_multiplier: float = 2.0,
    as_of: Optional[str] = None,
) -> dict:
    """Return a JSON-safe BOLL snapshot for one resampled close series."""
    clean = pd.to_numeric(close, errors="coerce").dropna()
    result = {
        "upper": None,
        "mid": None,
        "lower": None,
        "width": None,
        "distanceToMidPct": None,
        "position": None,
        "midSlopePct": None,
        "midDirection": None,
        "slopeSampleSufficient": len(clean) > period,
        "period": period,
        "sampleSize": int(len(clean)),
        "asOf": as_of or (pd.Timestamp(clean.index[-1]).date().isoformat() if not clean.empty else None),
    }
    if len(clean) < period:
        return result

    window = clean.tail(period)
    current = float(window.iloc[-1])
    mid = float(window.mean())
    std = float(window.std(ddof=0))
    upper = mid + std_multiplier * std
    lower = mid - std_multiplier * std
    mid_slope_pct = None
    mid_direction = None
    if len(clean) > period:
        previous_mid = float(clean.iloc[-period - 1:-1].mean())
        if previous_mid != 0:
            mid_slope_pct = (mid - previous_mid) / previous_mid * 100
            if mid_slope_pct > 0.05:
                mid_direction = "rising"
            elif mid_slope_pct < -0.05:
                mid_direction = "falling"
            else:
                mid_direction = "flat"

    if current > upper:
        position = "above_upper"
    elif current >= mid:
        position = "upper_half"
    elif current >= lower:
        position = "lower_half"
    else:
        position = "below_lower"

    result.update({
        "upper": upper,
        "mid": mid,
        "lower": lower,
        "width": (upper - lower) / mid if mid != 0 else None,
        "distanceToMidPct": (current - mid) / mid * 100 if mid != 0 else None,
        "position": position,
        "midSlopePct": mid_slope_pct,
        "midDirection": mid_direction,
    })
    return result


def _st_volume_session_complete(
    symbol: str,
    as_of: Optional[str],
    now: Optional[datetime] = None,
) -> Optional[bool]:
    """Return whether a daily volume bar belongs to a completed market session."""
    return is_daily_session_complete(symbol, as_of, now=now)


def _st_multitimeframe_context(
    daily: pd.DataFrame,
    symbol: str = "",
    now: Optional[datetime] = None,
) -> dict:
    """Build weekly/monthly BOLL structure plus comparable daily volume context."""
    empty_boll = _st_boll_context(pd.Series(dtype=float))
    empty_volume = {
        "current": None,
        "ma20": None,
        "ratio20": None,
        "ratio20Completed": None,
        "sessionComplete": None,
        "period": 20,
        "asOf": None,
    }
    if daily is None or daily.empty or "Close" not in daily.columns:
        return {
            "weeklyBoll": empty_boll,
            "monthlyBoll": empty_boll.copy(),
            "volumeContext": empty_volume,
        }

    ordered = daily.sort_index()
    close = pd.to_numeric(ordered["Close"], errors="coerce").dropna()
    weekly_close = close.resample("W").last().dropna()
    monthly_close = close.resample("ME").last().dropna()
    latest_close_date = pd.Timestamp(close.index[-1]).date().isoformat() if not close.empty else None
    reference_now = now or datetime.now(timezone.utc)
    current_month = pd.Timestamp(reference_now.date()).to_period("M")
    latest_month = pd.Timestamp(close.index[-1]).to_period("M") if not close.empty else None
    monthly_period_complete = latest_month is not None and latest_month < current_month
    completed_monthly_close = monthly_close if monthly_period_complete else monthly_close.iloc[:-1]

    volume_context = empty_volume.copy()
    if "Volume" in ordered.columns:
        volume = pd.to_numeric(ordered["Volume"], errors="coerce").dropna()
        if not volume.empty:
            current = float(volume.iloc[-1])
            ma20 = float(volume.tail(20).mean())
            volume_as_of = pd.Timestamp(volume.index[-1]).date().isoformat()
            session_complete = _st_volume_session_complete(symbol, volume_as_of, now=now)
            ratio20 = current / ma20 if ma20 > 0 else None
            volume_context.update({
                "current": current,
                "ma20": ma20,
                "ratio20": ratio20,
                "ratio20Completed": ratio20 if session_complete else None,
                "sessionComplete": session_complete,
                "asOf": volume_as_of,
            })

    monthly_boll = _st_boll_context(monthly_close, as_of=latest_close_date)
    decision_monthly_boll = _st_boll_context(completed_monthly_close)
    monthly_boll.update({
        "periodComplete": monthly_period_complete,
        "decisionMidDirection": decision_monthly_boll.get("midDirection"),
        "decisionMidSlopePct": decision_monthly_boll.get("midSlopePct"),
        "decisionAsOf": decision_monthly_boll.get("asOf"),
    })

    return {
        "weeklyBoll": _st_boll_context(weekly_close, as_of=latest_close_date),
        "monthlyBoll": monthly_boll,
        "volumeContext": volume_context,
    }


def _st_scan_signature(symbols: List[str]) -> list:
    signature = []
    for sym in symbols:
        daily_path = _st_path(sym)
        weekly_path = _st_path(sym, weekly=True)
        signature.append({
            "symbol": sym.upper(),
            "dailyMtime": _st_file_mtime(daily_path),
            "weeklyMtime": _st_file_mtime(weekly_path),
        })
    return signature


def _refresh_supertrend_symbols(symbols: List[str], timeout_seconds: float) -> bool:
    if not symbols:
        return True

    completed = {"done": False}

    def worker():
        try:
            batch_fetch_and_update(symbols)
            completed["done"] = True
        except Exception as exc:
            logger.warning(f"SuperTrend 扫描预刷新失败: {exc}")

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout_seconds)
    return completed["done"]

@app.get("/api/supertrend/scan", response_model=SupertrendScanResponse)
def supertrend_scan(force: bool = False, include_candles: bool = False):
    """扫描所有 watchlist 标的并返回统一的右侧交易决策契约。"""
    import pandas as pd
    from analysis_constants import ST_LENGTH, ST_MULTIPLIER

    groups = load_watchlist()
    user_symbols, alias_map = [], {}
    for g in groups:
        for item in g.get("symbols", []):
            sym = item["symbol"] if isinstance(item, dict) else item
            if sym not in user_symbols:
                user_symbols.append(sym)
                alias_map[sym] = item.get("alias", "") if isinstance(item, dict) else ""
    representative_symbols = list(dict.fromkeys(symbol for values in SYSTEM_MARKET_REPRESENTATIVES.values() for symbol in values))
    symbols = list(dict.fromkeys(user_symbols + representative_symbols))
    representative_set = set(representative_symbols)

    cache_symbols = _st_scan_cache.get("symbols")
    cache_signature = _st_scan_cache.get("signature")
    signature = _st_scan_signature(symbols)
    if (
        not force
        and _st_scan_cache["data"] is not None
        and cache_symbols == symbols
        and cache_signature == signature
    ):
        return _st_scan_response_view(_st_scan_cache["data"], include_candles)

    refresh_symbols = []
    missing_symbols = []
    stale_before = time.time() - ST_SCAN_REFRESH_THRESHOLD_SECONDS
    for sym in symbols:
        daily_path = _st_path(sym)
        if not os.path.exists(daily_path):
            refresh_symbols.append(sym)
            missing_symbols.append(sym)
            continue
        try:
            if force or os.path.getmtime(daily_path) < stale_before:
                refresh_symbols.append(sym)
        except OSError:
            continue

    refresh_completed = True
    if refresh_symbols:
        refresh_timeout = (
            ST_SCAN_MISSING_REFRESH_TIMEOUT_SECONDS
            if missing_symbols
            else ST_SCAN_STALE_REFRESH_TIMEOUT_SECONDS
        )
        refresh_completed = _refresh_supertrend_symbols(refresh_symbols, refresh_timeout)

    signature = _st_scan_signature(symbols)
    if (
        not force
        and refresh_completed
        and _st_scan_cache["data"] is not None
        and cache_symbols == symbols
        and cache_signature == signature
    ):
        return _st_scan_response_view(_st_scan_cache["data"], include_candles)

    import pandas_ta as ta

    def _process_sym(sym):
        daily_path = _st_path(sym)
        if not os.path.exists(daily_path):
            return None
        daily_mtime = _st_file_mtime(daily_path)
        daily = pd.read_parquet(daily_path)
        if daily.empty:
            return None
        daily = daily.sort_index()
        latest_data_date = _st_latest_data_date(daily)
        daily_session_complete = _st_volume_session_complete(sym, latest_data_date)
        data_integrity = _st_recent_gap_info(sym, daily)
        cache_stale = daily_mtime is None or daily_mtime < stale_before
        data_stale = _st_data_stale(latest_data_date, data_integrity)

        st = ta.supertrend(daily["High"], daily["Low"], daily["Close"], length=ST_LENGTH, multiplier=ST_MULTIPLIER)
        if st is None or st.empty:
            return None
        val_col = next((c for c in st.columns if c.startswith("SUPERT_") and not any(c.startswith(p) for p in ("SUPERTd_", "SUPERTs_", "SUPERTl_", "SUPERTu_"))), None)
        dir_col = next((c for c in st.columns if c.startswith("SUPERTd_")), None)
        if not val_col or not dir_col:
            return None

        daily["_st_val"] = st[val_col]
        daily["_st_dir"] = st[dir_col]
        if "ATR" not in daily.columns or daily["ATR"].isnull().all():
            daily["ATR"] = ta.atr(daily["High"], daily["Low"], daily["Close"], length=14)

        decision_daily = daily if daily_session_complete is not False else daily.iloc[:-1]
        decision_as_of = _st_latest_data_date(decision_daily)
        decision_daily_available = not decision_daily.empty
        all_dir_rows = daily.dropna(subset=["_st_dir"])
        formal_rows = decision_daily.dropna(subset=["Close"])
        last = formal_rows.iloc[-1] if not formal_rows.empty else daily.dropna(subset=["Close"]).iloc[-1]
        cur_dir = int(last["_st_dir"]) if pd.notna(last.get("_st_dir")) else 0
        dir_rows = decision_daily.dropna(subset=["_st_dir"])
        provisional_state, _ = classify_trend_state(all_dir_rows["_st_dir"].tail(2).tolist())
        state, just_flipped = (
            classify_trend_state(dir_rows["_st_dir"].tail(2).tolist())
            if decision_daily_available
            else (provisional_state, False)
        )

        trend_age_bars = 0
        if cur_dir != 0:
            for direction in reversed([int(r) for r in dir_rows["_st_dir"].tolist()]):
                if direction != cur_dir:
                    break
                trend_age_bars += 1

        def _to_candles(df, val_key, dir_key, n):
            rows = []
            for ts, row in df.sort_index().tail(n).iterrows():
                rows.append({
                    "time": pd.Timestamp(ts).date().isoformat(),
                    "open": float(row["Open"]) if pd.notna(row.get("Open")) else float(row["Close"]),
                    "high": float(row["High"]) if pd.notna(row.get("High")) else float(row["Close"]),
                    "low": float(row["Low"]) if pd.notna(row.get("Low")) else float(row["Close"]),
                    "close": float(row["Close"]),
                    "st_val": float(row[val_key]) if pd.notna(row.get(val_key)) else None,
                    "st_dir": int(row[dir_key]) if pd.notna(row.get(dir_key)) else None,
                })
            return rows

        candles = _to_candles(decision_daily, "_st_val", "_st_dir", 60)

        weekly_state = None
        weekly_st_val = None
        weekly_candles = []
        weekly = None
        weekly_just_flipped = False
        weekly_provisional_state = None
        weekly_period_complete = None
        wcur_dir = 0
        wprev_rows = None
        weekly_path = _st_path(sym, weekly=True)
        if os.path.exists(weekly_path):
            weekly = pd.read_parquet(weekly_path)
            if not weekly.empty:
                weekly = weekly.sort_index()
                wst = ta.supertrend(weekly["High"], weekly["Low"], weekly["Close"], length=ST_LENGTH, multiplier=ST_MULTIPLIER)
                if wst is not None and not wst.empty:
                    wval_col = next((c for c in wst.columns if c.startswith("SUPERT_") and not any(c.startswith(p) for p in ("SUPERTd_", "SUPERTs_", "SUPERTl_", "SUPERTu_"))), None)
                    wdir_col = next((c for c in wst.columns if c.startswith("SUPERTd_")), None)
                    if wval_col and wdir_col:
                        weekly["_wst_val"] = wst[wval_col]
                        weekly["_wst_dir"] = wst[wdir_col]
                        all_weekly_rows = weekly.dropna(subset=["_wst_dir"])
                        weekly_provisional_state, _ = classify_trend_state(
                            all_weekly_rows["_wst_dir"].tail(2).tolist()
                        )
                        completed_weekly = filter_completed_weekly_bars(sym, weekly, decision_as_of)
                        if not completed_weekly.empty:
                            completed_through = completed_weekly.index[-1]
                            wprev_rows = all_weekly_rows.loc[all_weekly_rows.index <= completed_through]
                        if wprev_rows is not None and not wprev_rows.empty:
                            wlast = wprev_rows.dropna(subset=["Close"]).iloc[-1]
                            wcur_dir = int(wlast["_wst_dir"]) if pd.notna(wlast.get("_wst_dir")) else 0
                            weekly_state, weekly_just_flipped = classify_trend_state(
                                wprev_rows["_wst_dir"].tail(2).tolist()
                            )
                            weekly_st_val = float(wlast["_wst_val"]) if pd.notna(wlast.get("_wst_val")) else None
                            weekly_period_complete = wprev_rows.index[-1] == all_weekly_rows.index[-1]
                        weekly_candles = _to_candles(weekly, "_wst_val", "_wst_dir", 30)

        # Weekly trend age (consecutive bars in current weekly ST direction)
        weekly_trend_age_bars = 0
        if wcur_dir is not None and wcur_dir != 0:
            for wdir in reversed([int(r) for r in wprev_rows["_wst_dir"].tolist()]):
                if wdir != wcur_dir:
                    break
                weekly_trend_age_bars += 1

        # Quality indicators from daily parquet (already pre-computed)
        def _fv(key, default=None):
            val = last.get(key)
            return float(val) if pd.notna(val) else default

        macd_hist_rows = (
            pd.to_numeric(daily.loc[:last.name, "MACD_Hist"], errors="coerce").dropna().tail(2)
            if "MACD_Hist" in daily.columns
            else pd.Series(dtype=float)
        )
        macd_hist_prev = float(macd_hist_rows.iloc[-2]) if len(macd_hist_rows) >= 2 else None
        macd_hist_current = _fv("MACD_Hist")

        indicators = {
            "adx": _fv("ADX"),
            "rsi7": _fv("RSI_7"),
            "rsi14": _fv("RSI_14"),
            "rsi21": _fv("RSI_21"),
            "macdDif": _fv("MACD_DIF"),
            "macdDea": _fv("MACD_DEA"),
            "macdHist": macd_hist_current,
            "macdHistPrev": macd_hist_prev,
            "macdHistDelta": (
                macd_hist_current - macd_hist_prev
                if macd_hist_current is not None and macd_hist_prev is not None
                else None
            ),
            "kdjK": _fv("K"),
            "kdjD": _fv("D"),
            "kdjJ": _fv("J"),
            "bollUpper": _fv("BOLL_Upper"),
            "bollMid": _fv("BOLL_Mid"),
            "bollLower": _fv("BOLL_Lower"),
            "atr": _fv("ATR"),
        }

        # Daily BOLL squeeze detection
        boll_upper = _fv("BOLL_Upper")
        boll_lower = _fv("BOLL_Lower")
        boll_mid = _fv("BOLL_Mid")
        boll_width = None
        is_squeeze = False
        if all(v is not None for v in (boll_upper, boll_lower, boll_mid)) and boll_mid != 0:
            boll_width = (boll_upper - boll_lower) / boll_mid
            # Compare to 20-period mean bandwidth
            recent = daily.dropna(subset=["BOLL_Upper", "BOLL_Lower", "BOLL_Mid"]).tail(20)
            if len(recent) >= 10:
                recent_bw = (recent["BOLL_Upper"] - recent["BOLL_Lower"]) / recent["BOLL_Mid"].replace(0, float("nan"))
                avg_bw = recent_bw.mean()
                if pd.notna(avg_bw) and avg_bw > 0:
                    is_squeeze = bool(boll_width < avg_bw * 0.85)
        indicators["bollWidth"] = boll_width
        indicators["bollSqueeze"] = is_squeeze
        macd_divergence = build_macd_divergence_summary(sym, daily, weekly)
        multitimeframe_context = _st_multitimeframe_context(daily, symbol=sym)

        alert = classify_supertrend_alert(
            state=state,
            weekly_state=weekly_state,
            close=float(last["Close"]) if pd.notna(last.get("Close")) else None,
            st_val=float(last["_st_val"]) if pd.notna(last.get("_st_val")) else None,
            atr=float(last["ATR"]) if pd.notna(last.get("ATR")) else None,
            just_flipped=state in ("bull_flip", "bear_flip"),
            trend_age_bars=trend_age_bars,
        )

        return {
            "symbol": sym.upper(),
            "alias": alias_map.get(sym, ""),
            "state": state,
            "dailyProvisionalState": provisional_state,
            "decisionDailyState": state if decision_daily_available else None,
            "decisionAsOf": decision_as_of,
            "decisionDailyAvailable": decision_daily_available,
            "isCrypto": sym.upper().endswith("-USD"),
            "close": float(last["Close"]) if pd.notna(last.get("Close")) else None,
            "stVal": float(last["_st_val"]) if pd.notna(last.get("_st_val")) else None,
            "candles": candles,
            "weeklyState": weekly_state,
            "weeklyProvisionalState": weekly_provisional_state,
            "weeklyPeriodComplete": weekly_period_complete,
            "weeklyStVal": weekly_st_val,
            "weeklyCandles": weekly_candles,
            "justFlipped": state in ("bull_flip", "bear_flip"),
            "weeklyJustFlipped": weekly_just_flipped,
            "trendAgeBars": trend_age_bars,
            "dailySessionComplete": daily_session_complete,
            "latestDataDate": latest_data_date,
            "dataUpdatedAt": _st_iso_from_timestamp(daily_mtime),
            "cacheStale": cache_stale,
            "dataStale": data_stale,
            "refreshTriggered": bool(refresh_symbols) and not refresh_completed,
            "dataIntegrity": data_integrity,
            "indicators": indicators,
            "macdDivergence": macd_divergence,
            "bollWidth": boll_width,
            "bollSqueeze": is_squeeze,
            **multitimeframe_context,
            "weeklyTrendAgeBars": weekly_trend_age_bars,
            **alert,
        }

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = [r for r in executor.map(_process_sym, symbols) if r is not None]

    user_results = [item for item in results if item["symbol"] in set(user_symbols)]
    representative_results = [item for item in results if item["symbol"] in representative_set and item["symbol"] not in set(user_symbols)]
    response = build_scan_response(
        user_results,
        requested_symbols=user_symbols,
        representative_items=representative_results,
    )
    _st_scan_cache["data"] = response
    _st_scan_cache["ts"] = time.time()
    _st_scan_cache["symbols"] = symbols
    _st_scan_cache["signature"] = signature
    return _st_scan_response_view(response, include_candles)


def _next_prewarm_run(now_local: datetime) -> datetime:
    """计算下一个固定预热时间点（本地时区时间）。"""
    today_candidates = [
        now_local.replace(hour=hour, minute=0, second=0, microsecond=0)
        for hour in PREWARM_HOURS
    ]
    for candidate in today_candidates:
        if candidate > now_local:
            return candidate
    return (now_local + timedelta(days=1)).replace(
        hour=PREWARM_HOURS[0],
        minute=0,
        second=0,
        microsecond=0,
    )


def _collect_watchlist_symbols() -> List[str]:
    groups = load_watchlist()
    symbols = []
    for group in groups:
        for item in group.get("symbols", []):
            symbol = item.get("symbol", "").strip().upper()
            if symbol:
                symbols.append(symbol)
    return normalize_symbols(symbols)


def refresh_watchlist_background():
    """后台任务：固定时点预热观察列表缓存。"""
    while True:
        try:
            now_local = datetime.now(PREWARM_TZ)
            next_run = _next_prewarm_run(now_local)
            sleep_seconds = max(1.0, (next_run - now_local).total_seconds())
            logger.info(
                "==> [后台预热] 下次执行时间: %s (%s), %.0f 秒后触发",
                next_run.strftime("%Y-%m-%d %H:%M:%S"),
                PREWARM_TZ.key,
                sleep_seconds,
            )
            time.sleep(sleep_seconds)

            symbols = _collect_watchlist_symbols()
            if symbols:
                triggered = refresh_symbols_async(
                    symbols,
                    reason="scheduled_prewarm",
                )
                if triggered:
                    logger.info(f"==> [后台预热] 已提交 {len(symbols)} 只股票刷新任务。")
                else:
                    logger.info("==> [后台预热] 本轮无可刷新股票（可能正在刷新中）。")
            else:
                logger.info("==> [后台预热] 观察列表为空，跳过本轮预热。")
        except Exception as e:
            logger.error(f"==> [后台预热] 作业出错: {e}")
            time.sleep(30)


def _try_become_prewarm_leader(lock_path: Optional[str] = None) -> bool:
    global _prewarm_leader_handle
    if _prewarm_leader_handle is not None:
        return False

    resolved_path = lock_path or os.path.join(
        DATA_DIR,
        ".provider-state",
        "prewarm-leader.lock",
    )
    os.makedirs(os.path.dirname(resolved_path), exist_ok=True)
    handle = open(resolved_path, "a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return False
    _prewarm_leader_handle = handle
    return True


def _start_background_prewarm() -> bool:
    if not BACKGROUND_PREWARM_ENABLED:
        logger.info("==> [系统启动] 后台预热已禁用")
        return False
    if not _try_become_prewarm_leader():
        logger.info("==> [系统启动] 当前 worker 非预热 leader")
        return False
    bg_thread = threading.Thread(
        target=refresh_watchlist_background,
        daemon=True,
        name="watchlist-prewarm",
    )
    bg_thread.start()
    logger.info("==> [系统启动] 当前 worker 已成为预热 leader")
    return True

# ---- Portfolio Strategy Paper Tracking Endpoints ----

@app.get("/api/portfolio-strategies", response_model=list[pm.StrategyListItem])
def api_list_portfolio_strategies():
    return _get_portfolio_service().list_strategies()


@app.get("/api/portfolio-strategies/{strategy_id}/snapshot", response_model=pm.SnapshotResponse)
def api_portfolio_snapshot(strategy_id: str):
    try:
        return _get_portfolio_service().get_snapshot(strategy_id)
    except UnknownStrategyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/portfolio-strategies/{strategy_id}/target-weights", response_model=pm.TargetWeightsResponse)
def api_portfolio_target_weights(strategy_id: str):
    try:
        return _get_portfolio_service().target_weights(strategy_id)
    except UnknownStrategyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/portfolio-strategies/{strategy_id}/rebalance-diff", response_model=pm.RebalanceDiffResponse)
def api_portfolio_rebalance_diff(strategy_id: str):
    try:
        return _get_portfolio_service().rebalance_diff(strategy_id)
    except UnknownStrategyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/portfolio-strategies/{strategy_id}/ledger", response_model=pm.LedgerEventsResponse)
def api_portfolio_ledger(
    strategy_id: str,
    limit: int = 50,
    cursor: int | None = None,
):
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
    try:
        return _get_portfolio_service().ledger_events(strategy_id, limit=limit, cursor=cursor)
    except UnknownStrategyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ComparisonStrategyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/api/portfolio-strategies/{strategy_id}/nav", response_model=pm.NavSeriesResponse)
def api_portfolio_nav(
    strategy_id: str,
    start: str | None = None,
    end: str | None = None,
):
    try:
        return _get_portfolio_service().nav_series(strategy_id, start=start, end=end)
    except UnknownStrategyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ComparisonStrategyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/api/portfolio-strategies/{strategy_id}/refresh", response_model=pm.SnapshotResponse)
def api_portfolio_refresh(strategy_id: str):
    try:
        return _get_portfolio_service().refresh(strategy_id)
    except UnknownStrategyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ComparisonStrategyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.on_event("startup")
async def startup_event():
    """系统启动时，启动后台维护线程"""
    logger.info("==> [系统启动] 正在启动后台数据管家...")
    _start_background_prewarm()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Trading backend utilities")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--precompute-history-trades", action="store_true")
    parser.add_argument("--symbol", action="append", help="Limit history precompute to a watchlist symbol")
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--min-adx-for-entry", type=float, default=None)
    parser.add_argument("--weekly-filter", action="store_true")
    parser.add_argument(
        "--exit-mode",
        choices=SUPER_TREND_HISTORY_EXIT_MODES,
        default=SUPER_TREND_DEFAULT_HISTORY_EXIT_MODE,
        help="SuperTrend history exit mode for trades, summary, and markers",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    if args.precompute_history_trades:
        target_symbols = normalize_symbols(args.symbol or [])
        result = precompute_history_trades(
            start=args.start,
            end=args.end,
            min_adx_for_entry=args.min_adx_for_entry,
            weekly_filter=args.weekly_filter,
            exit_mode=args.exit_mode,
            force=args.force,
            symbols=target_symbols or None,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
