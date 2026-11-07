# My Agent RAG API

基于 FastAPI 的 RAG 助教项目，目前提供基础 API 和健康检查接口，后续可扩展课程资料导入、检索、问答和权限管理。

项目业务和第一版范围见[方案草案](docs/project-proposal-v1.md)。

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

Milvus 客户端支持创建集合、写入已有向量和相似度搜索。集合维度由 Embedding 模型决定。当前尚未接入自动生成 Embedding 的 Worker。MinerU 解析和文本切分各有一个 Worker，随 API 服务启动。

启动后可访问：

- 文档管理后台：`http://127.0.0.1:8000/admin`
- 健康检查：`http://127.0.0.1:8000/api/v1/health`
- API 文档：`http://127.0.0.1:8000/docs`

文档管理目前支持 PDF、Markdown 和 DOCX 文件的新增、信息编辑、文件替换与删除，并可选择适用年级（小学一年级至六年级、初一至初三、高一至高三）和单元（第 1 至第 20 单元，支持单个单元或连续范围，例如“第1-2单元”）。文档元数据和上传文件保存在项目根目录的 `data/` 下；该目录已加入 `.gitignore`。

每次上传或重试都会保留解析任务和步骤状态；流程依次执行 MinerU 结构解析和文本切分。文档列表分别显示原文件、MinerU 解析和文本切分的状态。源文件、MinerU 日志、Markdown 解析结果保存在 `data/`。切分会尽量沿 Markdown 标题和段落边界进行，并按 `CHUNK_SIZE` 控制长度、按 `CHUNK_OVERLAP` 保留相邻块的上下文。在管理页点击“校验”后，可分别打开“MinerU 解析校验”（原始文档对照解析文本）和“文本切分校验”（解析文本对照切分块），检查各阶段的结果以及年级、单元等元数据。DOCX 源文件会转换成网页预览，支持查看文字、标题和表格；需要核对 Word 原始版式时，可点击“下载原始文件”。替换文件会开启新的解析任务；历史任务步骤记录保留在当前配置的数据库中。
