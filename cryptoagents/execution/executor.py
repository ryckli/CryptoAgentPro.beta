from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings
from app.core.logging_config import get_logger
from cryptoagents.risk.gateway import risk_gateway
from cryptoagents.execution import paper_account

logger = get_logger("executor")


@dataclass
class ExecutionResult:
    success: bool
    order_id: str = ""
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


def _calc_position_size(price: float, leverage: int, stop_loss_pct: float,
                        capital: float | None = None, ai_confidence: float = 0.5) -> float:
    """仓位计算 — AI根据余额动态决策, 范围20-100U保证金。
    
    规则:
    - 最低保证金: 20U (不管余额多少, 开得起就开)
    - 最高保证金: 100U (单仓上限, 防过度集中)
    - 余额不足20U保证金时不强行开仓
    - AI置信度越高, 仓位越大(在20-100间线性缩放)
    - 风险兜底: 预估亏损不超过余额x5%
    """
    cap = capital if capital and capital > 0 else settings.RISK_INITIAL_CAPITAL
    risk_pct = settings.RISK_MAX_LOSS_PER_TRADE_PCT / 100
    
    # 保证金范围: min 20U, max 100U (10x杠杆)
    min_margin = 20.0
    max_margin = 100.0
    
    # AI置信度映射: 0.5→min_margin, 0.9→max_margin
    confidence_factor = (ai_confidence - 0.5) / 0.4  # 0.5->0, 0.9->1
    confidence_factor = max(0.0, min(1.0, confidence_factor))
    target_margin = min_margin + (max_margin - min_margin) * confidence_factor
    
    # 余额不足时等比缩小(最低不低于账户1%)
    if cap < min_margin * 2:
        target_margin = max(min_margin, cap * 0.01)  # 至少用1%余额
    
    if stop_loss_pct and stop_loss_pct > 0:
        qty = (target_margin * leverage) / price
        # 风控兜底: 预估亏损不超过余额的risk_pct%
        est_loss = qty * price * (stop_loss_pct / 100) * leverage
        max_loss = cap * risk_pct
        # 高杠杆时放宽风控上限(杠杆越高单笔波动越大是正常的)
        if leverage >= 50:
            max_loss = cap * min(risk_pct * 2, 0.15)  # 最高15%
        if est_loss > max_loss and est_loss > 0:
            qty = qty * (max_loss / est_loss)
    else:
        margin = target_margin * 0.3
        qty = (margin * leverage) / price
    
    # 硬上限: 不超过余额的10%作为保证金
    max_qty = (cap * 0.10 * leverage) / price
    qty = min(qty, max_qty)
    return round(max(qty, 0.0), 6)


class ExecutionEngine:
    def _exchange(self):
        """获取交易所实例 (原生API, 不再依赖CCXT)。"""
        from cryptoagents.exchange import factory
        return factory.get_exchange(with_keys=True)

    def _get_price(self, symbol: str, entry_price: float = 0.0) -> float:
        if entry_price and entry_price > 0:
            return entry_price
        # 重试3次，间隔1秒
        for attempt in range(3):
            try:
                from cryptoagents.data.ccxt_fetcher import CCXTFetcher
                if settings.TRADING_MODE == "paper":
                    f = CCXTFetcher(with_keys=False, use_testnet=False)
                else:
                    f = CCXTFetcher()
                price = float(f.fetch_ticker(symbol)["last"])
                if price > 0:
                    return price
            except Exception:
                if attempt < 2:
                    import time; time.sleep(1)
        raise RuntimeError(f"无法获取{symbol}价格(重试3次失败)，拒绝操作")

    def execute_with_risk_params(self, signal: dict[str, Any], symbol: str,
                                 entry_price: float = 0.0, leverage: int | None = None,
                                 strategy_id: str = "", capital: float | None = None) -> ExecutionResult:
        mode = settings.TRADING_MODE
        lev = leverage or settings.RISK_MAX_LEVERAGE
        direction = signal.get("direction", "LONG")
        sl_pct = float(signal.get("stop_loss_pct", 1.8))
        tp_pct = float(signal.get("take_profit_pct", 2.0))

        price = self._get_price(symbol, entry_price)
        if price <= 0:
            return ExecutionResult(False, message="无法获取价格")

        ai_conf = signal.get("confidence", 0.5)
        qty = _calc_position_size(price, lev, sl_pct, capital=capital, ai_confidence=ai_conf)
        if qty <= 0:
            return ExecutionResult(False, message="仓位计算为0")

        sl = price * (1 - sl_pct / 100) if direction == "LONG" else price * (1 + sl_pct / 100)
        tp = price * (1 + tp_pct / 100) if direction == "LONG" else price * (1 - tp_pct / 100)
        if sl_pct == 0:
            sl = 0.0

        notional = qty * price
        margin_required = notional / max(lev, 1)
        est_loss = notional * (sl_pct / 100) * lev if sl_pct else notional * 0.1
        cap_val = capital if (capital and capital > 0) else settings.RISK_INITIAL_CAPITAL
        passed, reason = risk_gateway.check_order({"estimated_loss": est_loss, "margin_required": margin_required}, capital=cap_val)
        if not passed:
            return ExecutionResult(False, message=f"风控拦截: {reason}")

        side = "buy" if direction == "LONG" else "sell"

        # ---- Paper 模式: 本地模拟 ----
        if mode == "paper":
            order = paper_account.open_position(
                symbol, direction, qty, price, lev, sl, tp, strategy_id, mode="paper")
            if order.get("error"):
                return ExecutionResult(False, message=f"模拟开仓失败: {order['error']}")
            self._log_trade(symbol, strategy_id, direction, price, qty)
            logger.info(f"[executor] [模拟] {symbol} {direction} qty={qty:.4f} @{price:.4f} SL={sl:.4f} TP={tp:.4f}")
            return ExecutionResult(
                True, str(order["id"]),
                f"[模拟] {direction} {symbol} qty={qty} @{price:.4f} SL={sl:.4f} TP={tp:.4f}",
                {"mode": "paper", "qty": qty, "entry": price, "stop_loss": sl, "take_profit": tp, "leverage": lev})

        # ---- Testnet / Live 模式: 原生API真实下单 ----
        if getattr(settings, 'DRY_RUN', False):
            logger.info(f"[executor] [干跑] {symbol} {direction} qty={qty:.6f} @{price:.4f} SL={sl:.4f} TP={tp:.4f} — 未实际下单")
            return ExecutionResult(
                True, "dry_run",
                f"[干跑] {direction} {symbol} qty={qty:.6f} @{price:.4f} (未实际下单)",
                {"mode": "dry_run", "qty": qty, "entry": price, "stop_loss": sl, "take_profit": tp, "leverage": lev})
        
        try:
            ex = self._exchange()
            logger.info(f"[executor] {mode} 开始下单: {symbol} {direction} qty={qty:.6f} lev={lev}x SL={sl:.4f} TP={tp:.4f}")
            
            # 持仓检查
            try:
                existing = ex.fetch_positions([symbol])
                for pos in existing:
                    pos_qty = float(pos.get("qty", 0) or 0)
                    if pos_qty > 0:
                        pos_dir = pos.get("direction", "LONG")
                        if pos_dir == direction:
                            logger.warning(f"[executor] {symbol} 已有 {direction} 持仓 qty={pos_qty}, 拒绝重复开仓")
                            return ExecutionResult(False, message=f"已有同方向持仓, 拒绝开仓")
                        else:
                            logger.info(f"[executor] {symbol} 反向开仓, 先平旧仓 {pos_dir} qty={pos_qty}")
                            close_side = "sell" if pos_dir == "LONG" else "buy"
                            ex.place_market_order(symbol, close_side, pos_qty, reduce_only=True)
            except Exception as exc:
                logger.error(f"[executor] 持仓检查失败(拒绝下单): {exc}")
                return ExecutionResult(False, message=f"持仓检查失败: {exc}")
            
            # 设杠杆
            try:
                ex.set_leverage(symbol, lev)
                logger.info(f"[executor] {symbol} 杠杆设为 {lev}x")
            except Exception as exc:
                logger.warning(f"[executor] {symbol} 设杠杆失败: {exc}")
            
            # 下单
            order = ex.place_market_order(symbol, side, qty,
                                          sl_price=sl if sl else 0,
                                          tp_price=tp if tp else 0,
                                          leverage=lev)
            order_status = order.get("status", "unknown")
            order_id = order.get("id", "")
            order_msg = order.get("message", "")
            
            if order_status != "ok":
                logger.error(f"[executor] {symbol} 下单被拒: status={order_status} msg={order_msg}")
                return ExecutionResult(False, message=order_msg or "下单失败, 交易所拒绝")
            
            self._log_trade(symbol, strategy_id, direction, price, qty)
            tag = "测试网"
            logger.info(f"[executor] [{tag}] {symbol} {direction} 成功! id={order_id} qty={qty:.6f} @{price:.4f}")
            return ExecutionResult(
                True, order_id,
                f"[{tag}] {direction} {symbol} qty={qty:.6f} @{price:.4f} SL={sl:.4f} TP={tp:.4f}",
                {"mode": mode, "qty": qty, "entry": price, "stop_loss": sl, "take_profit": tp, "leverage": lev, "order_id": order_id})
        except Exception as exc:
            logger.error(f"[executor] {symbol} 下单异常: {type(exc).__name__}: {exc}")
            return ExecutionResult(False, message=f"{type(exc).__name__}: {exc}")

    def emergency_close_all(self, symbol: str) -> ExecutionResult:
        mode = settings.TRADING_MODE
        try:
            price = self._get_price(symbol)
        except Exception:
            return ExecutionResult(False, message=f"获取价格失败: {e}")
        if mode == "paper":
            r = paper_account.close_all(symbol, price)
            return ExecutionResult(True, message=f"[模拟] 平仓{r['closed']}个", details=r)
        try:
            ex = self._exchange()
            if hasattr(ex, 'close_position_market'):
                # Use OKX dedicated close-position endpoint
                result = ex.close_position_market(symbol)
                return ExecutionResult(True, message=result.get("message", "平仓已提交"), details=result)
            else:
                # Fallback: reduce_only market orders
                positions = ex.fetch_positions([symbol])
                closed = 0
                for pos in positions:
                    if pos.get("contracts", 0) > 0:
                        side = "sell" if pos["direction"] == "LONG" else "buy"
                        ex.place_market_order(symbol, side, pos["contracts"], reduce_only=True)
                        closed += 1
                return ExecutionResult(True, message=f"平仓{closed}个", details={"closed": closed})
        except Exception as exc:
            return ExecutionResult(False, message=str(exc))

    def _log_trade(self, symbol, strategy_id, direction, price, qty):
        try:
            import time
            from app.models.strategy import TradeLog
            from app.core.database import get_sqlite_session
            s = get_sqlite_session()
            s.add(TradeLog(timestamp=int(time.time()), symbol=symbol,
                           strategy_id=strategy_id or "manual", direction=direction,
                           entry_price=price, exit_price=0, pnl=0, pnl_pct=0))
            s.commit()
            s.close()
        except Exception:
            pass
