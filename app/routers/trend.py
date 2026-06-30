from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException

from cryptoagents.ai.trend_analyzer import analyze_trend
from cryptoagents.data.ccxt_fetcher import CCXTFetcher
from cryptoagents.strategy.scheduler import scheduler
from app.core.config import settings

router = APIRouter(prefix="/trend", tags=["AI趋势"])


@router.get("/{symbol}")
def get_trend(symbol: str):
    fetcher = CCXTFetcher()
    df_15m = fetcher.fetch_ohlcv(symbol, "15m", limit=200)
    df_1h = fetcher.fetch_ohlcv(symbol, "1h", limit=50)

    result = analyze_trend(symbol, df_15m, df_1h)
    switch = scheduler.on_trend_change(symbol, result.to_dict())

    from app.models.strategy import AITrendLog
    from app.core.database import get_sqlite_session
    session = get_sqlite_session()
    session.add(AITrendLog(timestamp=int(time.time()), symbol=symbol,
                           market_state=result.market_state, confidence=result.confidence,
                           recommended_str=result.recommended_strategy))
    session.commit()

    return {"symbol": symbol, "trend": result.to_dict(), "strategy_switch": switch}


@router.get("/history")
def get_history(symbol: str = "", limit: int = 50):
    from app.models.strategy import AITrendLog
    from app.core.database import get_sqlite_session
    session = get_sqlite_session()
    q = session.query(AITrendLog).order_by(AITrendLog.timestamp.desc()).limit(limit)
    if symbol:
        q = q.filter(AITrendLog.symbol == symbol)
    return {"history": [{"timestamp": l.timestamp, "symbol": l.symbol, "market_state": l.market_state,
                         "confidence": l.confidence, "recommended_strategy": l.recommended_str}
                        for l in q.all()]}


@router.post("/confirm-switch")
def confirm_switch(symbol: str):
    return scheduler.confirm(symbol)


@router.post("/reject-switch")
def reject_switch(symbol: str):
    return scheduler.reject(symbol)
