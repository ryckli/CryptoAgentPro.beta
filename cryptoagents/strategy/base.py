from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StrategyType(Enum):
    S1_EMA_TREND = "双EMA趋势追随"
    S2_RSI_REVERSAL = "RSI均值回归"
    S3_MACD_RESONANCE = "MACD多维度共振"
    S4_MARTINGALE = "马丁逆势反弹"
    S5_EMA_SCALPING = "EMA中间点刮头皮"
    S6_TD9_EXTREME = "TD9超买超卖"



class MarketState(Enum):
    STRONG_BULL = "strong_bull"
    STRONG_BEAR = "strong_bear"
    WEAK_BULL = "weak_bull"
    WEAK_BEAR = "weak_bear"
    RANGING = "ranging"
    CRASH_BOUNCE = "crash_bounce"
    PUMP_REVERSAL = "pump_reversal"
    TREND_CHANGE = "trend_change"


@dataclass
class Signal:
    signal: str
    strength: str = "NONE"
    strategy: str = ""
    direction: str = ""
    entry_price: float = 0.0
    stop_loss_pct: float = 0.0
    take_profit_pct: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal, "strength": self.strength,
            "strategy": self.strategy, "direction": self.direction,
            "stop_loss_pct": self.stop_loss_pct, "take_profit_pct": self.take_profit_pct,
            "metadata": {k: round(v, 6) if isinstance(v, float) else v for k, v in self.metadata.items()},
        }


class BaseStrategy(ABC):
    strategy_type: StrategyType
    best_markets: list[MarketState] = []
    params: dict = {}

    @abstractmethod
    def name(self) -> str: ...
    @abstractmethod
    def strategy_id(self) -> str: ...
    @abstractmethod
    def timeframe(self) -> str: ...
    @abstractmethod
    def calculate(self, df) -> Signal: ...

    @staticmethod
    def _ema(s, span): return s.ewm(span=span, adjust=False).mean()
    @staticmethod
    def _macd(df):
        e12 = df["close"].ewm(span=12, adjust=False).mean()
        e26 = df["close"].ewm(span=26, adjust=False).mean()
        d = e12 - e26
        dea = d.ewm(span=9, adjust=False).mean()
        return d, dea, (d - dea) * 2
    @staticmethod
    def _rsi(df, p=14):
        d = df["close"].diff()
        g = d.where(d > 0, 0.0).rolling(p).mean()
        l = (-d.where(d < 0, 0.0)).rolling(p).mean()
        return 100.0 - (100.0 / (1.0 + g / (l + 1e-10)))
    @staticmethod
    def _boll(df, p=20):
        m = df["close"].rolling(p).mean()
        s = df["close"].rolling(p).std()
        return m + 2 * s, m, m - 2 * s

    @staticmethod
    def _trend_filter(df, direction: str) -> bool:
        """趋势对齐过滤器: MA20 vs MA50 判断宏观趋势。
        若 direction=LONG 则仅在牛市中开多, SHORT 仅在熊市中开空。
        返回 True=通过, False=逆势拦截。"""
        if len(df) < 50:
            return True
        ma20 = df["close"].rolling(20).mean().iloc[-1]
        ma50 = df["close"].rolling(50).mean().iloc[-1]
        ma20_prev = df["close"].rolling(20).mean().iloc[-5]
        trend_up = ma20 > ma50 and ma20 > ma20_prev
        trend_down = ma20 < ma50 and ma20 < ma20_prev
        if direction == "LONG" and trend_down:
            return False
        if direction == "SHORT" and trend_up:
            return False
        return True

    @staticmethod
    def _vol_filter(df, multiplier: float = 0.7) -> bool:
        """成交量过滤器: 当前量需 > 20日均量*multiplier, 避免低流动性时段。"""
        if "volume" not in df.columns or len(df) < 21:
            return True
        avg_vol = df["volume"].rolling(20).mean().iloc[-1]
        return float(df["volume"].iloc[-1]) >= avg_vol * multiplier


STRATEGY_MARKET_MAP = {
    MarketState.STRONG_BULL:   {"primary": "S1", "fallback": "S5", "direction": "LONG_ONLY"},
    MarketState.STRONG_BEAR:   {"primary": "S1", "fallback": "S5", "direction": "SHORT_ONLY"},
    MarketState.WEAK_BULL:     {"primary": "S5", "fallback": "S2", "direction": "LONG_ONLY"},
    MarketState.WEAK_BEAR:     {"primary": "S5", "fallback": "S2", "direction": "SHORT_ONLY"},
    MarketState.RANGING:       {"primary": "S2", "fallback": "S6", "direction": "BOTH"},
    MarketState.CRASH_BOUNCE:  {"primary": "S4", "fallback": "S2", "direction": "LONG_ONLY"},
    MarketState.PUMP_REVERSAL: {"primary": "S4", "fallback": "S2", "direction": "SHORT_ONLY"},
    MarketState.TREND_CHANGE:  {"primary": "S3", "fallback": "S2", "direction": "BOTH"},
}
