"""熔断器 — 独立安全防护，监控全局风险指标。

双保险机制:
1. 连续亏损熔断: 连续 N 次亏损 → 强制停止
2. 回撤熔断: 权益从峰值回撤超 N% → 强制停止

独立于主循环运行，不阻塞 AI 决策。
"""

from __future__ import annotations

import time
from typing import Any, Callable

from app.core.logging_config import get_logger

logger = get_logger("safety_valve")


class SafetyValve:
    """熔断器 — 监控全局风险，触发时强制停止自动驾驶。

    使用方式:
        valve = SafetyValve(
            stop_callback=reactor.stop,
            get_equity=lambda: fetch_balance(),
            max_consecutive_losses=5,
            max_drawdown_pct=0.08,
        )
        valve.start_monitoring()  # 在后台线程中运行
    """

    def __init__(
        self,
        stop_callback: Callable[[], Any] | None = None,
        get_equity: Callable[[], float] | None = None,
        max_consecutive_losses: int = 5,
        max_drawdown_pct: float = 0.08,
        check_interval: float = 3.0,
    ):
        self._stop_callback = stop_callback
        self._get_equity = get_equity or (lambda: 10000.0)
        self.max_consecutive_losses = max_consecutive_losses
        self.max_drawdown_pct = max_drawdown_pct
        self.check_interval = check_interval

        # 状态
        self.peak_equity: float = 0.0
        self.consecutive_losses: int = 0
        self.total_trades: int = 0
        self.total_losses: int = 0
        self.triggered: bool = False
        self.trigger_reason: str = ""
        self._running: bool = False

    def on_trade_close(self, pnl: float):
        """每笔交易平仓后调用，更新连续亏损计数。

        Args:
            pnl: 该笔交易的盈亏 (正=盈利, 负=亏损)
        """
        self.total_trades += 1
        if pnl < 0:
            self.consecutive_losses += 1
            self.total_losses += 1
            logger.warning(
                f"[SafetyValve] 连续亏损 {self.consecutive_losses}/{self.max_consecutive_losses} "
                f"(本次: {pnl:.2f})"
            )
        else:
            self.consecutive_losses = 0  # 盈利重置连续亏损计数

    def check(self, current_equity: float | None = None) -> tuple[bool, str]:
        """检查是否触发熔断。

        Returns:
            (should_stop, reason): 是否应停止 + 原因
        """
        if current_equity is None:
            current_equity = self._get_equity()

        # 更新峰值
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity

        # 检查 1: 连续亏损
        if self.consecutive_losses >= self.max_consecutive_losses:
            self.triggered = True
            self.trigger_reason = (
                f"连续亏损 {self.consecutive_losses} 次 (上限 {self.max_consecutive_losses})"
            )
            return True, self.trigger_reason

        # 检查 2: 回撤
        if self.peak_equity > 0:
            drawdown = (self.peak_equity - current_equity) / self.peak_equity
            if drawdown > self.max_drawdown_pct:
                self.triggered = True
                self.trigger_reason = (
                    f"权益回撤 {drawdown:.1%} (上限 {self.max_drawdown_pct:.0%}), "
                    f"峰值 {self.peak_equity:.2f} → 当前 {current_equity:.2f}"
                )
                return True, self.trigger_reason

        return False, ""

    def reset(self):
        """重置熔断器状态 (手动重启时调用)。"""
        self.peak_equity = self._get_equity()
        self.consecutive_losses = 0
        self.total_trades = 0
        self.total_losses = 0
        self.triggered = False
        self.trigger_reason = ""
        logger.info("[SafetyValve] 熔断器已重置")

    def get_status(self) -> dict[str, Any]:
        """获取当前状态。"""
        current = self._get_equity()
        drawdown = 0.0
        if self.peak_equity > 0:
            drawdown = (self.peak_equity - current) / self.peak_equity
        return {
            "triggered": self.triggered,
            "trigger_reason": self.trigger_reason,
            "peak_equity": round(self.peak_equity, 2),
            "current_equity": round(current, 2),
            "drawdown_pct": round(drawdown * 100, 1),
            "drawdown_limit_pct": round(self.max_drawdown_pct * 100, 1),
            "consecutive_losses": self.consecutive_losses,
            "max_consecutive_losses": self.max_consecutive_losses,
            "total_trades": self.total_trades,
            "total_losses": self.total_losses,
        }
