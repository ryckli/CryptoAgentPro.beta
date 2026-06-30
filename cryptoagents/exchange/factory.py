from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.logging_config import get_logger
from cryptoagents.exchange.base import ExchangeBase

logger = get_logger("exchange_factory")

_REGISTRY: dict[str, type[ExchangeBase]] = {}
_working: str | None = None  # 缓存可用交易所
_working_ts: float = 0.0  # 缓存时间戳，超时重新探测


def register(name: str, cls: type[ExchangeBase]):
    _REGISTRY[name] = cls


def _create(name: str, with_keys: bool = True, testnet: bool | None = None) -> ExchangeBase:
    """创建指定交易所实例。"""
    cls = _REGISTRY.get(name)
    if not cls:
        raise ValueError(f"未知交易所: {name}, 可用: {list(_REGISTRY.keys())}")
    tn = settings.EXCHANGE_TESTNET if testnet is None else testnet
    return cls(
        api_key=settings.EXCHANGE_API_KEY if with_keys else "",
        secret=settings.EXCHANGE_SECRET if with_keys else "",
        passphrase=settings.EXCHANGE_PASSWORD if with_keys else "",
        testnet=tn, with_keys=with_keys,
    )


def get_exchange(name: str | None = None, with_keys: bool = True,
                 testnet: bool | None = None) -> ExchangeBase:
    """获取交易所实例, 自动故障转移。"""
    global _working, _working_ts
    target = name or settings.EXCHANGE_NAME
    # 无密钥模式: 缓存60秒，超时重新探测
    if not with_keys:
        import time
        if _working and (time.time() - _working_ts) < 60:
            return _create(_working, with_keys=False, testnet=testnet or False)
        for ex_name in [target] + [n for n in _REGISTRY if n != target]:
            try:
                ex = _create(ex_name, with_keys=False, testnet=testnet or False)
                ex.fetch_ticker("BTC/USDT")
                _working = ex_name
                _working_ts = time.time()
                if ex_name != target:
                    logger.info(f"交易所 {target} 不可达, 自动切换到 {ex_name}")
                return ex
            except Exception:
                continue
        logger.warning("所有交易所不可达, 使用默认")
        return _create(target, with_keys=False, testnet=testnet or False)
    # 有密钥模式: 直接用配置的交易所
    return _create(target, with_keys=True, testnet=testnet)


def find_working_exchange() -> str:
    """探测可用交易所名称。"""
    global _working, _working_ts
    if _working:
        return _working
    target = settings.EXCHANGE_NAME
    for ex_name in [target] + [n for n in _REGISTRY if n != target]:
        try:
            ex = _create(ex_name, with_keys=False, testnet=False)
            ex.fetch_ticker("BTC/USDT")
            _working = ex_name
            return ex_name
        except Exception:
            continue
    return target


# 注册交易所
try:
    from cryptoagents.exchange.okx import OKXExchange
    register("okx", OKXExchange)
except Exception:
    pass

try:
    from cryptoagents.exchange.binance import BinanceExchange
    register("binance", BinanceExchange)
except Exception:
    pass

try:
    from cryptoagents.exchange.mcp_client import MCPExchange
    register("okx_mcp", MCPExchange)
    logger.info("OKX MCP Client registered (via Agent Trade Kit)")
except Exception as exc:
    logger.warning(f"OKX MCP Client not available: {exc}")
