from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class BacktestRequest(BaseModel):
    strategy_id: str = "S1"
    symbol: str = "BTC/USDT"
    timeframe: str = "15m"
    start_date: str = "2024-01-01"
    end_date: str = "2024-12-31"
    initial_capital: float = 10000.0
    leverage: int = 10
    speed: int = 1
    position_size_pct: float = 100.0  # 仓位保证金比例%: 默认全仓, 设2可对齐模拟盘


class TradeOrderRequest(BaseModel):
    symbol: str
    direction: str
    quantity: float = 0.01
    stop_loss_pct: float = 1.8
    take_profit_pct: float = 2.0


class StrategyActivateRequest(BaseModel):
    symbol: str
    strategy_id: str


class SpeedRequest(BaseModel):
    speed: int


class TrendConfirmRequest(BaseModel):
    symbol: str
    action: str = "confirm"
