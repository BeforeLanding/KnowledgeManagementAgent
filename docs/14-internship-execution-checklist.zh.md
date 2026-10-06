# 实习项目优化执行清单

更新日期：2026-10-06。配套[优化方案](13-internship-optimization-plan.zh.md)。
本次只新增规划文档，以下任务全部未验收。状态只在实际产物、命令结果和证据齐备后更新。
预计 46～72 小时；先执行 KM-00～KM-05，再完成工程演示与证据包。

## 1. 任务与完成判据

### KM-00 / P0 / 基线可复现 / 2～4 小时

- [ ] 确认代码 SHA、Python/Node/uv/pnpm/Docker 版本，按锁文件安装依赖。
- [ ] 定位此前全套 pytest 停滞的测试和线程栈，记录环境原因或代码修复。
- [ ] 跑完后端检查、三套 Fake Gate、Web 类型检查/构建和 Compose 配置检查。
- [ ] 在真实演示栈跑一次迁移、seed、上传和问答，记录依赖 readiness。
- [ ] 在后续报告记录执行命令、退出码、测试数、环境和未通过项。

操作模块：`pyproject.toml`、`tests/`、`.github/workflows/ci.yml`、`docker-compose.yml`。
验收：门禁完整结束，失败有解释和修复证据；停滞不能计为通过。

### KM-01 / P0 / 语料与指标 / 4～6 小时 / 依赖 KM-00

- [ ] 新建公司无关的技术知识语料及标注，40～60 文档、120 问题，固定 ID/内容 hash。
- [ ] 按来源族分组完成 dev 40 / test 80，检查同义/中英近重复未跨分组。
- [ ] 保留至少 20 个权限/注入检查，区分工程回归与真实模型攻击实验。
- [ ] 原始候选排名与最终引用分开记录，文档级指标去重，明确替代来源与必需来源。
- [ ] 加入手算指标测试，特别验证重复文档不会让 nDCG 大于 1。
- [ ] 保存语料 manifest、数据版本、类别/语言数量、标注规则与限制。

操作模块：`evaluations/`、`services/api/app/evaluation.py`、`tests/test_evaluation.py`、
`tests/test_week5_evaluation.py`。新增文件和格式在实现 PR 中确定，不能假定已有 import 命令。
验收：每个 gold 来源可定位，无答案题在非空授权知识库运行，所有数字有分母。

### KM-02 / P0 / 编码器与切块 / 8～12 小时 / 依赖 KM-01

- [ ] 为 dense 定义 query/passage 接口，保留独立 sparse 和离线 hash 默认实现。
- [ ] 用 sentence-transformers 接入 multilingual-e5-small，记录模型 revision/维度/前缀/归一化。
- [ ] 用真实 tokenizer 处理中文、英文、表格及长行，正文首选 320 tokens、overlap 64。
- [ ] 给编码器最终输入和聊天上下文分别做长度上限；保留 locator 和原文引用位置。
- [ ] 每个配置使用独立 collection/fingerprint，错配拒绝，完成演示环境重建和回滚说明。
- [ ] 进程内复用编码器、批量编码，确认首次加载、预热和内存峰值。

操作模块：`providers.py`、`parsers.py`、`ingestion.py`、`search.py`、`config.py`、
`pyproject.toml`、`uv.lock`，必要时 `models.py` 和 Alembic migration。
验收：长中文不能绕过预算，切块不发生未记录的编码器截断，模型/索引一致。

### KM-03 / P0 / 检索对照 / 4～6 小时 / 依赖 KM-02

- [ ] 实现独立 benchmark 入口，复用生产检索和 ACL，不另写一套未经对照的 RAG。
- [ ] 运行 A0/A1/A2/A3，另做同切块的 hash/真实 dense 对照，参数只用 dev 选择。
- [ ] 在真实 Qdrant 上运行固定 test，输出原始 top-k、文档去重指标和分组结果。
- [ ] 记录真实服务延迟、错误、硬件、请求数、冷暖状态；重复 3 轮。
- [ ] 分析至少 5 个失败案例，解释切块/召回/排序各自贡献。

操作模块：`search.py`、`evaluation.py`，拟新增 `scripts/benchmark_rag.py`。
验收产物：拟新增 `docs/15-retrieval-results.zh.md`，包含完整复现命令、摘要和失败样例。

### KM-04 / P0 / 证据验证 / 8～12 小时 / 依赖 KM-03

- [ ] 用 dev 校准证据决策，补“相关片段存在但不支持回答”案例。
- [ ] 生成内部结构化断言、C 编号与引文；服务端映射并验证来源白名单和原文。
- [ ] 最终响应前回查权限/生命周期，撤权时重做证据验证或拒绝，不只移除引用。
- [ ] 分开记录 schema、来源合法性、引文真实性与语义支持检查。
- [ ] 实现可验收的来源摘录模式；生成式 verifier 完成标注校准后再设门禁。
- [ ] 配置生成/验证/修复上限；草稿验证前不发答案 token，SSE 和 sync 终态一致。
- [ ] 覆盖错误编号、正确编号错误事实、引文伪造、矛盾、撤权、超时与验证失败。

操作模块：`agent.py`、`providers.py`、`schemas.py`、`evaluation.py`、`tests/test_agent.py`、
`tests/test_week6_threats.py`。需要新 verifier 时保持一个小模块，先定义输入输出与失败语义。
验收：来源摘录能确定性核验；生成式支持率由 KM-05 人工评分，未校准不得宣称零幻觉。

### KM-05 / P0 / 真实模型报告 / 4～6 小时 / 依赖 KM-04

- [ ] 独立 live 入口支持显式 provider、固定 case 清单和整批调用/token/耗时上限。
- [ ] dev 10 题检查仪器，再冻结方案；test 预选 40 题，每方案 2 次，不挑结果。
- [ ] 先固定生成模型比较检索，再固定检索比较验证；记录全部失败、重试与未完成项。
- [ ] 人工标注正确性、断言支持、拒答和完整性；verifier 校准需要双人样本。
- [ ] provider/estimated usage 分列，保留合成逐题标签、脱敏摘要和运行 hash。
- [ ] 无答案 F1 与误拒率、TTFT/总延迟、成本与样本限制分别报告。

操作模块：`providers.py`、`evaluation.py`、拟新增 `scripts/benchmark_rag.py`。
验收产物：拟新增 `docs/16-answer-quality-results.zh.md`；Fake Gate 的通过率不进入真实模型效果栏。

### KM-06 / P1 / 并发一致性 / 6～10 小时 / 依赖 KM-00、KM-02

- [ ] 先在 PostgreSQL 上复现相同文件并发上传、重复消费和索引期间删除。
- [ ] 设计唯一约束、版本分配、冲突返回和对象补偿，加入 migration。
- [ ] 设计任务 claim/lease/generation 与 ready 条件提交，验证过期任务和迟到外部写入。
- [ ] 用同步屏障做确定时序测试，验证每个 crash/删除窗口中的可见性与清理。
- [ ] 验证 broker 失败；需要时实现最小 outbox 和可恢复 dispatcher。
- [ ] 记录软删除不可见与物理清理各自的时限，保留失败时序图。

操作模块：`models.py`、`documents.py`、`routes.py`、`worker.py`、`ingestion.py`、`search.py`、
`services/api/alembic/versions/`、拟新增 `tests/integration/`。
验收：同内容 10 并发唯一可见，重复消费无重复可见 chunk，删除时序全部不可泄漏，
broker 恢复可补投。只完成顺序重跑不能勾选本项。

### KM-07 / P1 / 演示与会话 / 4～6 小时 / 依赖 KM-04

- [ ] 补 refresh/退出语义、单次共享刷新及失效返回登录，明确 Cookie 与 CSRF 设计。
- [ ] 上传状态有界轮询、失败分类、重试/删除与角色状态，离开页面停止轮询。
- [ ] 接入 SSE 状态与终态、受 ACL 保护的引用片段查看。
- [ ] 用同源 API 代理或正确的 build 参数解决浏览器 localhost 地址，验收 SSE 透传。
- [ ] 从另一台机器验证；共享部署前配置 TLS、非默认身份/密钥、禁用 seed 和登录限制。

操作模块：`security.py`、`routes.py`、`schemas.py`、`apps/web/app/page.tsx`、
`apps/web/next.config.ts`、Web Dockerfile 和 Compose。
验收：过期可恢复、三角色流程成立、上传到回答可连续演示。

### KM-08 / P1 / 真实栈 E2E 与测量 / 4～6 小时 / 依赖 KM-06、KM-07

- [ ] 新增 Playwright 和独立真实服务 integration/E2E 入口与 CI job。
- [ ] 跑通登录到上传/ready/回答/引用/删除，加入 viewer 越权、过期和失败重试。
- [ ] 从 100 文档开始测量，成功后可到 1,000；保存文档/chunk 数及环境。
- [ ] search、Fake chat、live chat 分组统计；采集索引大小、CPU/内存、ready 延迟或注明未测。
- [ ] 保存 3 轮结果和错误数，说明重复上传与压测数据清理方式。

操作模块：`apps/web/package.json`、`pnpm-lock.yaml`、拟新增 `apps/web/e2e/`、
`scripts/load_test.py`、`.github/workflows/ci.yml`。
验收产物：拟新增 `docs/17-consistency-and-demo.zh.md`，不能以微基准填充实际服务容量。

### KM-09 / 交付 / README 与面试证据 / 2～4 小时 / 依赖 KM-03、KM-05、KM-08

- [ ] README 首屏连接三份已存在且有结果的报告，写清已实现、已验证与限制。
- [ ] 准备 3 分钟演示、截图和故障片段，使用纯合成数据。
- [ ] 选择 2～3 条实测结果写入简历，每个数字能追溯到报告。
- [ ] 为检索/回答/一致性准备问题、取舍、证据、局限的面试叙述。
- [ ] 核对两项目职责互补，独立实现与依赖库/参考来源交代清楚。

操作模块：README、三份结果文档、`evaluations/reports/`。
验收：他人按命令能复现关键路径；每条简历描述有代码与结果支撑。

## 2. 现在就能执行的命令

以下入口已经存在。安装会下载依赖；Compose 会拉镜像/创建本地演示数据。
在项目根目录执行，另开终端启动服务，全部使用自己的本地演示环境。

```powershell
git rev-parse HEAD
uv --version
pnpm --version
docker version
uv sync --locked --dev
pnpm install --frozen-lockfile
uv run pytest -vv --durations=20 -o faulthandler_timeout=30
uv run ruff check .
uv run mypy services/api/app
pnpm test:web
pnpm build:web
docker compose config --quiet
uv run python scripts/evaluate.py --suite smoke
uv run python scripts/evaluate.py --suite regression
uv run python scripts/evaluate.py --suite threat
uv run python scripts/evaluate_retrieval.py
```

`faulthandler_timeout` 用于打印停滞时的线程栈，不是测试超时或自动终止功能。
如果 uv 默认缓存路径在受限环境中不可写，可先设置
`$env:UV_CACHE_DIR = Join-Path (Get-Location).Path '.uv-cache'`，或使用现有
`.venv/Scripts/python.exe -m pytest`；先确认环境依赖与锁文件一致，再解释结果。

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose up --build
```

另一个终端执行：

```powershell
Invoke-RestMethod http://localhost:8000/health/ready
uv run python scripts/load_demo.py
```

现有 Compose 压测命令示例，先小规模，非提交默认测试：

```powershell
$env:KMA_LOAD_PASSWORD = 'Admin123!'
uv run python scripts/load_test.py --mode compose --documents 100 --requests 100 --concurrency 4 --duration-seconds 600 --email admin@example.com --password-env KMA_LOAD_PASSWORD --execute --output data/experiments/compose-100.json
Remove-Item Env:KMA_LOAD_PASSWORD
```

这里使用仓库公开的本地 demo 身份；真实凭据通过私有环境注入。
重新运行前核对已上传数据：生成器 seed 相同会命中重复内容，不应把 409 当成新一轮吞吐结果。
现有脚本会混合 search/chat 请求，结果不能直接写成纯 search P95；纯检索分组采集待 KM-08 补齐。

## 3. 待实现入口的明确契约

下面是 KM-03/KM-05/KM-08 的开发目标，当前没有这些新命令或参数，不能作为现有运行指南。

拟新增 `scripts/benchmark_rag.py`，先实现以下契约再在结果文档记录最终命令：

- `--task retrieval|answer`、`--split dev|test`、`--dataset PATH`、`--case-list PATH`。
- `--profile hash|dense|sparse|hybrid`、`--provider fake|openai`、`--repeat N`、`--output PATH`。
- `--execute` 显式执行；live 模式必须指定正整数的 `--max-requests`、`--max-total-tokens`
  与 `--max-seconds`，计入 verifier、修复和 provider 重试；设置上限不是允许无穷重试。
- manifest 保存 Git SHA、模型/prompt/chunk/索引/数据版本、阈值和语言/类别分母。
- 结果保存原始候选与最终引用的独立指标、逐题标签、耗时、usage 来源、失败及未执行数。
- API key 只读环境变量，不进命令行或输出。没有 provider usage 时分列估算并注明不能硬保证 token 账单上限。
- 原始文件写入被忽略的 `data/experiments/`，检查脱敏后再发布小规模摘要。
- 退出码约定：0 为完整执行且满足已声明验收，1 为验收未达，2 为配置/运行错误，
  3 为批次上限中止；中止批次不能按完整测试集计算通过率。

拟新增 Web `test:e2e` 和真实栈集成入口。当前 `pnpm test:web` 仅 `tsc --noEmit`，
不要把尚未添加的 Playwright 命令写成已通过。默认离线 Gate 保持独立，真实模型运行显式触发。

## 4. 一次任务的提交与验收流程

1. 在 KM 编号下记录失败例、要改变的行为和受影响模块；先固定验收条件。
2. 完成一个可独立审查的改动，添加覆盖具体失败机制的测试；migration 同时验证旧数据与新建库。
3. 跑相关测试和现有必需门禁；外部依赖测试记录具体环境，不能借用模拟结果。
4. 记录 commit、命令、退出码、结果路径、分子/分母和剩余风险，再勾选对应条目。
5. 更新真实结果文档；没有数据时保持“未测”，不创建空表格或填入目标值。
6. 最后更新 README/简历，不把本清单的勾选次数当成性能指标。

提交建议：KM-02 可分 provider、tokenizer、索引版本三个改动；KM-06 可分约束与上传补偿、
任务所有权与删除保护、可选 outbox 三个改动。根据实际代码依赖安排，不要求一次大改全部合并。
