from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from cryptoagents.ai import ai_service
from cryptoagents.ai import news_service
from cryptoagents.ai import chat_service
from app.worker import scheduler_worker

router = APIRouter(prefix="/ai", tags=["AI趋势"])


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    symbol: str | None = None
    include_news: bool = True
    include_kline: bool = True
    auto_apply: bool = False  # 是否自动执行 AI 返回的创建策略动作


@router.get("/trend/{symbol:path}")
def get_trend(symbol: str):
    """实时趋势感知 (手动触发单币种)。"""
    report = ai_service.run_sensing(symbol, triggered_by="manual")
    return {"symbol": symbol, "trend": report, "strategy_switch": {"action": report.get("action", "keep")}}


@router.get("/reports")
def get_reports(symbol: str = "", limit: int = 50):
    """历史 AI 报告。"""
    return {"reports": ai_service.list_reports(symbol or None, limit)}


@router.post("/sense-now")
def sense_now():
    """立即对全部监控币种执行一次感知。"""
    reports = ai_service.run_sensing_all()
    return {"count": len(reports), "reports": reports}


@router.get("/schedule")
def get_schedule():
    return scheduler_worker.status()


@router.post("/schedule")
def set_schedule(enabled: bool = True, minutes: int = 15):
    from app.core import settings_store
    settings_store.set_many({"ai_schedule_enabled": enabled, "ai_schedule_minutes": minutes})
    scheduler_worker.reschedule(minutes)
    return scheduler_worker.status()


# ---------- 新闻 ----------

@router.get("/news")
def get_news(limit: int = 20, force: bool = False):
    return {"news": news_service.fetch_news(limit=limit, force=force)}


# ---------- AI 聊天 ----------

@router.post("/chat")
def chat(req: ChatRequest):
    msgs = [{"role": m.role, "content": m.content} for m in req.messages]
    result = chat_service.chat(msgs, symbol=req.symbol,
                               include_news=req.include_news, include_kline=req.include_kline)
    applied = None
    if result.get("action") and req.auto_apply:
        applied = chat_service.apply_action(result["action"])
    return {"reply": result["reply"], "action": result.get("action"), "applied": applied}


@router.post("/chat/apply-action")
def apply_action(action: dict):
    return chat_service.apply_action(action)


# ---------- 组合优化 ----------

@router.get("/portfolio")
def portfolio_analysis(symbols: str = "", capital: float = 10000):
    """多币种组合优化分析。"""
    from cryptoagents.execution import portfolio as pf
    sym_list = [s.strip() for s in symbols.split(",") if s.strip()] if symbols else settings.SYMBOLS_WATCHLIST
    return pf.allocation_summary(capital or settings.RISK_INITIAL_CAPITAL, sym_list)
