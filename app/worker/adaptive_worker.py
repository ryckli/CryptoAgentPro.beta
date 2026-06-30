"""30秒自适应参数优化定时任务 — APScheduler管理。"""
from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.logging_config import get_logger

logger = get_logger("adaptive_worker")

_scheduler: BackgroundScheduler | None = None
_JOB_ID = "adaptive_optimize"


def _optimize_job():
    try:
        from cryptoagents.ai.adaptive_optimizer import optimize_all
        results = optimize_all()
        if results:
            logger.info(f"自适应优化完成: {len(results)} 个策略参数调整")
            for r in results:
                logger.info(f"  {r['strategy']}/{r['symbol']}: {r['reason']}")
    except Exception as exc:
        logger.error(f"自适应优化异常: {exc}")


def start_adaptive():
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(_optimize_job, IntervalTrigger(seconds=30),
                       id=_JOB_ID, replace_existing=True, max_instances=1)
    _scheduler.start()
    logger.info("自适应优化调度器已启动 (30秒间隔)")


def stop_adaptive():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
