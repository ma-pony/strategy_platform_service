# strategy_platform_service

策略平台服务 - 后端服务基础脚手架。

## 简介

本项目为 `strategy_platform_service` 的后端服务，提供标准化的工程目录结构、配置管理、日志系统和代码质量工具链。

## 本地启动说明

### 前置条件

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) 0.5+

### 安装依赖

```bash
make install
```

### 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入实际配置值
```

### 启动服务

```bash
make run
```

### 运行测试

```bash
make test
```

### 代码检查

```bash
make check
```
