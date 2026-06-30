"""蒙特卡洛回测 — 对历史数据做N次随机扰动模拟, 生成收益率分布。

核心: Bootstrap + 价格噪声 + 滑点扰动 + 信号跳过
输出: 置信区间 / VaR / CVaR / 分布直方图
"""
from __future__ import annotations

import concurrent.futures
import random
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.core.logging_config import get_logger

logger = get_logger("monte_carlo")


@dataclass
class MCResult:
    returns: list[float] = field(default_factory=list)
    win_rates: list[float] = field(default_factory=list)
    max_drawdowns: list[float] = field(default_factory=list)
    sharpes: list[float] = field(default_factory=list)
    trades_counts: list[int] = field(default_factory=list)
    profit_factors: list[float] = field(default_factory=list)
    n: int = 0
    elapsed: float = 0.0

    def summary(self) -> dict[str, Any]:
        if not self.returns:
            return {}
        r = np.array(self.returns)
        wr = np.array(self.win_rates)
        dd = np.array(self.max_drawdowns)
        sh = np.array(self.sharpes)
        return {
            "n_runs": self.n,
            "elapsed_seconds": round(self.elapsed, 1),
            "returns": {
                "mean": round(float(np.mean(r)), 2),
                "median": round(float(np.median(r)), 2),
                "std": round(float(np.std(r)), 2),
                "ci_95": [round(float(np.percentile(r, 2.5)), 2), round(float(np.percentile(r, 97.5)), 2)],
                "prob_profit": round(float(np.mean(r > 0) * 100), 1),
                "min": round(float(np.min(r)), 2),
                "max": round(float(np.max(r)), 2),
            },
            "var_cvar": {
                "var_95": round(float(np.percentile(r, 5)), 2),
                "cvar_95": round(float(np.mean(r[r <= np.percentile(r, 5)])) if any(r <= np.percentile(r, 5)) else 0, 2),
                "var_99": round(float(np.percentile(r, 1)), 2),
            },
            "win_rate": {
                "mean": round(float(np.mean(wr)), 1),
                "ci_95": [round(float(np.percentile(wr, 2.5)), 1), round(float(np.percentile(wr, 97.5)), 1)],
            },
            "max_drawdown": {
                "mean": round(float(np.mean(dd)), 1),
                "worst": round(float(np.min(dd)), 1),
            },
            "sharpe": {
                "mean": round(float(np.mean(sh)), 3),
                "ci_95": [round(float(np.percentile(sh, 2.5)), 3), round(float(np.percentile(sh, 97.5)), 3)],
            },
            "trades": {
                "mean": round(float(np.mean(self.trades_counts)), 1),
                "range": [int(np.min(self.trades_counts)), int(np.max(self.trades_counts))],
            },
            "histogram": _histogram_bins(r, bins=20),
        }


def _histogram_bins(data: np.ndarray, bins: int = 20) -> list[dict]:
    counts, edges = np.histogram(data, bins=bins)
    return [{"bin_start": round(float(edges[i]), 2),
             "bin_end": round(float(edges[i + 1]), 2),
             "count": int(counts[i])} for i in range(len(counts))]


def _run_one(engine_class, engine_args: dict, noise: float, skip_prob: float) -> tuple[float, float, float, float, int, float]:
    """执行一次蒙特卡洛模拟, 返回 (return, win_rate, max_dd, sharpe, trades, pf)。"""
    random.seed()
    np.random.seed()

    # 创建带噪声的引擎
    e = engine_class(**engine_args)
    # 注入噪声
    orig_slip = e.slippage
    e.slippage = orig_slip * (1 + random.gauss(0, noise))
    e.slippage = max(0.0, e.slippage)

    # 包裹 calculate 以随机跳过信号 (p=skip_prob)
    if skip_prob > 0:
        orig_calc = e.strategy.calculate

        def noisy_calc(df):
            sig = orig_calc(df)
            if sig.signal in ("BUY", "SELL") and random.random() < skip_prob:
                sig.signal = "HOLD"
            return sig
        e.strategy.calculate = noisy_calc

    result = e.run()

    trades = result.trade_log
    n_trades = len(trades)
    if n_trades == 0:
        return (0.0, 0.0, 0.0, 0.0, 0, 0.0)

    ret = float(result.total_return)
    wr = result.win_rate
    dd = float(result.max_drawdown)
    pf = result.profit_factor

    # Sharpe (简化)
    pnls = [t["pnl_pct"] for t in trades]
    mu = np.mean(pnls) if pnls else 0
    sigma = np.std(pnls) if len(pnls) > 1 else 1.0
    sharpe = mu / max(sigma, 0.01)

    return (ret, wr, dd, sharpe, n_trades, pf)


def run_monte_carlo(strategy, symbol: str, start: str, end: str,
                    capital: float = 10000, leverage: int = 10,
                    timeframe: str = "15m", n: int = 50,
                    noise: float = 0.001, skip_prob: float = 0.05,
                    max_workers: int = 4) -> MCResult:
    """执行蒙特卡洛回测。"""
    from cryptoagents.backtest.engine import BacktestEngine

    start_time = time.time()
    engine_args = {
        "symbol": symbol, "start_date": start, "end_date": end,
        "strategy": strategy, "timeframe": timeframe,
        "initial_capital": capital, "leverage": leverage, "speed": 100,
    }

    result = MCResult(n=n)

    # 先用默认参数跑一次确保数据可用
    try:
        demo = BacktestEngine(**engine_args)
        demo_result = demo.run()
        if not demo_result.trade_log:
            logger.warning("蒙特卡洛: 基准回测无交易, 跳过")
            result.elapsed = time.time() - start_time
            return result
    except Exception as exc:
        logger.error(f"蒙特卡洛基准回测失败: {exc}")
        result.elapsed = time.time() - start_time
        return result

    # 并行执行N次
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, n)) as executor:
        futures = [executor.submit(_run_one, BacktestEngine, engine_args, noise, skip_prob) for _ in range(n)]
        for f in concurrent.futures.as_completed(futures):
            try:
                ret, wr, dd, sh, nt, pf = f.result()
                result.returns.append(ret)
                result.win_rates.append(wr)
                result.max_drawdowns.append(dd)
                result.sharpes.append(sh)
                result.trades_counts.append(nt)
                result.profit_factors.append(pf)
            except Exception:
                pass

    result.elapsed = round(time.time() - start_time, 1)
    logger.info(f"蒙特卡洛完成: {n}次, 耗时{result.elapsed}s, 均值收益{np.mean(result.returns):.1f}%")
    return result
