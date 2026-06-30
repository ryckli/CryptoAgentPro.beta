from __future__ import annotations

from fastapi import APIRouter

from cryptoagents.strategy.scheduler import scheduler

router = APIRouter(prefix="/scheduler", tags=["调度"])


@router.get("/status/{symbol:path}")
def get_status(symbol: str):
    pending = scheduler.pending_switches.get(symbol)
    return {
        "symbol": symbol,
        "current_strategy": scheduler.get_current_strategy(symbol),
        "has_pending": scheduler.has_pending(symbol),
        "pending": {
            "from": pending.from_strategy, "to": pending.to_strategy,
            "market_state": pending.ai_market_state, "confidence": pending.confidence,
            "reasoning": pending.reasoning,
        } if pending else None,
    }


@router.post("/confirm/{symbol:path}")
def confirm(symbol: str):
    return scheduler.confirm(symbol)


@router.post("/reject/{symbol:path}")
def reject(symbol: str):
    return scheduler.reject(symbol)
