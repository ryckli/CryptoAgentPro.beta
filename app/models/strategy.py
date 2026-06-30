from __future__ import annotations

from sqlalchemy import Column, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class KlineCache(Base):
    __tablename__ = "kline_cache"
    symbol = Column(String, primary_key=True)
    timeframe = Column(String, primary_key=True)
    timestamp = Column(Integer, primary_key=True)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)


class AITrendLog(Base):
    __tablename__ = "ai_trend_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(Integer, nullable=False)
    symbol = Column(String, nullable=False)
    market_state = Column(String, nullable=False)
    confidence = Column(Float)
    recommended_str = Column(String)


class TradeLog(Base):
    __tablename__ = "trade_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(Integer, nullable=False)
    symbol = Column(String, nullable=False)
    strategy_id = Column(String, nullable=False)
    direction = Column(String, nullable=False)
    entry_price = Column(Float)
    exit_price = Column(Float)
    pnl = Column(Float)
    pnl_pct = Column(Float)


class BacktestResult(Base):
    __tablename__ = "backtest_results"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(Integer, nullable=False)
    strategy_id = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    timeframe = Column(String, nullable=False)
    total_return = Column(Float)
    win_rate = Column(Float)
    total_trades = Column(Integer)
    result_json = Column(Text)


class AIReport(Base):
    """AI 趋势感知报告 (15分钟定时生成)"""
    __tablename__ = "ai_reports"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(Integer, nullable=False)
    symbol = Column(String, nullable=False)
    market_state = Column(String, nullable=False)
    confidence = Column(Float)
    recommended_strategy = Column(String)
    suggested_leverage = Column(Integer)
    risk_level = Column(String)
    reasoning = Column(Text)
    key_levels_json = Column(Text)
    action = Column(String)  # keep / pending / switched / auto_traded
    triggered_by = Column(String, default="schedule")  # schedule / manual


class AppSetting(Base):
    """通用 KV 配置存储 (策略参数/风控参数/调度开关等前端可改项)"""
    __tablename__ = "app_settings"
    key = Column(String, primary_key=True)
    value_json = Column(Text)
    updated_at = Column(Integer)


class CustomStrategy(Base):
    """用户手动创建的参数化策略"""
    __tablename__ = "custom_strategies"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    base_type = Column(String, nullable=False)  # 基于哪类指标: ema_cross / rsi / macd / boll
    params_json = Column(Text)
    enabled = Column(Integer, default=1)
    created_at = Column(Integer)


class PaperOrder(Base):
    """模拟盘订单/持仓记录"""
    __tablename__ = "paper_orders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    opened_at = Column(Integer, nullable=False)
    closed_at = Column(Integer)
    symbol = Column(String, nullable=False)
    strategy_id = Column(String)
    direction = Column(String, nullable=False)
    qty = Column(Float)
    leverage = Column(Integer)
    entry_price = Column(Float)
    exit_price = Column(Float)
    stop_loss = Column(Float)
    take_profit = Column(Float)
    pnl = Column(Float)
    pnl_pct = Column(Float)
    status = Column(String, default="open")  # open / closed
    mode = Column(String, default="paper")


class AdaptLog(Base):
    """AI自适应参数调整记录"""
    __tablename__ = "adapt_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(Integer, nullable=False)
    strategy_id = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    old_params = Column(Text)
    new_params = Column(Text)
    reason = Column(Text)
    performance = Column(Text)
