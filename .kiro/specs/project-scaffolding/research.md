# 研究与设计决策

---
**用途**：记录发现阶段的调研活动、架构评估及设计决策依据，为 `design.md` 提供支撑。

---

## 摘要
- **功能名称**：`project-scaffolding`
- **发现范围**：新功能（绿地项目，全量发现）
- **关键发现**：
  - 现代 Python 项目（2025）推荐使用 `uv` 作为包管理器，配合 `pyproject.toml` 单一配置文件统一管理依赖、工具链和构建元数据，不再需要单独的 `requirements.txt`。
  - 配置管理的行业标准为 `pydantic-settings v2`，支持类型安全的环境变量读取、多环境切换（通过 `APP_ENV`），并在启动时对缺失必填配置项快速失败。
  - 结构化日志推荐 `structlog`（JSON 输出 + 处理器链）或 `loguru`（`serialize=True`），两者均支持时间戳、日志级别、来源模块的自动附加；`structlog` 在分布式系统中具有更强的上下文绑定能力。
  - 代码质量工具链以 `ruff`（替代 `black` + `isort` + `flake8`）+ `mypy` + `pre-commit` 为最佳实践组合，所有配置均集中在 `pyproject.toml`。

---

## 研究日志

### 主题一：包管理与项目配置

- **背景**：需要选择依赖管理工具并确定配置文件组织方式。
- **参考来源**：
  - [uv 完整指南 - Python Developer Tooling Handbook](https://pydevtools.com/handbook/explanation/uv-complete-guide/)
  - [现代 Python 代码质量配置：uv、ruff 与 mypy - Medium](https://simone-carolini.medium.com/modern-python-code-quality-setup-uv-ruff-and-mypy-8038c6549dcc)
- **发现**：
  - `uv` 由 Astral 出品（同 ruff 作者），提供 Python 版本管理、虚拟环境、依赖解析、lockfile 生成等一体化能力。
  - `uv init` + `uv add` 自动生成 `pyproject.toml` 和 `uv.lock`，消除 `requirements.txt` 维护负担。
  - 生成的 `uv.lock` 文件精确锁定所有传递依赖版本，保证环境一致性。
  - 开发依赖通过 `uv add --dev` 声明在 `[dependency-groups]` 下，运行时依赖在 `[project.dependencies]` 下。
- **影响**：采用 `uv` + `pyproject.toml` 作为唯一包管理方案；`Makefile` 中所有命令均通过 `uv run` 调用。

### 主题二：配置与环境变量管理

- **背景**：需要支持多环境切换、启动时校验必填配置项，且配置需类型安全。
- **参考来源**：
  - [pydantic-settings 官方文档](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
  - [pydantic-settings 2.0 完整指南 - Medium](https://medium.com/@yuxuzi/all-you-need-to-know-about-python-configuration-with-pydantic-settings-2-0-2025-guide-4c55d2346b31)
- **发现**：
  - `pydantic-settings v2` 通过 `BaseSettings` 子类声明配置模型，字段类型由 Pydantic 自动验证。
  - 支持从 `.env` 文件（`model_config = SettingsConfigDict(env_file=".env")`）或环境变量读取，大小写不敏感。
  - 通过继承 `BaseSettings` 并结合 `APP_ENV` 环境变量实例化对应子类（`DevSettings`、`TestSettings`、`ProdSettings`），实现多环境切换。
  - 缺少必填字段时 Pydantic 的 `ValidationError` 会在初始化时立即抛出，满足快速失败要求。
  - 使用 `@lru_cache` 包装工厂函数，避免重复读取。
- **影响**：`config/` 模块基于 `pydantic-settings v2` 设计；`settings_factory()` 函数作为统一入口，返回对应环境的 `Settings` 实例。

### 主题三：结构化日志

- **背景**：需要 JSON 结构化日志，自动附加时间戳、日志级别和来源模块。
- **参考来源**：
  - [structlog 最佳实践文档](https://www.structlog.org/en/stable/logging-best-practices.html)
  - [structlog 指南 - Better Stack](https://betterstack.com/community/guides/logging/structlog/)
  - [loguru 生产级指南 - Dash0](https://www.dash0.com/guides/python-logging-with-loguru)
- **发现**：
  - `structlog` 的处理器链（ProcessorChain）天然支持添加时间戳（`TimeStamper`）、日志级别（`add_log_level`）、调用模块（`CallsiteParameterAdder`）等元数据。
  - 生产环境使用 `JSONRenderer()` 输出 JSON；开发环境使用 `ConsoleRenderer()` 输出彩色可读格式，通过 `sys.stderr.isatty()` 自动切换。
  - `loguru` 使用 `serialize=True` 同样可输出 JSON，API 更简洁，但处理器可定制性低于 `structlog`。
  - 对于分布式追踪（如后续添加 trace_id），`structlog` 的 `contextvars` 集成更成熟。
- **影响**：选用 `structlog` 作为日志库；日志初始化在 `src/utils/logging.py` 模块中完成，由 `main.py` 在启动时调用。

### 主题四：代码质量工具链

- **背景**：需要格式化、Lint、类型检查和 pre-commit 钩子的完整配置。
- **参考来源**：
  - [ruff PyPI 页面](https://pypi.org/project/ruff/)
  - [ruff-pre-commit GitHub](https://github.com/astral-sh/ruff-pre-commit)
  - [使用 uv 与 pre-commit - uv 官方文档](https://docs.astral.sh/uv/guides/integration/pre-commit/)
- **发现**：
  - `ruff` 用 Rust 编写，速度极快，单一工具替代 `black`（格式化）、`isort`（import 排序）和 `flake8`（Lint）。
  - 所有 ruff 规则通过 `[tool.ruff]` 和 `[tool.ruff.lint]` 在 `pyproject.toml` 中配置。
  - `mypy` 的严格模式（`strict = true`）配置在 `[tool.mypy]` 节；建议目标版本锁定为项目 Python 版本。
  - pre-commit 使用 `ruff-check`（lint + 自动修复）和 `ruff-format`（格式化）两个钩子，从官方 `astral-sh/ruff-pre-commit` repo 引入。
  - `uv run pre-commit install` 将钩子注册到 `.git/hooks/pre-commit`。
- **影响**：`pyproject.toml` 包含 `[tool.ruff]`、`[tool.ruff.lint]`、`[tool.mypy]`、`[tool.pytest.ini_options]` 四个工具配置节；`.pre-commit-config.yaml` 仅需引用两个 ruff 钩子。

---

## 架构模式评估

| 选项 | 描述 | 优势 | 风险/限制 | 备注 |
|------|------|------|-----------|------|
| 分层架构（Layered） | `api/` → `services/` → `core/` → `models/` 垂直分层 | 结构直观，职责清晰，易于团队理解 | 层间耦合可能随时间增加 | 适合初期快速搭建，后续可演进为六边形 |
| 六边形架构（Hexagonal） | Ports & Adapters，核心域与外部依赖完全解耦 | 可测试性强，外部依赖可替换 | 初期抽象层较多，增加复杂度 | 适合已有明确外部集成需求时 |
| 扁平结构 | 所有模块平铺在 `src/` 下 | 简单 | 随项目增长难以维护 | 不适合团队协作项目 |

**选择**：分层架构。理由：项目处于初始脚手架阶段，分层结构足以支撑后续功能模块扩展，且对团队成员认知负担最小。后续如需引入外部服务集成，可在 `services/` 层添加 Adapter 模式局部演进。

---

## 设计决策

### 决策：使用 uv 代替 pip/poetry 作为包管理器

- **背景**：需要选择依赖管理工具，满足环境一致性和开发体验要求。
- **备选方案**：
  1. pip + requirements.txt — 传统方案，无 lockfile 机制
  2. poetry — 成熟方案，但速度较慢，lockfile 与 PEP 标准有差异
  3. uv — 现代方案，极速，完全符合 PEP 517/518/660 标准
- **选定方案**：uv
- **理由**：uv 是 2025 年 Python 社区最具动能的包管理工具，由 ruff 同一团队维护，工具链统一；lockfile 机制完整，安装速度比 pip 快 10-100x。
- **权衡**：uv 相对较新，部分 CI 环境可能需要额外安装步骤；但官方提供 GitHub Actions 集成指南，风险可控。
- **后续**：实现阶段验证 CI 环境（如 GitHub Actions）的 uv 安装配置。

### 决策：structlog 作为结构化日志库

- **背景**：需要 JSON 结构化日志，同时支持开发环境可读格式。
- **备选方案**：
  1. 标准库 `logging` + `python-json-logger` — 配置繁琐，处理器链扩展性有限
  2. loguru — API 简洁，但上下文绑定能力弱于 structlog
  3. structlog — 处理器链可组合，contextvars 支持好，社区活跃
- **选定方案**：structlog
- **理由**：structlog 的处理器链设计与需求中"自动附加时间戳、级别、模块名"完全契合；contextvars 支持为后续分布式追踪留有扩展空间。
- **权衡**：初始配置比 loguru 稍复杂，但通过统一初始化函数封装后对业务代码透明。

### 决策：pydantic-settings v2 作为配置管理方案

- **背景**：需要类型安全的配置读取，支持多环境和启动时校验。
- **备选方案**：
  1. python-dotenv + 手动读取 — 无类型安全，校验逻辑需自行编写
  2. dynaconf — 功能强大但引入额外概念，学习曲线陡
  3. pydantic-settings v2 — 与 Pydantic v2 生态无缝集成，类型安全，自动校验
- **选定方案**：pydantic-settings v2
- **理由**：Pydantic v2 是 Python 生态中类型验证的事实标准；pydantic-settings 与其深度集成，快速失败行为（ValidationError）和 SecretStr 类型均为生产级特性。

---

## 风险与缓解措施

- **uv 在 CI 中的可用性** — 缓解措施：在 `scripts/` 中提供 `install.sh` 脚本，包含 uv 的安装命令；Makefile 添加 `setup` 目标。
- **structlog 初始配置复杂** — 缓解措施：在 `src/utils/logging.py` 中封装 `configure_logging()` 函数，main.py 一行调用，业务模块无需感知配置细节。
- **pydantic-settings 多环境切换逻辑** — 缓解措施：`settings_factory()` 函数根据 `APP_ENV` 返回对应 Settings 子类实例，使用 `@lru_cache` 保证单例，避免重复实例化。
- **pre-commit 版本漂移** — 缓解措施：`.pre-commit-config.yaml` 中 ruff 版本与 `pyproject.toml` 中开发依赖版本保持一致，并在文档中说明同步方式。

---

## 参考资料

- [uv 官方文档](https://docs.astral.sh/uv/) — 包管理器完整指南
- [pydantic-settings 官方文档](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) — 配置管理
- [structlog 最佳实践](https://www.structlog.org/en/stable/logging-best-practices.html) — 结构化日志配置
- [ruff-pre-commit GitHub](https://github.com/astral-sh/ruff-pre-commit) — pre-commit 钩子配置
- [现代 Python 代码质量配置 - Medium](https://simone-carolini.medium.com/modern-python-code-quality-setup-uv-ruff-and-mypy-8038c6549dcc) — uv + ruff + mypy 配置示例
- [使用 uv 与 pre-commit](https://docs.astral.sh/uv/guides/integration/pre-commit/) — uv 与 pre-commit 集成指南
