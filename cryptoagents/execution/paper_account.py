"""模拟盘账户 — 本地撮合, 记录持仓与盈亏到 SQLite (paper_orders 表)。

不接触交易所, 用实时价格模拟成交。所有 paper/部分 testnet 流程共用。
"""
from __future__ import annotations

import time
from typing import Any

from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger("paper_account")


def _session():
    from app.core.database import get_sqlite_session
    return get_sqlite_session()


def open_position(symbol: str, direction: str, qty: float, entry_price: float,
                  leverage: int, stop_loss: float, take_profit: float,
                  strategy_id: str = "", mode: str = "paper") -> dict[str, Any]:
    """开仓 — 模拟真实交易所行为: 同一币种只允许一个净持仓。"""
    from app.models.strategy import PaperOrder

    # 检查已有持仓
    existing = list_open(symbol)
    if existing:
        for pos in existing:
            if pos["direction"] == direction:
                logger.warning(
                    f"[paper] 拒绝重复开仓: {symbol} 已有 {direction} 持仓 "
                    f"(id={pos['id']}, qty={pos['qty']}, entry={pos['entry_price']})"
                )
                return {"id": -1, "symbol": symbol, "direction": direction, "qty": 0,
                        "entry_price": entry_price, "error": "同币种同方向已有持仓, 拒绝重复开仓"}
            else:
                logger.info(f"[paper] {symbol} 反向开仓, 先平旧仓 {pos['direction']} id={pos['id']}")
                close_position(pos["id"], entry_price)

    s = _session()
    order = PaperOrder(
        opened_at=int(time.time()), symbol=symbol, strategy_id=strategy_id,
        direction=direction, qty=qty, leverage=leverage, entry_price=entry_price,
        stop_loss=stop_loss, take_profit=take_profit, status="open", mode=mode,
    )
    s.add(order)
    s.commit()
    oid = order.id
    s.close()
    logger.info(f"[paper] 开仓成功: {symbol} {direction} qty={qty} @{entry_price:.4f} SL={stop_loss} TP={take_profit}")
    return {"id": oid, "symbol": symbol, "direction": direction, "qty": qty,
            "entry_price": entry_price, "stop_loss": stop_loss, "take_profit": take_profit}


def list_open(symbol: str | None = None) -> list[dict[str, Any]]:
    from app.models.strategy import PaperOrder
    s = _session()
    q = s.query(PaperOrder).filter(PaperOrder.status == "open")
    if symbol:
        q = q.filter(PaperOrder.symbol == symbol)
    rows = q.all()
    out = [{
        "id": r.id, "symbol": r.symbol, "direction": r.direction, "qty": r.qty,
        "leverage": r.leverage, "entry_price": r.entry_price,
        "stop_loss": r.stop_loss, "take_profit": r.take_profit,
        "strategy_id": r.strategy_id, "opened_at": r.opened_at, "mode": r.mode,
    } for r in rows]
    s.close()
    return out


def close_position(order_id: int, exit_price: float) -> dict[str, Any]:
    """平仓 — 拒绝以0价格平仓。"""
    if exit_price <= 0:
        logger.error(f"[close_position] 拒绝以0价格平仓! order_id={order_id}")
        return {"success": False, "message": "平仓价格无效(0)，拒绝操作"}

    from app.models.strategy import PaperOrder
    s = _session()
    r = s.get(PaperOrder, order_id)
    if not r or r.status != "open":
        s.close()
        return {"success": False, "message": "订单不存在或已平仓"}
    pnl_pct = (exit_price - r.entry_price) / r.entry_price * 100 * (r.leverage or 1)
    if r.direction == "SHORT":
        pnl_pct = -pnl_pct
    notional = r.qty * r.entry_price
    pnl = notional * (pnl_pct / 100)
    r.exit_price = exit_price
    r.closed_at = int(time.time())
    r.pnl = round(pnl, 2)
    r.pnl_pct = round(pnl_pct, 2)
    r.status = "closed"
    s.commit()
    s.close()
    # 同步风控
    from cryptoagents.risk.gateway import risk_gateway
    risk_gateway.on_trade_close(pnl)
    return {"success": True, "order_id": order_id, "exit_price": exit_price,
            "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2)}


def close_all(symbol: str, exit_price: float) -> dict[str, Any]:
    if exit_price <= 0:
        return {"success": False, "message": "平仓价格无效", "closed": 0}
    closed = []
    for pos in list_open(symbol):
        r = close_position(pos["id"], exit_price)
        if r.get("success"):
            closed.append(r)
    return {"success": True, "closed": len(closed), "details": closed}


def mark_to_market(symbol: str, current_price: float) -> list[dict[str, Any]]:
    """根据当前价检查 SL/TP, 自动平仓触发的持仓。返回被平仓列表。"""
    if current_price <= 0:
        logger.error(f"[mark_to_market] {symbol} 拒绝以0价格平仓!")
        return []
    triggered = []
    for pos in list_open(symbol):
        pnl_pct = (current_price - pos["entry_price"]) / pos["entry_price"] * 100 * (pos["leverage"] or 1)
        if pos["direction"] == "SHORT":
            pnl_pct = -pnl_pct
        sl = pos["stop_loss"]
        tp = pos["take_profit"]
        hit = False
        if pos["direction"] == "LONG":
            if sl and current_price <= sl: hit = True
            if tp and current_price >= tp: hit = True
        else:
            if sl and current_price >= sl: hit = True
            if tp and current_price <= tp: hit = True
        if hit:
            r = close_position(pos["id"], current_price)
            triggered.append(r)
    return triggered


def account_summary() -> dict[str, Any]:
    from app.models.strategy import PaperOrder
    s = _session()
    closed = s.query(PaperOrder).filter(PaperOrder.status == "closed").all()
    open_n = s.query(PaperOrder).filter(PaperOrder.status == "open").count()
    s.close()
    realized = sum((r.pnl or 0) for r in closed)
    wins = [r for r in closed if (r.pnl or 0) > 0]
    return {
        "initial_capital": settings.RISK_INITIAL_CAPITAL,
        "equity": round(settings.RISK_INITIAL_CAPITAL + realized, 2),
        "realized_pnl": round(realized, 2),
        "open_positions": open_n,
        "closed_trades": len(closed),
        "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else 0.0,
    }
