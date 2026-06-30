from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Exchange ---
    EXCHANGE_NAME: str = "binance"
    EXCHANGE_TESTNET: bool = True
    EXCHANGE_API_KEY: str = ""
    EXCHANGE_SECRET: str = ""
    EXCHANGE_PASSWORD: str = ""  # 部分交易所(如OKX)需要 passphrase

    # --- Trading Mode ---
    # paper = 本地模拟撮合 (默认最安全) | testnet = 交易所测试网 (无真实资金风险)
    TRADING_MODE: str = "paper"
    AUTO_TRADE: bool = False  # AI/调度是否自动下单 (默认关闭, 仅建议)
    DRY_RUN: bool = False  # 干跑模式: testnet下不实际下单，仅验证流程

    # --- AI ---
    AI_PROVIDER: str = "deepseek"
    AI_MODEL: str = "deepseek-chat"
    DEEPSEEK_API_KEY: str = ""
    AI_MAX_TOKENS: int = 2000
    AI_TEMPERATURE: float = 0.1

    # --- Database ---
    MONGODB_HOST: str = "localhost"
    MONGODB_PORT: int = 27017
    MONGODB_USER: str = ""
    MONGODB_PASSWORD: str = ""
    MONGODB_DB: str = "cryptoagents"

    @computed_field
    @property
    def MONGO_URI(self) -> str:
        if self.MONGODB_USER and self.MONGODB_PASSWORD:
            return f"mongodb://{self.MONGODB_USER}:{self.MONGODB_PASSWORD}@{self.MONGODB_HOST}:{self.MONGODB_PORT}"
        return f"mongodb://{self.MONGODB_HOST}:{self.MONGODB_PORT}"

    # --- Redis ---
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""

    @computed_field
    @property
    def REDIS_URL(self) -> str:
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # --- SQLite (fallback) ---
    SQLITE_PATH: str = "data/cryptoagents.db"

    # --- Strategies ---
    STRATEGY_MODE: str = "auto"
    STRATEGY_SWITCH_CONFIRMATION: bool = True
    STRATEGY_CONFIRM_TIMEOUT: int = 300

    # --- Risk ---
    RISK_INITIAL_CAPITAL: float = 10000.0
    RISK_MAX_LEVERAGE: int = 10
    RISK_MAX_LOSS_PER_TRADE_PCT: float = 5.0  # 单笔最大亏损，配合10x杠杆=300U保证金
    RISK_MAX_DAILY_LOSS_PCT: float = 15.0
    RISK_POSITION_MARGIN_PCT: float = 2.0  # 单笔仓位保证金占总权益比例(%)  ~300U仓位
    RISK_MIN_STOP_DISTANCE_PCT: float = 0.3
    RISK_DAILY_RESET_TIME: str = "00:00"

    # --- Tasks ---
    TASK_5MIN_ENABLED: bool = True
    TASK_15MIN_ENABLED: bool = True
    TASK_1HOUR_ENABLED: bool = True
    TASK_DAILY_ENABLED: bool = True

    # --- Symbols ---
    SYMBOLS_WATCHLIST: list[str] = Field(default_factory=lambda: ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XAU/USDT"])
    SYMBOLS_TIMEFRAMES: list[str] = Field(default_factory=lambda: ["15m", "1h", "1d"])
    SYMBOLS_KLINE_LIMIT: int = 10000

    # --- Backtest ---
    BACKTEST_DEFAULT_SPEED: int = 1
    BACKTEST_SPEED_OPTIONS: list[int] = Field(default_factory=lambda: [1, 2, 5, 10, 20, 100])

    # --- Autopilot ---
    AUTOPILOT_INTERVAL: int = 15  # 自动驾驶循环间隔 (秒)
    AUTOPILOT_AI_TIMEOUT: float = 10.0  # AI 感知超时 (秒)
    AUTOPILOT_MAX_CONSECUTIVE_LOSSES: int = 5  # 连续亏损熔断阈值
    AUTOPILOT_MAX_DRAWDOWN_PCT: float = 8.0  # 权益回撤熔断阈值 (%)
    AUTOPILOT_COOLDOWN_AFTER_CLOSE: int = 2  # 平仓后冷却周期数

    # --- Logging ---
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "logs"

    # --- App ---
    DEBUG: bool = False
    SECRET_KEY: str = "change-me-in-production-open-source"
    HOST: str = "0.0.0.0"
    PORT: int = 8000


settings = Settings()
