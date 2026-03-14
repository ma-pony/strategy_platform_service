# 实现计划

- [x] 1. 创建工程目录结构与基础静态文件
- [x] 1.1 创建顶级目录树和所有 Python 包的 `__init__.py`
  - 在项目根目录下创建 `src/`、`tests/`、`config/`、`scripts/` 顶级目录
  - 在 `src/` 下创建 `api/`、`core/`、`models/`、`services/`、`utils/` 子目录，每个目录含空 `__init__.py`
  - 在 `tests/` 下创建 `unit/`、`integration/` 子目录，所有测试目录均含 `__init__.py`
  - 在 `config/` 下创建 `__init__.py`，确保配置包可被导入
  - _Requirements: 1.1, 1.2, 1.3_

- [x] 1.2 创建根目录静态文件（README、.gitignore、.env.example）
  - 创建 `README.md`，包含项目名称 `strategy_platform_service`、简介占位文本和本地启动说明占位内容
  - 创建 `.gitignore`，排除 Python 字节码（`__pycache__/`、`*.py[cod]`、`*.pyo`）、虚拟环境（`.venv/`、`venv/`、`env/`）、环境变量文件（`.env`，保留 `.env.example`）、IDE 配置（`.idea/`、`.vscode/`、`*.swp`）、uv 产物（`.uv/`）、测试产物（`.coverage`、`htmlcov/`、`.pytest_cache/`）、mypy 缓存（`.mypy_cache/`）
  - 创建 `.env.example`，列出所有必要环境变量名（`APP_ENV`、`LOG_LEVEL`、`APP_NAME`）及说明注释，不含真实值
  - _Requirements: 1.4, 1.5, 3.1, 3.2_

- [x] 2. 配置依赖管理与 Makefile 快捷命令
- [x] 2.1 创建 `pyproject.toml` 并声明项目元数据与依赖
  - 添加 `[project]` 节：项目名 `strategy_platform_service`，版本 `0.1.0`，Python 版本约束 `>=3.11`
  - 在 `[project.dependencies]` 下声明运行时依赖：`pydantic-settings>=2.0`、`structlog>=24.0`
  - 在 `[dependency-groups]` 下的 `dev` 组声明开发依赖：`pytest>=8.0`、`pytest-cov>=5.0`、`mypy>=1.0`、`ruff>=0.8`、`pre-commit>=3.0`
  - 运行 `uv sync` 生成 `uv.lock` 文件并验证所有依赖安装成功、无版本冲突
  - _Requirements: 2.1, 2.2, 2.3_

- [x] 2.2 创建 Makefile 快捷命令
  - 实现 `install` 目标：执行 `uv sync` 安装所有依赖（含 dev）
  - 实现 `run` 目标：执行 `uv run python -m src.main` 启动服务
  - 实现 `test` 目标：执行 `uv run pytest` 运行测试并输出覆盖率
  - 实现 `lint` 目标：执行 `uv run ruff check src/ tests/`
  - 实现 `format` 目标：执行 `uv run ruff format src/ tests/`
  - 实现 `typecheck` 目标：执行 `uv run mypy src/`
  - 实现 `check` 目标：依次调用 `lint` 和 `typecheck`
  - 实现 `pre-commit-install` 目标：执行 `uv run pre-commit install`
  - _Requirements: 2.4, 5.3_

- [x] 3. (P) 实现多环境配置加载模块
- [x] 3.1 (P) 实现配置类层次和工厂函数
  - 在 `config/` 下创建配置模块，基于 `pydantic-settings v2` 的 `BaseSettings` 定义 `BaseAppSettings`，包含 `app_env`、`log_level`（默认 `INFO`）、`app_name` 字段
  - 定义三个环境子类：`DevSettings`（`debug=True`）、`TestSettings`（`debug=True`）、`ProdSettings`（`debug=False`）
  - 实现 `settings_factory()` 工厂函数：读取 `APP_ENV` 环境变量（默认 `development`）并分派到对应配置类，使用 `@lru_cache` 保证进程内单例
  - 配置 `SettingsConfigDict`：从 `.env` 文件读取，`extra="ignore"`，UTF-8 编码
  - _Requirements: 3.3, 3.5_

- [x] 3.2 (P) 实现配置校验与快速失败行为
  - 确保必填字段（无默认值的字段）在实例化时由 Pydantic 自动抛出 `ValidationError`，错误消息列明所有缺失/非法字段名
  - 验证非法 `APP_ENV` 值触发 `ValidationError`
  - 在 `config/__init__.py` 中导出 `settings_factory` 和 `Settings` 类型，供其他模块直接导入
  - _Requirements: 3.4_

- [x] 4. (P) 实现结构化日志模块
- [x] 4.1 (P) 构建 structlog 处理器链并实现初始化函数
  - 在 `src/utils/` 下创建日志模块，实现 `configure_logging(level, is_production)` 函数
  - 处理器链包含：ISO 格式时间戳（`TimeStamper`）、日志级别（`add_log_level`）、来源模块名（`CallsiteParameterAdder`）
  - `is_production=True` 时使用 `JSONRenderer()` 输出 JSON；`is_production=False` 时使用 `ConsoleRenderer()` 输出彩色可读格式
  - 通过 `sys.stderr.isatty()` 辅助判断是否为交互式终端，自动切换渲染器
  - `configure_logging()` 为幂等操作，多次调用不产生副作用
  - _Requirements: 4.1, 4.2, 4.3_

- [x] 4.2 (P) 实现日志级别默认值与 `get_logger` 工具函数
  - `configure_logging()` 的 `level` 参数默认值为 `"INFO"`，确保未传入时自动降级为 INFO 级别
  - 实现 `get_logger(name)` 函数，返回绑定模块名的 `structlog` logger 实例
  - 在 `src/utils/__init__.py` 中导出 `configure_logging` 和 `get_logger`
  - _Requirements: 4.4_

- [x] 5. (P) 配置代码质量工具链与 pre-commit 钩子
- [x] 5.1 (P) 在 `pyproject.toml` 中添加 ruff 和 mypy 配置节
  - 添加 `[tool.ruff]` 节：`target-version = "py311"`，`line-length = 88`
  - 添加 `[tool.ruff.lint]` 节：启用 `E`（pycodestyle errors）、`F`（pyflakes）、`I`（isort）规则集
  - 添加 `[tool.mypy]` 节：`python_version = "3.11"`，`strict = true`，`ignore_missing_imports = true`
  - 验证 `make lint`、`make format`、`make typecheck` 命令可扫描 `src/` 和 `tests/` 目录并报告问题
  - 注意：此任务修改 `pyproject.toml`，须在任务 2.1 完成后执行
  - _Requirements: 5.1, 5.2, 5.3_

- [x] 5.2 (P) 配置 pre-commit 钩子
  - 创建 `.pre-commit-config.yaml`，引用 `astral-sh/ruff-pre-commit` 仓库的两个 hook：`ruff`（含 `--fix` 参数）和 `ruff-format`
  - hook 中 ruff 版本须与 `pyproject.toml` 中 `ruff` 开发依赖版本保持一致
  - 验证 `make pre-commit-install` 可将钩子注册到 `.git/hooks/pre-commit`
  - _Requirements: 5.4_

- [x] 6. 搭建测试框架结构与示例测试
- [x] 6.1 在 `pyproject.toml` 中配置 pytest 和覆盖率选项
  - 添加 `[tool.pytest.ini_options]` 节：`testpaths = ["tests"]`，`addopts = "--cov=src --cov-report=term-missing --cov-fail-under=0"`，`python_files = "test_*.py"`，`python_functions = "test_*"`
  - 验证 `make test` 执行后输出包含通过数量、失败数量和代码覆盖率的测试摘要
  - 注意：此任务修改 `pyproject.toml`，须在任务 2.1 完成后执行
  - _Requirements: 6.2, 6.4, 6.5_

- [x] 6.2 创建 conftest 和示例测试文件
  - 在 `tests/` 下创建 `conftest.py`，提供 `clear_settings_cache` fixture，在测试前后调用 `settings_factory.cache_clear()` 确保测试间隔离
  - 在 `tests/unit/` 下创建 `test_config.py` 示例测试文件，包含：`APP_ENV=development` 时实例化 `DevSettings` 并验证默认值、`APP_ENV=production` 时验证 `debug=False`、缺少必填字段时 `settings_factory()` 抛出 `ValidationError`、两次调用 `settings_factory()` 返回同一实例
  - 在 `tests/integration/` 下创建 `test_health.py` 集成测试占位文件，包含一个始终通过的占位测试
  - 验证 `make test` 可发现并运行所有测试文件，测试失败时以非零退出码退出
  - 依赖：任务 3（ConfigModule）须先完成，才能在 conftest 中调用 `settings_factory.cache_clear()`
  - _Requirements: 6.1, 6.3, 6.5_

- [x] 7. 实现应用程序主入口与信号处理
- [x] 7.1 创建 `src/main.py` 入口文件与 `ApplicationRunner` 骨架
  - 在 `src/main.py` 中创建 `ApplicationRunner` 类，包含 `_shutdown_event` 标志、`_handle_signal`、`start`、`shutdown` 方法
  - 实现 `main()` 模块入口函数和 `if __name__ == "__main__": main()` 保护块
  - 确保可通过 `python -m src.main` 命令执行
  - 依赖：任务 3（ConfigModule）和任务 4（LoggingModule）须先完成
  - _Requirements: 7.1_

- [x] 7.2 实现启动序列：配置加载 → 日志初始化 → 服务主循环
  - 在 `ApplicationRunner.start()` 中严格按顺序执行：调用 `settings_factory()` 加载配置（校验失败立即捕获并以 exit(1) 退出）；调用 `configure_logging(level, is_production)` 初始化日志；注册 `SIGTERM` 和 `SIGINT` 信号处理器；启动服务主循环（当前为占位实现，记录一条 INFO 日志后返回）
  - 验证 `make run` 命令可完成完整启动序列并输出启动日志
  - _Requirements: 7.2_

- [x] 7.3 实现未捕获异常处理与优雅退出机制
  - 在 `start()` 中使用 `try/except` 捕获所有未处理异常，记录 `CRITICAL` 级别日志后调用 `sys.exit(1)`
  - 在 `_handle_signal()` 中设置 `_shutdown_event = True`，触发 `shutdown()` 执行清理逻辑后以 `sys.exit(0)` 退出
  - 验证：有效配置下 `ApplicationRunner.start()` 完成初始化序列不抛出异常；缺少必填配置时 `start()` 以非零退出码退出；发送 `SIGINT` 后 `_handle_signal` 被触发并设置关闭标志
  - _Requirements: 7.3, 7.4_

- [x]* 7.4 补充日志模块单元测试
  - 验证 `configure_logging()` 调用不抛出异常（对应设计测试策略第 5 条）
  - 验证 `configure_logging()` 幂等性：多次调用结果一致
  - 依赖：任务 4（LoggingModule）须先完成
  - _Requirements: 4.1, 4.2, 4.3, 4.4_
