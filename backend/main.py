from fastapi import FastAPI, HTTPException, Header, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
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
)
from strategy_versions import get_strategy_version, list_strategy_versions
from analysis import (
    analyze_stock,
    batch_fetch_and_update,
    _build_mini_candles,
    get_cached_batch_summaries,
    refresh_symbols_async,
    refresh_symbols_sync_with_timeout,
)
import json
import os
import uuid
import time
import logging
import threading
import hashlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import formatdate
from zoneinfo import ZoneInfo

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

WATCHLIST_FILE = "watchlist.json"
RS_HOLDINGS_CACHE_FILE = "backtest_results/rs_holdings_cache.json"
PREWARM_HOURS = (9, 12, 15, 21)
PREWARM_TZ = ZoneInfo("Asia/Shanghai")
COLD_START_SYNC_TIMEOUT_SECONDS = 5.0

class UpdateAliasRequest(BaseModel):
    alias: str

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

@app.get("/api/quote/{symbol}", response_model=StockResponse)
def get_quote(symbol: str):
    data = analyze_stock(symbol.upper())
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
    symbol = request.symbol.strip().upper()
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
    """后台任务：固定时点预热观察列表缓存（Asia/Shanghai 09/12/15/21）。"""
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
                    min_interval_seconds=0,
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

@app.on_event("startup")
async def startup_event():
    """系统启动时，启动后台维护线程"""
    logger.info("==> [系统启动] 正在启动后台数据管家...")
    bg_thread = threading.Thread(target=refresh_watchlist_background, daemon=True)
    bg_thread.start()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
