from __future__ import annotations

import json
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import init_db, close_db
from app.core.logging_config import setup_logging, get_logger
from app.middleware.operation_log import RequestIDMiddleware, OperationLogMiddleware


def _get_frontend_dir() -> Path | None:
    """查找前端静态文件目录 (dev: frontend/dist, exe: _MEIPASS/frontend)."""
    # PyInstaller 打包路径
    if getattr(sys, 'frozen', False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
        d = base / "frontend"
        if d.is_dir():
            return d
    # 开发路径
    candidates = [
        Path(__file__).resolve().parents[2] / "frontend" / "dist",
        Path("frontend/dist").resolve(),
    ]
    for d in candidates:
        if d.is_dir() and (d / "index.html").exists():
            return d
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger = get_logger("app")
    logger.info("Starting CryptoAgents Pro...")
    await init_db()
    logger.info("Database initialized")
    # 应用已保存的运行时设置
    try:
        from app.core import settings_store
        settings_store.apply_to_settings()
    except Exception as e:
        logger.warning(f"应用设置失败: {e}")
    # 启动 APScheduler 后台 AI 感知任务
    try:
        from app.worker.scheduler_worker import start_scheduler
        start_scheduler()
    except Exception as e:
        logger.warning(f"调度器启动失败: {e}")
    # 启动 30秒 AI 自适应参数优化
    try:
        from app.worker.adaptive_worker import start_adaptive
        start_adaptive()
    except Exception as e:
        logger.warning(f"自适应优化器启动失败: {e}")
    yield
    logger.info("Shutting down...")
    try:
        from app.worker.scheduler_worker import stop_scheduler
        stop_scheduler()
    except Exception:
        pass
    try:
        from app.worker.adaptive_worker import stop_adaptive
        stop_adaptive()
    except Exception:
        pass
    await close_db()


app = FastAPI(
    title="CryptoAgents Pro API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url=None,
)

# --- Middleware ---
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(RequestIDMiddleware)
app.add_middleware(OperationLogMiddleware)


# --- Global Exception Handler ---
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    from fastapi.responses import JSONResponse
    request_id = getattr(request.state, "trace_id", "unknown")
    get_logger("app").error(f"Unhandled exception: {exc}")
    return JSONResponse(status_code=500, content={"error": str(exc), "request_id": request_id})


# --- Route Registration ---
from app.routers.kline import router as kline_router
from app.routers.strategy import router as strategy_router
from app.routers.backtest import router as backtest_router
from app.routers.trend import router as trend_router
from app.routers.trade import router as trade_router
from app.routers.risk import router as risk_router
from app.routers.scheduler import router as scheduler_router
from app.routers.config import router as config_router
from app.routers.ai import router as ai_router
from app.routers.settings import router as settings_router
from app.routers.autopilot import router as autopilot_router

app.include_router(kline_router, prefix="/api/v1")
app.include_router(strategy_router, prefix="/api/v1")
app.include_router(backtest_router, prefix="/api/v1")
app.include_router(trend_router, prefix="/api/v1")
app.include_router(trade_router, prefix="/api/v1")
app.include_router(risk_router, prefix="/api/v1")
app.include_router(scheduler_router, prefix="/api/v1")
app.include_router(config_router, prefix="/api/v1")
app.include_router(ai_router, prefix="/api/v1")
app.include_router(settings_router, prefix="/api/v1")
app.include_router(autopilot_router, prefix="/api/v1")


# --- Health Check ---
@app.get("/api/health")
def health():
    return {"status": "ok", "version": "1.0.0"}


# --- WebSocket ---
@app.websocket("/ws/realtime/{symbol}")
async def ws_realtime(websocket: WebSocket, symbol: str):
    from cryptoagents.data.ccxt_fetcher import CCXTFetcher
    from cryptoagents.data.kline_converter import KlineConverter
    await websocket.accept()
    cv = KlineConverter()
    try:
        while True:
            fetcher = CCXTFetcher()
            items = fetcher.fetch_ohlcv_list(symbol, "15m", limit=2)
            if len(items) >= 2:
                k = cv.convert_realtime(items[-1], items[-2])
                await websocket.send_text(k.to_standard_string())
            import asyncio
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        pass


@app.websocket("/ws/signals")
async def ws_signals(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            # 获取当前活跃策略的信号
            try:
                from cryptoagents.data.ccxt_fetcher import CCXTFetcher
                from cryptoagents.strategy.scheduler import scheduler
                fetcher = CCXTFetcher(with_keys=False, use_testnet=False)
                sig = "HOLD"
                for sym in settings.SYMBOLS_WATCHLIST[:1]:
                    sid = scheduler.get_current_strategy(sym)
                    from cryptoagents.strategy.strategies import get_strategy
                    strat = get_strategy(sid)
                    df = fetcher.fetch_ohlcv(sym, strat.timeframe(), limit=200)
                    if not df.empty:
                        sig = strat.calculate(df).signal
                    break
            except Exception:
                sig = "HOLD"
            await websocket.send_json({"time": datetime.now(timezone.utc).isoformat(), "signal": sig})
            import asyncio
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        pass


@app.websocket("/ws/trend")
async def ws_trend(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.send_json({"time": datetime.now(timezone.utc).isoformat(), "market_state": "RANGING"})
            import asyncio
            await asyncio.sleep(30)
    except WebSocketDisconnect:
        pass


# --- Frontend Static (SPA) ---
_frontend_dir = _get_frontend_dir()
if _frontend_dir:
    # 静态资源 (JS/CSS/图片等)
    assets_dir = _frontend_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
    favicon = _frontend_dir / "favicon.ico"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str, request: Request):
        """Vue SPA: 非 API 路径回退到 index.html。"""
        if full_path.startswith("api/") or full_path.startswith("ws/") or full_path.startswith("docs") or full_path.startswith("openapi"):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Not Found"}, 404)
        p = _frontend_dir / full_path
        if p.is_file():
            return FileResponse(str(p))
        return FileResponse(str(_frontend_dir / "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
