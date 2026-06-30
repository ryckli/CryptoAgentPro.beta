from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.core import settings_store

router = APIRouter(prefix="/settings", tags=["设置"])


class SettingsUpdate(BaseModel):
    # 全部可选, 仅更新提供的字段
    trading_mode: str | None = None
    auto_trade: bool | None = None
    exchange_name: str | None = None
    exchange_testnet: bool | None = None
    risk_initial_capital: float | None = None
    risk_max_leverage: int | None = None
    risk_max_loss_per_trade_pct: float | None = None
    risk_max_daily_loss_pct: float | None = None
    risk_min_stop_distance_pct: float | None = None
    strategy_switch_confirmation: bool | None = None
    watchlist: list[str] | None = None
    ai_schedule_enabled: bool | None = None
    ai_schedule_minutes: int | None = None
    ai_model: str | None = None
    ai_temperature: float | None = None


@router.get("")
def get_settings():
    return settings_store.get_all()


@router.post("")
def update_settings(req: SettingsUpdate):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    result = settings_store.set_many(updates)
    # 若改了风控本金, 重置风控网关本金
    if "risk_initial_capital" in updates:
        from cryptoagents.risk.gateway import risk_gateway
        risk_gateway.initial_capital = float(updates["risk_initial_capital"])
    # 若改了调度间隔, 重排任务
    if "ai_schedule_minutes" in updates or "ai_schedule_enabled" in updates:
        try:
            from app.worker.scheduler_worker import reschedule
            reschedule(int(result["ai_schedule_minutes"]))
        except Exception:
            pass
    return {"status": "ok", "settings": result}
