from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from cryptoagents.strategy.base import STRATEGY_MARKET_MAP, MarketState


@dataclass
class PendingSwitch:
    from_strategy: str
    to_strategy: str
    ai_market_state: str
    confidence: float
    reasoning: str
    created_at: int


class StrategyScheduler:
    def __init__(self):
        self.current_strategy: dict[str, str] = {}
        self.pending_switches: dict[str, PendingSwitch] = {}

    def on_trend_change(self, symbol: str, ai_result: dict[str, Any]) -> dict[str, Any]:
        new_state = ai_result.get("market_state", "RANGING")
        try:
            ms = MarketState(new_state)
        except ValueError:
            ms = MarketState.RANGING
        recommended = STRATEGY_MARKET_MAP.get(ms, STRATEGY_MARKET_MAP[MarketState.RANGING])
        current = self.current_strategy.get(symbol, "NONE")

        if current == recommended["primary"]:
            return {"action": "keep", "current": current}

        if not settings.STRATEGY_SWITCH_CONFIRMATION:
            self.current_strategy[symbol] = recommended["primary"]
            return {"action": "switched", "from": current, "to": recommended["primary"]}

        self.pending_switches[symbol] = PendingSwitch(
            from_strategy=current, to_strategy=recommended["primary"],
            ai_market_state=new_state,
            confidence=float(ai_result.get("confidence", 0)),
            reasoning=str(ai_result.get("reasoning", "")),
            created_at=int(datetime.now(timezone.utc).timestamp()),
        )
        return {"action": "pending", "from": current, "to": recommended["primary"],
                "market_state": new_state, "confidence": ai_result.get("confidence", 0),
                "reasoning": ai_result.get("reasoning", "")}

    def get_current_strategy(self, symbol: str) -> str:
        return self.current_strategy.get(symbol, "S2")

    def has_pending(self, symbol: str) -> bool:
        return symbol in self.pending_switches

    def confirm(self, symbol: str) -> dict[str, Any]:
        p = self.pending_switches.pop(symbol, None)
        if not p:
            return {"action": "no_pending"}
        self.current_strategy[symbol] = p.to_strategy
        return {"action": "confirmed", "from": p.from_strategy, "to": p.to_strategy}

    def reject(self, symbol: str) -> dict[str, Any]:
        self.pending_switches.pop(symbol, None)
        return {"action": "rejected"}


scheduler = StrategyScheduler()
