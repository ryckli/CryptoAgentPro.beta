from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from cryptoagents.strategy.base import BaseStrategy
from cryptoagents.data.ccxt_fetcher import CCXTFetcher


@dataclass
class BacktestResultData:
    total_return: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    equity_curve: list[float] = field(default_factory=list)
    trade_log: list[dict[str, Any]] = field(default_factory=list)
    strategy: str = ""
    timeframe: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_return": f"{self.total_return:.2f}%",
            "win_rate": f"{self.win_rate:.1f}%",
            "total_trades": self.total_trades,
            "profit_factor": round(self.profit_factor, 2),
            "max_drawdown": f"{self.max_drawdown:.1f}%",
            "avg_win": f"+{self.avg_win:.1f}%",
            "avg_loss": f"-{abs(self.avg_loss):.1f}%",
            "equity_curve": self.equity_curve,
            "trade_log": self.trade_log,
            "strategy": self.strategy,
            "timeframe": self.timeframe,
        }


SPEEDS = [1, 2, 5, 10, 20, 100]


class BacktestEngine:
    def __init__(self, symbol: str, start_date: str, end_date: str, strategy: BaseStrategy,
                 initial_capital: float = 10000.0, leverage: int = 10,
                 commission: float = 0.0004, slippage: float = 0.0001,
                 speed: int = 1, task_id: str = "", timeframe: str = ""):
        self.symbol = symbol
        self.start_date = start_date
        self.end_date = end_date
        self.strategy = strategy
        self.timeframe = timeframe or strategy.timeframe()
        self.initial_capital = initial_capital
        self.leverage = leverage
        self.commission = commission
        self.slippage = slippage
        self.speed = max(1, min(speed, 100))
        self.position_size_pct = 100.0  # 默认全仓(100%保证金), 前端可覆盖
        self.task_id = task_id or f"bt_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        self._cancelled = False
        self.progress_callback = None
        self._current_step = 0
        self._total_steps = 0
        self._start_time = 0.0
        self._equity = initial_capital

    @property
    def equity(self) -> float:
        return self._equity

    def cancel(self):
        self._cancelled = True

    def set_speed(self, new_speed: int):
        self.speed = max(1, min(new_speed, 100))

    def run(self) -> BacktestResultData:
        result = BacktestResultData(strategy=self.strategy.strategy_id(), timeframe=self.timeframe)
        self._cancelled = False
        self._start_time = time.time()

        self._report(0, 100, 'fetching')
        fetcher = CCXTFetcher(with_keys=False, use_testnet=False)
        since_ms = int(datetime.fromisoformat(self.start_date).timestamp() * 1000)
        try:
            end_ms = int(datetime.fromisoformat(self.end_date).timestamp() * 1000)
        except Exception:
            end_ms = fetcher.exchange.milliseconds()
        def _fetch_progress(n, total):
            self._report(min(n, total), max(total, 1), 'fetching')
        df = fetcher.fetch_ohlcv_range(self.symbol, self.timeframe, since_ms, end_ms, progress_cb=_fetch_progress)

        if df.empty or len(df) < 50:
            self._report(0, 1)
            return result

        total = len(df) - 1 - 30
        self._total_steps = max(1, total // self.speed)
        self._current_step = 0

        capital = self.initial_capital
        peak = capital
        position: dict[str, Any] | None = None   # 单一持仓 (净持仓模型)
        trades: list[dict[str, Any]] = []
        equity: list[float] = [capital]

        def _close(pos, exit_price, exit_time, reason):
            nonlocal capital
            # 杠杆收益率(按价格变化)
            pnl_pct = (exit_price - pos["entry_price"]) / pos["entry_price"] * 100 * self.leverage
            if pos["direction"] == "SHORT":
                pnl_pct = -pnl_pct
            # 手续费
            fee_pct = self.commission * 2 * 100 * self.leverage
            pnl_pct -= fee_pct
            # 仓位规模=保证金比例x杠杆, pnl_pct已是杠杆后收益率
            # 实际盈亏 = 本金 x 保证金比例 x pnl_pct/100 (因为pnl_pct已含杠杆)
            position_weight = self.position_size_pct / 100  # 2% → 0.02
            capital += capital * position_weight * pnl_pct / 100
            trades.append({
                "entry_time": pos["entry_time"], "exit_time": exit_time,
                "direction": pos["direction"], "entry_price": round(pos["entry_price"], 4),
                "exit_price": round(exit_price, 4), "pnl_pct": round(pnl_pct, 2), "reason": reason,
            })

        i = 30
        while i < len(df) - 1:
            if self._cancelled:
                break
            batch_end = min(i + self.speed, len(df) - 1)
            for j in range(batch_end - i):
                gidx = i + j
                window = df.iloc[:gidx + 1]
                cp = float(df["close"].iloc[gidx])

                # 1) 先检查现有持仓是否触发 SL/TP
                # 用本根K线的最高/最低价做盘中检查 (避免只用收盘价漏掉盘中触发)
                if position is not None:
                    bar_low = float(df["low"].iloc[gidx])
                    bar_high = float(df["high"].iloc[gidx])
                    bar_close = float(df["close"].iloc[gidx])
                    entry = position["entry_price"]
                    sl_pct = position.get("stop_loss_pct", 1.8)
                    tp_pct = position.get("take_profit_pct", 2.0)
                    if position["direction"] == "LONG":
                        sl_price = entry * (1 - sl_pct / 100)
                        tp_price = entry * (1 + tp_pct / 100)
                        hit_sl = sl_pct > 0 and bar_low <= sl_price
                        hit_tp = tp_pct > 0 and bar_high >= tp_price
                    else:
                        sl_price = entry * (1 + sl_pct / 100)
                        tp_price = entry * (1 - tp_pct / 100)
                        hit_sl = sl_pct > 0 and bar_high >= sl_price
                        hit_tp = tp_pct > 0 and bar_low <= tp_price
                    # 先触发的那个决定平仓价
                    if hit_sl and hit_tp:
                        # 同时触发: 用更保守的价格
                        exit_pr = sl_price if position["direction"] == "LONG" else tp_price
                        _close(position, exit_pr, str(df.index[gidx]), "SL")
                    elif hit_sl:
                        _close(position, sl_price, str(df.index[gidx]), "SL")
                    elif hit_tp:
                        _close(position, tp_price, str(df.index[gidx]), "TP")
                    else:
                        pass  # 未触发
                    position = None if (hit_sl or hit_tp) else position

                # 2) 计算信号
                signal = self.strategy.calculate(window)

                # 3) 入场 (仅在无持仓时, 净持仓模型)
                # 使用下根开盘价入场 (避免未来函数: 信号在gidx收盘算出, 实际在gidx+1开盘执行)
                if signal.signal in ("BUY", "SELL") and position is None and gidx + 1 < len(df):
                    entry_price = float(df["open"].iloc[gidx + 1]) * (1 + self.slippage)
                    position = {
                        "direction": signal.direction, "entry_price": entry_price,
                        "entry_time": str(df.index[gidx + 1]),
                        "stop_loss_pct": signal.stop_loss_pct, "take_profit_pct": signal.take_profit_pct,
                    }
                    result.total_trades += 1

            equity.append(capital)
            peak = max(peak, capital)
            self._equity = capital
            self._current_step += 1
            self._report(self._current_step, self._total_steps)
            i = batch_end

        # 收尾: 强平剩余持仓
        if position is not None and not self._cancelled:
            _close(position, float(df["close"].iloc[-1]), str(df.index[-1]), "EOF")
            equity.append(capital)

        if self._cancelled:
            result.equity_curve = equity
            result.trade_log = trades
            return result

        if trades:
            wins = [t for t in trades if t["pnl_pct"] > 0]
            losses = [t for t in trades if t["pnl_pct"] < 0]
            result.win_rate = len(wins) / len(trades) * 100 if trades else 0
            result.avg_win = sum(t["pnl_pct"] for t in wins) / len(wins) if wins else 0
            result.avg_loss = abs(sum(t["pnl_pct"] for t in losses) / len(losses)) if losses else 0
            tw = sum(t["pnl_pct"] for t in wins)
            tl = abs(sum(t["pnl_pct"] for t in losses))
            result.profit_factor = tw / tl if tl else 0

        result.total_return = (capital - self.initial_capital) / self.initial_capital * 100
        result.max_drawdown = min((e - peak) / peak * 100 for e in equity) if equity else 0
        result.equity_curve = equity
        result.trade_log = trades
        self._report(self._total_steps, self._total_steps)
        return result

    def _report(self, current: int, total: int, phase: str = ''):
        elapsed = time.time() - self._start_time
        pct = min(100.0, current / total * 100) if total > 0 else 100.0
        if phase == 'fetching':
            pct = max(1.0, min(99.0, current / total * 100)) if total > 0 else 1.0
        if current > 0 and current < total:
            est = max(0, elapsed / current * total - elapsed)
        else:
            est = 0.0
        if self.progress_callback:
            self.progress_callback({
                "task_id": self.task_id,
                "status": "cancelled" if self._cancelled else ("completed" if current >= total else "running"),
                "progress_pct": round(pct, 1),
                "current_step": current, "total_steps": total,
                "speed": self.speed, "current_equity": round(self._equity, 2),
                "estimated_remaining_seconds": round(est, 1),
            })
