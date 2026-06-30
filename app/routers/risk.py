from __future__ import annotations

from fastapi import APIRouter

from cryptoagents.risk.gateway import risk_gateway

router = APIRouter(prefix="/risk", tags=["风控"])


@router.get("/status")
def get_status():
    return risk_gateway.get_status()


@router.post("/reset")
def reset():
    risk_gateway.reset_daily()
    return {"status": "reset"}
