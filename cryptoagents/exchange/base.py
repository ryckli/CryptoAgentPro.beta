from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd


class ExchangeBase(ABC):
    """统一交易所接口基类 — 所有交易所实现此接口。"""

    name: str = ""
    base_url: str = ""
    testnet: bool = False

    @abstractmethod
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 100, since: int | None = None) -> pd.DataFrame:
        """拉K线, 返回 timestamp-indexed DataFrame [open,high,low,close,volume]。"""
        ...

    @abstractmethod
    def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        """拉现价, 返回 {"last":float,"bid":float,"ask":float,"timestamp":int}。"""
        ...

    @abstractmethod
    def fetch_positions(self, symbols: list[str] | None = None) -> list[dict[str, Any]]:
        """查持仓, 返回 [{"symbol":str,"direction":"LONG"/"SHORT","qty":float,
        "entry_price":float,"leverage":int}]。"""
        ...

    @abstractmethod
    def place_market_order(self, symbol: str, side: str, qty: float,
                           reduce_only: bool = False, sl_price: float = 0,
                           tp_price: float = 0, leverage: int = 0) -> dict[str, Any]:
        """市价下单, 返回 {"id":str,"status":str,"message":str}。"""
        ...

    @abstractmethod
    def fetch_account_balance(self) -> dict[str, Any]:
        """查账户余额, 返回 {"total":float,"available":float}。"""
        ...

    def set_leverage(self, symbol: str, leverage: int) -> None:
        """设杠杆 (可选实现)。"""
        pass

    def load_markets(self) -> dict[str, Any]:
        """加载交易对信息 (可选)。"""
        return {}

    @staticmethod
    def milliseconds() -> int:
        import time
        return int(time.time() * 1000)

    @property
    def rate_limit_ms(self) -> int:
        return 200
