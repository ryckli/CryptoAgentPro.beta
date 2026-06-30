from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.config import settings


class RiskGateway:
    def __init__(self):
        self.initial_capital = settings.RISK_INITIAL_CAPITAL
        self.daily_pnl: float = 0.0
        self.daily_trades: list[dict[str, Any]] = []
        self.trading_blocked: bool = False

    def check_order(self, order: dict[str, Any], capital: float = 0.0) -> tuple[bool, str]:
        if self.trading_blocked:
            return False, "当日已停盘"
        # 使用传入的测试网余额，未传则用初始本金
        cap = capital if capital > 0 else self.initial_capital
        max_loss = cap * settings.RISK_MAX_LOSS_PER_TRADE_PCT / 100
        est = float(order.get("estimated_loss", 0))
        if est > max_loss:
            return False, f"单笔预估亏损${est:.2f} > 上限${max_loss:.2f}"

        max_daily = cap * settings.RISK_MAX_DAILY_LOSS_PCT / 100
        if abs(self.daily_pnl) > max_daily:
            self.trading_blocked = True
            return False, "当日亏损达上限"

        margin = float(order.get("margin_required", 0))
        if margin > self.initial_capital * 0.8:
            return False, "保证金>80%"

        return True, "通过"

    def on_trade_close(self, pnl: float):
        self.daily_pnl += pnl
        self.daily_trades.append({"pnl": pnl, "timestamp": int(datetime.now(timezone.utc).timestamp())})

    def reset_daily(self):
        self.daily_pnl = 0.0
        self.daily_trades = []
        self.trading_blocked = False

    def get_status(self) -> dict[str, Any]:
        max_daily = self.initial_capital * settings.RISK_MAX_DAILY_LOSS_PCT / 100
        return {
            "trading_blocked": self.trading_blocked,
            "daily_pnl": round(self.daily_pnl, 2),
            "daily_pnl_pct": round(self.daily_pnl / self.initial_capital * 100, 2),
            "daily_trades_count": len(self.daily_trades),
            "max_daily_loss": round(max_daily, 2),
            "remaining_limit": round(max_daily - abs(self.daily_pnl), 2),
        }


risk_gateway = RiskGateway()
