from __future__ import annotations

import threading

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.models.analysis import BacktestRequest, SpeedRequest
from cryptoagents.backtest.engine import BacktestEngine, SPEEDS
from cryptoagents.backtest.monte_carlo import run_monte_carlo
from cryptoagents.strategy.strategies import get_strategy

router = APIRouter(prefix="/backtest", tags=["回测"])

_tasks: dict[str, BacktestEngine] = {}
_results: dict[str, dict] = {}
_progress: dict[str, dict] = {}   # task_id -> 最新进度快照 (供轮询)


def _on_progress(task_id: str, data: dict):
    """进度回调 — 在工作线程中执行, 只更新内存快照 (供 HTTP 轮询读取)。"""
    _progress[task_id] = data


def _run_thread(engine: BacktestEngine, task_id: str):
    try:
        result = engine.run()
        if not engine._cancelled:
            _results[task_id] = result.to_dict()
            _progress[task_id] = {"task_id": task_id, "status": "completed",
                                  "progress_pct": 100.0, "result": result.to_dict()}
        else:
            _progress[task_id] = {"task_id": task_id, "status": "cancelled", "progress_pct": 0.0}
    except Exception as exc:
        _progress[task_id] = {"task_id": task_id, "status": "error", "error": str(exc)}
    finally:
        _tasks.pop(task_id, None)


@router.post("/run")
def run_backtest(req: BacktestRequest):
    s = get_strategy(req.strategy_id)
    tf = getattr(req, "timeframe", None) or "15m"
    engine = BacktestEngine(req.symbol, req.start_date, req.end_date, s,
                            req.initial_capital, req.leverage,
                            speed=req.speed, timeframe=tf)
    engine.position_size_pct = getattr(req, 'position_size_pct', 2.0)
    engine.progress_callback = lambda d: _on_progress(engine.task_id, d)
    _tasks[engine.task_id] = engine
    _progress[engine.task_id] = {"task_id": engine.task_id, "status": "running", "progress_pct": 0.0}
    threading.Thread(target=_run_thread, args=(engine, engine.task_id), daemon=True).start()
    return {"task_id": engine.task_id, "status": "running", "speed": req.speed}


@router.get("/{task_id}/progress")
def get_progress(task_id: str):
    # 优先返回内存快照 (含 running 实时进度 / completed 结果)
    snap = _progress.get(task_id)
    if snap:
        return snap
    r = _results.get(task_id)
    if r:
        return {"task_id": task_id, "status": "completed", "progress_pct": 100.0, "result": r}
    raise HTTPException(404, "任务不存在")


@router.post("/{task_id}/cancel")
def cancel_backtest(task_id: str):
    e = _tasks.get(task_id)
    if not e: raise HTTPException(404, "任务不存在")
    e.cancel()
    return {"task_id": task_id, "status": "cancelled"}


@router.post("/{task_id}/speed")
def set_speed(task_id: str, req: SpeedRequest):
    e = _tasks.get(task_id)
    if not e: raise HTTPException(404, "任务不存在")
    if req.speed not in SPEEDS: raise HTTPException(400, f"倍速只支持: {SPEEDS}")
    e.set_speed(req.speed)
    return {"task_id": task_id, "new_speed": e.speed}


@router.get("/speeds")
def get_speeds():
    return {"speeds": [{"value": s, "label": f"{s}x", "fast": s >= 100} for s in SPEEDS]}


# ---------- 蒙特卡洛回测 ----------
class MCRequest(BaseModel):
    strategy_id: str = "S1"
    symbol: str = "BTC/USDT"
    timeframe: str = "15m"
    start_date: str = "2024-06-01"
    end_date: str = "2024-12-31"
    initial_capital: float = 10000.0
    leverage: int = 10
    n_runs: int = 50
    noise: float = 0.001
    skip_prob: float = 0.05


@router.post("/monte-carlo")
def run_monte_carlo_backtest(req: MCRequest):
    s = get_strategy(req.strategy_id)
    result = run_monte_carlo(
        s, req.symbol, req.start_date, req.end_date,
        req.initial_capital, req.leverage, req.timeframe,
        n=min(req.n_runs, 200), noise=req.noise, skip_prob=req.skip_prob,
    )
    return {"symbol": req.symbol, "strategy": req.strategy_id, "timeframe": req.timeframe,
            "summary": result.summary()}


@router.websocket("/ws/{task_id}")
async def ws_progress(websocket: WebSocket, task_id: str):
    """WebSocket 进度推送 — 从内存快照轮询并下发 (兼容旧前端)。"""
    import asyncio
    await websocket.accept()
    try:
        last = None
        while True:
            snap = _progress.get(task_id)
            if snap and snap != last:
                await websocket.send_json(snap)
                last = snap
                if snap.get("status") in ("completed", "cancelled", "error"):
                    break
            await asyncio.sleep(0.3)
    except (WebSocketDisconnect, Exception):
        pass
