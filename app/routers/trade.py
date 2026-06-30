from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from cryptoagents.execution.executor import ExecutionEngine
from cryptoagents.execution import paper_account
from cryptoagents.data.ccxt_fetcher import CCXTFetcher
from app.core.config import settings

router = APIRouter(prefix="/trade", tags=["交易"])


class ManualOrderRequest(BaseModel):
    symbol: str
    direction: str  # LONG / SHORT
    stop_loss_pct: float = 1.8
    take_profit_pct: float = 2.0
    leverage: int | None = None
    strategy_id: str = "manual"


@router.post("/order")
def place_order(req: ManualOrderRequest):
    signal = {"direction": req.direction, "stop_loss_pct": req.stop_loss_pct,
              "take_profit_pct": req.take_profit_pct}
    engine = ExecutionEngine()
    result = engine.execute_with_risk_params(
        signal, req.symbol, leverage=req.leverage, strategy_id=req.strategy_id)
    if not result.success:
        raise HTTPException(400, result.message)
    return {"success": result.success, "order_id": result.order_id,
            "message": result.message, "details": result.details}


@router.post("/strategy-order")
def strategy_order(symbol: str, strategy_id: str, leverage: int | None = None):
    """一键策略下单 — 计算该策略当前信号, 若为 BUY/SELL 则按信号自带的止损止盈下单。"""
    from cryptoagents.strategy.strategies import get_strategy
    from cryptoagents.data.ccxt_fetcher import CCXTFetcher
    try:
        strat = get_strategy(strategy_id)
    except ValueError:
        raise HTTPException(404, f"策略 {strategy_id} 不存在")
    fetcher = CCXTFetcher(with_keys=False, use_testnet=False)
    df = fetcher.fetch_ohlcv(symbol, strat.timeframe(), limit=200)
    if df.empty:
        raise HTTPException(404, "无K线数据")
    sig = strat.calculate(df).to_dict()
    if sig["signal"] not in ("BUY", "SELL"):
        return {"success": False, "signal": sig["signal"],
                "message": f"策略 {strategy_id} 当前信号为 {sig['signal']}, 无交易机会"}
    engine = ExecutionEngine()
    result = engine.execute_with_risk_params(sig, symbol, leverage=leverage, strategy_id=strategy_id)
    if not result.success:
        raise HTTPException(400, result.message)
    return {"success": True, "signal": sig["signal"], "order_id": result.order_id,
            "message": result.message, "details": result.details}


@router.post("/emergency-close")
def emergency_close(symbol: str):
    engine = ExecutionEngine()
    result = engine.emergency_close_all(symbol)
    return {"success": result.success, "message": result.message, "details": result.details}


@router.get("/positions")
def get_positions(symbol: str = ""):
    """当前持仓 (模拟盘从本地, 测试网从交易所)。"""
    if settings.TRADING_MODE == "paper":
        positions = paper_account.list_open(symbol or None)
        # 计算浮动盈亏
        _f = CCXTFetcher(with_keys=False, use_testnet=False)
        for p in positions:
            try:
                price = float(_f.fetch_ticker(p["symbol"])["last"])
                pnl_pct = (price - p["entry_price"]) / p["entry_price"] * 100 * (p["leverage"] or 1)
                if p["direction"] == "SHORT":
                    pnl_pct = -pnl_pct
                p["current_price"] = price
                p["unrealized_pnl_pct"] = round(pnl_pct, 2)
            except Exception:
                p["current_price"] = p["entry_price"]
                p["unrealized_pnl_pct"] = 0.0
        return {"mode": "paper", "positions": positions}
    try:
        engine = ExecutionEngine()
        ex = engine._exchange()
        positions = ex.fetch_positions([symbol] if symbol else None)
        out = [{"symbol": p.get("symbol"), "direction": p.get("direction"),
                "qty": p.get("qty"), "entry_price": p.get("entry_price"),
                "unrealized_pnl": 0} for p in positions
               if float(p.get("qty", 0) or 0) > 0]
        return {"mode": settings.TRADING_MODE, "positions": out}
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.post("/close/{order_id}")
def close_one(order_id: int):
    if settings.TRADING_MODE != "paper":
        raise HTTPException(400, "仅模拟盘支持按单平仓")
    positions = paper_account.list_open()
    pos = next((p for p in positions if p["id"] == order_id), None)
    if not pos:
        raise HTTPException(404, "持仓不存在")
    price = float(CCXTFetcher(with_keys=False, use_testnet=False).fetch_ticker(pos["symbol"])["last"])
    return paper_account.close_position(order_id, price)


@router.get("/account")
def get_account():
    return paper_account.account_summary()


@router.get("/history")
def get_history(symbol: str = "", limit: int = 100):
    from app.models.strategy import TradeLog
    from app.core.database import get_sqlite_session
    session = get_sqlite_session()
    q = session.query(TradeLog).order_by(TradeLog.timestamp.desc()).limit(limit)
    if symbol:
        q = q.filter(TradeLog.symbol == symbol)
    rows = q.all()
    out = [{"id": t.id, "timestamp": t.timestamp, "symbol": t.symbol, "direction": t.direction,
            "strategy_id": t.strategy_id, "entry_price": t.entry_price,
            "pnl": t.pnl, "pnl_pct": t.pnl_pct} for t in rows]
    session.close()
    return {"trades": out}
