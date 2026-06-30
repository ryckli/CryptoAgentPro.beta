from __future__ import annotations

import json
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from cryptoagents.strategy.strategies import (
    get_strategy, list_strategies, register_custom, unregister_custom,
)
from cryptoagents.strategy.scheduler import scheduler
from cryptoagents.data.ccxt_fetcher import CCXTFetcher
from cryptoagents.data.indicator_calc import compute_all_indicators

router = APIRouter(prefix="/strategy", tags=["策略"])


class CustomStrategyRequest(BaseModel):
    name: str
    base_type: str  # ema_cross / rsi / macd / boll
    params: dict = {}


@router.get("/list")
def get_list():
    return {"strategies": list_strategies()}


@router.get("/signal/{symbol:path}")
def get_signal(symbol: str, strategy_id: str = "S2"):
    s = get_strategy(strategy_id)
    fetcher = CCXTFetcher(with_keys=False, use_testnet=False)
    df = fetcher.fetch_ohlcv(symbol, s.timeframe(), limit=200)
    if df.empty:
        raise HTTPException(404, "无K线数据")
    signal = s.calculate(df)
    return signal.to_dict()


@router.get("/active/{symbol:path}")
def get_active(symbol: str):
    return {"symbol": symbol, "active_strategy": scheduler.get_current_strategy(symbol)}


@router.post("/activate")
def activate(symbol: str, strategy_id: str):
    get_strategy(strategy_id)  # 校验存在
    scheduler.current_strategy[symbol] = strategy_id
    return {"symbol": symbol, "active_strategy": strategy_id}


@router.get("/indicators/{symbol:path}")
def get_indicators(symbol: str, timeframe: str = "15m"):
    fetcher = CCXTFetcher(with_keys=False, use_testnet=False)
    df = fetcher.fetch_ohlcv(symbol, timeframe, limit=200)
    if df.empty:
        raise HTTPException(404, "无K线数据")
    return {"symbol": symbol, "timeframe": timeframe, "indicators": compute_all_indicators(df)}


# ---------- 自定义策略 ----------

def _load_custom_from_db():
    """启动/调用时从 DB 加载已保存的自定义策略到运行时。"""
    from app.models.strategy import CustomStrategy as CSModel
    from app.core.database import get_sqlite_session
    s = get_sqlite_session()
    for r in s.query(CSModel).filter(CSModel.enabled == 1).all():
        try:
            register_custom(r.id, r.name, r.base_type, json.loads(r.params_json or "{}"))
        except Exception:
            pass
    s.close()


@router.get("/custom/list")
def custom_list():
    _load_custom_from_db()
    from app.models.strategy import CustomStrategy as CSModel
    from app.core.database import get_sqlite_session
    s = get_sqlite_session()
    rows = s.query(CSModel).all()
    out = [{"id": r.id, "name": r.name, "base_type": r.base_type,
            "params": json.loads(r.params_json or "{}"), "enabled": bool(r.enabled)} for r in rows]
    s.close()
    return {"custom_strategies": out}


@router.post("/custom/create")
def custom_create(req: CustomStrategyRequest):
    from app.models.strategy import CustomStrategy as CSModel
    from app.core.database import get_sqlite_session
    sid = f"C{int(time.time())}"
    s = get_sqlite_session()
    s.add(CSModel(id=sid, name=req.name, base_type=req.base_type,
                  params_json=json.dumps(req.params), enabled=1, created_at=int(time.time())))
    s.commit()
    s.close()
    register_custom(sid, req.name, req.base_type, req.params)
    return {"status": "ok", "id": sid, "name": req.name}


@router.delete("/custom/{sid}")
def custom_delete(sid: str):
    from app.models.strategy import CustomStrategy as CSModel
    from app.core.database import get_sqlite_session
    s = get_sqlite_session()
    r = s.get(CSModel, sid)
    if r:
        s.delete(r)
        s.commit()
    s.close()
    unregister_custom(sid)
    return {"status": "ok", "deleted": sid}


# ---------- AI自适应优化 ----------

@router.get("/adaptive/params/{sid}")
def get_adaptive_params(sid: str):
    from cryptoagents.ai.adaptive_optimizer import get_params
    return {"strategy": sid, "params": get_params(sid)}


@router.post("/adaptive/params/{sid}")
def set_adaptive_params(sid: str, params: dict):
    from cryptoagents.ai.adaptive_optimizer import set_params
    set_params(sid, params)
    return {"status": "ok", "strategy": sid, "params": get_params(sid)}


@router.get("/adaptive/history")
def adaptive_history(sid: str = "", limit: int = 30):
    from cryptoagents.ai.adaptive_optimizer import get_adapt_history
    return {"history": get_adapt_history(sid, limit)}


@router.post("/adaptive/optimize-now")
def optimize_now():
    from cryptoagents.ai.adaptive_optimizer import optimize_all
    results = optimize_all()
    return {"status": "ok", "adjustments": len(results), "results": results}
