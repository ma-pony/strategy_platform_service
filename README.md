# Strategy Platform Service

面向数字货币量化交易入门用户的策略科普展示平台后端服务。

集成 freqtrade 量化引擎，提供 10 大经典交易策略的回测、信号生成、绩效分析和研报展示。支持基于会员等级的字段级访问控制，免费用户可浏览基础指标，VIP 用户解锁完整数据。

## 技术栈

| 组件 | 技术选型 |
|------|---------|
| Web 框架 | FastAPI + Uvicorn |
| ORM | SQLAlchemy 2.0 (asyncpg + psycopg2) |
| 数据库 | PostgreSQL 16 |
| 缓存/消息队列 | Redis 7 |
| 异步任务 | Celery + Celery Beat |
| 量化引擎 | freqtrade |
| 管理后台 | sqladmin |
| 认证 | JWT (python-jose) + bcrypt |
| 日志 | structlog |
| 迁移 | Alembic |
| 包管理 | uv |

## 项目结构

```
src/
├── api/                    # FastAPI 路由层
│   ├── app.py              # 应用工厂（含 lifespan）
│   ├── auth.py             # 认证端点（注册/登录/刷新）
│   ├── strategies.py       # 策略查询
│   ├── backtests.py        # 回测结果查询
│   ├── signals.py          # 交易信号查询
│   ├── pair_metrics.py     # 策略对绩效指标
│   ├── reports.py          # AI 研报
│   ├── admin_backtests.py  # 管理员回测任务
│   └── health.py           # 健康检查
├── admin/                  # sqladmin 后台视图
├── core/                   # 配置、枚举、异常、安全、依赖注入
├── models/                 # SQLAlchemy ORM 模型
├── schemas/                # Pydantic 请求/响应 Schema
├── services/               # 业务逻辑层
├── workers/                # Celery 异步任务
│   └── tasks/
│       ├── backtest_tasks.py   # 回测任务（每日定时）
│       └── signal_tasks.py     # 信号生成任务（每15分钟）
├── freqtrade_bridge/       # freqtrade 集成层
│   ├── strategies/         # 10 个交易策略实现
│   ├── seeds/              # 数据种子脚本
│   ├── backtester.py       # 回测子进程执行器
│   ├── signal_fetcher.py   # 信号提取器
│   └── strategy_registry.py
└── utils/                  # 工具函数
```

## 快速开始

### 前置条件

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) 0.5+
- PostgreSQL 16+
- Redis 7+
- freqtrade (用于回测和信号生成)

### 安装

```bash
# 克隆项目
git clone git@github.com:ma-pony/strategy_platform_service.git
cd strategy_platform_service

# 安装依赖
make install

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入实际配置值
```

### 环境变量

| 变量 | 必填 | 默认值 | 说明 |
|------|:----:|-------|------|
| `DATABASE_URL` | 是 | - | 异步 PostgreSQL 连接串 (`postgresql+asyncpg://...`) |
| `DATABASE_SYNC_URL` | 是 | - | 同步 PostgreSQL 连接串 (`postgresql+psycopg2://...`) |
| `REDIS_URL` | 是 | - | Redis 连接串 (`redis://...`) |
| `SECRET_KEY` | 是 | - | JWT 签名密钥 |
| `APP_ENV` | 否 | `development` | 运行环境 |
| `LOG_LEVEL` | 否 | `INFO` | 日志级别 |
| `ADMIN_USERNAME` | 否 | `admin` | 管理后台用户名 |
| `ADMIN_PASSWORD` | 否 | `admin` | 管理后台密码 |
| `SIGNAL_REFRESH_INTERVAL` | 否 | `5` | 信号刷新间隔（分钟） |
| `FREQTRADE_DATADIR` | 否 | `/tmp/freqtrade_data` | OHLCV 数据目录 |

### 数据库初始化

```bash
# 运行迁移
make migrate

# 下载真实 OHLCV 数据（种子脚本依赖）
freqtrade download-data \
  --exchange binance \
  --pairs BTC/USDT ETH/USDT BNB/USDT SOL/USDT XRP/USDT \
  --timeframes 4h \
  --datadir /tmp/freqtrade_data \
  --timerange 20200101- \
  --data-format-ohlcv feather \
  --userdir /tmp/freqtrade_userdir

# 一键初始化全量种子数据（策略 + 信号 + 回测结果 + 绩效指标）
make seed-all
```

`seed-all` 会执行以下操作：
1. 幂等写入 10 个策略
2. 在真实 OHLCV 数据上运行 10 策略 × 5 交易对，提取约 68,000 条交易信号
3. 从信号配对交易中计算绩效指标（收益率、盈亏比、最大回撤、夏普比率）
4. 写入 `backtest_tasks`、`backtest_results`、`strategy_pair_metrics` 表
5. 更新策略表汇总指标

### 启动服务

```bash
# 启动 API 服务（开发模式，热重载）
make run

# 服务地址
# API:      http://localhost:8000
# API 文档: http://localhost:8000/docs
# 管理后台: http://localhost:8000/admin
```

### 启动 Celery Worker（可选，用于定时任务）

```bash
# 回测 Worker（串行执行）
uv run celery -A src.workers.celery_app worker -Q backtest -c 1

# 信号 Worker
uv run celery -A src.workers.celery_app worker -Q signal -c 4

# 定时调度
uv run celery -A src.workers.celery_app beat
```

## Docker 部署

```bash
# 构建并启动所有服务
make docker-build
make docker-up

# 查看日志
make docker-logs

# 停止服务
make docker-down
```

Docker Compose 包含 5 个服务：

| 服务 | 端口 | 说明 |
|------|------|------|
| `postgres` | 5432 | PostgreSQL 数据库 |
| `redis` | 6379 | Redis 缓存/消息队列 |
| `web` | 8000 | FastAPI 应用（启动时自动运行迁移） |
| `celery-worker` | - | 处理回测和信号队列 |
| `celery-beat` | - | 定时任务调度器 |

## API 端点

### 认证

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | `/api/v1/auth/register` | 用户注册（初始等级 FREE） | 无 |
| POST | `/api/v1/auth/login` | 登录，返回 access_token + refresh_token | 无 |
| POST | `/api/v1/auth/refresh` | 刷新 access_token | refresh_token |

### 策略

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| GET | `/api/v1/strategies` | 策略分页列表 | 可选 |
| GET | `/api/v1/strategies/{id}` | 策略详情 | 可选 |

### 回测

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| GET | `/api/v1/strategies/{id}/backtests` | 策略回测结果列表 | 可选 |
| GET | `/api/v1/backtests/{id}` | 回测详情 | 可选 |

### 交易信号

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| GET | `/api/v1/strategies/{id}/signals` | 最新交易信号 | 可选 |

### 策略对绩效指标

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| GET | `/api/v1/strategies/{id}/pair-metrics` | 绩效分页列表，支持 `?pair` `?timeframe` 过滤 | 可选 |
| GET | `/api/v1/strategies/{id}/pair-metrics/{pair}/{timeframe}` | 单条绩效详情 | 可选 |

### 研报

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| GET | `/api/v1/reports` | 研报分页列表 | 无 |
| GET | `/api/v1/reports/{id}` | 研报详情 | 无 |

### 管理员

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | `/api/v1/admin/backtests` | 提交回测任务 | 管理员 |
| GET | `/api/v1/admin/backtests` | 回测任务列表 | 管理员 |
| GET | `/api/v1/admin/backtests/{task_id}` | 任务详情 | 管理员 |

## 会员等级与字段权限

系统采用字段级访问控制，不同会员等级可见的数据字段不同：

| 数据类型 | 匿名用户 | FREE | VIP1+ |
|---------|---------|------|-------|
| **策略** | 名称、描述、交易对 | + 策略类型 | + 全部指标 |
| **回测** | ID、时间范围 | + 收益率、交易数、回撤 | + 夏普、胜率、年化 |
| **信号** | 方向、价格 | 同匿名 | + 置信度 |
| **绩效** | 交易对、收益率、交易数 | + 盈亏比、数据来源 | + 回撤、夏普、更新时间 |

## 内置交易策略

| 策略 | 类型 | 说明 |
|------|------|------|
| TurtleTradingStrategy | 趋势跟随 | 海龟交易 — Donchian 通道快慢双突破 |
| BollingerBandMeanReversionStrategy | 均值回归 | 布林带上下轨触碰的均值回归 |
| RsiMeanReversionStrategy | 均值回归 | RSI 超买超卖区域反转 |
| MacdTrendFollowingStrategy | 趋势跟随 | MACD 金叉死叉趋势跟随 |
| IchimokuCloudTrendStrategy | 趋势跟随 | 一目均衡表云层突破 |
| ParabolicSarTrendStrategy | 趋势跟随 | 抛物线 SAR 翻转信号 |
| KeltnerChannelBreakoutStrategy | 突破 | EMA+ATR 通道突破动量交易 |
| AroonTrendSystemStrategy | 趋势跟随 | Aroon 指标交叉趋势判断 |
| Nr7VolatilityContractionBreakoutStrategy | 突破 | NR7 窄幅 K 线识别突破 |
| StochasticOscillatorReversalStrategy | 均值回归 | Stochastic K/D 交叉反转 |

每个策略支持 5 个交易对：BTC/USDT、ETH/USDT、BNB/USDT、SOL/USDT、XRP/USDT。

## 后台任务

| 任务 | 队列 | 调度 | 说明 |
|------|------|------|------|
| `run_backtest_task` | backtest | 每日 02:00 UTC | 对所有活跃策略执行 freqtrade 回测，结果写入 DB |
| `generate_signals_task` | signal | 每 15 分钟 | 生成最新交易信号，写入 Redis + DB |

回测任务特性：
- `acks_late=True`：Worker 崩溃时任务重新入队
- 串行执行（concurrency=1）
- 回测结果与绩效指标在同一事务内写入（原子性）
- 隔离临时目录，finally 清理

信号任务特性：
- 信号缓存至 Redis（TTL 1h）
- 持久化至 PostgreSQL 历史表
- 实盘指标非阻塞更新（失败不影响主流程）

## 开发

### 常用命令

```bash
make install          # 安装依赖
make run              # 启动开发服务器
make test             # 运行测试
make test-all         # 运行全部测试（含集成测试）+ HTML 覆盖率报告
make lint             # 代码检查
make format           # 代码格式化
make typecheck        # 类型检查
make check            # lint + typecheck + test
make migrate          # 数据库迁移
make seed             # 仅初始化策略种子
make seed-all         # 初始化全量种子数据
```

### 测试

```bash
# 运行单元测试
uv run pytest tests/unit/

# 运行集成测试（需要真实数据库）
TEST_DATABASE_URL=postgresql+asyncpg://... uv run pytest tests/integration/

# 带覆盖率
uv run pytest --cov=src --cov-report=html
```

### CI/CD

GitHub Actions 自动触发（push/PR 到 main）：

1. **lint** — ruff check + format check
2. **test** — PostgreSQL + Redis 服务容器，运行迁移和全量测试
3. **docker-build** — 验证 Docker 镜像构建

## 数据模型

```
strategies (1) ──┬── (N) backtest_tasks ── (1) backtest_results
                 ├── (N) trading_signals
                 └── (N) strategy_pair_metrics

users (独立)
research_reports ── (N) report_coins
```

核心表：

| 表 | 说明 |
|---|------|
| `users` | 用户（email 登录、会员等级） |
| `strategies` | 量化策略配置 + 汇总指标 |
| `backtest_tasks` | 回测任务生命周期（PENDING → RUNNING → DONE/FAILED） |
| `backtest_results` | 回测结果指标（收益率、夏普、回撤等） |
| `trading_signals` | 交易信号历史（方向、价格、置信度、指标快照） |
| `strategy_pair_metrics` | 策略×交易对×周期 绩效指标（支持 upsert） |
| `research_reports` | AI 研报 |

## License

Private
