# My Agent RAG API

基于 FastAPI 的 RAG 助教项目，目前提供基础 API 和健康检查接口，后续可扩展课程资料导入、检索、问答和权限管理。

项目业务和第一版范围见[方案草案](docs/project-proposal-v1.md)。

## 架构与面试演示

```mermaid
flowchart LR
    Upload["教师上传资料"] --> Parse["MinerU 解析"]
    Parse --> Chunk["按标题和段落切分"]
    Chunk --> DB[("SQLite 或 PostgreSQL<br/>文档、切分块、任务")]
    Chunk --> Embed["Embedding Worker"]
    Embed --> Milvus[("Milvus 向量索引")]
    User["学生或教师"] --> Scope["身份、科目、发布状态<br/>年级和单元范围"]
    Scope --> Search["混合召回与排序"]
    DB --> Search
    Milvus --> Search
    Search --> QA["意图路由与带引用回答"]
    Search --> Prep["生成双版本讲义"]
    Prep --> Review["LangGraph 暂停等待审阅"]
    Review -->|确认| Export["导出 Word 或 Markdown"]
    Review -->|拒绝后重生成| Prep
```

### 三分钟演示

准备一份已向量化且已发布的英语资料，再准备一份同年级、同单元的未发布资料。讲义演示需要启动 Milvus，并配置 Embedding 和对话模型。仓库中的九上 Unit 5 学案和教案是 Word 导出模板。演示时选择已经入库的资料范围。

| 演示 | 操作 | 可核对的结果 |
| --- | --- | --- |
| 问答与意图路由 | 学生先问「给我一点提示」，再明确要求答案 | 页面显示本次意图。提示和直接作答使用对应的回答规则 |
| RAG 授权 | 用教师和学生账号在相同范围内检索，或运行 `make test-permissions` | 学生只可访问已发布的英语资料。测试同时核对召回过滤、模型输入和引用 |
| 人工审阅与恢复 | 教师生成讲义后刷新页面，从草稿列表重新打开。拒绝并重新生成，再确认审阅与导出 | 旧稿保留为已拒绝，新稿有独立检查点。确认前导出会返回 409 |
| 越权拦截 | 运行 `make test-prep`，检查学生持有效草稿 ID 的请求 | 打开、审阅、拒绝和导出均返回 403，教师可查看拒绝审计 |

`make test-permissions` 和 `make test-prep` 使用临时 SQLite 与模拟模型。需要验证真实问答表现时，准备评测集对应资料并发布，再运行 `make eval-qa`。

## 环境配置

部署或本地运行前，先将项目根目录的 `.env.example` 复制为同目录下的 `.env`，再按实际环境修改配置值。请勿将包含真实密钥的 `.env` 提交到 Git。

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

macOS / Linux：

```bash
cp .env.example .env
```

`.env.example` 是可提交的配置模板；`.env` 用来保存本机或部署环境的实际配置，已加入 `.gitignore`。

| 变量 | 用途 | 示例默认值 |
| --- | --- | --- |
| `APP_NAME` | API 服务名称 | `My Agent RAG API` |
| `APP_VERSION` | API 版本 | `0.1.0` |
| `API_PREFIX` | API 路由前缀 | `/api/v1` |
| `HOST` | 服务监听地址 | `127.0.0.1` |
| `PORT` | 服务端口 | `8000` |
| `RELOAD` | 是否启用开发热重载 | `true` |
| `DATA_DIR` | 数据库、上传文件和解析结果目录 | `data` |
| `MINERU_EXECUTABLE` | MinerU 命令或可执行文件完整路径；留空时自动查找 | 留空 |
| `MINERU_TIER_PDF` | PDF 使用的 MinerU 档位 | `basic` |
| `MINERU_TIER_NON_PDF` | 非 PDF 文件使用的 MinerU 档位 | `flash` |
| `MINERU_TIMEOUT_SECONDS` | 单次 MinerU 解析等待时间（秒） | `3600` |
| `CHUNK_SIZE` | 切分文本块的目标长度（字符） | `800` |
| `CHUNK_OVERLAP` | 相邻文本块重复保留的长度（字符） | `100` |
| `WORKER_POLL_INTERVAL_SECONDS` | Worker 轮询任务队列的间隔（秒） | `2` |
| `OPENAI_API_KEY` | 模型服务密钥，接入模型时填写 | `your_api_key_here` |
| `CHAT_MODEL` | 对话模型名称，接入模型时填写 | `your_chat_model_here` |
| `EMBEDDING_MODEL` | 向量模型名称，接入模型时填写 | `your_embedding_model_here` |

## 本地运行

### Windows PowerShell

1. 安装 Windows 版 [PostgreSQL](https://www.postgresql.org/download/windows/)，启动 PostgreSQL 服务。使用安装器提供的 SQL Shell（psql）连接管理员账号，执行下方的建库命令。
2. 无 Docker 时，把 Milvus Standalone 部署到本机 WSL 2 的 Linux 环境，或使用已有的 Milvus 服务。选择有对应 Linux 安装包的发行版，并按 [Milvus Linux 安装包说明](https://milvus.io/docs/install_standalone-binary.md) 启动服务。WSL 2 尚未启用时，可在管理员 PowerShell 运行 `wsl --install -d Ubuntu`，按系统提示重启。
3. 从 CoursePilot 根目录执行。已有虚拟环境时可跳过创建命令。

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

完成下方的数据库配置后启动：

```powershell
.\.venv\Scripts\mineru.exe server start
.\.venv\Scripts\python.exe main.py
```

### macOS

1. 使用 [macOS PostgreSQL 安装选项](https://www.postgresql.org/download/macos/) 中的 Homebrew 方式安装并启动 PostgreSQL。执行下方的建库命令。
2. 无 Docker 时，在本机 Linux 虚拟机里部署 Milvus Standalone，或使用已有的 Milvus 服务。Linux 虚拟机的架构须和所选 Milvus 安装包匹配。从 macOS 使用虚拟机可达的 IP 或端口转发地址连接。参考 [Milvus Linux 安装包说明](https://milvus.io/docs/install_standalone-binary.md)。

```bash
brew install postgresql@17
brew services start postgresql@17
"$(brew --prefix postgresql@17)/bin/psql" -d postgres
```

退出 psql 后，从 CoursePilot 根目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
test -f .env || cp .env.example .env
```

完成下方的数据库配置后启动：

```bash
mineru server start
python main.py
```

### 数据库配置

在管理员 psql 会话中执行以下命令。`\password` 会交互式设置应用密码，`\q` 退出。

```sql
CREATE ROLE coursepilot LOGIN;
\password coursepilot
CREATE DATABASE coursepilot OWNER coursepilot;
\q
```

在项目根目录的 `.env` 设置：

```dotenv
DATABASE_URL=postgresql://coursepilot:YOUR_PASSWORD@127.0.0.1:5432/coursepilot
MILVUS_URI=http://127.0.0.1:19530
MILVUS_TOKEN=
```

将密码占位符换成实际值。密码包含 URI 保留字符时需要 URL 编码。若启用 Milvus 认证，填写 `MILVUS_TOKEN`。从宿主机连接 WSL 或 Linux 虚拟机时，按实际网络地址修改 `MILVUS_URI`。可以用下面的命令验证 Milvus REST 接口，启用认证时添加 Bearer 请求头。

```text
curl -X POST http://127.0.0.1:19530/v2/vectordb/collections/list -H "Content-Type: application/json" -d "{}"
```

Windows PowerShell 中用 `curl.exe` 运行该命令。返回 `code: 0` 表示接口可用。应用配置了 Milvus 后也会在启动时执行同样的连接检查。

PostgreSQL 的业务表由应用启动时创建。已有 SQLite 数据保留在 `data/documents.db`，配置 PostgreSQL 后应用会读取 PostgreSQL 中的记录。需要继续使用 SQLite 时将 `DATABASE_URL` 留空。上传文件和解析 Markdown 保存在 `DATA_DIR`，切分块写入当前数据库的 `document_chunks` 表。应用启动时会导入当前数据库所引用的旧切分 JSONL，并在入库后清理文件。

Milvus 客户端支持创建集合、写入已有向量和相似度搜索。集合维度由 Embedding 模型决定。配置 `EMBEDDING_BASE_URL`（通常以 `/v1` 结尾）、`EMBEDDING_MODEL`、`EMBEDDING_DIMENSION` 和 `MILVUS_URI` 后，API 启动时会同时启动向量化 Worker。服务要求鉴权时填写 `EMBEDDING_API_KEY`。向量化读取已入库的切分块，每批最多 16 块，使用稳定的块 ID 写入 Milvus。启动时也会为当前已切分、尚未向量化的文档补排任务。向量化失败后可在管理页单独重试。

启动后可访问：

- 文档管理后台：`http://127.0.0.1:8000/admin`
- 健康检查：`http://127.0.0.1:8000/api/v1/health`
- API 文档：`http://127.0.0.1:8000/docs`

文档管理目前支持 PDF、Markdown 和 DOCX 文件的新增、信息编辑、文件替换与删除，并可选择适用年级（小学一年级至六年级、初一至初三、高一至高三）和单元（第 1 至第 20 单元，支持单个单元或连续范围，例如“第1-2单元”）。文档元数据和上传文件保存在项目根目录的 `data/` 下；该目录已加入 `.gitignore`。

每次上传或重试都会保留解析任务和步骤状态；流程依次执行 MinerU 结构解析和文本切分。文档列表分别显示原文件、MinerU 解析和文本切分的状态。源文件、MinerU 日志、Markdown 解析结果保存在 `data/`。切分会尽量沿 Markdown 标题和段落边界进行，并按 `CHUNK_SIZE` 控制长度、按 `CHUNK_OVERLAP` 保留相邻块的上下文。在管理页点击“校验”后，可分别打开“MinerU 解析校验”（原始文档对照解析文本）和“文本切分校验”（解析文本对照切分块），检查各阶段的结果以及年级、单元等元数据。DOCX 源文件会转换成网页预览，支持查看文字、标题和表格；需要核对 Word 原始版式时，可点击“下载原始文件”。替换文件会开启新的解析任务；历史任务步骤记录保留在当前配置的数据库中。

## 测试与评测速查

在项目根目录运行。离线测试先安装 `requirements-dev.txt`。

| Makefile 目标 | 用途 | 运行条件 |
| --- | --- | --- |
| `make test-permissions` | 检查科目授权、召回范围和引用隔离 | 开发依赖 |
| `make test-prep` | 检查讲义自动保存、审批恢复、导出和越权拦截 | 开发依赖 |
| `make eval-validate` | 核对评测题的依据是否存在于当前切分块中 | 已导入评测资料 |
| `make eval-retrieval` | 测纯向量检索的 Top K 命中率 | 评测资料已向量化，Embedding 和 Milvus 可用 |
| `make eval-qa` | 测混合检索、意图和回答引用 | CoursePilot 已启动，评测资料已发布，对话模型可用 |
| `make eval-prep-review` | 测讲义审校能否识别错误 | 对话模型可用，会调用真实接口 |

PowerShell 没有 GNU Make 时，可直接运行对应命令：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q tests/test_qa_permissions.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_prep_workflow.py
.\.venv\Scripts\python.exe -m evals.retrieval --validate-only
.\.venv\Scripts\python.exe -m evals.retrieval --top-k 5
.\.venv\Scripts\python.exe -m evals.qa --top-k 5
.\.venv\Scripts\python.exe -m evals.prep_review
```

权限和讲义回归测试使用临时 SQLite 与模拟服务。问答和讲义审校评测的报告分别写入 `data/qa-eval.json` 和 `data/prep-review-eval.json`。检索和问答评测默认取前 5 条，可用 `TOP_K` 或 `--top-k` 调整。

## 检索评测

从项目根目录运行。评测数据位于 `evals/units_1_2.json`。数据库里需要有该 DOCX 的当前切分结果，完整评测还需要使用当前 Embedding 配置完成向量入库，并启动 Milvus。

`--validate-only` 只从数据库核对依据文本。完整评测会调用 Embedding 和 Milvus，不需要启动 CoursePilot API。输出包含每题的命中块 ID 以及完整命中题数。Q08 要求两处依据都出现在结果中。Q09 和 Q10 留给后续的回答评测。

切分调整后，脚本会用依据短语重新匹配当前块。原文或文件名发生变化时，更新对应的评测数据后先运行一次校验。对比不同检索方案时，使用同一版资料和评测题。

## 课程问答

启动 CoursePilot 后，打开 `http://127.0.0.1:8000/qa`。先在 `/admin` 上传并完成向量化，资料须标注年级和单元。问答页从已向量化的当前资料生成选项。起止单元相同表示选择单个单元，范围和资料标签有交集即可纳入检索。

问答使用已有 Embedding 和 Milvus 配置。另在 `.env` 设置 `CHAT_BASE_URL`（通常以 `/v1` 结尾）、`CHAT_MODEL` 和服务所需的 `OPENAI_API_KEY`。对话模型需要支持 JSON 对象响应。只调试检索时，可调用 `POST /api/v1/qa/search`，传入 `question`、`grade`、`unit_start`、`unit_end` 和可选的 `top_k`。

### 问答接口验收

启动 CoursePilot 后，从 `evals/units_1_2.json` 取题目。此次资料使用高一、第 1–2 单元。请求体设置 `question`、`grade`、`unit_start`、`unit_end` 和 `top_k`（建议 5），可在 `http://127.0.0.1:8000/docs` 发起请求。

- 对 Q01–Q08 调用 `POST /api/v1/qa/search`，检查返回的文本块是否包含各题的全部预期依据。Q08 需要两处依据同时命中。
- 对 Q01–Q10 调用 `POST /api/v1/qa/ask`，对照预期答案，核对引用是否支持回答。Q09 和 Q10 检查依据不足时的表现。
- `make eval-retrieval` 跑纯向量检索基线。问答接口还包含范围过滤、查询改写、关键词召回和结果融合，验收时单独记录它的结果。

自动检查包括 Top K 依据命中、回答引用是否覆盖依据，以及无依据题是否返回空引用。报告默认写到 `data/qa-eval.json`，其中的答案和引用需要人工核对。退出码为 1 表示至少有一条自动检查失败。

意图识别与检索改写共用一次模型调用。`/qa/search` 和 `/qa/ask` 返回 `intent`，便于查看路由结果。新增意图时，在 `app/rag/generation/intents.py` 的 `INTENTS` 中添加识别条件和回答规则。识别失败时使用通用问答。

可选 Jev 意图识别。在 `.env` 填写 `JEV_API_KEY` 后重启。Jev 接收用户问题和意图候选项，现有对话模型负责查询改写。Jev 请求失败或返回未知意图时，使用现有对话模型同时识别意图和改写查询。清空密钥可恢复原来的流程。通过 `/qa/search` 返回的 `intent` 对照两种配置的识别结果。

## 本地演示登录

启动项目后打开 `http://127.0.0.1:8000/login`。下拉框可选教师或学生，两个账号的密码都是 `123`。教师进入资料管理，也可以使用课程问答。学生进入课程问答，访问资料管理 API 会被拒绝。应用重启后需要重新登录。`make eval-qa` 会自动用学生账号登录。演示账号面向本机开发环境。

## 讲义工作流测试与演示

现场演示时，先启动项目并准备一份已完成向量化的资料。

1. 用教师账号登录，打开 `/prep`，选择资料对应的科目、年级和单元，点击「生成讲义」。生成后自动保存为待审阅草稿。
2. 刷新页面，从讲义草稿列表重新打开。点击「拒绝并重新生成」，观察旧稿保留为已拒绝，新稿进入待审阅。
3. 确认审阅新稿，切换学生学案和教师教案，分别导出 Markdown 或 Word。教师版带答案和引用。
4. 运行 `make test-prep`，展示学生持有真实草稿 ID 时，直接调用打开、审阅、拒绝或导出接口仍返回 HTTP 403，并由教师在工具权限审计中查到拒绝记录。

讲义保存后，LangGraph 使用草稿 ID 作为 `thread_id`，在人工审阅节点暂停。确认或拒绝时，服务先检查当前教师的科目权限，再恢复该草稿的检查点。检查点保存在 `DATA_DIR/prep-checkpoints.sqlite`，即使业务数据库配置为 PostgreSQL 也是如此。本地演示重启后重新登录，从草稿列表打开待审阅稿即可继续。拒绝后重新生成会创建新的草稿和检查点。
