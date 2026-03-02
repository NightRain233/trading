from fastapi import FastAPI, HTTPException, Header, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional
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
    data_stale: bool,
    refresh_triggered: bool,
) -> dict:
    updated_ts = latest_mtime if latest_mtime is not None else time.time()
    last_modified = formatdate(updated_ts, usegmt=True)
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
    results = batch_fetch_and_update(request.symbols)
    response = {}
    for symbol, result_tuple in results.items():
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
