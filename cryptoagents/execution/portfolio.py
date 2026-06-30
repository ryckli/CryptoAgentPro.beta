"""多币种组合优化器 — 风险平价分配 + Kelly最优下注 + 动态再平衡。

基于现代组合理论 (MPT) 和 Kelly Criterion, 在监控币种间优化资金分配。
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger("portfolio")


def returns_matrix(symbols: list[str], lookback_bars: int = 60) -> dict[str, np.ndarray]:
    """拉取各币种1H收益率序列，返回 {symbol: array of returns}。"""
    from cryptoagents.data.ccxt_fetcher import CCXTFetcher
    fetcher = CCXTFetcher(with_keys=False, use_testnet=False)
    result = {}
    for sym in symbols:
        try:
            df = fetcher.fetch_ohlcv(sym, "1h", limit=lookback_bars + 1)
            if len(df) >= 10:
                rets = df["close"].pct_change().dropna().values
                result[sym] = rets
        except Exception as exc:
            logger.warning(f"{sym} 收益率拉取失败: {exc}")
    return result


def correlation_matrix(returns: dict[str, np.ndarray]) -> dict[str, dict[str, float]]:
    """计算币种间 Pearson 相关系数矩阵。"""
    symbols = list(returns.keys())
    n = len(symbols)
    if n < 2:
        return {s: {s: 1.0} for s in symbols}
    # 对齐长度
    min_len = min(len(r) for r in returns.values())
    mat_data = np.array([returns[s][-min_len:] for s in symbols])
    corr = np.corrcoef(mat_data)
    result = {}
    for i, si in enumerate(symbols):
        result[si] = {}
        for j, sj in enumerate(symbols):
            result[si][sj] = round(float(corr[i][j]), 4)
    return result


def risk_parity_weights(returns: dict[str, np.ndarray]) -> dict[str, float]:
    """风险平价 (Equal Risk Contribution): 每个币种对组合的边际风险相等。

    波动率越高的币种分配越少资金，实现风险分散最大化。
    若无法收敛，回退为 1/vol 反波动率加权。
    """
    symbols = list(returns.keys())
    n = len(symbols)
    if n == 0:
        return {}
    if n == 1:
        return {symbols[0]: 1.0}

    min_len = min(len(r) for r in returns.values())
    ret_matrix = np.array([returns[s][-min_len:] for s in symbols])
    cov = np.cov(ret_matrix)
    vols = np.sqrt(np.diag(cov))

    # 1/vol 反波动率加权 (简洁且稳健)
    inv_vol = 1.0 / np.maximum(vols, 1e-9)
    weights = inv_vol / inv_vol.sum()

    # 尝试数值求解风险平价 (若失败则保持反波动率)
    try:
        def rp_objective(w):
            sigma = np.sqrt(w @ cov @ w)
            mrc = (cov @ w) / max(sigma, 1e-9)
            rc = w * mrc
            target = sigma / n
            return np.sum((rc - target) ** 2)

        from scipy.optimize import minimize
        bounds = [(0.01, 0.99)] * n
        cons = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
        result = minimize(rp_objective, weights, bounds=bounds, constraints=cons,
                          method="SLSQP", options={"maxiter": 200, "ftol": 1e-8})
        if result.success:
            weights = result.x
    except Exception:
        pass

    return {s: round(float(w), 4) for s, w in zip(symbols, weights)}


def kelly_fraction(win_rate: float, avg_win_pct: float, avg_loss_pct: float) -> float:
    """Kelly Criterion: f* = (p*b - q) / b

    p=胜率, q=1-p, b=avg_win/avg_loss (盈亏比)
    返回建议的资本分数 (0~1), 实际使用1/4 Kelly (极保守)
    """
    if avg_loss_pct <= 0 or avg_win_pct <= 0:
        return 0.0
    p = max(0.0, min(1.0, win_rate / 100))
    b = avg_win_pct / avg_loss_pct
    f_star = max(0.0, (p * b - (1 - p)) / max(b, 1e-9))
    return round(min(f_star * 0.25, 0.25), 4)  # 1/4 Kelly capped at 25%


def allocate_capital(capital: float, symbols: list[str],
                     strategy_metrics: dict[str, dict] | None = None) -> dict[str, dict]:
    """完整的三层资金分配。

    返回 {symbol: {weight, capital, kelly_fraction, max_position}}
    strategy_metrics: 可选, {symbol: {win_rate, avg_win, avg_loss}}
    """
    rets = returns_matrix(symbols)
    if not rets:
        return {s: {"weight": round(1.0/len(symbols), 4) if symbols else 0,
                     "capital": round(capital/len(symbols), 2) if symbols else 0,
                     "kelly_fraction": 0, "max_position": 0} for s in symbols}

    weights = risk_parity_weights(rets)
    corr = correlation_matrix(rets)

    result = {}
    for s in symbols:
        w = weights.get(s, 0)
        alloc = capital * w
        # Kelly
        kf = 0.05  # 默认5%
        if strategy_metrics and s in strategy_metrics:
            m = strategy_metrics[s]
            kf = kelly_fraction(m.get("win_rate", 50), m.get("avg_win", 1.0), m.get("avg_loss", 1.0))
        kf = max(0.01, kf)  # 至少1%，避免完全不开仓
        result[s] = {
            "weight": w,
            "capital": round(alloc, 2),
            "kelly_fraction": kf,
            "max_position": round(alloc * kf, 2),
            "annualized_vol": round(float(np.std(rets[s]) * math.sqrt(365*24)) * 100, 1) if s in rets else 0,
        }

    # 补充相关性信息
    for s in symbols:
        if s in corr and symbols:
            others = {o: corr[s][o] for o in symbols if o != s}
            avg_corr = sum(others.values()) / len(others) if others else 0
            result[s]["avg_correlation"] = round(avg_corr, 3)

    return result


def allocation_summary(capital: float, symbols: list[str]) -> dict[str, Any]:
    """组合分配摘要 (供前端展示)。"""
    alloc = allocate_capital(capital, symbols)
    diversification = 1.0
    if len(symbols) > 1:
        corrs = [alloc[s].get("avg_correlation", 0) for s in symbols]
        avg_corr = sum(corrs) / len(corrs) if corrs else 0
        diversification = round(1.0 - max(0, min(1, avg_corr)), 2)
    return {
        "capital": capital,
        "allocations": alloc,
        "diversification_score": diversification,
        "total_allocated": round(sum(a["capital"] for a in alloc.values()), 2),
    }
