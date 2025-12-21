from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from analysis import analyze_stock
import json
import os
import uuid

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
    trend: str
    signal: str
    candles: List[dict]
    alias: Optional[str] = ""  # Added alias capability

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

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Trading Backend is running"}

@app.get("/api/quote/{symbol}", response_model=StockResponse)
def get_quote(symbol: str):
    data = analyze_stock(symbol.upper())
    if not data:
        raise HTTPException(status_code=404, detail="Stock not found or insufficient data")
    return data

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
