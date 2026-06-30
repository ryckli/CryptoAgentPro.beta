"""自动驾驶模块 — AI全权接管策略切换与下单。

启动后: 后台循环每15秒感知 → 自动切换策略 → 自动下单
停止后: 平掉所有仓位 → 恢复手动模式

支持 paper/testnet 两种模式。
"""
from __future__ import annotations

import threading
import time
from typing import Any

from fastapi import APIRouter

from app.core.config import settings
from app.core.logging_config import get_logger
from cryptoagents.autopilot import SafetyValve, create_context

logger = get_logger("autopilot")

# 熔断器实例 (模块级单例)
_safety_valve: SafetyValve | None = None
_context = create_context(max_history=5)

router = APIRouter(prefix="/autopilot", tags=["自动驾驶"])

_state: dict[str, Any] = {
    "running": False,
    "started_at": 0,
    "loop_count": 0,
    "last_action": "",
    "last_action_time": 0,
    "saved_settings": {},
    "mode": "paper",
    "symbol_status": {},  # {BTC/USDT: {market_state, strategy, signal, error}}
}
_thread: threading.Thread | None = None
_stop_event = threading.Event()
_LOOP_INTERVAL = 15
_open_positions: dict[str, bool] = {}  # 内存级持仓跟踪: {symbol: True}
_order_lock: dict[str, float] = {}  # 下单互斥锁: {symbol: timestamp}, 同一币种30秒内禁止重复下单


def _check_api_ready() -> tuple[bool, str]:
    missing = []
    if not settings.DEEPSEEK_API_KEY:
        missing.append("DeepSeek API Key (AI趋势感知必需)")
    mode = settings.TRADING_MODE

    if mode == "testnet":
        if not settings.EXCHANGE_API_KEY or not settings.EXCHANGE_SECRET:
            missing.append(f"交易所 API Key/Secret ({mode} 模式真实下单必需)")

    # 检查交易所连通性
    if mode != "paper":
        try:
            from cryptoagents.data.ccxt_fetcher import CCXTFetcher
            working = CCXTFetcher.find_working_exchange()
            if working != settings.EXCHANGE_NAME:
                missing.insert(0, f"{settings.EXCHANGE_NAME} 不可达, 建议切换到 {working}")
        except Exception:
            missing.insert(0, "交易所网络超时, 请检查网络或切换到 paper 模式")

    if missing:
        return False, "以下 API 未接入: " + "、".join(missing) + "。请到「设置」页配置后再启动。"
    return True, ""


def _relax_params(sid: str, current: dict) -> dict:
    """自动放宽策略参数，增加入场机会 (更激进)。"""
    relaxed = {}
    if sid == "S1":
        relaxed["sep"] = round(max(0.01, current.get("sep", 0.03) * 0.3), 2)
        relaxed["fast"] = max(4, current.get("fast", 6) - 2)
        relaxed["slow"] = min(15, current.get("slow", 18) - 3)
    elif sid == "S2":
        relaxed["oversold"] = min(current.get("oversold", 40) + 10, 48)
        relaxed["overbought"] = max(current.get("overbought", 60) - 10, 52)
    elif sid == "S3":
        relaxed["vol_mult"] = round(max(0.5, current.get("vol_mult", 1.1) * 0.4), 2)
    elif sid == "S4":
        relaxed["rsi_thresh"] = min(current.get("rsi_thresh", 30) + 10, 42)
        relaxed["drop_pct"] = round(max(0.5, current.get("drop_pct", 2.0) * 0.4), 1)
    elif sid == "S5":
        relaxed["ema_period"] = max(5, current.get("ema_period", 14) - 7)
    elif sid == "S6":
        relaxed["td_count"] = max(4, current.get("td_count", 7) - 3)
    return relaxed


def _autopilot_loop():
    from cryptoagents.ai import ai_service
    from cryptoagents.execution.executor import ExecutionEngine
    from cryptoagents.data.ccxt_fetcher import CCXTFetcher
    from cryptoagents.strategy.strategies import get_strategy
    from cryptoagents.strategy.scheduler import scheduler

    mode = settings.TRADING_MODE
    logger.info(f"自动驾驶启动, 模式: {mode}, 监控: {settings.SYMBOLS_WATCHLIST}")

    while not _stop_event.is_set():
        _state["loop_count"] += 1
        loop_start = time.time()
        watchlist = _state.get("selected_symbols", settings.SYMBOLS_WATCHLIST)
        # 熔断器检查 (模拟盘跳过，避免无API密钥时误触发)
        if _safety_valve and mode != "paper":
            should_stop, reason = _safety_valve.check()
            if should_stop:
                logger.critical(f"[自动驾驶] 熔断触发: {reason}")
                _state["running"] = False
                _state["last_action"] = f"熔断: {reason}"
                _state["last_action_time"] = int(time.time())
                _stop_event.set()
                break

        for symbol in watchlist:
            if _stop_event.is_set():
                break
            ss = _state["symbol_status"].setdefault(symbol, {})
            try:
                # 1) AI 感知
                ss["phase"] = "AI感知中"
                pos_ctx = _build_position_context(symbol, mode, ss) if _open_positions.get(symbol) else None
                report = ai_service.run_sensing(symbol, triggered_by="autopilot", position=pos_ctx)
                ms = report.get("market_state", "RANGING")
                rec = report.get("recommended_strategy", "S2")
                conf = report.get("confidence", 0)
                err = report.get("error", "")
                ss["market_state"] = ms
                ss["confidence"] = round(conf * 100)
                ss["strategy"] = rec
                ss["error"] = err
                _state["last_action"] = f"{symbol}: {ms}({round(conf*100)}%) → {rec}"
                _state["last_action_time"] = int(time.time())

                # 2) 自动切换策略
                current = scheduler.get_current_strategy(symbol)
                if rec != current and rec in strategies:
                    scheduler.current_strategy[symbol] = rec
                    ss["switched"] = f"{current}→{rec}"
                    logger.info(f"[自动驾驶] {symbol} 策略 {current}→{rec}")

                # 2.5) 变盘检测: 用内存级持仓标记 (避免DB查询不一致)
                pos_open = _open_positions.get(symbol, False)
                if not pos_open:
                    pos_open = _has_open_position(symbol, mode)
                    if pos_open:
                        _open_positions[symbol] = True
                else:
                    if not _has_open_position(symbol, mode):
                        logger.warning(f"[自动驾驶] {symbol} _open_positions 标记有持仓但实际无持仓, 清除标记")
                        _open_positions[symbol] = False
                        pos_open = False
                if pos_open:
                    # 变盘检测: 仅在STRONG趋势反转时触发，均值回归策略允许逆势
                    is_strong = ("STRONG" in ms.upper()) if ms else False
                    bullish = "BULL" in ms.upper() if ms else False
                    bearish = "BEAR" in ms.upper() if ms else False
                    pos_long = _is_position_long(symbol, mode)
                    # 只有强趋势 + 持仓方向相反 才触发变盘检测
                    trend_conflict = (bullish and not pos_long) or (bearish and pos_long)
                    if is_strong and trend_conflict:
                        rc = ss.get("reversal_consensus", 0)
                        rc += 1
                        ss["reversal_consensus"] = rc
                        if rc >= 8:  # 8周期=2分钟，给策略足够时间
                            logger.info(f"[自动驾驶] {symbol} 强趋势变盘确认({rc}周期), 平仓")
                            _close_position_immediate(symbol, mode)
                            _open_positions[symbol] = False
                            ss["reversal_consensus"] = 0
                            ss["cooldown_cycles"] = 1
                            pos_open = False
                            ss["last_action"] = f"变盘平仓 {symbol}"
                            _state["last_action"] = f"{symbol}: 变盘平仓 ({ms})"
                            _state["last_action_time"] = int(time.time())
                    else:
                        ss["reversal_consensus"] = 0
                ss["has_position"] = pos_open

                # 3) AI动态持仓管理 + 多层保护
                if pos_open:
                    held_cycles = ss.get("held_cycles", 0)
                    if held_cycles >= 1:
                        _check_positions(symbol, mode)
                        pnl = _get_position_pnl(symbol, mode)
                        # 第一层: 慢流血保护 — 持仓>5分钟且浮亏>1.5%，不管AI怎么说都平
                        if held_cycles >= 20 and pnl is not None and pnl < -1.5:
                            logger.info(f"[自动驾驶] {symbol} 慢流血保护: 持仓{held_cycles}周期 浮亏{pnl:.1f}%")
                            _close_position_immediate(symbol, mode)
                            _open_positions[symbol] = False
                            ss["held_cycles"] = 0
                            ss["cooldown_cycles"] = 5
                            _state["last_action"] = f"{symbol}: 慢流血平仓 (浮亏{pnl:.1f}%)"
                            _state["last_action_time"] = int(time.time())
                            pos_open = False
                        # 第二层: 极端保护 — 浮亏>6%立刻平仓
                        if pos_open and pnl is not None and pnl < -6.0:
                            logger.critical(f"[自动驾驶] {symbol} 极端浮亏保护: {pnl:.1f}%")
                            _close_position_immediate(symbol, mode)
                            _open_positions[symbol] = False
                            ss["held_cycles"] = 0
                            ss["cooldown_cycles"] = 5
                            _state["last_action"] = f"{symbol}: 极端浮亏平仓 ({pnl:.1f}%)"
                            _state["last_action_time"] = int(time.time())
                            pos_open = False
                        # 第三层: AI动态判断 — DeepSeek决定是否平仓
                        if pos_open:
                            ai_action = report.get("position_action", "NONE")
                            ai_reason = report.get("position_reason", "")
                            if ai_action == "CLOSE" and held_cycles >= 3:
                                logger.info(f"[自动驾驶] {symbol} AI建议平仓: {ai_reason}")
                                _close_position_immediate(symbol, mode)
                                _open_positions[symbol] = False
                                ss["held_cycles"] = 0
                                ss["cooldown_cycles"] = 3
                                _state["last_action"] = f"{symbol}: AI平仓 ({ai_reason})"
                                _state["last_action_time"] = int(time.time())
                                pos_open = False

                    else:
                        ss["held_cycles"] = held_cycles + 1

                # 4) 计算信号 — 已有持仓则跳过开仓
                ss["phase"] = "计算信号"
                # 如果已有持仓则跳过开仓
                if pos_open:
                    ss["phase"] = "持有中"
                    ss["no_trade_cycles"] = 0
                    continue

                # 无持仓: 计算策略信号 (含回退策略)
                nt = ss.get("no_trade_cycles", 0)
                try:
                    from cryptoagents.data.ccxt_fetcher import CCXTFetcher
                    from cryptoagents.strategy.base import STRATEGY_MARKET_MAP, MarketState
                    
                    fetcher = CCXTFetcher(with_keys=False, use_testnet=False)
                    df = fetcher.fetch_ohlcv(symbol, "15m", limit=200)
                    
                    if not df.empty:
                        # 确定主策略和回退策略
                        primary = rec
                        fallback = None
                        try:
                            ms_enum = MarketState(ms.lower() if ms else "ranging")
                            fb = STRATEGY_MARKET_MAP.get(ms_enum, {}).get("fallback", "")
                            if fb and fb != primary:
                                fallback = fb
                        except Exception:
                            pass
                        
                        # 按市场优先级尝试全部6个策略
                        sig = None
                        tried = []
                        # 策略优先级: 主策略 → 回退 → S1(趋势) → S3(转折) → S6(极端) → S4(反弹) → S2(回归) → S5(刮头皮)
                        all_sids = [s for s in strategies.keys() if s.startswith("S")]
                        candidates = [primary]
                        if fallback and fallback not in candidates:
                            candidates.append(fallback)
                        for s in all_sids:
                            if s not in candidates:
                                candidates.append(s)
                        for sid in candidates:
                            if sid not in strategies:
                                continue
                            strat = get_strategy(sid)
                            df_tf = fetcher.fetch_ohlcv(symbol, strat.timeframe(), limit=200) if strat.timeframe() != "15m" else df
                            if df_tf.empty:
                                continue
                            # 参数放宽 (仅对主策略)
                            orig_params = dict(strat.params) if hasattr(strat, "params") else {}
                            if sid == primary and nt >= 1 and hasattr(strat, "params"):
                                relaxed = _relax_params(sid, strat.params)
                                strat.params.update(relaxed)
                                ss["relaxed"] = relaxed
                            s = strat.calculate(df_tf).to_dict()
                            # 恢复参数
                            if orig_params and hasattr(strat, "params"):
                                for k in orig_params:
                                    strat.params[k] = orig_params[k]
                            tried.append(f"{sid}={s['signal']}")
                            if s["signal"] in ("BUY", "SELL"):
                                # 趋势策略(S1/S3/S5)遵守方向限制, 反转策略(S2/S4/S6)不限制
                                sig_dir = s.get("direction", "")
                                if sid in ("S1", "S3", "S5") and ms:
                                    ms_upper = ms.upper()
                                    if "BULL" in ms_upper and sig_dir == "SHORT":
                                        tried[-1] = f"{sid}={s['signal']}(方向限制)"
                                        continue  # 牛市不做空(趋势策略)
                                    if "BEAR" in ms_upper and sig_dir == "LONG":
                                        tried[-1] = f"{sid}={s['signal']}(方向限制)"
                                        continue  # 熊市不做多(趋势策略)
                                sig = s
                                ss["used_strategy"] = sid
                                if sid != primary:
                                    logger.info(f"[自动驾驶] {symbol} 主策略{primary}=HOLD, 回退{sid}={s['signal']}")
                                break
                        
                        if sig is None:
                            sig = {"signal": "HOLD", "strength": "NONE", "strategy": primary}
                        ss["tried_strategies"] = ",".join(tried)
                        ss["signal"] = sig["signal"]
                        ss["signal_dir"] = sig.get("direction", "")
                        ss["signal_sl"] = sig.get("stop_loss_pct", 0)
                        ss["signal_tp"] = sig.get("take_profit_pct", 0)
                        if sig["signal"] in ("BUY", "SELL"):
                            # 使用实际产生信号的策略ID (可能是回退策略)
                            actual_strategy = ss.get("used_strategy", rec)
                            sig["strategy"] = actual_strategy
                            # 防重复开仓: 同一币种30秒内只能开一单
                            now_ts = time.time()
                            last_entry = ss.get("last_entry_time", 0)
                            if now_ts - last_entry < 30:
                                ss["phase"] = "冷却中"
                                continue
                            cooldown = ss.get("cooldown_cycles", 0)
                            if cooldown > 0:
                                ss["cooldown_cycles"] = cooldown - 1
                                ss["phase"] = f"冷却中({cooldown})"
                                continue
                            ss["phase"] = "下单中"
                            _open_positions[symbol] = True  # 预先标记, 防止重复
                            # AI置信度传入信号, 影响仓位大小
                            sig["confidence"] = conf
                            # 获取当前权益 (测试网/模拟盘统一)
                            real_capital = None
                            if mode == "paper":
                                from cryptoagents.execution import paper_account
                                summary = paper_account.account_summary()
                                real_capital = summary.get("equity", settings.RISK_INITIAL_CAPITAL)
                            else:
                                try:
                                    from cryptoagents.exchange import factory
                                    ex = factory.get_exchange(with_keys=True)
                                    bal = ex.fetch_account_balance()
                                    real_capital = bal.get("total", 0)
                                except Exception:
                                    pass
                            if real_capital and real_capital > 0:
                                ss["real_balance"] = real_capital
                            # AI置信度→杠杆
                            ai_lev = 10  # 默认10x
                            ai_conf = report.get("confidence", 0.5)
                            if ai_conf >= 0.8: ai_lev = settings.RISK_MAX_LEVERAGE
                            elif ai_conf >= 0.6: ai_lev = 10
                            else: ai_lev = 5
                            ai_lev = max(1, min(ai_lev, settings.RISK_MAX_LEVERAGE))
                            ss["used_leverage"] = ai_lev
                            result = ExecutionEngine().execute_with_risk_params(
                                sig, symbol, strategy_id=actual_strategy, leverage=ai_lev, capital=real_capital)
                            if result.success:
                                used_lev = ss.get("used_leverage", ai_lev)
                                logger.info(f"[自动驾驶] {symbol} {sig['signal']} {used_lev}x OK [{mode}]")
                                _state["last_action"] = f"{symbol}: {sig['signal']} {used_lev}x @{result.details.get('entry',0):.2f} [{mode}]"
                                _state["last_action_time"] = int(time.time())
                                # 更新上下文 (AI感知+策略信号→下单成功)
                                _context.update_passive(
                                    f"Opened {sig['signal']} {symbol} via {rec}. "
                                    f"Market: {ms}({round(conf*100)}%). Equity: {real_capital or 'paper'}"
                                )
                                # 熔断器: 记录开仓 (平仓时通知pnl)
                                if _safety_valve:
                                    _safety_valve.total_trades += 1
                                ss["last_trade"] = f"{sig['signal']} {used_lev}x @{result.details.get('entry',0):.2f}"
                                ss["no_trade_cycles"] = 0
                                ss["held_cycles"] = 0
                                ss["cooldown_cycles"] = 0
                                ss["last_entry_time"] = time.time()
                            else:
                                _open_positions[symbol] = False
                                ss["signal_error"] = result.message
                                ss["phase"] = f"下单失败: {result.message[:30]}"
                                logger.warning(f"[自动驾驶] {symbol} 下单失败: {result.message}")
                                nt += 1
                        else:
                            nt += 1
                        ss["no_trade_cycles"] = nt
                        if ss.get("phase") != "下单中":
                            ss["phase"] = "就绪"
                    else:
                        ss["signal"] = "HOLD"
                        ss["phase"] = "无数据"
                except Exception as exc:
                    ss["signal_error"] = str(exc)
                    logger.warning(f"[自动驾驶] {symbol} 信号/下单异常: {exc}")
            except Exception as exc:
                ss["error"] = str(exc)
                logger.error(f"[自动驾驶] {symbol} 异常: {exc}")

        elapsed = time.time() - loop_start
        remaining = max(0.2, _LOOP_INTERVAL - elapsed)
        _stop_event.wait(remaining)
    logger.info("自动驾驶停止")


def _has_open_position(symbol: str, mode: str) -> bool:
    """检查持仓 — 异常时返回True(保守假定有持仓)，防止误开重复仓位。"""
    if mode == "paper":
        from cryptoagents.execution import paper_account
        return len(paper_account.list_open(symbol)) > 0
    try:
        from cryptoagents.execution.executor import ExecutionEngine
        ex = ExecutionEngine()._exchange()
        positions = ex.fetch_positions([symbol])
        return any(float(p.get("qty", 0) or 0) > 0 for p in positions)
    except Exception as exc:
        logger.error(f"[_has_open_position] {symbol} API异常, 保守假定有持仓: {exc}")
        return True


def _is_position_long(symbol: str, mode: str) -> bool:
    """检查当前持仓是否为多头。"""
    if mode == "paper":
        from cryptoagents.execution import paper_account
        positions = paper_account.list_open(symbol)
        return positions[0]["direction"] == "LONG" if positions else False
    try:
        from cryptoagents.execution.executor import ExecutionEngine
        ex = ExecutionEngine()._exchange()
        positions = ex.fetch_positions([symbol])
        for p in positions:
            if float(p.get("qty", 0) or 0) > 0:
                return p.get("direction", "") == "LONG"
    except Exception:
        pass
    return False


def _build_position_context(symbol: str, mode: str, ss: dict) -> dict | None:
    """构建传给AI的持仓上下文。"""
    try:
        pnl = _get_position_pnl(symbol, mode)
        if pnl is None:
            return None
        if mode == "paper":
            from cryptoagents.execution import paper_account
            positions = paper_account.list_open(symbol)
            if not positions:
                return None
            pos = positions[0]
            return {
                "direction": pos["direction"], "entry_price": pos["entry_price"],
                "pnl_pct": pnl, "leverage": pos.get("leverage", 10),
                "stop_loss": pos.get("stop_loss", 0), "take_profit": pos.get("take_profit", 0),
                "held_cycles": ss.get("held_cycles", 0),
            }
        return {"direction": "?", "entry_price": 0, "pnl_pct": pnl, "leverage": 10, "stop_loss": 0, "take_profit": 0, "held_cycles": 0}
    except Exception:
        return None


def _get_position_pnl(symbol: str, mode: str) -> float | None:
    """获取当前持仓浮盈百分比。None表示无法获取。"""
    try:
        from cryptoagents.data.ccxt_fetcher import CCXTFetcher
        fetcher = CCXTFetcher(with_keys=False, use_testnet=False)
        ticker = fetcher.fetch_ticker(symbol)
        price = float(ticker.get("last", 0) or 0)
        if price <= 0:
            return None  # 价格无效，不执行任何操作
        if mode == "paper":
            from cryptoagents.execution import paper_account
            positions = paper_account.list_open(symbol)
            if not positions:
                return None
            pos = positions[0]
            entry = float(pos["entry_price"])
            lev = int(pos.get("leverage", 10) or 10)
            if pos["direction"] == "LONG":
                pnl = (price - entry) / entry * 100 * lev
            else:
                pnl = (entry - price) / entry * 100 * lev
            return round(pnl, 2)
        else:
            from cryptoagents.exchange import factory
            ex = factory.get_exchange(with_keys=True)
            positions = ex.fetch_positions([symbol])
            for p in positions:
                if float(p.get("qty", 0) or 0) > 0:
                    entry = float(p.get("entry_price", 0) or 0)
                    lev = int(p.get("leverage", 10) or 10)
                    if entry > 0:
                        if p.get("direction", "LONG") == "LONG":
                            pnl = (price - entry) / entry * 100 * lev
                        else:
                            pnl = (entry - price) / entry * 100 * lev
                        return round(pnl, 2)
            return 0.0
    except Exception:
        return None


def _close_position_immediate(symbol: str, mode: str):
    """立即平仓 (不等待循环)。"""
    from cryptoagents.execution.executor import ExecutionEngine
    engine = ExecutionEngine()
    result = engine.emergency_close_all(symbol)
    if not result.success:
        logger.error(f"[_close_position_immediate] {symbol} 平仓失败: {result.message}")
    _open_positions[symbol] = False
    logger.info(f"[_close_position_immediate] {symbol} 已平仓, _open_positions 已清除")


def _check_positions(symbol: str, mode: str):
    try:
        from cryptoagents.data.ccxt_fetcher import CCXTFetcher
        fetcher = CCXTFetcher(with_keys=False, use_testnet=False)
        ticker = fetcher.fetch_ticker(symbol)
        price = float(ticker.get("last", 0) or 0)
        if price <= 0:
            logger.warning(f"[_check_positions] {symbol} 行情价格无效({price}), 跳过止损止盈检查")
            return
        if mode == "paper":
            from cryptoagents.execution import paper_account
            triggered = paper_account.mark_to_market(symbol, price)
            if triggered:
                _open_positions[symbol] = False
                logger.info(f"[自动驾驶] {symbol} 模拟平仓 {len(triggered)}笔, _open_positions 已清除")
        else:
            from cryptoagents.execution.executor import ExecutionEngine
            ex = ExecutionEngine()._exchange()
            positions = ex.fetch_positions([symbol])
            for pos in positions:
                contracts = float(pos.get("qty", 0) or pos.get("contracts", 0) or 0)
                if contracts <= 0:
                    continue
                side = pos.get("direction", "LONG").lower()
                entry = float(pos.get("entry_price", 0) or 0)
                if entry <= 0:
                    continue
                lev = int(pos.get("leverage", 10) or 10)
                pnl_pct = (price - entry) / entry * 100 * lev
                if side == "short":
                    pnl_pct = -pnl_pct
                # 用测试网持仓的实际杠杆计算浮盈，-8%硬止损
                if pnl_pct <= -8 or pnl_pct >= 20:
                    close_side = "sell" if side == "long" else "buy"
                    if hasattr(ex, 'close_position_market'):
                        ex.close_position_market(symbol)
                    else:
                        ex.place_market_order(symbol, close_side, abs(contracts), reduce_only=True)
                    _open_positions[symbol] = False
                    logger.info(f"[自动驾驶] {symbol} 测试网止损止盈平仓 (pnl={pnl_pct:.1f}%), _open_positions 已清除")
                    if _safety_valve:
                        _safety_valve.on_trade_close(pnl_pct)
    except Exception as exc:
        logger.debug(f"[自动驾驶] {symbol} 持仓检查: {exc}")


@router.post("/start")
def start(symbols: str = ""):
    """一键启动。symbols: 逗号分隔的币种列表, 空则使用全部监控币种。"""
    global _thread
    if _state["running"]:
        return {"status": "already_running", "state": _get_state()}

    ready, msg = _check_api_ready()
    if not ready:
        return {"status": "error", "message": msg}

    _state["saved_settings"] = {
        "auto_trade": settings.AUTO_TRADE,
        "switch_confirmation": settings.STRATEGY_SWITCH_CONFIRMATION,
    }
    settings.AUTO_TRADE = True
    settings.STRATEGY_SWITCH_CONFIRMATION = False
    _state["mode"] = settings.TRADING_MODE
    _state["symbol_status"] = {}
    if symbols:
        _state["selected_symbols"] = [s.strip() for s in symbols.split(",") if s.strip()]
    else:
        _state["selected_symbols"] = list(settings.SYMBOLS_WATCHLIST)

    # 重置风控(跨模式切换时清除旧状态)
    from cryptoagents.risk.gateway import risk_gateway
    risk_gateway.reset_daily()
    logger.info(f"[自动驾驶] 风控已重置, 初始本金={settings.RISK_INITIAL_CAPITAL}")
    _stop_event.clear()
    _state["running"] = True
    _state["started_at"] = int(time.time())
    _state["loop_count"] = 0
    _state["last_action"] = f"正在启动({','.join(_state['selected_symbols'])})..."

    # 初始化熔断器 (模拟/测试网统一读余额)
    global _safety_valve
    def _get_equity():
        """获取当前权益 — 模拟盘读paper_account, 测试网读交易所。"""
        if settings.TRADING_MODE == "paper":
            try:
                from cryptoagents.execution import paper_account
                return float(paper_account.account_summary().get("equity", settings.RISK_INITIAL_CAPITAL))
            except Exception:
                return settings.RISK_INITIAL_CAPITAL
        try:
            from cryptoagents.exchange import factory
            ex = factory.get_exchange(with_keys=True)
            bal = ex.fetch_account_balance()
            total = float(bal.get("total", 0))
            return total if total > 0 else settings.RISK_INITIAL_CAPITAL
        except Exception:
            return settings.RISK_INITIAL_CAPITAL
    _safety_valve = SafetyValve(
        get_equity=_get_equity,
        max_consecutive_losses=5,
        max_drawdown_pct=0.08,
    )
    _safety_valve.reset()
    _context = create_context(max_history=5)
    _state["last_action_time"] = int(time.time())
    _thread = threading.Thread(target=_autopilot_loop, daemon=True)
    _thread.start()
    logger.info(f"自动驾驶已启动, 模式: {settings.TRADING_MODE}, 币种: {_state['selected_symbols']}")
    return {"status": "started", "state": _get_state()}


@router.post("/stop")
def stop():
    global _thread
    if not _state["running"]:
        return {"status": "not_running"}
    _stop_event.set()
    _state["running"] = False
    if _thread:
        _thread.join(timeout=8)
        _thread = None
    saved = _state.get("saved_settings", {})
    settings.AUTO_TRADE = saved.get("auto_trade", False)
    settings.STRATEGY_SWITCH_CONFIRMATION = saved.get("switch_confirmation", True)
    closed = _close_all_positions()
    _state["last_action"] = f"已停止, 平仓{closed}笔"
    _state["last_action_time"] = int(time.time())
    _open_positions.clear()
    _order_lock.clear()
    if _safety_valve:
        _safety_valve.reset()
    logger.info(f"自动驾驶已停止, 平仓{closed}笔")
    return {"status": "stopped", "closed": closed, "state": _get_state()}


@router.post("/cleanup")
def cleanup_duplicates():
    """紧急清理: 平掉同币种的所有重复持仓 (保留最早的一个)。"""
    from cryptoagents.execution import paper_account
    from cryptoagents.data.ccxt_fetcher import CCXTFetcher
    mode = settings.TRADING_MODE
    fetcher = CCXTFetcher(with_keys=False, use_testnet=False)
    cleaned = []
    for symbol in _state.get("selected_symbols", settings.SYMBOLS_WATCHLIST):
        if mode == "paper":
            positions = paper_account.list_open(symbol)
            if len(positions) <= 1:
                continue
            long_pos = [p for p in positions if p["direction"] == "LONG"]
            short_pos = [p for p in positions if p["direction"] == "SHORT"]
            price = float(fetcher.fetch_ticker(symbol)["last"])
            for group in [long_pos, short_pos]:
                if len(group) > 1:
                    group.sort(key=lambda p: p["opened_at"])
                    for dup in group[1:]:
                        r = paper_account.close_position(dup["id"], price)
                        if r.get("success"):
                            cleaned.append({"symbol": symbol, "id": dup["id"], "direction": dup["direction"], "qty": dup["qty"], "pnl": r.get("pnl")})
        else:
            from cryptoagents.execution.executor import ExecutionEngine
            engine = ExecutionEngine()
            result = engine.emergency_close_all(symbol)
            if result.success:
                cleaned.append({"symbol": symbol, "mode": mode, "message": result.message})
    _open_positions.clear()
    _order_lock.clear()
    return {"status": "cleaned", "count": len(cleaned), "details": cleaned}


def _close_all_positions() -> int:
    closed = 0
    mode = _state.get("mode", "paper")
    try:
        from cryptoagents.data.ccxt_fetcher import CCXTFetcher
        fetcher = CCXTFetcher(with_keys=False, use_testnet=False)
        watchlist = _state.get("selected_symbols", settings.SYMBOLS_WATCHLIST)
        for symbol in watchlist:
            if mode == "paper":
                from cryptoagents.execution import paper_account
                positions = paper_account.list_open(symbol)
                if positions:
                    price = float(fetcher.fetch_ticker(symbol)["last"])
                    r = paper_account.close_all(symbol, price)
                    closed += r.get("closed", 0)
            else:
                from cryptoagents.execution.executor import ExecutionEngine
                ex = ExecutionEngine()._exchange()
                positions = ex.fetch_positions([symbol])
                for pos in positions:
                    contracts = float(pos.get("qty", 0) or 0)
                    if contracts > 0:
                        direction = pos.get("direction", "LONG")
                        side = "sell" if direction == "LONG" else "buy"
                        ex.place_market_order(symbol, side, abs(contracts), reduce_only=True)
                        closed += 1
    except Exception as exc:
        logger.error(f"停止平仓异常: {exc}")
    return closed


@router.get("/status")
def status():
    mode = settings.TRADING_MODE
    positions = _get_positions(mode)
    result = {**_get_state(), "positions": positions, "mode": mode}
    if _safety_valve:
        result["safety_valve"] = _safety_valve.get_status()
    return result


def _get_positions(mode: str) -> list[dict[str, Any]]:
    if mode == "paper":
        from cryptoagents.execution import paper_account
        positions = paper_account.list_open()
    else:
        try:
            from cryptoagents.execution.executor import ExecutionEngine
            ex = ExecutionEngine()._exchange()
            raw = ex.fetch_positions()
            positions = []
            for p in raw:
                contracts = float(p.get("qty", 0) or p.get("contracts", 0) or 0)
                if contracts <= 0:
                    continue
                positions.append({
                    "id": 0, "symbol": p.get("symbol", ""),
                    "direction": p.get("direction", "LONG"),
                    "qty": contracts, "leverage": int(p.get("leverage", 1) or 1),
                    "entry_price": float(p.get("entry_price", 0) or 0),
                    "stop_loss": 0, "take_profit": 0,
                    "strategy_id": "", "mode": mode,
                })
        except Exception:
            positions = []
    for p in positions:
        try:
            from cryptoagents.data.ccxt_fetcher import CCXTFetcher
            price = float(CCXTFetcher(with_keys=False, use_testnet=False).fetch_ticker(p["symbol"])["last"])
            pnl_pct = (price - p["entry_price"]) / p["entry_price"] * 100 * (p["leverage"] or 1)
            if p["direction"] == "SHORT":
                pnl_pct = -pnl_pct
            p["current_price"] = price
            p["unrealized_pnl_pct"] = round(pnl_pct, 2)
        except Exception:
            p["current_price"] = p["entry_price"]
            p["unrealized_pnl_pct"] = 0.0
    return positions


@router.get("/history")
def history(limit: int = 50):
    from app.models.strategy import PaperOrder
    from app.core.database import get_sqlite_session
    s = get_sqlite_session()
    rows = s.query(PaperOrder).filter(PaperOrder.status == "closed") \
        .order_by(PaperOrder.closed_at.desc()).limit(limit).all()
    out = [{
        "id": r.id, "symbol": r.symbol, "direction": r.direction,
        "qty": r.qty, "leverage": r.leverage,
        "entry_price": r.entry_price, "exit_price": r.exit_price,
        "stop_loss": r.stop_loss, "take_profit": r.take_profit,
        "pnl": r.pnl, "pnl_pct": r.pnl_pct,
        "strategy_id": r.strategy_id, "mode": r.mode,
        "opened_at": r.opened_at, "closed_at": r.closed_at,
    } for r in rows]
    s.close()
    return {"history": out}


@router.get("/account")
def account():
    mode = settings.TRADING_MODE
    if mode == "paper":
        from cryptoagents.execution import paper_account
        return paper_account.account_summary()
    try:
        from cryptoagents.exchange import factory
        ex = factory.get_exchange(with_keys=True)
        bal = ex.fetch_account_balance()
        from cryptoagents.execution import paper_account
        paper = paper_account.account_summary()
        return {
            "trading_mode": mode,
            "equity": bal.get("total", 0),
            "available": bal.get("available", 0),
            "realized_pnl": paper.get("realized_pnl", 0),
            "open_positions": len(paper_account.list_open()),
            "closed_trades": paper.get("closed_trades", 0),
            "win_rate": paper.get("win_rate", 0),
        }
    except Exception:
        from cryptoagents.execution import paper_account
        return paper_account.account_summary()


@router.get("/check")
def check_api():
    ready, msg = _check_api_ready()
    return {"ready": ready, "message": msg, "mode": settings.TRADING_MODE}


def _get_state() -> dict[str, Any]:
    return {
        "running": _state["running"],
        "started_at": _state["started_at"],
        "loop_count": _state["loop_count"],
        "last_action": _state["last_action"],
        "last_action_time": _state["last_action_time"],
        "uptime": int(time.time()) - _state["started_at"] if _state["running"] else 0,
        "mode": _state.get("mode", "paper"),
        "symbol_status": _state.get("symbol_status", {}),
        "selected_symbols": _state.get("selected_symbols", settings.SYMBOLS_WATCHLIST),
    }
