"""APScheduler 后台调度器 — 每 N 分钟自动触发 AI 趋势感知。

由 FastAPI lifespan 启动/停止。间隔与开关由 settings_store 控制, 可前端动态调整。
"""
from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.logging_config import get_logger

logger = get_logger("scheduler_worker")

_scheduler: BackgroundScheduler | None = None
_JOB_ID = "ai_sensing"


def _sensing_job():
    try:
        from cryptoagents.ai.ai_service import run_sensing_all
        from app.core import settings_store
        if not settings_store.get("ai_schedule_enabled", True):
            return
        logger.info("定时任务: 开始 AI 趋势感知...")
        run_sensing_all()
    except Exception as exc:
        logger.error(f"定时感知任务异常: {exc}")


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        return
    from app.core import settings_store
    minutes = int(settings_store.get("ai_schedule_minutes", 15))
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(_sensing_job, IntervalTrigger(minutes=minutes),
                       id=_JOB_ID, replace_existing=True, max_instances=1)
    _scheduler.start()
    logger.info(f"调度器已启动, AI感知间隔 {minutes} 分钟")


def reschedule(minutes: int):
    """前端改间隔时调用。"""
    if _scheduler is None:
        return
    _scheduler.reschedule_job(_JOB_ID, trigger=IntervalTrigger(minutes=max(1, minutes)))
    logger.info(f"调度间隔已调整为 {minutes} 分钟")


def trigger_now():
    """立即执行一次 (前端手动触发全量感知)。"""
    if _scheduler is not None:
        _scheduler.add_job(_sensing_job, id=f"{_JOB_ID}_manual", replace_existing=True)


def stop_scheduler():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("调度器已停止")


def status() -> dict:
    from app.core import settings_store
    running = _scheduler is not None and _scheduler.running
    next_run = None
    if running:
        job = _scheduler.get_job(_JOB_ID)
        if job and job.next_run_time:
            next_run = job.next_run_time.isoformat()
    return {
        "running": running,
        "enabled": settings_store.get("ai_schedule_enabled", True),
        "interval_minutes": settings_store.get("ai_schedule_minutes", 15),
        "next_run": next_run,
    }
