# Knowledge Management Agent

[![CI](https://github.com/BeforeLanding/KnowledgeManagementAgent/actions/workflows/ci.yml/badge.svg)](https://github.com/BeforeLanding/KnowledgeManagementAgent/actions/workflows/ci.yml)

[English](README.md) | [简体中文](README.zh.md)

一个评测驱动的双语企业级 RAG Agent，支持知识空间 ACL、混合检索、可靠引用、Trace 回放和确定性回归检查。仓库仅包含公司无关的合成数据。

## 快速开始

```bash
copy .env.example .env
docker compose up --build
python scripts/load_demo.py
```

打开 `http://localhost:3000`，使用 `admin@example.com` / `Admin123!` 登录。其他预置演示账号为 `curator@example.com` / `Curator123!` 和 `viewer@example.com` / `Viewer123!`。

如需使用 OpenAI 兼容模型，请设置 `MODEL_PROVIDER=openai`、`OPENAI_BASE_URL`、`OPENAI_API_KEY` 和 `CHAT_MODEL`。Fake 模式具备确定性，且不需要付费 API。

## 本地开发

```bash
uv sync --dev
uv run alembic upgrade head
uv run --directory services/api python -m app.seed
uv run uvicorn app.main:app --reload --app-dir services/api
pnpm install
pnpm dev:web
```

使用 `uv run pytest`、`uv run ruff check .`、`uv run mypy services/api/app`、`pnpm test:web` 和 `pnpm build:web` 运行检查。使用以下命令运行无需模型的确定性 Gate：

```bash
uv run python scripts/evaluate.py --suite smoke
uv run python scripts/evaluate.py --suite regression
uv run python scripts/evaluate.py --suite threat
uv run python scripts/evaluate.py --suite regression --case prompt-injection
```

这些命令使用公司无关的合成夹具、内存数据库、生产环境所用的有界 Agent／检索／引用路径以及 Fake Provider，不会调用外部服务或付费模型。此前仅针对检索的基准测试仍可通过 `uv run python scripts/evaluate_retrieval.py` 使用。

Week 6 增加了确定性威胁测试、具有安全边界的负载工具、低基数指标、依赖就绪检查、安全运维脚本和发布加固。昂贵的负载测试默认不会运行：

```bash
# 仅生成计划
uv run python scripts/load_test.py --mode plan --documents 10000 --confirm-expensive
# 可测量的进程内微基准；其结果不代表生产容量
uv run python scripts/load_test.py --mode local --documents 1000 --requests 1000 --execute
# 除非显式提供执行和确认参数，否则运维操作均为 dry-run
uv run python scripts/backup.py --target data/backups/example
uv run python scripts/check_consistency.py
```

`/health/live` 用于进程存活检查，`/health/ready` 检查必要依赖；需要认证的 `/api/v1/operations/status` 端点为轻量发布视图提供数据。详见[部署与运维](docs/08-deployment-operations.md)和 [Week 6 验证指南](docs/12-week6-verification.md)。

## 架构

Next.js Web 应用调用 FastAPI 服务。PostgreSQL 是身份、ACL、元数据、Trace 和评测记录的权威数据源；MinIO 存储原始文件；Celery／Redis 处理摄取；Qdrant 提供稠密和稀疏候选结果，API 使用 RRF 进行融合。Agent 是一个有界 LangGraph，且只使用只读工具。详见[架构](docs/02-architecture.md)、[Agent 设计](docs/11-agent.md)、[检索](docs/10-retrieval.md)和 [API 契约](docs/04-api-tool-contracts.md)。

## 安全边界

未经书面批准，请勿提交雇主数据、内部提示词、凭据、邮件、日志或由其派生的评测案例。详见[开源边界](docs/09-open-source-boundary.md)。

本原型不宣称已经验证可承载 10,000 份文档的生产容量，也不承诺 SLA、渗透测试、安全认证或经过校准的 LLM 安全裁判。仓库中提交的测试和夹具均明确为公司无关的合成内容。
