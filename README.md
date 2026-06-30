# CryptoAgents Pro

基于 TradingAgents-CN 架构的虚拟货币智能交易系统。整合 6套交易策略+自定义策略、DeepSeek AI趋势感知（15分钟定时）、倍速回测引擎、模拟/测试网双模式交易和严格风控网关。

## 核心能力

| 能力 | 说明 |
|------|------|
| **真实回测** | CCXT 拉取生产历史数据（自动分页），逐根模拟，含手续费/滑点/杠杆/止损止盈，净持仓模型 |
| **双模式交易** | `paper` 本地模拟撮合（默认安全）/ `testnet` 交易所测试网（沙盒环境，无真实资金风险），前端一键切换 |
| **自动仓位计算** | 基于风控的仓位 sizing（单笔风险 = 本金 × 风险%），不再写死数量 |
| **风控前置** | 下单前强制经过风控网关（单笔/当日亏损/保证金检查） |
| **AI趋势感知** | DeepSeek 每15分钟自动分析监控币种，生成报告并持久化，建议策略切换 |
| **AI建议+人工确认** | 默认 AI 仅建议，前端确认后才切换/下单；可开启全自动 |
| **自定义策略** | 前端可视化创建参数化策略（EMA/RSI/MACD/BOLL），存入数据库 |
| **全前端可配** | API密钥、交易模式、风控参数、监控币种、AI模型/间隔均可在前端面板修改并持久化 |

> 模拟盘与回测使用生产公开行情，无需 API Key。仅 testnet 测试网下单需要密钥。
> 前端为单页多Tab：主面板 / AI报告 / 策略 / 回测 / 设置。

## 系统架构

```
cryptoagents/              ← 核心引擎（对标 tradingagents/）
├── data/                  CCXT数据引擎 + F/S/L/H转换 + 技术指标
├── strategy/              6套策略工厂 + 策略调度器
├── backtest/              倍速回测引擎 (1x~100x)
├── ai/                    DeepSeek V4 Pro 趋势感知
├── risk/                  风控网关 (单笔3%/当日15%)
├── execution/             CCXT交易所执行引擎
└── graph/                 LangGraph 多Agent工作流

app/                       ← FastAPI 后端（对标 TradingAgents-CN app/）
├── routers/               API路由 (kline/strategy/backtest/trend/trade/risk/scheduler)
├── models/                Pydantic + SQLAlchemy 数据模型
├── core/                  配置中心 + MongoDB/SQLite + Redis + 日志
├── middleware/             RequestID + 操作日志中间件
└── main.py                 Lifespan 生命周期入口

frontend/                  ← Vue 3 + TailwindCSS
config/                    ← 配置文件
docker/                    ← Docker部署
```

## 环境要求

| 依赖 | 版本 |
|------|------|
| Python | 3.11+ |
| Node.js | 18+ (前端) |
| MongoDB | 4.4+ (可选，有SQLite回退) |
| Redis | 7+ (可选) |

## 快速开始

### 1. 克隆并安装

```bash
cd CryptoAgents
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`：

```env
EXCHANGE_API_KEY=你的交易所API_KEY
EXCHANGE_SECRET=你的交易所SECRET
DEEPSEEK_API_KEY=你的DeepSeek_API_KEY

MONGODB_HOST=localhost
MONGODB_PORT=27017
REDIS_HOST=localhost
REDIS_PORT=6379

DEBUG=true
LOG_LEVEL=INFO
```

环境变量说明：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `EXCHANGE_NAME` | binance | 交易所 (binance/okx/bybit) |
| `EXCHANGE_TESTNET` | true | 是否使用测试网 |
| `AI_PROVIDER` | deepseek | AI提供商 |
| `AI_MODEL` | deepseek-v4-pro | 模型名称 |
| `RISK_INITIAL_CAPITAL` | 10000 | 初始本金 |
| `RISK_MAX_LEVERAGE` | 10 | 最大杠杆 |
| `RISK_MAX_LOSS_PER_TRADE_PCT` | 3 | 单笔最大亏损% |
| `RISK_MAX_DAILY_LOSS_PCT` | 15 | 当日最大亏损% |
| `STRATEGY_SWITCH_CONFIRMATION` | true | 策略切换需人工确认 |

### 3. 启动后端

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

API文档：http://localhost:8000/docs

### 4. 启动前端

```bash
cd frontend
npm install
npm run dev
```

访问：http://localhost:3000

### 5. 运行测试

```bash
pytest tests/ -v
```

## API 接口

所有接口前缀 `/api/v1`

### K线数据

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/kline/symbols` | 可用币种列表 |
| GET | `/kline/{symbol}/{timeframe}` | K线数据（含F/S/L/H格式） |

### 策略管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/strategy/list` | 6套策略列表 |
| GET | `/strategy/signal/{symbol}` | 指定策略的信号 |
| GET | `/strategy/active/{symbol}` | 当前活跃策略 |
| POST | `/strategy/activate` | 手动切换策略 |
| GET | `/strategy/indicators/{symbol}` | 技术指标 |

### 回测

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/backtest/run` | 提交回测（支持speed参数） |
| GET | `/backtest/{task_id}/progress` | 回测进度 |
| POST | `/backtest/{task_id}/cancel` | 取消回测 |
| POST | `/backtest/{task_id}/speed` | 动态调速 |
| GET | `/backtest/speeds` | 可用倍速列表 |

### 回测结果说明

| 字段 | 含义 |
|------|------|
| 总收益 | 回测期间总收益率（含手续费/杠杆） |
| 胜率 | 盈利交易占总交易的比例 |
| 交易数 | 总开仓次数 |
| 最大回撤 | 权益曲线的最大回撤幅度 |
| 盈亏比 | 总盈利 / 总亏损（>1表示盈利大于亏损） |

交易明细中的**平仓原因**：

| 原因 | 含义 |
|------|------|
| **TP** | Take Profit — 止盈触发，盈利达标自动平仓 |
| **SL** | Stop Loss — 止损触发，亏损触及止损线自动平仓 |
| **REVERSE** | 反向信号 — 策略发出相反方向信号，先平旧仓 |
| **EOF** | End of Data — 回测时间区间结束，强制平掉剩余持仓 |

### AI趋势

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/trend/{symbol}` | 当前趋势状态 |
| GET | `/trend/history` | 趋势分析历史 |
| POST | `/trend/confirm-switch` | 确认策略切换 |
| POST | `/trend/reject-switch` | 拒绝策略切换 |

### 交易执行

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/trade/order` | 下单 |
| POST | `/trade/emergency-close` | 紧急平仓 |
| GET | `/trade/history` | 交易历史 |

### 风控

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/risk/status` | 风控状态 |
| POST | `/risk/reset` | 重置当日风控 |

### WebSocket

| 路径 | 说明 |
|------|------|
| `ws://localhost:8000/ws/realtime/{symbol}` | 实时K线（F/S/L/H格式） |
| `ws://localhost:8000/ws/signals` | 策略信号推送 |
| `ws://localhost:8000/ws/trend` | AI趋势推送 |
| `ws://localhost:8000/api/v1/backtest/ws/{task_id}` | 回测进度实时推送 |

## 六套策略

| ID | 名称 | 最适市场 | 周期 | 逻辑 |
|----|------|---------|------|------|
| S1 | 双EMA趋势追随 | 强趋势 | 15m | EMA9/26金叉死叉 + MACD发散 |
| S2 | RSI均值回归 | 震荡 | 15m | RSI(7) <15做多 / >85做空 |
| S3 | MACD多维度共振 | 趋势转换 | 15m | MACD背离 + 成交量放大 |
| S4 | 马丁逆势反弹 | 急涨急跌 | 15m | RSI极端 + 不加止损加仓 |
| S5 | EMA刮头皮 | 温和趋势 | 15m | EMA21触碰回调 + 1%止盈 |
| S6 | TD9超买超卖 | 极端行情 | 15m | TD序列计数 ≥9 |

### 策略→市场状态映射

```
STRONG_BULL/STRONG_BEAR  →  S1 (双EMA趋势)
WEAK_BULL/WEAK_BEAR      →  S5 (EMA刮头皮)
RANGING                  →  S2 (RSI回归) / S6 (TD9)
CRASH_BOUNCE             →  S4 (马丁做多)
PUMP_REVERSAL            →  S4 (马丁做空)
TREND_CHANGE             →  S3 (MACD共振)
```

## 倍速回测

### 使用

POST `/backtest/run` 传入 `speed`：

```json
{
  "strategy_id": "S1",
  "symbol": "BTC/USDT",
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "initial_capital": 10000,
  "leverage": 10,
  "speed": 10
}
```

### 倍速档位

| 倍速 | 进度刷新 | 适用场景 |
|:--|:--|:--|
| 1x | 每根K线 | 调试/演示 |
| 2x | 每2根 | 快速浏览 |
| 5x | 每5根 | 日常回测 |
| 10x | 每10根 | 批量回测 |
| 20x | 每20根 | 多策略对比 |
| 100x ⚡ | 每100根 | 年度回测 |

**信号计算永远逐根执行**，倍速只控制进度刷新频率。回测运行中可通过 `POST /backtest/{task_id}/speed` 动态变速。

### 进度推送格式

```json
{
  "task_id": "bt_1710000000_a1b2c3",
  "status": "running",
  "progress_pct": 45.0,
  "current_step": 450,
  "total_steps": 1000,
  "speed": 10,
  "current_equity": 9876.50,
  "estimated_remaining_seconds": 3.2
}
```

## AI趋势感知

每15分钟自动触发 DeepSeek V4 Pro 分析：

1. CCXT拉取15m/1h周期K线
2. K线转为 F/S/L/H 紧凑格式
3. 计算 MACD/RSI/BOLL/KDJ 指标
4. DeepSeek 分析 → 输出市场状态(8种) + 置信度 + 推荐策略
5. 策略调度器检查是否需要切换
6. 如需切换 → 前端弹窗确认（或自动切换）

## 风控规则

| 规则 | 阈值 | 触发动作 |
|------|------|---------|
| 单笔最大亏损 | 本金 × 3% | 拒绝下单 |
| 当日累计亏损 | 本金 × 15% | 自动停盘 |
| 保证金率 | ≤ 可用80% | 拒绝下单 |

## K线格式

### F/S/L/H 自定义格式

```
实时: F1.0023,S0.9950,L0.9910,H1.0120
收阳: F1.0050,S0.9950,L0.9910,H1.0120 | U
收阴: F0.9980,S0.9950,L0.9850,H1.0080 | D
```

| 字段 | 含义 |
|------|------|
| F | 实时价格 (close) |
| S | 前一根K线收盘价 |
| L | 当前K线最低价 |
| H | 当前K线最高价 |
| U | 收阳标记 |
| D | 收阴标记 |

## Docker部署

```bash
docker-compose up -d
```

服务：

| 服务 | 端口 | 说明 |
|------|------|------|
| backend | 8000 | FastAPI |
| frontend | 3000:80 | Vue + Nginx |
| mongodb | 27017 | 数据库 |
| redis | 6379 | 缓存/队列 |

## 目录结构详解

```
CryptoAgents/
├── app/
│   ├── main.py                     # Lifespan入口，注册路由/中间件/WebSocket
│   ├── core/
│   │   ├── config.py               # Pydantic BaseSettings 配置中心
│   │   ├── database.py             # MongoDB + SQLite 双数据库管理
│   │   ├── redis_client.py         # Redis异步客户端
│   │   └── logging_config.py       # 统一日志配置
│   ├── middleware/
│   │   └── operation_log.py        # RequestID + 操作审计中间件
│   ├── routers/
│   │   ├── kline.py                # K线数据接口
│   │   ├── strategy.py             # 策略管理接口
│   │   ├── backtest.py             # 回测接口（含WebSocket）
│   │   ├── trend.py                # AI趋势接口
│   │   ├── trade.py                # 交易执行接口
│   │   ├── risk.py                 # 风控接口
│   │   └── scheduler.py            # 调度接口
│   ├── models/
│   │   ├── strategy.py             # SQLAlchemy 表模型
│   │   └── analysis.py             # Pydantic 请求/响应模型
│   └── services/
│       └── queue_service.py        # Redis任务队列
├── cryptoagents/
│   ├── data/
│   │   ├── ccxt_fetcher.py         # CCXT统一交易所接口
│   │   ├── kline_converter.py      # F/S/L/H格式转换
│   │   └── indicator_calc.py       # MACD/RSI/BOLL/KDJ计算
│   ├── strategy/
│   │   ├── base.py                 # 策略基类 + 市场状态映射
│   │   ├── strategies.py           # S1~S6 六套策略实现
│   │   └── scheduler.py            # 策略调度器
│   ├── backtest/
│   │   └── engine.py               # 倍速回测引擎
│   ├── ai/
│   │   └── trend_analyzer.py       # DeepSeek趋势分析
│   ├── risk/
│   │   └── gateway.py              # 风控网关
│   ├── execution/
│   │   └── executor.py             # CCXT下单/平仓
│   └── graph/
│       └── trading_graph.py        # LangGraph多Agent工作流
├── frontend/
│   └── src/
│       ├── views/
│       │   ├── DashboardView.vue   # 主面板（实时行情+信号+风控）
│       │   └── BacktestView.vue    # 回测页面（倍速选择器）
│       ├── components/
│       │   ├── SpeedSelector.vue   # 倍速选择器
│       │   ├── KlineViewer.vue     # K线展示
│       │   ├── TrendPanel.vue      # AI趋势面板
│       │   ├── RiskPanel.vue       # 风控面板
│       │   └── SchedulerPanel.vue  # 调度面板
│       └── stores/
│           └── dashboard.ts        # Pinia状态管理
├── config/
│   └── crypto_config.yaml          # 加密货币专用配置
├── docker/
│   ├── Dockerfile.backend
│   ├── Dockerfile.frontend
│   └── nginx.conf
├── tests/
│   └── test_engine.py              # 策略+回测+转换器测试 (15个)
├── requirements.txt
├── docker-compose.yml
├── .env.example
└── README.md
```

## 项目体系

| 参考项目 | 复用内容 |
|---------|---------|
| TradingAgents-CN | FastAPI lifespan / Pydantic Settings / MongoDB / APIRouter模式 / 中间件栈 / Docker |
| 原有K线读取模块 | CCXT拉取逻辑 / API Key管理 |
| LangGraph | 多Agent工作流骨架（可扩展） |
