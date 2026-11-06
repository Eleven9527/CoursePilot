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

先激活项目虚拟环境并安装依赖：

```powershell
.\my_agent\Scripts\Activate.ps1
pip install -r requirements.txt
```

MinerU 本地解析服务需先启动（当前配置使用本地 `basic` 档位；PDF 使用 `basic`，DOCX 使用 `flash`）：

```powershell
.\my_agent\Scripts\mineru.exe server start
.\my_agent\Scripts\mineru.exe server status
```

MinerU 程序依赖版本记录在 `requirements.txt`；模型文件与 MinerU 自身缓存位于用户目录 `C:\Users\ASUS\.mineru\`，不会放进 Git 仓库。当前已下载并验证 `basic` 模型。

启动项目（API 启动时会自动启动 SQLite 轮询 Worker）：

```powershell
python main.py
```

上传接口只将步骤写入 SQLite 队列。后台 Worker 轮询并原子领取 `queued` 步骤；MinerU 成功后才将切分步骤排队。步骤失败会将依赖步骤标记为跳过。Worker 随 API 服务启动和关闭，无需单独打开终端。

启动后可访问：

- 文档管理后台：`http://127.0.0.1:8000/admin`
- 健康检查：`http://127.0.0.1:8000/api/v1/health`
- API 文档：`http://127.0.0.1:8000/docs`

文档管理目前支持 PDF、Markdown 和 DOCX 文件的新增、信息编辑、文件替换与删除，并可选择适用年级（小学一年级至六年级、初一至初三、高一至高三）和单元（第 1 至第 20 单元，支持单个单元或连续范围，例如“第1-2单元”）。文档元数据和上传文件保存在项目根目录的 `data/` 下；该目录已加入 `.gitignore`。

每次上传或重试都会保留解析任务和步骤状态；流程依次执行 MinerU 结构解析和文本切分。文档列表会细分显示原始文件已保存、MinerU 解析中、文本切分中及对应阶段的失败状态。源文件、MinerU 日志、Markdown 解析结果及 JSONL 切分结果保存在 `data/`。切分会尽量沿 Markdown 标题和段落边界进行，并按 `CHUNK_SIZE` 控制长度、按 `CHUNK_OVERLAP` 保留相邻块的上下文。在管理页点击“校验”后，可分别打开“MinerU 解析校验”（原始文档对照解析文本）和“文本切分校验”（解析文本对照切分块），检查各阶段的结果以及年级、单元等元数据。DOCX 源文件会转换成网页预览，支持查看文字、标题和表格；需要核对 Word 原始版式时，可点击“下载原始文件”。替换文件会开启新的解析任务；历史任务步骤记录保留在 SQLite 中。
