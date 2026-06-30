# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: CryptoAgents Pro 打包为单文件 exe。"""

import os
from pathlib import Path

# SPECPATH 是 PyInstaller 在 spec 上下文中注入的变量
_base = Path(SPECPATH)

a = Analysis(
    ['run.py'],
    pathex=[str(_base)],
    binaries=[],
    datas=[
        # 前端静态文件
        (str(_base / "frontend" / "dist"), "frontend"),
        (str(_base / "frontend" / "dist" / "index.html"), "."),
        # 配置文件
        (str(_base / ".env.example"), "."),
        (str(_base / "config" / "crypto_config.yaml"), "config"),
    ],
    hiddenimports=[
        # FastAPI + uvicorn
        'uvicorn.loops', 'uvicorn.loops.auto',
        'uvicorn.protocols', 'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.wsproto_impl',
        'uvicorn.logging',
        'uvicorn.lifespan.on',
        # starlette
        'starlette.responses',
        # pydantic
        'pydantic', 'pydantic_settings', 'pydantic_core',
        # DB
        'sqlalchemy', 'sqlalchemy.ext.declarative',
        # exchange modules
        'cryptoagents.exchange', 'cryptoagents.exchange.base',
        'cryptoagents.exchange.okx', 'cryptoagents.exchange.binance',
        'cryptoagents.exchange.factory',
        # pandas / numpy
        'pandas', 'numpy',
        # APScheduler
        'apscheduler', 'apscheduler.schedulers',
        'apscheduler.schedulers.background',
        'apscheduler.triggers', 'apscheduler.triggers.interval',
        # httpx
        'httpx',
        # app modules
        'app', 'app.main', 'app.core', 'app.core.config',
        'app.core.database', 'app.core.logging_config',
        'app.core.settings_store',
        'app.middleware', 'app.middleware.operation_log',
        'app.models', 'app.models.strategy', 'app.models.analysis',
        'app.routers', 'app.routers.kline', 'app.routers.strategy',
        'app.routers.backtest', 'app.routers.trend', 'app.routers.trade',
        'app.routers.risk', 'app.routers.scheduler', 'app.routers.config',
        'app.routers.ai', 'app.routers.settings',
        'app.worker', 'app.worker.scheduler_worker',
        # cryptoagents modules
        'cryptoagents', 'cryptoagents.data', 'cryptoagents.data.ccxt_fetcher',
        'cryptoagents.data.kline_converter', 'cryptoagents.data.indicator_calc',
        'cryptoagents.strategy', 'cryptoagents.strategy.base',
        'cryptoagents.strategy.strategies', 'cryptoagents.strategy.scheduler',
        'cryptoagents.backtest', 'cryptoagents.backtest.engine',
        'cryptoagents.ai', 'cryptoagents.ai.trend_analyzer',
        'cryptoagents.ai.ai_service', 'cryptoagents.ai.chat_service',
        'cryptoagents.ai.news_service',
        'cryptoagents.risk', 'cryptoagents.risk.gateway',
        'cryptoagents.execution', 'cryptoagents.execution.executor',
        'cryptoagents.execution.paper_account', 'cryptoagents.execution.portfolio',
        'cryptoagents.ai.adaptive_optimizer',
        'cryptoagents.backtest.monte_carlo',
        'cryptoagents.autopilot', 'cryptoagents.autopilot.context_manager',
        'cryptoagents.autopilot.safety_valve',
        'cryptoagents.graph', 'cryptoagents.graph.trading_graph',
        'app.routers.autopilot',
        'app.worker.adaptive_worker',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'unittest', 'test', 'tests',
        'matplotlib', 'PIL', 'scipy', 'IPython',
        'jupyter', 'notebook', 'nbformat',
        'pytest', 'coverage', 'mypy',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='CryptoAgentsPro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
