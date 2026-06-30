from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings

router = APIRouter(prefix="/config", tags=["配置"])

_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


class ApiKeysRequest(BaseModel):
    exchange_api_key: str = ""
    exchange_secret: str = ""
    exchange_password: str = ""
    exchange_name: str = "binance"
    exchange_testnet: bool = True
    deepseek_api_key: str = ""


def _write_env(updates: dict[str, str]) -> None:
    """更新 .env 文件 (持久化密钥, 重启后仍生效)。"""
    lines: dict[str, str] = {}
    if _ENV_PATH.exists():
        for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                lines[k.strip()] = v
    for k, v in updates.items():
        lines[k] = v
    content = "\n".join(f"{k}={v}" for k, v in lines.items()) + "\n"
    _ENV_PATH.write_text(content, encoding="utf-8")


@router.get("")
def get_config():
    return {
        "exchange_name": settings.EXCHANGE_NAME,
        "exchange_testnet": settings.EXCHANGE_TESTNET,
        "trading_mode": settings.TRADING_MODE,
        "has_exchange_key": bool(settings.EXCHANGE_API_KEY),
        "has_exchange_password": bool(settings.EXCHANGE_PASSWORD),
        "has_deepseek_key": bool(settings.DEEPSEEK_API_KEY),
    }


@router.post("")
def save_config(req: ApiKeysRequest):
    env_updates: dict[str, str] = {}
    if req.exchange_api_key:
        settings.EXCHANGE_API_KEY = req.exchange_api_key
        env_updates["EXCHANGE_API_KEY"] = req.exchange_api_key
    if req.exchange_secret:
        settings.EXCHANGE_SECRET = req.exchange_secret
        env_updates["EXCHANGE_SECRET"] = req.exchange_secret
    if req.exchange_password is not None:
        settings.EXCHANGE_PASSWORD = req.exchange_password
        env_updates["EXCHANGE_PASSWORD"] = req.exchange_password
    if req.exchange_name:
        settings.EXCHANGE_NAME = req.exchange_name
        env_updates["EXCHANGE_NAME"] = req.exchange_name
    settings.EXCHANGE_TESTNET = req.exchange_testnet
    env_updates["EXCHANGE_TESTNET"] = str(req.exchange_testnet).lower()
    if req.deepseek_api_key:
        settings.DEEPSEEK_API_KEY = req.deepseek_api_key
        env_updates["DEEPSEEK_API_KEY"] = req.deepseek_api_key

    try:
        _write_env(env_updates)
    except Exception:
        pass

    # 同步到设置存储
    try:
        from app.core import settings_store
        settings_store.set_many({
            "exchange_name": settings.EXCHANGE_NAME,
            "exchange_testnet": settings.EXCHANGE_TESTNET,
        })
    except Exception:
        pass

    return {"status": "ok", "message": "配置已保存"}
