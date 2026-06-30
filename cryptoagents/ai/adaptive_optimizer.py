"""AI自适应参数优化器 — 每30秒评估策略表现, 性能衰减时调用DeepSeek自动调参。

核心逻辑:
  1. 拉取最近交易记录计算滚动指标 (Sharpe, WinRate, 连续亏损)
  2. 判断是否需要优化 (连续亏损≥3 / Sharpe<0 / WinRate下降30%)
  3. 调用 DeepSeek 分析当前参数+表现, 建议新参数
  4. 安全约束后热更新策略参数
  5. 持久化变更记录到 adapt_log 表
"""
from __future__ import annotations

import json
import time
from typing import Any

from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger("adaptive")

# 每策略可调参数范围
_PARAM_RANGES: dict[str, dict[str, tuple[float, float]]] = {
    "S1": {"fast": (3, 20), "slow": (15, 50), "sl_pct": (0.5, 3.0), "tp_pct": (0.5, 5.0), "sep": (0.05, 0.5)},
    "S2": {"period": (5, 21), "oversold": (10, 40), "overbought": (60, 90), "sl_pct": (0.5, 3.0), "tp_pct": (0.5, 5.0)},
    "S3": {"vol_mult": (1.0, 3.0), "sl_pct": (0.5, 3.0), "tp_pct": (0.5, 5.0)},
    "S4": {"rsi_thresh": (10, 35), "drop_pct": (1.0, 8.0), "tp_pct": (0.5, 5.0)},
    "S5": {"ema_period": (10, 50), "sl_pct": (0.3, 2.0), "tp_pct": (0.5, 3.0)},
    "S6": {"td_count": (7, 13), "sl_pct": (0.5, 3.0), "tp_pct": (0.5, 5.0)},
}

# 策略默认参数
_DEFAULT_PARAMS: dict[str, dict] = {
    "S1": {"fast": 7, "slow": 21, "sl_pct": 2.5, "tp_pct": 8.0, "sep": 0.05},
    "S2": {"period": 7, "oversold": 35, "overbought": 65, "sl_pct": 2.5, "tp_pct": 5.0},
    "S3": {"vol_mult": 1.3, "sl_pct": 2.0, "tp_pct": 5.0},
    "S4": {"rsi_thresh": 25, "drop_pct": 3.0, "sl_pct": 4.0, "tp_pct": 8.0},
    "S5": {"ema_period": 17, "sl_pct": 2.0, "tp_pct": 5.0},
    "S6": {"td_count": 8, "sl_pct": 1.5, "tp_pct": 4.0},
}

_OPTIMIZER_SYSTEM = """你是量化策略参数优化专家。分析策略近期表现,建议参数调整。
输出严格JSON: {"need_adapt":true/false, "new_params":{...}, "reason":"中文理由"}
调整原则:高波动→宽止损;趋势→大止盈;震荡→小止盈;连续亏损→优先缩小风险敞口。
止损只能增大不能减小(安全约束)。每次调整幅度≤原值20%。"""

# 上次调整时间 (防止震荡调整)
_last_adjust: dict[str, float] = {}
_MIN_ADJUST_INTERVAL = 300  # 5分钟


def get_params(sid: str) -> dict:
    """获取策略当前参数 (从运行时策略实例读取)。"""
    try:
        from cryptoagents.strategy.strategies import get_strategy
        s = get_strategy(sid)
        return dict(s.params) if hasattr(s, "params") else dict(_DEFAULT_PARAMS.get(sid, {}))
    except Exception:
        return dict(_DEFAULT_PARAMS.get(sid, {}))


def set_params(sid: str, new_params: dict):
    """热更新策略参数。"""
    from cryptoagents.strategy.strategies import get_strategy
    s = get_strategy(sid)
    if not hasattr(s, "params"):
        s.params = dict(_DEFAULT_PARAMS.get(sid, {}))
    for k, v in new_params.items():
        s.params[k] = v
    logger.info(f"策略 {sid} 参数已更新: {new_params}")


def _get_recent_trades(sid: str, symbol: str, lookback: int = 20) -> list[dict]:
    """获取最近N笔已平仓交易 (按策略+币种过滤)。"""
    from app.models.strategy import PaperOrder
    from app.core.database import get_sqlite_session
    s = get_sqlite_session()
    rows = s.query(PaperOrder).filter(
        PaperOrder.status == "closed",
        PaperOrder.strategy_id == sid,
        PaperOrder.symbol == symbol,
    ).order_by(PaperOrder.closed_at.desc()).limit(lookback).all()
    s.close()
    return [{"pnl": r.pnl or 0, "pnl_pct": r.pnl_pct or 0, "closed_at": r.closed_at or 0} for r in rows]


def _calc_metrics(trades: list[dict]) -> dict[str, float]:
    """从交易列表计算滚动表现指标。"""
    if len(trades) < 3:
        return {"win_rate": 0, "sharpe": 0, "streak": 0, "avg_win": 0, "avg_loss": 0, "pnls": []}
    pnls = [t["pnl_pct"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    win_rate = len(wins) / len(pnls) * 100
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0
    # Sharpe (简化: 均值/std, 不做年化)
    import statistics
    mu = statistics.mean(pnls) if pnls else 0
    sigma = statistics.stdev(pnls) if len(pnls) > 1 else 1.0
    sharpe = mu / max(sigma, 0.01)
    # 连续亏损
    streak = 0
    for p in pnls:
        if p < 0:
            streak += 1
        else:
            break
    return {"win_rate": round(win_rate, 1), "sharpe": round(sharpe, 3),
            "streak": streak, "avg_win": round(avg_win, 2), "avg_loss": round(avg_loss, 2), "pnls": pnls[:10]}


def _should_adapt(metrics: dict) -> tuple[bool, str]:
    """判断是否需要AI调参。"""
    if metrics["streak"] >= 3:
        return True, f"连续亏损{metrics['streak']}笔, 需紧急优化"
    if metrics["sharpe"] < -0.5 and metrics.get("pnls") and len(metrics["pnls"]) >= 5:
        return True, f"Sharpe={metrics['sharpe']}, 策略表现恶化"
    return False, ""


def _call_ai_for_params(sid: str, name: str, current_params: dict, metrics: dict,
                        market_state: str, confidence: float) -> dict | None:
    """调用DeepSeek获取参数建议。"""
    key = settings.DEEPSEEK_API_KEY
    if not key:
        return None
    try:
        ranges = _PARAM_RANGES.get(sid, {})
        prompt = f"""策略{sid}: {name}
当前参数: {json.dumps(current_params)}
参数范围: {json.dumps({k: list(v) for k, v in ranges.items()})}
近期表现: 胜率{metrics['win_rate']}% Sharpe{metrics['sharpe']} 连续亏损{metrics['streak']}笔
平均盈利{metrics['avg_win']}% 平均亏损{metrics['avg_loss']}%
最近盈亏序列: {metrics.get('pnls',[])}
市场状态: {market_state} 置信度: {int(confidence*100)}%
请分析是否需要调整参数。"""
        import httpx
        with httpx.Client(timeout=20, verify=False) as c:
            r = c.post("https://api.deepseek.com/v1/chat/completions",
                       headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                       json={"model": settings.AI_MODEL, "messages": [
                           {"role": "system", "content": _OPTIMIZER_SYSTEM},
                           {"role": "user", "content": prompt},
                       ], "max_tokens": 500, "temperature": 0.1})
            data = r.json()
        if "choices" not in data:
            logger.warning(f"DeepSeek调参失败: {data.get('error', {}).get('message', '')}")
            return None
        content = data["choices"][0]["message"]["content"]
        for s in ("```json", "```"):
            if s in content:
                content = content.split(s)[1].split("```")[0]
        result = json.loads(content)
        if not result.get("need_adapt"):
            return None
        return result
    except Exception as exc:
        logger.warning(f"AI调参异常: {exc}")
        return None


def _clamp_params(sid: str, new_params: dict, old_params: dict) -> dict:
    """安全约束: 限幅+止损只增不减"""
    ranges = _PARAM_RANGES.get(sid, {})
    clamped = {}
    for k, (lo, hi) in ranges.items():
        if k not in new_params:
            continue
        v = float(new_params[k])
        v = max(lo, min(hi, v))
        # 止损只能增大
        if k in ("sl_pct",) and k in old_params:
            v = max(v, float(old_params[k]))
        # 单次调整幅度≤20%
        if k in old_params:
            old_v = float(old_params[k])
            v = max(old_v * 0.8, min(old_v * 1.2, v))
        # 限幅
        v = max(lo, min(hi, v))
        clamped[k] = round(v, 2)
    return clamped


def _persist_log(sid: str, symbol: str, old_params: dict, new_params: dict,
                 reason: str, metrics: dict):
    """持久化参数变更记录。"""
    try:
        from app.models.strategy import AdaptLog
        from app.core.database import get_sqlite_session
        s = get_sqlite_session()
        s.add(AdaptLog(
            ts=int(time.time()), strategy_id=sid, symbol=symbol,
            old_params=json.dumps(old_params), new_params=json.dumps(new_params),
            reason=reason, performance=json.dumps(metrics),
        ))
        s.commit()
        s.close()
    except Exception as exc:
        logger.warning(f"持久化adapt log失败: {exc}")


def optimize_one(sid: str, symbol: str) -> dict[str, Any] | None:
    """对一个策略+币种组合执行一次优化检查。返回调整结果或None。"""
    now = time.time()
    last = _last_adjust.get(f"{sid}:{symbol}", 0)
    if now - last < _MIN_ADJUST_INTERVAL:
        return None

    trades = _get_recent_trades(sid, symbol, 20)
    if len(trades) < 5:
        return None  # 样本不足

    metrics = _calc_metrics(trades)
    need, reason = _should_adapt(metrics)
    if not need:
        return None

    old_params = get_params(sid)
    if not old_params:
        return None

    # 获取当前市场状态
    market_state = "RANGING"
    confidence = 0.5
    try:
        from cryptoagents.ai.ai_service import list_reports
        reports = list_reports(symbol, limit=1)
        if reports:
            market_state = reports[0].get("market_state", "RANGING")
            confidence = reports[0].get("confidence", 0.5)
    except Exception:
        pass

    ai_result = _call_ai_for_params(sid, sid, old_params, metrics, market_state, confidence)
    if not ai_result:
        return None

    new_raw = ai_result.get("new_params", {})
    if not new_raw:
        return None

    clamped = _clamp_params(sid, new_raw, old_params)
    reason_full = f"{reason} | AI: {ai_result.get('reason', '')}"
    set_params(sid, clamped)
    _persist_log(sid, symbol, old_params, clamped, reason_full, metrics)
    _last_adjust[f"{sid}:{symbol}"] = now

    return {"strategy": sid, "symbol": symbol, "old": old_params, "new": clamped,
            "reason": reason_full, "metrics": metrics}


def optimize_all() -> list[dict]:
    """对所有监控币种+策略执行优化 (30秒定时调用)。"""
    from app.core import settings_store
    watchlist = settings_store.get("watchlist", settings.SYMBOLS_WATCHLIST)
    results = []
    for sid in ["S1", "S2", "S3", "S4", "S5", "S6"]:
        for symbol in watchlist:
            r = optimize_one(sid, symbol)
            if r:
                results.append(r)
    return results


def get_adapt_history(sid: str = "", limit: int = 30) -> list[dict]:
    from app.models.strategy import AdaptLog
    from app.core.database import get_sqlite_session
    s = get_sqlite_session()
    q = s.query(AdaptLog).order_by(AdaptLog.ts.desc())
    if sid:
        q = q.filter(AdaptLog.strategy_id == sid)
    rows = q.limit(limit).all()
    s.close()
    return [{
        "ts": r.ts, "strategy": r.strategy_id, "symbol": r.symbol,
        "old": json.loads(r.old_params or "{}"), "new": json.loads(r.new_params or "{}"),
        "reason": r.reason, "perf": json.loads(r.performance or "{}"),
    } for r in rows]
