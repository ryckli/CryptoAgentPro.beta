"""AI 趋势感知服务 — 被 15分钟定时任务和手动触发共用。

流程: 拉K线 -> DeepSeek分析 -> 存报告 -> 通知策略调度器 -> (可选)自动建议/下单
"""
from __future__ import annotations

import json
import time
from typing import Any

from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger("ai_service")


def run_sensing(symbol: str, triggered_by: str = "schedule", position: dict | None = None) -> dict[str, Any]:
    """对单个币种执行一次完整的趋势感知, 返回报告 dict。"""
    from cryptoagents.data.ccxt_fetcher import CCXTFetcher
    from cryptoagents.ai.trend_analyzer import analyze_trend
    from cryptoagents.strategy.scheduler import scheduler

    try:
        fetcher = CCXTFetcher(with_keys=False, use_testnet=False)
        df_15m = fetcher.fetch_ohlcv(symbol, "15m", limit=200)
        df_1h = fetcher.fetch_ohlcv(symbol, "1h", limit=50)
    except Exception as exc:
        logger.warning(f"[{symbol}] 拉取K线失败: {exc}")
        return {"symbol": symbol, "error": str(exc)}

    if df_15m.empty:
        return {"symbol": symbol, "error": "无K线数据"}

    result = analyze_trend(symbol, df_15m, df_1h, position)
    trend = result.to_dict()

    # 通知策略调度器 (产生 keep/pending/switched)
    switch = scheduler.on_trend_change(symbol, trend)
    action = switch.get("action", "keep")

    # 可选自动交易 (仅当 AUTO_TRADE 且调度器已切换/确认)
    auto_traded = False
    if settings.AUTO_TRADE and action == "switched":
        try:
            from cryptoagents.execution.executor import ExecutionEngine
            sid = switch.get("to", scheduler.get_current_strategy(symbol))
            from cryptoagents.strategy.strategies import get_strategy
            strat = get_strategy(sid)
            sig = strat.calculate(df_15m).to_dict()
            if sig["signal"] in ("BUY", "SELL"):
                ExecutionEngine().execute_with_risk_params(sig, symbol, strategy_id=sid)
                auto_traded = True
                action = "auto_traded"
        except Exception as exc:
            logger.error(f"[{symbol}] 自动交易失败: {exc}")

    report = {
        "symbol": symbol,
        "created_at": int(time.time()),
        "market_state": trend["market_state"],
        "confidence": trend["confidence"],
        "recommended_strategy": trend["recommended_strategy"],
        "suggested_leverage": trend["suggested_leverage"],
        "risk_level": trend["risk_level"],
        "reasoning": trend["reasoning"],
        "key_levels": trend.get("key_levels", {}),
        "action": action,
        "auto_traded": auto_traded,
        "triggered_by": triggered_by,
    }
    _persist(report)
    logger.info(f"[{symbol}] 趋势感知: {trend['market_state']} 置信{trend['confidence']} -> {action}")
    return report


def _persist(report: dict[str, Any]) -> None:
    try:
        from app.models.strategy import AIReport
        from app.core.database import get_sqlite_session
        s = get_sqlite_session()
        s.add(AIReport(
            created_at=report["created_at"], symbol=report["symbol"],
            market_state=report["market_state"], confidence=report["confidence"],
            recommended_strategy=report["recommended_strategy"],
            suggested_leverage=report["suggested_leverage"], risk_level=report["risk_level"],
            reasoning=report["reasoning"], key_levels_json=json.dumps(report.get("key_levels", {})),
            action=report["action"], triggered_by=report["triggered_by"],
        ))
        s.commit()
        s.close()
    except Exception as exc:
        logger.warning(f"报告持久化失败: {exc}")


def run_sensing_all() -> list[dict[str, Any]]:
    """对监控列表所有币种执行感知 (定时任务入口)。"""
    from app.core import settings_store
    watchlist = settings_store.get("watchlist", settings.SYMBOLS_WATCHLIST)
    reports = []
    for sym in watchlist:
        reports.append(run_sensing(sym, triggered_by="schedule"))
    return reports


def list_reports(symbol: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    from app.models.strategy import AIReport
    from app.core.database import get_sqlite_session
    s = get_sqlite_session()
    q = s.query(AIReport).order_by(AIReport.created_at.desc())
    if symbol:
        q = q.filter(AIReport.symbol == symbol)
    rows = q.limit(limit).all()
    out = [{
        "id": r.id, "created_at": r.created_at, "symbol": r.symbol,
        "market_state": r.market_state, "confidence": r.confidence,
        "recommended_strategy": r.recommended_strategy, "suggested_leverage": r.suggested_leverage,
        "risk_level": r.risk_level, "reasoning": r.reasoning,
        "key_levels": json.loads(r.key_levels_json or "{}"),
        "action": r.action, "triggered_by": r.triggered_by,
    } for r in rows]
    s.close()
    return out
