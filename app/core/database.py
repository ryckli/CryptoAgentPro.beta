from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger("database")

_mongo_client = None
_mongo_db = None
_sqlite_engine = None
_sqlite_session = None


def init_sqlite():
    global _sqlite_engine, _sqlite_session
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    path = settings.SQLITE_PATH
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    _sqlite_engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False}, echo=False)
    from app.models.strategy import Base
    Base.metadata.create_all(bind=_sqlite_engine)
    _sqlite_session = sessionmaker(autocommit=False, autoflush=False, bind=_sqlite_engine)
    logger.info("SQLite initialized")


async def init_mongodb():
    global _mongo_client, _mongo_db
    try:
        import motor.motor_asyncio as motor
        _mongo_client = motor.AsyncIOMotorClient(settings.MONGO_URI, serverSelectionTimeoutMS=5000)
        await _mongo_client.admin.command("ping")
        _mongo_db = _mongo_client[settings.MONGODB_DB]
        logger.info("MongoDB connected")
    except Exception:
        logger.warning("MongoDB unavailable, using SQLite")
        _mongo_client = None
        _mongo_db = None


async def init_db():
    init_sqlite()
    await init_mongodb()


async def close_db():
    global _mongo_client
    if _mongo_client:
        _mongo_client.close()


def get_mongo_db():
    return _mongo_db


def get_sqlite_session():
    if _sqlite_session is None:
        init_sqlite()
    return _sqlite_session()


def get_mongo_collection(name: str):
    return _mongo_db[name] if _mongo_db is not None else None
