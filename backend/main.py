from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from analysis import analyze_stock
import json
import os

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

def load_watchlist():
    if not os.path.exists(WATCHLIST_FILE):
        return []
    with open(WATCHLIST_FILE, "r") as f:
        return json.load(f)

def save_watchlist(watchlist):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(watchlist, f, indent=2)

class StockResponse(BaseModel):
    symbol: str
    name: str
    price: float
    changePercent: float
    ema20: float
    ema50: float
    adx: float
    trend: str
    trendStrength: str
    signal: str
    candles: List[dict]

class AddStockRequest(BaseModel):
    symbol: str

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
    symbols = load_watchlist()
    results = []
    
    # In a real app, this should be async or parallelized
    for sym in symbols:
        try:
            data = analyze_stock(sym)
            if data:
                results.append(data)
        except Exception as e:
            print(f"Error fetching {sym}: {e}")
            
    return results

@app.post("/api/watchlist")
def add_to_watchlist(request: AddStockRequest):
    symbol = request.symbol.strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="Invalid symbol")
        
    current_list = load_watchlist()
    if symbol in current_list:
        return {"message": "Symbol already in watchlist"}
    
    # Optional: Validate with analyze_stock first? 
    # Let's trust user or let frontend handle validation error if fetch fails later.
    
    current_list.append(symbol)
    save_watchlist(current_list)
    return {"message": "Symbol added", "watchlist": current_list}

@app.delete("/api/watchlist/{symbol}")
def remove_from_watchlist(symbol: str):
    symbol = symbol.strip().upper()
    current_list = load_watchlist()
    
    if symbol in current_list:
        current_list.remove(symbol)
        save_watchlist(current_list)
        return {"message": "Symbol removed", "watchlist": current_list}
    
    raise HTTPException(status_code=404, detail="Symbol not found in watchlist")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
