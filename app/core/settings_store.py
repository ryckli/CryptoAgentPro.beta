"""运行时设置存储 — 把前端可自定义项持久化到 SQLite 的 app_settings 表。

提供默认值 + 读取/写入 + 应用到 settings 单例。
"""
from __future__ import annotations

import json
import time
from typing import Any

from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger("settings_store")

# 所有可被前端修改的项及其默认值
DEFAULTS: dict[str, Any] = {
    # 交易模式
    "trading_mode": settings.TRADING_MODE,        # paper / testnet
    "auto_trade": settings.AUTO_TRADE,            # 是否自动下单
    "exchange_name": settings.EXCHANGE_NAME,
    "exchange_testnet": settings.EXCHANGE_TESTNET,
    # 风控参数
    "risk_initial_capital": settings.RISK_INITIAL_CAPITAL,
    "risk_max_leverage": settings.RISK_MAX_LEVERAGE,
    "risk_max_loss_per_trade_pct": settings.RISK_MAX_LOSS_PER_TRADE_PCT,
    "risk_max_daily_loss_pct": settings.RISK_MAX_DAILY_LOSS_PCT,
    "risk_min_stop_distance_pct": settings.RISK_MIN_STOP_DISTANCE_PCT,
    # 策略调度
    "strategy_switch_confirmation": settings.STRATEGY_SWITCH_CONFIRMATION,
    # 监控币种
    "watchlist": settings.SYMBOLS_WATCHLIST,
    # AI 调度
    "ai_schedule_enabled": True,
    "ai_schedule_minutes": 15,
    "ai_model": settings.AI_MODEL,
    "ai_temperature": settings.AI_TEMPERATURE,
}


def _session():
    from app.core.database import get_sqlite_session
    return get_sqlite_session()


def get_all() -> dict[str, Any]:
    """返回合并了默认值与已存储覆盖值的完整设置字典。"""
    from app.models.strategy import AppSetting
    result = dict(DEFAULTS)
    try:
        s = _session()
        for row in s.query(AppSetting).all():
            try:
                result[row.key] = json.loads(row.value_json)
            except Exception:
                pass
        s.close()
    except Exception as e:
        logger.warning(f"读取设置失败: {e}")
    return result


def get(key: str, default: Any = None) -> Any:
    return get_all().get(key, default if default is not None else DEFAULTS.get(key))


def set_many(updates: dict[str, Any]) -> dict[str, Any]:
    """批量写入设置并应用到 settings 单例。"""
    from app.models.strategy import AppSetting
    s = _session()
    now = int(time.time())
    for k, v in updates.items():
        row = s.get(AppSetting, k)
        if row:
            row.value_json = json.dumps(v)
            row.updated_at = now
        else:
            s.add(AppSetting(key=k, value_json=json.dumps(v), updated_at=now))
    s.commit()
    s.close()
    apply_to_settings()
    return get_all()


def apply_to_settings() -> None:
    """把存储的设置同步到内存 settings 单例，使各模块即时生效。"""
    cfg = get_all()
    settings.TRADING_MODE = cfg["trading_mode"]
    settings.AUTO_TRADE = bool(cfg["auto_trade"])
    settings.EXCHANGE_NAME = cfg["exchange_name"]
    settings.EXCHANGE_TESTNET = bool(cfg["exchange_testnet"])
    settings.RISK_INITIAL_CAPITAL = float(cfg["risk_initial_capital"])
    settings.RISK_MAX_LEVERAGE = int(cfg["risk_max_leverage"])
    settings.RISK_MAX_LOSS_PER_TRADE_PCT = float(cfg["risk_max_loss_per_trade_pct"])
    settings.RISK_MAX_DAILY_LOSS_PCT = float(cfg["risk_max_daily_loss_pct"])
    settings.RISK_MIN_STOP_DISTANCE_PCT = float(cfg["risk_min_stop_distance_pct"])
    settings.STRATEGY_SWITCH_CONFIRMATION = bool(cfg["strategy_switch_confirmation"])
    settings.SYMBOLS_WATCHLIST = list(cfg["watchlist"])
    settings.AI_MODEL = cfg["ai_model"]
    settings.AI_TEMPERATURE = float(cfg["ai_temperature"])
